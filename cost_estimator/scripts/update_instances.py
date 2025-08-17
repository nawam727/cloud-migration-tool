"""
Script: update_instances.py
- Downloads the ec2instances.info raw JSON (small & community-maintained)
- Extracts only: instance_type, vCPU, memory_GB, price_per_hour_us_east_1 (linux ondemand)
- Writes a compact JSON to ../data/instances_slim.json
Run once, or schedule to run daily/weekly.
"""

import os
import json
import requests
from pathlib import Path

RAW_URL = "https://raw.githubusercontent.com/powdahound/ec2instances.info/master/www/instances.json"
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUT_FILE = DATA_DIR / "instances_slim.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

def parse_memory(mem_str):
    # mem_str like "8 GiB" or "16384 MiB"
    try:
        num_str = str(mem_str).split()[0]
        return float(num_str)
    except Exception:
        return None

def extract_price_for_region(pricing_obj, preferred_regions=("us-east-1", "US East (N. Virginia)")):
    # pricing_obj = item.get("pricing", {})
    if not pricing_obj:
        return None
    # prefer us-east-1 if available
    for r in preferred_regions:
        region = pricing_obj.get(r)
        if region:
            linux = region.get("linux") or region.get("Linux")
            if linux:
                # many datasets store price directly in linux['ondemand'] as string
                od = linux.get("ondemand")
                if od is None:
                    # sometimes the shape is linux -> {'ondemand': '0.0116'}
                    continue
                # od may be a string number or nested object; try float conversion
                try:
                    return float(od)
                except Exception:
                    # try if dict with price field
                    if isinstance(od, dict):
                        # sometimes there are fields, try to find first numeric
                        for v in od.values():
                            try:
                                return float(v)
                            except Exception:
                                continue
    # fallback: search all regions and take first linux.ondemand numeric value found
    for region_key, region in pricing_obj.items():
        linux = region.get("linux") or region.get("Linux") if isinstance(region, dict) else None
        if linux:
            od = linux.get("ondemand")
            try:
                return float(od)
            except Exception:
                if isinstance(od, dict):
                    for v in od.values():
                        try:
                            return float(v)
                        except Exception:
                            continue
    return None

def main():
    print("Downloading source JSON (ec2instances.info)...")
    r = requests.get(RAW_URL, timeout=60)
    r.raise_for_status()
    raw = r.json()
    print("Downloaded items:", len(raw))

    slim = []
    for item in raw:
        instance_type = item.get("instance_type") or item.get("name") or item.get("InstanceType")
        vcpu = item.get("vCPU") or item.get("vcpu") or item.get("vcpus") or item.get("vcpu_count")
        memory = item.get("memory") or item.get("memory_gb") or item.get("Memory")
        pricing = item.get("pricing") or {}

        if instance_type is None:
            continue

        # normalize vCPU
        try:
            vcpu_int = int(vcpu)
        except Exception:
            # some items have 'vcpu' as strings; try parse
            try:
                vcpu_int = int(str(vcpu).split()[0])
            except Exception:
                vcpu_int = None

        memory_gb = parse_memory(memory)
        price = extract_price_for_region(pricing)

        if vcpu_int is None or memory_gb is None or price is None:
            # skip items missing key info
            continue

        slim.append({
            "instance_type": instance_type,
            "vCPU": vcpu_int,
            "memory_GB": memory_gb,
            "price_per_hour": float(price)
        })

    # sort by price ascending (optional)
    slim_sorted = sorted(slim, key=lambda x: x["price_per_hour"])

    print("Filtered slim instances:", len(slim_sorted))
    print("Writing to:", OUT_FILE)
    with OUT_FILE.open("w") as f:
        json.dump(slim_sorted, f, indent=2)

    print("Done. You can now run your Flask app which will read data/instances_slim.json")

if __name__ == "__main__":
    main()
