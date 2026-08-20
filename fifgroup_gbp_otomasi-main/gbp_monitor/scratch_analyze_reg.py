import json, sqlite3
from pathlib import Path

BASE_DIR = Path(r"c:\Users\alifp\Music\fifgroup_gbp_otomasi-main\fifgroup_gbp_otomasi-main\gbp_monitor")
net_file = BASE_DIR / "data" / "fifgroup_network_locations.json"

with open(net_file, "r", encoding="utf-8") as f:
    net_data = json.load(f)

# Map Regional Code -> Areas -> Cabangs
reg_area_map = {}
for x in net_data:
    reg = str(x.get("regional") or "UNKNOWN").replace(".0", "")
    area = str(x.get("area") or "UNKNOWN")
    c_type = x.get("type")
    
    if reg not in reg_area_map:
        reg_area_map[reg] = {"areas": set(), "cabang_count": 0, "pos_count": 0, "kios_count": 0}
    
    reg_area_map[reg]["areas"].add(area)
    if c_type == "CABANG":
        reg_area_map[reg]["cabang_count"] += 1
    elif c_type == "POS":
        reg_area_map[reg]["pos_count"] += 1
    elif c_type == "KIOSK":
        reg_area_map[reg]["kios_count"] += 1

print("Mapping REGIONAL CODE -> AREAS:")
for reg, data in sorted(reg_area_map.items()):
    print(f"  Region {reg}: {sorted(list(data['areas']))} (Cabang: {data['cabang_count']}, Pos: {data['pos_count']}, Kios: {data['kios_count']})")

# Check Area -> Regional
area_reg_map = {}
for x in net_data:
    area = str(x.get("area") or "UNKNOWN")
    reg = str(x.get("regional") or "UNKNOWN").replace(".0", "")
    if area not in area_reg_map:
        area_reg_map[area] = set()
    area_reg_map[area].add(reg)

print("\nMapping AREA -> REGIONAL CODES:")
for area, regs in sorted(area_reg_map.items()):
    print(f"  Area {area} -> Region: {sorted(list(regs))}")
