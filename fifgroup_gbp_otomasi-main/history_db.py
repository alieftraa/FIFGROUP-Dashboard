"""
history_db.py
-------------
Mengelola SQLite database untuk menyimpan riwayat fetch GBP.
Database ini digunakan oleh dashboard.py untuk menampilkan
data historis dan tren.

Tabel:
  runs      → metadata setiap eksekusi (tanggal, total, counts per status)
  snapshots → status per lokasi per run (foreign key ke runs)
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from collections import Counter

DB_PATH = "gbp_history.db"
log     = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# CONNECTION MANAGER
# ──────────────────────────────────────────────

@contextmanager
def get_conn():
    """Context manager untuk koneksi SQLite dengan auto-commit/rollback."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # akses kolom by name
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────
# INISIALISASI SCHEMA
# ──────────────────────────────────────────────

def init_db():
    """Buat tabel dan index jika belum ada. Aman dipanggil berulang kali."""
    with get_conn() as conn:
        conn.executescript("""
            -- Metadata setiap eksekusi fetch
            CREATE TABLE IF NOT EXISTS runs (
                run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date      TEXT    NOT NULL,          -- YYYY-MM-DD
                run_timestamp TEXT    NOT NULL,          -- YYYY-MM-DD HH:MM:SS
                total         INTEGER DEFAULT 0,
                verified      INTEGER DEFAULT 0,
                duplicate     INTEGER DEFAULT 0,
                suspended     INTEGER DEFAULT 0,
                unverified    INTEGER DEFAULT 0
            );

            -- Snapshot status per lokasi per run
            CREATE TABLE IF NOT EXISTS snapshots (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id            INTEGER NOT NULL,
                store_code        TEXT,
                location_name     TEXT,
                business_name     TEXT,
                address           TEXT,
                latitude          REAL,    -- disimpan sebagai float, NULL jika tidak ada
                longitude         REAL,
                coord_status      TEXT,    -- OK / MISSING / PARSE_ERROR / OUT_OF_RANGE
                status            TEXT,    -- Verified / Duplicate / Suspended / Verification Required
                has_vom           INTEGER  DEFAULT 0,
                is_duplicate      INTEGER  DEFAULT 0,
                is_suspended      INTEGER  DEFAULT 0,
                has_pending_edits INTEGER  DEFAULT 0,
                maps_uri          TEXT,
                fetched_at        TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
            );

            -- Index untuk query dashboard yang cepat
            CREATE INDEX IF NOT EXISTS idx_snap_run_id
                ON snapshots(run_id);
            CREATE INDEX IF NOT EXISTS idx_snap_status
                ON snapshots(status);
            CREATE INDEX IF NOT EXISTS idx_snap_store_code
                ON snapshots(store_code);
            CREATE INDEX IF NOT EXISTS idx_runs_date
                ON runs(run_date);
        """)
    log.info(f"Database siap: {Path(DB_PATH).resolve()}")


# ──────────────────────────────────────────────
# WRITE
# ──────────────────────────────────────────────

def save_run(records: list[dict]) -> int:
    """
    Simpan satu batch hasil fetch ke database.
    Return run_id yang baru dibuat.

    Dipanggil oleh fetch_status.py setelah semua lokasi selesai diparsing.
    """
    counts = Counter(r["status"] for r in records)
    now    = datetime.now()

    with get_conn() as conn:
        # Insert run metadata
        cur = conn.execute(
            """
            INSERT INTO runs
                (run_date, run_timestamp, total, verified, duplicate, suspended, unverified)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d %H:%M:%S"),
                len(records),
                counts.get("Verified", 0),
                counts.get("Duplicate", 0),
                counts.get("Suspended", 0),
                counts.get("Verification Required", 0),
            ),
        )
        run_id = cur.lastrowid

        # Bulk insert snapshots
        rows = [
            (
                run_id,
                r.get("store_code"),
                r.get("location_name"),
                r.get("business_name"),
                r.get("address"),
                r.get("latitude"),    # sudah float atau None dari fetch_status.py
                r.get("longitude"),
                r.get("coord_status", "MISSING"),
                r.get("status"),
                int(bool(r.get("has_vom",           False))),
                int(bool(r.get("is_duplicate",      False))),
                int(bool(r.get("is_suspended",      False))),
                int(bool(r.get("has_pending_edits", False))),
                r.get("maps_uri"),
                r.get("fetched_at"),
            )
            for r in records
        ]
        conn.executemany(
            """
            INSERT INTO snapshots (
                run_id, store_code, location_name, business_name,
                address, latitude, longitude, coord_status, status,
                has_vom, is_duplicate, is_suspended, has_pending_edits,
                maps_uri, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    log.info(f"Run #{run_id} disimpan ke DB: {len(records)} lokasi.")
    return run_id


# ──────────────────────────────────────────────
# READ — untuk dashboard
# ──────────────────────────────────────────────

def get_all_runs() -> list[dict]:
    """Ambil semua run, terbaru di atas. Dipakai untuk selector di dashboard."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY run_id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_run_id() -> int | None:
    """Ambil run_id terbaru."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
    return row["run_id"] if row else None


def get_snapshots(
    run_id: int,
    status_filter: list[str] | None = None,
    search: str | None = None,
) -> list[dict]:
    """
    Ambil semua snapshot untuk satu run.

    Args:
        run_id        : ID run yang dipilih
        status_filter : list status yang diinginkan, None = semua
        search        : string pencarian di business_name, store_code, location_name
    """
    query  = "SELECT * FROM snapshots WHERE run_id = ?"
    params: list = [run_id]

    if status_filter:
        placeholders = ",".join("?" * len(status_filter))
        query  += f" AND status IN ({placeholders})"
        params += status_filter

    if search:
        query  += """ AND (
            business_name  LIKE ? OR
            store_code     LIKE ? OR
            location_name  LIKE ?
        )"""
        pattern = f"%{search}%"
        params += [pattern, pattern, pattern]

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_status_trend(days: int = 30) -> list[dict]:
    """
    Tren status per hari untuk N hari terakhir.
    Dipakai untuk line chart di dashboard Overview.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                run_date,
                SUM(verified)   AS verified,
                SUM(duplicate)  AS duplicate,
                SUM(suspended)  AS suspended,
                SUM(unverified) AS unverified,
                SUM(total)      AS total
            FROM runs
            WHERE run_date >= date('now', ?)
            GROUP BY run_date
            ORDER BY run_date ASC
            """,
            (f"-{days} days",),
        ).fetchall()
    return [dict(r) for r in rows]


def get_run_by_id(run_id: int) -> dict | None:
    """Ambil detail satu run."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row else None