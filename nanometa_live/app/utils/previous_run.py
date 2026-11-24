"""The run that produced a results folder, for an app that did not start it.

A restarted app opened on a finished run's results said STANDBY, "Click
'Start Analysis' to begin processing" and a run time of 00:00:00 above a page
of detections (Barcelona exercise feedback, 2026-11-24). The run's outcome is
already on disk in ``.nanometa.run.json``; this module reads it for the
header and the run-time tile. It is consulted only where those would
otherwise say STANDBY, never while a run is active.

The header polls every few seconds, so the read is memoised on the metadata
file's mtime: one ``stat`` per poll while the file is unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from nanometa_live.core.export.run_status import (
    RUN_METADATA_FILENAME,
    read_final_run_status,
)

_TERMINAL = ("completed", "stopped", "error")


@dataclass(frozen=True)
class PreviousRun:
    run_state: str
    started_at: Optional[str]
    ended_at: Optional[str]
    duration_s: Optional[int]
    stop_reason: Optional[str]


# Single entry: (metadata path, mtime_ns) -> result. One results folder is
# on screen at a time, so one entry is enough and nothing accumulates.
_last: Optional[Tuple[Tuple[str, int], Optional[PreviousRun]]] = None


def _seconds_between(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    except (TypeError, ValueError):
        return None
    return max(0, int(delta.total_seconds()))


def _written_at(path: str) -> Optional[str]:
    import json

    try:
        with open(path) as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    return meta.get("written_at") if isinstance(meta, dict) else None


def previous_run_status(results_dir: Optional[str]) -> Optional[PreviousRun]:
    """The finished run recorded in ``results_dir``, or None."""
    global _last
    if not results_dir:
        return None
    path = os.path.join(results_dir, RUN_METADATA_FILENAME)
    try:
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return None
    if _last is not None and _last[0] == key:
        return _last[1]
    final = read_final_run_status(results_dir)
    result = None
    if final.get("run_state") in _TERMINAL:
        started = _written_at(path)
        ended = final.get("ended_at")
        result = PreviousRun(
            run_state=final["run_state"],
            started_at=started,
            ended_at=ended,
            duration_s=_seconds_between(started, ended),
            stop_reason=final.get("stop_reason"),
        )
    _last = (key, result)
    return result


def format_duration(seconds: Optional[int]) -> str:
    """``HH:MM:SS``, or ``--:--:--`` when the duration is not known."""
    if seconds is None:
        return "--:--:--"
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _clock(iso: Optional[str]) -> Optional[str]:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M") if iso else None
    except (TypeError, ValueError):
        return None


def _ran_for(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f" (ran {hours} h {minutes} min)" if hours else f" (ran {minutes} min)"


def previous_run_header(prev: PreviousRun) -> Tuple[str, str, str]:
    """(colour, text, details) for the header's status line."""
    at = _clock(prev.ended_at)
    when = f" at {at}" if at else ""
    if prev.run_state == "completed":
        color, outcome = "blue", f"Completed{when}"
    elif prev.run_state == "stopped":
        reason = f" ({prev.stop_reason})" if prev.stop_reason else ""
        color, outcome = "orange", f"Stopped{reason}{when}"
    else:
        color, outcome = "red", f"Ended with an error{when}"
    details = (f"{outcome}{_ran_for(prev.duration_s)}. Results shown are from "
               "that run; Start Analysis begins a new one.")
    return color, "LAST RUN", details
