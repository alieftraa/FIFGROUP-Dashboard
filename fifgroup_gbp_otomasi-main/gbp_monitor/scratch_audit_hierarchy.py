"""Audit hierarchy relationships in network data."""
import json

d = json.load(open('data/fifgroup_network_locations.json', encoding='utf-8'))
cov = json.load(open('data/fifgroup_area_coverage.json', encoding='utf-8'))

# Build fast coord lookup from coverage
coord_to_cov = {}
for r in cov:
    lat, lng = r.get('latitude'), r.get('longitude')
    if lat and lng:
        k4 = (round(float(lat), 4), round(float(lng), 4))
        if k4 not in coord_to_cov:
            coord_to_cov[k4] = r

# All POS under CABANG 11700
cov_11700 = {str(r.get('pos', '')).split('.')[0].strip() for r in cov
             if str(r.get('cabang', '')).split('.')[0].strip() == '11700'}
print('All POS under CABANG 11700:', sorted(cov_11700))

# All POS under CABANG 10100
cov_10100 = {str(r.get('pos', '')).split('.')[0].strip() for r in cov
             if str(r.get('cabang', '')).split('.')[0].strip() == '10100'}
print('All POS under CABANG 10100:', sorted(cov_10100))

print()
# Check KIOS in 101xx range
kios_in_101 = [r for r in d if r.get('type') == 'KIOSK' and str(r.get('code', '')).startswith('101')]
seen_kios = {}
for k in kios_in_101:
    code = str(k.get('code', '')).split('.')[0].strip()
    if code not in seen_kios:
        seen_kios[code] = k

for code, k in sorted(seen_kios.items()):
    lat, lng = k.get('latitude'), k.get('longitude')
    matched_pos = None
    if lat and lng:
        k4 = (round(float(lat), 4), round(float(lng), 4))
        cov_rec = coord_to_cov.get(k4)
        if cov_rec:
            matched_pos = str(cov_rec.get('pos', '')).split('.')[0].strip()
            matched_cab = str(cov_rec.get('cabang', '')).split('.')[0].strip()
            print(f'KIOS {code} ({k.get("name")}) -> cab={matched_cab} pos={matched_pos}')
        else:
            print(f'KIOS {code} ({k.get("name")}) -> NO COVERAGE MATCH')

print()
print("=== CODE STRUCTURE ANALYSIS ===")
# Understand code hierarchy:
# - CABANG always ends in 00 (last 2 digits)?
cabang_codes = {str(r.get('code', '')).split('.')[0].strip() for r in d if r.get('type') == 'CABANG'}
ending_00 = sum(1 for c in cabang_codes if c.endswith('00'))
print(f'Cabang codes ending in 00: {ending_00}/{len(cabang_codes)}')

# What are the non-00 endings?
non_00 = [c for c in sorted(cabang_codes) if not c.endswith('00')]
print(f'Non-00 cabang codes: {non_00[:20]}')

print()
# POS code relationship to CABANG
# POS 10102: prefix = 101, cabang = 10100
# POS 10100: prefix = 101, IS the cabang
# Theory: prefix = first 3 digits, cabang = prefix + '00'
pos_codes_unique = {}
for r in d:
    if r.get('type') == 'POS':
        code = str(r.get('code', '')).split('.')[0].strip()
        if code not in pos_codes_unique:
            pos_codes_unique[code] = r.get('name')

prefix_cabang_match = 0
for code in pos_codes_unique:
    prefix = code[:3]
    expected_cabang = prefix + '00'
    if expected_cabang in cabang_codes:
        prefix_cabang_match += 1

print(f'POS codes where prefix+00 matches a CABANG code: {prefix_cabang_match}/{len(pos_codes_unique)}')
