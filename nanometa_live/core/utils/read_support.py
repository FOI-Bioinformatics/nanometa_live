"""Read support: how many classified reads back a detection.

One rule for every card, the Pathogen Report modal and the exported report.
The Dashboard used >= 100 reads for "HIGH" and the Organisms tab >= 1000,
both called it "confidence" and neither stated a threshold, so beside
"pending confirmatory validation" it read as if confirmation had been done
(Barcelona exercise feedback, 2026-11-24). It counts reads only.
"""

from __future__ import annotations

from typing import Any

READ_SUPPORT_HIGH = 100
READ_SUPPORT_MODERATE = 20

READ_SUPPORT_LABELS = {
    "high": "High read support",
    "moderate": "Moderate read support",
    "low": "Low read support",
    "none": "No reads",
}

READ_SUPPORT_TOOLTIP = (
    f"{READ_SUPPORT_HIGH} or more classified reads is high, "
    f"{READ_SUPPORT_MODERATE} to {READ_SUPPORT_HIGH - 1} moderate, fewer low. "
    "This counts reads only; it does not confirm the identification "
    "(see the Validation tab)."
)

# Words the callers already pass: the modal's "High/Moderate/Low/N/A", the
# alert panel's upper-case form and the Organisms cards' "medium".
_WORD_TO_LEVEL = {
    "high": "high",
    "moderate": "moderate",
    "medium": "moderate",
    "low": "low",
    "none": "none",
    "n/a": "none",
}


def read_support_level(reads: Any) -> str:
    """``high`` / ``moderate`` / ``low`` / ``none`` for a read count."""
    try:
        r = int(reads)
    except (TypeError, ValueError):
        return "none"
    if r >= READ_SUPPORT_HIGH:
        return "high"
    if r >= READ_SUPPORT_MODERATE:
        return "moderate"
    if r >= 1:
        return "low"
    return "none"


def read_support_label(word: Any) -> str:
    """Display label for a level word in any of the cases in use."""
    level = _WORD_TO_LEVEL.get(str(word or "").strip().lower(), "none")
    return READ_SUPPORT_LABELS[level]
