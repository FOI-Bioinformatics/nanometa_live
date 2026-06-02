"""Backend status, results-fingerprint, status display and control-button callbacks."""

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


def register_status(app, backend_manager):
    @app.callback(
        Output("backend-status", "data"), Input("update-interval", "n_intervals")
    )
    def update_backend_status(_):
        """Update the backend status."""
        return backend_manager.get_status()

    @app.callback(
        Output("results-fingerprint", "data"),
        Input("update-interval", "n_intervals"),
        # app-config is an Input (not just State) so that pointing the app at a
        # new results folder via Open Results or Apply Settings rescans
        # immediately instead of waiting for the next interval tick.
        Input("app-config", "data"),
        State("results-fingerprint", "data"),
    )
    def compute_results_fingerprint(_n_intervals, config, prev):
        """
        Scan the nanometanf output directories and emit a fingerprint
        update only when at least one of them has changed.

        Data-bound callbacks consume this Store as their Input instead of
        ``update-interval``. PreventUpdate on an unchanged fingerprint
        means downstream callbacks do not run, so unchanged ticks become
        zero-cost. The gate itself is four ``os.scandir`` calls plus an
        MD5 -- microseconds at any realistic dataset size.
        """
        if not config:
            raise PreventUpdate
        main_dir = resolve_outdir_for_fingerprint(config)
        if not main_dir:
            raise PreventUpdate

        try:
            fp = check_data_freshness(main_dir)
        except Exception as e:
            log_callback_error("compute_results_fingerprint", e)
            raise PreventUpdate

        # U4: sticky 'first batch arrived' flag. Once any tracked
        # subdirectory holds a non-empty file we leave the flag set for
        # the remainder of the run; downstream callbacks use it to hide
        # the waiting banner without re-checking the filesystem.
        from nanometa_live.app.utils.first_batch import first_batch_seen
        prev_seen = bool((prev or {}).get("first_batch_seen", False))
        if prev_seen:
            seen = True
        else:
            try:
                seen = first_batch_seen(main_dir)
            except Exception:
                seen = False

        if fp == (prev or {}).get("fp") and seen == prev_seen:
            raise PreventUpdate
        return {"fp": fp, "ts": time.time(), "first_batch_seen": seen}

    @app.callback(
        [
            Output("status-indicator", "color"),
            Output("status-text", "children"),
            Output("status-details", "children"),
        ],
        Input("backend-status", "data"),
        Input("app-config", "data"),
    )
    def update_status_display(status, config):
        """Update the status display based on backend status."""
        if not status:
            return "gray", "STANDBY", "Unable to determine backend status"

        # Check if in visualization-only mode
        if config and config.get("visualization_only", False):
            return "blue", "VIEWING", "Visualization mode - displaying existing results"

        if status.get("running", False):
            color = "green"
            text = "RUNNING"

            # Cap files_processed against the inbox size only in batch
            # mode. In realtime mode the inbox grows during the run via
            # watchPath, so files_waiting is a moving snapshot rather
            # than a fixed total -- clamping there undercounts processed
            # files while streaming.
            total_files = status.get("files_waiting", 0)
            raw_processed = status.get("files_processed", 0)
            processing_mode = (config or {}).get("processing_mode", "batch")
            if processing_mode == "realtime":
                files_processed = raw_processed
            else:
                files_processed = min(raw_processed, total_files) if total_files > 0 else raw_processed

            details = [
                f"Files processed: {files_processed} / {total_files}",
            ]

            if status.get("last_update"):
                timestamp = time.strftime(
                    "%H:%M:%S", time.localtime(status.get("last_update"))
                )
                details.append(f"Last update: {timestamp}")

            return color, text, ", ".join(details)

        if status.get("pipeline_status") == "error":
            return "red", "ERROR", ", ".join(status.get("errors", ["Unknown error"]))

        if status.get("pipeline_status") == "completed":
            return "blue", "Complete", "Pipeline finished successfully"

        return "gray", "STANDBY", "Click 'Start Analysis' to begin processing"

    @app.callback(
        [
            Output("start-stop-button", "children"),
            Output("start-stop-button", "color"),
            Output("start-stop-button", "disabled"),
        ],
        Input("backend-status", "data"),
        Input("app-config", "data"),
        Input("readiness-state", "data"),
    )
    def update_control_button(status, config, readiness):
        """Update the start/stop button based on backend status and readiness."""
        if not status or not config:
            return "Start Analysis", "primary", True

        # Disable control buttons in visualization-only mode
        if config.get("visualization_only", False):
            return "Start Analysis", "secondary", True

        if status.get("running", False):
            return [
                dbc.Spinner(size="sm", spinner_class_name="me-2"),
                "Stop Analysis"
            ], "danger", False

        # Gate on readiness checks
        is_ready = readiness.get("ready", False) if readiness else False
        return "Start Analysis", "primary", not is_ready

    @app.callback(
        Output("start-analysis-tooltip", "children"),
        Input("app-config", "data"),
        Input("backend-status", "data"),
    )
    def update_start_tooltip(config, status):
        """Update Start/Stop button tooltip based on mode and state."""
        if config and config.get("visualization_only", False):
            return "Not available in visualization mode - displaying existing results only"
        if status and status.get("running", False):
            return "Stop the running analysis pipeline"
        return "Begin processing the nanopore sequence data"

    @app.callback(
        Output("header-title", "children"),
        Input("app-config", "data")
    )
    def update_header_title(config):
        """Update the header title based on the analysis name in config."""
        if config and "analysis_name" in config and config["analysis_name"]:
            return config["analysis_name"]
        return "Nanometa Live Analysis"

    # NOTE: the former show_notification callback (which rendered the
    # notification-trigger channel into a separate header notification-container)
    # has been folded into the single display_toast renderer below, so there is
    # one notification UI instead of two. notification-trigger is still written
    # by ~14 call sites and read for navigation by switch_to_results_tab; only
    # its rendering moved.
