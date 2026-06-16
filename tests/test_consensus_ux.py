"""Unit tests for the Consensus sub-tab pure helpers."""

import pytest

from nanometa_live.app.tabs.consensus_helpers import (
    build_consensus_selector_options,
    find_consensus_result,
    consensus_stats_badges,
)

pytestmark = pytest.mark.unit


def _result(sample="barcode05", taxid=263, span=428, species="F. tularensis"):
    return {
        "sample_id": sample, "taxid": taxid, "species": species,
        "span": span, "consensus_length": span, "n_count": 4,
        "mean_depth": 52.0, "covered_start": 435, "covered_end": 863,
        "mapped_reads": 396, "ref_name": "chr", "has_sequence": span > 0,
    }


def test_selector_groups_and_keys():
    opts, value = build_consensus_selector_options(
        [_result(), _result("barcode06", 562, species="E. coli")], None, {}
    )
    # two header rows + two species rows
    headers = [o for o in opts if o.get("disabled")]
    assert len(headers) == 2
    assert value == "barcode05_263"


def test_selector_preserves_valid_selection():
    results = [_result(), _result("barcode06", 562)]
    _, value = build_consensus_selector_options(results, "barcode06_562", {})
    assert value == "barcode06_562"


def test_selector_marks_no_consensus():
    opts, _ = build_consensus_selector_options([_result(span=0)], None, {})
    species_rows = [o for o in opts if not o.get("disabled")]
    assert "no consensus" in species_rows[0]["label"]


def test_selector_empty():
    assert build_consensus_selector_options([], None, {}) == ([], None)


def test_find_consensus_result():
    results = [_result(), _result("barcode06", 562)]
    found = find_consensus_result(results, "barcode06_562")
    assert found and found["taxid"] == 562
    assert find_consensus_result(results, "nope_1") is None


def test_stats_badges_render_span():
    rendered = str(consensus_stats_badges(_result()))
    assert "428 bp" in rendered
    assert "435-863" in rendered


def test_stats_badges_no_consensus_warns():
    rendered = str(consensus_stats_badges(_result(span=0)))
    assert "No consensus" in rendered


def test_stats_badges_empty_selection():
    assert consensus_stats_badges(None) == ""
