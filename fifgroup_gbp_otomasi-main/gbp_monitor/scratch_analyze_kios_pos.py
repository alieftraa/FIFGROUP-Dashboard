import json

with open("data/fifgroup_network_locations.json", "r", encoding="utf-8") as f:
    net_data = json.load(f)

with open("data/fifgroup_area_coverage.json", "r", encoding="utf-8") as f:
    area_data = json.load(f)

# Zipcode -> pos mapping from area_data
zip_to_pos = {}
for x in area_data:
    zipc = str(x.get("zip_code")).strip()
    c = str(x.get("cabang")).replace(".0", "").strip()
    p = str(x.get("pos")).replace(".0", "").strip()
    zip_to_pos[zipc] = {"cabang": c, "pos": p, "kecamatan": x.get("kecamatan"), "kelurahan": x.get("kelurahan")}

# Check KIOSK records: match by coordinates to zip_code in area_data
coord_to_zip = {}
for x in area_data:
    lat = round(float(x.get("latitude", 0)), 5)
    lng = round(float(x.get("longitude", 0)), 5)
    coord_to_zip[(lat, lng)] = x

kiosk_unique = {}
for x in net_data:
    if x.get("type") == "KIOSK":
        key = (x.get("name"), x.get("area"), x.get("regional"), x.get("code"))
        kiosk_unique[key] = x

kiosk_matched_zip_pos = 0
kiosk_samples = []
for (name, area, regional, code), k in list(kiosk_unique.items()):
    lat = round(float(k.get("latitude", 0)), 5)
    lng = round(float(k.get("longitude", 0)), 5)
    matched_cov = coord_to_zip.get((lat, lng))
    pos_code = None
    if matched_cov:
        pos_code = str(matched_cov.get("pos")).replace(".0", "")
        kiosk_matched_zip_pos += 1
    kiosk_samples.append({
        "kios_name": name,
        "kios_code": code,
        "parent_cabang_code": code[:3] + "00" if len(code) >= 3 else code,
        "matched_pos_code": pos_code,
        "zip_code": matched_cov.get("zip_code") if matched_cov else None,
        "kelurahan": matched_cov.get("kelurahan") if matched_cov else None
    })

print(f"Total Unique Kiosks: {len(kiosk_unique)}")
print(f"Kiosks matched to exact POS via zipcode coverage: {kiosk_matched_zip_pos} / {len(kiosk_unique)} ({kiosk_matched_zip_pos/len(kiosk_unique)*100:.1f}%)")

print("\nSample 10 KIOS mappings to Parent POS & Parent Cabang:")
for s in kiosk_samples[:10]:
    print(" ", s)
