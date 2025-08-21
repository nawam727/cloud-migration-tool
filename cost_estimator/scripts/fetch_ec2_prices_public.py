#!/usr/bin/env python3
"""
Builds a local snapshot of EC2 On-Demand Linux (Shared) prices for 1+ regions
using AWS's public offer files (no IAM needed).
Writes: cost_estimator/data/pricing/ec2_prices_<region>.json
"""
import argparse, json, os, sys, time
from pathlib import Path
import requests

BASE = "https://pricing.us-east-1.amazonaws.com"
REGION_INDEX_URL = f"{BASE}/offers/v1.0/aws/AmazonEC2/current/region_index.json"

# Where to write snapshots (relative to this script)
PRICE_DIR = Path(__file__).resolve().parents[1] / "data" / "pricing"
PRICE_DIR.mkdir(parents=True, exist_ok=True)

def region_offer_url(region_code: str) -> str:
    r = requests.get(REGION_INDEX_URL, timeout=60)
    r.raise_for_status()
    regions = r.json()["regions"]
    if region_code not in regions:
        raise SystemExit(f"Unknown region in AWS price index: {region_code}")
    # region entry -> currentVersionUrl (e.g., /offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json)
    rel = regions[region_code]["currentVersionUrl"]
    return f"{BASE}{rel}"

def build_snapshot(region_code: str) -> dict:
    url = region_offer_url(region_code)
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    j = r.json()

    products = j.get("products", {})
    terms = j.get("terms", {}).get("OnDemand", {})

    prices = {}

    # Walk products -> keep Compute Instance, Linux, Shared, NA
    for sku, prod in products.items():
        attrs = prod.get("attributes", {})
        if attrs.get("productFamily") not in ("Compute Instance", "Compute Instance (bare metal)"):
            continue
        if attrs.get("operatingSystem") != "Linux":
            continue
        if attrs.get("tenancy") != "Shared":
            continue
        if attrs.get("preInstalledSw") != "NA":
            continue
        itype = attrs.get("instanceType")
        if not itype:
            continue

        # Find the cheapest $/Hr across dimensions of this SKU
        ond = terms.get(sku, {})
        best = None
        for offer in ond.values():
            dims = offer.get("priceDimensions", {})
            for dim in dims.values():
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
        if best is not None:
            # Keep minimum across SKUs that map to the same instanceType
            if (itype not in prices) or (best < prices[itype]):
                prices[itype] = best

    snapshot = {
        "region": region_code,
        "updated": int(time.time()),
        "count": len(prices),
        "prices": prices,
        "source_url": url,
        "note": "On-Demand Linux, Shared tenancy, preInstalledSw=NA",
    }
    return snapshot

def write_snapshot(region_code: str, snap: dict):
    out = PRICE_DIR / f"ec2_prices_{region_code}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("regions", nargs="+", help="Region codes (e.g., us-east-1 ap-south-1)")
    args = ap.parse_args()
    for region in args.regions:
        snap = build_snapshot(region)
        path = write_snapshot(region, snap)
        print(f"✅ wrote {path}  (count={snap['count']})")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print("HTTP error:", e, file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)
