"""
scheduler.py
------------
Menjalankan fetch + update database secara otomatis setiap hari.
Bisa dijalankan sebagai background process atau via cron/Task Scheduler.

Cara pakai:
    # Jalankan sekarang (sekali)
    python scheduler.py --run-now

    # Jalankan loop harian otomatis (jam 08:00 setiap hari)
    python scheduler.py --schedule 08:00

    # Custom waktu
    python scheduler.py --schedule 06:30
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# KONFIGURASI — sesuaikan dengan setup kamu
# ──────────────────────────────────────────────
CONFIG = {
    "db_file"    : "database_kios.csv",   # path ke database kios
    "db_mode"    : "csv",                 # "csv" atau "sqlite"
    "db_table"   : "kios",               # hanya untuk mode sqlite
    "db_key_col" : "kode_kios",          # kolom kunci di database kios
    "account_id" : "",                   # kosongkan = ambil semua akun
    "log_dir"    : "logs",               # folder untuk menyimpan log harian
}
# ──────────────────────────────────────────────


def run_pipeline():
    """Jalankan fetch_status.py → update_database.py secara berurutan."""
    today     = datetime.now().strftime("%Y%m%d")
    gbp_file  = f"gbp_status_{today}.csv"
    log_dir   = Path(CONFIG["log_dir"])
    log_dir.mkdir(exist_ok=True)
    log_file  = log_dir / f"run_{today}.log"

    log.info("=" * 55)
    log.info(f"Memulai pipeline GBP — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 55)

    # ── STEP 1: Fetch status dari GBP ──────────────
    log.info("STEP 1/2 — Fetch status verifikasi dari GBP API...")
    fetch_cmd = [
        sys.executable, "fetch_status.py",
        "--output", gbp_file,
    ]
    if CONFIG["account_id"]:
        fetch_cmd += ["--account-id", CONFIG["account_id"]]

    result = subprocess.run(fetch_cmd, capture_output=True, text=True)
    _log_subprocess(result, log_file, "fetch_status")

    if result.returncode != 0:
        log.error("❌ fetch_status.py gagal. Pipeline dihentikan.")
        return False

    # ── STEP 2: Update database ────────────────────
    log.info("STEP 2/2 — Update database kios...")
    update_cmd = [
        sys.executable, "update_database.py",
        "--gbp-file",    gbp_file,
        "--db-file",     CONFIG["db_file"],
        "--mode",        CONFIG["db_mode"],
        "--db-key-col",  CONFIG["db_key_col"],
    ]
    if CONFIG["db_mode"] == "sqlite":
        update_cmd += ["--table", CONFIG["db_table"]]

    result = subprocess.run(update_cmd, capture_output=True, text=True)
    _log_subprocess(result, log_file, "update_database")

    if result.returncode != 0:
        log.error("❌ update_database.py gagal.")
        return False

    log.info("✅ Pipeline selesai sukses.")
    return True


def _log_subprocess(result, log_file: Path, label: str):
    """Tulis output subprocess ke file log."""
    with open(log_file, "a") as f:
        f.write(f"\n--- {label} ---\n")
        f.write(result.stdout or "")
        if result.stderr:
            f.write("\nSTDERR:\n" + result.stderr)
    if result.stdout:
        log.info(result.stdout.strip())
    if result.stderr and result.returncode != 0:
        log.error(result.stderr.strip())


def wait_until(target_time_str: str):
    """Tunggu hingga jam target (format HH:MM)."""
    now = datetime.now()
    h, m = map(int, target_time_str.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)

    if target <= now:
        # Sudah lewat untuk hari ini → tunggu besok
        target += timedelta(days=1)

    wait_seconds = (target - now).total_seconds()
    log.info(f"Menunggu hingga {target.strftime('%Y-%m-%d %H:%M:%S')} "
             f"({wait_seconds / 3600:.1f} jam lagi)...")
    time.sleep(wait_seconds)


def main():
    parser = argparse.ArgumentParser(description="Scheduler pipeline GBP harian")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-now",  action="store_true", help="Jalankan sekarang sekali")
    group.add_argument("--schedule", metavar="HH:MM",     help="Jalankan otomatis setiap hari jam ini")
    args = parser.parse_args()

    if args.run_now:
        run_pipeline()
    else:
        log.info(f"Scheduler aktif. Pipeline akan berjalan setiap hari jam {args.schedule}.")
        log.info("Tekan Ctrl+C untuk menghentikan.\n")
        try:
            while True:
                wait_until(args.schedule)
                run_pipeline()
        except KeyboardInterrupt:
            log.info("Scheduler dihentikan.")


if __name__ == "__main__":
    main()
