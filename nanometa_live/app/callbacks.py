"""
Core callbacks for the Nanometa Live application.

This module contains the core callbacks that are used across multiple tabs
and components of the application.
"""

import os
import logging
import time
import json
from typing import Dict, Any

from dash import Dash, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.utils.sample_detector import get_available_samples, get_sample_file_mapping
from nanometa_live.app.utils.callback_helpers import log_callback_error


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
    # Taxid Mapping Initialization (for pathogen detection)
    # ========================================================================
    # This runs once on startup to load cached taxid mappings if they exist.
    # Required for proper pathogen detection with GTDB/custom Kraken2 databases.

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Input("app-config", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def initialize_taxid_mappings(config):
        """
        Load cached taxid mappings on startup for proper pathogen detection.

        This callback runs once when the app-config is first set and loads
        any cached mappings for the configured Kraken2 database. This enables
        proper pathogen detection with GTDB databases where taxids differ from
        NCBI taxids.
        """
        from nanometa_live.app.utils.config_manager import atomic_config_update

        if not config:
            return no_update

        kraken_db = config.get("kraken_db", "")
        if not kraken_db or not os.path.exists(kraken_db):
            return no_update

        # Only initialize once per session
        if config.get("_taxid_mapping_initialized"):
            return no_update

        try:
            from nanometa_live.core.taxonomy.taxid_mapping import (
                get_mapping_cache_path,
                TaxidMappingCollection,
                set_mapping_collection,
            )

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

            # Use atomic update to properly track version
            return atomic_config_update(
                config,
                {"_taxid_mapping_initialized": True},
                source="initialize_taxid_mappings"
            )

        except Exception as e:
            logging.debug(f"Could not load taxid mappings: {e}")
            return no_update

    @app.callback(
        Output("backend-status", "data"), Input("update-interval", "n_intervals")
    )
    def update_backend_status(_):
        """Update the backend status."""
        return backend_manager.get_status()

    @app.callback(
        [
            Output("status-indicator", "color"),
            Output("status-text", "children"),
            Output("status-details", "children"),
        ],
        [Input("backend-status", "data"), Input("app-config", "data")],
    )
    def update_status_display(status, config):
        """Update the status display based on backend status."""
        if not status:
            return "gray", "Unknown", "Unable to determine backend status"

        # Check if in visualization-only mode
        if config and config.get("visualization_only", False):
            return "blue", "Viewing Data", "Visualization mode - displaying existing results (no pipeline execution)"

        if status.get("running", False):
            color = "green"
            text = "Running"

            # Create details
            details = [
                f"Files processed: {status.get('files_processed', 0)}",
                f"Files waiting: {status.get('files_waiting', 0)}",
            ]

            if status.get("last_update"):
                timestamp = time.strftime(
                    "%H:%M:%S", time.localtime(status.get("last_update"))
                )
                details.append(f"Last update: {timestamp}")

            return color, text, ", ".join(details)

        if status.get("pipeline_status") == "error":
            return "red", "Error", ", ".join(status.get("errors", ["Unknown error"]))

        return "gray", "Idle", "Click 'Start Analysis' to begin processing"

    @app.callback(
        [
            Output("start-stop-button", "children"),
            Output("start-stop-button", "color"),
            Output("start-stop-button", "disabled"),
        ],
        [Input("backend-status", "data"), Input("app-config", "data")],
    )
    def update_control_button(status, config):
        """Update the start/stop button based on backend status."""
        if not status or not config:
            return "Start Analysis", "primary", True

        # Disable control buttons in visualization-only mode
        if config.get("visualization_only", False):
            return "Start Analysis", "secondary", True

        # Check if configuration is complete
        required_fields = ["nanopore_output_directory", "kraken_db"]
        config_complete = all(field in config and config[field] for field in required_fields)

        if status.get("running", False):
            return "Stop Analysis", "danger", False

        return "Start Analysis", "primary", not config_complete

    @app.callback(
        [
            Output("prepare-data-button", "disabled"),
            Output("prepare-data-button", "color"),
            Output("prepare-data-wrapper", "style"),
        ],
        Input("app-config", "data"),
    )
    def update_prepare_button(config):
        """Update the prepare data button based on config.

        Hides the button entirely when BLAST validation is disabled,
        since genome preparation is only needed for validation.
        """
        if not config:
            return True, "info", {"display": "inline-block"}

        # Disable in visualization-only mode
        if config.get("visualization_only", False):
            return True, "secondary", {"display": "none"}

        # Hide when validation is disabled
        blast_validation = config.get("blast_validation", True)
        if isinstance(blast_validation, str):
            blast_validation = blast_validation.lower() in ["true", "yes", "y", "1"]
        if not blast_validation:
            return True, "secondary", {"display": "none"}

        return False, "info", {"display": "inline-block"}

    @app.callback(
        [
            Output("prepare-data-tooltip", "children"),
            Output("start-analysis-tooltip", "children"),
        ],
        Input("app-config", "data"),
    )
    def update_tooltips(config):
        """Update button tooltips based on mode."""
        if config and config.get("visualization_only", False):
            prepare_tip = "Not available in visualization mode"
            start_tip = "Not available in visualization mode - displaying existing results only"
            return prepare_tip, start_tip

        return ("Extract taxonomy IDs and prepare validation databases",
                "Begin processing the nanopore sequence data")

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

            notification = dbc.Toast(
                message,
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
        ],
        Input("start-stop-button", "n_clicks"),
        [State("app-config", "data"), State("backend-status", "data")],
        prevent_initial_call=True,
    )
    def start_stop_analysis(n_clicks, config, status):
        """Start or stop the analysis based on current state."""
        from nanometa_live.app.utils.config_manager import merge_config_safely

        if not n_clicks:
            return no_update, no_update

        if status.get("running", False):
            # Stop the analysis
            success, message = backend_manager.stop()
            color = "success" if success else "danger"

            return {
                "title": "Analysis Stopped" if success else "Error",
                "message": message,
                "color": color,
            }, no_update
        else:
            # Start the analysis - first set the config on backend_manager
            if not config:
                return {
                    "title": "Error",
                    "message": "No configuration loaded. Please load or configure settings first.",
                    "color": "danger",
                }, no_update
            backend_manager.config = config
            success, message = backend_manager.start()
            color = "success" if success else "danger"

            # After start, backend_manager.config has updated main_dir with analysis directory
            # Merge the updated config while preserving internal state
            if success:
                updated_config = merge_config_safely(config, backend_manager.config)
            else:
                updated_config = no_update

            return {
                "title": "Analysis Started" if success else "Error",
                "message": message,
                "color": color,
            }, updated_config

    @app.callback(
        Output("tabs", "active_tab"),
        Input("notification-trigger", "data"),
        State("tabs", "active_tab"),
        prevent_initial_call=True,
    )
    def switch_to_results_tab(notification, current_tab):
        """Switch to the results tab after starting analysis."""
        if not notification:
            return no_update

        if (
            notification.get("title") == "Analysis Started"
            and notification.get("color") == "success"
        ):
            return "main-tab"

        return current_tab

    @app.callback(
        [
            Output("prepare-data-modal", "is_open"),
            Output("prepare-status", "children"),
            Output("prepare-overall-progress", "value"),
            Output("close-prepare-modal", "disabled"),
            Output("cancel-prepare-button", "style"),
            Output("notification-trigger", "data", allow_duplicate=True),
        ],
        [
            Input("prepare-data-button", "n_clicks"),
            Input("close-prepare-modal", "n_clicks"),
            Input("cancel-prepare-button", "n_clicks"),
            Input("update-interval", "n_intervals"),
        ],
        [
            State("app-config", "data"),
            State("prepare-data-modal", "is_open"),
        ],
        prevent_initial_call=True,
    )
    def manage_data_preparation(
        prepare_clicks, close_clicks, cancel_clicks, n_intervals,
        config, is_open
    ):
        """
        Manage the data preparation process:
        - Start preparation on button click
        - Update progress during preparation
        - Close modal when done
        """
        try:
            # Default values for returns
            no_changes = [no_update, no_update, no_update, no_update, no_update, no_update]

            # Handle modal closing
            if close_clicks and ctx.triggered_id == "close-prepare-modal":
                return False, no_update, no_update, no_update, no_update, no_update

            # Handle preparation cancellation
            if cancel_clicks and ctx.triggered_id == "cancel-prepare-button":
                try:
                    # Update backend status if possible
                    if hasattr(backend_manager, 'prep_status'):
                        backend_manager.prep_status["running"] = False
                        backend_manager.prep_status["message"] = "Cancelled by user"
                except Exception as e:
                    log_callback_error("manage_data_preparation.cancel", e)

                return False, no_update, no_update, no_update, {"display": "none"}, {
                    "title": "Cancelled",
                    "message": "Data preparation was cancelled",
                    "color": "warning",
                }

            # Start preparation
            if prepare_clicks and ctx.triggered_id == "prepare-data-button":
                if not config:
                    return no_update, no_update, no_update, no_update, no_update, {
                        "title": "Error",
                        "message": "No configuration loaded. Please configure the application first.",
                        "color": "danger",
                    }

                # Make sure backend manager has the current config
                if hasattr(backend_manager, 'config'):
                    backend_manager.config = config

                # Start the preparation process
                try:
                    success, message = backend_manager.prepare_data()
                    if not success:
                        return no_update, no_update, no_update, no_update, no_update, {
                            "title": "Error",
                            "message": f"Failed to start data preparation: {message}",
                            "color": "danger",
                        }
                except Exception as e:
                    log_callback_error("manage_data_preparation.start", e, extra_context={"config_keys": list(config.keys()) if config else None})
                    return no_update, no_update, no_update, no_update, no_update, {
                        "title": "Error",
                        "message": f"Exception starting data preparation: {str(e)}",
                        "color": "danger",
                    }

                # Preparation started successfully
                return (
                    True,  # Open modal
                    "Starting data preparation...",  # Status message
                    0,  # Progress value
                    True,  # Close button disabled
                    {"display": "block"},  # Cancel button visible
                    no_update  # No notification
                )

            # Update progress during preparation
            if is_open and ctx.triggered_id == "update-interval":
                try:
                    status = backend_manager.get_preparation_status()
                except Exception as e:
                    log_callback_error("manage_data_preparation.get_status", e)
                    return (
                        True,  # Keep modal open
                        f"Error retrieving status: {str(e)}",  # Show error
                        0,  # Reset progress
                        False,  # Enable close button
                        {"display": "none"},  # Hide cancel button
                        {
                            "title": "Error",
                            "message": f"Error retrieving preparation status: {str(e)}",
                            "color": "danger",
                        }
                    )

                if not status["running"]:
                    # Preparation finished
                    if status["errors"]:
                        # Preparation failed
                        return (
                            True,  # Keep modal open
                            f"Error: {status['errors'][0]}",  # Show first error
                            100,  # Complete progress
                            False,  # Enable close button
                            {"display": "none"},  # Hide cancel button
                            {
                                "title": "Error",
                                "message": f"Data preparation failed: {status['errors'][0]}",
                                "color": "danger",
                            }
                        )
                    else:
                        # Preparation succeeded
                        return (
                            True,  # Keep modal open
                            "Data preparation completed successfully!",  # Success message
                            100,  # Complete progress
                            False,  # Enable close button
                            {"display": "none"},  # Hide cancel button
                            {
                                "title": "Success",
                                "message": "Data preparation completed successfully",
                                "color": "success",
                            }
                        )
                else:
                    # Preparation still running
                    return (
                        True,  # Keep modal open
                        status.get("message", "Processing..."),  # Current status message
                        status.get("progress", 0),  # Current progress value
                        True,  # Keep close button disabled
                        {"display": "block"},  # Show cancel button
                        no_update  # No notification
                    )

            # Default return if no conditions met
            return no_changes

        except Exception as e:
            # Global error handler with full traceback
            log_callback_error("manage_data_preparation", e)
            return (
                False,
                f"Error: {str(e)}",
                0,
                False,
                {"display": "none"},
                {
                    "title": "Error",
                    "message": f"An unexpected error occurred: {str(e)}",
                    "color": "danger",
                }
            )

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        [
            Input("update-interval", "n_intervals"),
            Input("prepare-data-modal", "is_open")  # Make this an Input instead of State
        ],
        [
            State("app-config", "data")
        ],
        prevent_initial_call=True,
    )
    def update_config_after_preparation(n_intervals, modal_open, current_config):
        """
        Update the app configuration after data preparation completes.
        This ensures any taxonomy IDs discovered during preparation are reflected in the UI.

        Uses race condition protection to avoid overwriting concurrent user changes.
        """
        from nanometa_live.app.utils.config_manager import (
            should_skip_stale_update,
            merge_config_safely,
        )

        # Skip if recent update from another source (prevents race conditions)
        if should_skip_stale_update(current_config):
            return no_update

        # Check if modal just closed (triggered by modal_open changing to False)
        if ctx.triggered_id == "prepare-data-modal" and not modal_open:
            status = backend_manager.get_preparation_status()

            # If preparation completed successfully
            if status["progress"] >= 100 and not status["errors"]:
                # Merge backend config while preserving internal state
                return merge_config_safely(current_config, backend_manager.config)

        # Regular interval update while modal is open
        elif modal_open:
            status = backend_manager.get_preparation_status()

            # If preparation just completed
            if not status["running"] and status["progress"] >= 100 and not status["errors"]:
                # Merge backend config while preserving internal state
                return merge_config_safely(current_config, backend_manager.config)

        return no_update

    # NOTE: handle_prepare_data_click and open_prepare_data_modal were removed as they
    # were duplicates of manage_data_preparation. All prepare-data button handling
    # (including opening the modal, starting preparation, and progress updates) is now
    # consolidated in manage_data_preparation above.

    @app.callback(
        [
            Output("prepare-current-step", "children"),
            Output("prepare-step-details", "children"),
            Output("prepare-step-progress", "value"),
            Output("prepare-status", "children", allow_duplicate=True),
            Output("prepare-overall-progress", "value", allow_duplicate=True),
            Output("close-prepare-modal", "disabled", allow_duplicate=True),
            Output("cancel-prepare-button", "style", allow_duplicate=True),
        ],
        Input("update-interval", "n_intervals"),
        State("prepare-data-modal", "is_open"),
        prevent_initial_call=True,
    )
    def update_preparation_progress(n_intervals, modal_open):
        """Update the preparation progress modal with latest status"""
        if not modal_open:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update

        try:
            status = backend_manager.get_preparation_status()

            # Determine current step based on progress
            step_name = "Initializing..."
            step_details = "Preparing to start"
            step_progress = 0

            if status["progress"] < 10:
                step_name = "Starting up"
                step_details = "Initializing preparation"
                step_progress = status["progress"] * 10
            elif status["progress"] < 30:
                step_name = "Extracting taxonomy IDs"
                step_details = status.get("message", "Processing taxonomy data")
                step_progress = (status["progress"] - 10) * 5
            elif status["progress"] < 50:
                step_name = "Matching species"
                step_details = status.get("message", "Finding species in databases")
                step_progress = (status["progress"] - 30) * 5
            elif status["progress"] < 70:
                step_name = "Downloading genomes"
                step_details = status.get("message", "Retrieving reference genomes")
                step_progress = (status["progress"] - 50) * 5
            elif status["progress"] < 90:
                step_name = "Building BLAST databases"
                step_details = status.get("message", "Preparing validation databases")
                step_progress = (status["progress"] - 70) * 5
            else:
                step_name = "Finishing up"
                step_details = status.get("message", "Completing preparation")
                step_progress = 100

            # Format status message
            if status["errors"]:
                status_message = f"Error: {status['errors'][0]}"
            else:
                status_message = status.get("message", "Processing...")

            # Only enable close button when complete or error
            close_disabled = status["running"]

            # Hide cancel button when complete
            cancel_style = {"display": "block" if status["running"] else "none"}

            return step_name, step_details, step_progress, status_message, status["progress"], close_disabled, cancel_style

        except Exception as e:
            log_callback_error("update_preparation_progress", e)
            return "Error", f"Failed to update status: {str(e)}", 0, f"Error: {str(e)}", 0, False, {"display": "none"}

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
    )
    def update_available_samples(n_intervals, config):
        """
        Detect and update available samples from nanometanf output.

        Scans the output directory for Kraken2, FASTP, and BLAST files
        to automatically detect all available samples/barcodes.
        """
        if not config:
            return ["All Samples"], {}

        try:
            # Use results_output_directory for pipeline output (where kraken2/, fastp/ are)
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")

            if not main_dir or not os.path.exists(main_dir):
                return ["All Samples"], {}

            # Get available samples from output files
            samples = get_available_samples(main_dir)
            mapping = get_sample_file_mapping(main_dir)

            logging.debug(f"Detected {len(samples)-1} samples: {samples}")

            return samples, mapping

        except Exception as e:
            log_callback_error("update_available_samples", e, level=logging.WARNING)
            return ["All Samples"], {}

    @app.callback(
        Output("sample-selector", "options"),
        Input("available-samples", "data"),
    )
    def update_sample_selector_options(available_samples):
        """
        Update sample selector dropdown options.

        Converts the list of available samples into Dash dropdown options.
        """
        if not available_samples:
            available_samples = ["All Samples"]

        return [{"label": sample, "value": sample} for sample in available_samples]

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
        else:
            return (
                "live-indicator-dot offline",
                "Idle",
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

    @app.callback(
        [
            Output("elapsed-time-display", "children"),
            Output("elapsed-time-container", "style"),
        ],
        Input("countdown-tick", "n_intervals"),
        State("backend-status", "data"),
    )
    def update_elapsed_time(n_intervals, status):
        """
        Update the elapsed time display showing time since analysis started.

        Displays in HH:MM:SS format, visible only when backend is running.
        """
        from datetime import datetime

        if not status or not status.get("running"):
            return "00:00:00", {"display": "none"}

        start_time = status.get("start_time")
        if not start_time:
            return "00:00:00", {"display": "none"}

        try:
            start_dt = datetime.fromisoformat(start_time)
            elapsed = datetime.now() - start_dt
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}", {"display": "flex", "alignItems": "center"}
        except Exception as e:
            log_callback_error("update_elapsed_time", e, level=logging.WARNING)
            return "00:00:00", {"display": "none"}

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

        is_running = status.get("running", False)

        # Store current state for next comparison
        new_prev_state = is_running

        # Detect completion: was running, now not running
        if prev_running and not is_running:
            # Analysis just completed - navigate to dashboard
            # Only if not already on dashboard
            if current_tab != "dashboard-tab":
                analysis_name = config.get("analysis_name", "Analysis") if config else "Analysis"
                toast_msg = {
                    "header": "Analysis Complete",
                    "body": f"{analysis_name} has finished. Viewing results on Dashboard.",
                    "icon": "bi-check-circle-fill",
                    "duration": 5000,
                    "type": "success"
                }
                return "dashboard-tab", new_prev_state, toast_msg
            else:
                # Already on dashboard, just show toast
                toast_msg = {
                    "header": "Analysis Complete",
                    "body": "Results are now available.",
                    "icon": "bi-check-circle-fill",
                    "duration": 4000,
                    "type": "success"
                }
                return no_update, new_prev_state, toast_msg

        # No navigation needed, just update the previous state tracker
        return no_update, new_prev_state, no_update

    # ========================================================================
    # Welcome Modal (first-run onboarding)
    # ========================================================================

    @app.callback(
        Output("welcome-modal", "is_open"),
        [
            Input("welcome-shown", "data"),
            Input("close-welcome-modal", "n_clicks"),
        ],
        prevent_initial_call=False,
    )
    def manage_welcome_modal(already_shown, close_clicks):
        """Show the welcome modal on first visit, dismiss on button click."""
        triggered = ctx.triggered_id
        if triggered == "close-welcome-modal":
            return False
        # Show on first visit only
        if not already_shown:
            return True
        return False

    @app.callback(
        Output("welcome-shown", "data"),
        Input("close-welcome-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def mark_welcome_shown(_):
        """Persist that the welcome modal has been shown."""
        return True