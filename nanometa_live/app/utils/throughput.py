"""
Pure helpers for the header throughput tile (U1 in the 2026-05-09 UX spec).

The tile shows reads/min and files/min derived from a 5-tick rolling buffer
of cumulative samples. Logic is isolated here so it can be unit tested
without standing up a Dash app.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Maximum entries kept in the buffer. A small window keeps the rate
# responsive without smoothing away short stalls.
BUFFER_LIMIT = 5

# Stall detection threshold (seconds): if the rate has been zero for
# longer than this, the tile flips to STALLED.
STALL_THRESHOLD_S = 120.0


def append_tick(
    buffer: List[Dict[str, float]],
    ts: float,
    total_reads: int,
    total_files: int,
) -> List[Dict[str, float]]:
    """Append one tick to the buffer and trim to BUFFER_LIMIT entries."""
    new_buf = list(buffer or [])
    new_buf.append({"ts": ts, "reads": int(total_reads), "files": int(total_files)})
    if len(new_buf) > BUFFER_LIMIT:
        new_buf = new_buf[-BUFFER_LIMIT:]
    return new_buf


def compute_rates(
    buffer: List[Dict[str, float]],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute reads-per-minute and files-per-minute from the buffer.

    Returns (None, None) when fewer than two ticks are available or when
    the time window is non-positive. Negative deltas (a counter reset
    between runs) clamp to zero rather than producing a misleading
    negative rate.
    """
    if not buffer or len(buffer) < 2:
        return None, None
    first = buffer[0]
    last = buffer[-1]
    dt = float(last["ts"]) - float(first["ts"])
    if dt <= 0:
        return None, None
    d_reads = max(0, int(last["reads"]) - int(first["reads"]))
    d_files = max(0, int(last["files"]) - int(first["files"]))
    return (d_reads * 60.0) / dt, (d_files * 60.0) / dt


def last_nonzero_delta_ts(buffer: List[Dict[str, float]]) -> Optional[float]:
    """
    Return the timestamp of the most recent tick where reads advanced.

    Used to drive stall detection. None when no tick recorded a positive
    delta (e.g. the buffer has not yet captured any progress).
    """
    if not buffer or len(buffer) < 2:
        return None
    last_ts: Optional[float] = None
    prev = buffer[0]
    for entry in buffer[1:]:
        if int(entry["reads"]) > int(prev["reads"]):
            last_ts = float(entry["ts"])
        prev = entry
    return last_ts


def classify_state(
    buffer: List[Dict[str, float]],
    now: float,
    pipeline_running: bool,
    last_progress: Optional[float] = None,
    watch_since: Optional[float] = None,
) -> str:
    """
    Map the current buffer + pipeline status to a tile state.

    Returns one of "idle", "normal", "stalled". Idle takes precedence
    when the pipeline is not running or the buffer has fewer than two
    ticks. A stall requires the pipeline to be running and no nonzero
    delta within STALL_THRESHOLD_S.

    ``last_progress`` and ``watch_since`` carry history the rate window
    cannot hold: the buffer spans BUFFER_LIMIT ticks (about 50 s at the
    10 s run cadence), shorter than STALL_THRESHOLD_S, so from the buffer
    alone a stall was never observable. Both default to what the buffer
    shows. See :func:`advance_throughput`.
    """
    if not pipeline_running:
        return "idle"
    if not buffer or len(buffer) < 2:
        return "idle"
    if last_progress is None:
        last_progress = last_nonzero_delta_ts(buffer)
    if last_progress is not None and (now - last_progress) <= STALL_THRESHOLD_S:
        return "normal"
    if last_progress is None:
        # Pipeline running but never observed progress; only flip to
        # stalled once enough wall time has passed.
        first_ts = watch_since if watch_since is not None else float(buffer[0]["ts"])
        if now - first_ts > STALL_THRESHOLD_S:
            return "stalled"
        return "idle"
    return "stalled"


def advance_throughput(
    state: Optional[Dict],
    now: float,
    total_reads: int,
    total_files: int,
    running: bool,
) -> Tuple[Dict, str]:
    """Advance the tile's stored state by one tick; return (state, tile state).

    ``state`` is the ``throughput-buffer`` Store value without its ``dir``
    key handling (the caller resets it on an outdir switch). Besides the
    rate window (``ticks``) it keeps:

    - ``last_progress``: the last tick at which reads advanced. It must
      outlive the rate window, or a stall is forgotten before it is old
      enough to report.
    - ``watch_since``: when the current run was first seen running, so a
      run that never produces reads also stalls after the threshold.

    Both reset when the pipeline is not running, so one run's stall clock
    never carries into the next.
    """
    state = dict(state or {})
    ticks = append_tick(state.get("ticks") or [], now, total_reads, total_files)
    if running:
        last_progress = last_nonzero_delta_ts(ticks) or state.get("last_progress")
        watch_since = state.get("watch_since")
        if watch_since is None:
            watch_since = now
    else:
        last_progress = None
        watch_since = None
    tile_state = classify_state(ticks, now, running, last_progress, watch_since)
    state.update(ticks=ticks, last_progress=last_progress, watch_since=watch_since)
    return state, tile_state


def format_age_seconds(seconds: float) -> str:
    """
    Format a positive elapsed-seconds value as 'NmSSs' (e.g. '3m12s').

    Negative or zero values render as '0s'. The format is intended for
    the 'last data Nm Ss' subtitle in the stalled state.
    """
    if seconds is None or seconds <= 0:
        return "0s"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    return f"{minutes}m{sec:02d}s"
