"""Tests for UX components: empty states, actionable errors, and callback output formats."""

import os
import pytest
import pandas as pd
import dash_bootstrap_components as dbc

from nanometa_live.core.utils.data_loaders import (
    load_kraken_data,
    clear_data_cache,
    KRAKEN2_EXPECTED_COLUMNS,
    _empty_fastp_stats,
    _empty_nanoplot_stats,
)
from nanometa_live.app.utils.error_handler import (
    get_actionable_error,
    create_error_toast,
    ErrorCategory,
    ActionableError,
    PIPELINE_ERROR_MESSAGES,
)
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


class TestActionableErrors:
    """Verify error handler produces correct categories and structures."""

    def test_file_not_found_error(self):
        result = get_actionable_error(FileNotFoundError("missing.txt"))
        assert result.category == ErrorCategory.FILE_SYSTEM

    def test_permission_error(self):
        result = get_actionable_error(PermissionError("/path"))
        assert result.category == ErrorCategory.PERMISSION
        assert len(result.suggestions) > 0

    def test_pipeline_errors_all_defined(self):
        for key, error in PIPELINE_ERROR_MESSAGES.items():
            assert isinstance(error, ActionableError), f"{key} is not ActionableError"
            assert error.title, f"{key} has empty title"
            assert error.message, f"{key} has empty message"
            assert len(error.suggestions) > 0, f"{key} has no suggestions"

    def test_to_alert_renders_correctly(self):
        error = ActionableError(
            title="Test",
            message="msg",
            suggestions=["fix it"],
            category=ErrorCategory.FILE_SYSTEM,
        )
        alert = error.to_alert()
        assert isinstance(alert, dbc.Alert)

    def test_unknown_exception_fallback(self):
        result = get_actionable_error(RuntimeError("weird"))
        assert result.category == ErrorCategory.UNKNOWN


class TestCallbackOutputFormats:
    """Verify callback helpers return correctly shaped data."""

    def test_status_display_returns_expected_keys(self):
        error = ActionableError(
            title="Test",
            message="msg",
            suggestions=["do something"],
            category=ErrorCategory.FILE_SYSTEM,
        )
        toast = create_error_toast(error)
        assert set(toast.keys()) == {"header", "body", "icon", "duration", "type"}

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
