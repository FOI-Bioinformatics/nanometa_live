"""Live indicator, stale-data warning, last-update tracking and toast renderer."""

import hashlib
import json
import os
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

import dash
from dash import ALL, Dash, Input, Output, State, callback, dcc, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.utils.sample_detector import get_available_samples, get_sample_file_mapping
from nanometa_live.core.utils.loader_utils import check_data_freshness
from nanometa_live.app.utils.callback_helpers import log_callback_error
from nanometa_live.app.utils.outdir_resolution import resolve_outdir_for_fingerprint
from nanometa_live.app.utils.debounce import (
    should_skip_update, get_trigger_type,
    interval_render_is_redundant, mark_rendered,
)
from nanometa_live.app.app import background_callback_manager

# Maximum number of notification / toast nodes kept in the DOM. Older
# entries are dropped so a long real-time session that emits repeated
# notifications does not accumulate an unbounded list in the store.
_MAX_NOTIFICATIONS = 10

# Coalesce identical toasts fired in quick succession into one. A per-entry
# loop (e.g. genome/taxid preparation iterating watchlist entries) can write
# the same "Validated x/x" message to the store many times in a burst; without
# this the operator gets a wall of duplicate pop-ups. Distinct messages are
# unaffected. Process-local; the GUI runs the toast renderer in the main process.
_TOAST_DEDUP_WINDOW_S = 5.0
_toast_dedup: Dict[str, Any] = {"sig": None, "ts": 0.0}

# The legacy notification-trigger channel labels severity with a Bootstrap
# "color"; the toast channel uses "type". This maps the former onto the
# latter so both feed the single unified toast renderer.
_COLOR_TO_TOAST_TYPE = {
    "success": "success",
    "danger": "danger",
    "warning": "warning",
    "info": "info",
    "primary": "info",
    "secondary": "info",
}

# Icon class per toast severity.
_TOAST_ICON_MAP = {
    "success": "bi-check-circle-fill text-success",
    "warning": "bi-exclamation-triangle-fill text-warning",
    "danger": "bi-x-circle-fill text-danger",
    "info": "bi-info-circle-fill text-info",
}


def _toast_is_duplicate(sig) -> bool:
    """True if *sig* repeats a recent toast within the dedup window.

    Updates the dedup state's timestamp on a match so a sustained burst keeps
    coalescing; records the new signature otherwise.
    """
    now = time.time()
    if (sig == _toast_dedup["sig"]
            and (now - _toast_dedup["ts"]) < _TOAST_DEDUP_WINDOW_S):
        _toast_dedup["ts"] = now
        return True
    _toast_dedup["sig"] = sig
    _toast_dedup["ts"] = now
    return False


def _build_toast_node(toast_type: str, title: str, message: str):
    """Build a single floating-notification DOM node."""
    from dash import html

    icon_class = _TOAST_ICON_MAP.get(toast_type, _TOAST_ICON_MAP["info"])
    return html.Div(
        className=f"toast-notification toast-{toast_type}",
        children=[
            html.I(className=f"bi {icon_class} toast-icon"),
            html.Div(
                className="toast-content",
                children=[
                    html.Div(title, className="toast-title"),
                    html.Div(message, className="toast-message") if message else None,
                ]
            ),
            html.Button(
                html.I(className="bi bi-x"),
                className="toast-close",
                n_clicks=0,
                # Use inline onclick to remove parent toast element
                **{"data-dismiss": "toast", "aria-label": "Dismiss notification"}
            )
        ],
        id=f"toast-{int(time.time()*1000)}"
    )


def register_indicators(app, backend_manager):
    @app.callback(
        [
            Output("live-indicator-dot", "className"),
            Output("live-indicator-text", "children"),
            Output("last-update-display", "children"),
        ],
        [
            Input("backend-status", "data"),
            Input("results-fingerprint", "data"),
        ],
        State("app-config", "data"),
    )
    def update_live_indicator(status, fingerprint, config):
        """
        Update the live indicator in the header.

        The displayed timestamp reflects the last time the results
        fingerprint advanced (i.e. real data arrived), not the wall
        clock of the polling tick. When the configured outdir exists
        but no data has arrived yet, render "no data yet" instead of
        a misleading current-time stamp.
        """
        fp_ts = (fingerprint or {}).get("ts") if isinstance(fingerprint, dict) else None
        if fp_ts:
            data_time = time.strftime("%H:%M:%S", time.localtime(fp_ts))
        else:
            data_time = None

        # Check if in visualization-only mode
        if config and config.get("visualization_only", False):
            label = f"Last data: {data_time}" if data_time else "no data yet"
            return (
                "live-indicator-dot offline",
                "View Only",
                label,
            )

        # Check backend status
        if status and status.get("running", False):
            label = f"Updated: {data_time}" if data_time else "no data yet"
            return (
                "live-indicator-dot",  # Animated pulse
                "LIVE",
                label,
            )
        elif status and status.get("completed", False):
            label = f"Finished: {data_time}" if data_time else "no data yet"
            return (
                "live-indicator-dot offline",
                "Complete",
                label,
            )
        else:
            label = f"Last data: {data_time}" if data_time else "no data yet"
            return (
                "live-indicator-dot offline",
                "Standby",
                label,
            )

    # ========================================================================
    # Stale Data Indicator Callback
    # ========================================================================

    @app.callback(
        Output("stale-data-warning", "style"),
        [
            Input("update-interval", "n_intervals"),
            Input("last-update-time", "data"),
        ],
        State("app-config", "data"),
    )
    def update_stale_data_warning(n_intervals, last_update_time, config):
        """
        Show a warning if data hasn't been updated within expected timeframe.

        Data is considered stale if no update has occurred within 2x the
        configured update interval.
        """
        import datetime

        if not config:
            return {"display": "none"}

        try:
            update_interval = config.get("update_interval_seconds", 10)
            stale_threshold = update_interval * 2  # 2x the interval

            if last_update_time:
                # Calculate time since last update
                last_update = datetime.datetime.fromisoformat(last_update_time)
                time_since_update = (datetime.datetime.now() - last_update).total_seconds()

                if time_since_update > stale_threshold:
                    return {"display": "flex"}

            return {"display": "none"}

        except Exception as e:
            log_callback_error("check_stale_data", e, level=logging.WARNING)
            return {"display": "none"}

    @app.callback(
        Output("last-update-time", "data"),
        Input("results-fingerprint", "data"),
        State("app-config", "data"),
    )
    def track_last_update_time(fingerprint, config):
        """Track when results last changed.

        Driven by ``results-fingerprint`` rather than the wall-clock
        polling tick: the fingerprint store only emits a new value
        when at least one output file changed. The companion stale
        warning callback can therefore actually fire when data goes
        quiet -- previously this restamped every tick and the warning
        was unreachable.
        """
        import datetime

        if not config:
            return None

        try:
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
            if main_dir and os.path.exists(main_dir):
                # Stamp at fingerprint-change time.
                return datetime.datetime.now().isoformat()
            return None
        except Exception as e:
            log_callback_error("track_last_update_time", e, level=logging.WARNING)
            return None

    # ========================================================================
    # Toast Notification Callback
    # ========================================================================

    @app.callback(
        Output("toast-container", "children"),
        [
            Input("toast-message", "data"),
            Input("notification-trigger", "data"),
        ],
        State("toast-container", "children"),
    )
    def display_toast(toast_data, notification_data, current_toasts):
        """
        Unified floating-notification renderer.

        Both notification channels feed this single container so there is one
        notification UI rather than two:
          - toast-message:        {"type", "title", "message"}
          - notification-trigger: {"title", "message", "color"[, "navigate_to"]}
        The legacy "color" field is normalized to a toast "type". (The
        navigate_to field on notification-trigger is consumed separately by
        switch_to_results_tab; it is ignored here.)
        """
        # Pick the payload from whichever store actually fired.
        payload = toast_data if dash.ctx.triggered_id == "toast-message" else notification_data

        if not payload or not isinstance(payload, dict):
            return current_toasts or []

        if current_toasts is None:
            current_toasts = []

        try:
            # toast-message uses "type"; notification-trigger uses "color".
            toast_type = payload.get("type") or _COLOR_TO_TOAST_TYPE.get(
                payload.get("color", "info"), "info"
            )
            title = payload.get("title", "Notification")
            message = payload.get("message", "")

            # Coalesce a burst of identical toasts (e.g. a per-entry prep loop
            # writing the same "Validated x/x" message repeatedly) into one.
            if _toast_is_duplicate((toast_type, title, message)):
                return current_toasts or []

            new_toast = _build_toast_node(toast_type, title, message)

            # Auto-remove after 4 seconds (handled by CSS animation).
            # Cap the list so repeated toasts over a long session do not
            # grow the DOM without bound.
            return (current_toasts + [new_toast])[-_MAX_NOTIFICATIONS:]

        except Exception as e:
            log_callback_error("display_toast", e)
            return current_toasts or []

    # ========================================================================
    # Theme Toggle Callback (Client-side for immediate response)
    # ========================================================================

    app.clientside_callback(
        """
        function(n_clicks, currentTheme) {
            if (!n_clicks) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }

            // Cycle through themes: auto -> dark -> light -> auto
            let newTheme;
            let iconClass;

            if (currentTheme === 'auto' || !currentTheme) {
                newTheme = 'dark';
                iconClass = 'bi bi-sun';
                document.documentElement.setAttribute('data-theme', 'dark');
            } else if (currentTheme === 'dark') {
                newTheme = 'light';
                iconClass = 'bi bi-moon-stars';
                document.documentElement.setAttribute('data-theme', 'light');
            } else {
                newTheme = 'auto';
                iconClass = 'bi bi-circle-half';
                document.documentElement.removeAttribute('data-theme');
            }

            return [newTheme, iconClass];
        }
        """,
        [
            Output("theme-preference", "data"),
            Output("theme-icon", "className"),
        ],
        Input("theme-toggle", "n_clicks"),
        State("theme-preference", "data"),
    )

    # ========================================================================
    # Timer and Progress Display Callbacks
    # ========================================================================

    # update_elapsed_time was a 1 Hz server callback. It is now a
    # clientside callback registered in app.register_callbacks; the
    # browser computes elapsed time directly from backend_status.start_time
    # using Date.now(), which removes one Flask round-trip per second
    # for the lifetime of the session.
