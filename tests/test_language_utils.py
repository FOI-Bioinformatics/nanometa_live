"""
Unit tests for core/utils/language_utils.py (was 0% covered).

Pure string/format/lookup helpers that render technical metrics in plain
language for the operator UI. All deterministic, no I/O.
"""

import pytest

from nanometa_live.core.utils.language_utils import (
    create_plain_summary,
    format_number,
    format_percentage,
    format_time_duration,
    get_classification_interpretation,
    get_metric_description,
    get_pathogen_action_guidance,
    get_quality_interpretation,
    get_read_count_interpretation,
    get_recommendation,
    translate_status,
    translate_term,
)

pytestmark = pytest.mark.unit


class TestTranslateTerm:
    def test_known_term_is_translated(self):
        assert translate_term("reads") == "DNA sequences"

    def test_case_and_whitespace_insensitive(self):
        assert translate_term("  READS ") == "DNA sequences"

    def test_unknown_term_returned_unchanged(self):
        assert translate_term("zzzgibberish") == "zzzgibberish"


class TestTranslateStatus:
    def test_known_status(self):
        assert translate_status("running") == "In Progress"

    def test_unknown_status_titlecased(self):
        assert translate_status("wibble") == "Wibble"


class TestFormatNumber:
    def test_thousands_separator(self):
        assert format_number(1500) == "1,500"

    def test_millions_hint(self):
        assert format_number(1_500_000) == "1,500,000 (1.5 million)"

    def test_plain_language_disabled(self):
        assert format_number(1_500_000, use_plain_language=False) == "1,500,000"


class TestFormatPercentage:
    def test_default_one_decimal(self):
        assert format_percentage(75.5) == "75.5%"

    def test_custom_decimals(self):
        assert format_percentage(99.99, decimal_places=2) == "99.99%"


class TestFormatTimeDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (1, "1 second"),
            (30, "30 seconds"),
            (60, "1 minute"),
            (90, "1 minute 30 seconds"),
            (3600, "1 hour"),
            (3661, "1 hour 1 minute"),
            (90000, "1 day 1 hour"),
            (172800, "2 days"),
        ],
    )
    def test_durations(self, seconds, expected):
        assert format_time_duration(seconds) == expected


class TestQualityInterpretation:
    @pytest.mark.parametrize(
        "score,rating,color",
        [
            (90, "Excellent", "success"),
            (80, "Good", "success"),
            (65, "Fair", "warning"),
            (50, "Poor", "danger"),
            (10, "Very Poor", "danger"),
        ],
    )
    def test_bands(self, score, rating, color):
        r, _explanation, c = get_quality_interpretation(score)
        assert (r, c) == (rating, color)


class TestClassificationInterpretation:
    @pytest.mark.parametrize(
        "rate,rating,color",
        [(75, "High", "success"), (55, "Moderate", "info"),
         (35, "Low", "warning"), (10, "Very Low", "danger")],
    )
    def test_bands(self, rate, rating, color):
        r, _exp, c = get_classification_interpretation(rate)
        assert (r, c) == (rating, color)


class TestReadCountInterpretation:
    @pytest.mark.parametrize(
        "count,rating",
        [(2_000_000, "Very High"), (200_000, "High"),
         (20_000, "Moderate"), (2_000, "Low")],
    )
    def test_bands(self, count, rating):
        assert get_read_count_interpretation(count)[0] == rating


class TestPathogenActionGuidance:
    def test_critical_has_stop_instruction(self):
        g = get_pathogen_action_guidance("critical")
        assert "STOP" in g["immediate"]
        assert g["color"] == "danger"
        assert {"immediate", "next_steps", "contact"} <= set(g)

    def test_unknown_threat_falls_back_to_low(self):
        assert get_pathogen_action_guidance("nonsense") == get_pathogen_action_guidance("low")


class TestMetricDescriptionAndRecommendation:
    def test_unknown_metric_falls_back(self):
        assert get_metric_description("zzz").startswith("Information about")

    def test_unknown_recommendation_falls_back(self):
        assert get_recommendation("zzz") == (
            "Continue monitoring and contact support if issues persist"
        )


class TestCreatePlainSummary:
    def test_includes_counts_and_singular_plural(self):
        summary = create_plain_summary(
            total_reads=10000, pass_rate=85.5, organisms_detected=12, sample_count=3
        )
        assert "10,000 DNA sequences" in summary
        assert "3 samples" in summary
        assert "85.5%" in summary
        assert "12 different organisms" in summary

    def test_zero_organisms_message(self):
        summary = create_plain_summary(100, 90.0, 0, 1)
        assert "1 sample" in summary  # singular
        assert "No organisms identified" in summary
