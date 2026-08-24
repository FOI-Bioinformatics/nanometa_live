"""Watchdog for background-callback workers that died mid-job (round 3).

A DiskcacheManager worker runs in a separate OS process. When it is
killed (OOM, crash), Dash's ``running=`` machinery never fires its
off-state: the progress bar freezes at its last value and the trigger
buttons stay disabled for the life of the session, with a browser refresh
as the only exit. The export modal -- a worker that copies up to 5 GiB --
is the most exposed surface.

The watchdog is a main-process interval callback: while an export is
running it tracks (progress value, since when unchanged) in a memory
Store; once the value has been frozen past ``WATCHDOG_TIMEOUT_S`` it
re-enables the modal's buttons and posts a warning toast. The timeout is
generous on purpose (the raw-copy stage can legitimately hold one
progress value for minutes on a slow disk) -- this is a last-resort
unstick, not a liveness probe.
"""

import time
from typing import Optional, Tuple

from dash import Input, Output, State, no_update
from dash.exceptions import PreventUpdate

#: Seconds a running export's progress value may stay frozen before the
#: watchdog declares the worker dead. Must exceed the longest legitimate
#: silent stage (the capped 5 GiB raw copy on a slow disk).
WATCHDOG_TIMEOUT_S = 300.0


def watchdog_decision(
    *,
    state: Optional[dict],
    running: bool,
    progress,
    now: float,
    timeout_s: float = WATCHDOG_TIMEOUT_S,
) -> Tuple[Optional[dict], bool]:
    """Pure decision: (next tracking state, fire?).

    ``state`` is ``{"progress": value, "since": timestamp}`` or None.
    Not running clears tracking; advancing progress resets the clock;
    a frozen value past the timeout fires once and clears.
    """
    if not running:
        return None, False
    if state is None or state.get("progress") != progress:
        return {"progress": progress, "since": now}, False
    if now - float(state.get("since", now)) >= timeout_s:
        return None, True
    return state, False


def register_worker_watchdog(app) -> None:
    """Register the export-modal watchdog."""

    @app.callback(
        [
            Output("export-watchdog-state", "data"),
            Output("export-generate-btn", "disabled", allow_duplicate=True),
            Output("export-cancel-btn", "disabled", allow_duplicate=True),
            Output("toast-message", "data", allow_duplicate=True),
        ],
        Input("update-interval", "n_intervals"),
        [
            State("export-watchdog-state", "data"),
            State("export-generate-btn", "disabled"),
            State("export-progress", "value"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def export_worker_watchdog(_n, state, generate_disabled, progress):
        running = bool(generate_disabled)
        next_state, fired = watchdog_decision(
            state=state, running=running, progress=progress,
            now=time.time(),
        )
        if fired:
            return None, False, False, {
                "type": "warning",
                "title": "Export worker not responding",
                "message": (
                    "The export has made no progress for "
                    f"{int(WATCHDOG_TIMEOUT_S / 60)} minutes -- the worker "
                    "process may have died. The buttons are re-enabled; "
                    "check free disk space and try again."
                ),
            }
        if next_state == state:
            raise PreventUpdate
        return next_state, no_update, no_update, no_update
