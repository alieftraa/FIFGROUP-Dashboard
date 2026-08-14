"""
dashboard_service.py — Service untuk mengagregasi data untuk dashboard Overview.
Menghitung status verifikasi secara dinamis berdasarkan gabungan MasterLocation dan LocationSnapshot.
"""

from typing import Dict, List, Any
from datetime import timedelta
from collections import defaultdict
from django.utils import timezone
from gbp.models import MasterLocation, LocationSnapshot, FetchRun

def _get_matched_status(master: MasterLocation, snapshots_by_store: dict, snapshots_by_loc: dict, snapshots_by_biz: dict) -> str:
    """Mencocokkan MasterLocation dengan snapshot dan mengembalikan statusnya."""
    if master.store_code and master.store_code in snapshots_by_store:
        return snapshots_by_store[master.store_code].status
    if master.location_name and master.location_name in snapshots_by_loc:
        return snapshots_by_loc[master.location_name].status
    if master.business_name and master.business_name in snapshots_by_biz:
        return snapshots_by_biz[master.business_name].status
    
    return LocationSnapshot.STATUS_UNVERIFIED


def _get_dashboard_data(run_id: int | None = None) -> List[Dict[str, Any]]:
    """
    Menghasilkan data mentah yang sudah di-match antara Master dan Snapshot.
    Returns: List of dict {'area': str, 'network': str, 'status': str}
    """
    run = FetchRun.objects.filter(id=run_id).first() if run_id else FetchRun.objects.order_by('-run_date', '-id').first()
    
    snapshots_by_store = {}
    snapshots_by_loc = {}
    snapshots_by_biz = {}
    
    if run:
        snapshots = LocationSnapshot.objects.filter(run=run)
        for s in snapshots:
            if s.store_code:
                snapshots_by_store[s.store_code] = s
            if s.location_name:
                snapshots_by_loc[s.location_name] = s
            if s.business_name:
                snapshots_by_biz[s.business_name] = s

    master_locations = MasterLocation.objects.all()
    
    data = []
    if master_locations.exists():
        for master in master_locations:
            status = _get_matched_status(master, snapshots_by_store, snapshots_by_loc, snapshots_by_biz)
            data.append({
                'area': master.area or 'Unknown Area',
                'network': master.network or 'Unknown',
                'status': status
            })
    else:
        # Fallback: jika Master Data kosong, gunakan data langsung dari API Snapshots
        if run:
            for s in snapshots:
                # Ekstrak nama area dari business_name: "FIFGROUP - NAMA AREA" → "NAMA AREA"
                biz_name = s.business_name or ""
                if " - " in biz_name:
                    area = biz_name.split(" - ", 1)[1].strip().title()
                elif biz_name.upper().startswith("FIFGROUP"):
                    area = biz_name[len("FIFGROUP"):].strip().strip("-").strip().title()
                else:
                    area = biz_name.strip().title() if biz_name else "Unknown Area"

                # Deteksi tipe network dari nama bisnis (order penting: Subkios sebelum Kios)
                name_upper = biz_name.upper()
                if "SUBKIOS" in name_upper or "SUB KIOS" in name_upper:
                    network = "Subkios"
                elif "KIOS" in name_upper:
                    network = "Kios"
                elif "CABANG" in name_upper or "CBG" in name_upper:
                    network = "Cabang"
                elif "POS " in name_upper or " POS" in name_upper or name_upper.endswith(" POS"):
                    network = "Pos"
                else:
                    network = "Unknown"

                data.append({
                    'area': area or "Unknown Area",
                    'network': network,
                    'status': s.status
                })
    return data


def get_overview_summary(run_id: int | None = None) -> Dict[str, Any]:
    data = _get_dashboard_data(run_id)
    
    summary = {
        "total": len(data),
        "verified": 0,
        "duplicate": 0,
        "suspended": 0,
        "need_verification": 0,
        "unverified": 0,
        "verified_rate": 0,
        "need_verification_rate": 0,
        "unverified_rate": 0,
    }
    
    for item in data:
        s = item['status']
        if s == LocationSnapshot.STATUS_VERIFIED:
            summary['verified'] += 1
        elif s == LocationSnapshot.STATUS_DUPLICATE:
            summary['duplicate'] += 1
        elif s == LocationSnapshot.STATUS_SUSPENDED:
            summary['suspended'] += 1
        elif s == LocationSnapshot.STATUS_NEED_VERIFICATION:
            summary['need_verification'] += 1
        elif s == LocationSnapshot.STATUS_UNVERIFIED:
            summary['unverified'] += 1

    if summary['total'] > 0:
        summary['verified_rate'] = round((summary['verified'] / summary['total']) * 100, 1)
        summary['need_verification_rate'] = round((summary['need_verification'] / summary['total']) * 100, 1)
        summary['unverified_rate'] = round((summary['unverified'] / summary['total']) * 100, 1)

    return summary


def get_verified_growth_timeseries(days: int = 30) -> List[Dict[str, Any]]:
    # Ambil runs dalam X hari terakhir
    cutoff = timezone.now().date() - timedelta(days=days)
    runs = FetchRun.objects.filter(run_date__gte=cutoff).order_by('run_date', 'id')
    
    timeseries = []
    prev_verified = None
    
    for run in runs:
        # Panggil summary untuk run ini (ini agak mahal jika banyak data, tapi OK untuk 30 hari)
        # Jika data ribuan dan performa lambat, kita bisa mengoptimalkan ini nanti
        summary = get_overview_summary(run.id)
        verified = summary['verified']
        
        delta = 0
        if prev_verified is not None:
            delta = verified - prev_verified
            
        timeseries.append({
            "date": run.run_date.strftime("%Y-%m-%d"),
            "verified": verified,
            "total": summary['total'],
            "verified_rate": summary['verified_rate'],
            "delta_verified": delta
        })
        
        prev_verified = verified
        
    return timeseries


def _aggregate_areas(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    area_stats = defaultdict(lambda: {
        "total": 0, "verified": 0, "need_verification": 0, 
        "unverified": 0, "suspended": 0, "duplicate": 0
    })
    
    for item in data:
        area = item['area']
        area_stats[area]['total'] += 1
        s = item['status']
        if s == LocationSnapshot.STATUS_VERIFIED:
            area_stats[area]['verified'] += 1
        elif s == LocationSnapshot.STATUS_NEED_VERIFICATION:
            area_stats[area]['need_verification'] += 1
        elif s == LocationSnapshot.STATUS_UNVERIFIED:
            area_stats[area]['unverified'] += 1
        elif s == LocationSnapshot.STATUS_SUSPENDED:
            area_stats[area]['suspended'] += 1
        elif s == LocationSnapshot.STATUS_DUPLICATE:
            area_stats[area]['duplicate'] += 1
            
    result = []
    for area, stats in area_stats.items():
        rate = round((stats['verified'] / stats['total']) * 100, 1) if stats['total'] > 0 else 0
        stats['area'] = area
        stats['verification_rate'] = rate
        result.append(stats)
        
    return result


def get_top_areas(run_id: int | None = None, limit: int = 10) -> List[Dict[str, Any]]:
    data = _get_dashboard_data(run_id)
    areas = _aggregate_areas(data)
    # Urutkan berdasarkan verification_rate (descending)
    areas.sort(key=lambda x: x['verification_rate'], reverse=True)
    return areas[:limit]


def get_bottom_areas(run_id: int | None = None, limit: int = 10) -> List[Dict[str, Any]]:
    data = _get_dashboard_data(run_id)
    areas = _aggregate_areas(data)
    # Urutkan berdasarkan verification_rate (ascending)
    areas.sort(key=lambda x: x['verification_rate'])
    return areas[:limit]


def get_status_by_network_type(run_id: int | None = None) -> List[Dict[str, Any]]:
    data = _get_dashboard_data(run_id)
    network_stats = defaultdict(lambda: {
        "total": 0, "verified": 0, "duplicate": 0, "suspended": 0, 
        "need_verification": 0, "unverified": 0
    })
    
    for item in data:
        network = item['network']
        network_stats[network]['total'] += 1
        s = item['status']
        if s == LocationSnapshot.STATUS_VERIFIED:
            network_stats[network]['verified'] += 1
        elif s == LocationSnapshot.STATUS_DUPLICATE:
            network_stats[network]['duplicate'] += 1
        elif s == LocationSnapshot.STATUS_SUSPENDED:
            network_stats[network]['suspended'] += 1
        elif s == LocationSnapshot.STATUS_NEED_VERIFICATION:
            network_stats[network]['need_verification'] += 1
        elif s == LocationSnapshot.STATUS_UNVERIFIED:
            network_stats[network]['unverified'] += 1
            
    result = []
    # Urutan standar: Cabang, Pos, Kios, Subkios, Unknown
    order_map = {"Cabang": 1, "Pos": 2, "Kios": 3, "Subkios": 4, "Unknown": 5}
    
    for network, stats in network_stats.items():
        rate = round((stats['verified'] / stats['total']) * 100, 1) if stats['total'] > 0 else 0
        stats['network'] = network
        stats['verification_rate'] = rate
        result.append(stats)
        
    result.sort(key=lambda x: order_map.get(x['network'], 99))
    return result


def get_attention_status_summary(run_id: int | None = None) -> Dict[str, Any]:
    summary = get_overview_summary(run_id)
    total = summary['total'] or 1
    
    return {
        "suspended": {
            "count": summary['suspended'],
            "percentage": round((summary['suspended'] / total) * 100, 1)
        },
        "unverified": {
            "count": summary['unverified'],
            "percentage": round((summary['unverified'] / total) * 100, 1)
        },
        "need_verification": {
            "count": summary['need_verification'],
            "percentage": round((summary['need_verification'] / total) * 100, 1)
        }
    }
