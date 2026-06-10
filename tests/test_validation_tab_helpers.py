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
    sort_results_validated_first,
    status_rank,
    build_species_by_taxid,
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

    def test_criteria_states_true_hardcoded_thresholds(self):
        # Hit-rate (80% confirmed / 50% partial) and identity (90%) are
        # hardcoded in ValidationResult.determine_status, NOT config-driven.
        text = _format_criteria_text({
            "validation_identity_threshold": 95,   # ignored
            "validation_hit_rate_threshold": 0.6,  # ignored
            "minimap2_min_mapq": 20,
        })
        assert "80%" in text   # Confirmed hit-rate floor
        assert "90%" in text   # Confirmed identity floor
        assert "50%" in text   # Partial hit-rate floor
        assert "20" in text    # mapq IS config-driven
        # The ignored config values must not appear.
        assert "95%" not in text
        assert "60%" not in text

    def test_criteria_mapq_config_driven(self):
        text = _format_criteria_text({"minimap2_min_mapq": "20"})
        assert "20" in text

    def test_criteria_mapq_defaults_on_garbage(self):
        text = _format_criteria_text({"minimap2_min_mapq": "x"})
        assert "10" in text  # mapq default
        assert "80%" in text
        assert "90%" in text
        assert "50%" in text


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


class TestSortValidatedFirst:
    """Confirmed/validated results must float to the top (operator feedback #3)."""

    def _results(self):
        # Deliberately not in status order; lower percent_validated on the
        # confirmed one to prove status beats the numeric secondary key.
        return [
            {"species": "A", "status": "no_data", "percent_validated": 95},
            {"species": "B", "status": "confirmed", "percent_validated": 10},
            {"species": "C", "status": "partial", "percent_validated": 60},
            {"species": "D", "status": "failed", "percent_validated": 99},
        ]

    def test_confirmed_first_regardless_of_secondary_key(self):
        out = sort_results_validated_first(self._results(), "percent_validated")
        assert [r["status"] for r in out] == ["confirmed", "partial", "no_data", "failed"]

    def test_within_status_numeric_descending(self):
        results = [
            {"species": "lo", "status": "confirmed", "percent_validated": 30},
            {"species": "hi", "status": "confirmed", "percent_validated": 90},
        ]
        out = sort_results_validated_first(results, "percent_validated")
        assert [r["species"] for r in out] == ["hi", "lo"]

    def test_species_sort_key_ascending_within_status(self):
        results = [
            {"species": "Zeta", "status": "confirmed"},
            {"species": "Alpha", "status": "confirmed"},
        ]
        out = sort_results_validated_first(results, "species")
        assert [r["species"] for r in out] == ["Alpha", "Zeta"]

    def test_does_not_mutate_input_and_handles_empty(self):
        results = self._results()
        snapshot = list(results)
        sort_results_validated_first(results, "percent_validated")
        assert results == snapshot
        assert sort_results_validated_first([], "percent_validated") == []

    def test_status_rank_unknown_sorts_with_no_data(self):
        assert status_rank("confirmed") < status_rank("partial")
        assert status_rank("garbage") == status_rank("no_data")


class TestSpeciesByTaxid:
    class _Entry:
        def __init__(self, taxid, name, db_taxid=None):
            self.taxid = taxid
            self.name = name
            self.db_taxid = db_taxid

    def test_maps_both_taxid_forms_int_and_str(self):
        entries = {263: self._Entry(263, "Francisella tularensis", db_taxid=119857)}
        name_map = build_species_by_taxid(entries)
        assert name_map[263] == "Francisella tularensis"
        assert name_map["263"] == "Francisella tularensis"
        assert name_map[119857] == "Francisella tularensis"

    def test_skips_entries_without_name(self):
        entries = [self._Entry(1, ""), self._Entry(2, None)]
        assert build_species_by_taxid(entries) == {}


class TestCoverageSelectorLabels:
    """Dropdown labels must always carry a species name (operator feedback #5)."""

    def _data(self):
        return {"results": [
            {"sample_id": "bc01", "taxid": 263, "species": "",
             "validation_method": "minimap2", "status": "confirmed"},
            {"sample_id": "bc01", "taxid": 1773, "species": "M. tuberculosis",
             "validation_method": "both", "status": "no_data"},
        ]}

    def test_resolves_name_from_watchlist_when_result_lacks_species(self):
        opts, _ = _build_coverage_selector_options(
            self._data(), None, species_by_taxid={263: "Francisella tularensis"}
        )
        labels = [o["label"] for o in opts if not o.get("disabled")]
        assert any("Francisella tularensis (taxid 263)" == lbl for lbl in labels)
        assert not any("Unknown" in lbl for lbl in labels)

    def test_bare_taxid_fallback_when_unresolvable(self):
        opts, _ = _build_coverage_selector_options(self._data(), None)
        labels = [o["label"] for o in opts if not o.get("disabled")]
        assert "taxid 263" in labels  # no name anywhere -> bare taxid, not "Unknown"

    def test_matched_species_sorted_first_within_sample(self):
        opts, _ = _build_coverage_selector_options(
            self._data(), None, species_by_taxid={263: "Francisella tularensis"}
        )
        # Skip the disabled sample header; the confirmed entry (263) comes first.
        entries = [o for o in opts if not o.get("disabled")]
        assert entries[0]["value"] == "bc01_263"
