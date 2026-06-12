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


# Tabs that show analysis results. Completion should NOT yank the operator off
# one of these (they may be mid-investigation); it only auto-navigates from a
# Setup tab. Kept module-level so it is unit-testable and shared.
RESULTS_TABS = frozenset({
    "dashboard-tab", "main-tab", "qc-tab", "classification-tab", "validation-tab",
})


def _format_process_progress(completed: int, running: int, failed: int) -> str:
    """Format the header process-progress string.

    Shows the cumulative completed count and, when relevant, how many processes
    are active or have failed right now. Avoids the old ``completed/total`` form
    that read as ``N/N`` (total == completed+running+failed, usually with
    running==0 at the poll), which looked like "done out of done".
    """
    if completed <= 0 and running <= 0 and failed <= 0:
        return ""
    parts = [f"{completed} done"]
    if running > 0:
        parts.append(f"{running} active")
    if failed > 0:
        parts.append(f"{failed} failed")
    return "(" + " · ".join(parts) + ")"


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

        # Build progress text. Avoid the old "completed/total" form: total was
        # completed+running+failed, so at most poll snapshots (running==0) it
        # read "N/N", looking like "done out of done" while both grew. Show the
        # completed count plus how many are active/failed right now instead.
        completed = status.get("processes_complete", 0)
        running = status.get("processes_running", 0)
        failed = status.get("processes_failed", 0)
        progress_text = _format_process_progress(completed, running, failed)

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
        except Exception as e:
            logging.debug("describe_kraken_scan_locations(%s) failed: %s", main_dir, e)
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
        Navigate to the Dashboard when analysis completes -- but only if the
        operator is on a Setup tab.

        Detects the running -> not-running transition. If the operator is
        already viewing a results tab (Dashboard/Organisms/QC/Taxonomy/
        Validation) they may be mid-investigation, so we leave their tab
        untouched and only show the completion toast. Switching focus out from
        under them was a reported annoyance.
        """
        if not status:
            return no_update, False, no_update

        is_running = bool(status.get("running", False))

        # Store current state for next comparison
        new_prev_state = is_running

        # Detect completion: was running, now not running
        # Use explicit bool() to guard against truthy non-boolean values in the store
        if bool(prev_running) and not is_running:
            analysis_name = config.get("analysis_name", "Analysis") if config else "Analysis"
            # Stay put when already viewing results; only pull the operator to
            # the Dashboard from a Setup tab (config/watchlist/deployment).
            if current_tab in RESULTS_TABS:
                toast_msg = {
                    "type": "success",
                    "title": "Analysis Complete",
                    "message": f"{analysis_name} has finished. Results are up to date.",
                }
                return no_update, new_prev_state, toast_msg
            toast_msg = {
                "type": "success",
                "title": "Analysis Complete",
                "message": f"{analysis_name} has finished. Viewing results on Dashboard.",
            }
            return "dashboard-tab", new_prev_state, toast_msg

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
