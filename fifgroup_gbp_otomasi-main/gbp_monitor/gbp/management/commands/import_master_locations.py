"""
import_master_locations.py — Management command untuk import data master ke MasterLocation.

Usage:
    python manage.py import_master_locations --file path/to/master.csv
    python manage.py import_master_locations --file master.csv --clear

CSV wajib memiliki kolom (nama fleksibel):
    store_code / kode_kios / kode_outlet (unik)
    location_name / location_id / branch_id
    business_name / nama_bisnis / branch_name
    network_name / network
    account_name / account
    verification_status / status_verifikasi / status
"""

import logging
import os

from django.core.management.base import BaseCommand, CommandError

log = logging.getLogger("gbp.management.import_master_locations")


class Command(BaseCommand):
    help = "Import data master lokasi dari CSV ke tabel MasterLocation di Supabase"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path ke file CSV master lokasi",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Hapus semua data MasterLocation yang ada sebelum import (hati-hati!)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Jalankan tanpa benar-benar menyimpan ke database",
        )

    def handle(self, *args, **options):
        filepath = options["file"]
        do_clear = options["clear"]
        dry_run = options["dry_run"]

        if not os.path.exists(filepath):
            raise CommandError(f"File tidak ditemukan: {filepath}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Mode DRY-RUN aktif. Data tidak akan disimpan."))

        if do_clear and not dry_run:
            from gbp.models import MasterLocation
            count = MasterLocation.objects.count()
            if count > 0:
                confirm = input(
                    f"Ini akan menghapus {count} baris MasterLocation. "
                    f"Ketik 'YES' untuk melanjutkan: "
                )
                if confirm.strip() != "YES":
                    self.stdout.write(self.style.ERROR("Dibatalkan."))
                    return
                MasterLocation.objects.all().delete()
                self.stdout.write(self.style.WARNING(f"{count} baris dihapus."))

        self.stdout.write(f"Membaca file: {filepath}")

        try:
            if dry_run:
                # Baca saja, jangan simpan
                import csv
                with open(filepath, encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                summary = {
                    "total": len(rows),
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "error": 0,
                    "errors_detail": [],
                }
                self.stdout.write(f"   Kolom ditemukan: {list(rows[0].keys()) if rows else '[]'}")
                self.stdout.write(self.style.WARNING(f"   DRY RUN: {len(rows)} baris akan diproses."))
            else:
                from gbp.services.master_update_service import import_master_locations
                summary = import_master_locations(filepath=filepath)

        except FileNotFoundError:
            raise CommandError(f"File tidak ditemukan: {filepath}")
        except ValueError as e:
            raise CommandError(str(e))
        except Exception as e:
            raise CommandError(f"Error: {e}")

        # Output summary
        self.stdout.write("")
        self.stdout.write("-" * 40)
        self.stdout.write(f"  Total baris   : {summary['total']}")
        self.stdout.write(
            self.style.SUCCESS(f"  Dibuat       : {summary['created']}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"  Diperbarui   : {summary['updated']}")
        )
        if summary["skipped"] > 0:
            self.stdout.write(
                self.style.WARNING(f"  Dilewati     : {summary['skipped']}")
            )
        if summary["error"] > 0:
            self.stdout.write(
                self.style.ERROR(f"  Error         : {summary['error']}")
            )
            for detail in summary.get("errors_detail", [])[:10]:
                self.stdout.write(self.style.ERROR(f"     -> {detail}"))
            if len(summary.get("errors_detail", [])) > 10:
                self.stdout.write(self.style.ERROR(
                    f"     ... dan {len(summary['errors_detail']) - 10} error lainnya."
                ))
        self.stdout.write("-" * 40)

        if not dry_run and (summary["created"] + summary["updated"]) > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nImport selesai: {summary['created']} dibuat, "
                    f"{summary['updated']} diperbarui."
                )
            )
        elif dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN selesai. Tidak ada data yang disimpan."))
