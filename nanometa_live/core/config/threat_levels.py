"""The single definition of watchlist threat levels and how to present them.

Before this module existed there were seven independent threat-level color
maps in the app and four different vocabularies for the same field (the
banner said ACTION REQUIRED, the alert cards CRITICAL/HIGH RISK/WATCH/INFO,
the watchlist tables Critical/High/Moderate/Low, the HTML report lowercase
words) -- and they disagreed: the same "low" organism rendered green in the
report, grey in the watchlist table and cyan on the alert cards
(2026-08-17 reaudit). Every surface now derives label, meaning, color and
icon from here.

Colors follow the documented scheme (docs/configuration.md, "Threat Level
Behavior"): critical red, high orange, moderate amber, low blue. Text
colors are darkened so text-on-tint pairs clear WCAG AA.

This is core so ``core/export`` (the HTML report) can use it; the Dash
badge/tooltip helpers built on top of it live in
``app/utils/threat_display.py``.
"""

from typing import Dict, List

# Severity order, most severe first. Use this to sort tables and reports --
# a plain alphabetical sort puts "low" above "moderate".
THREAT_LEVEL_ORDER: List[str] = ["critical", "high", "moderate", "low"]

THREAT_LEVELS: Dict[str, Dict[str, str]] = {
    "critical": {
        "label": "Critical",
        "alias": "CRITICAL",
        "meaning": (
            "Highest-risk organisms: select agents and BSL-3+ pathogens. "
            "A detection calls for immediate notification and action per "
            "local protocol."
        ),
        "action": "Contact your safety officer immediately",
        "hex": "#dc3545",        # saturated identity color (borders, chips)
        "text_hex": "#8b0000",   # AA-safe on the tint below
        "bg_hex": "#f8d7da",
        "icon": "bi-exclamation-octagon-fill",
        "bootstrap": "danger",
    },
    "high": {
        "label": "High risk",
        "alias": "HIGH RISK",
        "meaning": (
            "High-risk pathogens, such as BSL-2 organisms with resistance "
            "or invasiveness concerns. A detection warrants prompt review "
            "and follow-up."
        ),
        "action": "Follow your safety protocols",
        "hex": "#fd7e14",
        "text_hex": "#721c24",
        "bg_hex": "#f8d7da",
        "icon": "bi-exclamation-triangle-fill",
        "bootstrap": "warning",
    },
    "moderate": {
        "label": "Moderate",
        "alias": "MODERATE",
        "meaning": (
            "Common clinical or environmental pathogens. Detections are "
            "informational and worth monitoring in context."
        ),
        "action": "Document and monitor",
        "hex": "#ffc107",
        "text_hex": "#664d03",
        "bg_hex": "#fff3cd",
        "icon": "bi-eye-fill",
        "bootstrap": "warning",
    },
    "low": {
        "label": "Low",
        "alias": "LOW",
        "meaning": (
            "Low-virulence or commensal organisms. Logged for completeness; "
            "no immediate action is expected from a detection."
        ),
        "action": "No immediate action required",
        "hex": "#17a2b8",
        "text_hex": "#0c5460",
        "bg_hex": "#d1ecf1",
        "icon": "bi-info-circle-fill",
        "bootstrap": "info",
    },
}

_UNKNOWN = {
    "label": "Unknown",
    "alias": "UNKNOWN",
    "meaning": "This entry carries no recognised threat level.",
    "action": "Review the watchlist entry",
    "hex": "#6c757d",
    "text_hex": "#343a40",
    "bg_hex": "#e9ecef",
    "icon": "bi-question-circle",
    "bootstrap": "secondary",
}


def threat_level_info(level: str) -> Dict[str, str]:
    """The presentation record for a level; a safe Unknown for anything else."""
    return THREAT_LEVELS.get(str(level or "").strip().lower(), _UNKNOWN)


def threat_severity(level: str) -> int:
    """Sort key: 0 = most severe. Unknown levels sort last."""
    try:
        return THREAT_LEVEL_ORDER.index(str(level or "").strip().lower())
    except ValueError:
        return len(THREAT_LEVEL_ORDER)


def threat_legend() -> List[Dict[str, str]]:
    """[{level, label, meaning, hex, ...}] in severity order, for legends."""
    return [
        {"level": lvl, **THREAT_LEVELS[lvl]} for lvl in THREAT_LEVEL_ORDER
    ]
