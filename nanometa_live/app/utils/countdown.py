"""
Pure helpers for the realtime-timeout countdown (U3, 2026-05-09 UX spec).

Renders an ``auto_stop_remaining_s`` integer as a human-readable string
and assigns the appropriate Bootstrap utility class for the right-hand
side of the verdict banner. The class escalates from text-muted (calm)
through text-warning (under five minutes) to text-danger (under one
minute).
"""

from __future__ import annotations

from typing import Optional, Tuple

# Class-escalation thresholds (seconds remaining).
WARN_THRESHOLD_S = 5 * 60
DANGER_THRESHOLD_S = 60


def format_countdown(remaining_s: Optional[int]) -> Optional[str]:
    """Format a remaining-seconds value for display.

    Returns ``None`` when the input is missing or non-positive (the
    callback uses that as the signal to render nothing). Sub-minute
    values render as ``"Ns"``; values below an hour as ``"Mm SSs"``;
    longer values as ``"Hh MMm"``.
    """
    if remaining_s is None:
        return None
    try:
        remaining_s = int(remaining_s)
    except (TypeError, ValueError):
        return None
    if remaining_s <= 0:
        return "0s"
    if remaining_s < 60:
        return f"{remaining_s}s"
    if remaining_s < 3600:
        minutes, seconds = divmod(remaining_s, 60)
        return f"{minutes}m {seconds:02d}s"
    hours, rem = divmod(remaining_s, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{hours}h {minutes:02d}m"


def countdown_classes(remaining_s: Optional[int]) -> Tuple[str, str]:
    """Return (text-utility class, icon class) for a remaining-seconds value.

    Mirrors the visual states described in the UX spec:
    - text-muted, hourglass-split when more than five minutes remain
    - text-warning, hourglass-bottom under five minutes
    - text-danger, hourglass-bottom under one minute
    """
    if remaining_s is None:
        return "text-muted", "bi-hourglass-split"
    try:
        remaining_s = int(remaining_s)
    except (TypeError, ValueError):
        return "text-muted", "bi-hourglass-split"
    if remaining_s <= DANGER_THRESHOLD_S:
        return "text-danger fw-bold", "bi-hourglass-bottom"
    if remaining_s <= WARN_THRESHOLD_S:
        return "text-warning fw-semibold", "bi-hourglass-bottom"
    return "text-muted fw-medium", "bi-hourglass-split"
