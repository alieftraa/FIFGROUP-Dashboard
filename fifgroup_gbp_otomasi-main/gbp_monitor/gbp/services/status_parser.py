"""
status_parser.py — Service untuk parsing status verifikasi dan koordinat GBP.
Dimigrasikan dari fetch_status.py (fungsi _parse_float, parse_latlng, parse_location).

Logika status (prioritas dari atas ke bawah):
  1. Suspended   → metadata.isSuspended/suspended/isDisabled = True
  2. Duplicate   → "duplicateLocation" ada di metadata
  3. Verified    → metadata.hasVoiceOfMerchant = True
  4. Verification Required → semua kondisi di atas False
"""

import logging
from datetime import datetime

log = logging.getLogger("gbp.services.status_parser")


# ── Koordinat ─────────────────────────────────────────────────────────

def _parse_float(value) -> float | None:
    """
    Parse nilai koordinat dari API response menjadi float bersih.

    Masalah yang ditangani:
      - Nilai bertipe int/float dari JSON → langsung cast
      - String dengan koma sebagai desimal  (misal: "-6,2672318")
      - String dengan titik ribuan          (misal: "-6.267.2318")

    Return None jika tidak bisa diparsing.
    """
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)

        s = str(value).strip()

        # Jika ada koma dan tidak ada titik → koma adalah desimal
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        # Jika ada koma DAN titik → titik adalah ribuan, koma adalah desimal
        elif "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        # Jika ada lebih dari satu titik → titik pertama adalah ribuan
        elif s.count(".") > 1:
            parts = s.split(".")
            s = "".join(parts[:-1]) + "." + parts[-1]

        return float(s)

    except (ValueError, TypeError):
        return None


def parse_latlng(location: dict) -> tuple[float | None, float | None, str]:
    """
    Ekstrak dan validasi koordinat dari objek lokasi GBP.

    Returns:
        Tuple (latitude, longitude, coord_status) dimana coord_status adalah:
          "OK"           → koordinat valid
          "MISSING"      → tidak ada di response API
          "PARSE_ERROR"  → ada nilai tapi tidak bisa diparsing
          "OUT_OF_RANGE" → nilai di luar rentang valid
    """
    raw = location.get("latlng", {})
    if not raw:
        return None, None, "MISSING"

    lat = _parse_float(raw.get("latitude"))
    lng = _parse_float(raw.get("longitude"))

    if lat is None or lng is None:
        return None, None, "PARSE_ERROR"

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return lat, lng, "OUT_OF_RANGE"

    return lat, lng, "OK"


# ── Status & Lokasi ───────────────────────────────────────────────────

def parse_location(location: dict) -> dict:
    """
    Ekstrak seluruh data yang diperlukan dari objek lokasi GBP.

    Prioritas status:
      1. Suspended   → metadata.isSuspended/suspended/isDisabled = True
      2. Duplicate   → "duplicateLocation" ada di metadata
      3. Verified    → metadata.hasVoiceOfMerchant = True
      4. Need Verification → semua kondisi di atas False

    Returns:
        Dict berisi semua field yang diperlukan untuk LocationSnapshot.
    """
    metadata = location.get("metadata", {})
    address = location.get("storefrontAddress", {})

    # ── Status flags ──────────────────────────────────────────────────
    has_vom = metadata.get("hasVoiceOfMerchant", False)
    is_duplicate = "duplicateLocation" in metadata
    has_pending = metadata.get("hasPendingEdits", False)
    maps_uri = metadata.get("mapsUri", "")

    # Deteksi Suspended: cek beberapa kemungkinan nama field GBP API
    is_suspended = (
        metadata.get("isSuspended", False)
        or metadata.get("suspended", False)
        or metadata.get("isDisabled", False)
    )

    # ── Penentuan status (prioritas) ──────────────────────────────────
    if is_suspended:
        status = "Suspended"
    elif is_duplicate:
        status = "Duplicate"
    elif has_vom:
        status = "Verified"
    else:
        status = "Need Verification"

    # ── Alamat ────────────────────────────────────────────────────────
    addr_lines = address.get("addressLines", [])
    full_address = ", ".join(filter(None, [
        " ".join(addr_lines),
        address.get("locality", ""),
        address.get("administrativeArea", ""),
        address.get("postalCode", ""),
        address.get("regionCode", ""),
    ]))

    # ── Koordinat ─────────────────────────────────────────────────────
    latitude, longitude, coord_status = parse_latlng(location)

    return {
        "location_name": location.get("name", ""),
        "store_code": location.get("storeCode", ""),
        "business_name": location.get("title", ""),
        "account_name": location.get("account_name", ""),
        "address": full_address,
        "latitude": latitude,
        "longitude": longitude,
        "coord_status": coord_status,
        "status": status,
        "has_vom": has_vom,
        "is_duplicate": is_duplicate,
        "is_suspended": is_suspended,
        "has_pending_edits": has_pending,
        "maps_uri": maps_uri,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
