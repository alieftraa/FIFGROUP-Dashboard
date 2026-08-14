"""
update_database.py
------------------
Melakukan lookup hasil GBP ke database kios yang sudah ada,
lalu memperbarui kolom status verifikasi secara otomatis.

Mendukung dua mode database:
  1. CSV  — cocok untuk database sederhana / Excel
  2. SQLite — cocok untuk database lokal yang sudah ada

Cara pakai:
    # Update database CSV
    python update_database.py \
        --gbp-file gbp_status_20260511.csv \
        --db-file database_kios.csv \
        --mode csv

    # Update database SQLite
    python update_database.py \
        --gbp-file gbp_status_20260511.csv \
        --db-file kios.db \
        --mode sqlite \
        --table kios \
        --db-key-col kode_kios \
        --gbp-key-col store_code
"""

import csv
import sqlite3
import argparse
import logging
import shutil
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# LOAD DATA GBP
# ──────────────────────────────────────────────

def load_gbp_csv(filepath: str) -> dict:
    """
    Baca hasil fetch_status.py, return dict:
    { store_code: { status, has_vom, is_duplicate, ... } }
    """
    gbp_map = {}
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row["store_code"].strip()
            if key:
                gbp_map[key] = row
    log.info(f"Loaded {len(gbp_map)} baris dari GBP file: {filepath}")
    return gbp_map


# ──────────────────────────────────────────────
# MODE CSV
# ──────────────────────────────────────────────

def update_csv_database(
    gbp_file: str,
    db_file: str,
    db_key_col: str,
    gbp_key_col: str,
    status_col: str,
    fetched_col: str,
):
    """Update database CSV dengan status terbaru dari GBP."""
    gbp_map = load_gbp_csv(gbp_file)

    # Backup file asli
    backup = db_file.replace(".csv", f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    shutil.copy(db_file, backup)
    log.info(f"Backup disimpan: {backup}")

    # Baca database kios
    rows = []
    with open(db_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    # Tambah kolom jika belum ada
    if status_col not in fieldnames:
        fieldnames.append(status_col)
    if fetched_col not in fieldnames:
        fieldnames.append(fetched_col)

    # Update setiap baris
    updated = 0
    not_found = 0
    for row in rows:
        kode = row.get(db_key_col, "").strip()
        if kode in gbp_map:
            row[status_col] = gbp_map[kode]["status"]
            row[fetched_col] = gbp_map[kode]["fetched_at"]
            updated += 1
        else:
            not_found += 1

    # Tulis kembali
    with open(db_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log.info(f"✅ Update selesai: {updated} baris diupdate, {not_found} tidak ditemukan di GBP.")
    _generate_report(gbp_map, db_key_col, updated, not_found, db_file)


# ──────────────────────────────────────────────
# MODE SQLITE
# ──────────────────────────────────────────────

def update_sqlite_database(
    gbp_file: str,
    db_file: str,
    table: str,
    db_key_col: str,
    gbp_key_col: str,
    status_col: str,
    fetched_col: str,
):
    """Update database SQLite dengan status terbaru dari GBP."""
    gbp_map = load_gbp_csv(gbp_file)

    # Backup
    backup = db_file.replace(".db", f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    shutil.copy(db_file, backup)
    log.info(f"Backup disimpan: {backup}")

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Tambah kolom jika belum ada
    existing_cols = {
        row[1] for row in cursor.execute(f"PRAGMA table_info({table})")
    }
    for col in [status_col, fetched_col]:
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
            log.info(f"Kolom baru ditambahkan ke tabel '{table}': {col}")

    # Update baris per baris
    updated = 0
    not_found = 0

    for store_code, gbp_data in gbp_map.items():
        cursor.execute(
            f"""
            UPDATE {table}
            SET {status_col}  = ?,
                {fetched_col} = ?
            WHERE {db_key_col} = ?
            """,
            (gbp_data["status"], gbp_data["fetched_at"], store_code),
        )
        if cursor.rowcount > 0:
            updated += 1
        else:
            not_found += 1

    conn.commit()
    conn.close()

    log.info(f"✅ Update SQLite selesai: {updated} baris diupdate, {not_found} tidak ditemukan.")
    _generate_report(gbp_map, db_key_col, updated, not_found, db_file)


# ──────────────────────────────────────────────
# LAPORAN
# ──────────────────────────────────────────────

def _generate_report(gbp_map: dict, key_col: str, updated: int, not_found: int, db_file: str):
    """Simpan laporan ringkas ke file teks."""
    from collections import Counter
    status_counts = Counter(v["status"] for v in gbp_map.values())
    report_file   = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    lines = [
        "=" * 55,
        "LAPORAN UPDATE STATUS GBP",
        f"Waktu   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Database: {db_file}",
        "=" * 55,
        f"Total lokasi GBP          : {len(gbp_map)}",
        f"Berhasil diupdate         : {updated}",
        f"Tidak ditemukan di DB     : {not_found}",
        "-" * 55,
        "BREAKDOWN STATUS:",
        f"  Verified                : {status_counts.get('Verified', 0)}",
        f"  Verification Required   : {status_counts.get('Verification Required', 0)}",
        f"  Duplicate               : {status_counts.get('Duplicate', 0)}",
        "=" * 55,
    ]

    with open(report_file, "w") as f:
        f.write("\n".join(lines))

    print("\n".join(lines))
    log.info(f"Laporan disimpan: {report_file}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Update database kios dengan status GBP")
    parser.add_argument("--gbp-file",   required=True,  help="File CSV hasil fetch_status.py")
    parser.add_argument("--db-file",    required=True,  help="File database kios (.csv atau .db)")
    parser.add_argument("--mode",       choices=["csv", "sqlite"], default="csv")
    parser.add_argument("--table",      default="kios",           help="Nama tabel (SQLite only)")
    parser.add_argument("--db-key-col", default="kode_kios",      help="Kolom kunci di database kios")
    parser.add_argument("--gbp-key-col",default="store_code",     help="Kolom kunci di file GBP")
    parser.add_argument("--status-col", default="gbp_status",     help="Kolom status yang akan diisi/diupdate")
    parser.add_argument("--fetched-col",default="gbp_fetched_at", help="Kolom timestamp update")
    args = parser.parse_args()

    if args.mode == "csv":
        update_csv_database(
            gbp_file=args.gbp_file,
            db_file=args.db_file,
            db_key_col=args.db_key_col,
            gbp_key_col=args.gbp_key_col,
            status_col=args.status_col,
            fetched_col=args.fetched_col,
        )
    elif args.mode == "sqlite":
        update_sqlite_database(
            gbp_file=args.gbp_file,
            db_file=args.db_file,
            table=args.table,
            db_key_col=args.db_key_col,
            gbp_key_col=args.gbp_key_col,
            status_col=args.status_col,
            fetched_col=args.fetched_col,
        )


if __name__ == "__main__":
    main()
