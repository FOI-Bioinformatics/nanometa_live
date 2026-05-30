"""
Unit tests for app/tabs/qc_tab_helpers.py (extracted from qc_tab.py).

Pure component/figure builders and the amplicon-mode heuristic. The Stage Strip
builder encodes the read-funnel display + classification-rate colour bands
(relaxed in amplicon mode), so tests assert the rendered text/structure.
"""

import plotly.graph_objects as go
import pytest
from dash import html

from nanometa_live.app.tabs.qc_tab_helpers import (
    _build_stage_strip,
    _build_stage_strip_empty,
    _build_stage_strip_slot,
    _get_empty_qc_figures,
    _is_amplicon_mode,
)

pytestmark = pytest.mark.unit


class TestIsAmpliconMode:
    def test_short_min_length_enables(self):
        assert _is_amplicon_mode({"chopper_minlength": 300}) is True
        assert _is_amplicon_mode({"filtlong_min_length": "200"}) is True

    def test_long_default_disables(self):
        assert _is_amplicon_mode({"chopper_minlength": 1000}) is False

    def test_missing_or_garbage_is_conservative(self):
        assert _is_amplicon_mode({}) is False
        assert _is_amplicon_mode(None) is False
        assert _is_amplicon_mode({"chopper_minlength": ""}) is False
        assert _is_amplicon_mode({"chopper_minlength": "abc"}) is False


class TestStageStripSlot:
    def test_slot_structure(self):
        slot = _build_stage_strip_slot("RAW READS", "1,000", "(FASTP)")
        assert isinstance(slot, html.Div)
        text = str(slot.children)
        assert "RAW READS" in text and "1,000" in text and "(FASTP)" in text

    def test_unavailable_count_marks_class(self):
        slot = _build_stage_strip_slot("RAW READS", "—", "(Chopper)")
        # The em-dash count gets the --unavailable modifier class.
        count_div = slot.children[1]
        assert "stage-strip-count--unavailable" in count_div.className


class TestBuildStageStrip:
    def test_chopper_mode_marks_raw_unavailable(self):
        strip = _build_stage_strip(
            raw_reads=None, filtered_reads=900, classified_reads=800,
            unclassified_reads=100, is_chopper=True, filter_tool="Chopper",
            timestamp_str="12:00:00",
        )
        text = str(strip.children)
        assert "Not available (Chopper pipeline)" in text

    def test_removed_percentage_computed(self):
        strip = _build_stage_strip(
            raw_reads=1000, filtered_reads=900, classified_reads=800,
            unclassified_reads=100, is_chopper=False, filter_tool="FASTP",
            timestamp_str="12:00:00",
        )
        assert "10.0% removed" in str(strip.children)

    def test_classification_rate_green_band(self):
        # 900/1000 = 90% >= long-read green floor (80).
        strip = _build_stage_strip(
            raw_reads=None, filtered_reads=1000, classified_reads=900,
            unclassified_reads=100, is_chopper=True, filter_tool="Chopper",
            timestamp_str="12:00:00",
        )
        assert "stage-strip-delta--green" in str(strip.children)
        assert "90.0%" in str(strip.children)

    def test_amplicon_mode_relaxes_band(self):
        # 60% would be amber under long-read bands but green under amplicon (>=50).
        strip = _build_stage_strip(
            raw_reads=None, filtered_reads=1000, classified_reads=600,
            unclassified_reads=400, is_chopper=True, filter_tool="Chopper",
            timestamp_str="12:00:00", amplicon_mode=True,
        )
        assert "stage-strip-delta--green" in str(strip.children)


class TestPlaceholders:
    def test_empty_strip(self):
        strip = _build_stage_strip_empty()
        assert "Waiting for data" in str(strip.children)

    def test_empty_figures(self):
        figs = _get_empty_qc_figures()
        assert len(figs) == 4
        assert all(isinstance(f, go.Figure) for f in figs)
