"""
import_legacy_sqlite.py — Management command untuk mengimpor data historis
dari file gbp_history.db (SQLite lama) ke database Django ORM.

Berguna untuk migrasi dari project Streamlit ke Django.

Penggunaan:
    python manage.py import_legacy_sqlite
    python manage.py import_legacy_sqlite --db-path path/to/gbp_history.db
    python manage.py import_legacy_sqlite --dry-run
"""

import sqlite3
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

log = logging.getLogger("gbp.management.import_legacy_sqlite")


class Command(BaseCommand):
    help = "Import data historis dari gbp_history.db (SQLite lama) ke Django ORM"

    def add_arguments(self, parser):
        parser.add_argument(
            "--db-path",
            default=None,
            help="Path ke file gbp_history.db. Default: cari di direktori parent project.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simulasi tanpa menyimpan ke database.",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            default=True,
            help="Skip run yang sudah ada di Django DB (berdasarkan run_date + total).",
        )

    def handle(self, *args, **options):
        from gbp.models import FetchRun, LocationSnapshot

        # ── Temukan file DB lama ──────────────────────────────────
        db_path = options.get("db_path")
        if not db_path:
            # Cari di beberapa lokasi umum
            candidates = [
                Path(__file__).resolve().parents[6] / "gbp_history.db",
                Path(__file__).resolve().parents[5] / "gbp_history.db",
                Path("gbp_history.db").resolve(),
            ]
            for candidate in candidates:
                if candidate.exists():
                    db_path = str(candidate)
                    break

        if not db_path or not Path(db_path).exists():
            raise CommandError(
                f"File gbp_history.db tidak ditemukan. "
                f"Gunakan --db-path untuk menentukan lokasi file."
            )

        self.stdout.write(self.style.NOTICE(f"Database lama: {db_path}"))

        dry_run = options.get("dry_run", False)
        skip_existing = options.get("skip_existing", True)

        if dry_run:
            self.stdout.write(self.style.WARNING("MODE DRY RUN — tidak ada perubahan yang disimpan"))

        # ── Koneksi ke SQLite lama ────────────────────────────────
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
        except Exception as exc:
            raise CommandError(f"Gagal membuka database: {exc}") from exc

        try:
            runs = conn.execute("SELECT * FROM runs ORDER BY run_id ASC").fetchall()
        except Exception as exc:
            raise CommandError(f"Gagal membaca tabel runs: {exc}") from exc

        self.stdout.write(f"Ditemukan {len(runs)} run di database lama.")

        imported_runs = 0
        skipped_runs = 0
        imported_snapshots = 0

        with transaction.atomic():
            for run_row in runs:
                run_dict = dict(run_row)

                # ── Cek duplikat ──────────────────────────────────
                if skip_existing:
                    exists = FetchRun.objects.filter(
                        run_date=run_dict["run_date"],
                        total=run_dict["total"],
                    ).exists()
                    if exists:
                        self.stdout.write(
                            f"  Skip run #{run_dict['run_id']} ({run_dict['run_date']}, "
                            f"{run_dict['total']} lokasi) — sudah ada di DB"
                        )
                        skipped_runs += 1
                        continue

                # ── Buat FetchRun baru ────────────────────────────
                try:
                    run_ts = timezone.datetime.strptime(
                        run_dict["run_timestamp"], "%Y-%m-%d %H:%M:%S"
                    )
                    run_ts = timezone.make_aware(run_ts)
                except (ValueError, TypeError):
                    run_ts = timezone.now()

                if not dry_run:
                    new_run = FetchRun.objects.create(
                        run_date=run_dict["run_date"],
                        run_timestamp=run_ts,
                        total=run_dict.get("total", 0),
                        verified=run_dict.get("verified", 0),
                        duplicate=run_dict.get("duplicate", 0),
                        suspended=run_dict.get("suspended", 0),
                        unverified=run_dict.get("unverified", 0),
                    )
                    old_run_id = run_dict["run_id"]
                else:
                    new_run = None
                    old_run_id = run_dict["run_id"]

                # ── Ambil snapshots untuk run ini ─────────────────
                try:
                    snapshots = conn.execute(
                        "SELECT * FROM snapshots WHERE run_id = ?",
                        (old_run_id,),
                    ).fetchall()
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"  Gagal baca snapshots untuk run #{old_run_id}: {exc}"))
                    snapshots = []

                if not dry_run and new_run and snapshots:
                    snap_objs = []
                    for snap in snapshots:
                        s = dict(snap)
                        try:
                            fetched_dt = timezone.datetime.strptime(
                                s.get("fetched_at", ""), "%Y-%m-%d %H:%M:%S"
                            )
                            fetched_dt = timezone.make_aware(fetched_dt)
                        except (ValueError, TypeError):
                            fetched_dt = run_ts

                        snap_objs.append(LocationSnapshot(
                            run=new_run,
                            store_code=s.get("store_code") or "",
                            location_name=s.get("location_name") or "",
                            business_name=s.get("business_name") or "",
                            account_name=s.get("account_name", "") or "",
                            address=s.get("address") or "",
                            latitude=s.get("latitude"),
                            longitude=s.get("longitude"),
                            coord_status=s.get("coord_status") or "MISSING",
                            status=s.get("status") or "Verification Required",
                            has_vom=bool(s.get("has_vom", 0)),
                            is_duplicate=bool(s.get("is_duplicate", 0)),
                            is_suspended=bool(s.get("is_suspended", 0)),
                            has_pending_edits=bool(s.get("has_pending_edits", 0)),
                            maps_uri=s.get("maps_uri") or "",
                            fetched_at=fetched_dt,
                        ))

                    LocationSnapshot.objects.bulk_create(snap_objs, batch_size=500)
                    imported_snapshots += len(snap_objs)

                imported_runs += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [OK] Run #{old_run_id} -> Django Run #{new_run.pk if new_run else '(dry-run)'} "
                        f"({len(snapshots)} snapshots)"
                    )
                )

            if dry_run:
                transaction.set_rollback(True)

        conn.close()

        self.stdout.write("\n" + "=" * 55)
        self.stdout.write(self.style.SUCCESS("IMPORT SELESAI"))
        self.stdout.write("=" * 55)
        self.stdout.write(f"  Runs diimpor   : {imported_runs}")
        self.stdout.write(f"  Runs di-skip   : {skipped_runs}")
        self.stdout.write(f"  Snapshots      : {imported_snapshots}")
        if dry_run:
            self.stdout.write(self.style.WARNING("  (Dry-run: tidak ada data yang disimpan)"))
