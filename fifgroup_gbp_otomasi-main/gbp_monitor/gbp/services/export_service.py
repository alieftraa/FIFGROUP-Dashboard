"""
export_service.py — Service untuk export data ke CSV dan Excel.
Dimigrasikan dari dashboard.py (fungsi to_csv_bytes dan to_excel_bytes).
"""

import io
import logging

import pandas as pd

log = logging.getLogger("gbp.services.export_service")

# Kolom yang ditampilkan di export (sesuai dengan dashboard Streamlit)
EXPORT_COLUMNS = {
    "store_code": "Kode Kios",
    "business_name": "Nama Bisnis",
    "address": "Alamat",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "maps_uri": "URL Maps",
    "status": "Status",
    "fetched_at": "Diperbarui",
}


def snapshots_to_dataframe(snapshots: list[dict]) -> pd.DataFrame:
    """
    Konversi list snapshot dict ke DataFrame siap export.

    Args:
        snapshots: List of dict dari history_service.get_snapshots()

    Returns:
        DataFrame dengan kolom yang sudah diformat.
    """
    if not snapshots:
        return pd.DataFrame(columns=list(EXPORT_COLUMNS.values()))

    df = pd.DataFrame(snapshots)
    df["latitude"] = pd.to_numeric(df.get("latitude", pd.Series(dtype=float)), errors="coerce")
    df["longitude"] = pd.to_numeric(df.get("longitude", pd.Series(dtype=float)), errors="coerce")
    return df


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    Export DataFrame ke bytes CSV (UTF-8 with BOM untuk Excel compatibility).

    Args:
        df: DataFrame dengan kolom export

    Returns:
        bytes isi file CSV
    """
    cols = [c for c in EXPORT_COLUMNS.keys() if c in df.columns]
    export_df = df[cols].copy()
    export_df.columns = [EXPORT_COLUMNS[c] for c in cols]
    return export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    """
    Export DataFrame ke bytes Excel (.xlsx).

    Args:
        df: DataFrame dengan kolom export

    Returns:
        bytes isi file Excel
    """
    cols = [c for c in EXPORT_COLUMNS.keys() if c in df.columns]
    export_df = df[cols].copy()
    export_df.columns = [EXPORT_COLUMNS[c] for c in cols]

    # Excel tidak mendukung datetime dengan timezone — strip tz dari semua kolom datetime
    for col in export_df.columns:
        if pd.api.types.is_datetime64_any_dtype(export_df[col]):
            try:
                export_df[col] = export_df[col].dt.tz_localize(None)
            except TypeError:
                export_df[col] = export_df[col].dt.tz_convert(None)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="GBP Status")
        # Auto-fit kolom
        ws = writer.sheets["GBP Status"]
        for col in ws.columns:
            max_len = max(
                len(str(cell.value)) if cell.value is not None else 0
                for cell in col
            )
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)
    return buf.getvalue()


def comparison_to_csv_bytes(comparison_df: pd.DataFrame, master_source: str = "") -> bytes:
    """
    Export hasil rekonsiliasi ke CSV.

    Args:
        comparison_df : DataFrame hasil compare_master_to_api()
        master_source : Label sumber master (untuk kolom tambahan)

    Returns:
        bytes isi file CSV
    """
    show_cols = [
        "match_status", "match_rule", "identifier_value",
        "old_status", "new_status", "status_changed", "change_note",
    ]
    available = [c for c in show_cols if c in comparison_df.columns]
    export_df = comparison_df[available].copy()
    if master_source:
        export_df.insert(0, "Master Source", master_source)
    return export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
