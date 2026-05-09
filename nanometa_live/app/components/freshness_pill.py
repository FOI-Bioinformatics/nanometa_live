"""
Per-barcode freshness pill component (U2 in the 2026-05-09 UX spec).

A small dbc.Badge that maps an "age in seconds" value to a coloured pill
(green / amber / red / muted) plus a compact age label. Used by the
sample selector and the Organisms per-sample table so operators can see
at a glance which barcode last produced data.
"""

from __future__ import annotations

from typing import Optional, Tuple

import dash_bootstrap_components as dbc

# Age band thresholds (seconds). Anything younger than the lower bound
# is considered fresh (green); the middle band warns; older values are
# treated as stale (red).
GREEN_MAX_S = 60.0
AMBER_MAX_S = 300.0


def _band_for_age(age_seconds: Optional[float]) -> Tuple[str, str]:
    """
    Return (Bootstrap colour, text utility class) for a given age.

    Unknown ages fall through to the muted secondary band so a barcode
    waiting on its first batch gets a neutral marker rather than green.
    """
    if age_seconds is None:
        return "secondary", "text-white"
    if age_seconds < GREEN_MAX_S:
        return "success", "text-white"
    if age_seconds < AMBER_MAX_S:
        return "warning", "text-dark"
    return "danger", "text-white"


def _format_age_label(age_seconds: Optional[float]) -> str:
    """Compact age label: '12s', '3m', '1h+', or '--' when unknown."""
    if age_seconds is None or age_seconds < 0:
        return "--"
    if age_seconds < 60:
        return f"{int(age_seconds)}s"
    if age_seconds < 3600:
        return f"{int(age_seconds // 60)}m"
    return "1h+"


def freshness_pill(
    sample_name: str,
    age_seconds: Optional[float],
    *,
    pill: bool = True,
    class_name: str = "ms-2",
) -> dbc.Badge:
    """
    Build a freshness badge for a single sample.

    Args:
        sample_name: Sample identifier (used for the accessible label).
        age_seconds: Wall-clock seconds since the sample's most recent
            output file mtime. ``None`` renders the muted unknown state.
        pill: Render with the dbc pill style (rounded ends).
        class_name: Extra Bootstrap utility classes for the badge.

    Returns:
        A dbc.Badge component carrying the colour, label, and aria
        attributes documented in the UX spec.
    """
    color, text_class = _band_for_age(age_seconds)
    label = _format_age_label(age_seconds)
    badge_class = f"{class_name} {text_class}".strip()
    # dbc.Badge does not accept aria-* kwargs; the component's title
    # attribute is enough for the visible tooltip and the surrounding
    # row carries aria-live at the container level.
    return dbc.Badge(
        label,
        color=color,
        pill=pill,
        className=badge_class,
        style={"fontSize": "0.75rem", "whiteSpace": "nowrap"},
        title=f"{sample_name}: {label} since last data",
    )
