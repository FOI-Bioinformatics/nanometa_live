"""Dash helpers that present threat levels consistently across the GUI.

Data comes from the single definition in
``core/config/threat_levels.py``; this module only turns it into
components. Every badge carries the level's plain-language meaning as a
hover title, so an operator seeing "Critical" anywhere can learn what it
implies without leaving the screen (2026-08-17 reaudit: no surface
explained the levels at all).
"""

from dash import html
import dash_bootstrap_components as dbc

from nanometa_live.core.config.threat_levels import (
    THREAT_LEVEL_ORDER,
    threat_legend,
    threat_level_info,
)

__all__ = [
    "THREAT_LEVEL_ORDER",
    "threat_badge",
    "threat_legend_inline",
    "threat_legend_block",
]


def threat_badge(level: str, className: str = "", uppercase: bool = False):
    """A colored badge for a threat level, with the meaning as hover text."""
    info = threat_level_info(level)
    return dbc.Badge(
        info["alias"] if uppercase else info["label"],
        title=info["meaning"],
        className=className,
        style={
            "backgroundColor": info["hex"],
            "color": "#fff" if level != "moderate" else info["text_hex"],
        },
    )


def threat_badges_row():
    """The four level badges in severity order, each with its meaning on hover."""
    return html.Span([
        threat_badge(entry["level"], className="me-1")
        for entry in threat_legend()
    ])


def threat_legend_inline():
    """One-line 'Threat levels:' key with hoverable badges (dashboard footer)."""
    return html.Small(
        [html.Span("Threat levels: ", className="me-1"), threat_badges_row()],
        className="text-muted",
    )


def threat_legend_block():
    """A stacked legend: badge + meaning per level (help modals, cards)."""
    rows = []
    for entry in threat_legend():
        rows.append(html.Div(
            [
                threat_badge(entry["level"], className="me-2"),
                html.Span(entry["meaning"], className="small"),
            ],
            className="mb-2 d-flex align-items-start",
        ))
    return html.Div(rows)
