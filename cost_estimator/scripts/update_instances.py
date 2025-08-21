# cost_estimator/scripts/update_instances.py
import os, time, json, traceback
from typing import List, Dict, Any, Iterable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from flask import Blueprint, request, jsonify

rec_bp = Blueprint("recommendations", __name__)

# =========================
# Config (env-overridable)
# =========================
TARGET_REGION_CODE      = os.getenv("TARGET_REGION_CODE", "us-east-1")         # Region to recommend/price
PRICING_ENDPOINT_REGION = os.getenv("PRICING_ENDPOINT_REGION", "us-east-1")    # Pricing API endpoint region
INSTANCE_FAMILY_FILTERS = [s.strip().lower() for s in os.getenv("INSTANCE_FAMILY_FILTERS", "").split(",") if s.strip()]  # e.g. "t" or "t,m"
MAX_CANDIDATES          = int(os.getenv("MAX_CANDIDATES", "20"))               # shortlist to price for /optimize
AWS_PROFILE_NAME        = os.getenv("AWS_PROFILE") or os.getenv("CLOUD_MIGRATION_AWS_PROFILE")
CACHE_TTL               = int(os.getenv("CACHE_TTL", str(24*60*60)))           # 24h for offerings/specs
PRICE_CACHE_TTL         = int(os.getenv("PRICE_CACHE_TTL", str(24*60*60)))     # 24h for per-type price

# regionCode -> human location
REGION_TO_LOCATION = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
}

# =========================
# Boto3 sessions/clients
# =========================
def _session():
    if AWS_PROFILE_NAME:
        return boto3.session.Session(profile_name=AWS_PROFILE_NAME)
    return boto3.session.Session()

def ec2_client(region_code: str):
    return _session().client(
        "ec2",
        region_name=region_code,
        config=Config(retries={"max_attempts": 10, "mode": "standard"})
    )

def pricing_client():
    # Pricing endpoint is only in certain regions (commonly us-east-1 or ap-south-1)
    return _session().client(
        "pricing",
        region_name=PRICING_ENDPOINT_REGION,
        config=Config(retries={"max_attempts": 10, "mode": "standard"})
    )

# =========================
# Helpers
# =========================
def _chunked(seq: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def _mib_to_gib(mib: int) -> float:
    return round(mib / 1024.0, 3)

def _matches_families(instance_type: str) -> bool:
    if not INSTANCE_FAMILY_FILTERS:
        return True
    t = instance_type.lower()
    return any(t.startswith(prefix) for prefix in INSTANCE_FAMILY_FILTERS)

# =========================
# EC2 offerings/specs
# =========================
def list_offered_instance_types(region_code: str) -> List[str]:
    """All instance types launchable in this region."""
    cli = ec2_client(region_code)
    types: List[str] = []
    paginator = cli.get_paginator("describe_instance_type_offerings")
    for page in paginator.paginate(LocationType="region", Filters=[{"Name": "location", "Values": [region_code]}]):
        for it in page.get("InstanceTypeOfferings", []):
            itype = it.get("InstanceType")
            if itype and _matches_families(itype):
                types.append(itype)
    return sorted(list(set(types)))

def describe_instance_specs(region_code: str, instance_types: List[str]) -> List[Dict[str, Any]]:
    """vCPU & memory for instance types (batch up to 100, IMPORTANT: no MaxResults when passing InstanceTypes)."""
    cli = ec2_client(region_code)
    out: List[Dict[str, Any]] = []
    for batch in _chunked(instance_types, 100):
        resp = cli.describe_instance_types(InstanceTypes=batch)  # no MaxResults
        for it in resp.get("InstanceTypes", []):
            itype = it.get("InstanceType")
            vcpus = it.get("VCpuInfo", {}).get("DefaultVCpus")
            mem_mib = it.get("MemoryInfo", {}).get("SizeInMiB")
            if not (itype and isinstance(vcpus, int) and isinstance(mem_mib, int)):
                continue
            out.append({"instance_type": itype, "vCPU": vcpus, "memory_GB": _mib_to_gib(mem_mib)})
    return out

# =========================
# Pricing helpers + cache
# =========================
_price_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}  # {region: {itype: {"price":float|None, "ts":epoch}}}

def _extract_price_from_products(price_list: List[str]) -> Optional[float]:
    """Find the minimum On-Demand USD/Hrs in a PriceList page."""
    best = None
    for product_json in price_list:
        try:
            product = json.loads(product_json)
        except Exception:
            continue

        # Guard: skip unrelated product families
        attrs = (product.get("product") or {}).get("attributes") or {}
        pfam = attrs.get("productFamily")
        if pfam not in ("Compute Instance", "Compute Instance (bare metal)", None):
            continue

        terms = product.get("terms", {}).get("OnDemand", {})
        for sku_obj in terms.values():
            if not isinstance(sku_obj, dict):
                continue
            for offer in sku_obj.values():
                if not isinstance(offer, dict):
                    continue
                dims = offer.get("priceDimensions", {})
                for dim in dims.values():
                    if not isinstance(dim, dict):
                        continue
                    if dim.get("unit") != "Hrs":
                        continue
                    usd = (dim.get("pricePerUnit") or {}).get("USD")
                    if not usd:
                        continue
                    try:
                        v = float(usd)
                        best = v if (best is None or v < best) else best
                    except Exception:
                        pass
    return best

def _best_price_via_filters(cli, filters: List[Dict[str, str]]) -> Optional[float]:
    """Iterate all pages and return the lowest On-Demand $/hr."""
    try:
        paginator = cli.get_paginator("get_products")
        best = None
        for page in paginator.paginate(ServiceCode="AmazonEC2", Filters=filters, FormatVersion="aws_v1"):
            v = _extract_price_from_products(page.get("PriceList", []))
            if v is not None:
                best = v if (best is None or v < best) else best
        return best
    except ClientError as e:
        print("Pricing get_products failed:", e)
        return None

def price_instance_type_usd_per_hr(itype: str, region_code: str) -> Optional[float]:
    """
    Robust filters + pagination:
      - Linux, Shared tenancy, capacitystatus=Used, preInstalledSw=NA, licenseModel=No License required
      - Try human location first, then regionCode
    """
    # cache check
    region_cache = _price_cache.setdefault(region_code, {})
    entry = region_cache.get(itype)
    now = time.time()
    if entry and (now - entry["ts"]) < PRICE_CACHE_TTL:
        return entry["price"]

    cli = pricing_client()
    location = REGION_TO_LOCATION.get(region_code)

    common = [
        {"Type": "TERM_MATCH", "Field": "instanceType",     "Value": itype},
        {"Type": "TERM_MATCH", "Field": "operatingSystem",  "Value": "Linux"},
        {"Type": "TERM_MATCH", "Field": "tenancy",          "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "capacitystatus",   "Value": "Used"},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw",   "Value": "NA"},
        {"Type": "TERM_MATCH", "Field": "licenseModel",     "Value": "No License required"},
        {"Type": "TERM_MATCH", "Field": "productFamily",    "Value": "Compute Instance"},
    ]

    price = None

    if location:
        f1 = common + [{"Type": "TERM_MATCH", "Field": "location", "Value": location}]
        price = _best_price_via_filters(cli, f1)

    if price is None:
        f2 = common + [{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region_code}]
        price = _best_price_via_filters(cli, f2)

    region_cache[itype] = {"price": price, "ts": now}
    return price

def prices_for_types(instance_types: List[str], region_code: str) -> List[Dict[str, Any]]:
    """[{instance_type, price_per_hour}] for given names (order preserved), parallelized for speed."""
    # Deduplicate preserving order
    seen = set()
    ordered = [it for it in instance_types if isinstance(it, str) and not (it in seen or seen.add(it))]

    results: Dict[str, Optional[float]] = {}
    max_workers = min(16, max(1, len(ordered)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {ex.submit(price_instance_type_usd_per_hr, it, region_code): it for it in ordered}
        for fut in as_completed(future_map):
            it = future_map[fut]
            try:
                results[it] = fut.result()
            except Exception:
                results[it] = None

    return [{"instance_type": it, "price_per_hour": results.get(it)} for it in ordered]

# =========================
# Cache for offerings/specs list (used by /debug/eligibles and /optimize)
# =========================
_pricing_cache: Dict[str, Any] = {"ts": 0, "region": None, "rows": None}

def _ensure_specs_cache(region_code: str):
    """Warm or reuse the offerings/specs cache."""
    global _pricing_cache
    now = time.time()
    if (
        _pricing_cache["rows"] is not None
        and _pricing_cache["region"] == region_code
        and (now - _pricing_cache["ts"]) < CACHE_TTL
    ):
        return
    offered = list_offered_instance_types(region_code)
    if not offered:
        raise RuntimeError(f"No EC2 instance type offerings in {region_code}")
    specs = describe_instance_specs(region_code, offered)
    _pricing_cache["rows"] = specs
    _pricing_cache["region"] = region_code
    _pricing_cache["ts"] = now

def _eligible_specs(req_cpu: int, req_ram_gb: float) -> List[Dict[str, Any]]:
    rows = [r for r in _pricing_cache["rows"] if r["vCPU"] >= req_cpu and r["memory_GB"] >= req_ram_gb]
    rows.sort(key=lambda r: (r["vCPU"], r["memory_GB"]))
    return rows

# Public warm function called by app.py
def warm_rec_cache():
    print("Warming EC2 offerings/specs cache...")
    offered = list_offered_instance_types(TARGET_REGION_CODE)
    _pricing_cache["rows"] = describe_instance_specs(TARGET_REGION_CODE, offered)
    _pricing_cache["region"] = TARGET_REGION_CODE
    _pricing_cache["ts"] = time.time()
    print("Cache warm complete. Types cached:", len(_pricing_cache["rows"]))

# =========================
# Routes (Blueprint)
# =========================
@rec_bp.route("/debug/eligibles")
def debug_eligibles():
    try:
        req_cpu = int(request.args.get("cpu", "1"))
        req_ram = float(request.args.get("ram", "1"))
        _ensure_specs_cache(TARGET_REGION_CODE)
        rows = _eligible_specs(req_cpu, req_ram)
        return jsonify({"region": TARGET_REGION_CODE, "eligible_count": len(rows), "first_20": rows[:20]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@rec_bp.route("/price_instances", methods=["POST"])
def price_instances():
    try:
        body = request.get_json(force=True, silent=True) or {}
        types = body.get("instance_types", [])
        if not isinstance(types, list) or not types:
            return jsonify({"error": "Provide JSON {\"instance_types\": [\"t3.micro\", ...]}"}), 400
        region_code = request.args.get("region", TARGET_REGION_CODE)
        priced = prices_for_types(types, region_code)
        return jsonify({"region": region_code, "count": len(priced), "rows": priced})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@rec_bp.route("/debug/pricing_raw")
def debug_pricing_raw():
    itype = request.args.get("type")
    region_code = request.args.get("region", TARGET_REGION_CODE)
    if not itype:
        return jsonify({"error": "Add ?type=t3.micro"}), 400

    cli = pricing_client()
    location = REGION_TO_LOCATION.get(region_code)

    def count(filters):
        total = 0
        paginator = cli.get_paginator("get_products")
        for page in paginator.paginate(ServiceCode="AmazonEC2", Filters=filters, FormatVersion="aws_v1"):
            total += len(page.get("PriceList", []))
        return total

    common_min = [
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": itype},
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
    ]

    results = {}
    if location:
        f1 = common_min + [{"Type": "TERM_MATCH", "Field": "location", "Value": location}]
        results["location_count"] = count(f1)
        results["location_price"] = _best_price_via_filters(cli, f1)

    f2 = common_min + [{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region_code}]
    results["regionCode_count"] = count(f2)
    results["regionCode_price"] = _best_price_via_filters(cli, f2)

    return jsonify({"region": region_code, "type": itype, **results})

@rec_bp.route("/optimize", methods=["POST"])
def optimize():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid or missing JSON body"}), 400
        req_cpu = int(data.get("cpu_cores", 1))
        req_ram = float(data.get("ram_gb", 1))
        _ensure_specs_cache(TARGET_REGION_CODE)

        rows = _eligible_specs(req_cpu, req_ram)[:max(1, MAX_CANDIDATES)]
        priced = []
        for r in rows:
            p = price_instance_type_usd_per_hr(r["instance_type"], TARGET_REGION_CODE)
            if p is not None:
                priced.append({**r, "price_per_hour": p})
        if not priced:
            return jsonify({"error": "No instances meet the requirements in this region"}), 404
        best = min(priced, key=lambda r: r["price_per_hour"])
        return jsonify(best)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Unhandled server error", "details": str(e), "type": e.__class__.__name__}), 500

@rec_bp.route("/recommend_with_prices", methods=["GET"])
def recommend_with_prices():
    try:
        req_cpu = int(request.args.get("cpu", "1"))
        req_ram = float(request.args.get("ram", "1"))
        region = request.args.get("region", TARGET_REGION_CODE)
        _ensure_specs_cache(region)
        rows = _eligible_specs(req_cpu, req_ram)[:max(1, MAX_CANDIDATES)]
        types = [r["instance_type"] for r in rows]
        priced = prices_for_types(types, region)
        price_map = {p["instance_type"]: p["price_per_hour"] for p in priced}
        for r in rows:
            r["price_per_hour"] = price_map.get(r["instance_type"])
        return jsonify({"region": region, "count": len(rows), "rows": rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@rec_bp.route("/generate-iac", methods=["POST"])
def generate_iac():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify({"message": "IaC code generation feature coming soon!", "input_received": data})
