"""Tests for UX components: empty states, actionable errors, and callback output formats."""

import os
import pytest
import pandas as pd
from nanometa_live.core.utils.data_loaders import (
    load_kraken_data,
    clear_data_cache,
    KRAKEN2_EXPECTED_COLUMNS,
    _empty_fastp_stats,
    _empty_nanoplot_stats,
)
from nanometa_live.app.components.modern_components import EmptyStateMessage
from nanometa_live.core.utils.sample_detector import get_available_samples


class TestEmptyStates:
    """Verify that empty/missing data produces well-formed default structures."""

    def test_empty_kraken_df_has_correct_columns(self, tmp_path):
        clear_data_cache()
        df = load_kraken_data(str(tmp_path))
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == KRAKEN2_EXPECTED_COLUMNS
        assert len(df) == 0

    def test_empty_fastp_stats_has_all_keys(self):
        stats = _empty_fastp_stats()
        expected_keys = {
            "total_reads_before",
            "total_reads_after",
            "total_bases_before",
            "total_bases_after",
            "passed_filter",
            "low_quality",
            "too_short",
            "too_many_N",
            "q30_rate_after",
        }
        assert set(stats.keys()) == expected_keys
        for value in stats.values():
            assert value == 0 or value == 0.0

    def test_empty_nanoplot_stats(self):
        stats = _empty_nanoplot_stats()
        assert stats["source"] == "none"
        for key, value in stats.items():
            if key != "source":
                assert value == 0 or value == 0.0


    def test_empty_state_message_has_all_params(self):
        """EmptyStateMessage renders with all supported parameters."""
        from dash import html

        # Basic usage
        component = EmptyStateMessage(
            title="Test Title",
            message="Test message",
            icon="bi-inbox",
        )
        assert isinstance(component, html.Div)

        # With action button
        component_with_action = EmptyStateMessage(
            title="No Data",
            message="Start analysis",
            icon="bi-hourglass",
            action_button={"label": "Start", "id": "start-btn"},
        )
        assert isinstance(component_with_action, html.Div)

        # Default params
        component_default = EmptyStateMessage()
        assert isinstance(component_default, html.Div)


class TestCallbackOutputFormats:
    """Verify callback helpers return correctly shaped data."""

    def test_sample_selector_options(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        report = kraken_dir / "barcode01.kraken2.report.txt"
        report.write_text(
            " 95.00\t1000\t1000\tU\t0\tunclassified\n"
            "  5.00\t50\t50\tS\t562\tEscherichia coli\n"
        )
        samples = get_available_samples(str(tmp_path))
        assert "All Samples" in samples
        assert "barcode01" in samples
