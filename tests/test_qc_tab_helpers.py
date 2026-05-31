"""
Unit tests for app/tabs/qc_tab_helpers.py (extracted from qc_tab.py).

Pure component/figure builders and the amplicon-mode heuristic. The Stage Strip
builder encodes the read-funnel display + classification-rate colour bands
(relaxed in amplicon mode), so tests assert the rendered text/structure.
"""

import plotly.graph_objects as go
import pytest
from dash import html

from datetime import datetime

import plotly.graph_objects as go

from nanometa_live.app.tabs.qc_tab_helpers import (
    _build_stage_strip,
    _build_stage_strip_empty,
    _build_stage_strip_slot,
    _get_empty_qc_figures,
    _is_amplicon_mode,
    build_qc_figures,
    compute_qc_stat_lines,
)

pytestmark = pytest.mark.unit


class TestBuildQcFigures:
    def test_empty_returns_four_empty_state_figures(self):
        figs = build_qc_figures([])
        assert len(figs) == 4
        assert all(isinstance(f, go.Figure) for f in figs)
        # Each carries the empty-state annotation.
        assert all(f.layout.annotations for f in figs)

    def test_builds_four_figures_from_samples(self):
        sample_data = [
            {"Sample": "bc01", "Time": datetime(2026, 5, 31, 10, 0, 0),
             "Reads": 1000, "Bp": 1_500_000},
            {"Sample": "bc02", "Time": datetime(2026, 5, 31, 10, 5, 0),
             "Reads": 2000, "Bp": 3_000_000},
        ]
        figs = build_qc_figures(sample_data)
        assert len(figs) == 4
        cumul_reads, cumul_bp, reads_bar, bp_bar = figs
        assert all(isinstance(f, go.Figure) for f in figs)
        # Cumulative reads line ends at the running total (1000 + 2000).
        assert cumul_reads.data[0].y[-1] == 3000
        # Per-sample bar carries both samples.
        assert set(reads_bar.data[0].x) == {"bc01", "bc02"}

    def test_sorted_by_time(self):
        # Out-of-order input: cumulative should still be monotonic by Time.
        sample_data = [
            {"Sample": "late", "Time": datetime(2026, 5, 31, 11, 0, 0), "Reads": 500, "Bp": 1},
            {"Sample": "early", "Time": datetime(2026, 5, 31, 9, 0, 0), "Reads": 100, "Bp": 1},
        ]
        cumul_reads = build_qc_figures(sample_data)[0]
        # First cumulative point is the earliest sample's reads (100), not 500.
        assert cumul_reads.data[0].y[0] == 100
        assert cumul_reads.data[0].y[-1] == 600


class TestComputeQcStatLines:
    def _counts(self, **over):
        base = dict(
            tot_reads_pre_filt=1000, tot_passed_reads=900, tot_removed_reads=100,
            tot_low_quality_reads=60, tot_too_short_reads=30, tot_too_many_N_reads=10,
            classified_reads=800, unclassified_reads=100, processed_files=5,
            waiting_files=2, chopper_estimated=False,
        )
        base.update(over)
        return base

    def test_returns_ten_lines(self):
        lines = compute_qc_stat_lines(**self._counts())
        assert len(lines) == 10

    def test_percentages_and_separators(self):
        lines = compute_qc_stat_lines(**self._counts())
        assert "1,000" in lines[0]                 # raw reads, thousands sep
        assert "900 (90.0%)" in lines[1]           # passed = 900/1000
        assert "100 (10.0%)" in lines[2]           # removed = 100/1000
        assert "60 (60.0%)" in lines[3]            # low quality = 60/100 removed
        assert "Classified reads: 800 (88.9%)" in lines[6]  # 800/900
        assert lines[8] == "Files processed: 5"
        assert lines[9] == "Files awaiting processing: 2"

    def test_chopper_estimated_marks_categories(self):
        lines = compute_qc_stat_lines(**self._counts(chopper_estimated=True))
        assert "(est.)" in lines[3]

    def test_zero_prefilter_shows_unavailable(self):
        lines = compute_qc_stat_lines(**self._counts(tot_reads_pre_filt=0))
        assert "not available for Chopper pipeline" in lines[0]

    def test_seqkit_overcount_adjusts_baseline(self):
        # passed > pre_filt -> baseline bumped, removed zeroed, passed shows 100%.
        lines = compute_qc_stat_lines(**self._counts(
            tot_reads_pre_filt=500, tot_passed_reads=900, tot_removed_reads=100,
        ))
        assert "900 (100.0%)" in lines[1]
        assert "0 (0.0%)" in lines[2]


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
