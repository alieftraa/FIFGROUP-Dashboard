"""
run_gbp_pipeline.py — Management command untuk menjalankan pipeline GBP
(fetch + optional update master database) secara otomatis.

Pengganti scheduler.py dari project Streamlit.

Penggunaan:
    # Jalankan sekarang sekali
    python manage.py run_gbp_pipeline --run-now

    # Jalankan dengan scheduler harian jam 08:00
    python manage.py run_gbp_pipeline --schedule 08:00

    # Dengan update master CSV
    python manage.py run_gbp_pipeline --run-now --master-file database_kios.csv

    # Dengan update master SQLite
    python manage.py run_gbp_pipeline --run-now \\
        --master-file kios.db --master-mode sqlite --master-table kios
"""

import logging
import time
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

log = logging.getLogger("gbp.management.run_gbp_pipeline")


class Command(BaseCommand):
    help = "Jalankan pipeline fetch GBP + update master database"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--run-now",
            action="store_true",
            default=False,
            help="Jalankan pipeline sekali sekarang.",
        )
        group.add_argument(
            "--schedule",
            metavar="HH:MM",
            default=None,
            help="Jalankan otomatis setiap hari pada jam ini (format HH:MM).",
        )

        # GBP API options
        parser.add_argument(
            "--account-id",
            default=None,
            help="Account ID GBP spesifik. Kosongkan untuk semua akun.",
        )
        parser.add_argument(
            "--no-db",
            action="store_true",
            default=False,
            help="Skip simpan ke Django database.",
        )

        # Master update options
        parser.add_argument(
            "--master-file",
            default=None,
            help="Path ke file master database kios (CSV atau SQLite) untuk diupdate.",
        )
        parser.add_argument(
            "--master-mode",
            choices=["csv", "sqlite"],
            default="csv",
            help="Mode update master: csv atau sqlite.",
        )
        parser.add_argument(
            "--master-table",
            default="kios",
            help="Nama tabel SQLite (hanya untuk --master-mode sqlite).",
        )
        parser.add_argument(
            "--master-key-col",
            default="kode_kios",
            help="Kolom kunci di database master.",
        )
        parser.add_argument(
            "--log-dir",
            default="logs",
            help="Direktori untuk menyimpan log harian.",
        )

    def handle(self, *args, **options):
        if options.get("run_now"):
            self._run_pipeline(options)
        else:
            schedule_time = options.get("schedule")
            self.stdout.write(
                self.style.NOTICE(
                    f"Scheduler aktif. Pipeline berjalan setiap hari jam {schedule_time}.\n"
                    f"Tekan Ctrl+C untuk menghentikan."
                )
            )
            try:
                while True:
                    self._wait_until(schedule_time)
                    self._run_pipeline(options)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\nScheduler dihentikan."))

    def _run_pipeline(self, options):
        """Jalankan satu siklus pipeline: fetch → (opsional) update master."""
        from gbp.services.gbp_api import fetch_records
        from gbp.services.history_service import save_run
        from gbp.services.master_update_service import (
            load_gbp_records,
            update_csv_database,
            update_sqlite_database,
            generate_report,
        )

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.stdout.write(self.style.NOTICE("=" * 55))
        self.stdout.write(self.style.NOTICE(f"GBP Pipeline — {ts}"))
        self.stdout.write(self.style.NOTICE("=" * 55))

        # ── STEP 1: Fetch ─────────────────────────────────────────
        self.stdout.write("\n📡 STEP 1: Fetch data dari GBP API...")
        try:
            account_id = options.get("account_id") or None
            records = fetch_records(account_id=account_id)
            self.stdout.write(self.style.SUCCESS(f"  ✅ {len(records)} lokasi berhasil diambil."))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ❌ Gagal fetch: {exc}"))
            return False

        if not records:
            self.stdout.write(self.style.WARNING("  ⚠️  Tidak ada data dari API."))
            return False

        # ── STEP 2: Simpan ke DB ──────────────────────────────────
        if not options.get("no_db"):
            self.stdout.write("\n💾 STEP 2: Simpan ke Django database...")
            try:
                run_id = save_run(records)
                self.stdout.write(self.style.SUCCESS(f"  ✅ Run #{run_id} tersimpan."))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  ❌ Gagal simpan ke DB: {exc}"))
        else:
            self.stdout.write("\n  ⏭️  Skip simpan ke database (--no-db).")

        # ── STEP 3: Update master (opsional) ──────────────────────
        master_file = options.get("master_file")
        if master_file:
            self.stdout.write(f"\n📝 STEP 3: Update master database: {master_file}...")
            try:
                gbp_map = load_gbp_records(records)
                master_mode = options.get("master_mode", "csv")

                if master_mode == "csv":
                    result = update_csv_database(
                        gbp_map=gbp_map,
                        db_file=master_file,
                        db_key_col=options.get("master_key_col", "kode_kios"),
                    )
                else:
                    result = update_sqlite_database(
                        gbp_map=gbp_map,
                        db_file=master_file,
                        table=options.get("master_table", "kios"),
                        db_key_col=options.get("master_key_col", "kode_kios"),
                    )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✅ {result['updated']} baris diupdate, "
                        f"{result['not_found']} tidak ditemukan. "
                        f"Backup: {result['backup_path']}"
                    )
                )

                # Generate laporan
                log_dir = options.get("log_dir", "logs")
                report_path = generate_report(gbp_map, result, master_file, output_dir=log_dir)
                self.stdout.write(f"  📄 Laporan: {report_path}")

            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  ❌ Gagal update master: {exc}"))
        else:
            self.stdout.write("\n  ⏭️  Skip update master (--master-file tidak diisi).")

        self.stdout.write(self.style.SUCCESS("\n✅ Pipeline selesai!"))
        return True

    def _wait_until(self, target_time_str: str):
        """Tunggu hingga jam target (format HH:MM)."""
        now = datetime.now()
        h, m = map(int, target_time_str.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)

        if target <= now:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        self.stdout.write(
            f"⏰ Menunggu hingga {target.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({wait_seconds / 3600:.1f} jam lagi)..."
        )
        time.sleep(wait_seconds)
