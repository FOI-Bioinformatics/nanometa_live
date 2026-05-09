"""Unit tests for per-sample freshness derivation (U2, 2026-05-09 spec)."""

import os
import time

import pytest

from nanometa_live.app.components.freshness_pill import (
    GREEN_MAX_S,
    AMBER_MAX_S,
    _band_for_age,
    _format_age_label,
    freshness_pill,
)
from nanometa_live.app.utils.freshness import (
    age_seconds_for,
    freshness_map,
    sample_last_data_ts,
)


# ---- Band classification ---------------------------------------------------

def test_band_for_age_unknown_is_secondary():
    color, _ = _band_for_age(None)
    assert color == "secondary"


def test_band_for_age_under_60s_is_green():
    color, _ = _band_for_age(0.0)
    assert color == "success"
    color, _ = _band_for_age(GREEN_MAX_S - 0.1)
    assert color == "success"


def test_band_for_age_60_to_300s_is_amber():
    color, text = _band_for_age(GREEN_MAX_S)
    assert color == "warning"
    assert text == "text-dark"
    color, _ = _band_for_age(AMBER_MAX_S - 0.1)
    assert color == "warning"


def test_band_for_age_over_300s_is_red():
    color, _ = _band_for_age(AMBER_MAX_S)
    assert color == "danger"
    color, _ = _band_for_age(86400.0)
    assert color == "danger"


# ---- Label formatting ------------------------------------------------------

def test_format_age_label_unknown():
    assert _format_age_label(None) == "--"
    assert _format_age_label(-1) == "--"


def test_format_age_label_seconds_minutes_hours():
    assert _format_age_label(45) == "45s"
    assert _format_age_label(60) == "1m"
    assert _format_age_label(180) == "3m"
    assert _format_age_label(3600) == "1h+"
    assert _format_age_label(7200) == "1h+"


# ---- age_seconds_for -------------------------------------------------------

def test_age_seconds_for_basic():
    now = 1_000_000.0
    assert age_seconds_for(now - 30, now) == 30.0
    assert age_seconds_for(None, now) is None


def test_age_seconds_for_clock_skew_clamps_to_zero():
    """Future timestamps should not yield negative ages."""
    now = 1_000_000.0
    assert age_seconds_for(now + 5, now) == 0.0


# ---- Filesystem-backed sample_last_data_ts ---------------------------------

def test_sample_last_data_ts_reads_batch_reports(tmp_path):
    main_dir = tmp_path
    sample = "barcode01"
    batch_dir = main_dir / "kraken2" / sample / "batch_reports"
    batch_dir.mkdir(parents=True)
    f1 = batch_dir / "batch_001.kraken2.report.txt"
    f1.write_text("data")
    expected = f1.stat().st_mtime
    assert sample_last_data_ts(str(main_dir), sample) == pytest.approx(expected)


def test_sample_last_data_ts_falls_back_to_top_level(tmp_path):
    main_dir = tmp_path
    sample = "barcode02"
    kraken_dir = main_dir / "kraken2"
    kraken_dir.mkdir()
    report = kraken_dir / f"{sample}.kraken2.report.txt"
    report.write_text("data")
    expected = report.stat().st_mtime
    assert sample_last_data_ts(str(main_dir), sample) == pytest.approx(expected)


def test_sample_last_data_ts_unknown_sample_returns_none(tmp_path):
    main_dir = tmp_path
    (main_dir / "kraken2").mkdir()
    assert sample_last_data_ts(str(main_dir), "barcode99") is None


def test_freshness_map_skips_aggregate(tmp_path):
    main_dir = tmp_path
    (main_dir / "kraken2").mkdir()
    fmap = freshness_map(str(main_dir), ["All Samples", "barcode01"])
    assert "All Samples" not in fmap
    assert "barcode01" in fmap
    assert fmap["barcode01"] is None


# ---- Component smoke -------------------------------------------------------

def test_freshness_pill_returns_badge():
    badge = freshness_pill("barcode01", 12.0)
    # The component should be a dbc.Badge instance.
    import dash_bootstrap_components as dbc
    assert isinstance(badge, dbc.Badge)
    assert badge.color == "success"
    assert badge.children == "12s"
