"""Tests for the shared per-sample attribution helpers.

The bug these guard against is silent: a detection whose NCBI taxid differs
from its Kraken2 report taxid (every GTDB or custom database) resolved to no
samples, and a detection with no samples is rendered exactly like a detection
that legitimately spans none. Every surface now resolves through
``nanometa_live.core.utils.attribution`` so a fix in one place holds in all.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.utils.attribution import (
    build_pathogen_attribution,
    format_attribution_text,
    is_negative_control,
    resolve_attribution_taxids,
    samples_for_detection,
)


def _sample(name, reads):
    return {"sample": name, "reads": reads, "abundance": 1.0,
            "is_negative_control": False}


class TestTaxidResolution:
    def test_detected_taxid_takes_precedence(self):
        detection = {"taxid": 1392, "detected_taxid": 88888}
        assert resolve_attribution_taxids(detection) == [88888, 1392]

    def test_ncbi_taxid_alone(self):
        assert resolve_attribution_taxids({"taxid": 1392}) == [1392]

    def test_identical_taxids_are_deduped(self):
        detection = {"taxid": 1392, "detected_taxid": 1392}
        assert resolve_attribution_taxids(detection) == [1392]

    def test_non_numeric_taxids_are_dropped(self):
        assert resolve_attribution_taxids({"taxid": "not-a-taxid"}) == []
        assert resolve_attribution_taxids({}) == []

    def test_string_taxid_is_coerced(self):
        assert resolve_attribution_taxids({"taxid": "1392"}) == [1392]

    def test_lookup_falls_back_to_ncbi_taxid(self):
        detection = {"taxid": 1392, "detected_taxid": 88888}
        rows = samples_for_detection(detection, {1392: [_sample("bc01", 10)]})
        assert [r["sample"] for r in rows] == ["bc01"]

    def test_lookup_prefers_the_kraken_taxid(self):
        detection = {"taxid": 1392, "detected_taxid": 88888}
        rows = samples_for_detection(
            detection,
            {88888: [_sample("bc07", 10)], 1392: [_sample("bc01", 10)]},
        )
        assert [r["sample"] for r in rows] == ["bc07"]

    def test_unknown_taxid_returns_empty(self):
        assert samples_for_detection({"taxid": 1}, {2: [_sample("bc01", 10)]}) == []


class TestBuildPathogenAttribution:
    def test_threshold_splits_above_and_below(self):
        detections = [{
            "taxid": 1392, "detected_taxid": 88888,
            "name": "Bacillus anthracis", "threshold": 100, "reads": 350,
        }]
        taxid_to_samples = {88888: [_sample("bc04", 300), _sample("bc05", 50)]}
        [attribution] = build_pathogen_attribution(detections, taxid_to_samples)
        assert attribution.samples == ["bc04"]
        assert attribution.below_threshold_samples == ["bc05"]
        assert attribution.resolved

    def test_no_threshold_names_every_sample(self):
        detections = [{"taxid": 1, "name": "X", "reads": 10}]
        [attribution] = build_pathogen_attribution(
            detections, {1: [_sample("bc01", 5), _sample("bc02", 3)]}
        )
        assert attribution.samples == ["bc01", "bc02"]

    def test_unresolved_detection_is_flagged(self):
        [attribution] = build_pathogen_attribution(
            [{"taxid": 1392, "name": "X", "threshold": 5}], {}
        )
        assert not attribution.resolved
        assert attribution.samples == []

    def test_sorted_by_read_support_descending(self):
        detections = [
            {"taxid": 1, "name": "Low", "threshold": 1},
            {"taxid": 2, "name": "High", "threshold": 1},
        ]
        attributions = build_pathogen_attribution(
            detections, {1: [_sample("bc01", 10)], 2: [_sample("bc02", 900)]}
        )
        assert [a.pathogen for a in attributions] == ["High", "Low"]

    def test_annotation_is_carried_into_the_label(self):
        [attribution] = build_pathogen_attribution(
            [{"taxid": 1, "name": "X", "annotation": "select agent"}],
            {1: [_sample("bc01", 10)]},
        )
        assert attribution.pathogen == "X (select agent)"

    def test_duplicate_pathogens_are_collapsed(self):
        detections = [
            {"taxid": 1, "name": "X", "threshold": 1},
            {"taxid": 1, "name": "X", "threshold": 1},
        ]
        assert len(build_pathogen_attribution(
            detections, {1: [_sample("bc01", 10)]}
        )) == 1


class TestFormatAttributionText:
    def test_pairs_each_pathogen_with_its_samples(self):
        attributions = build_pathogen_attribution(
            [
                {"taxid": 1, "name": "Bacillus anthracis", "threshold": 1},
                {"taxid": 2, "name": "Yersinia pestis", "threshold": 1},
            ],
            {1: [_sample("bc01", 900)], 2: [_sample("bc07", 400)]},
        )
        text = format_attribution_text(attributions)
        assert text == (
            "Triggered by: Bacillus anthracis (bc01); Yersinia pestis (bc07)"
        )

    def test_below_threshold_only_reports_the_aggregate(self):
        attributions = build_pathogen_attribution(
            [{"taxid": 1, "name": "X", "threshold": 100}],
            {1: [_sample(f"bc{i:02d}", 50) for i in range(10)]},
        )
        assert format_attribution_text(attributions) == (
            "Triggered by: X (aggregate across 10 samples)"
        )

    def test_samples_beyond_three_are_summarised(self):
        attributions = build_pathogen_attribution(
            [{"taxid": 1, "name": "X", "threshold": 1}],
            {1: [_sample(f"bc{i:02d}", 100) for i in range(6)]},
        )
        text = format_attribution_text(attributions)
        assert "+3 more" in text
        assert "bc05" not in text

    def test_returns_none_when_nothing_resolved(self):
        attributions = build_pathogen_attribution(
            [{"taxid": 1, "name": "X", "threshold": 1}], {}
        )
        assert format_attribution_text(attributions) is None
        assert format_attribution_text([]) is None


class TestNegativeControlDetection:
    @pytest.mark.parametrize("name", [
        "NTC", "ntc_01", "neg_ctrl", "NEG-CTRL", "blank", "NC",
        "negative", "negative_control", "NegativeControl",
        "no_template_control", "run1_blank",
    ])
    def test_recognised_controls(self, name):
        assert is_negative_control(name) is True

    @pytest.mark.parametrize("name", [
        "barcode01", "sample_A", "negative_strand_test", "Anopheles",
        "control_group_positive", "", None,
    ])
    def test_not_controls(self, name):
        assert is_negative_control(name) is False

    def test_configured_list_is_authoritative(self):
        config = {"negative_control_samples": ["barcode12"]}
        assert is_negative_control("barcode12", config) is True
        assert is_negative_control("barcode11", config) is False

    def test_configured_match_is_case_insensitive(self):
        config = {"negative_control_samples": ["Barcode12 "]}
        assert is_negative_control("barcode12", config) is True
