"""Unit tests for the realtime-timeout countdown helpers (U3, 2026-05-09)."""

import pytest

from nanometa_live.app.utils.countdown import (
    DANGER_THRESHOLD_S,
    WARN_THRESHOLD_S,
    countdown_classes,
    format_countdown,
)


# ---- Formatter -------------------------------------------------------------

def test_format_countdown_none_input():
    assert format_countdown(None) is None


def test_format_countdown_invalid_input():
    assert format_countdown("not-a-number") is None


def test_format_countdown_zero_or_negative():
    assert format_countdown(0) == "0s"
    assert format_countdown(-3) == "0s"


def test_format_countdown_seconds_only():
    assert format_countdown(1) == "1s"
    assert format_countdown(58) == "58s"
    assert format_countdown(59) == "59s"


def test_format_countdown_minute_grain():
    assert format_countdown(60) == "1m 00s"
    assert format_countdown(452) == "7m 32s"
    assert format_countdown(3599) == "59m 59s"


def test_format_countdown_hour_grain():
    assert format_countdown(3600) == "1h 00m"
    assert format_countdown(3840) == "1h 04m"
    assert format_countdown(7320) == "2h 02m"


# ---- Class escalation ------------------------------------------------------

def test_countdown_classes_none():
    text, icon = countdown_classes(None)
    assert "text-muted" in text
    assert icon == "bi-hourglass-split"


def test_countdown_classes_calm():
    text, icon = countdown_classes(WARN_THRESHOLD_S + 1)
    assert "text-muted" in text
    assert icon == "bi-hourglass-split"


def test_countdown_classes_warn_at_boundary():
    # Spec: <= 5 minutes triggers warning band.
    text, icon = countdown_classes(WARN_THRESHOLD_S)
    assert "text-warning" in text
    assert icon == "bi-hourglass-bottom"


def test_countdown_classes_warn_below_threshold():
    text, icon = countdown_classes(120)
    assert "text-warning" in text


def test_countdown_classes_danger_at_boundary():
    # Spec: <= 60 s triggers danger band.
    text, icon = countdown_classes(DANGER_THRESHOLD_S)
    assert "text-danger" in text
    assert icon == "bi-hourglass-bottom"


def test_countdown_classes_danger_below_threshold():
    text, icon = countdown_classes(15)
    assert "text-danger" in text
    assert "fw-bold" in text


def test_countdown_classes_invalid_input_falls_back():
    text, _ = countdown_classes("nope")
    assert "text-muted" in text
