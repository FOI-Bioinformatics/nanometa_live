"""Tests for the pathogen alert attribution -- the expandable "+N more"
pill (P0-T01) and the verdict-banner triggering-sample subhead (P0-T02).

Both fixes were flagged as clinical-safety P0s in
``docs/audit-2026-04-28-throughput-ux.md``. The 30-second-scan promise
breaks when an operator cannot see which of 24 barcodes is contaminated.
"""

import json

import dash_bootstrap_components as dbc
from dash import html

from nanometa_live.app.components.pathogen_alert import (
    _build_attribution_popover,
    _render_sample_attribution,
)
from nanometa_live.app.tabs.dashboard_tab import _make_banner_content


def _render_to_json(component) -> str:
    return json.dumps(component.to_plotly_json(), default=str)


def _find_first(node, predicate):
    """DFS through a Dash component tree returning the first matching node."""
    if predicate(node):
        return node
    children = getattr(node, "children", None)
    if children is None:
        return None
    if not isinstance(children, (list, tuple)):
        children = [children]
    for c in children:
        if hasattr(c, "children") or hasattr(c, "id"):
            found = _find_first(c, predicate)
            if found is not None:
                return found
    return None


# -- P0-T01: alert pill is expandable --------------------------------------


class TestAttributionPillExpandable:
    """The "+N more" chip pill must be a clickable affordance with a
    Popover listing every triggering sample."""

    def _build_samples(self, count: int):
        return [
            {
                "sample": f"barcode{i:02d}",
                "reads": 5000 - i * 100,
                "abundance": round(5.0 - i * 0.1, 2),
                "is_negative_control": False,
            }
            for i in range(1, count + 1)
        ]

    def test_overflow_renders_popover_with_every_sample(self):
        """An 18-sample pile must produce a Popover whose body lists 18 rows."""
        result = _render_sample_attribution(self._build_samples(18), "critical")
        popover = _find_first(result, lambda n: isinstance(n, dbc.Popover))
        assert popover is not None, "Popover missing from attribution row"
        # PopoverBody is the second child of the Popover
        body = popover.children[1]
        assert len(body.children) == 18, (
            f"Popover body should list 18 sample rows, got {len(body.children)}"
        )

    def test_overflow_pill_targets_popover(self):
        """The pill's id must match the Popover.target so click-to-open works."""
        result = _render_sample_attribution(self._build_samples(18), "critical")
        popover = _find_first(result, lambda n: isinstance(n, dbc.Popover))
        # The pill is the html.Span carrying the matching id
        pill = _find_first(
            result,
            lambda n: isinstance(n, html.Span) and getattr(n, "id", None) == popover.target,
        )
        assert pill is not None, "No pill carrying the Popover target id"
        # Pill must look interactive
        style = pill.style or {}
        assert style.get("cursor") == "pointer", "Pill must be styled as clickable"

    def test_no_overflow_no_popover(self):
        """3 or fewer samples render inline -- no overflow pill, no popover."""
        result = _render_sample_attribution(self._build_samples(3), "critical")
        popover = _find_first(result, lambda n: isinstance(n, dbc.Popover))
        assert popover is None

    def test_negative_control_visually_distinct_in_popover(self):
        """NC samples carry an "(NC)" suffix in the popover body too."""
        samples = self._build_samples(5)
        samples.append({
            "sample": "NC_blank",
            "reads": 12,
            "abundance": 0.05,
            "is_negative_control": True,
        })
        popover = _build_attribution_popover(samples, "test-id", "critical")
        rendered = _render_to_json(popover)
        assert "NC_blank (NC)" in rendered


# -- P0-T02: verdict banner names triggering samples -----------------------


class TestVerdictBannerAttribution:
    """When ACTION REQUIRED fires, the verdict banner subhead must name
    the triggering samples so the operator can see "barcode13" without
    having to scroll into the alert cards."""

    def test_attribution_renders_with_top_3_inline(self):
        banner = _make_banner_content(
            "exclamation-octagon-fill", "#8b0000",
            "ACTION REQUIRED", "5 of 42 monitored pathogens found",
            "ACTIVE", "01:23:45",
            sub_color="#721c24",
            triggering_samples=[f"barcode{i:02d}" for i in range(1, 19)],
            total_sample_count=24,
        )
        rendered = _render_to_json(banner)
        assert "Triggered by" in rendered
        assert "barcode01" in rendered
        assert "barcode02" in rendered
        assert "barcode03" in rendered
        # 4th name must NOT be inline (only top-3 + overflow pill)
        assert "barcode04" not in rendered
        # Overflow phrase tells the operator the total
        assert "15 more" in rendered
        assert "of 24 samples" in rendered

    def test_no_attribution_when_triggering_list_empty(self):
        """No subhead when triggering_samples is None or empty."""
        banner_none = _make_banner_content(
            "shield-check", "#28a745",
            "ALL CLEAR", "0 of 42 monitored pathogens found",
            "ACTIVE", "00:30:00",
            sub_color="#155724",
        )
        rendered = _render_to_json(banner_none)
        assert "Triggered by" not in rendered

    def test_three_or_fewer_samples_no_overflow_pill(self):
        """When only 2 samples trigger, the subhead names both with no pill."""
        banner = _make_banner_content(
            "exclamation-octagon-fill", "#8b0000",
            "ACTION REQUIRED", "1 of 42 monitored pathogens found",
            "ACTIVE", "00:45:00",
            sub_color="#721c24",
            triggering_samples=["barcode13", "barcode17"],
            total_sample_count=24,
        )
        rendered = _render_to_json(banner)
        assert "Triggered by" in rendered
        assert "barcode13" in rendered
        assert "barcode17" in rendered
        # No "+N more" phrasing when nothing was elided
        assert "more" not in rendered or "more)" not in rendered.split("Triggered by")[1].split("samples)")[0]
