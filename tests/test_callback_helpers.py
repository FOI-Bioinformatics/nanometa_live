"""
Unit tests for app/utils/callback_helpers.py (was 27% covered).

These are the pure validators, formatters, alert/figure builders and kraken
stat helpers used inside callbacks. All deterministic; the only I/O is path
existence (tmp_path) and a kraken loader wrapped for safety.
"""

import logging

import pandas as pd
import plotly.graph_objects as go
import pytest
from dash import html
import dash_bootstrap_components as dbc

from nanometa_live.app.utils.callback_helpers import (
    create_empty_alert,
    create_error_alert,
    create_info_alert,
    empty_figure,
    get_classification_stats,
    get_pipeline_output_dir,
    get_total_kraken_reads,
    log_callback_error,
    safe_load_kraken_data,
    validate_config,
    validate_config_and_get_main_dir,
    validate_dataframe,
    validate_numeric,
    validate_path,
    validate_sample,
)

pytestmark = pytest.mark.unit


class TestValidateConfig:
    def test_none_invalid(self):
        ok, msg = validate_config(None)
        assert ok is False and "No configuration" in msg

    def test_non_dict_invalid(self):
        ok, msg = validate_config(["not", "a", "dict"])
        assert ok is False

    def test_dict_valid(self):
        assert validate_config({"a": 1}) == (True, None)


class TestValidateSample:
    def test_none(self):
        assert validate_sample(None)[0] is False

    def test_not_in_available(self):
        ok, msg = validate_sample("barcode99", ["barcode01"])
        assert ok is False and "not found" in msg

    def test_all_samples_always_valid(self):
        assert validate_sample("All Samples", ["barcode01"]) == (True, None)

    def test_present_sample(self):
        assert validate_sample("barcode01", ["barcode01"]) == (True, None)


class TestValidateDataframe:
    def test_none_and_empty_invalid(self):
        assert validate_dataframe(None)[0] is False
        assert validate_dataframe(pd.DataFrame())[0] is False

    def test_missing_columns(self):
        df = pd.DataFrame({"a": [1]})
        ok, msg = validate_dataframe(df, required_columns=["a", "b"])
        assert ok is False and "b" in msg

    def test_valid(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        assert validate_dataframe(df, required_columns=["a", "b"]) == (True, None)


class TestValidateNumeric:
    def test_none_required(self):
        assert validate_numeric(None)[0] is False

    def test_nan_invalid(self):
        assert validate_numeric(float("nan"))[0] is False

    def test_below_min(self):
        ok, msg = validate_numeric(3, min_val=5)
        assert ok is False and "at least" in msg

    def test_above_max(self):
        ok, msg = validate_numeric(10, max_val=5)
        assert ok is False and "at most" in msg

    def test_within_bounds(self):
        assert validate_numeric("4.5", min_val=0, max_val=10) == (True, None)

    def test_non_number(self):
        assert validate_numeric("abc")[0] is False


class TestValidatePath:
    def test_empty_required(self):
        assert validate_path("")[0] is False

    def test_traversal_rejected(self):
        assert validate_path("/a/../b")[0] is False

    def test_missing_when_must_exist(self, tmp_path):
        assert validate_path(str(tmp_path / "nope"))[0] is False

    def test_existing(self, tmp_path):
        assert validate_path(str(tmp_path)) == (True, None)

    def test_missing_allowed_when_must_exist_false(self, tmp_path):
        assert validate_path(str(tmp_path / "new"), must_exist=False) == (True, None)


class TestEmptyFigure:
    def test_message_and_height(self):
        fig = empty_figure("Nothing here", height=321)
        assert isinstance(fig, go.Figure)
        assert fig.layout.annotations[0].text == "Nothing here"
        assert fig.layout.height == 321


class TestPipelineOutputDir:
    def test_none_config(self):
        assert get_pipeline_output_dir(None) is None

    def test_results_dir_preferred(self, tmp_path):
        assert get_pipeline_output_dir({"results_output_directory": str(tmp_path)}) == str(tmp_path)

    def test_falls_back_to_main_dir(self, tmp_path):
        cfg = {"results_output_directory": "/does/not/exist", "main_dir": str(tmp_path)}
        assert get_pipeline_output_dir(cfg) == str(tmp_path)

    def test_neither_exists(self):
        assert get_pipeline_output_dir({"results_output_directory": "/nope"}) is None

    def test_validate_wrapper_matches(self, tmp_path):
        cfg = {"results_output_directory": str(tmp_path)}
        assert validate_config_and_get_main_dir(cfg) == get_pipeline_output_dir(cfg)


class TestAlertBuilders:
    def test_empty_alert(self):
        alert = create_empty_alert("Loading...", color="light")
        assert isinstance(alert, dbc.Alert)
        assert alert.color == "light"

    def test_error_alert_is_danger(self):
        assert create_error_alert("boom").color == "danger"

    def test_info_alert_is_info(self):
        assert create_info_alert("fyi").color == "info"


class TestKrakenStats:
    def _kraken_df(self):
        return pd.DataFrame({
            "name": ["unclassified", "root", "  Bacteria"],
            "cumul_reads": [50, 450, 450],
            "rank": ["U", "R", "D"],
        })

    def test_classification_stats(self):
        classified, unclassified, rate = get_classification_stats(self._kraken_df())
        assert classified == 450
        assert unclassified == 50
        assert rate == pytest.approx(90.0)

    def test_empty_df(self):
        assert get_classification_stats(pd.DataFrame()) == (0, 0, 0.0)

    def test_missing_name_column(self):
        assert get_classification_stats(pd.DataFrame({"x": [1]})) == (0, 0, 0.0)

    def test_total_reads(self):
        assert get_total_kraken_reads(self._kraken_df()) == 500


class TestSafeLoadAndLog:
    def test_safe_load_returns_empty_on_bad_dir(self, tmp_path):
        df = safe_load_kraken_data(str(tmp_path / "nope"), "All Samples")
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_log_callback_error_does_not_raise(self):
        # Smoke: logging a handled error must never propagate.
        log_callback_error("my_cb", ValueError("boom"), level=logging.WARNING)
