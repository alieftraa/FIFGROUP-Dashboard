"""
gbp_api.py — Service untuk autentikasi dan pengambilan data dari Google Business Profile API.
Dimigrasikan dari fetch_status.py.

Penggunaan:
    from gbp.services.gbp_api import fetch_records
    records = fetch_records(account_id=None)
"""

import logging
import os
from pathlib import Path

import certifi
import requests as req_lib
from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

log = logging.getLogger("gbp.services.gbp_api")

# ── Konfigurasi ──────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/business.manage"]

API_ACCOUNT = "https://mybusinessaccountmanagement.googleapis.com/v1"
API_LOCATIONS = "https://mybusinessbusinessinformation.googleapis.com/v1"

LOCATION_FIELDS = (
    "name,title,storefrontAddress,metadata,"
    "storeCode,websiteUri,latlng"
)


# ── Helper: resolve path ──────────────────────────────────────────────

def _get_credentials_path() -> Path:
    """
    Kembalikan absolute Path untuk credentials.json.
    Sumber kebenaran tunggal: settings.GBP_CREDENTIALS_PATH (sudah di-resolve di settings.py).
    """
    raw = getattr(settings, "GBP_CREDENTIALS_PATH", None)
    if raw is None:
        # Fallback aman jika settings belum dikonfigurasi
        base = Path(__file__).resolve().parent.parent.parent
        return base / "data" / "credentials.json"
    return Path(raw).resolve()


def _get_token_path() -> Path:
    """
    Kembalikan absolute Path untuk token.json.
    Sumber kebenaran tunggal: settings.GBP_TOKEN_PATH (sudah di-resolve di settings.py).
    """
    raw = getattr(settings, "GBP_TOKEN_PATH", None)
    if raw is None:
        base = Path(__file__).resolve().parent.parent.parent
        return base / "data" / "token.json"
    return Path(raw).resolve()


# ── Helper: HTTP error handling ───────────────────────────────────────

def _extract_google_error_detail(response) -> dict:
    """
    Ekstrak detail error dari Google API response body secara aman.
    Tidak menampilkan credential apapun.
    """
    detail = {"reason": None, "message": None, "retry_after": None, "raw_status": None}
    if response is None:
        return detail

    detail["retry_after"] = response.headers.get("Retry-After")
    detail["raw_status"] = response.status_code

    try:
        body = response.json()
        err = body.get("error", {})
        if isinstance(err, dict):
            detail["message"] = err.get("message")
            detail["reason"] = err.get("status") or err.get("code")
            errors = err.get("errors", [])
            if errors and isinstance(errors, list):
                first = errors[0]
                if not detail["reason"]:
                    detail["reason"] = first.get("reason")
                if not detail["message"]:
                    detail["message"] = first.get("message")
    except Exception:
        pass  # response bukan JSON — tidak apa-apa

    return detail


def _handle_http_error(exc: req_lib.HTTPError, context: str = "") -> None:
    """
    Tangani HTTP error dari Google API dengan pesan yang informatif.
    Ekstrak reason/message/Retry-After dari response body Google.
    Selalu me-raise ulang dengan pesan yang lebih jelas.
    """
    status_code = exc.response.status_code if exc.response is not None else None
    prefix = f"[{context}] " if context else ""
    detail = _extract_google_error_detail(exc.response)

    def _detail_lines() -> str:
        lines = []
        if detail["reason"]:
            lines.append(f"  Reason     : {detail['reason']}")
        if detail["message"]:
            lines.append(f"  Message    : {detail['message']}")
        if detail["retry_after"]:
            lines.append(f"  Retry-After: {detail['retry_after']} detik")
        return ("\n" + "\n".join(lines)) if lines else ""

    if status_code == 401:
        raise PermissionError(
            f"{prefix}Google API Authentication Failed (401)\n"
            "Token tidak valid atau sudah tidak dapat diperbarui.\n"
            "Solusi: Hapus token.json dan lakukan autentikasi ulang:\n"
            f"  Lokasi token: {_get_token_path()}\n"
            "  Kemudian jalankan: python manage.py fetch_gbp_status"
            f"{_detail_lines()}"
        ) from exc
    elif status_code == 403:
        raise PermissionError(
            f"{prefix}Google API Permission Denied (403)\n"
            "Akun Google berhasil login tetapi tidak memiliki akses ke "
            "Business Profile API atau account yang diminta.\n"
            "Pastikan:\n"
            "  1. Akun Google memiliki akses ke Google Business Profile.\n"
            "  2. Google Business Profile API sudah diaktifkan di Google Cloud Console.\n"
            "  3. OAuth Client ID memiliki scope yang benar."
            f"{_detail_lines()}"
        ) from exc
    elif status_code == 404:
        raise ValueError(
            f"{prefix}Google API Not Found (404)\n"
            "Resource yang diminta tidak ditemukan. Periksa account_id yang digunakan."
            f"{_detail_lines()}"
        ) from exc
    elif status_code == 429:
        raise RuntimeError(
            f"{prefix}Google API Rate Limited (429)\n"
            "Quota atau rate limit Google API terlampaui."
            f"{_detail_lines()}\n\n"
            "Kemungkinan penyebab:\n"
            "  - Quota harian Google Business Profile API habis\n"
            "  - Terlalu banyak request dalam waktu singkat\n"
            "  - Token baru saja dibuat (throttle sementara)\n"
            "Tunggu beberapa menit lalu coba jalankan ulang."
        ) from exc
    else:
        raise RuntimeError(
            f"{prefix}Google API Error ({status_code}): {exc}"
            f"{_detail_lines()}"
        ) from exc


# ── Helper: Retry dengan exponential backoff ──────────────────────────

def _request_with_retry(
    url: str,
    headers: dict,
    params: dict | None = None,
    context: str = "",
    max_attempts: int = 3,
) -> req_lib.Response:
    """
    Lakukan GET request ke Google API dengan bounded exponential backoff.

    Retry hanya untuk 429 (rate limit) dan 503 (service unavailable).
    Untuk error lain (401, 403, 404, 5xx selain 503) langsung raise.

    Backoff strategy untuk 429 (Requests per minute limit):
      Attempt 1: langsung
      Attempt 2: tunggu Retry-After (jika ada) atau 15 detik + jitter
      Attempt 3: tunggu Retry-After (jika ada) atau 35 detik + jitter

    Args:
        url: URL endpoint Google API
        headers: Authorization headers
        params: Query params opsional
        context: Nama konteks untuk logging (misal 'get_accounts')
        max_attempts: Jumlah maksimal percobaan (default: 3)
    """
    import time
    import random
    from datetime import datetime

    RETRYABLE = {429, 503}
    last_exc = None

    for attempt in range(1, max_attempts + 1):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"[GBP API] [{context}] Request attempt #{attempt}/{max_attempts} | Endpoint: {url} | Timestamp: {ts}")
        log.debug(f"[GBP API] [{context}] GET {url} params={list((params or {}).keys())}")

        try:
            resp = req_lib.get(url, headers=headers, params=params, verify=certifi.where(), timeout=60)
            log.info(f"[GBP API] [{context}] Response status: {resp.status_code}")
            resp.raise_for_status()
            return resp

        except req_lib.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            log.warning(f"[GBP API] [{context}] Response status: {status_code}")

            if status_code not in RETRYABLE or attempt == max_attempts:
                # Tidak bisa di-retry atau sudah habis attempt → raise dengan detail
                _handle_http_error(e, context=context)

            # Tentukan waktu tunggu: prioritaskan Retry-After dari header Google
            detail = _extract_google_error_detail(e.response)
            retry_after = detail.get("retry_after")

            if retry_after:
                try:
                    wait = float(retry_after) + random.uniform(0.5, 2.0)
                    log.info(
                        f"[GBP API] [{context}] Rate limited ({status_code}). "
                        f"Retry-After dari Google: {wait:.1f} detik. "
                        f"Attempt {attempt+1}/{max_attempts} dalam {wait:.1f}s..."
                    )
                except (ValueError, TypeError):
                    wait = 15.0 * (2 ** (attempt - 1)) + random.uniform(1.0, 3.0)
            else:
                # Exponential backoff disesuaikan untuk rate limit per-menit
                if status_code == 429:
                    wait = (15.0 * attempt) + random.uniform(1.0, 4.0)
                else:
                    wait = (2.0 * (2 ** (attempt - 1))) + random.uniform(0.5, 1.5)

                log.info(
                    f"[GBP API] [{context}] Rate limited ({status_code}). "
                    f"Retrying in {wait:.1f} seconds to allow quota window reset... "
                    f"(attempt {attempt+1}/{max_attempts})"
                )

            if detail.get("reason"):
                log.info(f"[GBP API] [{context}]   Reason : {detail['reason']}")
            if detail.get("message"):
                log.info(f"[GBP API] [{context}]   Message: {detail['message']}")

            time.sleep(wait)
            last_exc = e

        except req_lib.RequestException as e:
            # Connection error / timeout — raise langsung, tidak retry
            raise RuntimeError(
                f"[GBP API] [{context}] Koneksi ke Google API gagal: {e}"
            ) from e

    # Seharusnya tidak tercapai, tapi sebagai safety net:
    if last_exc:
        _handle_http_error(last_exc, context=context)
    raise RuntimeError(f"[GBP API] [{context}] Request gagal setelah {max_attempts} percobaan.")


# ── Autentikasi ───────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    """
    Autentikasi OAuth2 dengan Google.

    Alur:
    1. Jika token.json ada dan valid → gunakan langsung.
    2. Jika token expired dan refresh_token tersedia → refresh otomatis.
    3. Jika token tidak ada → jalankan OAuth browser flow (membutuhkan credentials.json).
    4. Jika credentials.json tidak ditemukan → raise FileNotFoundError dengan instruksi jelas.

    Path credentials dan token dibaca dari Django settings sebagai single source of truth
    (GBP_CREDENTIALS_PATH dan GBP_TOKEN_PATH, keduanya sudah absolute path dari settings.py).
    """
    # Override certificate agar tidak terganggu environment variable lain
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["SSL_CERT_FILE"] = certifi.where()

    credentials_path = _get_credentials_path()
    token_path = _get_token_path()

    log.info(f"[GBP] Credential path: {credentials_path}")
    log.info(f"[GBP] Token path: {token_path}")

    # Pastikan direktori untuk token.json ada sebelum menyimpan
    token_path.parent.mkdir(parents=True, exist_ok=True)

    creds = None

    # ── Langkah 1: Coba load token yang sudah ada ──────────────────
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            log.info("[GBP] Token ditemukan, memvalidasi...")
        except Exception as e:
            log.warning(f"[GBP] Token tidak bisa dimuat (akan diregenerasi): {e}")
            creds = None

    # ── Langkah 2: Validasi / refresh / buat baru ─────────────────
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired tapi refresh token tersedia → refresh otomatis
            log.info("[GBP] Token expired. Melakukan refresh token otomatis...")
            try:
                session = req_lib.Session()
                session.verify = certifi.where()
                creds.refresh(Request(session=session))
                log.info("[GBP] Token berhasil di-refresh.")
            except Exception as e:
                log.warning(f"[GBP] Refresh token gagal: {e}. Akan mencoba OAuth flow ulang.")
                creds = None

        if not creds or not creds.valid:
            # Perlu OAuth browser flow — butuh credentials.json
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"\n{'='*60}\n"
                    f"OAuth credentials tidak ditemukan.\n\n"
                    f"Expected path:\n"
                    f"  {credentials_path}\n\n"
                    f"Silakan:\n"
                    f"  1. Buka Google Cloud Console: https://console.cloud.google.com/\n"
                    f"  2. Pilih project Anda → APIs & Services → Credentials.\n"
                    f"  3. Download OAuth 2.0 Client JSON.\n"
                    f"  4. Rename menjadi: credentials.json\n"
                    f"  5. Simpan ke lokasi: {credentials_path}\n\n"
                    f"Catatan:\n"
                    f"  Application Type yang direkomendasikan adalah Desktop App.\n"
                    f"{'='*60}"
                )

            log.info("[GBP OAuth] Memulai OAuth browser flow...")
            log.info("[GBP OAuth] Starting local callback server")
            log.info("[GBP OAuth] Host: 127.0.0.1 (IPv4 loopback eksplisit)")
            log.info("[GBP OAuth] Port: dynamic (ditentukan OS)")
            log.info("[GBP OAuth] Waiting for authorization callback...")
            log.info("[GBP OAuth] Browser akan terbuka untuk login Google. Jangan tutup terminal ini.")

            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            try:
                creds = flow.run_local_server(
                    host="127.0.0.1",  # eksplisit IPv4 — hindari localhost→IPv6 issue di Windows
                    port=0,            # port dinamis dari OS
                    open_browser=True,
                )
            except KeyboardInterrupt:
                raise KeyboardInterrupt(
                    "\n[GBP OAuth] OAuth flow dibatalkan oleh user (Ctrl+C).\n"
                    "Token tidak disimpan. Jalankan ulang untuk autentikasi."
                )
            except Exception as oauth_exc:
                raise RuntimeError(
                    f"\n[GBP OAuth] OAuth callback gagal diterima: {oauth_exc}\n\n"
                    "Browser berhasil membuka Google login tetapi tidak dapat terhubung\n"
                    "ke local callback server.\n\n"
                    "Pastikan:\n"
                    "  1. Python process masih berjalan saat redirect terjadi.\n"
                    "  2. Firewall/antivirus tidak memblokir Python pada port lokal.\n"
                    "  3. Callback menggunakan 127.0.0.1, bukan localhost.\n\n"
                    "Coba jalankan ulang: python manage.py fetch_gbp_status"
                ) from oauth_exc

            log.info("[GBP OAuth] Authorization callback diterima. OAuth berhasil.")

        # Simpan token baru / yang sudah di-refresh
        try:
            with open(str(token_path), "w") as f:
                f.write(creds.to_json())
            log.info(f"[GBP] Token disimpan ke: {token_path}")
        except IOError as e:
            log.error(f"[GBP] Gagal menyimpan token: {e}")
    else:
        log.info("[GBP] Token ditemukan dan valid. Tidak perlu login ulang.")

    return creds


def make_headers(creds: Credentials) -> dict:
    """
    Buat HTTP headers dengan Authorization Bearer token.
    Hanya refresh token jika mendekati expired atau tidak valid.
    """
    if not creds.valid or creds.expired:
        log.debug("[GBP] Token tidak valid/expired di make_headers, melakukan refresh...")
        session = req_lib.Session()
        session.verify = certifi.where()
        try:
            creds.refresh(Request(session=session))
        except Exception as e:
            raise RuntimeError(
                f"[GBP] Gagal refresh token di make_headers: {e}\n"
                f"Hapus token.json dan lakukan autentikasi ulang:\n"
                f"  Lokasi: {_get_token_path()}"
            ) from e

    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }


# ── Cache & Concurrency Control untuk Accounts ─────────────────────────
_ACCOUNTS_CACHE: list[dict] | None = None
_ACCOUNTS_CACHE_TIME: float = 0
_ACCOUNTS_CACHE_TTL: float = 86400.0  # 24 jam dalam detik
_FETCH_LOCK = None


def _get_fetch_lock():
    global _FETCH_LOCK
    if _FETCH_LOCK is None:
        import threading
        _FETCH_LOCK = threading.Lock()
    return _FETCH_LOCK


def _get_accounts_cache_path() -> Path:
    """Path file untuk menyimpan cache akun GBP secara persisten."""
    raw = getattr(settings, "GBP_DATA_DIR", None)
    if raw:
        return Path(raw).resolve() / "accounts_cache.json"
    base = Path(__file__).resolve().parent.parent.parent
    return base / "data" / "accounts_cache.json"


# ── Fungsi API ────────────────────────────────────────────────────────

def get_accounts(headers: dict, force_refresh: bool = False) -> list[dict]:
    """
    Ambil semua akun GBP yang dapat diakses dengan proteksi caching.

    Untuk mencegah 429 RESOURCE_EXHAUSTED pada service
    mybusinessaccountmanagement.googleapis.com, hasil get_accounts di-cache
    di memori dan file disk.
    """
    global _ACCOUNTS_CACHE, _ACCOUNTS_CACHE_TIME
    import time
    import json

    now = time.time()
    cache_path = _get_accounts_cache_path()

    # 1. Cek in-memory cache
    if not force_refresh and _ACCOUNTS_CACHE is not None:
        if (now - _ACCOUNTS_CACHE_TIME) < _ACCOUNTS_CACHE_TTL:
            log.info(f"[GBP API] [get_accounts] Menggunakan memory cache ({len(_ACCOUNTS_CACHE)} akun).")
            return _ACCOUNTS_CACHE

    # 2. Cek persistent disk cache
    if not force_refresh and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if isinstance(cached_data, list) and len(cached_data) > 0:
                    _ACCOUNTS_CACHE = cached_data
                    _ACCOUNTS_CACHE_TIME = now
                    log.info(f"[GBP API] [get_accounts] Menggunakan persistent disk cache dari {cache_path} ({len(cached_data)} akun).")
                    return cached_data
        except Exception as e:
            log.warning(f"[GBP API] [get_accounts] Gagal membaca cache file: {e}")

    # 3. Request ke Google API
    log.info("[GBP API] [get_accounts] Mengambil daftar Business Accounts dari Google API...")
    url = f"{API_ACCOUNT}/accounts"
    log.info(f"[GBP API] [get_accounts] Endpoint: {url}")

    resp = _request_with_retry(url, headers=headers, context="get_accounts")

    accounts = resp.json().get("accounts", [])
    log.info(f"[GBP API] [get_accounts] Account ditemukan dari Google API: {len(accounts)}")

    if not accounts:
        log.warning(
            "[GBP API] Tidak ada Business Account ditemukan.\n"
            "Pastikan akun Google yang digunakan memiliki akses ke Google Business Profile."
        )
    else:
        # Simpan ke cache
        _ACCOUNTS_CACHE = accounts
        _ACCOUNTS_CACHE_TIME = now
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(accounts, f, indent=2)
            log.info(f"[GBP API] [get_accounts] Berhasil menyimpan akun ke cache disk: {cache_path}")
        except Exception as e:
            log.warning(f"[GBP API] [get_accounts] Gagal menyimpan cache akun ke disk: {e}")

    return accounts


def get_locations(account_name: str, headers: dict) -> list[dict]:
    """
    Ambil semua lokasi dari satu akun GBP dengan paginasi otomatis.
    Setiap page request menggunakan bounded exponential backoff untuk 429.

    Args:
        account_name: Nama akun GBP (format: "accounts/123456789")
        headers: HTTP headers dengan Authorization Bearer token
    """
    log.info(f"[GBP API] Mengambil locations dari akun: {account_name}")
    url = f"{API_LOCATIONS}/{account_name}/locations"
    params = {"readMask": LOCATION_FIELDS, "pageSize": 100}

    all_locations: list[dict] = []
    page_token = None
    page_num = 0

    while True:
        page_num += 1
        if page_token:
            params["pageToken"] = page_token
        elif "pageToken" in params:
            del params["pageToken"]

        resp = _request_with_retry(
            url,
            headers=headers,
            params=params,
            context=f"get_locations page {page_num}",
        )

        data = resp.json()
        locations = data.get("locations", [])
        all_locations.extend(locations)
        log.info(f"[GBP API] Page {page_num}: {len(locations)} locations (total: {len(all_locations)})")

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    log.info(f"[GBP API] Total fetched dari {account_name}: {len(all_locations)} locations")
    return all_locations


# ── Fetch Utama ───────────────────────────────────────────────────────

def fetch_records(account_id: str | None = None, force_refresh_accounts: bool = False) -> list[dict]:
    """
    Ambil dan parse semua lokasi GBP dari API dengan thread safety lock.

    Args:
        account_id: Account ID spesifik (format: "accounts/123456789").
                    Jika None, periksa settings.GBP_DEFAULT_ACCOUNT_ID atau ambil dari cache/API.
        force_refresh_accounts: Jika True, paksa refresh daftar akun dari Google API.

    Returns:
        List of dict berisi data lokasi yang sudah diparsing.

    Raises:
        FileNotFoundError: Jika credentials.json tidak ditemukan.
        PermissionError: Jika 401/403 dari Google API.
        RuntimeError: Jika error lain dari Google API.
    """
    from gbp.services.status_parser import parse_location  # avoid circular import

    # Gunakan lock untuk mencegah multiple fetch dieksekusi secara bersamaan (mencegah burst request ganda)
    lock = _get_fetch_lock()
    if not lock.acquire(blocking=False):
        raise RuntimeError("Proses fetch data GBP sedang berjalan di background. Mohon tunggu proses sebelumnya selesai.")

    try:
        log.info("[GBP] ══════════════════════════════════════════════════")
        log.info("[GBP] Memulai fetch Google Business Profile...")
        log.info(f"[GBP] Credential path: {_get_credentials_path()}")
        log.info(f"[GBP] Token path: {_get_token_path()}")

        creds = get_credentials()
        headers = make_headers(creds)

        default_account = getattr(settings, "GBP_DEFAULT_ACCOUNT_ID", "")
        target_account = account_id or (default_account if default_account else None)

        if target_account:
            log.info(f"[GBP] Menggunakan account ID spesifik/default: {target_account}")
            accounts = [{"name": target_account}]
        else:
            accounts = get_accounts(headers, force_refresh=force_refresh_accounts)

        if not accounts:
            log.warning("[GBP] Tidak ada akun yang ditemukan. Fetch dihentikan.")
            return []

        all_records: list[dict] = []
        for account in accounts:
            acct_name = account["name"]
            log.info(f"[GBP] Mengambil lokasi dari akun: {acct_name}")
            try:
                locations = get_locations(acct_name, headers)
                for loc in locations:
                    record = parse_location(loc)
                    record["account_name"] = acct_name
                    all_records.append(record)
            except (PermissionError, ValueError, RuntimeError) as e:
                # Error spesifik dari Google API — log dan lanjutkan ke akun berikutnya
                log.error(f"[GBP] Gagal mengambil lokasi dari {acct_name}: {e}")
            except req_lib.HTTPError as e:
                _handle_http_error(e, context=f"fetch_records({acct_name})")

        log.info(f"[GBP] ══════════════════════════════════════════════════")
        log.info(f"[GBP] Total fetched: {len(all_records)} lokasi dari {len(accounts)} akun.")
        return all_records

    finally:
        lock.release()


# ── Guard untuk Web Request ───────────────────────────────────────────

def check_oauth_ready() -> tuple[bool, str]:
    """
    Periksa apakah OAuth sudah siap digunakan (token ada, atau credentials.json tersedia).

    Returns:
        (True, "") jika OAuth siap.
        (False, pesan_error) jika OAuth belum siap.

    Digunakan oleh views.py untuk memberikan error yang informatif tanpa
    menggantung request karena menunggu browser OAuth flow.
    """
    token_path = _get_token_path()
    cred_path = _get_credentials_path()

    if token_path.exists():
        # Token ada — coba validasi cepat tanpa network call
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if creds.valid or (creds.expired and creds.refresh_token):
                return True, ""
        except Exception:
            pass

    if cred_path.exists():
        # Credentials ada, tapi token belum ada/invalid → perlu OAuth flow dari CLI
        return False, (
            "OAuth belum diinisialisasi. Token tidak ditemukan atau tidak valid.\n\n"
            "Jalankan perintah berikut untuk melakukan autentikasi pertama kali:\n\n"
            "    cd gbp_monitor\n"
            "    python manage.py fetch_gbp_status\n\n"
            "Browser akan terbuka untuk login Google. Setelah login berhasil,\n"
            "token akan disimpan dan Update Status dari web dapat digunakan."
        )

    # Credentials juga tidak ada
    return False, (
        f"OAuth credentials tidak ditemukan.\n\n"
        f"Expected path:\n"
        f"  {cred_path}\n\n"
        f"Silakan:\n"
        f"  1. Download OAuth 2.0 Client JSON dari Google Cloud Console.\n"
        f"  2. Rename menjadi credentials.json.\n"
        f"  3. Simpan ke lokasi di atas.\n\n"
        f"Kemudian jalankan: python manage.py fetch_gbp_status"
    )
