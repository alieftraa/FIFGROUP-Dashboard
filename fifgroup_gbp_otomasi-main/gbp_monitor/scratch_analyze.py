import os
import json
from pathlib import Path

BASE_DIR = Path(r"c:\Users\alifp\Music\fifgroup_gbp_otomasi-main\fifgroup_gbp_otomasi-main\gbp_monitor")
net_file = BASE_DIR / "data" / "fifgroup_network_locations.json"
area_file = BASE_DIR / "data" / "fifgroup_area_coverage.json"

with open(net_file, "r", encoding="utf-8") as f:
    net_data = json.load(f)

with open(area_file, "r", encoding="utf-8") as f:
    area_data = json.load(f)

print(f"Total raw network records: {len(net_data)}")
print(f"Total area coverage records: {len(area_data)}")

# 1. Analyze network types and their structure
types_count = {}
sample_by_type = {}
regions_found = set()
areas_found = set()

for item in net_data:
    t = item.get("type")
    types_count[t] = types_count.get(t, 0) + 1
    if t not in sample_by_type:
        sample_by_type[t] = item
    if item.get("regional"):
        regions_found.add(str(item.get("regional")))
    if item.get("area"):
        areas_found.add(str(item.get("area")))

print("\nNetwork Types Count:")
for k, v in types_count.items():
    print(f"  {k}: {v}")

print("\nSample for each type:")
for k, v in sample_by_type.items():
    print(f"  [{k}]: {v}")

print(f"\nUnique Regionals in network locations ({len(regions_found)}):", sorted(list(regions_found)))
print(f"Unique Areas in network locations ({len(areas_found)}):", sorted(list(areas_found)))

# 2. Check Cabang, Pos, Kios deduplication and how they connect
cabang_list = [x for x in net_data if x.get("type") == "CABANG"]
pos_list = [x for x in net_data if x.get("type") == "POS"]
kiosk_list = [x for x in net_data if x.get("type") == "KIOSK"]

print(f"\nRaw counts -> CABANG: {len(cabang_list)}, POS: {len(pos_list)}, KIOSK: {len(kiosk_list)}")

# Deduplicate Pos and Kios by (name, area, regional) or code
unique_cabang = {}
for c in cabang_list:
    key = str(c.get("code") or c.get("name"))
    unique_cabang[key] = c

unique_pos = {}
for p in pos_list:
    key = (p.get("name"), p.get("area"), p.get("regional"), p.get("code"))
    if key not in unique_pos:
        unique_pos[key] = p

unique_kios = {}
for k in kiosk_list:
    key = (k.get("name"), k.get("area"), k.get("regional"), k.get("code"))
    if key not in unique_kios:
        unique_kios[key] = k

print(f"Unique entities -> CABANG: {len(unique_cabang)}, POS: {len(unique_pos)}, KIOS: {len(unique_kios)}")

# Let's inspect codes: what is 'code' in POS and KIOSK?
cabang_codes = {str(c.get("code")): c for c in unique_cabang.values()}
print("\nSample Cabang codes:", list(cabang_codes.keys())[:10])

pos_sample = list(unique_pos.values())[:5]
print("\nSample POS records with code:")
for p in pos_sample:
    print(f"  POS Name: {p.get('name')}, Code: {p.get('code')}, Area: {p.get('area')}, Regional: {p.get('regional')}")
    # Does code match a Cabang?
    parent_c = cabang_codes.get(str(p.get("code")))
    if parent_c:
        print(f"    --> Matched Parent Cabang by code: {parent_c.get('name')} ({parent_c.get('code')})")

kios_sample = list(unique_kios.values())[:5]
print("\nSample KIOSK records with code:")
for k in kios_sample:
    print(f"  KIOS Name: {k.get('name')}, Code: {k.get('code')}, Area: {k.get('area')}, Regional: {k.get('regional')}")
    parent_c = cabang_codes.get(str(k.get("code")))
    if parent_c:
        print(f"    --> Matched Parent Cabang by code: {parent_c.get('name')} ({parent_c.get('code')})")

# Let's check statistics of code match
pos_matched_cabang = sum(1 for p in unique_pos.values() if str(p.get("code")) in cabang_codes)
kios_matched_cabang = sum(1 for k in unique_kios.values() if str(k.get("code")) in cabang_codes)
print(f"\nTotal POS matching a Cabang code: {pos_matched_cabang} / {len(unique_pos)} ({pos_matched_cabang/len(unique_pos)*100:.1f}%)")
print(f"Total KIOS matching a Cabang code: {kios_matched_cabang} / {len(unique_kios)} ({kios_matched_cabang/len(unique_kios)*100:.1f}%)")

# Let's inspect area_data: what columns/relations exist in area_data?
print("\nSample records in area_data (3 records):")
for x in area_data[:3]:
    print(" ", x)
