"""
Core callbacks for the Nanometa Live application.

This module contains the core callbacks that are used across multiple tabs
and components of the application.
"""

import hashlib
import json
import os
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from dash import Dash, Input, Output, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.utils.sample_detector import get_available_samples, get_sample_file_mapping
from nanometa_live.core.utils.loader_utils import check_data_freshness
from nanometa_live.app.utils.callback_helpers import log_callback_error


# update_readiness_indicator runs the full ReadinessChecker every
# update-interval tick. Each invocation does ~7 shutil.which calls plus
# os.stat / glob over the configured Kraken2 DB and BLAST DB directories,
# i.e. 10+ syscalls every 30 s for a state that almost never changes.
# This module-level cache reuses a recent ReadinessReport when the
# relevant config has not changed AND less than _READINESS_TTL seconds
# have elapsed. The TTL guarantees that "operator just installed
# bowtie / dropped a Kraken2 DB into place" surfaces within 60 s.
_READINESS_TTL = 60.0
_readiness_cache: Dict[str, Tuple[float, Any]] = {}
_readiness_cache_lock = threading.Lock()


def _readiness_cache_key(config: Optional[Dict[str, Any]]) -> str:
    """Build a stable cache key from the config fields that affect readiness.

    The full config dict is not used because the dashboard mutates
    unrelated keys (UI flags, last-selected sample) on every save, which
    would invalidate the cache for no reason. Only the fields the
    readiness checks actually read are included.
    """
    if not config:
        return "no-config"
    relevant = {
        k: config.get(k) for k in (
            "kraken_db",
            "main_dir",
            "results_output_directory",
            "nanopore_output_directory",
            "pipeline_source",
            "pipeline_profile",
            "pipeline_cache_dir",
            "blast_validation",
            "network_check_enabled",
            "offline_mode",
        )
    }
    return hashlib.md5(json.dumps(relevant, sort_keys=True).encode()).hexdigest()


def register_core_callbacks(app: Dash, backend_manager: BackendManager):
    """
    Register core application callbacks.

    Args:
        app: Dash application
        backend_manager: Backend manager instance
    """

    @app.callback(Output("update-interval", "interval"), Input("app-config", "data"))
    def update_interval(config):
        """Update the interval based on configuration."""
        if config and "update_interval_seconds" in config:
            return config["update_interval_seconds"] * 1000
        return 30000  # Default 30 seconds

    # ========================================================================
    # Offline Mode Badge
    # ========================================================================

    @app.callback(
        Output("offline-mode-badge", "style"),
        Input("app-config", "data"),
    )
    def toggle_offline_badge(config):
        """Show or hide the OFFLINE badge based on config."""
        if config and config.get("offline_mode"):
            return {"fontSize": "0.7rem"}
        return {"display": "none", "fontSize": "0.7rem"}

    # ========================================================================
    # Internet Auto-Detection (startup suggestion)
    # ========================================================================

    _internet_check_lock = threading.Lock()
    _internet_checked = {"done": False}

    @app.callback(
        Output("toast-message", "data", allow_duplicate=True),
        Input("app-config", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def check_internet_on_startup(config):
        """On first load, check internet and suggest offline mode if unreachable."""
        with _internet_check_lock:
            if _internet_checked["done"]:
                return no_update
            _internet_checked["done"] = True

        if config and config.get("offline_mode"):
            return no_update
        try:
            import requests as req
            req.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi",
                timeout=3,
            ).raise_for_status()
            return no_update
        except Exception:
            return {
                "type": "warning",
                "title": "No Internet Detected",
                "message": "Consider enabling Offline Mode in Settings.",
            }

    # ========================================================================
    # Taxid Mapping Initialization (for pathogen detection)
    # ========================================================================
    # This runs once on startup to load cached taxid mappings if they exist.
    # Required for proper pathogen detection with GTDB/custom Kraken2 databases.

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Output("taxmap-collection", "data", allow_duplicate=True),
        Output("taxmap-database-info", "data", allow_duplicate=True),
        Output("taxmap-rescan-complete", "data", allow_duplicate=True),
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def initialize_taxid_mappings(_n_intervals, config):
        """
        Load cached taxid mappings on startup for proper pathogen detection.

        This callback runs once when the app-config is first set and loads
        any cached mappings for the configured Kraken2 database. This enables
        proper pathogen detection with GTDB databases where taxids differ from
        NCBI taxids, and populates the Dash stores so the Preparation tab
        shows correct status on first visit.
        """
        from nanometa_live.app.utils.config_manager import atomic_config_update

        if not config:
            return no_update, no_update, no_update, no_update

        kraken_db = config.get("kraken_db", "")
        if not kraken_db or not os.path.exists(kraken_db):
            return no_update, no_update, no_update, no_update

        # Only initialize once per session
        if config.get("_taxid_mapping_initialized"):
            return no_update, no_update, no_update, no_update

        try:
            from nanometa_live.core.taxonomy.taxid_mapping import (
                get_mapping_cache_path,
                TaxidMappingCollection,
                set_mapping_collection,
            )

            collection_data = no_update
            db_info = no_update
            rescan_time = no_update

            # Check if cached mappings exist for this database
            cache_path = get_mapping_cache_path(kraken_db)
            if cache_path.exists():
                collection = TaxidMappingCollection.load(str(cache_path))
                if collection:
                    set_mapping_collection(collection)
                    logging.info(
                        f"Loaded cached taxid mappings: {collection.total_entries} entries, "
                        f"{collection.mapped_exact} exact, {collection.mapped_fuzzy} fuzzy"
                    )

                    # Populate Dash stores for Preparation tab display
                    coll_dict = collection.to_dict()
                    collection_data = {
                        "mappings": {
                            str(m["ncbi_taxid"]): m
                            for m in coll_dict.get("mappings", [])
                        },
                        "statistics": coll_dict.get("statistics", {}),
                    }
                    db_info = {
                        "type": collection.database_type.value,
                        "hash": collection.database_hash,
                        "path": collection.database_path,
                    }
                    rescan_time = collection.updated_at.isoformat()

            # Use atomic update to properly track version
            updated_config = atomic_config_update(
                config,
                {"_taxid_mapping_initialized": True},
                source="initialize_taxid_mappings"
            )

            return updated_config, collection_data, db_info, rescan_time

        except Exception as e:
            logging.debug(f"Could not load taxid mappings: {e}")
            return no_update, no_update, no_update, no_update

    @app.callback(
        Output("backend-status", "data"), Input("update-interval", "n_intervals")
    )
    def update_backend_status(_):
        """Update the backend status."""
        return backend_manager.get_status()

    @app.callback(
        Output("results-fingerprint", "data"),
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
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
        main_dir = config.get("main_dir") or config.get("results_output_directory") or ""
        if not main_dir:
            raise PreventUpdate

        try:
            fp = check_data_freshness(main_dir)
        except Exception as e:
            log_callback_error("compute_results_fingerprint", e)
            raise PreventUpdate

        if fp == (prev or {}).get("fp"):
            raise PreventUpdate
        return {"fp": fp, "ts": time.time()}

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

            # Cap files_processed: batch stats can sum across batches,
            # exceeding the actual number of input files
            total_files = status.get("files_waiting", 0)
            raw_processed = status.get("files_processed", 0)
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

    @app.callback(
        Output("notification-container", "children"),
        Input("notification-trigger", "data"),
        State("notification-container", "children"),
    )
    def show_notification(notification_data, current_notifications):
        """Show a notification."""
        try:
            if not notification_data:
                return current_notifications or []

            if current_notifications is None:
                current_notifications = []

            # Validate notification data structure
            if not isinstance(notification_data, dict):
                logging.error(f"Invalid notification data format: {notification_data}")
                return current_notifications

            # Make sure required fields exist
            message = notification_data.get("message", "Notification")
            title = notification_data.get("title", "Notification")
            color = notification_data.get("color", "primary")

            # Render multi-line messages as separate lines
            if isinstance(message, str) and "\n" in message:
                message_content = html.Div([
                    html.Div(line, className="mb-1") for line in message.split("\n") if line.strip()
                ])
            else:
                message_content = message

            notification = dbc.Toast(
                message_content,
                id=f"notification-{int(time.time())}",
                header=title,
                is_open=True,
                dismissable=True,
                duration=4000,
                color=color,
            )

            return current_notifications + [notification]
        except Exception as e:
            log_callback_error("show_notification", e)
            return current_notifications or []

    @app.callback(
        [
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("app-config", "data", allow_duplicate=True),
            Output("stop-confirm-modal", "is_open", allow_duplicate=True),
            Output("collision-modal", "is_open", allow_duplicate=True),
            Output("collision-modal-body", "children", allow_duplicate=True),
            Output("collision-decision-pending", "data", allow_duplicate=True),
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
            return no_update, no_update, no_update, no_update, no_update, no_update

        if status.get("running", False):
            # Open stop-confirmation modal instead of stopping directly
            return no_update, no_update, True, no_update, no_update, no_update

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
            )

        # Determine the results directory the run will write to. The
        # GUI accepts either explicit `results_output_directory` or
        # falls back to `main_dir`; mirror parameter_mapping's choice.
        outdir = (
            config.get("results_output_directory")
            or config.get("main_dir")
            or ""
        )
        found = backend_manager.detect_existing_results(outdir)
        if found:
            # Compare current input fingerprint with the prior run's
            # (None when no .nanometa.run.json exists yet).
            input_match = backend_manager.fingerprint_matches(outdir, config)
            return (
                no_update,
                no_update,
                no_update,
                True,
                render_collision_body(outdir, found, input_match=input_match),
                {"outdir": outdir, "found": found, "input_match": input_match},
            )

        # Clean outdir -- start the analysis directly.
        backend_manager.config = config
        success, message = backend_manager.start()
        color = "success" if success else "danger"

        if success:
            updated_config = merge_config_safely(config, backend_manager.config)
        else:
            updated_config = no_update

        return (
            {
                "title": "Analysis Started" if success else "Error",
                "message": message,
                "color": color,
            },
            updated_config,
            no_update,
            no_update,
            no_update,
            no_update,
        )

    @app.callback(
        [
            Output("collision-modal", "is_open", allow_duplicate=True),
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("app-config", "data", allow_duplicate=True),
        ],
        [
            Input("collision-archive-btn", "n_clicks"),
            Input("collision-resume-btn", "n_clicks"),
            Input("collision-cancel-btn", "n_clicks"),
        ],
        [
            State("collision-decision-pending", "data"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_collision_choice(
        archive_clicks, resume_clicks, cancel_clicks, pending, config
    ):
        """Dispatch the collision modal's three buttons.

        Cancel just closes the modal with an info toast. Archive moves
        existing result subdirs into a timestamped subfolder and starts
        a fresh run. Continue runs the pipeline with -resume so
        Nextflow reuses cached work where it can.
        """
        from nanometa_live.app.utils.config_manager import merge_config_safely

        triggered = ctx.triggered_id
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
            )

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
                )
            success, message = backend_manager.start(resume=False)
            if success and archive_path:
                message = (
                    f"{message}\nPrevious results archived to "
                    f"{archive_path}"
                )
        elif triggered == "collision-resume-btn":
            success, message = backend_manager.start(resume=True)
        else:
            raise PreventUpdate

        color = "success" if success else "danger"
        if success:
            updated_config = merge_config_safely(config, backend_manager.config)
        else:
            updated_config = no_update

        return (
            False,
            {
                "title": "Analysis Started" if success else "Error",
                "message": message,
                "color": color,
            },
            updated_config,
        )

    @app.callback(
        [
            Output("stop-confirm-modal", "is_open"),
            Output("notification-trigger", "data", allow_duplicate=True),
        ],
        [
            Input("confirm-stop-analysis", "n_clicks"),
            Input("cancel-stop-analysis", "n_clicks"),
        ],
        State("stop-confirm-modal", "is_open"),
        prevent_initial_call=True,
    )
    def handle_stop_confirmation(confirm_clicks, cancel_clicks, is_open):
        """Handle stop confirmation modal buttons."""
        if not is_open:
            return no_update, no_update

        triggered = ctx.triggered_id
        if triggered == "confirm-stop-analysis" and confirm_clicks:
            success, message = backend_manager.stop()
            color = "success" if success else "danger"
            return False, {
                "title": "Analysis Stopped" if success else "Error",
                "message": message,
                "color": color,
            }
        elif triggered == "cancel-stop-analysis" and cancel_clicks:
            return False, no_update

        return no_update, no_update

    @app.callback(
        Output("tabs", "active_tab"),
        Input("notification-trigger", "data"),
        State("tabs", "active_tab"),
        prevent_initial_call=True,
    )
    def switch_to_results_tab(notification, current_tab):
        """Switch to the Dashboard tab after starting analysis."""
        if not notification or not isinstance(notification, dict):
            return no_update

        if (
            notification.get("title") == "Analysis Started"
            and notification.get("color") == "success"
        ):
            return "dashboard-tab"

        return no_update

    # ========================================================================
    # Readiness Indicator
    # ========================================================================

    @app.callback(
        [
            Output("readiness-badge", "children"),
            Output("readiness-badge", "color"),
            Output("readiness-state", "data"),
            Output("readiness-popover-body", "children"),
        ],
        Input("update-interval", "n_intervals"),
        Input("app-config", "data"),
    )
    def update_readiness_indicator(n_intervals, config):
        """Update the readiness badge, popover details, and cached readiness state."""
        from nanometa_live.core.workflow.readiness_checker import ReadinessChecker

        if not config:
            return (
                [html.I(className="bi bi-dash-circle me-1"), "Not configured"],
                "secondary",
                {"ready": False, "checks": [], "message": "No configuration loaded"},
                html.Div("Load a configuration to see readiness checks.", className="text-muted small"),
            )

        try:
            cache_key = _readiness_cache_key(config)
            now = time.time()
            with _readiness_cache_lock:
                cached = _readiness_cache.get(cache_key)
            if cached is not None and (now - cached[0]) < _READINESS_TTL:
                report = cached[1]
            else:
                checker = ReadinessChecker()
                report = checker.check_readiness(config)
                with _readiness_cache_lock:
                    _readiness_cache[cache_key] = (now, report)
            summary = report.summary()

            if report.ready:
                badge_children = [html.I(className="bi bi-check-circle-fill me-1"), "Ready"]
                badge_color = "success"
            else:
                badge_children = [
                    html.I(className="bi bi-exclamation-triangle-fill me-1"),
                    f"{summary['passed']}/{summary['total']} checks",
                ]
                badge_color = "danger" if summary["critical_failures"] > 0 else "warning"

            checks_data = []
            popover_items = []
            for c in report.checks:
                checks_data.append({
                    "name": c.name,
                    "passed": c.passed,
                    "severity": c.severity.value,
                    "message": c.message,
                })
                if c.passed:
                    icon_cls = "bi bi-check-circle-fill text-success"
                elif c.severity.value == "critical":
                    icon_cls = "bi bi-x-circle-fill text-danger"
                else:
                    icon_cls = "bi bi-exclamation-triangle-fill text-warning"
                popover_items.append(
                    html.Div([
                        html.I(className=f"{icon_cls} me-2"),
                        html.Span(c.name, className="small"),
                    ], className="mb-1", title=c.message)
                )

            popover_content = html.Div(popover_items, style={"maxHeight": "300px", "overflowY": "auto"})
            if not report.ready:
                popover_content = html.Div([
                    popover_content,
                    html.Hr(className="my-2"),
                    html.Div("Click badge to go to Preparation tab", className="text-muted small fst-italic"),
                ])

            return (
                badge_children,
                badge_color,
                {"ready": report.ready, "checks": checks_data, "message": ""},
                popover_content,
            )
        except Exception as e:
            logging.error(f"Readiness check failed: {e}")
            return (
                [html.I(className="bi bi-dash-circle me-1"), "Unknown"],
                "secondary",
                {"ready": False, "checks": [], "message": str(e)},
                html.Div(f"Error: {str(e)}", className="text-danger small"),
            )

    app.clientside_callback(
        """
        function(n_clicks, readiness) {
            if (!n_clicks || !readiness) return dash_clientside.no_update;
            if (readiness.ready) return dash_clientside.no_update;
            return "preparation-tab";
        }
        """,
        Output("tabs", "active_tab", allow_duplicate=True),
        Input("readiness-badge", "n_clicks"),
        State("readiness-state", "data"),
        prevent_initial_call=True,
    )

    # ========================================================================
    # Config Status Badge (Auto-save indicator)
    # ========================================================================

    @app.callback(
        [
            Output("config-status-badge", "children"),
            Output("config-status-badge", "color"),
            Output("config-status-badge", "style"),
        ],
        Input("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_config_badge(config):
        """Show config save status in header badge."""
        last_session = os.path.expanduser("~/.nanometa/configs/last-session.yaml")
        badge_style = {"fontSize": "0.75rem", "display": "inline-block"}
        if os.path.exists(last_session):
            return "Auto-saved", "success", badge_style
        return "Not saved", "secondary", badge_style

    # ========================================================================
    # Sample Management Callbacks (Multi-sample/Barcode Support)
    # ========================================================================

    @app.callback(
        [
            Output("available-samples", "data"),
            Output("sample-file-mapping", "data"),
        ],
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
        State("available-samples", "data"),
        State("sample-file-mapping", "data"),
    )
    def update_available_samples(n_intervals, config, prev_samples, prev_mapping):
        """
        Detect and update available samples from nanometanf output.

        Scans the output directory for Kraken2, FASTP, and BLAST files
        to automatically detect all available samples/barcodes.

        Short-circuits with PreventUpdate when the detected sample list
        and file mapping have not changed since the previous tick. This
        eliminates the per-tick store-overwrite churn flagged as P1-T03
        in docs/audit-2026-04-28-throughput-gui.md, which otherwise
        cascades a re-render of every callback subscribed to either
        store on every interval tick at 24-barcode scale.
        """

        if not config:
            new_samples, new_mapping = ["All Samples"], {}
        else:
            try:
                # Use results_output_directory for pipeline output (where kraken2/, fastp/ are)
                main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")

                if not main_dir or not os.path.exists(main_dir):
                    new_samples, new_mapping = ["All Samples"], {}
                else:
                    # Get available samples from output files
                    new_samples = get_available_samples(main_dir)
                    new_mapping = get_sample_file_mapping(main_dir)
                    logging.debug(f"Detected {len(new_samples)-1} samples: {new_samples}")
            except Exception as e:
                log_callback_error("update_available_samples", e, level=logging.WARNING)
                new_samples, new_mapping = ["All Samples"], {}

        # Skip the store overwrite when nothing meaningful changed. The
        # comparison is intentionally on the wire-format dicts/lists Dash
        # sees; identical content means subscribers will not re-render.
        if new_samples == (prev_samples or []) and new_mapping == (prev_mapping or {}):
            raise PreventUpdate

        return new_samples, new_mapping

    @app.callback(
        [
            Output("sample-selector", "options"),
            Output("sample-selector", "value"),
        ],
        Input("available-samples", "data"),
        State("sample-selector", "value"),
    )
    def update_sample_selector_options(available_samples, current_value):
        """
        Update sample selector dropdown options.

        Converts the list of available samples into Dash dropdown options.
        Resets the selected value to 'All Samples' if the current selection
        is no longer available (e.g. sample directory was removed).
        """
        if not available_samples:
            available_samples = ["All Samples"]

        options = []
        for sample in available_samples:
            if sample == "All Samples":
                options.append({"label": "All Samples (Aggregated)", "value": sample})
            else:
                options.append({"label": sample, "value": sample})

        # Reset to 'All Samples' if current selection is no longer valid
        if current_value and current_value not in available_samples:
            return options, "All Samples"

        return options, no_update

    @app.callback(
        Output("selected-sample", "data"),
        Input("sample-selector", "value"),
    )
    def update_selected_sample(selected_value):
        """
        Update the selected-sample store when user changes selection.

        This store is used by all tabs to filter data by sample.
        """
        return selected_value if selected_value else "All Samples"

    # ========================================================================
    # Live Indicator Callbacks (Real-time Status Display)
    # ========================================================================

    @app.callback(
        [
            Output("live-indicator-dot", "className"),
            Output("live-indicator-text", "children"),
            Output("last-update-display", "children"),
        ],
        [
            Input("backend-status", "data"),
            Input("update-interval", "n_intervals"),
        ],
        State("app-config", "data"),
    )
    def update_live_indicator(status, n_intervals, config):
        """
        Update the live indicator in the header.

        Shows whether the system is actively monitoring and when
        data was last updated.
        """
        # Get current time for display
        current_time = time.strftime("%H:%M:%S")

        # Check if in visualization-only mode
        if config and config.get("visualization_only", False):
            return (
                "live-indicator-dot offline",
                "View Only",
                f"Last check: {current_time}"
            )

        # Check backend status
        if status and status.get("running", False):
            return (
                "live-indicator-dot",  # Animated pulse
                "LIVE",
                f"Updated: {current_time}"
            )
        elif status and status.get("completed", False):
            return (
                "live-indicator-dot offline",
                "Complete",
                f"Finished: {current_time}"
            )
        else:
            return (
                "live-indicator-dot offline",
                "Standby",
                f"Last check: {current_time}"
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
            update_interval = config.get("update_interval_seconds", 30)
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
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
    )
    def track_last_update_time(n_intervals, config):
        """Track when data was last successfully updated."""
        import datetime

        if not config:
            return None

        try:
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
            if main_dir and os.path.exists(main_dir):
                # Return current timestamp as ISO format
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
        Input("toast-message", "data"),
        State("toast-container", "children"),
    )
    def display_toast(toast_data, current_toasts):
        """
        Display toast notifications for non-blocking feedback.

        Toast data format:
        {
            "type": "success" | "warning" | "danger" | "info",
            "title": "Toast Title",
            "message": "Toast message content"
        }
        """
        from dash import html

        if not toast_data:
            return current_toasts or []

        if current_toasts is None:
            current_toasts = []

        try:
            toast_type = toast_data.get("type", "info")
            title = toast_data.get("title", "Notification")
            message = toast_data.get("message", "")

            # Icon mapping
            icon_map = {
                "success": "bi-check-circle-fill text-success",
                "warning": "bi-exclamation-triangle-fill text-warning",
                "danger": "bi-x-circle-fill text-danger",
                "info": "bi-info-circle-fill text-info",
            }

            icon_class = icon_map.get(toast_type, icon_map["info"])

            new_toast = html.Div(
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

            # Auto-remove after 4 seconds (handled by CSS animation)
            return current_toasts + [new_toast]

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

        # No navigation needed, just update the previous state tracker
        return no_update, new_prev_state, no_update

    # ========================================================================
    # Welcome Modal (first-run onboarding)
    # ========================================================================

    @app.callback(
        [
            Output("welcome-modal", "is_open"),
            Output("tabs", "active_tab", allow_duplicate=True),
        ],
        [
            Input("welcome-shown", "data"),
            Input("close-welcome-modal", "n_clicks"),
        ],
        prevent_initial_call="initial_duplicate",
    )
    def manage_welcome_modal(already_shown, close_clicks):
        """Show the welcome modal on first visit, dismiss on button click."""
        triggered = ctx.triggered_id
        if triggered == "close-welcome-modal":
            return False, "config-tab"
        # Show on first visit only
        if not already_shown:
            return True, no_update
        return False, no_update

    @app.callback(
        Output("welcome-shown", "data"),
        Input("close-welcome-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def mark_welcome_shown(_):
        """Persist that the welcome modal has been shown."""
        return True

    # ========================================================================
    # Step Navigation Buttons
    # ========================================================================

    @app.callback(
        Output("tabs", "active_tab", allow_duplicate=True),
        Input("config-next-watchlist-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def navigate_config_to_watchlist(_):
        """Navigate from Configuration to Watchlist tab."""
        return "watchlist-tab"

    @app.callback(
        Output("tabs", "active_tab", allow_duplicate=True),
        Input("watchlist-next-preparation-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def navigate_watchlist_to_preparation(_):
        """Navigate from Watchlist to Preparation tab."""
        return "preparation-tab"