# cost_estimator/scripts/update_instances.py
import os
import time
import json
import traceback
from typing import List, Dict, Any, Iterable
from pathlib import Path

import requests
import boto3
from botocore.config import Config
from flask import Blueprint, request, jsonify

rec_bp = Blueprint("recommendations", __name__)

# =========================
# Config
# =========================
TARGET_REGION_CODE = os.getenv("TARGET_REGION_CODE", "us-east-1")
INSTANCE_FAMILY_FILTERS = [
    s.strip().lower()
    for s in os.getenv("INSTANCE_FAMILY_FILTERS", "").split(",")
    if s.strip()
]
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "20"))
AWS_PROFILE_NAME = os.getenv("AWS_PROFILE") or os.getenv("CLOUD_MIGRATION_AWS_PROFILE")
CACHE_TTL = int(os.getenv("CACHE_TTL", str(24 * 60 * 60)))

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PRICE_DIR = DATA_DIR / "pricing"
PRICE_DIR.mkdir(parents=True, exist_ok=True)

# Public AWS offer endpoints (no IAM/credentials needed)
OFFER_BASE = "https://pricing.us-east-1.amazonaws.com"
REGION_INDEX = f"{OFFER_BASE}/offers/v1.0/aws/AmazonEC2/current/region_index.json"

# =========================
# EC2 specs (unchanged)
# =========================
def _session():
    if AWS_PROFILE_NAME:
        return boto3.session.Session(profile_name=AWS_PROFILE_NAME)
    return boto3.session.Session()

def ec2_client(region_code: str):
    return _session().client(
        "ec2",
        region_name=region_code,
        config=Config(retries={"max_attempts": 10, "mode": "standard"}),
    )

def _chunked(seq: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]

def _mib_to_gib(mib: int) -> float:
    return round(mib / 1024.0, 3)

def _matches_families(instance_type: str) -> bool:
    if not INSTANCE_FAMILY_FILTERS:
        return True
    t = instance_type.lower()
    return any(t.startswith(prefix) for prefix in INSTANCE_FAMILY_FILTERS)

_specs_cache: Dict[str, Any] = {"ts": 0, "region": None, "rows": None}

def list_offered_instance_types(region_code: str) -> List[str]:
    cli = ec2_client(region_code)
    types: List[str] = []
    paginator = cli.get_paginator("describe_instance_type_offerings")
    for page in paginator.paginate(
        LocationType="region", Filters=[{"Name": "location", "Values": [region_code]}]
    ):
        for it in page.get("InstanceTypeOfferings", []):
            itype = it.get("InstanceType")
            if itype and _matches_families(itype):
                types.append(itype)
    return sorted(list(set(types)))

def describe_instance_specs(
    region_code: str, instance_types: List[str]
) -> List[Dict[str, Any]]:
    cli = ec2_client(region_code)
    out: List[Dict[str, Any]] = []
    for batch in _chunked(instance_types, 100):
        resp = cli.describe_instance_types(InstanceTypes=batch)
        for it in resp.get("InstanceTypes", []):
            itype = it.get("InstanceType")
            vcpus = it.get("VCpuInfo", {}).get("DefaultVCpus")
            mem_mib = it.get("MemoryInfo", {}).get("SizeInMiB")
            if not (itype and isinstance(vcpus, int) and isinstance(mem_mib, int)):
                continue
            out.append(
                {"instance_type": itype, "vCPU": vcpus, "memory_GB": _mib_to_gib(mem_mib)}
            )
    return out

def _ensure_specs_cache(region_code: str):
    now = time.time()
    if (
        _specs_cache["rows"] is not None
        and _specs_cache["region"] == region_code
        and (now - _specs_cache["ts"]) < CACHE_TTL
    ):
        return
    offered = list_offered_instance_types(region_code)
    if not offered:
        raise RuntimeError(f"No EC2 instance type offerings in {region_code}")
    specs = describe_instance_specs(region_code, offered)
    _specs_cache["rows"] = specs
    _specs_cache["region"] = region_code
    _specs_cache["ts"] = now

def _eligible_specs(req_cpu: int, req_ram_gb: float) -> List[Dict[str, Any]]:
    rows = [
        r for r in _specs_cache["rows"]
        if r["vCPU"] >= req_cpu and r["memory_GB"] >= req_ram_gb
    ]
    rows.sort(key=lambda r: (r["vCPU"], r["memory_GB"]))
    return rows

# =========================
# Pricing snapshot (public offers)
# =========================
def _price_file(region: str) -> Path:
    return PRICE_DIR / f"ec2_prices_{region}.json"

def _region_offer_url(region: str) -> str:
    r = requests.get(REGION_INDEX, timeout=60)
    r.raise_for_status()
    rel = r.json()["regions"][region]["currentVersionUrl"]
    return f"{OFFER_BASE}{rel}"

def _is_boxusage_dimension(desc: str) -> bool:
    """True only for On-Demand instance-hours (not hosts, not add-ons)."""
    if not desc:
        return False
    d = desc.lower()
    allow = ("on demand", "boxusage", "instance-hour", "instance hours", "instance-hours")
    deny  = ("dedicated host", "per host", "host reservation", "reserved instance",
             "upfront", "prepay", "cpu credits", "ebs", "io", "provisioned iops")
    if not any(k in d for k in allow):
        return False
    if any(k in d for k in deny):
        return False
    return True

def _build_price_map_public(region: str) -> Dict[str, float]:
    """
    Build {instanceType: price_per_hour} for On-Demand Linux, Shared tenancy.
    Filters strictly to BoxUsage (instance-hour) dimensions and ignores $0 add-ons.
    """
    url = _region_offer_url(region)
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    offer = r.json()
    products = offer.get("products", {})
    terms_all = (offer.get("terms") or {}).get("OnDemand", {})

    prices: Dict[str, float] = {}
    for sku, prod in products.items():
        attrs = (prod or {}).get("attributes") or {}
        fam = attrs.get("productFamily", "")
        if "Compute Instance" not in fam:  # includes bare metal
            continue
        if attrs.get("operatingSystem") != "Linux":
            continue
        tenancy = attrs.get("tenancy") or "Shared"
        if tenancy != "Shared":
            continue
        # preInstalledSw may be missing; only skip if clearly not NA-like
        pis = (attrs.get("preInstalledSw") or "").upper()
        if pis and pis not in ("NA", "NONE", "N/A"):
            continue
        itype = attrs.get("instanceType")
        if not itype:
            continue

        # Cheapest BoxUsage $/Hr across dimensions for this SKU
        best = None
        for term in (terms_all.get(sku) or {}).values():
            for dim in (term.get("priceDimensions") or {}).values():
                if not isinstance(dim, dict):
                    continue
                if dim.get("unit") != "Hrs":
                    continue
                if not _is_boxusage_dimension(dim.get("description") or ""):
                    continue
                usd = (dim.get("pricePerUnit") or {}).get("USD")
                if not usd:
                    continue
                try:
                    v = float(usd)
                except Exception:
                    continue
                if v <= 0:
                    # ignore $0 dimensions like CPU credits, metadata, etc.
                    continue
                best = v if (best is None or v < best) else best

        if best is None:
            continue

        # Keep minimum across SKUs mapping to same instanceType
        if (itype not in prices) or (best < prices[itype]):
            prices[itype] = best

    # Last-resort relax: if nothing captured, at least keep Linux regardless of family/tenancy quirks
    if not prices:
        for sku, prod in products.items():
            attrs = (prod or {}).get("attributes") or {}
            if attrs.get("operatingSystem") != "Linux":
                continue
            itype = attrs.get("instanceType")
            if not itype:
                continue
            best = None
            for term in (terms_all.get(sku) or {}).values():
                for dim in (term.get("priceDimensions") or {}).values():
                    if not isinstance(dim, dict) or dim.get("unit") != "Hrs":
                        continue
                    usd = (dim.get("pricePerUnit") or {}).get("USD")
                    if not usd:
                        continue
                    try:
                        v = float(usd)
                    except Exception:
                        continue
                    if v <= 0:
                        continue
                    best = v if (best is None or v < best) else best
            if best is not None and ((itype not in prices) or (best < prices[itype])):
                prices[itype] = best

    # Write trimmed snapshot
    pf = _price_file(region)
    tmp = pf.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {
                "region": region,
                "updated": int(time.time()),
                "count": len(prices),
                "prices": prices,
                "source_url": url,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp.replace(pf)
    return prices

def _ensure_price_file(region: str) -> Dict[str, float]:
    pf = _price_file(region)
    if pf.exists():
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            prices = data.get("prices") or {}
            # only reuse if non-empty and no zeros
            if isinstance(prices, dict) and prices and not _has_zero_entries(prices):
                return prices
        except Exception:
            pass
    # Build (or rebuild) from public offers
    return _build_price_map_public(region)

def _load_price_map(region: str) -> Dict[str, float]:
    prices = _ensure_price_file(region)
    if not prices:
        raise RuntimeError(f"No prices available for {region}.")
    return prices

def prices_for_types(instance_types: List[str], region: str) -> List[Dict[str, Any]]:
    seen = set()
    ordered = [it for it in instance_types if isinstance(it, str) and not (it in seen or seen.add(it))]
    price_map = _load_price_map(region)
    return [{"instance_type": it, "price_per_hour": price_map.get(it)} for it in ordered]

# =========================
# Warm on startup
# =========================
def warm_rec_cache():
    print("Warming EC2 offerings/specs cache...")
    offered = list_offered_instance_types(TARGET_REGION_CODE)
    _specs_cache["rows"] = describe_instance_specs(TARGET_REGION_CODE, offered)
    _specs_cache["region"] = TARGET_REGION_CODE
    _specs_cache["ts"] = time.time()
    print("Cache warm complete. Types cached:", len(_specs_cache["rows"]))

    # Ensure a valid price file exists
    try:
        prices = _ensure_price_file(TARGET_REGION_CODE)
        print(f"Price file ready for {TARGET_REGION_CODE}: {len(prices)} entries at {_price_file(TARGET_REGION_CODE)}")
    except Exception as e:
        print("WARN: could not prepare price file:", e)

# put this near the other helpers
def _has_zero_entries(prices: Dict[str, float]) -> bool:
    # any 0 or negative value is considered invalid for On-Demand instance-hours
    for v in prices.values():
        try:
            if float(v) <= 0.0:
                return True
        except Exception:
            return True
    return False



# =========================
# Routes
# =========================
@rec_bp.route("/prices/status")
def prices_status():
    region = request.args.get("region", TARGET_REGION_CODE)
    pf = _price_file(region)
    meta = None
    if pf.exists():
        try:
            meta = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            meta = None
    return jsonify({
        "region": region,
        "path": str(pf),
        "exists": pf.exists(),
        "count": (meta or {}).get("count"),
        "updated": (meta or {}).get("updated"),
    })

@rec_bp.route("/prices/refresh", methods=["POST"])
def prices_refresh():
    region = request.args.get("region", TARGET_REGION_CODE)
    try:
        prices = _build_price_map_public(region)
        return jsonify({"ok": True, "region": region, "count": len(prices)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

@rec_bp.route("/debug/eligibles")
def debug_eligibles():
    try:
        req_cpu = int(request.args.get("cpu", "1"))
        req_ram = float(request.args.get("ram", "1"))
        region = request.args.get("region", TARGET_REGION_CODE)
        _ensure_specs_cache(region)
        rows = _eligible_specs(req_cpu, req_ram)
        return jsonify({"region": region, "eligible_count": len(rows), "first_20": rows[:20]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@rec_bp.route("/optimize", methods=["POST"])
def optimize():
    """Return single cheapest eligible instance (Linux On-Demand) using the local price map."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        req_cpu = int(data.get("cpu_cores", 1))
        req_ram = float(data.get("ram_gb", 1))
        region = data.get("region", TARGET_REGION_CODE)

        _ensure_specs_cache(region)
        # shortlist (same MAX_CANDIDATES logic you already use)
        rows = _eligible_specs(req_cpu, req_ram)[:max(1, MAX_CANDIDATES)]
        if not rows:
            return jsonify({"error": "No instances meet the requirements in this region"}), 404

        # price them from the snapshot
        names = [r["instance_type"] for r in rows]
        price_list = prices_for_types(names, region)
        pmap = {p["instance_type"]: p["price_per_hour"] for p in price_list}

        priced = [{**r, "price_per_hour": pmap.get(r["instance_type"])} for r in rows]
        # pick lowest positive (or lowest non-null if all zeros/None)
        valid = [r for r in priced if r["price_per_hour"] not in (None, 0)]
        best = min(valid, key=lambda r: r["price_per_hour"]) if valid else min(
            priced, key=lambda r: (float("inf") if r["price_per_hour"] in (None, 0) else r["price_per_hour"])
        )
        return jsonify(best)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Unhandled server error", "details": str(e)}), 500

@rec_bp.route("/recommend_with_prices")
def recommend_with_prices():
    try:
        req_cpu = int(request.args.get("cpu", "1"))
        req_ram = float(request.args.get("ram", "1"))
        region = request.args.get("region", TARGET_REGION_CODE)

        _ensure_specs_cache(region)
        rows = _eligible_specs(req_cpu, req_ram)[: max(1, MAX_CANDIDATES)]

        types = [r["instance_type"] for r in rows]
        priced = prices_for_types(types, region)
        pmap = {p["instance_type"]: p["price_per_hour"] for p in priced}
        for r in rows:
            r["price_per_hour"] = pmap.get(r["instance_type"])

        return jsonify({"region": region, "count": len(rows), "rows": rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@rec_bp.route("/price_instances", methods=["POST"])
def price_instances():
    try:
        body = request.get_json(force=True, silent=True) or {}
        types = body.get("instance_types", [])
        if not isinstance(types, list) or not types:
            return jsonify({"error": 'Provide JSON {"instance_types": ["t3.micro", ...]}'}
                           ), 400
        region = request.args.get("region", TARGET_REGION_CODE)
        rows = prices_for_types(types, region)
        return jsonify({"region": region, "count": len(rows), "rows": rows})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
