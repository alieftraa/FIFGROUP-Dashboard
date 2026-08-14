"""
history_service.py — Service untuk menyimpan dan membaca data run history.
Menggantikan history_db.py menggunakan Django ORM.

Fungsi utama:
  save_run(records)          → Simpan batch hasil fetch ke DB
  get_all_runs()             → Ambil semua run untuk selector
  get_snapshots(...)         → Ambil snapshot dengan filter
  get_status_trend(days)     → Data tren untuk chart
  get_run_by_id(run_id)      → Detail satu run
"""

import logging
from collections import Counter
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from gbp.models import FetchRun, LocationSnapshot

log = logging.getLogger("gbp.services.history_service")


# ── Write ─────────────────────────────────────────────────────────────

@transaction.atomic
def save_run(records: list[dict]) -> int:
    """
    Simpan satu batch hasil fetch ke database menggunakan Django ORM.

    Args:
        records: List of dict hasil dari gbp_api.fetch_records()

    Returns:
        run_id (primary key) dari FetchRun yang baru dibuat.
    """
    if not records:
        log.warning("save_run dipanggil dengan records kosong.")
        return 0

    counts = Counter(r["status"] for r in records)
    now = timezone.now()

    # Buat FetchRun
    run = FetchRun.objects.create(
        run_date=now.date(),
        run_timestamp=now,
        total=len(records),
        verified=counts.get("Verified", 0),
        duplicate=counts.get("Duplicate", 0),
        suspended=counts.get("Suspended", 0),
        unverified=counts.get("Verification Required", 0),
    )

    # Bulk create LocationSnapshot
    snapshots = []
    for r in records:
        fetched_raw = r.get("fetched_at", "")
        try:
            fetched_dt = datetime.strptime(fetched_raw, "%Y-%m-%d %H:%M:%S")
            fetched_dt = timezone.make_aware(fetched_dt)
        except (ValueError, TypeError):
            fetched_dt = now

        snapshots.append(LocationSnapshot(
            run=run,
            store_code=r.get("store_code", "") or "",
            location_name=r.get("location_name", "") or "",
            business_name=r.get("business_name", "") or "",
            account_name=r.get("account_name", "") or "",
            address=r.get("address", "") or "",
            latitude=r.get("latitude"),
            longitude=r.get("longitude"),
            coord_status=r.get("coord_status", "MISSING"),
            status=r.get("status", "Verification Required"),
            has_vom=bool(r.get("has_vom", False)),
            is_duplicate=bool(r.get("is_duplicate", False)),
            is_suspended=bool(r.get("is_suspended", False)),
            has_pending_edits=bool(r.get("has_pending_edits", False)),
            maps_uri=r.get("maps_uri", "") or "",
            fetched_at=fetched_dt,
        ))

    LocationSnapshot.objects.bulk_create(snapshots, batch_size=500)
    log.info(f"Run #{run.pk} disimpan ke DB: {len(records)} lokasi.")
    return run.pk


# ── Read ──────────────────────────────────────────────────────────────

def get_all_runs() -> list[dict]:
    """
    Ambil semua run, terbaru di atas.
    Dipakai untuk dropdown selector di dashboard.
    """
    runs = FetchRun.objects.order_by("-pk").values(
        "pk", "run_date", "run_timestamp",
        "total", "verified", "duplicate", "suspended", "unverified",
    )
    result = []
    for r in runs:
        result.append({
            "run_id": r["pk"],
            "run_date": str(r["run_date"]),
            "run_timestamp": str(r["run_timestamp"]),
            "total": r["total"],
            "verified": r["verified"],
            "duplicate": r["duplicate"],
            "suspended": r["suspended"],
            "unverified": r["unverified"],
        })
    return result


def get_run_by_id(run_id: int) -> dict | None:
    """Ambil detail satu run berdasarkan ID."""
    try:
        run = FetchRun.objects.get(pk=run_id)
        return {
            "run_id": run.pk,
            "run_date": str(run.run_date),
            "run_timestamp": str(run.run_timestamp),
            "total": run.total,
            "verified": run.verified,
            "duplicate": run.duplicate,
            "suspended": run.suspended,
            "unverified": run.unverified,
        }
    except FetchRun.DoesNotExist:
        return None


def get_latest_run_id() -> int | None:
    """Ambil run_id terbaru."""
    run = FetchRun.objects.order_by("-pk").values("pk").first()
    return run["pk"] if run else None


def get_snapshots(
    run_id: int,
    status_filter: list[str] | None = None,
    search: str | None = None,
) -> list[dict]:
    """
    Ambil semua snapshot untuk satu run dengan filter opsional.

    Args:
        run_id        : ID run yang dipilih
        status_filter : list status yang diinginkan, None = semua
        search        : string pencarian di business_name, store_code, location_name
    """
    qs = LocationSnapshot.objects.filter(run_id=run_id)

    if status_filter:
        qs = qs.filter(status__in=status_filter)

    if search:
        qs = qs.filter(
            Q(business_name__icontains=search) |
            Q(store_code__icontains=search) |
            Q(location_name__icontains=search)
        )

    return list(qs.values(
        "id", "run_id", "store_code", "location_name", "business_name",
        "account_name", "address", "latitude", "longitude",
        "coord_status", "status", "has_vom", "is_duplicate",
        "is_suspended", "has_pending_edits", "maps_uri", "fetched_at",
    ))


def get_status_trend(days: int = 30) -> list[dict]:
    """
    Tren status per hari untuk N hari terakhir.
    Dipakai untuk line chart di halaman Overview.

    Returns:
        List of dict dengan keys: run_date, verified, duplicate, suspended, unverified, total
    """
    from django.db.models import Sum
    from django.db.models.functions import TruncDate

    cutoff = timezone.now().date() - timedelta(days=days)

    rows = (
        FetchRun.objects
        .filter(run_date__gte=cutoff)
        .values("run_date")
        .annotate(
            verified=Sum("verified"),
            duplicate=Sum("duplicate"),
            suspended=Sum("suspended"),
            unverified=Sum("unverified"),
            total=Sum("total"),
        )
        .order_by("run_date")
    )

    return [
        {
            "run_date": str(r["run_date"]),
            "verified": r["verified"] or 0,
            "duplicate": r["duplicate"] or 0,
            "suspended": r["suspended"] or 0,
            "unverified": r["unverified"] or 0,
            "total": r["total"] or 0,
        }
        for r in rows
    ]
