"""Pipeline-stage display, analyze-error toast and auto-navigation-on-completion."""

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


def register_progress(app, backend_manager):
    @app.callback(
        [
            Output("current-pipeline-stage", "children"),
            Output("pipeline-progress-text", "children"),
            Output("pipeline-stage-container", "style"),
        ],
        Input("backend-status", "data"),
    )
    def update_pipeline_stage_display(status):
        """
        Update the pipeline stage display in the header.

        Shows the current stage name and process counts when pipeline is running.
        """
        from dash import html

        if not status or not status.get("running"):
            return "", "", {"display": "none"}

        current_stage = status.get("current_stage", "")
        if not current_stage:
            # Check if we have any process info even without a current stage
            completed = status.get("processes_complete", 0)
            running = status.get("processes_running", 0)
            if completed > 0 or running > 0:
                current_stage = "Processing"
            else:
                return "", "", {"display": "none"}

        # Build progress text
        completed = status.get("processes_complete", 0)
        running = status.get("processes_running", 0)
        failed = status.get("processes_failed", 0)
        total = completed + running + failed

        if total > 0:
            progress_text = f"({completed}/{total} processes)"
            if running > 0:
                progress_text = f"({completed}/{total}, {running} active)"
        else:
            progress_text = ""

        stage_display = html.Span([
            html.I(className="bi bi-gear-fill me-1 text-primary spinning"),
            current_stage
        ])

        return stage_display, progress_text, {"display": "flex", "alignItems": "center"}

    # ========================================================================
    # Auto-Navigation on Analysis Completion
    # ========================================================================

    # Track the last error string we surfaced to avoid re-toasting
    # the same message on every status poll. Status writes are
    # serialised in BackendManager so this dict-of-one is sufficient.
    _last_analyze_error = {"text": None}

    @app.callback(
        Output("toast-message", "data", allow_duplicate=True),
        Input("backend-status", "data"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def emit_analyze_error_toast(status, config):
        """Surface pipeline errors as a toast that names the path the
        Kraken2 loader scanned and the glob patterns it tried.

        The previous experience was a generic ``Pipeline encountered
        errors`` message in the status bar; the operator had no way to
        tell whether the failure was at launch, mid-pipeline, or in
        the dashboard's loader. Naming the absolute path and the glob
        patterns turns a 'where did it look?' question into something
        the operator can verify with ``ls``.
        """
        if not status or status.get("pipeline_status") != "error":
            return no_update
        errors = status.get("errors") or []
        if not errors:
            return no_update
        error_text = "; ".join(errors)
        if error_text == _last_analyze_error["text"]:
            return no_update
        _last_analyze_error["text"] = error_text

        main_dir = ""
        if config:
            main_dir = (
                config.get("results_output_directory")
                or config.get("main_dir")
                or ""
            )

        try:
            from nanometa_live.core.utils.classification_loaders import (
                describe_kraken_scan_locations,
            )
            scan = describe_kraken_scan_locations(main_dir)
        except Exception:
            scan = {"kraken_dir": "", "exists": False, "patterns": []}

        kraken_dir = scan.get("kraken_dir") or "(results directory not configured)"
        exists_label = (
            "(directory present)" if scan.get("exists") else "(directory missing)"
        )
        patterns = scan.get("patterns") or []
        patterns_text = ", ".join(patterns) if patterns else "(none)"

        message = (
            f"{error_text}\n\n"
            f"Loader scan path: {kraken_dir} {exists_label}\n"
            f"Glob patterns tried: {patterns_text}"
        )
        return {
            "type": "error",
            "title": "Analysis error",
            "message": message,
        }

    @app.callback(
        [
            Output("tabs", "active_tab", allow_duplicate=True),
            Output("previous-running-state", "data"),
            Output("toast-message", "data", allow_duplicate=True),
        ],
        Input("backend-status", "data"),
        [
            State("previous-running-state", "data"),
            State("tabs", "active_tab"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def auto_navigate_on_completion(status, prev_running, current_tab, config):
        """
        Auto-navigate to Dashboard tab when analysis completes.

        Detects when backend transitions from running to not running,
        and switches to the Dashboard tab to show results.
        """
        if not status:
            return no_update, False, no_update

        is_running = bool(status.get("running", False))

        # Store current state for next comparison
        new_prev_state = is_running

        # Detect completion: was running, now not running
        # Use explicit bool() to guard against truthy non-boolean values in the store
        if bool(prev_running) and not is_running:
            # Analysis just completed - navigate to dashboard
            # Only if not already on dashboard
            if current_tab != "dashboard-tab":
                analysis_name = config.get("analysis_name", "Analysis") if config else "Analysis"
                toast_msg = {
                    "type": "success",
                    "title": "Analysis Complete",
                    "message": f"{analysis_name} has finished. Viewing results on Dashboard.",
                }
                return "dashboard-tab", new_prev_state, toast_msg
            else:
                # Already on dashboard, just show toast
                toast_msg = {
                    "type": "success",
                    "title": "Analysis Complete",
                    "message": "Results are now available.",
                }
                return no_update, new_prev_state, toast_msg

        # No navigation needed. Only write the tracker store when the
        # running flag actually changed (e.g. transition into running);
        # writing an unchanged value on every backend-status poll would
        # mark the store dirty and re-fire downstream subscribers each tick.
        if new_prev_state == bool(prev_running):
            return no_update, no_update, no_update
        return no_update, new_prev_state, no_update

    # ========================================================================
    # Welcome Modal (first-run onboarding)
    # ========================================================================
