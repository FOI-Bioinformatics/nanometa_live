"""
Unit tests for app/utils/plotly_theme.py.

Covers the colour-lookup helpers (threat/status -> hex, with unknown-value
fallbacks), template registration with Plotly, and applying a template to a
figure. These run without a browser; only Plotly's in-process template registry
is touched.
"""

import plotly.graph_objects as go
import plotly.io as pio

from nanometa_live.app.utils.plotly_theme import (
    COLORS,
    apply_theme_to_figure,
    get_status_color,
    get_threat_color,
    register_templates,
)


class TestThreatColor:
    def test_known_levels(self):
        assert get_threat_color("critical") == COLORS["threat_critical"]
        assert get_threat_color("low") == COLORS["threat_low"]

    def test_case_insensitive(self):
        assert get_threat_color("CRITICAL") == COLORS["threat_critical"]

    def test_unknown_falls_back(self):
        assert get_threat_color("nonsense") == COLORS["threat_unknown"]


class TestStatusColor:
    def test_aliases_map_to_same_colour(self):
        assert get_status_color("success") == get_status_color("good")
        assert get_status_color("danger") == get_status_color("error")

    def test_unknown_falls_back_to_secondary(self):
        assert get_status_color("mystery") == COLORS["secondary"]


class TestTemplates:
    def test_register_adds_both_templates(self):
        register_templates()
        assert "nanometa" in pio.templates
        assert "nanometa_dark" in pio.templates

    def test_apply_theme_sets_template_on_figure(self):
        fig = go.Figure()
        apply_theme_to_figure(fig, dark_mode=False)
        assert fig.layout.template is not None

    def test_apply_dark_theme(self):
        fig = go.Figure()
        apply_theme_to_figure(fig, dark_mode=True)
        # dark template registered and applied without error
        assert "nanometa_dark" in pio.templates
