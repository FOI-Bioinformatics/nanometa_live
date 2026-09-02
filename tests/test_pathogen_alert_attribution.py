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
from nanometa_live.app.tabs.dashboard_helpers import _make_banner_content


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

    def test_watched_tier_multi_sample_names_one_and_summarises_the_rest(self):
        """A moderate hit across several barcodes names its top sample.

        It rendered no attribution at all originally, then a bare count pill,
        which said a detection spanned barcodes without saying which. It now
        names the highest-count sample and keeps the popover for the full
        list -- one chip per card, not one per barcode.
        """
        samples = self._build_samples(4)
        result = _render_sample_attribution(samples, "watched")
        assert result is not None, "watched multi-sample attribution suppressed"
        rendered = _render_to_json(result)
        popover = _find_first(result, lambda n: isinstance(n, dbc.Popover))
        assert popover is not None
        assert len(popover.children[1].children) == 4
        inline = rendered.split("Popover")[0]
        # Exactly one barcode chip inline, plus the overflow pill.
        assert "barcode01" in inline
        assert "barcode02" not in inline
        assert "+3 more" in inline

    def test_watched_tier_single_sample_still_names_it(self):
        result = _render_sample_attribution(self._build_samples(1), "watched")
        rendered = _render_to_json(result)
        assert "barcode01" in rendered
        assert _find_first(result, lambda n: isinstance(n, dbc.Popover)) is None

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


class TestModerateTierNamesItsTopSample:
    """A count pill alone hides the one fact the operator needs.

    Chips per sample are suppressed at watched tier for a real reason: at 96
    barcodes and 129 entries the eager version serialised tens of thousands of
    components (round-2 scale audit). Naming the highest-count sample costs one
    chip per card and keeps the popover for the rest.

    Observed live on 2026-09-01: moderate cards read "DETECTED IN: 3 samples"
    and "4 samples", naming none, on the same screen where the critical cards
    named their barcodes.
    """

    def test_the_top_sample_is_named_inline(self):
        from nanometa_live.app.components.attribution import (
            _render_sample_attribution,
        )

        samples = [
            {"sample": "barcode06", "reads": 900, "abundance": 12.0,
             "is_negative_control": False},
            {"sample": "barcode07", "reads": 40, "abundance": 1.0,
             "is_negative_control": False},
            {"sample": "barcode05", "reads": 20, "abundance": 0.5,
             "is_negative_control": False},
        ]

        rendered = str(
            _render_sample_attribution(samples, "watched", attribution_taxid=263)
        )

        assert "barcode06" in rendered
        assert "2 more" in rendered

    def test_a_single_sample_is_unchanged(self):
        from nanometa_live.app.components.attribution import (
            _render_sample_attribution,
        )

        samples = [{"sample": "barcode05", "reads": 900, "abundance": 12.0,
                    "is_negative_control": False}]

        assert "barcode05" in str(
            _render_sample_attribution(samples, "watched", attribution_taxid=263)
        )

    def test_critical_tier_is_unchanged(self):
        """Three chips plus overflow, as before."""
        from nanometa_live.app.components.attribution import (
            _render_sample_attribution,
        )

        samples = [
            {"sample": f"barcode0{i}", "reads": 100 - i, "abundance": 1.0,
             "is_negative_control": False}
            for i in range(5)
        ]

        rendered = str(
            _render_sample_attribution(samples, "critical", attribution_taxid=263)
        )

        for name in ("barcode00", "barcode01", "barcode02"):
            assert name in rendered
        assert "2 more" in rendered
