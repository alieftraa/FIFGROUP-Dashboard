"""
fetch_gbp_status.py — Management command untuk mengambil data dari GBP API
dan menyimpannya ke database Django.

Penggunaan:
    python manage.py fetch_gbp_status
    python manage.py fetch_gbp_status --account-id accounts/123456789
    python manage.py fetch_gbp_status --output gbp_status_today.csv
    python manage.py fetch_gbp_status --no-db
"""

import csv
import logging
from pathlib import Path
from collections import Counter
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

log = logging.getLogger("gbp.management.fetch_gbp_status")


class Command(BaseCommand):
    help = "Ambil status verifikasi GBP dari API dan simpan ke database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--account-id",
            default=None,
            help="Account ID spesifik GBP (format: accounts/123456789). Kosongkan untuk semua akun.",
        )
        parser.add_argument(
            "--output",
            default=None,
            help="Nama file CSV output (opsional). Default: gbp_status_YYYYMMDD.csv",
        )
        parser.add_argument(
            "--no-db",
            action="store_true",
            dest="no_db",
            default=False,
            help="Skip menyimpan ke database Django.",
        )

    def handle(self, *args, **options):
        from gbp.services.gbp_api import fetch_records
        from gbp.services.history_service import save_run

        account_id = options.get("account_id")
        output_file = options.get("output") or f"gbp_status_{datetime.now().strftime('%Y%m%d')}.csv"
        no_db = options.get("no_db", False)

        self.stdout.write(self.style.NOTICE("=" * 55))
        self.stdout.write(self.style.NOTICE("GBP Monitor — Fetch Status Verifikasi"))
        self.stdout.write(self.style.NOTICE("=" * 55))

        if account_id:
            self.stdout.write(f"Account ID: {account_id}")
        else:
            self.stdout.write("Account ID: semua akun")

        # ── Fetch dari GBP API ────────────────────────────────────
        self.stdout.write("\n📡 Memulai autentikasi Google dan fetch data...")
        try:
            all_records = fetch_records(account_id=account_id)
        except Exception as exc:
            raise CommandError(f"Gagal fetch dari GBP API: {exc}") from exc

        if not all_records:
            self.stdout.write(self.style.WARNING("⚠️  Tidak ada data yang ditemukan."))
            return

        # ── Simpan ke CSV ─────────────────────────────────────────
        try:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(all_records[0].keys()))
                writer.writeheader()
                writer.writerows(all_records)
            self.stdout.write(self.style.SUCCESS(f"✅ CSV disimpan: {output_file} ({len(all_records)} baris)"))
        except IOError as exc:
            self.stdout.write(self.style.WARNING(f"⚠️  Gagal menyimpan CSV: {exc}"))

        # ── Simpan ke Database ────────────────────────────────────
        if not no_db:
            try:
                run_id = save_run(all_records)
                self.stdout.write(self.style.SUCCESS(f"✅ Database: Run #{run_id} tersimpan."))
            except Exception as exc:
                raise CommandError(f"Gagal menyimpan ke database: {exc}") from exc
        else:
            self.stdout.write(self.style.WARNING("⚠️  Skip menyimpan ke database (--no-db)."))

        # ── Ringkasan ─────────────────────────────────────────────
        counts = Counter(r["status"] for r in all_records)
        coord_stats = Counter(r.get("coord_status", "MISSING") for r in all_records)

        self.stdout.write("\n" + "=" * 55)
        self.stdout.write("RINGKASAN STATUS VERIFIKASI GBP")
        self.stdout.write("=" * 55)
        self.stdout.write(f"  Total lokasi             : {len(all_records)}")
        self.stdout.write(self.style.SUCCESS(f"  ✅ Verified               : {counts.get('Verified', 0)}"))
        self.stdout.write(f"  ⚪ Verification Required  : {counts.get('Verification Required', 0)}")
        self.stdout.write(self.style.WARNING(f"  ⚠️  Duplicate               : {counts.get('Duplicate', 0)}"))
        self.stdout.write(self.style.ERROR(f"  🚫 Suspended               : {counts.get('Suspended', 0)}"))
        self.stdout.write("-" * 55)
        self.stdout.write(f"  📍 Koordinat OK           : {coord_stats.get('OK', 0)}")
        self.stdout.write(f"  ❌ Koordinat tidak ada    : {coord_stats.get('MISSING', 0)}")
        self.stdout.write(f"  ⚠️  Koordinat error        : {coord_stats.get('PARSE_ERROR', 0) + coord_stats.get('OUT_OF_RANGE', 0)}")
        self.stdout.write("=" * 55)
