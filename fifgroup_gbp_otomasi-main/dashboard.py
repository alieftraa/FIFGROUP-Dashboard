"""
dashboard.py
------------
Dashboard monitoring status verifikasi Google Business Profile.
Membaca data dari gbp_history.db yang diisi oleh fetch_status.py.

Cara menjalankan:
    streamlit run dashboard.py

Fitur:
  - Summary cards (Total / Verified / Duplicate / Suspended)
  - Tren status 30 hari
  - Tabel dengan search, filter, sort, pagination
  - Export CSV & Excel
  - Detail lokasi (klik dari tabel)
  - Peta interaktif dengan marker berwarna per status
"""

import io
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import history_db as db
import fetch_status

# ──────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="GBP Monitor",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# KONSTANTA
# ──────────────────────────────────────────────

STATUS_META = {
    "Verified":              {"icon": "🟢", "color": "#22c55e", "map_color": "green"},
    "Duplicate":             {"icon": "🟡", "color": "#eab308", "map_color": "orange"},
    "Suspended":             {"icon": "🔴", "color": "#ef4444", "map_color": "red"},
    "Verification Required": {"icon": "⚪", "color": "#94a3b8", "map_color": "gray"},
}

UPDATE_PAGE = "🔄 Update Status Verifikasi"
PAGE_SIZE = 50

IDENTIFIER_GROUPS = [
    (
        "NETWORK ID UPDATED",
        ["NETWORK ID UPDATED", "network_id_updated", "networkidupdated"],
        ["store_code", "kode_outlet", "kode_kios", "outlet_code"],
    ),
    (
        "NAMA NETWORK",
        ["NAMA NETWORK", "nama_network", "network", "business_name"],
        ["business_name", "business_location_name", "network_name", "nama_network", "nama_outlet"],
    ),
    (
        "BRANCH ID",
        ["BRANCH ID", "branch_id", "branchid"],
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


def _normalize_value(value) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    if isinstance(value, (int,)):
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
    lookup = {column.casefold(): column for column in columns}
    for candidate in candidates:
        if candidate.casefold() in lookup:
            return lookup[candidate.casefold()]
    return None


def _detect_status_column(columns: list[str]) -> str | None:
    return _first_existing_column(columns, STATUS_CANDIDATES)


def _detect_identifier_group(master_df: pd.DataFrame, api_df: pd.DataFrame) -> tuple[str, str, str] | None:
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


def compare_master_to_api(
    master_df: pd.DataFrame,
    api_df: pd.DataFrame,
    master_status_col: str | None = None,
    api_status_col: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Bandingkan master vs API dan kembalikan master yang sudah diperbarui plus tabel hasil."""
    if master_df.empty:
        empty = master_df.copy()
        return empty, empty, {"matched": 0, "updated": 0, "invalid": 0, "manual_review": 0, "not_found": 0}

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
    master = master_df.copy()
    api = api_df.copy()

    master["__match_key"] = master[master_key_col].map(_normalize_value)
    api["__match_key"] = api[api_key_col].map(_normalize_value)

    api_index = {}
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
                "master_identifier": master_key_col,
                "api_identifier": api_key_col,
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
                "master_identifier": master_key_col,
                "api_identifier": api_key_col,
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
                "master_identifier": master_key_col,
                "api_identifier": api_key_col,
                "identifier_value": master_value,
                "old_status": master_status,
                "new_status": matched_rows[0].get(api_status_col, ""),
                "status_changed": False,
                "change_note": "Identifier sama muncul di lebih dari satu baris API",
            })
            continue

        api_row = matched_rows[0]
        api_status = api_row.get(api_status_col, "")
        status_changed = _normalize_value(master_status) != _normalize_value(api_status)
        if status_changed:
            updated_master.at[idx, master_status_col] = api_status
            summary["updated"] += 1

        summary["matched"] += 1
        comparison_rows.append({
            "match_status": "Matched",
            "match_rule": group_name,
            "master_identifier": master_key_col,
            "api_identifier": api_key_col,
            "identifier_value": master_value,
            "old_status": master_status,
            "new_status": api_status,
            "status_changed": status_changed,
            "change_note": f"Diupdate dari {master_status} ke {api_status}" if status_changed else "Tidak ada perubahan",
        })

    updated_master = updated_master.drop(columns=["__match_key"], errors="ignore")
    comparison_df = pd.DataFrame(comparison_rows)
    return updated_master, comparison_df, summary


def _read_master_csv(uploaded_file) -> pd.DataFrame:
    return pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)


def _read_master_sqlite(db_path: str, table_name: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)


def _backup_file(path: str) -> str:
    source = Path(path)
    backup = source.with_name(f"{source.stem}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{source.suffix}")
    shutil.copy(source, backup)
    return str(backup)


def _write_csv_file(path: str, df: pd.DataFrame) -> None:
    df.to_csv(path, index=False, encoding="utf-8")


def _update_sqlite_file(
    path: str,
    table_name: str,
    updated_df: pd.DataFrame,
    key_col: str,
    status_col: str,
) -> int:
    changed_rows = updated_df[updated_df.get("__changed", False)].copy()
    if changed_rows.empty:
        return 0

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        updated_count = 0
        for _, row in changed_rows.iterrows():
            key_value = row.get(key_col, "")
            if pd.isna(key_value) or str(key_value).strip() == "":
                continue
            cursor.execute(
                f'UPDATE "{table_name}" SET "{status_col}" = ? WHERE "{key_col}" = ?',
                (row[status_col], key_value),
            )
            updated_count += cursor.rowcount
        conn.commit()

    return updated_count


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def status_label(status: str) -> str:
    meta = STATUS_META.get(status, {"icon": "❓"})
    return f"{meta['icon']} {status}"


@st.cache_data(ttl=120, show_spinner=False)
def load_snapshots(run_id: int, statuses: tuple, search: str) -> pd.DataFrame:
    """Load + cache snapshot dari DB. Cache invalidasi tiap 2 menit."""
    rows = db.get_snapshots(
        run_id,
        status_filter=list(statuses) if statuses else None,
        search=search or None,
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_trend(days: int = 30) -> pd.DataFrame:
    rows = db.get_status_trend(days)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("run_date")


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="GBP Status")
    return buf.getvalue()


def build_map(df_map: pd.DataFrame) -> folium.Map:
    """Buat folium map dengan marker berwarna sesuai status."""
    center = [df_map["latitude"].mean(), df_map["longitude"].mean()]
    m = folium.Map(location=center, zoom_start=6, tiles="CartoDB positron")

    for _, row in df_map.iterrows():
        color = STATUS_META.get(row["status"], {}).get("map_color", "gray")
        popup = folium.Popup(
            f"""
            <div style="font-family:sans-serif;min-width:220px;font-size:13px">
                <b>{row['business_name']}</b><br>
                <span style="color:#666">{row['store_code']}</span>
                <hr style="margin:5px 0">
                📍 {row['address']}<br>
                🔵 {row['latitude']:.7f}, {row['longitude']:.7f}<br>
                <hr style="margin:5px 0">
                <b>Status:</b> {row['status']}
            </div>
            """,
            max_width=300,
        )
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=7,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            popup=popup,
            tooltip=f"{row['business_name']} — {row['status']}",
        ).add_to(m)

    # Legend
    legend = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                background:white;padding:12px 16px;border-radius:8px;
                box-shadow:0 2px 10px rgba(0,0,0,0.15);font-family:sans-serif;font-size:13px">
        <b>Status</b><br>
        <span style="color:#22c55e;font-size:16px">●</span> Verified<br>
        <span style="color:#f59e0b;font-size:16px">●</span> Duplicate<br>
        <span style="color:#ef4444;font-size:16px">●</span> Suspended<br>
        <span style="color:#94a3b8;font-size:16px">●</span> Unverified
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))
    return m


# ──────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────

db.init_db()
all_runs = db.get_all_runs()

st.sidebar.title("📍 GBP Monitor")
st.sidebar.caption("FIFGROUP — Business Profile Dashboard")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Halaman",
    ["📊 Overview", "📋 Data Table", "🗺️ Map View", UPDATE_PAGE],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

if not all_runs and page != UPDATE_PAGE:
    st.error("Belum ada data. Jalankan `python fetch_status.py` terlebih dahulu.")
    st.stop()

sel_run_id = None
sel_run = None
sel_statuses: list[str] = []
search_text = ""

if page != UPDATE_PAGE:
    # Run selector
    run_labels = {
        f"#{r['run_id']} · {r['run_date']} ({r['total']:,} lokasi)": r["run_id"]
        for r in all_runs
    }
    sel_label  = st.sidebar.selectbox("📅 Pilih Run", list(run_labels.keys()))
    sel_run_id = run_labels[sel_label]
    sel_run    = db.get_run_by_id(sel_run_id)

    st.sidebar.markdown("---")

    # Filter status
    st.sidebar.subheader("Filter Status")
    all_statuses = list(STATUS_META.keys())
    for s in all_statuses:
        if st.sidebar.checkbox(status_label(s), value=True, key=f"cb_{s}"):
            sel_statuses.append(s)

    st.sidebar.markdown("---")

    # Search
    search_text = st.sidebar.text_input(
        "🔍 Cari",
        placeholder="Nama bisnis / kode kios / location ID",
    )

    st.sidebar.markdown("---")

# ──────────────────────────────────────────────
# LOAD DATA
# ──────────────────────────────────────────────

df = load_snapshots(sel_run_id, tuple(sel_statuses), search_text) if sel_run_id is not None else pd.DataFrame()


# ══════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ══════════════════════════════════════════════

if page == "📊 Overview":
    st.title("📊 Overview")
    st.caption(
        f"Run #{sel_run_id} · {sel_run['run_timestamp']} · "
        f"{sel_run['total']:,} total lokasi"
    )

    # ── Summary Cards ───────────────────────
    c1, c2, c3, c4 = st.columns(4)

    total = sel_run["total"] or 1   # hindari division by zero

    c1.metric(
        "📍 Total Lokasi",
        f"{sel_run['total']:,}",
    )
    c2.metric(
        "🟢 Verified",
        f"{sel_run['verified']:,}",
        f"{sel_run['verified']/total*100:.1f}% dari total",
    )
    c3.metric(
        "🟡 Duplicate",
        f"{sel_run['duplicate']:,}",
        f"{sel_run['duplicate']/total*100:.1f}% dari total",
        delta_color="inverse",
    )
    c4.metric(
        "🔴 Suspended",
        f"{sel_run['suspended']:,}",
        f"{sel_run['suspended']/total*100:.1f}% dari total",
        delta_color="inverse",
    )

    st.markdown("---")

    # ── Tren & Distribusi ───────────────────
    col_trend, col_dist = st.columns([3, 1])

    with col_trend:
        st.subheader("Tren Status — 30 Hari Terakhir")
        df_trend = load_trend(30)
        if not df_trend.empty:
            st.line_chart(
                df_trend[["verified", "duplicate", "suspended", "unverified"]],
                color=["#22c55e", "#eab308", "#ef4444", "#94a3b8"],
            )
        else:
            st.info("Belum cukup data historis untuk tren. Jalankan fetch beberapa hari.")

    with col_dist:
        st.subheader("Distribusi")
        dist = {
            "🟢 Verified":    sel_run["verified"],
            "🟡 Duplicate":   sel_run["duplicate"],
            "🔴 Suspended":   sel_run["suspended"],
            "⚪ Unverified":   sel_run["unverified"],
        }
        df_dist = pd.DataFrame.from_dict(dist, orient="index", columns=["Jumlah"])
        st.bar_chart(df_dist)

    # ── Riwayat Run ─────────────────────────
    st.markdown("---")
    st.subheader("Riwayat Semua Run")
    df_runs = pd.DataFrame(all_runs)[[
        "run_id","run_date","run_timestamp",
        "total","verified","duplicate","suspended","unverified"
    ]]
    df_runs.columns = [
        "Run ID","Tanggal","Timestamp",
        "Total","Verified","Duplicate","Suspended","Unverified"
    ]
    st.dataframe(df_runs, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════
# PAGE 2 — DATA TABLE
# ══════════════════════════════════════════════

elif page == "📋 Data Table":
    st.title("📋 Data Lokasi")
    st.caption(
        f"{len(df):,} lokasi ditampilkan"
        + (f" dari {sel_run['total']:,} total" if search_text or len(sel_statuses) < 4 else "")
    )

    if df.empty:
        st.warning("Tidak ada data yang cocok dengan filter saat ini.")
        st.stop()

    # ── Sort ────────────────────────────────
    sort_col = st.selectbox(
        "Urutkan berdasarkan",
        ["business_name", "store_code", "status", "fetched_at"],
        format_func=lambda x: {
            "business_name": "Nama Bisnis",
            "store_code":    "Kode Kios",
            "status":        "Status",
            "fetched_at":    "Waktu Update",
        }.get(x, x),
        horizontal=True,
    )
    sort_asc = st.radio("Urutan", ["A → Z", "Z → A"], horizontal=True) == "A → Z"
    df = df.sort_values(sort_col, ascending=sort_asc)

    # ── Tabel utama ─────────────────────────
    display_cols = {
        "store_code":    "Kode Kios",
        "business_name": "Nama Bisnis",
        "address":       "Alamat",
        "latitude":      "Latitude",
        "longitude":     "Longitude",
        "status":        "Status",
        "fetched_at":    "Diperbarui",
    }

    df_show = df[list(display_cols.keys())].copy()
    df_show.columns = list(display_cols.values())
    df_show["Status"] = df_show["Status"].map(status_label)

    # Format koordinat: 7 desimal, "-" jika kosong
    df_show["Latitude"]  = df_show["Latitude"].map(
        lambda v: f"{v:.7f}" if pd.notna(v) else "—"
    )
    df_show["Longitude"] = df_show["Longitude"].map(
        lambda v: f"{v:.7f}" if pd.notna(v) else "—"
    )

    # Pagination
    total_pages  = max(1, (len(df_show) - 1) // PAGE_SIZE + 1)
    _, col_pnum, _ = st.columns([2, 1, 2])
    with col_pnum:
        cur_page = st.number_input(
            f"Halaman (dari {total_pages})",
            min_value=1, max_value=total_pages, value=1,
        )
    start    = (cur_page - 1) * PAGE_SIZE
    df_page  = df_show.iloc[start : start + PAGE_SIZE]

    st.dataframe(df_page, use_container_width=True, hide_index=True)
    st.caption(f"Menampilkan baris {start+1}–{min(start+PAGE_SIZE, len(df_show))} dari {len(df_show):,}")

    # ── Export ──────────────────────────────
    st.markdown("---")
    col_e1, col_e2, _ = st.columns([1, 1, 3])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    col_e1.download_button(
        "⬇️ Export CSV",
        data=to_csv_bytes(df[list(display_cols.keys())]),
        file_name=f"gbp_export_{ts}.csv",
        mime="text/csv",
    )
    col_e2.download_button(
        "⬇️ Export Excel",
        data=to_excel_bytes(df[list(display_cols.keys())]),
        file_name=f"gbp_export_{ts}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ── Detail View ─────────────────────────
    st.markdown("---")
    st.subheader("🔍 Detail Lokasi")

    options = ["— Pilih lokasi —"] + df["business_name"].tolist()
    sel_loc = st.selectbox("Pilih atau cari nama bisnis", options)

    if sel_loc != "— Pilih lokasi —":
        row = df[df["business_name"] == sel_loc].iloc[0]
        d1, d2 = st.columns(2)

        with d1:
            st.markdown(f"**Nama Bisnis**   : {row['business_name']}")
            st.markdown(f"**Kode Kios**     : `{row['store_code']}`")
            st.markdown(f"**Location ID**   : `{row['location_name']}`")
            st.markdown(f"**Alamat**         : {row['address']}")
            st.markdown(f"**Status**         : {status_label(row['status'])}")
            st.markdown(f"**Diperbarui**     : {row['fetched_at']}")

        with d2:
            lat_str = f"{row['latitude']:.7f}" if pd.notna(row['latitude']) else "—"
            lng_str = f"{row['longitude']:.7f}" if pd.notna(row['longitude']) else "—"
            st.markdown(f"**Latitude**       : `{lat_str}`")
            st.markdown(f"**Longitude**      : `{lng_str}`")
            st.markdown(f"**Has VoM**        : {'✅ Ya' if row['has_vom'] else '❌ Tidak'}")
            st.markdown(f"**Duplicate**      : {'⚠️ Ya' if row['is_duplicate'] else '— Tidak'}")
            st.markdown(f"**Suspended**      : {'🚫 Ya' if row['is_suspended'] else '— Tidak'}")
            st.markdown(f"**Pending Edits**  : {'⏳ Ya' if row['has_pending_edits'] else '— Tidak'}")

        # Copy helpers
        st.markdown("**Salin:**")
        cc1, cc2, cc3 = st.columns(3)
        cc1.markdown("Location ID")
        cc1.code(row["location_name"] or "—", language=None)

        if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
            cc2.markdown("LatLong")
            cc2.code(f"{row['latitude']:.7f},{row['longitude']:.7f}", language=None)

        if row.get("maps_uri"):
            cc3.markdown("Google Maps")
            cc3.link_button("🗺️ Buka Maps", row["maps_uri"])


# ══════════════════════════════════════════════
# PAGE 3 — MAP VIEW
# ══════════════════════════════════════════════

elif page == "🗺️ Map View":
    st.title("🗺️ Peta Persebaran Lokasi")

    df_map = df.dropna(subset=["latitude", "longitude"]).copy()

    col_info1, col_info2, col_info3 = st.columns(3)
    col_info1.metric("Ditampilkan di peta", f"{len(df_map):,}")
    col_info2.metric("Tanpa koordinat",     f"{len(df) - len(df_map):,}")
    col_info3.metric("Total filtered",      f"{len(df):,}")

    if df_map.empty:
        st.warning(
            "Tidak ada lokasi dengan koordinat valid untuk ditampilkan. "
            "Pastikan `latlng` sudah diambil dari GBP API."
        )
    else:
        m = build_map(df_map)
        st_folium(m, use_container_width=True, height=620, returned_objects=[])

        # Breakdown koordinat error
        if "coord_status" in df.columns:
            coord_issues = df[df["coord_status"] != "OK"]
            if not coord_issues.empty:
                with st.expander(f"⚠️ {len(coord_issues)} lokasi dengan masalah koordinat"):
                    st.dataframe(
                        coord_issues[["store_code","business_name","coord_status","address"]],
                        use_container_width=True,
                        hide_index=True,
                    )


# ══════════════════════════════════════════════
# PAGE 4 — UPDATE STATUS VERIFIKASI
# ══════════════════════════════════════════════

elif page == UPDATE_PAGE:
    st.title("🔄 Update Status Verifikasi GBP")
    st.caption("Bandingkan status verifikasi master dengan data terbaru dari Google Business Profile API, lalu update hanya baris yang berubah.")

    st.info(
        "Identifikasi baris dilakukan dengan prioritas: Location ID, Store Code, Account ID, lalu Business Name. "
        "Jika identifier kosong atau muncul ganda, baris akan ditandai untuk cek manual."
    )

    source_type = st.radio("Sumber master", ["CSV", "SQLite"], horizontal=True)
    col_left, col_right = st.columns(2)

    with col_left:
        master_path = st.text_input(
            "Path file master",
            placeholder=r"D:\path\to\master.csv atau D:\path\to\master.db",
        )

    with col_right:
        account_id = st.text_input(
            "Account ID GBP (opsional)",
            placeholder="accounts/123456789",
        )

    uploaded_master = None
    sqlite_table = "kios"
    if source_type == "CSV":
        uploaded_master = st.file_uploader("Atau upload master CSV", type=["csv"])
    else:
        sqlite_table = st.text_input("Nama tabel SQLite", value="kios")

    save_to_disk = st.checkbox("Simpan perubahan ke file master di disk", value=bool(master_path))

    run_update = st.button("🔍 Ambil data terbaru & bandingkan", type="primary")

    if run_update:
        try:
            with st.spinner("Mengambil data terbaru dari GBP API..."):
                api_records = fetch_status.fetch_records(account_id or None)
            api_df = pd.DataFrame(api_records)

            if api_df.empty:
                st.error("Data API kosong. Tidak ada baris yang bisa dibandingkan.")
                st.stop()

            if source_type == "CSV":
                if uploaded_master is not None:
                    master_df = _read_master_csv(uploaded_master)
                    master_source_label = "upload CSV"
                elif master_path:
                    master_df = pd.read_csv(master_path)
                    master_source_label = master_path
                else:
                    st.error("Isi path master CSV atau upload file master terlebih dahulu.")
                    st.stop()
            else:
                if not master_path:
                    st.error("Isi path file SQLite terlebih dahulu.")
                    st.stop()
                master_df = _read_master_sqlite(master_path, sqlite_table)
                master_source_label = f"{master_path} :: {sqlite_table}"

            if master_df.empty:
                st.warning("Master data kosong, tidak ada yang bisa diupdate.")
                st.stop()

            master_status_col = _detect_status_column(list(master_df.columns))
            api_status_col = _detect_status_column(list(api_df.columns))
            master_key_group = _detect_identifier_group(master_df, api_df)

            updated_master_df, comparison_df, summary = compare_master_to_api(
                master_df,
                api_df,
                master_status_col=master_status_col,
                api_status_col=api_status_col,
            )

            updated_master_df["__changed"] = comparison_df["status_changed"].fillna(False).tolist()

            st.success(f"Pencocokan selesai untuk {len(master_df):,} baris master dan {len(api_df):,} baris API.")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Matched", f"{summary['matched']:,}")
            m2.metric("Updated", f"{summary['updated']:,}")
            m3.metric("Manual Review", f"{summary['manual_review']:,}")
            m4.metric("Invalid / Not Found", f"{summary['invalid'] + summary['not_found']:,}")

            status_summary = pd.DataFrame([
                {"Kategori": "Matched", "Jumlah": summary["matched"]},
                {"Kategori": "Updated", "Jumlah": summary["updated"]},
                {"Kategori": "Manual Review", "Jumlah": summary["manual_review"]},
                {"Kategori": "Invalid", "Jumlah": summary["invalid"]},
                {"Kategori": "Not Found", "Jumlah": summary["not_found"]},
            ])
            st.bar_chart(status_summary.set_index("Kategori"))

            show_cols = [
                "match_status",
                "match_rule",
                "identifier_value",
                "old_status",
                "new_status",
                "status_changed",
                "change_note",
            ]
            comparison_show = comparison_df[show_cols].copy()
            comparison_show.insert(0, "Master Source", master_source_label)

            st.subheader("Tabel Hasil Pencocokan")
            st.dataframe(comparison_show, use_container_width=True, hide_index=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                "⬇️ Download hasil pencocokan CSV",
                data=to_csv_bytes(comparison_show),
                file_name=f"gbp_match_result_{ts}.csv",
                mime="text/csv",
            )

            changed_rows = comparison_df[comparison_df["status_changed"] == True]  # noqa: E712
            if not changed_rows.empty:
                st.subheader("Perubahan Status")
                changed_show = changed_rows[["identifier_value", "old_status", "new_status", "match_rule", "change_note"]].copy()
                changed_show.columns = ["Identifier", "Status Lama", "Status Baru", "Rule", "Catatan"]
                st.dataframe(changed_show, use_container_width=True, hide_index=True)
            else:
                st.info("Tidak ada status yang berubah.")

            if save_to_disk:
                if not master_path:
                    st.warning("Mode simpan ke disk diaktifkan, tetapi path master belum diisi. Hasil hanya ditampilkan di layar.")
                else:
                    backup_path = _backup_file(master_path)
                    if source_type == "CSV":
                        _write_csv_file(master_path, updated_master_df.drop(columns=["__changed"], errors="ignore"))
                        st.success(f"CSV master diperbarui. Backup tersimpan di {backup_path}")
                    else:
                        if not master_key_group:
                            st.error("Tidak ada identifier yang cocok untuk update SQLite.")
                        else:
                            _, master_key_col, _ = master_key_group
                            status_col = master_status_col or _detect_status_column(list(master_df.columns))
                            updated_count = _update_sqlite_file(
                                master_path,
                                sqlite_table,
                                updated_master_df,
                                master_key_col,
                                status_col,
                            )
                            st.success(f"SQLite master diperbarui ({updated_count} baris terkena update). Backup tersimpan di {backup_path}")

            st.subheader("Preview Master Setelah Update")
            preview_cols = [col for col in [master_key_group[1] if master_key_group else None, master_status_col] if col]
            preview_cols = [col for col in preview_cols if col in updated_master_df.columns]
            if preview_cols:
                st.dataframe(updated_master_df[preview_cols].head(50), use_container_width=True, hide_index=True)
            else:
                st.dataframe(updated_master_df.head(50), use_container_width=True, hide_index=True)

        except Exception as exc:
            st.error(f"Gagal menjalankan update status: {exc}")