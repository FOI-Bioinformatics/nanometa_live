"""Start / stop analysis and output-collision handling callbacks."""

import hashlib
import json
import os
import logging
import threading
import time
from datetime import datetime
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


def register_start_stop(app, backend_manager):
    @app.callback(
        [
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("app-config", "data", allow_duplicate=True),
            Output("stop-confirm-modal", "is_open", allow_duplicate=True),
            Output("collision-modal", "is_open", allow_duplicate=True),
            Output("collision-modal-body", "children", allow_duplicate=True),
            Output("collision-decision-pending", "data", allow_duplicate=True),
            Output("backend-status", "data", allow_duplicate=True),
        ],
        Input("start-stop-button", "n_clicks"),
        State("app-config", "data"),
        State("backend-status", "data"),
        prevent_initial_call=True,
    )
    def start_or_prompt_stop(n_clicks, config, status):
        """Start analysis, prompt to stop, or warn about output collision.

        When the user clicks Start with a results dir that already
        contains nanometanf output, this callback opens the collision
        modal instead of starting the run. The actual run is then
        triggered by handle_collision_choice based on which button the
        user picks.
        """
        from nanometa_live.app.utils.config_manager import merge_config_safely
        from nanometa_live.app.components.collision_modal import (
            render_collision_body,
        )

        if not n_clicks:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update

        if status.get("running", False):
            # Open stop-confirmation modal instead of stopping directly
            return no_update, no_update, True, no_update, no_update, no_update, no_update

        if not config:
            return (
                {
                    "title": "Error",
                    "message": "No configuration loaded. Please load or configure settings first.",
                    "color": "danger",
                },
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
            )

        # Determine the results directory this run will write to. Always
        # (re)derive from the current Run name + override so that stopping a
        # run, changing the Run name, and restarting writes to a NEW folder
        # rather than reusing the previous run's directory. resolve_run_outdir
        # honours an explicit results_dir_override and otherwise derives
        # <project>/results/<run slug>; it falls back to an existing
        # results_output_directory/main_dir only for a project-less config.
        from nanometa_live.app.utils.outdir_resolution import resolve_run_outdir
        outdir = resolve_run_outdir(config) or (
            config.get("results_output_directory")
            or config.get("main_dir")
            or ""
        )
        if outdir:
            config = dict(config)
            config["results_output_directory"] = outdir
        found = backend_manager.detect_existing_results(outdir)
        if found:
            # Compare current input fingerprint with the prior run's
            # (None when no .nanometa.run.json exists yet).
            input_match = backend_manager.fingerprint_matches(outdir, config)
            # A matching input can still be screened differently: the
            # watchlist fingerprint says whether the previous run watched
            # the same organism set (finding C10).
            watchlist_match = backend_manager.watchlist_matches(outdir)
            # has_metadata is False when the folder holds result-shaped data
            # but no .nanometa.run.json -- i.e. data this app did not create.
            # Resuming over it is meaningless and risks clobbering it, so the
            # modal hides Resume and shows a distinct foreign-data warning.
            has_metadata = backend_manager.read_run_metadata(outdir) is not None
            return (
                no_update,
                no_update,
                no_update,
                True,
                render_collision_body(
                    outdir, found, input_match=input_match,
                    has_metadata=has_metadata,
                    watchlist_match=watchlist_match,
                    realtime=(config or {}).get("processing_mode") == "realtime",
                ),
                {
                    "outdir": outdir,
                    "found": found,
                    "input_match": input_match,
                    "watchlist_match": watchlist_match,
                    "has_metadata": has_metadata,
                },
                no_update,
            )

        # Clean outdir -- launch the analysis in a background thread. The
        # blocking preflight (git ls-remote, engine probes, conda-cache
        # walks) froze this click for 25-40 s; the click now returns
        # instantly with optimistic status, and surface_backend_transition
        # posts the terminal success/failure toast when the thread ends.
        if backend_manager.transition_in_progress():
            return (
                {"title": "Please wait",
                 "message": "A start or stop is already in progress.",
                 "color": "info"},
                no_update, no_update, no_update, no_update, no_update,
                no_update,
            )
        backend_manager.config = config
        success, message = backend_manager.start_async()
        color = "info" if success else "danger"

        # The derived outdir was written into `config` above; push it now so
        # the viewer follows the run directory. The full post-start config
        # merge happens in surface_backend_transition.
        updated_config = dict(config) if success else no_update

        # Optimistic backend-status update on successful launch so
        # the verdict banner flips from STANDBY to SCREENING IN
        # PROGRESS within ~30 ms instead of waiting up to one full
        # 30-second polling tick. The next real status poll
        # (update_backend_status, callbacks.py:269) will overwrite
        # this with the authoritative dict from
        # backend_manager.get_status(); on failure the poll reports
        # running=False and the banner reverts. Showing optimism on
        # click and recovering on poll beats 30 seconds of dead air.
        if success:
            optimistic_status = dict(status or {})
            optimistic_status.update({
                "running": True,
                "starting": True,
                # ISO-8601, matching BackendManager.start (which writes
                # datetime.now().isoformat()). Every reader parses this with
                # datetime.fromisoformat / Date.parse -- _format_time_elapsed,
                # toggle_waiting_banner, and the clientside elapsed-time
                # callback -- so a float epoch made all three fail closed and
                # blanked the elapsed-time display until the next status poll.
                "start_time": datetime.now().isoformat(),
                "pipeline_status": "starting",
            })
        else:
            optimistic_status = no_update

        return (
            {
                "title": "Starting Analysis" if success else "Error",
                "message": message,
                "color": color,
                # Explicit navigation intent, so switch_to_results_tab does
                # not have to string-match a (locale-sensitive) title.
                "navigate_to": "dashboard-tab" if success else None,
            },
            updated_config,
            no_update,
            no_update,
            no_update,
            no_update,
            optimistic_status,
        )

    @app.callback(
        Output("collision-resume-btn", "style"),
        Input("collision-decision-pending", "data"),
        prevent_initial_call=True,
    )
    def toggle_collision_resume_button(pending):
        """Hide the Resume button when the existing folder is foreign data
        (no .nanometa.run.json) -- resuming over it is disallowed."""
        if pending and not pending.get("has_metadata", True):
            return {"display": "none"}
        return {}

    @app.callback(
        [
            Output("collision-modal", "is_open", allow_duplicate=True),
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("app-config", "data", allow_duplicate=True),
            Output("backend-status", "data", allow_duplicate=True),
        ],
        [
            Input("collision-archive-btn", "n_clicks"),
            Input("collision-resume-btn", "n_clicks"),
            Input("collision-cancel-btn", "n_clicks"),
        ],
        [
            State("collision-decision-pending", "data"),
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_collision_choice(
        archive_clicks, resume_clicks, cancel_clicks, pending, config, status
    ):
        """Dispatch the collision modal's three buttons.

        Cancel just closes the modal with an info toast. Archive moves
        existing result subdirs into a timestamped subfolder and starts
        a fresh run. Continue runs the pipeline with -resume so
        Nextflow reuses cached work where it can.
        """
        from nanometa_live.app.utils.config_manager import merge_config_safely

        triggered = dash.ctx.triggered_id
        if not triggered:
            raise PreventUpdate

        outdir = (pending or {}).get("outdir", "")

        if triggered == "collision-cancel-btn":
            return (
                False,
                {
                    "title": "Run cancelled",
                    "message": (
                        "Update the Nanometa Live Results Folder (output) in the "
                        "Configuration tab and try again."
                    ),
                    "color": "info",
                },
                no_update,
                no_update,
            )

        # The same transition guard every other start path has (round 3):
        # without it a double-click on Archive ran
        # archive_existing_results TWICE -- two timestamped folders,
        # results split -- before the second start_async was refused.
        if backend_manager.transition_in_progress():
            return (
                False,
                {
                    "title": "Already in progress",
                    "message": "A start or stop is already in progress.",
                    "color": "warning",
                },
                no_update,
                no_update,
            )

        # Both Archive and Resume need to actually start the pipeline.
        if not config:
            return (
                False,
                {
                    "title": "Error",
                    "message": "No configuration loaded.",
                    "color": "danger",
                },
                no_update,
                no_update,
            )

        # Resolve the run directory exactly as the first-Start handler does.
        # The collision path used to take the app-config State as is; a tab
        # whose Store never carried a results_output_directory (H34) then
        # launched with an empty one and nanometanf fell back to a fresh
        # ~/.nanometa/data/analysis_<ts>, while this modal had just promised
        # to continue in `outdir` (round-4 audit, H33, observed live).
        from nanometa_live.app.utils.outdir_resolution import resolve_run_outdir
        resolved = resolve_run_outdir(config) or outdir or ""
        if not resolved:
            return (
                False,
                {
                    "title": "Results folder unknown",
                    "message": (
                        "Could not determine the results folder for this run. "
                        "Set the Run name or the Results folder in the "
                        "Configuration tab and try again."
                    ),
                    "color": "danger",
                },
                no_update,
                no_update,
            )
        if outdir and os.path.abspath(resolved) != os.path.abspath(outdir):
            logging.warning(
                "Collision decision: resolved run dir %s differs from the "
                "directory the modal described (%s); using the described one",
                resolved, outdir,
            )
            resolved = outdir
        config = dict(config)
        config["results_output_directory"] = resolved
        backend_manager.config = config

        if triggered == "collision-archive-btn":
            try:
                archive_path = backend_manager.archive_existing_results(outdir)
            except OSError as e:
                logging.error(f"archive_existing_results failed: {e}")
                return (
                    False,
                    {
                        "title": "Archive failed",
                        "message": str(e),
                        "color": "danger",
                    },
                    no_update,
                    no_update,
                )
            success, message = backend_manager.start_async(resume=False)
            if success and archive_path:
                message = (
                    f"{message}\nPrevious results archived to "
                    f"{archive_path}"
                )
        elif triggered == "collision-resume-btn":
            # Refuse to resume over foreign data even if the button is
            # somehow reachable: the Resume button is hidden in that case,
            # but guard server-side so a stale/forced click cannot clobber
            # data Nanometa Live did not create.
            if not (pending or {}).get("has_metadata", True):
                return (
                    False,
                    {
                        "title": "Resume not allowed",
                        "message": (
                            "This folder has no Nanometa Live run record, so "
                            "resuming could clobber unrelated data. Choose "
                            "'Move existing & start fresh' or cancel."
                        ),
                        "color": "danger",
                    },
                    no_update,
                    no_update,
                )
            success, message = backend_manager.start_async(resume=True)
        else:
            raise PreventUpdate

        color = "info" if success else "danger"
        if success:
            # Terminal toast + full config merge arrive via
            # surface_backend_transition when the start thread finishes.
            updated_config = dict(config)
            # Optimistic backend-status update -- see start_or_prompt_stop
            # for the rationale. Without this the verdict banner sits
            # at STANDBY for up to one polling tick after the operator
            # picks Archive or Continue from the collision modal.
            optimistic_status = dict(status or {})
            optimistic_status.update({
                "running": True,
                "starting": True,
                # ISO-8601 -- see start_or_prompt_stop for why a float epoch
                # is wrong here.
                "start_time": datetime.now().isoformat(),
                "pipeline_status": "starting",
            })
        else:
            updated_config = no_update
            optimistic_status = no_update

        return (
            False,
            {
                "title": "Starting Analysis" if success else "Error",
                "message": message,
                "color": color,
                # Explicit navigation intent (see switch_to_results_tab).
                "navigate_to": "dashboard-tab" if success else None,
            },
            updated_config,
            optimistic_status,
        )

    @app.callback(
        [
            Output("stop-confirm-modal", "is_open"),
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("user-stop-requested", "data", allow_duplicate=True),
        ],
        [
            Input("confirm-stop-analysis", "n_clicks"),
            Input("cancel-stop-analysis", "n_clicks"),
        ],
        State("stop-confirm-modal", "is_open"),
        prevent_initial_call=True,
    )
    def handle_stop_confirmation(confirm_clicks, cancel_clicks, is_open):
        """Handle stop confirmation modal buttons.

        A successful stop also raises the ``user-stop-requested`` flag. The
        running -> not-running transition is otherwise indistinguishable from a
        natural finish, and auto_navigate_on_completion announced an operator
        abort as "has finished. Results are up to date." The flag rides a
        dedicated Store rather than backend-status because the next status poll
        overwrites backend-status wholesale from BackendManager.get_status().
        """
        if not is_open:
            return no_update, no_update, no_update

        triggered = dash.ctx.triggered_id
        if triggered == "confirm-stop-analysis" and confirm_clicks:
            # Non-blocking: stop() waits on the process for up to 30+ s.
            # The stop-requested flag is raised on the REQUEST (it only
            # affects completion-toast wording, and the operator did ask);
            # the terminal stop result arrives via
            # surface_backend_transition.
            success, message = backend_manager.stop_async()
            color = "info" if success else "danger"
            return False, {
                "title": "Stopping Analysis" if success else "Error",
                "message": message
                if not success
                else "Stopping the pipeline; this can take up to 30 "
                     "seconds. A toast will confirm when it has stopped.",
                "color": color,
            }, (True if success else no_update)
        elif triggered == "cancel-stop-analysis" and cancel_clicks:
            return False, no_update, no_update

        return no_update, no_update, no_update

    @app.callback(
        [
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("app-config", "data", allow_duplicate=True),
        ],
        Input("backend-status", "data"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def surface_backend_transition(_status, config):
        """Post the terminal toast for an async start/stop, exactly once.

        The click callbacks return instantly with an optimistic "Starting/
        Stopping..." toast; the daemon thread's real outcome -- including a
        preflight FAILURE, which must never be silent -- is picked up here
        on the next status tick. A successful start also merges the
        backend's post-start config (run metadata paths etc.) into the
        app-config Store, which the synchronous path used to do inline.
        """
        result = backend_manager.consume_transition_result()
        if not result:
            raise PreventUpdate

        from nanometa_live.app.utils.config_manager import merge_config_safely

        if result["kind"] == "start":
            if result["success"]:
                updated_config = merge_config_safely(
                    config or {}, backend_manager.config or {})
                return {
                    "title": "Analysis Started",
                    "message": result["message"],
                    "color": "success",
                    "navigate_to": "dashboard-tab",
                }, updated_config
            return {
                "title": "Start failed",
                "message": result["message"],
                "color": "danger",
            }, no_update

        return {
            "title": "Analysis Stopped" if result["success"] else
                     "Stop failed",
            "message": result["message"],
            "color": "success" if result["success"] else "danger",
        }, no_update

    @app.callback(
        Output("tabs", "active_tab"),
        Input("notification-trigger", "data"),
        State("tabs", "active_tab"),
        prevent_initial_call=True,
    )
    def switch_to_results_tab(notification, current_tab):
        """Switch to the Dashboard tab after starting analysis.

        Keys on the explicit ``navigate_to`` field set by the start
        callbacks rather than matching the notification title string, which
        was locale-sensitive and would fire for any unrelated toast that
        happened to use the same title/color.
        """
        if not notification or not isinstance(notification, dict):
            return no_update

        target = notification.get("navigate_to")
        if target:
            return target

        return no_update

    # ========================================================================
    # Readiness Indicator
    # ========================================================================
