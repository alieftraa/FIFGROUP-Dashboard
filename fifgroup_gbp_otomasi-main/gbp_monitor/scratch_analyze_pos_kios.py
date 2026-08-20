import json

with open("data/fifgroup_area_coverage.json", "r", encoding="utf-8") as f:
    area_data = json.load(f)

print(f"Total records in area coverage: {len(area_data)}")

# Inspect sample records where pos != cabang
different_pos_cabang = []
for x in area_data:
    c = str(x.get("cabang")).replace(".0", "")
    p = str(x.get("pos")).replace(".0", "")
    if c != p:
        different_pos_cabang.append(x)

print(f"Records where pos != cabang: {len(different_pos_cabang)} / {len(area_data)}")
print("Sample where pos != cabang (5 records):")
for d in different_pos_cabang[:5]:
    print(" ", d)

# Check unique cabang and unique pos in area coverage
unique_c_in_coverage = set(str(x.get("cabang")).replace(".0", "") for x in area_data)
unique_p_in_coverage = set(str(x.get("pos")).replace(".0", "") for x in area_data)
print(f"\nUnique Cabang in coverage data: {len(unique_c_in_coverage)}")
print(f"Unique Pos in coverage data: {len(unique_p_in_coverage)}")

# Check network locations: how KIOS connect to POS
with open("data/fifgroup_network_locations.json", "r", encoding="utf-8") as f:
    net_data = json.load(f)

# Group all entities by Cabang (3-digit prefix)
cabang_groups = {}
for x in net_data:
    c_type = x.get("type")
    code = str(x.get("code") or "").strip()
    prefix = code[:3] if len(code) >= 3 else code
    if prefix not in cabang_groups:
        cabang_groups[prefix] = {"cabang": None, "pos": set(), "kios": set(), "area": x.get("area"), "regional": x.get("regional")}
    if c_type == "CABANG":
        cabang_groups[prefix]["cabang"] = (x.get("name"), code, x.get("latitude"), x.get("longitude"))
    elif c_type == "POS":
        cabang_groups[prefix]["pos"].add((x.get("name"), code, x.get("latitude"), x.get("longitude")))
    elif c_type == "KIOSK":
        cabang_groups[prefix]["kios"].add((x.get("name"), code, x.get("latitude"), x.get("longitude")))

print(f"\nTotal Cabang Groups (by prefix): {len(cabang_groups)}")
sample_prefixes = list(cabang_groups.keys())[:3]
for sp in sample_prefixes:
    cg = cabang_groups[sp]
    print(f"\nPrefix {sp} (Area: {cg['area']}):")
    print(f"  Cabang: {cg['cabang']}")
    print(f"  POS count: {len(cg['pos'])}")
    print(f"  Sample POS: {list(cg['pos'])[:3]}")
    print(f"  KIOS count: {len(cg['kios'])}")
    print(f"  Sample KIOS: {list(cg['kios'])[:3]}")
