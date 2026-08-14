"""
reconciliation_service.py — Service untuk pencocokan dan rekonsiliasi
status verifikasi antara master data dan data terbaru dari GBP API.

Logika matching (prioritas group):
  1. NETWORK ID UPDATED — langsung digunakan jika ditemukan
  2. NAMA NETWORK
  3. BRANCH ID
  4. BRANCH NAME
  5. NETWORK
"""

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from django.db import transaction
from django.utils import timezone

log = logging.getLogger("gbp.services.reconciliation_service")

# ── Konfigurasi Identifier Groups ─────────────────────────────────────
IDENTIFIER_GROUPS: list[tuple[str, list[str], list[str]]] = [
    (
        "NETWORK ID UPDATED",
        ["NETWORK ID UPDATED", "network_id_updated", "networkidupdated",
         "store_code", "kode_outlet", "kode_kios", "outlet_code"],  # tambahan: store_code sbg master key
        ["store_code", "kode_outlet", "kode_kios", "outlet_code"],
    ),
    (
        "NAMA NETWORK",
        ["NAMA NETWORK", "nama_network", "network", "business_name"],
        ["business_name", "business_location_name", "network_name", "nama_network", "nama_outlet"],
    ),
    (
        "BRANCH ID",
        ["BRANCH ID", "branch_id", "branchid", "location_name", "location_id"],
        ["location_name", "location_id", "name"],
    ),
    (
        "BRANCH NAME",
        ["BRANCH NAME", "branch_name"],
        ["business_name", "business_location_name", "title"],
    ),
    (
        "NETWORK",
        ["NETWORK", "network"],
        ["account_name", "account_id", "account"],
    ),
]

STATUS_CANDIDATES = ["STATUS VERIFIKASI", "verification_status", "gbp_status", "status"]


# ── Helper Functions ──────────────────────────────────────────────────

def _normalize_value(value: Any) -> str:
    """Normalisasi nilai untuk pencocokan."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "f").rstrip("0").rstrip(".")
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith(".0") and text[:-2].replace("-", "").isdigit():
        text = text[:-2]
    return " ".join(text.split()).casefold()


def _first_existing_column(columns: list[str], candidates: list[str]) -> str | None:
    lookup = {col.casefold(): col for col in columns}
    for candidate in candidates:
        if candidate.casefold() in lookup:
            return lookup[candidate.casefold()]
    return None


def _detect_status_column(columns: list[str]) -> str | None:
    return _first_existing_column(columns, STATUS_CANDIDATES)


def _detect_identifier_group(
    master_df: pd.DataFrame,
    api_df: pd.DataFrame,
) -> tuple[str, str, str] | None:
    preferred_group = "NETWORK ID UPDATED"
    best_match: tuple[int, int, str, str, str] | None = None

    for priority, (group_name, master_candidates, api_candidates) in enumerate(IDENTIFIER_GROUPS):
        master_col = _first_existing_column(list(master_df.columns), master_candidates)
        api_col = _first_existing_column(list(api_df.columns), api_candidates)
        if not master_col or not api_col:
            continue

        master_non_empty = int(master_df[master_col].map(_normalize_value).astype(bool).sum())
        api_non_empty = int(api_df[api_col].map(_normalize_value).astype(bool).sum())
        usable_rows = min(master_non_empty, api_non_empty)

        if group_name == preferred_group:
            return group_name, master_col, api_col

        candidate = (usable_rows, -priority, group_name, master_col, api_col)
        if best_match is None or candidate > best_match:
            best_match = candidate

    if best_match is None:
        return None

    _, _, group_name, master_col, api_col = best_match
    return group_name, master_col, api_col


# ── Fungsi Utama ──────────────────────────────────────────────────────

def compare_master_to_api(
    master_df: pd.DataFrame,
    api_df: pd.DataFrame,
    master_status_col: str | None = None,
    api_status_col: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Bandingkan master data vs data API GBP.

    Returns:
        Tuple of (updated_master_df, comparison_df, summary_dict)

        summary_dict keys:
          matched, updated, invalid, manual_review, not_found
    """
    if master_df.empty:
        empty = master_df.copy()
        return empty, empty, {
            "matched": 0, "updated": 0, "invalid": 0,
            "manual_review": 0, "not_found": 0,
        }

    if api_df.empty:
        raise ValueError("Data API kosong, tidak ada data yang bisa dicocokkan.")

    master_status_col = master_status_col or _detect_status_column(list(master_df.columns))
    api_status_col = api_status_col or _detect_status_column(list(api_df.columns))

    if not master_status_col:
        raise ValueError("Kolom status master tidak ditemukan.")
    if not api_status_col:
        raise ValueError("Kolom status API tidak ditemukan.")

    identifier_group = _detect_identifier_group(master_df, api_df)
    if not identifier_group:
        raise ValueError("Tidak ada pasangan identifier yang sama antara master dan API.")

    group_name, master_key_col, api_key_col = identifier_group
    log.info(f"Menggunakan identifier group: {group_name} ({master_key_col} <-> {api_key_col})")

    master = master_df.copy()
    api = api_df.copy()

    master["__match_key"] = master[master_key_col].map(_normalize_value)
    api["__match_key"] = api[api_key_col].map(_normalize_value)

    api_index: dict[str, list] = {}
    for _, api_row in api.iterrows():
        key = api_row["__match_key"]
        if not key:
            continue
        api_index.setdefault(key, []).append(api_row)

    updated_master = master.copy()
    comparison_rows: list[dict] = []
    summary = {"matched": 0, "updated": 0, "invalid": 0, "manual_review": 0, "not_found": 0}

    for idx, master_row in master.iterrows():
        master_value = master_row.get(master_key_col, "")
        master_status = master_row.get(master_status_col, "")
        match_key = _normalize_value(master_value)

        if not match_key:
            summary["invalid"] += 1
            comparison_rows.append({
                "match_status": "Invalid",
                "match_rule": group_name,
                "identifier_value": master_value,
                "old_status": master_status,
                "new_status": "",
                "status_changed": False,
                "change_note": "Identifier kosong atau tidak valid",
            })
            continue

        matched_rows = api_index.get(match_key, [])

        if not matched_rows:
            summary["not_found"] += 1
            comparison_rows.append({
                "match_status": "Not Found",
                "match_rule": group_name,
                "identifier_value": master_value,
                "old_status": master_status,
                "new_status": "",
                "status_changed": False,
                "change_note": "Tidak ditemukan di data API",
            })
            continue

        if len(matched_rows) > 1:
            summary["manual_review"] += 1
            comparison_rows.append({
                "match_status": "Manual Review",
                "match_rule": group_name,
                "identifier_value": master_value,
                "old_status": master_status,
                "new_status": matched_rows[0].get(api_status_col, ""),
                "status_changed": False,
                "change_note": "Identifier sama muncul di lebih dari satu baris API",
            })
            continue

        api_row = matched_rows[0]
        api_status = api_row.get(api_status_col, "")
        
        # Penyesuaian: Jika master lama adalah "Need Reverification" dan API bilang "Need Verification",
        # ubah status baru menjadi "Need Reverification" agar konsisten dan tidak dianggap berubah.
        norm_master = _normalize_value(master_status)
        norm_api = _normalize_value(api_status)
        
        if norm_master == "need reverification" and norm_api in ["need verification", "verification required"]:
            api_status = master_status
            norm_api = norm_master
            
        status_changed = norm_master != norm_api

        if status_changed:
            updated_master.at[idx, master_status_col] = api_status
            summary["updated"] += 1

        summary["matched"] += 1
        comparison_rows.append({
            "match_status": "Matched",
            "match_rule": group_name,
            "identifier_value": master_value,
            "store_code": master_row.get("store_code", "") or master_row.get("NETWORK ID UPDATED", ""),
            "business_name": master_row.get("business_name", "") or master_row.get("BRANCH NAME", ""),
            "network_name": master_row.get("network_name", "") or master_row.get("NAMA NETWORK", ""),
            "location_name": master_row.get("location_name", "") or master_row.get("BRANCH ID", ""),
            "old_status": master_status,
            "new_status": api_status,
            "status_changed": status_changed,
            "change_note": f"Diupdate dari '{master_status}' ke '{api_status}'" if status_changed else "Tidak ada perubahan",
        })

    updated_master = updated_master.drop(columns=["__match_key"], errors="ignore")
    comparison_df = pd.DataFrame(comparison_rows)

    log.info(
        f"Rekonsiliasi selesai: {summary['matched']} matched, "
        f"{summary['updated']} updated, {summary['not_found']} not found, "
        f"{summary['manual_review']} manual review, {summary['invalid']} invalid"
    )

    return updated_master, comparison_df, summary


# ── Database Persistence ──────────────────────────────────────────────

@transaction.atomic
def save_reconciliation_job(
    summary: dict,
    source_type: str = "",
    source_label: str = "",
    total_master: int = 0,
    total_api: int = 0,
) -> "ReconciliationJob":
    """Simpan ReconciliationJob ke database Supabase."""
    from gbp.models import ReconciliationJob

    job_name = f"Rekonsiliasi {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    job = ReconciliationJob.objects.create(
        job_name=job_name,
        source_type=source_type,
        source_label=source_label,
        total_master=total_master,
        total_api=total_api,
        total_matched=summary.get("matched", 0),
        total_updated=summary.get("updated", 0),
        total_unchanged=summary.get("matched", 0) - summary.get("updated", 0),
        total_not_found_api=summary.get("not_found", 0),
        total_not_found_master=0,
        total_invalid=summary.get("invalid", 0),
        total_manual_review=summary.get("manual_review", 0),
        total_error=0,
    )
    log.info(f"ReconciliationJob #{job.pk} dibuat.")
    return job


@transaction.atomic
def save_reconciliation_results(job, comparison_rows: list[dict]) -> int:
    """Simpan ReconciliationResult ke database Supabase. Returns jumlah baris disimpan."""
    from gbp.models import ReconciliationResult

    # Mapping match_status lama ke process_status baru
    STATUS_MAP = {
        "Matched": lambda row: "Updated" if row.get("status_changed") else "Unchanged",
        "Not Found": "Not Found in API",
        "Invalid": "Invalid",
        "Manual Review": "Manual Review",
        "Error": "Error",
    }

    objs = []
    for row in comparison_rows:
        match_status = row.get("match_status", "")
        mapper = STATUS_MAP.get(match_status, match_status)
        if callable(mapper):
            process_status = mapper(row)
        else:
            process_status = mapper

        objs.append(ReconciliationResult(
            job=job,
            store_code=str(row.get("store_code", "") or ""),
            business_name=str(row.get("business_name", "") or ""),
            network_name=str(row.get("network_name", "") or ""),
            location_name=str(row.get("location_name", "") or ""),
            identifier_value=str(row.get("identifier_value", "") or ""),
            match_rule=str(row.get("match_rule", "") or ""),
            old_status=str(row.get("old_status", "") or ""),
            new_status=str(row.get("new_status", "") or ""),
            process_status=process_status,
            status_changed=bool(row.get("status_changed", False)),
            change_note=str(row.get("change_note", "") or ""),
        ))

    ReconciliationResult.objects.bulk_create(objs, batch_size=500)
    log.info(f"Disimpan {len(objs)} ReconciliationResult untuk Job #{job.pk}.")
    return len(objs)


def update_master_statuses(comparison_rows: list[dict], master_key_col: str = "identifier_value") -> int:
    """
    Update MasterLocation.verification_status di Supabase berdasarkan hasil rekonsiliasi.
    Hanya update baris dengan status_changed=True.
    Returns jumlah baris yang diupdate.
    """
    from gbp.models import MasterLocation

    updated_count = 0
    now = timezone.now()

    for row in comparison_rows:
        if not row.get("status_changed"):
            continue
        identifier = str(row.get("identifier_value", "") or "").strip()
        new_status = str(row.get("new_status", "") or "").strip()
        if not identifier or not new_status:
            continue

        # Coba update berdasarkan store_code, location_name, atau business_name
        updated = MasterLocation.objects.filter(
            store_code=identifier
        ).update(verification_status=new_status, last_synced_at=now)

        if not updated:
            updated = MasterLocation.objects.filter(
                location_name=identifier
            ).update(verification_status=new_status, last_synced_at=now)

        if not updated:
            updated = MasterLocation.objects.filter(
                business_name__iexact=identifier
            ).update(verification_status=new_status, last_synced_at=now)

        updated_count += updated

    log.info(f"MasterLocation diupdate: {updated_count} baris.")
    return updated_count


def generate_changed_networks(comparison_rows: list[dict]) -> list[dict]:
    """
    Generate daftar network yang mengalami perubahan status.
    Returns list of dict: {identifier_value, old_status, new_status, change_note}
    """
    return [
        row for row in comparison_rows
        if row.get("status_changed") and row.get("match_status") == "Matched"
    ]


# ── Public Wrappers ───────────────────────────────────────────────────

def detect_status_column(columns: list[str]) -> str | None:
    return _detect_status_column(columns)


def detect_identifier_group(
    master_df: pd.DataFrame,
    api_df: pd.DataFrame,
) -> tuple[str, str, str] | None:
    return _detect_identifier_group(master_df, api_df)


normalize_value = _normalize_value
