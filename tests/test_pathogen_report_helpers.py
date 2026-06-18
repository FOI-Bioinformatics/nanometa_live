"""Tests for the Pathogen Report modal's pure builders.

These cover the dead-link / wrong-link guards and the derived fields added in
the 2026-06-03 report audit:

- ``build_reference_links`` must never emit a link that resolves to a wrong or
  nonexistent record: NCBI only for real NCBI taxids (or a resolved link),
  GTDB only when a resolved link exists, and the Federal Select Agent Program
  link always (the live successor to CDC's retired bioterrorism page).
- ``compute_detection_confidence`` reflects read support, not a placeholder.
- ``build_detection_meta`` surfaces reported-at, taxonomy-ID validation status,
  and lineage without conflating taxonomy validation with the confirmatory
  Validation tab.
"""

import json

import pytest

from nanometa_live.app.tabs.dashboard_helpers import (
    build_reference_links,
    compute_detection_confidence,
    build_detection_meta,
    SELECT_AGENTS_URL,
)
from nanometa_live.core.utils.genome_manager import _PSEUDO_TAXID_MIN

pytestmark = pytest.mark.unit


def _render(component) -> str:
    return json.dumps(component, default=str)


class TestReferenceLinks:
    def test_select_agents_always_present_and_live_url(self):
        rendered = _render(build_reference_links())
        assert "Select Agents (FSAP)" in rendered
        assert SELECT_AGENTS_URL in rendered
        # The retired CDC NIOSH chemical-agent URL must never reappear.
        assert "niosh/topics/emres/chemagent" not in rendered

    def test_real_ncbi_taxid_gets_ncbi_link(self):
        rendered = _render(build_reference_links(ncbi_taxid=1392))
        assert "NCBI Taxonomy" in rendered
        assert "wwwtax.cgi?id=1392" in rendered

    def test_pseudo_taxid_omits_ncbi_link(self):
        # A name-only / GTDB-custom pseudo-taxid would point at a wrong NCBI
        # taxon -- the link must be omitted rather than mislead the operator.
        pseudo = _PSEUDO_TAXID_MIN + 42
        rendered = _render(build_reference_links(ncbi_taxid=pseudo))
        assert "NCBI Taxonomy" not in rendered
        assert "Select Agents (FSAP)" in rendered

    def test_resolved_ncbi_link_used_verbatim(self):
        rendered = _render(build_reference_links(
            ncbi_taxid=_PSEUDO_TAXID_MIN + 7,  # not real, but link is resolved
            ncbi_link="https://example.org/ncbi/123",
        ))
        assert "https://example.org/ncbi/123" in rendered
        assert "NCBI Taxonomy" in rendered

    def test_gtdb_link_only_when_resolved(self):
        without = _render(build_reference_links(ncbi_taxid=1392))
        assert "GTDB" not in without
        with_link = _render(build_reference_links(
            ncbi_taxid=1392,
            gtdb_link="https://gtdb.ecogenomic.org/species?id=s__Bacillus",
        ))
        assert "GTDB" in with_link
        assert "gtdb.ecogenomic.org" in with_link


class TestConfidence:
    @pytest.mark.parametrize("reads,expected", [
        (1000, "High"),
        (100, "High"),
        (99, "Moderate"),
        (20, "Moderate"),
        (19, "Low"),
        (1, "Low"),
        (0, "N/A"),
        (None, "N/A"),
        ("not-a-number", "N/A"),
    ])
    def test_bands(self, reads, expected):
        assert compute_detection_confidence(reads) == expected


class TestDetectionMeta:
    def test_validated_shows_date_and_badge(self):
        rendered = _render(build_detection_meta(
            detected_at="2026-06-03 17:00",
            taxonomy_validated=True,
            validation_date="2026-05-01T12:00:00",
            lineage=["Bacteria", "Bacillota", "Bacillus anthracis"],
        ))
        assert "Reported" in rendered
        assert "2026-06-03 17:00" in rendered
        assert "Validated" in rendered
        assert "2026-05-01" in rendered  # date trimmed to 10 chars
        assert "Bacteria > Bacillota > Bacillus anthracis" in rendered

    def test_on_watchlist_unvalidated_shows_not_yet(self):
        rendered = _render(build_detection_meta(
            detected_at="2026-06-03 17:00", on_watchlist=True,
        ))
        assert "Not yet validated" in rendered

    def test_gtdb_taxonomy_fallback_when_no_lineage(self):
        rendered = _render(build_detection_meta(
            detected_at="t", gtdb_taxonomy="d__Bacteria;p__Bacillota",
        ))
        assert "GTDB lineage" in rendered
        assert "d__Bacteria;p__Bacillota" in rendered

    def test_off_watchlist_no_validation_row(self):
        rendered = _render(build_detection_meta(
            detected_at="2026-06-03 17:00", on_watchlist=False,
        ))
        assert "Not yet validated" not in rendered
        assert "Reported" in rendered


class TestReportCallback:
    """Wiring-level tests for handle_view_report and the Validation jump.

    The report callback is not reachable via the viz-only smoke test (no
    active watchlist => no "View Report" buttons), so its 16-output wiring and
    its use of the dynamic builders are pinned here instead.
    """

    def _register(self):
        from dash import Dash
        from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_dashboard_callbacks(app)
        return app

    def test_view_report_builds_dynamic_links_and_meta(self):
        from unittest.mock import MagicMock, patch
        from dash_test_utils import get_callback_fn

        app = self._register()
        fn = get_callback_fn(app, "pathogen-modal-references")

        empty_mgr = MagicMock()
        empty_mgr.get_active_entries.return_value = {}

        with patch(
            "nanometa_live.app.tabs.dashboard_tab.ctx",
            MagicMock(triggered_id={"type": "pathogen-view-report", "taxid": 1392}),
        ), patch(
            "nanometa_live.app.tabs.dashboard_tab.get_watchlist_manager",
            return_value=empty_mgr,
        ), patch(
            "nanometa_live.core.utils.pathogen_database.get_pathogen_by_taxid",
            return_value=None,  # exercise the Kraken-only (not-found) path
        ):
            out = fn([1], None, None, False, {}, {}, "All Samples")

        assert len(out) == 17
        assert out[0] is True  # modal opens
        rendered = _render(out)
        # Dynamic references rendered: real NCBI taxid -> NCBI link present,
        # Select Agents always, dead CDC URL never.
        assert "Select Agents (FSAP)" in rendered
        assert "wwwtax.cgi?id=1392" in rendered
        assert "niosh/topics/emres/chemagent" not in rendered

    def test_goto_validation_switches_tab_and_closes(self):
        from dash_test_utils import get_callback_fn

        app = self._register()
        fn = get_callback_fn(
            app, "tabs", input_contains="pathogen-modal-goto-validation"
        )
        assert fn(1) == ("validation-tab", False)
