"""
utils.py — Konstanta dan helper functions untuk GBP Monitor.
"""

# ── Status Metadata ───────────────────────────────────────────────────
STATUS_META: dict[str, dict] = {
    "Verified": {
        "icon": "✅",
        "label": "Verified",
        "color": "#22c55e",
        "bg": "rgba(34, 197, 94, 0.15)",
        "map_color": "green",
        "badge_class": "badge-verified",
    },
    "Duplicate": {
        "icon": "⚠️",
        "label": "Duplicate",
        "color": "#eab308",
        "bg": "rgba(234, 179, 8, 0.15)",
        "map_color": "orange",
        "badge_class": "badge-duplicate",
    },
    "Suspended": {
        "icon": "🚫",
        "label": "Suspended",
        "color": "#ef4444",
        "bg": "rgba(239, 68, 68, 0.15)",
        "map_color": "red",
        "badge_class": "badge-suspended",
    },
    "Need Verification": {
        "icon": "⚪",
        "label": "Need Verification",
        "color": "#94a3b8",
        "bg": "rgba(148, 163, 184, 0.15)",
        "map_color": "gray",
        "badge_class": "badge-unverified",
    },
}

ALL_STATUSES = list(STATUS_META.keys())

PAGE_SIZE = 50


def get_status_meta(status: str) -> dict:
    """Ambil metadata status. Return dict kosong jika tidak dikenal."""
    return STATUS_META.get(status, {
        "icon": "❓",
        "label": status,
        "color": "#64748b",
        "bg": "rgba(100, 116, 139, 0.15)",
        "map_color": "gray",
        "badge_class": "badge-unknown",
    })


def status_label(status: str) -> str:
    """Format status dengan icon, contoh: '✅ Verified'."""
    meta = get_status_meta(status)
    return f"{meta['icon']} {meta['label']}"


def format_coordinate(value) -> str:
    """Format koordinat float ke 7 desimal, atau '—' jika kosong."""
    try:
        f = float(value)
        return f"{f:.7f}"
    except (TypeError, ValueError):
        return "—"
