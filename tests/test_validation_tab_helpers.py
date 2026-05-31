"""
Unit tests for app/tabs/validation_tab_helpers.py (extracted from validation_tab).

Pure filter/format/summary functions over validation result lists, the grouped
coverage-selector option builder, the card-list paginator, and the empty
identity plot. All deterministic, no Dash app.
"""

import plotly.graph_objects as go
import pytest
from dash import html

from nanometa_live.app.tabs.validation_tab_helpers import (
    _CARD_LIST_INITIAL_LIMIT,
    _build_coverage_selector_options,
    _build_paginated_card_list,
    _compute_summary,
    _create_empty_identity_plot,
    _filter_by_method,
    _filter_results_by_sample,
    _format_criteria_text,
    _format_scope_text,
    _load_real_coverage,
)
from nanometa_live.core.parsers.paf_coverage_parser import CoverageData

pytestmark = pytest.mark.unit


# PAF columns: qname qlen qstart qend strand tname tlen tstart tend matches alnlen mapq
_PAF_LINE = "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60\n"


class TestLoadRealCoverage:
    def test_none_config(self):
        assert _load_real_coverage("bc01_562", None, 0) is None

    def test_no_results_dir(self):
        assert _load_real_coverage("bc01_562", {"analysis_name": "x"}, 0) is None

    def test_bad_key_without_taxid(self):
        # "noseparator" has no '_' -> rsplit yields a single part -> None.
        assert _load_real_coverage("noseparator", {"main_dir": "/tmp"}, 0) is None

    def test_loads_from_minimap2_paf(self, tmp_path):
        paf = tmp_path / "validation" / "minimap2"
        paf.mkdir(parents=True)
        (paf / "bc01_taxid562.paf").write_text(_PAF_LINE)
        cov = _load_real_coverage("bc01_562", {"results_output_directory": str(tmp_path)}, 0)
        assert isinstance(cov, CoverageData)

    def test_loads_from_on_demand_paf(self, tmp_path):
        d = tmp_path / "on_demand_validation"
        d.mkdir(parents=True)
        (d / "bc01_562_ondemand.paf").write_text(_PAF_LINE)
        cov = _load_real_coverage("bc01_562", {"main_dir": str(tmp_path)}, 0)
        assert isinstance(cov, CoverageData)

    def test_missing_paf_returns_none(self, tmp_path):
        assert _load_real_coverage("bc01_562", {"main_dir": str(tmp_path)}, 0) is None

    def test_all_filtered_by_mapq_returns_none(self, tmp_path):
        paf = tmp_path / "validation" / "minimap2"
        paf.mkdir(parents=True)
        (paf / "bc01_taxid562.paf").write_text(_PAF_LINE)  # mapq 60
        # min_mapq above the only alignment's mapq -> no alignments pass -> None.
        assert _load_real_coverage("bc01_562", {"results_output_directory": str(tmp_path)}, 99) is None

RESULTS = [
    {"sample_id": "bc01", "taxid": 562, "species": "E. coli",
     "validation_method": "blast", "status": "confirmed",
     "validated_reads": 80, "total_reads": 100},
    {"sample_id": "bc01", "taxid": 1280, "species": "S. aureus",
     "validation_method": "minimap2", "status": "partial",
     "validated_reads": 40, "total_reads": 100},
    {"sample_id": "bc02", "taxid": 1392, "species": "B. anthracis",
     "validation_method": "both", "status": "low",
     "validated_reads": 5, "total_reads": 100},
]


class TestFilterByMethod:
    def test_blast_excludes_minimap2(self):
        out = _filter_by_method(RESULTS, "blast")
        methods = {r["validation_method"] for r in out}
        assert "minimap2" not in methods  # blast + both kept

    def test_minimap2_includes_both(self):
        out = _filter_by_method(RESULTS, "minimap2")
        assert {r["validation_method"] for r in out} == {"minimap2", "both"}


class TestFilterBySample:
    def test_all_samples_no_filter(self):
        assert len(_filter_results_by_sample(RESULTS, "All Samples")) == 3
        assert len(_filter_results_by_sample(RESULTS, None)) == 3

    def test_specific_sample(self):
        out = _filter_results_by_sample(RESULTS, "bc02")
        assert [r["taxid"] for r in out] == [1392]


class TestFormatText:
    def test_scope_specific_and_all(self):
        assert "bc01" in _format_scope_text("bc01")
        assert "all samples" in _format_scope_text("All Samples")

    def test_criteria_uses_config_thresholds(self):
        text = _format_criteria_text({
            "validation_identity_threshold": 95,
            "validation_hit_rate_threshold": 0.6,
            "minimap2_min_mapq": 20,
        })
        assert "95%" in text and "60%" in text and "20" in text

    def test_criteria_defaults_on_garbage(self):
        text = _format_criteria_text({"validation_identity_threshold": "x"})
        assert "90%" in text


class TestComputeSummary:
    def test_buckets_and_read_totals(self):
        s = _compute_summary(RESULTS)
        assert s["confirmed"] == 1
        assert s["partial"] == 1
        assert s["low_confidence"] == 1  # 'low' maps to low_confidence
        assert s["reads_validated"] == 125  # 80 + 40 + 5
        assert s["reads_total"] == 300

    def test_empty(self):
        s = _compute_summary([])
        assert s["confirmed"] == 0 and s["reads_total"] == 0


class TestCoverageSelectorOptions:
    def test_empty_data(self):
        assert _build_coverage_selector_options(None, None) == ([], None)

    def test_groups_minimap2_by_sample_with_headers(self):
        options, default = _build_coverage_selector_options({"results": RESULTS}, None)
        headers = [o for o in options if o.get("disabled")]
        # bc01 (minimap2) and bc02 (both) each get a disabled header row.
        assert {h["value"] for h in headers} == {"__header__:bc01", "__header__:bc02"}
        # default is the first non-header value.
        assert default and not default.startswith("__header__")

    def test_preserves_valid_current_value(self):
        options, default = _build_coverage_selector_options(
            {"results": RESULTS}, "bc02_1392"
        )
        assert default == "bc02_1392"


class TestPaginatedCardList:
    def test_empty(self):
        div = _build_paginated_card_list([], False, "btn")
        assert isinstance(div, html.Div)
        assert div.children == []

    def test_truncates_with_button(self):
        cards = [html.Div(f"c{i}") for i in range(_CARD_LIST_INITIAL_LIMIT + 5)]
        div = _build_paginated_card_list(cards, show_all=False, show_all_button_id="btn")
        text = str(div.children)
        assert f"of {_CARD_LIST_INITIAL_LIMIT + 5}" in text
        assert "Show all" in text

    def test_show_all_renders_everything(self):
        cards = [html.Div(f"c{i}") for i in range(_CARD_LIST_INITIAL_LIMIT + 5)]
        div = _build_paginated_card_list(cards, show_all=True, show_all_button_id="btn")
        # All cards present (plus a count footer); no "Show all" button.
        assert "Show all" not in str(div.children)


class TestEmptyIdentityPlot:
    def test_returns_figure(self):
        fig = _create_empty_identity_plot()
        assert isinstance(fig, go.Figure)
        assert "No identity data" in str(fig.layout.annotations[0].text)
