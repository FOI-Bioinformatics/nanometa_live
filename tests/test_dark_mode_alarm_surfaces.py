"""Alarm surfaces must stay readable in dark mode.

The verdict banner and the pathogen alert cards keep their light pink,
amber and blue backgrounds in dark mode (the colour is the verdict), but
their text inherited the dark theme's light ink: "ACTION REQUIRED" was
near-white on pale pink and the organism names on the alert cards were
almost invisible (live test 2026-11-24, s11_dark.png). The light surfaces
re-scope the ink variables to dark values, and the banner carries the class
that opts it in.
"""

import re
from pathlib import Path

import pytest

import nanometa_live

pytestmark = pytest.mark.unit

CSS = (Path(nanometa_live.__file__).parent / "app" / "assets" / "styles.css").read_text()

LIGHT_SURFACES = [
    ".on-light-surface",
    ".pathogen-alert-critical",
    ".pathogen-alert-high",
    ".pathogen-alert-moderate",
    ".pathogen-alert-watch",
]


def _dark_rule_for(selector):
    pattern = r'\[data-theme="dark"\]\s*' + re.escape(selector) + r'[^{]*\{([^}]*)\}'
    return [m.group(1) for m in re.finditer(pattern, CSS)]


@pytest.mark.parametrize("selector", LIGHT_SURFACES)
def test_light_surface_keeps_dark_ink_in_dark_mode(selector):
    bodies = " ".join(_dark_rule_for(selector))
    assert "--dark: #1F2937" in bodies, selector
    assert "color: #1F2937" in bodies, selector


def test_muted_text_on_light_surfaces_is_dark_grey():
    assert re.search(r'\[data-theme="dark"\]\s*\.on-light-surface \.text-muted[^{]*\{[^}]*#4B5563',
                     CSS)


def test_verdict_banner_opts_in():
    from nanometa_live.app.layouts.dashboard_layout import create_dashboard_layout
    layout = create_dashboard_layout()

    def walk(node):
        yield node
        children = getattr(node, "children", None)
        for c in (children if isinstance(children, (list, tuple)) else [children] if children is not None else []):
            yield from walk(c)

    banner = next(n for n in walk(layout) if getattr(n, "id", None) == "dashboard-verdict-banner")
    assert "on-light-surface" in banner.className


@pytest.mark.parametrize("factory", ["HighRiskPathogenAlert", "WatchedSpeciesAlert"])
def test_inline_background_cards_opt_in(factory):
    """The HIGH RISK and watched cards paint their light background inline,
    so only the class can tell the dark theme to keep their ink dark."""
    from nanometa_live.app.components import pathogen_alert

    card = getattr(pathogen_alert, factory)("Staphylococcus aureus", read_count=10)

    def classes(node):
        cls = getattr(node, "className", None)
        if cls:
            yield cls
        children = getattr(node, "children", None)
        for c in (children if isinstance(children, (list, tuple)) else [children] if children is not None else []):
            yield from classes(c)

    assert any("on-light-surface" in c for c in classes(card))
