import json
from shapely.geometry import MultiPoint, mapping, Point

with open("data/fifgroup_network_locations.json", "r", encoding="utf-8") as f:
    net_data = json.load(f)

# Group entities by Cabang code
cabang_entities = {}
for x in net_data:
    c_type = x.get("type")
    code = str(x.get("code") or "").strip()
    prefix = code[:3] if len(code) >= 3 else code
    if prefix not in cabang_entities:
        cabang_entities[prefix] = {"cabang": None, "pos": [], "kios": [], "points": []}
    
    lat, lng = x.get("latitude"), x.get("longitude")
    if lat is not None and lng is not None:
        cabang_entities[prefix]["points"].append((float(lng), float(lat)))
    
    if c_type == "CABANG":
        cabang_entities[prefix]["cabang"] = x
    elif c_type == "POS":
        cabang_entities[prefix]["pos"].append(x)
    elif c_type in ("KIOSK", "KIOS"):
        cabang_entities[prefix]["kios"].append(x)

print(f"Total Cabang groups: {len(cabang_entities)}")

# Test generating polygons for Cabang
branch_polygons = {}
for prefix, grp in cabang_entities.items():
    pts = list(set(grp["points"]))
    if not pts:
        continue
    c_info = grp["cabang"] or (grp["pos"][0] if grp["pos"] else (grp["kios"][0] if grp["kios"] else {}))
    b_name = c_info.get("name")
    b_code = str(c_info.get("code") or prefix + "00")
    
    if len(pts) >= 3:
        mp = MultiPoint(pts)
        poly = mp.convex_hull.buffer(0.015)
    elif len(pts) in (1, 2):
        mp = MultiPoint(pts)
        poly = mp.buffer(0.035)
    
    branch_polygons[b_code] = {
        "type": "Feature",
        "geometry": mapping(poly),
        "properties": {
            "branch_code": b_code,
            "branch_name": b_name,
            "area": c_info.get("area"),
            "total_points": len(pts),
            "total_pos": len(grp["pos"]),
            "total_kios": len(grp["kios"]),
        }
    }

print(f"Successfully generated {len(branch_polygons)} Branch Coverage Polygons!")
print("Sample Branch Polygon Feature:", list(branch_polygons.values())[0]["properties"])
