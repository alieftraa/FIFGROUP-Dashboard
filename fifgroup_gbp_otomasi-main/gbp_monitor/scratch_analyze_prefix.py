import json

with open("data/fifgroup_network_locations.json", "r", encoding="utf-8") as f:
    net_data = json.load(f)

# Group Cabang by code prefix (first 3 digits) and exact code
cabang_by_prefix = {}
cabang_by_code = {}
for x in net_data:
    if x.get("type") == "CABANG":
        code = str(x.get("code")).strip()
        prefix = code[:3] if len(code) >= 3 else code
        cabang_by_prefix[prefix] = x
        cabang_by_code[code] = x

print(f"Total Cabang records: {len(cabang_by_code)}")

# Inspect POS codes and how they relate to Cabang
pos_unique = {}
for x in net_data:
    if x.get("type") == "POS":
        key = (x.get("name"), x.get("area"), x.get("regional"), x.get("code"))
        pos_unique[key] = x

pos_matched_prefix = 0
pos_samples = []
for (name, area, regional, code), p in list(pos_unique.items()):
    c_code = str(code).strip()
    prefix = c_code[:3] if len(c_code) >= 3 else c_code
    parent_cabang = cabang_by_prefix.get(prefix)
    if parent_cabang:
        pos_matched_prefix += 1
    pos_samples.append({
        "pos_name": name,
        "pos_code": code,
        "pos_area": area,
        "matched_cabang": parent_cabang.get("name") if parent_cabang else None,
        "matched_cabang_code": parent_cabang.get("code") if parent_cabang else None,
        "matched_cabang_area": parent_cabang.get("area") if parent_cabang else None,
    })

print(f"POS matching Cabang by 3-digit prefix: {pos_matched_prefix} / {len(pos_unique)} ({pos_matched_prefix/len(pos_unique)*100:.1f}%)")
print("\nSample 10 POS mappings to Cabang:")
for s in pos_samples[:10]:
    print(" ", s)

# Inspect KIOSK codes and how they relate to Cabang & POS
kiosk_unique = {}
for x in net_data:
    if x.get("type") == "KIOSK":
        key = (x.get("name"), x.get("area"), x.get("regional"), x.get("code"))
        kiosk_unique[key] = x

kiosk_matched_prefix = 0
kiosk_samples = []
for (name, area, regional, code), k in list(kiosk_unique.items()):
    c_code = str(code).strip()
    prefix = c_code[:3] if len(c_code) >= 3 else c_code
    parent_cabang = cabang_by_prefix.get(prefix)
    if parent_cabang:
        kiosk_matched_prefix += 1
    kiosk_samples.append({
        "kios_name": name,
        "kios_code": code,
        "kios_area": area,
        "matched_cabang": parent_cabang.get("name") if parent_cabang else None,
        "matched_cabang_code": parent_cabang.get("code") if parent_cabang else None,
    })

print(f"\nKIOSK matching Cabang by 3-digit prefix: {kiosk_matched_prefix} / {len(kiosk_unique)} ({kiosk_matched_prefix/len(kiosk_unique)*100:.1f}%)")
print("\nSample 10 KIOS mappings to Cabang:")
for s in kiosk_samples[:10]:
    print(" ", s)
