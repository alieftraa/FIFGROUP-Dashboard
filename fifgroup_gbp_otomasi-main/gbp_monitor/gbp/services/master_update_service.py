"""
master_update_service.py — Service untuk manajemen data master lokasi.
Mendukung import dari CSV ke MasterLocation di Supabase via Django ORM.
"""

import csv
import io
import logging
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

log = logging.getLogger("gbp.services.master_update_service")

# ── Kolom CSV yang dikenali (case-insensitive) ────────────────────────
COLUMN_MAP = {
    # store_code
    "store_code": "store_code",
    "kode_kios": "store_code",
    "kode kios": "store_code",
    "kode_outlet": "store_code",
    "kode outlet": "store_code",
    "outlet_code": "store_code",
    "network_id_updated": "store_code",
    "network id updated": "store_code",
    # location_name
    "location_name": "location_name",
    "location name": "location_name",
    "location_id": "location_name",
    "location id": "location_name",
    "branch_id": "location_name",
    "branch id": "location_name",
    # business_name
    "business_name": "business_name",
    "business name": "business_name",
    "nama_bisnis": "business_name",
    "nama bisnis": "business_name",
    "nama_network": "business_name",
    "nama network": "business_name",
    "branch_name": "business_name",
    "branch name": "business_name",
    # network_name
    "network_name": "network_name",
    "network name": "network_name",
    "network": "network_name",
    "nama_brand": "network_name",
    "nama brand": "network_name",
    # account_name
    "account_name": "account_name",
    "account name": "account_name",
    "account": "account_name",
    # verification_status
    "verification_status": "verification_status",
    "verification status": "verification_status",
    "status_verifikasi": "verification_status",
    "status verifikasi": "verification_status",
    "gbp_status": "verification_status",
    "gbp status": "verification_status",
    "status": "verification_status",
    # area
    "area": "area",
    "area 2026": "area",
    "wilayah": "area",
    "region": "area",
    "area_name": "area",
    "area name": "area",
    # network
    "network": "network",
    "jenis_network": "network",
    "jenis network": "network",
    "network_type": "network",
    "network type": "network",
    "tipe_network": "network",
    "tipe network": "network",
    "kategori_network": "network",
    "kategori network": "network",
}

MODEL_FIELDS = ["store_code", "location_name", "business_name", "network_name", "account_name", "verification_status", "area", "network"]


def _map_columns(headers: list[str]) -> dict[str, str]:
    """
    Peta header CSV ke field model.
    Returns: {csv_col: model_field}
    """
    result = {}
    for header in headers:
        normalized = header.strip().lower()
        if normalized in COLUMN_MAP:
            model_field = COLUMN_MAP[normalized]
            if model_field not in result.values():
                result[header] = model_field
    return result


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


@transaction.atomic
def import_master_locations(
    filepath: str | None = None,
    file_content: bytes | None = None,
    filename: str = "upload",
) -> dict:
    """
    Import data master dari CSV ke tabel MasterLocation di Supabase.

    Args:
        filepath     : Path ke file CSV di disk (opsional)
        file_content : Bytes konten CSV (untuk upload; opsional)
        filename     : Nama file untuk logging

    Returns:
        dict: {total, created, updated, skipped, error, errors_detail}
    """
    from gbp.models import MasterLocation, MasterDataHistory

    summary = {"total": 0, "created": 0, "updated": 0, "skipped": 0, "error": 0, "errors_detail": []}

    # Baca konten file
    if file_content is not None:
        try:
            text = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_content.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))
    elif filepath:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File tidak ditemukan: {filepath}")
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            reader_content = f.read()
        reader = csv.DictReader(io.StringIO(reader_content))
    else:
        raise ValueError("Harus menyediakan filepath atau file_content.")

    rows = list(reader)
    if not rows:
        log.warning("File CSV kosong.")
        return summary

    headers = list(rows[0].keys())
    col_map = _map_columns(headers)

    if not col_map:
        raise ValueError(
            f"Tidak ada kolom yang dikenali di CSV. "
            f"Kolom ditemukan: {headers}. "
            f"Kolom yang dibutuhkan: store_code, location_name, business_name, dll."
        )

    log.info(f"Mapping kolom: {col_map}")

    # Hapus data master lama
    MasterLocation.objects.all().delete()
    log.info("Semua data MasterLocation sebelumnya telah dihapus.")

    now = timezone.now()

    for i, row in enumerate(rows, start=1):
        summary["total"] += 1
        try:
            # Map baris CSV ke field model
            data = {}
            for csv_col, model_field in col_map.items():
                val = _clean_value(row.get(csv_col))
                
                # Normalisasi area
                if model_field == "area":
                    if not val:
                        val = "Unknown Area"
                
                # Normalisasi network
                if model_field == "network":
                    if val:
                        v = val.lower()
                        if "sub kios" in v or "subkios" in v:
                            val = "Subkios"
                        elif "kios" in v:
                            val = "Kios"
                        elif "cabang" in v:
                            val = "Cabang"
                        elif "pos" in v:
                            val = "Pos"
                        else:
                            val = "Unknown"
                    else:
                        val = "Unknown"
                        
                data[model_field] = val

            # store_code adalah identifier utama
            store_code = data.get("store_code")

            if store_code:
                # Upsert berdasarkan store_code
                obj, created = MasterLocation.objects.update_or_create(
                    store_code=store_code,
                    defaults={k: v for k, v in data.items() if k != "store_code"},
                )
                if created:
                    summary["created"] += 1
                else:
                    summary["updated"] += 1
            else:
                # Tidak ada store_code — coba buat baru atau skip jika sudah ada
                location_name = data.get("location_name")
                business_name = data.get("business_name")

                if not location_name and not business_name:
                    summary["skipped"] += 1
                    summary["errors_detail"].append(f"Baris {i}: Tidak ada identifier (store_code/location_name/business_name).")
                    continue

                if location_name:
                    obj, created = MasterLocation.objects.update_or_create(
                        location_name=location_name,
                        defaults=data,
                    )
                else:
                    # Hanya buat baru jika business_name belum ada
                    if MasterLocation.objects.filter(business_name__iexact=business_name).exists():
                        summary["skipped"] += 1
                        continue
                    obj = MasterLocation.objects.create(**data)
                    created = True

                if created:
                    summary["created"] += 1
                else:
                    summary["updated"] += 1

        except Exception as exc:
            summary["error"] += 1
            summary["errors_detail"].append(f"Baris {i}: {exc}")
            log.warning(f"Error import baris {i}: {exc}")

    log.info(
        f"Import master selesai: {summary['total']} total, "
        f"{summary['created']} dibuat, {summary['updated']} diupdate, "
        f"{summary['skipped']} dilewati, {summary['error']} error."
    )

    # Simpan history total network
    total_saved = MasterLocation.objects.count()
    MasterDataHistory.objects.create(total_network=total_saved)
    log.info(f"History total network disimpan: {total_saved} networks.")

    return summary


def update_master_location_status(
    identifier: str,
    new_status: str,
    identifier_type: str = "store_code",
) -> bool:
    """
    Update satu MasterLocation berdasarkan identifier.

    Args:
        identifier      : Nilai identifier
        new_status      : Status baru
        identifier_type : Tipe identifier (store_code/location_name/business_name)

    Returns:
        True jika berhasil diupdate, False jika tidak ditemukan.
    """
    from gbp.models import MasterLocation

    now = timezone.now()
    filter_kwargs = {identifier_type: identifier}

    updated = MasterLocation.objects.filter(**filter_kwargs).update(
        verification_status=new_status,
        last_synced_at=now,
    )
    return updated > 0


def backup_master_file_if_needed(filepath: str) -> str | None:
    """Buat backup file master CSV dengan timestamp. Returns path backup atau None."""
    import shutil
    from datetime import datetime as dt
    path = Path(filepath)
    if not path.exists():
        return None
    ts = dt.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}_backup_{ts}{path.suffix}")
    shutil.copy(path, backup)
    return str(backup)


def read_master_csv(filepath: str) -> list[dict]:
    """Baca CSV master dan return list of dict."""
    import pandas as pd
    df = pd.read_csv(filepath, dtype=str, keep_default_na=False)
    return df.to_dict("records")
