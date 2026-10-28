"""The first polls after boot run at the active cadence (field audit
2026-10-28, M8). The Interval booted at the active cadence but the first
app-config write switched it to the idle one before any tick fired, so a
dashboard opened on existing results showed STANDBY and 0 sequences for
over a minute (79 s measured)."""

from unittest.mock import MagicMock

import pytest
from dash import Dash

from dash_test_utils import get_callback_fn
from nanometa_live.app.callbacks.interval_offline import register_interval_offline

pytestmark = pytest.mark.callback


@pytest.fixture
def interval_fn():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_interval_offline(app, MagicMock())
    return get_callback_fn(app, "update-interval.interval")


CFG = {"update_interval_seconds": 10, "idle_update_interval_seconds": 60}
IDLE = {"running": False}


def test_first_ticks_are_fast_even_when_idle(interval_fn):
    assert interval_fn(CFG, IDLE, 0) == 10_000
    assert interval_fn(CFG, IDLE, 1) == 10_000


def test_idle_back_off_after_warmup(interval_fn):
    assert interval_fn(CFG, IDLE, 2) == 60_000
    assert interval_fn(CFG, IDLE, 50) == 60_000


def test_active_run_is_always_fast(interval_fn):
    assert interval_fn(CFG, {"running": True}, 50) == 10_000
    assert interval_fn(CFG, {"starting": True}, 50) == 10_000
