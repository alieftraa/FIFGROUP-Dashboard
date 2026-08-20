"""Quick test script for backend fix validation."""
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbp_monitor.settings')
django.setup()

from gbp.services.area_coverage_service import (
    get_all_network_locations, get_area_color_map, invalidate_network_caches
)

invalidate_network_caches()
locs = get_all_network_locations()

kios_via_pos = [l for l in locs if l.get('network_type') == 'Kios' and not l.get('hierarchy', {}).get('is_direct_to_branch')]
kios_direct = [l for l in locs if l.get('network_type') == 'Kios' and l.get('hierarchy', {}).get('is_direct_to_branch')]
cabangs = [l for l in locs if l.get('network_type') == 'Cabang']
pos_list = [l for l in locs if l.get('network_type') == 'Pos']

print('=== HASIL BACKEND FIX ===')
print(f'Total locations: {len(locs)}')
print(f'CABANG: {len(cabangs)}')
print(f'POS: {len(pos_list)}')
print(f'KIOS via POS: {len(kios_via_pos)}')
print(f'KIOS direct to CABANG: {len(kios_direct)}')

if cabangs:
    sample = cabangs[0]
    print(f'\nSample CABANG: {sample.get("name")} | area={sample.get("area")} | area_color={sample.get("area_color")}')
    print(f'  parent_id={sample.get("parent_id")}, parent_type={sample.get("parent_type")}')

if kios_via_pos:
    sample = kios_via_pos[0]
    h = sample.get('hierarchy', {})
    print(f'\nSample KIOS via POS: {sample.get("name")}')
    print(f'  path: {h.get("path")}')
    print(f'  parent_id={sample.get("parent_id")}, parent_type={sample.get("parent_type")}')
    print(f'  pos_code={h.get("pos_code")}, branch_code={h.get("branch_code")}')

if kios_direct:
    sample = kios_direct[0]
    h = sample.get('hierarchy', {})
    print(f'\nSample KIOS direct: {sample.get("name")}')
    print(f'  path: {h.get("path")}')

print('\n=== AREA COLOR MAP (sample) ===')
for k, v in list(get_area_color_map().items())[:8]:
    print(f'  {k}: {v}')

print('\n✅ Backend test completed successfully!')
