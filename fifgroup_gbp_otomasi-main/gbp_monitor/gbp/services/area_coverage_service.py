"""
area_coverage_service.py — Service untuk pembentukan Coverage Area FIFGROUP.

Sumber data:
  - data/fifgroup_area_coverage.json  → Coverage zona (72.956 titik, 34 area)
  - data/fifgroup_network_locations.json → Lokasi network nyata (CABANG, POS, KIOS)

Fitur:
  - Hierarki valid: REGION → AREA → CABANG → POS → KIOS
  - KIOS parent ditentukan via coordinate-lookup ke area_coverage.json
  - Multi-color per AREA (deterministic, tidak berubah tiap reload)
  - Polygon coverage dengan clustering anti-lintas-laut (DBSCAN grid-based)
  - Caching disk & memori untuk performa <10ms setelah cold start
"""

import os
import json
import logging
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional

import shapely
from shapely.geometry import Point, MultiPoint, Polygon, MultiPolygon, LineString, mapping
from shapely.ops import unary_union

log = logging.getLogger("gbp.services.area_coverage_service")

# Path ke file source of truth
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_FILE = BASE_DIR / "data" / "fifgroup_area_coverage.json"
CACHE_FILE = BASE_DIR / "data" / "fifgroup_area_polygons_cache.json"
NETWORK_DATA_FILE = BASE_DIR / "data" / "fifgroup_network_locations.json"

_MEM_CACHE: Optional[Dict[str, Any]] = None
_LAST_MTIME: float = 0.0

# ══════════════════════════════════════════════════════════════════════
# AREA COLOR MAP — Warna identitas unik per Area FIFGROUP
# Setiap area mendapat warna konsisten, cerah, dan kontras satu sama lain.
# ══════════════════════════════════════════════════════════════════════
AREA_COLOR_MAP: Dict[str, str] = {
    # JAWA — Jakarta & Banten
    "JATA 1":        "#2563EB",   # Biru Royal
    "JATA 2":        "#DC2626",   # Merah Solid
    "JATA 3":        "#9333EA",   # Ungu
    "BANTEN":        "#0891B2",   # Cyan/Teal
    # JAWA BARAT
    "JABAR 1":       "#16A34A",   # Hijau
    "JABAR 2":       "#F97316",   # Orange
    "JABAR 3":       "#DB2777",   # Pink/Magenta
    "JABAR 4":       "#4F46E5",   # Indigo
    "JABAR 5":       "#0F766E",   # Teal gelap
    # JAWA TENGAH & DIY
    "JATENG 1":      "#B45309",   # Amber tua
    "JATENG 2":      "#7C3AED",   # Violet
    "DIY":           "#059669",   # Emerald
    # JAWA TIMUR
    "JATIM 1":       "#1D4ED8",   # Biru tua
    "JATIM 2":       "#BE123C",   # Rose/Crimson
    "JATIM 3":       "#15803D",   # Hijau tua
    "JATIM 4":       "#A16207",   # Kuning tua/Ochre
    # BALI & NUSA TENGGARA
    "BALI":          "#0E7490",   # Cyan gelap
    "NUSA TENGGARA": "#6D28D9",   # Purple
    # SUMATERA
    "NAD":           "#047857",   # Emerald gelap
    "SUMUT 1":       "#B91C1C",   # Red tua
    "SUMUT 2":       "#92400E",   # Brown/Orange tua
    "SUMBAR":        "#1E40AF",   # Biru Navy
    "RIDAR":         "#065F46",   # Green gelap
    "RIKEP":         "#4338CA",   # Indigo tua
    "JAMBI":         "#78350F",   # Amber gelap
    "SUMSEL":        "#831843",   # Pink tua
    "LAMBABEL":      "#134E4A",   # Teal gelap
    # KALIMANTAN
    "KALBAR":        "#1E3A5F",   # Navy gelap
    "KALSELTENG":    "#5B21B6",   # Purple gelap
    "KALTIMTARA":    "#0C4A6E",   # Sky tua
    # SULAWESI
    "SULSELBAR":     "#7F1D1D",   # Red gelap
    "SULTENGTRAM":   "#365314",   # Lime gelap
    "SULUT":         "#374151",   # Slate
    # PAPUA & MALUKU
    "PAPUA":         "#1F2937",   # Dark teal-gray
}

# Fallback warna deterministic untuk area tidak dikenal
_FALLBACK_COLORS = [
    "#2563EB", "#DC2626", "#9333EA", "#F97316", "#16A34A",
    "#0891B2", "#DB2777", "#4F46E5", "#B45309", "#059669",
    "#7C3AED", "#0E7490", "#BE123C", "#15803D", "#A16207",
]


def get_area_color(area_name: str) -> str:
    """Kembalikan warna identitas unik dan konsisten untuk sebuah Area."""
    if not area_name:
        return "#64748b"
    name = area_name.strip()
    if name in AREA_COLOR_MAP:
        return AREA_COLOR_MAP[name]
    # Deterministic fallback berdasarkan hash nama area
    idx = abs(hash(name)) % len(_FALLBACK_COLORS)
    return _FALLBACK_COLORS[idx]


def get_area_color_map() -> Dict[str, str]:
    """Return seluruh AREA_COLOR_MAP untuk digunakan di frontend."""
    return dict(AREA_COLOR_MAP)


# ══════════════════════════════════════════════════════════════════════
# AREA → REGION MAPPING
# ══════════════════════════════════════════════════════════════════════
AREA_TO_REGION: Dict[str, Dict[str, str]] = {
    "JATA 1":        {"code": "REG-01", "name": "REGION 1 (DKI JAKARTA)"},
    "JATA 2":        {"code": "REG-01", "name": "REGION 1 (DKI JAKARTA)"},
    "JATA 3":        {"code": "REG-01", "name": "REGION 1 (DKI JAKARTA)"},
    "BANTEN":        {"code": "REG-02", "name": "REGION 2 (BANTEN)"},
    "JABAR 1":       {"code": "REG-03", "name": "REGION 3 (JAWA BARAT)"},
    "JABAR 2":       {"code": "REG-03", "name": "REGION 3 (JAWA BARAT)"},
    "JABAR 3":       {"code": "REG-03", "name": "REGION 3 (JAWA BARAT)"},
    "JABAR 4":       {"code": "REG-03", "name": "REGION 3 (JAWA BARAT)"},
    "JABAR 5":       {"code": "REG-03", "name": "REGION 3 (JAWA BARAT)"},
    "JATENG 1":      {"code": "REG-04", "name": "REGION 4 (JAWA TENGAH & DIY)"},
    "JATENG 2":      {"code": "REG-04", "name": "REGION 4 (JAWA TENGAH & DIY)"},
    "DIY":           {"code": "REG-04", "name": "REGION 4 (JAWA TENGAH & DIY)"},
    "JATIM 1":       {"code": "REG-05", "name": "REGION 5 (JAWA TIMUR)"},
    "JATIM 2":       {"code": "REG-05", "name": "REGION 5 (JAWA TIMUR)"},
    "JATIM 3":       {"code": "REG-05", "name": "REGION 5 (JAWA TIMUR)"},
    "JATIM 4":       {"code": "REG-05", "name": "REGION 5 (JAWA TIMUR)"},
    "BALI":          {"code": "REG-06", "name": "REGION 6 (BALI & NUSA TENGGARA)"},
    "NUSA TENGGARA": {"code": "REG-06", "name": "REGION 6 (BALI & NUSA TENGGARA)"},
    "NAD":           {"code": "REG-07", "name": "REGION 7 (SUMATERA 1 - SUMBAGUT)"},
    "SUMUT 1":       {"code": "REG-07", "name": "REGION 7 (SUMATERA 1 - SUMBAGUT)"},
    "SUMUT 2":       {"code": "REG-07", "name": "REGION 7 (SUMATERA 1 - SUMBAGUT)"},
    "SUMBAR":        {"code": "REG-07", "name": "REGION 7 (SUMATERA 1 - SUMBAGUT)"},
    "RIDAR":         {"code": "REG-07", "name": "REGION 7 (SUMATERA 1 - SUMBAGUT)"},
    "RIKEP":         {"code": "REG-07", "name": "REGION 7 (SUMATERA 1 - SUMBAGUT)"},
    "JAMBI":         {"code": "REG-08", "name": "REGION 8 (SUMATERA 2 - SUMBAGSEL)"},
    "SUMSEL":        {"code": "REG-08", "name": "REGION 8 (SUMATERA 2 - SUMBAGSEL)"},
    "LAMBABEL":      {"code": "REG-08", "name": "REGION 8 (SUMATERA 2 - SUMBAGSEL)"},
    "KALBAR":        {"code": "REG-09", "name": "REGION 9 (KALIMANTAN)"},
    "KALSELTENG":    {"code": "REG-09", "name": "REGION 9 (KALIMANTAN)"},
    "KALTIMTARA":    {"code": "REG-09", "name": "REGION 9 (KALIMANTAN)"},
    "SULSELBAR":     {"code": "REG-10", "name": "REGION 10 (SULAWESI)"},
    "SULTENGTRAM":   {"code": "REG-10", "name": "REGION 10 (SULAWESI)"},
    "SULUT":         {"code": "REG-10", "name": "REGION 10 (SULAWESI)"},
    "PAPUA":         {"code": "REG-11", "name": "REGION 11 (PAPUA & MALUKU)"},
}


def get_region_info(area_name: str) -> Dict[str, str]:
    if not area_name:
        return {"code": "REG-00", "name": "NASIONAL"}
    return AREA_TO_REGION.get(area_name.strip(), {"code": "REG-00", "name": f"REGION ({area_name.strip()})"})


# ══════════════════════════════════════════════════════════════════════
# POLYGON BUILDING — Cluster-based, anti cross-sea
# ══════════════════════════════════════════════════════════════════════

def _build_cluster_polygons(pts_list: List[tuple], eps_km: float = 20.0):
    """
    Cluster titik berdasarkan kedekatan geografis lalu buat polygon/multipolygon.
    Menghindari satu polygon raksasa yang menghubungkan pulau/wilayah berjauhan.
    """
    coords = np.array(pts_list)
    unique_coords = np.unique(coords, axis=0)
    if len(unique_coords) == 0:
        return None

    grid_size = eps_km / 111.0
    grid: Dict[tuple, List[int]] = {}
    for idx, (x, y) in enumerate(unique_coords):
        gx, gy = int(x / grid_size), int(y / grid_size)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                grid.setdefault((gx + dx, gy + dy), []).append(idx)

    visited = set()
    clusters = []
    for i in range(len(unique_coords)):
        if i in visited:
            continue
        cluster = []
        queue = [i]
        visited.add(i)

        while queue:
            curr = queue.pop()
            cluster.append(unique_coords[curr])
            cx, cy = unique_coords[curr]
            gx, gy = int(cx / grid_size), int(cy / grid_size)

            for neighbor in grid.get((gx, gy), []):
                if neighbor not in visited:
                    nx, ny = unique_coords[neighbor]
                    dist_km = np.sqrt(
                        ((nx - cx) * np.cos(np.radians((ny + cy) / 2)) * 111.0) ** 2
                        + ((ny - cy) * 111.0) ** 2
                    )
                    if dist_km <= eps_km:
                        visited.add(neighbor)
                        queue.append(neighbor)
        clusters.append(cluster)

    polys = []
    for cl in clusters:
        if len(cl) == 1:
            polys.append(Point(cl[0][0], cl[0][1]).buffer(0.025))
        elif len(cl) == 2:
            polys.append(LineString([cl[0], cl[1]]).buffer(0.025))
        else:
            mp = MultiPoint(cl)
            try:
                # Concave hull dengan rasio 0.35 untuk lekuk area yang natural
                hull = shapely.concave_hull(mp, ratio=0.35)
                if not hull.is_valid or hull.is_empty or hull.geom_type not in ("Polygon", "MultiPolygon"):
                    hull = mp.convex_hull
            except Exception:
                hull = mp.convex_hull
            # Buffer kecil (~2.2 km) agar polygon rapi membungkus titik-titik
            polys.append(hull.buffer(0.020))

    union_geom = unary_union(polys)
    return union_geom.simplify(0.001, preserve_topology=True)


def _build_small_cluster_polygons(pts_list: List[tuple], eps_km: float = 5.0, buffer_deg: float = 0.010):
    """
    Versi clustering untuk coverage CABANG dan POS — radius lebih kecil.
    Menghindari polygon yang menghubungkan lokasi berjauhan.
    """
    coords = np.array(pts_list)
    unique_coords = np.unique(coords, axis=0)
    if len(unique_coords) == 0:
        return None

    grid_size = eps_km / 111.0
    grid: Dict[tuple, List[int]] = {}
    for idx, (x, y) in enumerate(unique_coords):
        gx, gy = int(x / grid_size), int(y / grid_size)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                grid.setdefault((gx + dx, gy + dy), []).append(idx)

    visited = set()
    clusters = []
    for i in range(len(unique_coords)):
        if i in visited:
            continue
        cluster = []
        queue = [i]
        visited.add(i)
        while queue:
            curr = queue.pop()
            cluster.append(unique_coords[curr])
            cx, cy = unique_coords[curr]
            gx, gy = int(cx / grid_size), int(cy / grid_size)
            for neighbor in grid.get((gx, gy), []):
                if neighbor not in visited:
                    nx, ny = unique_coords[neighbor]
                    dist_km = np.sqrt(
                        ((nx - cx) * np.cos(np.radians((ny + cy) / 2)) * 111.0) ** 2
                        + ((ny - cy) * 111.0) ** 2
                    )
                    if dist_km <= eps_km:
                        visited.add(neighbor)
                        queue.append(neighbor)
        clusters.append(cluster)

    polys = []
    for cl in clusters:
        if len(cl) == 1:
            polys.append(Point(cl[0][0], cl[0][1]).buffer(buffer_deg))
        elif len(cl) == 2:
            polys.append(LineString([cl[0], cl[1]]).buffer(buffer_deg))
        else:
            mp = MultiPoint(cl)
            try:
                hull = shapely.concave_hull(mp, ratio=0.4)
                if not hull.is_valid or hull.is_empty:
                    hull = mp.convex_hull
            except Exception:
                hull = mp.convex_hull
            polys.append(hull.buffer(buffer_deg * 0.5))

    union_geom = unary_union(polys)
    return union_geom.simplify(0.0005, preserve_topology=True)


# ══════════════════════════════════════════════════════════════════════
# AREA POLYGON GENERATION (dari fifgroup_area_coverage.json)
# ══════════════════════════════════════════════════════════════════════

def _generate_all_area_polygons() -> Dict[str, Any]:
    """
    Membaca data/fifgroup_area_coverage.json, membentuk polygon per area,
    dan menyimpannya ke cache file.
    """
    if not DATA_FILE.exists():
        log.error(f"File data tidak ditemukan: {DATA_FILE}")
        return {"areas_list": [], "features": {}}

    log.info(f"Membaca {DATA_FILE} untuk pembentukan coverage area...")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    area_data: Dict[str, Dict[str, Any]] = {}
    for r in raw_data:
        area = r.get("area")
        if not area:
            continue
        lat, lng = r.get("latitude"), r.get("longitude")
        if lat is None or lng is None:
            continue
        try:
            lat = float(lat)
            lng = float(lng)
        except (ValueError, TypeError):
            continue
        # Filter batas koordinat Indonesia
        if not (-12 <= lat <= 10 and 90 <= lng <= 145):
            continue

        if area not in area_data:
            area_data[area] = {
                "pts": [],
                "zips": set(),
                "cabang": set(),
                "kab": set(),
                "prov": set(),
            }
        ad = area_data[area]
        ad["pts"].append((lng, lat))
        if r.get("zip_code"):
            ad["zips"].add(str(r["zip_code"]))
        if r.get("cabang"):
            ad["cabang"].add(str(r["cabang"]))
        if r.get("kabupaten_kota"):
            ad["kab"].add(str(r["kabupaten_kota"]))
        if r.get("provinsi"):
            ad["prov"].add(str(r["provinsi"]))

    # Sort area names naturally
    sorted_area_names = sorted(area_data.keys())

    areas_list = []
    features_dict = {}

    for area in sorted_area_names:
        info = area_data[area]
        color = get_area_color(area)  # Warna unik konsisten per nama area
        geom = _build_cluster_polygons(info["pts"], eps_km=20.0)

        bounds = None
        if geom and not geom.is_empty:
            minx, miny, maxx, maxy = geom.bounds
            bounds = [[miny, minx], [maxy, maxx]]

        meta = {
            "area": area,
            "color": color,
            "total_points": len(info["pts"]),
            "total_zips": len(info["zips"]),
            "total_cabang": len(info["cabang"]),
            "total_kab": len(info["kab"]),
            "kabupaten_kota": sorted(list(info["kab"]))[:8],
            "provinsi": sorted(list(info["prov"])),
            "bounds": bounds,
        }
        areas_list.append(meta)

        feat = {
            "type": "Feature",
            "properties": meta,
            "geometry": mapping(geom) if geom else None,
        }
        features_dict[area] = feat

    result = {
        "areas_list": areas_list,
        "features": features_dict,
    }

    # Simpan ke cache file
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        log.info(f"Cache polygon berhasil disimpan ke {CACHE_FILE}")
    except Exception as e:
        log.warning(f"Gagal menyimpan cache polygon ke disk: {e}")

    return result


def _get_cache_data() -> Dict[str, Any]:
    """Mengambil data dari in-memory cache atau disk cache."""
    global _MEM_CACHE, _LAST_MTIME

    if not DATA_FILE.exists():
        return {"areas_list": [], "features": {}}

    current_mtime = os.path.getmtime(DATA_FILE)

    if _MEM_CACHE is not None and _LAST_MTIME == current_mtime:
        return _MEM_CACHE

    # Cek disk cache jika ada dan valid
    if CACHE_FILE.exists() and os.path.getmtime(CACHE_FILE) >= current_mtime:
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _MEM_CACHE = json.load(f)
                _LAST_MTIME = current_mtime
                return _MEM_CACHE
        except Exception as e:
            log.warning(f"Gagal membaca disk cache: {e}")

    # Generate ulang jika belum ada cache atau file data berubah
    _MEM_CACHE = _generate_all_area_polygons()
    _LAST_MTIME = current_mtime
    return _MEM_CACHE


def get_all_areas_meta() -> List[Dict[str, Any]]:
    """Return daftar 34 area dengan metadata ringkas untuk sidebar."""
    cache = _get_cache_data()
    return cache.get("areas_list", [])


def get_area_geojson_feature(area_name: str) -> Optional[Dict[str, Any]]:
    """Return GeoJSON Feature (Polygon / MultiPolygon) untuk satu area."""
    if not area_name:
        return None
    cache = _get_cache_data()
    features = cache.get("features", {})
    return features.get(area_name.strip())


def get_all_areas_geojson() -> Dict[str, Any]:
    """Return GeoJSON FeatureCollection berisi polygon seluruh 34 Area FIFGROUP."""
    cache = _get_cache_data()
    features = list(cache.get("features", {}).values())
    return {
        "type": "FeatureCollection",
        "features": features,
    }


# ══════════════════════════════════════════════════════════════════════
# NETWORK LOCATIONS: CABANG, POS, KIOS (REAL FIFGROUP NETWORK DATA)
# ══════════════════════════════════════════════════════════════════════

_NETWORK_CACHE: Optional[List[Dict[str, Any]]] = None
_NETWORK_LAST_MTIME: float = 0.0
_BRANCH_POLYGONS_CACHE: Optional[Dict[str, Any]] = None
_POS_POLYGONS_CACHE: Optional[Dict[str, Any]] = None


def _norm_code(val) -> str:
    """Normalisasi kode: hapus desimal, strip whitespace."""
    return str(val or "").split(".")[0].strip()


def _is_valid_coord(lat, lng) -> bool:
    """Validasi koordinat berada dalam batas Indonesia."""
    try:
        lat_f, lng_f = float(lat), float(lng)
        return -12 <= lat_f <= 10 and 90 <= lng_f <= 145
    except (ValueError, TypeError):
        return False


def _load_raw_network_locations() -> List[Dict[str, Any]]:
    """
    Memuat dan menormalkan seluruh lokasi real FIFGROUP dengan Hierarki Lengkap:
    REGION -> AREA -> CABANG -> POS -> KIOS

    Hierarki KIOS ditentukan via coordinate-lookup ke area_coverage.json:
    - Jika pos_code dari lookup != cabang_code → KIOS di bawah POS
    - Jika pos_code == cabang_code atau tidak ada → KIOS langsung di bawah CABANG

    CABANG codes selalu berakhir '00' (e.g. 11700).
    POS prefix[:3] + '00' = kode CABANG induk-nya.
    """
    if not NETWORK_DATA_FILE.exists():
        log.error(f"File network locations tidak ditemukan: {NETWORK_DATA_FILE}")
        return []

    log.info(f"Memuat {NETWORK_DATA_FILE}...")
    try:
        with open(NETWORK_DATA_FILE, "r", encoding="utf-8") as f:
            raw_net = json.load(f)
    except Exception as e:
        log.error(f"Gagal membaca {NETWORK_DATA_FILE}: {e}")
        return []

    # ── Build coordinate lookup dari area_coverage.json (SUMBER KEBENARAN hierarki) ──
    # zip_by_coord: (lat4, lng4) -> {pos_code, cabang_code, zipcode, address}
    zip_by_coord: Dict[tuple, Dict[str, str]] = {}   # precision 4 desimal
    zip_by_coord5: Dict[tuple, Dict[str, str]] = {}  # precision 5 desimal (fallback)
    zip_by_code: Dict[str, Dict[str, str]] = {}      # kode → {zipcode, address}

    if DATA_FILE.exists():
        try:
            log.info("Memuat lookup dari area_coverage.json untuk resolusi hierarki KIOS...")
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                cov_data = json.load(f)

            for r in cov_data:
                lat, lng = r.get("latitude"), r.get("longitude")
                z = str(r.get("zip_code") or "").strip()
                addr_parts = [r.get("kelurahan"), r.get("kecamatan"), r.get("kabupaten_kota"), r.get("provinsi")]
                addr = ", ".join([p for p in addr_parts if p])
                p_code = _norm_code(r.get("pos"))
                c_code = _norm_code(r.get("cabang"))

                if lat is not None and lng is not None:
                    try:
                        lat_f, lng_f = float(lat), float(lng)
                        entry = {"pos_code": p_code, "cabang_code": c_code, "zipcode": z, "address": addr}
                        k4 = (round(lat_f, 4), round(lng_f, 4))
                        k5 = (round(lat_f, 5), round(lng_f, 5))
                        if k4 not in zip_by_coord:
                            zip_by_coord[k4] = entry
                        if k5 not in zip_by_coord5:
                            zip_by_coord5[k5] = entry
                    except (ValueError, TypeError):
                        pass

                if c_code and c_code not in zip_by_code:
                    zip_by_code[c_code] = {"zipcode": z, "address": addr}
                if p_code and p_code not in zip_by_code:
                    zip_by_code[p_code] = {"zipcode": z, "address": addr}

            log.info(f"Lookup koordinat: {len(zip_by_coord)} entries (prec4), {len(zip_by_coord5)} entries (prec5)")
        except Exception as e:
            log.warning(f"Gagal memuat lookup dari area coverage: {e}")

    def _lookup_coverage(lat, lng) -> Dict[str, str]:
        """Cari data coverage (pos, cabang, zip, addr) berdasarkan koordinat."""
        if lat is None or lng is None:
            return {}
        try:
            lat_f, lng_f = float(lat), float(lng)
            k4 = (round(lat_f, 4), round(lng_f, 4))
            k5 = (round(lat_f, 5), round(lng_f, 5))
            return zip_by_coord.get(k4) or zip_by_coord5.get(k5) or {}
        except (ValueError, TypeError):
            return {}

    # ── 1. CABANG: lookup by code & 3-digit prefix ──
    cabangs = [x for x in raw_net if x.get("type") == "CABANG"]
    cabang_by_code: Dict[str, Dict[str, Any]] = {}
    cabang_by_prefix: Dict[str, Dict[str, Any]] = {}
    seen_cabangs: set = set()

    for c in cabangs:
        sc = _norm_code(c.get("code"))
        if not sc or sc in seen_cabangs:
            continue
        seen_cabangs.add(sc)
        prefix = sc[:3] if len(sc) >= 3 else sc
        cabang_by_code[sc] = c
        if prefix not in cabang_by_prefix:
            cabang_by_prefix[prefix] = c

    # ── 2. POS: deduplikasi berdasarkan kode unik ──
    pos_by_code: Dict[str, Dict[str, Any]] = {}
    seen_pos: set = set()
    for p in raw_net:
        if p.get("type") != "POS":
            continue
        sc = _norm_code(p.get("code"))
        if not sc or sc in seen_pos:
            continue
        seen_pos.add(sc)
        pos_by_code[sc] = p

    # ── 3. KIOS: deduplikasi berdasarkan kode unik ──
    kios_by_code: Dict[str, Dict[str, Any]] = {}
    seen_kios: set = set()
    for k in raw_net:
        if k.get("type") not in ("KIOSK", "KIOS"):
            continue
        sc = _norm_code(k.get("code"))
        if not sc or sc in seen_kios:
            continue
        seen_kios.add(sc)
        kios_by_code[sc] = k

    processed: List[Dict[str, Any]] = []

    # ── Process CABANG ──
    for sc, c in sorted(cabang_by_code.items()):
        prefix = sc[:3] if len(sc) >= 3 else sc
        lat_raw = c.get("latitude")
        lng_raw = c.get("longitude")
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (ValueError, TypeError):
            lat, lng = None, None

        info = _lookup_coverage(lat, lng) or zip_by_code.get(sc) or {}
        name = (c.get("name") or "").strip()
        area = (c.get("area") or "").strip()
        reg_info = get_region_info(area)
        area_color = get_area_color(area)
        b_name = f"FIFGROUP - CABANG {name}" if not name.upper().startswith("FIFGROUP") else name
        coord_ok = _is_valid_coord(lat, lng)

        processed.append({
            "id": f"cab_{sc}",
            "store_code": sc,
            "branch_prefix": prefix,
            "name": name,
            "business_name": b_name,
            "network_type": "Cabang",
            "network_raw": "CABANG",
            "area": area,
            "area_color": area_color,
            "regional": str(c.get("regional") or "").strip(),
            "region_code": reg_info["code"],
            "region_name": reg_info["name"],
            # Relasi parent-child eksplisit
            "parent_id": area,
            "parent_type": "AREA",
            "hierarchy": {
                "level": "CABANG",
                "region_code": reg_info["code"],
                "region_name": reg_info["name"],
                "area_name": area,
                "area_color": area_color,
                "branch_code": sc,
                "branch_name": name,
                "pos_code": "",
                "pos_name": "",
                "kios_code": "",
                "kios_name": "",
                "path": f"{reg_info['name']} > {area} > Cabang {name}",
            },
            "latitude": lat,
            "longitude": lng,
            "zipcode": info.get("zipcode", ""),
            "address": info.get("address", ""),
            "status": "Verified",
            "coord_status": "OK" if coord_ok else "INVALID",
            "maps_uri": f"https://www.google.com/maps/search/?api=1&query={lat},{lng}" if coord_ok else "",
        })

    # ── Process POS ──
    for sc, p in sorted(pos_by_code.items()):
        prefix = sc[:3] if len(sc) >= 3 else sc
        lat_raw = p.get("latitude")
        lng_raw = p.get("longitude")
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (ValueError, TypeError):
            lat, lng = None, None

        info = _lookup_coverage(lat, lng) or zip_by_code.get(sc) or {}
        name = (p.get("name") or "").strip()
        area = (p.get("area") or "").strip()
        reg_info = get_region_info(area)
        area_color = get_area_color(area)
        b_name = f"FIFGROUP - POS {name}" if not name.upper().startswith("FIFGROUP") else name

        # Temukan parent CABANG: prefix[:3] + "00"
        cabang_code_expected = prefix + "00"
        parent_cabang = cabang_by_code.get(cabang_code_expected) or cabang_by_prefix.get(prefix) or {}
        p_branch_code = _norm_code(parent_cabang.get("code")) or cabang_code_expected
        p_branch_name = (parent_cabang.get("name") or name).strip()
        coord_ok = _is_valid_coord(lat, lng)

        processed.append({
            "id": f"pos_{sc}",
            "store_code": sc,
            "branch_prefix": prefix,
            "name": name,
            "business_name": b_name,
            "network_type": "Pos",
            "network_raw": "POS",
            "area": area,
            "area_color": area_color,
            "regional": str(p.get("regional") or "").strip(),
            "region_code": reg_info["code"],
            "region_name": reg_info["name"],
            # Relasi parent-child eksplisit
            "parent_id": p_branch_code,
            "parent_type": "CABANG",
            "hierarchy": {
                "level": "POS",
                "region_code": reg_info["code"],
                "region_name": reg_info["name"],
                "area_name": area,
                "area_color": area_color,
                "branch_code": p_branch_code,
                "branch_name": p_branch_name,
                "pos_code": sc,
                "pos_name": name,
                "kios_code": "",
                "kios_name": "",
                "path": f"{reg_info['name']} > {area} > Cabang {p_branch_name} > Pos {name}",
            },
            "latitude": lat,
            "longitude": lng,
            "zipcode": info.get("zipcode", ""),
            "address": info.get("address", ""),
            "status": "Need Verification",
            "coord_status": "OK" if coord_ok else "INVALID",
            "maps_uri": f"https://www.google.com/maps/search/?api=1&query={lat},{lng}" if coord_ok else "",
        })

    # ── Process KIOS ──
    for sc, k in sorted(kios_by_code.items()):
        prefix = sc[:3] if len(sc) >= 3 else sc
        lat_raw = k.get("latitude")
        lng_raw = k.get("longitude")
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (ValueError, TypeError):
            lat, lng = None, None

        # ── KUNCI: Lookup koordinat ke area_coverage untuk mendapatkan pos & cabang YANG BENAR ──
        info = _lookup_coverage(lat, lng)
        cov_pos_code = info.get("pos_code", "") if info else ""
        cov_cabang_code = info.get("cabang_code", "") if info else ""

        name = (k.get("name") or "").strip()
        area = (k.get("area") or "").strip()
        reg_info = get_region_info(area)
        area_color = get_area_color(area)
        b_name = f"FIFGROUP - {name}" if not name.upper().startswith("FIFGROUP") else name

        # Tentukan parent CABANG: prioritas dari lookup coverage, fallback ke prefix
        cabang_code_from_prefix = prefix + "00"
        if cov_cabang_code and cov_cabang_code in cabang_by_code:
            p_branch_code = cov_cabang_code
            p_branch_name = (cabang_by_code[cov_cabang_code].get("name") or "").strip()
        elif cabang_code_from_prefix in cabang_by_code:
            p_branch_code = cabang_code_from_prefix
            p_branch_name = (cabang_by_code[cabang_code_from_prefix].get("name") or "").strip()
        else:
            parent_cabang = cabang_by_prefix.get(prefix) or {}
            p_branch_code = _norm_code(parent_cabang.get("code")) or cabang_code_from_prefix
            p_branch_name = (parent_cabang.get("name") or "").strip()

        # Tentukan parent POS:
        # - Jika coverage pos_code ada DAN berbeda dari cabang_code → KIOS di bawah POS
        # - Jika coverage pos_code == cabang_code → pos sama dengan cabang (POS Utama)
        #   → KIOS tetap dianggap di bawah POS tsb (bukan langsung ke CABANG)
        #   → is_direct_to_branch = False (ada via POS Utama = sama dengan CABANG)
        # - Jika tidak ada pos_code dari coverage → KIOS langsung ke CABANG
        if cov_pos_code and cov_pos_code in pos_by_code:
            # Ada POS yang valid dari coverage
            p_pos_code = cov_pos_code
            p_pos_data = pos_by_code[cov_pos_code]
            p_pos_name = (p_pos_data.get("name") or "").strip()
            is_direct = False
            parent_type = "POS"
            parent_id = p_pos_code
            h_path = f"{reg_info['name']} > {area} > Cabang {p_branch_name} > Pos {p_pos_name} > {name}"
        else:
            # Tidak ada POS yang cocok → langsung ke CABANG
            p_pos_code = ""
            p_pos_name = ""
            is_direct = True
            parent_type = "CABANG"
            parent_id = p_branch_code
            h_path = f"{reg_info['name']} > {area} > Cabang {p_branch_name} > {name} (Langsung)"

        zip_info = info if info else (zip_by_code.get(sc) or {})
        coord_ok = _is_valid_coord(lat, lng)

        processed.append({
            "id": f"kios_{sc}",
            "store_code": sc,
            "branch_prefix": prefix,
            "name": name,
            "business_name": b_name,
            "network_type": "Kios",
            "network_raw": "KIOSK",
            "area": area,
            "area_color": area_color,
            "regional": str(k.get("regional") or "").strip(),
            "region_code": reg_info["code"],
            "region_name": reg_info["name"],
            # Relasi parent-child eksplisit
            "parent_id": parent_id,
            "parent_type": parent_type,
            "hierarchy": {
                "level": "KIOS",
                "region_code": reg_info["code"],
                "region_name": reg_info["name"],
                "area_name": area,
                "area_color": area_color,
                "branch_code": p_branch_code,
                "branch_name": p_branch_name,
                "parent_type": parent_type,
                "is_direct_to_branch": is_direct,
                "pos_code": p_pos_code,
                "pos_name": p_pos_name,
                "kios_code": sc,
                "kios_name": name,
                "path": h_path,
            },
            "latitude": lat,
            "longitude": lng,
            "zipcode": zip_info.get("zipcode", ""),
            "address": zip_info.get("address", ""),
            "status": "Need Verification",
            "coord_status": "OK" if coord_ok else "INVALID",
            "maps_uri": f"https://www.google.com/maps/search/?api=1&query={lat},{lng}" if coord_ok else "",
        })

    log.info(
        f"Loaded {len(processed)} network locations with full hierarchy "
        f"(Cabang: {len(cabang_by_code)}, Pos: {len(pos_by_code)}, Kios: {len(kios_by_code)})"
    )
    return processed


def get_all_network_locations(run_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Mengambil data lokasi network (in-memory cached) dan menggabungkannya dengan
    status terbaru dari database LocationSnapshot jika tersedia.
    """
    global _NETWORK_CACHE, _NETWORK_LAST_MTIME

    if not NETWORK_DATA_FILE.exists():
        return []

    mtime = os.path.getmtime(NETWORK_DATA_FILE)
    if _NETWORK_CACHE is None or _NETWORK_LAST_MTIME != mtime:
        _NETWORK_CACHE = _load_raw_network_locations()
        _NETWORK_LAST_MTIME = mtime

    # Buat copy agar modifikasi per-run tidak merusak cache dasar
    locations = [dict(loc) for loc in _NETWORK_CACHE]

    # Overlay status dari database LocationSnapshot jika ada
    try:
        from gbp.services import history_service
        snapshots = history_service.get_snapshots(run_id=run_id)
        if snapshots:
            snap_by_store = {}
            snap_by_name = {}
            for s in snapshots:
                if s.get("store_code"):
                    snap_by_store[str(s["store_code"]).strip()] = s
                if s.get("business_name"):
                    snap_by_name[str(s["business_name"]).strip().lower()] = s

            for loc in locations:
                sc = loc.get("store_code")
                bn = (loc.get("business_name") or "").lower()
                nm = (loc.get("name") or "").lower()

                matched = snap_by_store.get(sc) or snap_by_name.get(bn) or snap_by_name.get(nm)
                if matched:
                    if matched.get("status"):
                        loc["status"] = matched["status"]
                    if matched.get("maps_uri"):
                        loc["maps_uri"] = matched["maps_uri"]
                    if matched.get("has_vom") is not None:
                        loc["has_vom"] = bool(matched["has_vom"])
                    if matched.get("id"):
                        loc["snapshot_id"] = matched["id"]
    except Exception as e:
        log.warning(f"Error overlaying snapshots on network locations: {e}")

    return locations


def get_network_locations_stats(run_id: Optional[int] = None) -> Dict[str, Any]:
    """Mengembalikan statistik ringkas lokasi network."""
    locs = get_all_network_locations(run_id=run_id)
    with_coords = sum(1 for l in locs if l.get("latitude") is not None and l.get("longitude") is not None)
    without_coords = len(locs) - with_coords

    cabang_count = sum(1 for l in locs if l.get("network_type") == "Cabang")
    pos_count = sum(1 for l in locs if l.get("network_type") == "Pos")
    kios_count = sum(1 for l in locs if l.get("network_type") == "Kios")
    kios_direct_count = sum(
        1 for l in locs
        if l.get("network_type") == "Kios" and l.get("hierarchy", {}).get("is_direct_to_branch")
    )
    kios_via_pos_count = kios_count - kios_direct_count

    return {
        "total": len(locs),
        "with_coords": with_coords,
        "without_coords": without_coords,
        "cabang_count": cabang_count,
        "pos_count": pos_count,
        "kios_count": kios_count,
        "kios_direct_count": kios_direct_count,
        "kios_via_pos_count": kios_via_pos_count,
    }


def get_network_hierarchy_tree() -> List[Dict[str, Any]]:
    """
    Mengembalikan struktur pohon hierarki lengkap:
    REGION -> AREA -> CABANG -> POS & KIOS LANGSUNG
    Digunakan untuk cascading filter, popup breakdown, dan navigasi hierarki.
    """
    locs = get_all_network_locations()
    tree: Dict[str, Dict[str, Any]] = {}

    for loc in locs:
        h = loc.get("hierarchy") or {}
        r_code = h.get("region_code") or "REG-00"
        r_name = h.get("region_name") or "NASIONAL"
        area = h.get("area_name") or loc.get("area") or "UNKNOWN"
        b_code = h.get("branch_code") or ""
        b_name = h.get("branch_name") or ""
        p_code = h.get("pos_code") or ""
        p_name = h.get("pos_name") or ""
        is_direct = h.get("is_direct_to_branch", False)
        n_type = loc.get("network_type")
        area_color = loc.get("area_color") or get_area_color(area)

        if r_code not in tree:
            tree[r_code] = {
                "region_code": r_code,
                "region_name": r_name,
                "areas": {},
            }

        if area not in tree[r_code]["areas"]:
            tree[r_code]["areas"][area] = {
                "area_name": area,
                "area_color": area_color,
                "branches": {},
            }

        if b_code and b_code not in tree[r_code]["areas"][area]["branches"]:
            tree[r_code]["areas"][area]["branches"][b_code] = {
                "branch_code": b_code,
                "branch_name": b_name,
                "area_name": area,
                "area_color": area_color,
                "pos_list": {},
                "direct_kios_list": [],
                "total_pos": 0,
                "total_kios": 0,
                "total_kios_via_pos": 0,
                "total_kios_direct": 0,
            }

        if b_code:
            branch_node = tree[r_code]["areas"][area]["branches"][b_code]
            if n_type == "Pos":
                branch_node["total_pos"] += 1
                pos_key = loc.get("store_code") or p_code
                if pos_key and pos_key not in branch_node["pos_list"]:
                    branch_node["pos_list"][pos_key] = {
                        "pos_code": pos_key,
                        "pos_name": loc.get("name") or p_name,
                        "total_kios": 0,
                        "kios_list": [],
                    }
            elif n_type == "Kios":
                branch_node["total_kios"] += 1
                if is_direct or not p_code:
                    branch_node["total_kios_direct"] += 1
                    branch_node["direct_kios_list"].append({
                        "kios_code": loc.get("store_code"),
                        "kios_name": loc.get("name"),
                    })
                else:
                    branch_node["total_kios_via_pos"] += 1
                    if p_code not in branch_node["pos_list"]:
                        branch_node["pos_list"][p_code] = {
                            "pos_code": p_code,
                            "pos_name": p_name,
                            "total_kios": 0,
                            "kios_list": [],
                        }
                    branch_node["pos_list"][p_code]["total_kios"] += 1
                    branch_node["pos_list"][p_code]["kios_list"].append({
                        "kios_code": loc.get("store_code"),
                        "kios_name": loc.get("name"),
                    })

    # Format menjadi nested lists yang terurut
    result = []
    for r_code, r_data in sorted(tree.items()):
        areas_list = []
        for a_name, a_data in sorted(r_data["areas"].items()):
            branches_list = []
            for b_code, b_data in sorted(a_data["branches"].items(), key=lambda x: x[1]["branch_name"]):
                pos_list = list(b_data["pos_list"].values())
                pos_list.sort(key=lambda x: x["pos_name"])
                branches_list.append({
                    "branch_code": b_code,
                    "branch_name": b_data["branch_name"],
                    "area_name": b_data["area_name"],
                    "area_color": b_data["area_color"],
                    "total_pos": b_data["total_pos"],
                    "total_kios": b_data["total_kios"],
                    "total_kios_via_pos": b_data["total_kios_via_pos"],
                    "total_kios_direct": b_data["total_kios_direct"],
                    "pos_list": pos_list,
                    "direct_kios_list": b_data["direct_kios_list"],
                })
            areas_list.append({
                "area_name": a_name,
                "area_color": a_data["area_color"],
                "branches": branches_list,
            })
        result.append({
            "region_code": r_code,
            "region_name": r_data["region_name"],
            "areas": areas_list,
        })

    return result


def get_all_branch_coverage_polygons() -> Dict[str, Any]:
    """
    Menghasilkan GeoJSON FeatureCollection untuk seluruh Branch Coverage Polygon.
    Setiap poligon dibentuk dari titik-titik Cabang + POS + KIOS miliknya.
    Menggunakan clustering anti-lintas-laut.
    Warna polygon = warna area (dengan opacity yang diatur di frontend).
    """
    global _BRANCH_POLYGONS_CACHE
    if _BRANCH_POLYGONS_CACHE is not None:
        return _BRANCH_POLYGONS_CACHE

    locs = get_all_network_locations()
    branch_groups: Dict[str, Dict[str, Any]] = {}

    for loc in locs:
        h = loc.get("hierarchy") or {}
        b_code = h.get("branch_code") or ""
        if not b_code:
            continue

        b_name = h.get("branch_name") or loc.get("name") or ""
        area = loc.get("area") or ""
        r_name = h.get("region_name") or ""
        area_color = loc.get("area_color") or get_area_color(area)

        if b_code not in branch_groups:
            branch_groups[b_code] = {
                "branch_code": b_code,
                "branch_name": b_name,
                "area": area,
                "region_name": r_name,
                "area_color": area_color,
                "points": [],
                "pos_count": 0,
                "kios_count": 0,
                "kios_direct_count": 0,
                "kios_via_pos_count": 0,
            }

        lat, lng = loc.get("latitude"), loc.get("longitude")
        if lat is not None and lng is not None and _is_valid_coord(lat, lng):
            branch_groups[b_code]["points"].append((float(lng), float(lat)))

        ntype = loc.get("network_type")
        if ntype == "Pos":
            branch_groups[b_code]["pos_count"] += 1
        elif ntype == "Kios":
            branch_groups[b_code]["kios_count"] += 1
            if h.get("is_direct_to_branch"):
                branch_groups[b_code]["kios_direct_count"] += 1
            else:
                branch_groups[b_code]["kios_via_pos_count"] += 1

    features = []
    for b_code, grp in sorted(branch_groups.items()):
        pts = list(set(grp["points"]))
        if not pts:
            continue

        try:
            # Gunakan clustering anti-lintas-laut dengan eps 8km untuk CABANG
            geom = _build_small_cluster_polygons(pts, eps_km=8.0, buffer_deg=0.012)
            if geom is None or geom.is_empty:
                continue

            features.append({
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {
                    "branch_code": b_code,
                    "branch_name": grp["branch_name"],
                    "area": grp["area"],
                    "region_name": grp["region_name"],
                    "area_color": grp["area_color"],
                    "total_points": len(pts),
                    "total_pos": grp["pos_count"],
                    "total_kios": grp["kios_count"],
                    "total_kios_direct": grp["kios_direct_count"],
                    "total_kios_via_pos": grp["kios_via_pos_count"],
                },
            })
        except Exception as e:
            log.warning(f"Error building branch polygon for {b_code}: {e}")

    _BRANCH_POLYGONS_CACHE = {
        "type": "FeatureCollection",
        "features": features,
    }
    log.info(f"Built {len(features)} branch coverage polygons")
    return _BRANCH_POLYGONS_CACHE


def get_all_pos_coverage_polygons() -> Dict[str, Any]:
    """
    Menghasilkan GeoJSON FeatureCollection untuk seluruh Pos Coverage Polygon.
    Setiap Pos mendapat polygon yang melingkupi Kios-kios binaannya.
    Pos tanpa Kios binaan mendapat circle kecil di koordinat Pos itu sendiri.
    """
    global _POS_POLYGONS_CACHE
    if _POS_POLYGONS_CACHE is not None:
        return _POS_POLYGONS_CACHE

    locs = get_all_network_locations()

    # Kumpulkan metadata semua Pos
    pos_groups: Dict[str, Dict[str, Any]] = {}

    for loc in locs:
        if loc.get("network_type") != "Pos":
            continue
        h = loc.get("hierarchy") or {}
        p_code = loc.get("store_code") or ""
        if not p_code:
            continue
        lat_raw, lng_raw = loc.get("latitude"), loc.get("longitude")
        if lat_raw is None or lng_raw is None:
            continue
        if not _is_valid_coord(lat_raw, lng_raw):
            continue
        lat, lng = float(lat_raw), float(lng_raw)
        area = loc.get("area") or ""
        area_color = loc.get("area_color") or get_area_color(area)

        pos_groups[p_code] = {
            "pos_code": p_code,
            "pos_name": loc.get("name") or "",
            "branch_code": h.get("branch_code") or "",
            "branch_name": h.get("branch_name") or "",
            "area": area,
            "region_name": h.get("region_name") or "",
            "area_color": area_color,
            "pos_lat": lat,
            "pos_lng": lng,
            "points": [(lng, lat)],  # include pos itself
            "kios_count": 0,
        }

    # Tambahkan koordinat KIOS yang punya parent POS
    for loc in locs:
        if loc.get("network_type") != "Kios":
            continue
        h = loc.get("hierarchy") or {}
        is_direct = h.get("is_direct_to_branch", False)
        p_code = h.get("pos_code") or ""
        if is_direct or not p_code or p_code not in pos_groups:
            continue
        lat_raw, lng_raw = loc.get("latitude"), loc.get("longitude")
        if lat_raw is None or lng_raw is None:
            continue
        if not _is_valid_coord(lat_raw, lng_raw):
            continue
        pos_groups[p_code]["points"].append((float(lng_raw), float(lat_raw)))
        pos_groups[p_code]["kios_count"] += 1

    features = []
    for p_code, grp in sorted(pos_groups.items()):
        pts = list(set(grp["points"]))
        try:
            if grp["kios_count"] == 0:
                # Tidak ada Kios → circle kecil di koordinat Pos
                geom = Point(grp["pos_lng"], grp["pos_lat"]).buffer(0.006)
            else:
                # Ada Kios → cluster polygon
                geom = _build_small_cluster_polygons(pts, eps_km=3.0, buffer_deg=0.006)
                if geom is None or geom.is_empty:
                    geom = Point(grp["pos_lng"], grp["pos_lat"]).buffer(0.006)

            features.append({
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {
                    "pos_code": p_code,
                    "pos_name": grp["pos_name"],
                    "branch_code": grp["branch_code"],
                    "branch_name": grp["branch_name"],
                    "area": grp["area"],
                    "region_name": grp["region_name"],
                    "area_color": grp["area_color"],
                    "total_kios": grp["kios_count"],
                    "has_kios": grp["kios_count"] > 0,
                },
            })
        except Exception as e:
            log.warning(f"Error building pos polygon for {p_code}: {e}")

    _POS_POLYGONS_CACHE = {
        "type": "FeatureCollection",
        "features": features,
    }
    log.info(f"Built {len(features)} POS coverage polygons")
    return _POS_POLYGONS_CACHE


def invalidate_network_caches() -> None:
    """Reset semua cache network locations & polygon agar di-rebuild saat request berikutnya."""
    global _NETWORK_CACHE, _NETWORK_LAST_MTIME, _BRANCH_POLYGONS_CACHE, _POS_POLYGONS_CACHE
    _NETWORK_CACHE = None
    _NETWORK_LAST_MTIME = 0.0
    _BRANCH_POLYGONS_CACHE = None
    _POS_POLYGONS_CACHE = None
    log.info("Network caches invalidated.")
