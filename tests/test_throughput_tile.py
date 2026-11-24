"""Unit tests for the header throughput tile helpers (U1, 2026-05-09 spec)."""

import pytest

from nanometa_live.app.utils.throughput import (
    BUFFER_LIMIT,
    STALL_THRESHOLD_S,
    append_tick,
    classify_state,
    compute_rates,
    format_age_seconds,
    last_nonzero_delta_ts,
)


def _series(start_ts, deltas):
    """Helper: build a buffer from (dt_seconds, reads, files) tuples."""
    buf = []
    for dt, reads, files in deltas:
        buf = append_tick(buf, start_ts + dt, reads, files)
    return buf


def test_append_tick_trims_to_limit():
    buf = []
    for i in range(BUFFER_LIMIT + 3):
        buf = append_tick(buf, ts=i, total_reads=i, total_files=i)
    assert len(buf) == BUFFER_LIMIT
    # The trim keeps the most recent ticks.
    assert buf[-1]["reads"] == BUFFER_LIMIT + 2


def test_compute_rates_steady_progress():
    # 1000 reads in 60 seconds -> 1000 reads/min.
    buf = _series(0, [(0, 0, 0), (60, 1000, 5)])
    rpm, fpm = compute_rates(buf)
    assert rpm == pytest.approx(1000.0)
    assert fpm == pytest.approx(5.0)


def test_compute_rates_too_few_ticks_returns_none():
    buf = _series(0, [(0, 100, 1)])
    assert compute_rates(buf) == (None, None)


def test_compute_rates_clamps_negative_delta():
    # Counter reset between runs must not produce a negative rate.
    buf = _series(0, [(0, 5000, 10), (60, 0, 0)])
    rpm, fpm = compute_rates(buf)
    assert rpm == 0.0
    assert fpm == 0.0


def test_classify_state_idle_when_not_running():
    buf = _series(0, [(0, 0, 0), (10, 100, 1)])
    assert classify_state(buf, now=20, pipeline_running=False) == "idle"


def test_classify_state_idle_with_too_few_ticks():
    buf = _series(0, [(0, 0, 0)])
    assert classify_state(buf, now=10, pipeline_running=True) == "idle"


def test_classify_state_normal_when_progress():
    buf = _series(0, [(0, 0, 0), (30, 500, 2)])
    assert classify_state(buf, now=30, pipeline_running=True) == "normal"


def test_classify_state_stalled_after_threshold():
    # Last progress at t=30; current time is more than STALL_THRESHOLD_S later.
    buf = _series(0, [(0, 0, 0), (30, 500, 2), (60, 500, 2)])
    now = 30 + STALL_THRESHOLD_S + 1
    assert classify_state(buf, now=now, pipeline_running=True) == "stalled"


def test_classify_state_not_stalled_just_below_threshold():
    buf = _series(0, [(0, 0, 0), (30, 500, 2), (60, 500, 2)])
    now = 30 + STALL_THRESHOLD_S - 1
    assert classify_state(buf, now=now, pipeline_running=True) == "normal"


def test_last_nonzero_delta_ts():
    buf = _series(0, [(0, 0, 0), (10, 50, 1), (20, 50, 1), (30, 80, 2)])
    assert last_nonzero_delta_ts(buf) == 30


def test_format_age_seconds():
    assert format_age_seconds(0) == "0s"
    assert format_age_seconds(-5) == "0s"
    assert format_age_seconds(45) == "45s"
    assert format_age_seconds(60) == "1m00s"
    assert format_age_seconds(192) == "3m12s"


# --- Stall detection over a real tick cadence --------------------------------
#
# The buffer holds BUFFER_LIMIT ticks, about 50 s at the 10 s run cadence,
# while STALL_THRESHOLD_S is 120 s. Classified from the buffer alone, the
# last progress tick fell out of the window long before the threshold and
# the oldest tick was never 120 s old: a run whose reads stopped read
# "idle" (--- reads/min) for ever and the tile never said "stalled".
# advance_throughput carries the last-progress time and the time the run
# was first seen across ticks, outside the trimmed rate window.

from nanometa_live.app.utils.throughput import advance_throughput  # noqa: E402


def _drive(schedule, start=1000.0, tick_s=10.0):
    """Feed (reads, running) per tick at tick_s; return the states."""
    buf, states = {}, []
    for i, (reads, running) in enumerate(schedule):
        buf, state = advance_throughput(
            buf, now=start + i * tick_s, total_reads=reads, total_files=0,
            running=running)
        states.append(state)
    return buf, states


def test_stall_is_reported_when_reads_stop_at_the_10s_cadence():
    # 10 ticks of progress, then 30 ticks (300 s) with no new reads.
    schedule = [(100 * i, True) for i in range(10)] + [(900, True)] * 30
    _, states = _drive(schedule)
    assert states[9] == "normal"
    # Inside the threshold after the last progress: not yet a stall.
    assert "stalled" not in states[10:20]
    # Well past 120 s without progress: stalled, and it stays stalled.
    assert set(states[-10:]) == {"stalled"}


def test_stall_age_is_measured_from_the_last_progress():
    schedule = [(100 * i, True) for i in range(10)] + [(900, True)] * 30
    buf, _ = _drive(schedule)
    # Last progress at tick 9 (t=1090); the final tick is t=1390.
    assert buf["last_progress"] == pytest.approx(1090.0)


def test_running_without_any_progress_stalls_after_the_threshold():
    _, states = _drive([(0, True)] * 20)
    assert states[5] != "stalled"
    assert states[-1] == "stalled"


def test_progress_resuming_clears_the_stall():
    schedule = ([(100 * i, True) for i in range(5)] + [(400, True)] * 20
                + [(500, True), (600, True)])
    _, states = _drive(schedule)
    assert states[-3] == "stalled"
    assert states[-1] == "normal"


def test_stop_resets_the_stall_clock():
    schedule = [(0, True)] * 20 + [(0, False)] * 2 + [(0, True)] * 3
    _, states = _drive(schedule)
    assert states[19] == "stalled"
    assert states[20] == "idle"
    # A new run starts its own clock.
    assert states[-1] != "stalled"
