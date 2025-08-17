# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import os, time, json, traceback
from typing import List, Dict, Any, Iterable, Optional

import boto3
from botocore.config import Config

import numpy as np
import joblib

app = Flask(__name__)
CORS(app)

# =========================
# Config (env-overridable)
# =========================
TARGET_REGION_CODE      = os.getenv("TARGET_REGION_CODE", "us-east-1")         # Region you want to recommend for
PRICING_ENDPOINT_REGION = os.getenv("PRICING_ENDPOINT_REGION", "ap-south-1")   # Pricing API endpoint (ap-south-1 or us-east-1)
INSTANCE_FAMILY_FILTERS = [s.strip().lower() for s in os.getenv("INSTANCE_FAMILY_FILTERS", "").split(",") if s.strip()]  # e.g. "t" or "t,m"
MAX_CANDIDATES          = int(os.getenv("MAX_CANDIDATES", "20"))               # shortlist to price
AWS_PROFILE_NAME        = os.getenv("AWS_PROFILE") or os.getenv("CLOUD_MIGRATION_AWS_PROFILE")
CACHE_TTL               = int(os.getenv("CACHE_TTL", str(24*60*60)))           # 24h

# regionCode -> human location (same region; not cross-region)
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
# Optional ML model
# =========================
try:
    model = joblib.load('model/cost_model.pkl')
    print("Model loaded successfully.")
except Exception as e:
    print("Failed to load model:", e)
    model = None

# =========================
# Boto3 sessions/clients
# =========================
def _session():
    if AWS_PROFILE_NAME:
        return boto3.session.Session(profile_name=AWS_PROFILE_NAME)
    return boto3.session.Session()

def ec2_client(region_code: str):
    return _session().client("ec2", region_name=region_code, config=Config(retries={"max_attempts": 10, "mode": "standard"}))

def pricing_client():
    return _session().client("pricing", region_name=PRICING_ENDPOINT_REGION, config=Config(retries={"max_attempts": 10, "mode": "standard"}))

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
# EC2: What’s actually offered in region
# =========================
def list_offered_instance_types(region_code: str) -> List[str]:
    """DescribeInstanceTypeOfferings → all instance types launchable in this region."""
    cli = ec2_client(region_code)
    types: List[str] = []
    paginator = cli.get_paginator("describe_instance_type_offerings")
    for page in paginator.paginate(LocationType="region", Filters=[{"Name": "location", "Values": [region_code]}]):
        for it in page.get("InstanceTypeOfferings", []):
            itype = it.get("InstanceType")
            if itype and _matches_families(itype):
                types.append(itype)
    return sorted(list(set(types)))

# =========================
# EC2: Specs (vCPU & MiB) for those types
# =========================
def describe_instance_specs(region_code: str, instance_types: List[str]) -> List[Dict[str, Any]]:
    """
    DescribeInstanceTypes with an explicit list (<=100 per call).
    NOTE: Do NOT pass MaxResults/NextToken with InstanceTypes (invalid combo).
    """
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
# Pricing helpers
# =========================
def _extract_price_from_products(price_list: List[str]) -> Optional[float]:
    """Parse PriceList array of JSON strings to find On-Demand USD / Hrs price (min across dims)."""
    best = None
    for product_json in price_list:
        try:
            product = json.loads(product_json)
        except Exception:
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
                    usd = dim.get("pricePerUnit", {}).get("USD")
                    if not usd:
                        continue
                    try:
                        v = float(usd)
                        best = v if (best is None or v < best) else best
                    except Exception:
                        pass
    return best

def price_instance_type_usd_per_hr(itype: str, region_code: str) -> Optional[float]:
    """
    Price one instanceType with reliable, single-region filters.
    Try LOCATION first, then REGIONCODE, then add capacitystatus as last fallback.
    """
    cli = pricing_client()
    location = REGION_TO_LOCATION.get(region_code)

    # Common filters (no capacitystatus initially; it can drop rows for some catalogs)
    common = [
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
        {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": itype},
    ]

    # 1) LOCATION (most reliable)
    if location:
        f1 = common + [{"Type": "TERM_MATCH", "Field": "location", "Value": location}]
        resp = cli.get_products(ServiceCode="AmazonEC2", Filters=f1, FormatVersion="aws_v1", MaxResults=100)
        price = _extract_price_from_products(resp.get("PriceList", []))
        if price is not None:
            return price

    # 2) REGIONCODE
    f2 = common + [{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region_code}]
    resp = cli.get_products(ServiceCode="AmazonEC2", Filters=f2, FormatVersion="aws_v1", MaxResults=100)
    price = _extract_price_from_products(resp.get("PriceList", []))
    if price is not None:
        return price

    # 3) LOCATION + capacitystatus=Used (last fallback)
    if location:
        f3 = f1 + [{"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"}]
        resp = cli.get_products(ServiceCode="AmazonEC2", Filters=f3, FormatVersion="aws_v1", MaxResults=100)
        price = _extract_price_from_products(resp.get("PriceList", []))
        if price is not None:
            return price

    # 4) REGIONCODE + capacitystatus=Used (last fallback)
    f4 = f2 + [{"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"}]
    resp = cli.get_products(ServiceCode="AmazonEC2", Filters=f4, FormatVersion="aws_v1", MaxResults=100)
    price = _extract_price_from_products(resp.get("PriceList", []))
    if price is not None:
        return price

    return None

# =========================
# Cache for offerings/specs (per region)
# =========================
_pricing_cache: Dict[str, Any] = {"ts": 0, "region": None, "rows": None}

def _get_pricing_rows(region_code: str, req_cpu: int, req_ram_gb: float) -> List[Dict[str, Any]]:
    """
    Build shortlist:
      1) offerings (launchable types)
      2) specs (vcpu/mem) -> keep >= requested
      3) sort by (vCPU asc, mem asc), then price top N
    Return list of {instance_type, vCPU, memory_GB, price_per_hour}
    """
    global _pricing_cache
    now = time.time()
    have_cache = (
        _pricing_cache["rows"] is not None
        and _pricing_cache["region"] == region_code
        and (now - _pricing_cache["ts"]) < CACHE_TTL
    )

    if not have_cache:
        offered = list_offered_instance_types(region_code)
        if not offered:
            raise RuntimeError(f"No EC2 instance type offerings in {region_code}")
        specs = describe_instance_specs(region_code, offered)
        _pricing_cache["rows"] = specs          # cache unfiltered specs for TTL
        _pricing_cache["region"] = region_code
        _pricing_cache["ts"] = now
    else:
        specs = _pricing_cache["rows"]

    eligible = [r for r in specs if r["vCPU"] >= req_cpu and r["memory_GB"] >= req_ram_gb]
    if not eligible:
        return []

    eligible.sort(key=lambda r: (r["vCPU"], r["memory_GB"]))  # smallest that fits
    shortlist = eligible[:max(1, MAX_CANDIDATES)]

    results = []
    for row in shortlist:
        p = price_instance_type_usd_per_hr(row["instance_type"], region_code)
        if p is None:
            continue
        results.append({**row, "price_per_hour": p})

    return results

# =========================
# Routes
# =========================
@app.route("/")
def home():
    return "Cloud Migration Cost Estimator API is running."

@app.route("/health")
def health():
    return jsonify({"ok": True})

# quick debug to see eligibles (no prices)
@app.route("/debug/eligibles")
def debug_eligibles():
    try:
        req_cpu = int(request.args.get("cpu", "1"))
        req_ram = float(request.args.get("ram", "1"))
        # ensure cache built
        _ = _get_pricing_rows(TARGET_REGION_CODE, 1, 0.5)  # warm if needed
        # pull from cache directly to list eligibles
        rows = [r for r in _pricing_cache["rows"] if r["vCPU"] >= req_cpu and r["memory_GB"] >= req_ram]
        rows.sort(key=lambda r: (r["vCPU"], r["memory_GB"]))
        return jsonify({"region": TARGET_REGION_CODE, "eligible_count": len(rows), "first_20": rows[:20]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/predict", methods=["POST"])
def predict():
    if not model:
        return jsonify({"error": "Model not loaded"}), 500

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    try:
        features = np.array([
            data["cpu_cores"],
            data["ram_gb"],
            data["storage_gb"],
            data["transfer_gb"],
            data["labor_hours"]
        ]).reshape(1, -1)
    except KeyError as e:
        return jsonify({"error": f"Missing input field: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Invalid input data: {str(e)}"}), 400

    try:
        prediction = float(model.predict(features)[0])
    except Exception as e:
        return jsonify({"error": f"Model prediction failed: {str(e)}"}), 500

    return jsonify({"estimated_cost": round(prediction, 2)})

@app.route("/optimize", methods=["POST"])
def optimize():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid or missing JSON body"}), 400

        try:
            req_cpu = int(data.get("cpu_cores", 1))
            req_ram = float(data.get("ram_gb", 1))
        except Exception as e:
            return jsonify({"error": f"Invalid cpu_cores or ram_gb: {str(e)}"}), 400

        try:
            priced = _get_pricing_rows(TARGET_REGION_CODE, req_cpu, req_ram)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": "Failed to build pricing shortlist", "details": str(e), "type": e.__class__.__name__}), 500

        if not priced:
            # help message: show a couple eligibles from debug endpoint idea
            # (don’t price here—just hint what was eligible)
            try:
                rows = [r for r in _pricing_cache["rows"] if r["vCPU"] >= req_cpu and r["memory_GB"] >= req_ram]
                rows.sort(key=lambda r: (r["vCPU"], r["memory_GB"]))
                sample = rows[:5]
            except Exception:
                sample = []
            return jsonify({"error": "No instances meet the requirements in this region", "eligible_sample": sample}), 404

        best = min(priced, key=lambda r: r["price_per_hour"])
        return jsonify(best)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Unhandled server error", "details": str(e), "type": e.__class__.__name__}), 500

@app.route("/generate-iac", methods=["POST"])
def generate_iac():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify({"message": "IaC code generation feature coming soon!", "input_received": data})

# =========================
# Startup
# =========================
if __name__ == "__main__":
    # Pre-warm offerings/specs cache (pricing happens per shortlist later)
    try:
        print("Warming EC2 offerings/specs cache...")
        _ = _get_pricing_rows(TARGET_REGION_CODE, 1, 0.5)
        print("Cache warm complete.")
    except Exception as e:
        print("Warm-up skipped:", e)

    # Make sure creds are visible:
    #   export AWS_PROFILE=cloud-migration-tool
    # Optional: narrow families for speed:
    #   export INSTANCE_FAMILY_FILTERS="t"
    app.run(host="0.0.0.0", port=5000, debug=True)
