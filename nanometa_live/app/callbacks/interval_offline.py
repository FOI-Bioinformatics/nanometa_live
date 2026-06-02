"""Update-interval cadence and offline-mode callbacks."""

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


def register_interval_offline(app, backend_manager):

    @app.callback(
        Output("update-interval", "interval"),
        Input("app-config", "data"),
        Input("backend-status", "data"),
    )
    def update_interval(config, status):
        """Adaptive poll cadence.

        Poll at the configured ``update_interval_seconds`` while a run is
        active (or just starting), and back off to
        ``idle_update_interval_seconds`` when nothing is running -- complete,
        standby, or viewing existing results. Combined with the
        fingerprint-gated callbacks (idle ticks are no-ops) and the
        hidden-tab pause, this keeps the server quiet between runs while
        staying responsive during one. Changing the interval restarts the
        timer, so a Start (which optimistically flips backend-status to
        running) speeds polling up almost immediately.
        """
        config = config or {}
        active = bool(status and (status.get("running") or status.get("starting")))
        base = config.get("update_interval_seconds", 10)
        if active:
            return int(base) * 1000
        idle = config.get("idle_update_interval_seconds") or max(int(base), 60)
        return int(idle) * 1000

    # ========================================================================
    # Offline Mode Badge
    # ========================================================================

    @app.callback(
        Output("offline-mode-badge", "style"),
        Output("offline-mode-toggle", "value"),
        Input("app-config", "data"),
    )
    def toggle_offline_badge(config):
        """Show or hide the OFFLINE badge and keep the header toggle in sync
        with the config (covers boot and any non-toggle writer of the flag)."""
        offline = bool(config and config.get("offline_mode"))
        style = {"fontSize": "0.7rem"} if offline else {"display": "none", "fontSize": "0.7rem"}
        return style, offline

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Output("toast-message", "data", allow_duplicate=True),
        Input("offline-mode-toggle", "value"),
        State("app-config", "data"),
        State("app-data-dir", "data"),
        prevent_initial_call=True,
    )
    def set_offline_mode(offline, config, data_dir):
        """Flip offline mode live from the header toggle.

        Re-initialises the NCBI/GTDB/cache/genome singletons immediately (no
        restart needed), persists the flag into last-session.yaml so it
        survives a relaunch, and updates the app-config store (which drives
        the OFFLINE badge). No-op when the toggle already matches config, so
        the badge-sync callback above does not ping-pong with this one."""
        offline = bool(offline)
        config = dict(config or {})
        if bool(config.get("offline_mode", False)) == offline:
            raise PreventUpdate
        config["offline_mode"] = offline

        # Live propagation: reconfigure the API/genome singletons in-process.
        try:
            from nanometa_live.app.app import _init_offline_mode
            _init_offline_mode(offline, config.get("genome_cache_dir"))
        except Exception as e:  # pragma: no cover - defensive
            log_callback_error("set_offline_mode/_init_offline_mode", e)

        # Persist just this flag so it survives a relaunch, without forcing a
        # full Apply Settings. Merge into the existing last-session.yaml
        # (project-local via NanometaPaths).
        try:
            from nanometa_live.core.config.config_loader import ConfigLoader
            from nanometa_live.core.utils.paths import NanometaPaths
            configs_dir = str(NanometaPaths.from_config(config).configs)
            loader = ConfigLoader(configs_dir)
            existing = {}
            session_path = os.path.join(configs_dir, "last-session.yaml")
            if os.path.exists(session_path):
                try:
                    existing = loader.load_config(session_path)
                except Exception:
                    existing = {}
            existing["offline_mode"] = offline
            loader.save_config(existing, "last-session.yaml")
        except Exception as e:  # pragma: no cover - defensive
            log_callback_error("set_offline_mode/persist", e)

        return config, {
            "type": "info",
            "title": "Offline mode " + ("enabled" if offline else "disabled"),
            "message": (
                "Network calls are now disabled; using local caches only."
                if offline
                else "Network calls are now allowed (NCBI/GTDB/GitHub)."
            ),
        }
