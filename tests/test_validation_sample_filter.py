"""Tests for the Validation tab's sample-selector filtering and the
scope/criteria banner.

Operator complaint (2026-05-01): the Validation tab shows the same
statistics regardless of which sample is selected, and operators
cannot tell why species visible on the Dashboard / Organism tab are
missing from the Validation tab. These tests pin the pure helpers
that drive the new behaviour:

* ``_filter_results_by_sample`` filters its input list by the
  selected sample, with ``All Samples`` and empty values acting
  as no-op.
* ``_format_scope_text`` produces operator-friendly text that
  reflects the live sample selection.
* ``_format_criteria_text`` states the fixed thresholds applied by
  ``ValidationResult.determine_status`` (80% confirmed hit rate, 90%
  identity, 50% partial) and the config-driven minimap2 MAPQ floor.
"""

from __future__ import annotations

import pytest

from nanometa_live.app.tabs.validation_tab import (
    _filter_results_by_sample,
    _format_criteria_text,
    _format_scope_text,
)


# ---------------------------------------------------------------------------
# _filter_results_by_sample
# ---------------------------------------------------------------------------


def _result(sample_id, taxid=562):
    return {"sample_id": sample_id, "taxid": taxid, "species": "X"}


class TestFilterResultsBySample:
    def test_all_samples_returns_unfiltered(self):
        results = [_result("s1"), _result("s2"), _result("s3")]
        assert _filter_results_by_sample(results, "All Samples") == results

    def test_empty_string_returns_unfiltered(self):
        results = [_result("s1"), _result("s2")]
        assert _filter_results_by_sample(results, "") == results

    def test_none_returns_unfiltered(self):
        results = [_result("s1")]
        assert _filter_results_by_sample(results, None) == results

    def test_specific_sample_filters_to_match(self):
        results = [_result("s1"), _result("s2"), _result("s3")]
        out = _filter_results_by_sample(results, "s2")
        assert len(out) == 1
        assert out[0]["sample_id"] == "s2"

    def test_unknown_sample_returns_empty(self):
        # Selected sample does not match any result -> empty list, not
        # the full set. This is what makes the operator's bug surface
        # when validation has not run for a given barcode.
        results = [_result("barcode01")]
        assert _filter_results_by_sample(results, "barcodeXX") == []

    def test_empty_input_returns_empty(self):
        assert _filter_results_by_sample([], "barcode01") == []
        assert _filter_results_by_sample([], None) == []

    def test_returns_a_list_copy(self):
        # Callers expect a fresh list so they can mutate without affecting
        # the original validation-data-store payload.
        results = [_result("s1")]
        out = _filter_results_by_sample(results, "All Samples")
        assert out == results
        out.append(_result("s2"))
        assert len(results) == 1


# ---------------------------------------------------------------------------
# _format_scope_text
# ---------------------------------------------------------------------------


class TestFormatScopeText:
    def test_specific_sample_shown_verbatim(self):
        assert "barcode05" in _format_scope_text("barcode05")

    def test_all_samples_emits_explainer(self):
        msg = _format_scope_text("All Samples")
        assert "all samples" in msg.lower()
        assert "sample selector" in msg.lower()

    def test_empty_emits_all_samples_message(self):
        for empty in (None, "", 0, False):
            msg = _format_scope_text(empty)
            assert "all samples" in msg.lower()


# ---------------------------------------------------------------------------
# _format_criteria_text
# ---------------------------------------------------------------------------


class TestFormatCriteriaText:
    def test_fixed_thresholds_when_config_empty(self):
        text = _format_criteria_text({})
        assert "80%" in text  # confirmed hit-rate floor (hardcoded)
        assert "90%" in text  # identity floor (hardcoded)
        assert "50%" in text  # partial hit-rate floor (hardcoded)
        assert "10" in text   # mapq default
        assert "Confirmed" in text
        assert "Partial" in text

    def test_hit_rate_and_identity_not_config_driven(self):
        # determine_status hardcodes these, so config must NOT change them.
        text = _format_criteria_text({
            "validation_identity_threshold": 85,
            "validation_hit_rate_threshold": 0.3,
            "minimap2_min_mapq": 5,
        })
        assert "80%" in text
        assert "90%" in text
        assert "50%" in text
        assert "5" in text    # mapq IS config-driven
        assert "85%" not in text
        assert "30%" not in text

    def test_mapq_handles_string_numerics(self):
        # Saved config sometimes round-trips numbers as strings.
        text = _format_criteria_text({"minimap2_min_mapq": "20"})
        assert "20" in text
        assert "80%" in text
        assert "90%" in text
        assert "50%" in text

    def test_mapq_handles_bad_values_with_default(self):
        text = _format_criteria_text({"minimap2_min_mapq": "x"})
        # Falls back to the documented MAPQ default rather than raising.
        assert "10" in text
        assert "80%" in text
        assert "90%" in text
        assert "50%" in text

    def test_none_config(self):
        text = _format_criteria_text(None)
        assert "80%" in text
        assert "90%" in text
        assert "Confirmed" in text
