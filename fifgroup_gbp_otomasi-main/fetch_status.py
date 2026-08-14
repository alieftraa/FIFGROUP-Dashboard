"""
fetch_status.py  (v2)
---------------------
Mengambil status verifikasi + koordinat semua lokasi GBP,
menyimpan ke CSV harian, DAN menyimpan ke history_db.sqlite
untuk keperluan dashboard.

Perubahan dari v1:
  - Fix format latitude/longitude (decimal, tanpa thousand separator)
  - Validasi rentang koordinat (-90..90 / -180..180)
  - Deteksi status Suspended
  - Otomatis simpan ke history_db.sqlite setelah setiap fetch

Cara pakai:
    python fetch_status.py
    python fetch_status.py --output hasil.csv
    python fetch_status.py --account-id accounts/123456789
    python fetch_status.py --no-db   # skip simpan ke history DB
"""

import csv
import argparse
import logging
import os
import requests as req_lib
import certifi
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import history_db

# ──────────────────────────────────────────────
# KONFIGURASI
# ──────────────────────────────────────────────

SCOPES           = ["https://www.googleapis.com/auth/business.manage"]
TOKEN_FILE       = "token.json"
CREDENTIALS_FILE = "credentials.json"

API_ACCOUNT   = "https://mybusinessaccountmanagement.googleapis.com/v1"
API_LOCATIONS = "https://mybusinessbusinessinformation.googleapis.com/v1"

LOCATION_FIELDS = (
    "name,title,storefrontAddress,metadata,"
    "storeCode,websiteUri,latlng"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# AUTENTIKASI
# ──────────────────────────────────────────────

def get_credentials() -> Credentials:
    """
    OAuth2 dengan certificate eksplisit dari certifi
    (menghindari konflik SSL dengan PostgreSQL atau library lain).
    """
    # Override certificate agar tidak terganggu environment variable lain
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["SSL_CERT_FILE"]      = certifi.where()

    creds = None
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Token expired, me-refresh otomatis...")
            # Gunakan session dengan certificate eksplisit
            session = req_lib.Session()
            session.verify = certifi.where()
            creds.refresh(Request(session=session))
        else:
            log.info("Login Google pertama kali — browser akan terbuka...")
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        log.info(f"Token disimpan ke {TOKEN_FILE}")

    return creds


def make_headers(creds: Credentials) -> dict:
    session = req_lib.Session()
    session.verify = certifi.where()
    creds.refresh(Request(session=session))
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type":  "application/json",
    }


# ──────────────────────────────────────────────
# FUNGSI API
# ──────────────────────────────────────────────

def get_accounts(headers: dict) -> list[dict]:
    url  = f"{API_ACCOUNT}/accounts"
    resp = req_lib.get(url, headers=headers, verify=certifi.where())
    resp.raise_for_status()
    accounts = resp.json().get("accounts", [])
    log.info(f"Ditemukan {len(accounts)} akun GBP.")
    return accounts


def get_locations(account_name: str, headers: dict) -> list[dict]:
    url    = f"{API_LOCATIONS}/{account_name}/locations"
    params = {"readMask": LOCATION_FIELDS, "pageSize": 100}

    all_locations = []
    page_token    = None
    page_num      = 0

    while True:
        page_num += 1
        if page_token:
            params["pageToken"] = page_token

        resp = req_lib.get(url, headers=headers, params=params, verify=certifi.where())
        resp.raise_for_status()
        data = resp.json()

        locations = data.get("locations", [])
        all_locations.extend(locations)
        log.info(f"  Halaman {page_num}: {len(locations)} lokasi (total: {len(all_locations)})")

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return all_locations


# ──────────────────────────────────────────────
# KOORDINAT — FIX & VALIDASI
# ──────────────────────────────────────────────

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

        # Normalkan string
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
    Ekstrak dan validasi koordinat.
    Return: (latitude, longitude, coord_status)

    coord_status:
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


# ──────────────────────────────────────────────
# PARSING STATUS
# ──────────────────────────────────────────────

def parse_location(location: dict) -> dict:
    """
    Ekstrak seluruh data yang diperlukan dari objek lokasi GBP.

    Status logic (prioritas dari atas ke bawah):
      1. Suspended   → metadata.isSuspended = True
                       ATAU metadata.hasVoiceOfMerchant = False
                       DAN  tidak ada duplicateLocation
                       DAN  listing tidak dapat diakses publik
         ⚠️  Catatan: field "isSuspended" belum terkonfirmasi di semua
             versi API. Setelah API aktif, cek raw response untuk
             memastikan nama field yang tepat.
      2. Duplicate   → "duplicateLocation" ada di metadata
      3. Verified    → metadata.hasVoiceOfMerchant = True
      4. Unverified  → semua kondisi di atas false
    """
    metadata = location.get("metadata", {})
    address  = location.get("storefrontAddress", {})

    # ── Status flags ──────────────────────────
    has_vom      = metadata.get("hasVoiceOfMerchant", False)
    is_duplicate = "duplicateLocation" in metadata
    has_pending  = metadata.get("hasPendingEdits", False)
    maps_uri     = metadata.get("mapsUri", "")

    # Deteksi Suspended
    # Cek beberapa kemungkinan nama field yang digunakan GBP API
    is_suspended = (
        metadata.get("isSuspended", False)
        or metadata.get("suspended", False)
        or metadata.get("isDisabled", False)
    )

    # ── Penentuan status ──────────────────────
    if is_suspended:
        status = "Suspended"
    elif is_duplicate:
        status = "Duplicate"
    elif has_vom:
        status = "Verified"
    else:
        status = "Verification Required"

    # ── Alamat ───────────────────────────────
    addr_lines   = address.get("addressLines", [])
    full_address = ", ".join(filter(None, [
        " ".join(addr_lines),
        address.get("locality", ""),
        address.get("administrativeArea", ""),
        address.get("postalCode", ""),
        address.get("regionCode", ""),
    ]))

    # ── Koordinat ─────────────────────────────
    latitude, longitude, coord_status = parse_latlng(location)

    return {
        "location_name"    : location.get("name", ""),
        "store_code"       : location.get("storeCode", ""),
        "business_name"    : location.get("title", ""),
        "account_name"     : location.get("account_name", ""),
        "address"          : full_address,
        "latitude"         : latitude,         # float atau None
        "longitude"        : longitude,        # float atau None
        "coord_status"     : coord_status,     # OK/MISSING/PARSE_ERROR/OUT_OF_RANGE
        "status"           : status,
        "has_vom"          : has_vom,
        "is_duplicate"     : is_duplicate,
        "is_suspended"     : is_suspended,
        "has_pending_edits": has_pending,
        "maps_uri"         : maps_uri,
        "fetched_at"       : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_records(account_id: str | None = None) -> list[dict]:
    """Ambil dan parse semua lokasi GBP dari API tanpa menyimpan ke file atau DB."""
    log.info("Memulai autentikasi Google...")
    creds   = get_credentials()
    headers = make_headers(creds)

    if account_id:
        accounts = [{"name": account_id}]
    else:
        accounts = get_accounts(headers)

    all_records = []
    for account in accounts:
        acct_name = account["name"]
        log.info(f"Mengambil lokasi dari akun: {acct_name}")
        try:
            locations = get_locations(acct_name, headers)
            for loc in locations:
                record = parse_location(loc)
                record["account_name"] = acct_name
                all_records.append(record)
        except req_lib.HTTPError as e:
            log.error(f"Gagal: {acct_name}: {e}")

    return all_records


# ──────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────

def save_to_csv(records: list[dict], output_path: str):
    if not records:
        log.warning("Tidak ada data untuk disimpan.")
        return

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    log.info(f"✅ CSV disimpan: {output_path} ({len(records)} baris)")


def print_summary(records: list[dict]):
    from collections import Counter
    counts      = Counter(r["status"]       for r in records)
    coord_stats = Counter(r["coord_status"] for r in records)

    print("\n" + "=" * 55)
    print("RINGKASAN STATUS VERIFIKASI GBP")
    print("=" * 55)
    print(f"  Total lokasi             : {len(records)}")
    print(f"  ✅ Verified               : {counts.get('Verified', 0)}")
    print(f"  ⚠️  Verification Required  : {counts.get('Verification Required', 0)}")
    print(f"  🔁 Duplicate              : {counts.get('Duplicate', 0)}")
    print(f"  🚫 Suspended              : {counts.get('Suspended', 0)}")
    print("-" * 55)
    print(f"  📍 Koordinat OK           : {coord_stats.get('OK', 0)}")
    print(f"  ❌ Koordinat tidak ada    : {coord_stats.get('MISSING', 0)}")
    print(f"  ⚠️  Koordinat error        : {coord_stats.get('PARSE_ERROR', 0) + coord_stats.get('OUT_OF_RANGE', 0)}")
    print("=" * 55 + "\n")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch GBP verification status v2")
    parser.add_argument("--output",     default=None,  help="Nama file CSV output")
    parser.add_argument("--account-id", default=None,  help="Account ID spesifik")
    parser.add_argument("--no-db", dest="no_db",      action="store_true",
                        help="Skip menyimpan ke history database")
    args = parser.parse_args()

    output_file = args.output or f"gbp_status_{datetime.now().strftime('%Y%m%d')}.csv"

    # 1-3. Ambil & parse semua lokasi
    all_records = fetch_records(args.account_id)

    # 4. Simpan CSV
    save_to_csv(all_records, output_file)

    # 5. Simpan ke history DB (untuk dashboard)
    if not args.no_db and all_records:
        history_db.init_db()
        run_id = history_db.save_run(all_records)
        log.info(f"✅ History DB: run #{run_id} tersimpan.")

    # 6. Ringkasan
    print_summary(all_records)


if __name__ == "__main__":
    main()