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
        Input("backend-status", "data"),
    )
    def update_status_display(status):
        """Update the status display based on backend status."""
        if not status:
            return "gray", "Unknown", "Unable to determine backend status"

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

        # Check if configuration is complete
        required_fields = ["nanopore_output_directory", "kraken_db"]
        config_complete = all(field in config and config[field] for field in required_fields)

        if status.get("running", False):
            return "Stop Analysis", "danger", False

        return "Start Analysis", "primary", not config_complete

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
        if not notification_data:
            return current_notifications or []

        if current_notifications is None:
            current_notifications = []

        notification = dbc.Toast(
            notification_data.get("message", "Notification"),
            id=f"notification-{int(time.time())}",
            header=notification_data.get("title", "Notification"),
            is_open=True,
            dismissable=True,
            duration=4000,
            color=notification_data.get("color", "primary"),
        )

        return current_notifications + [notification]

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        Input("start-stop-button", "n_clicks"),
        [State("app-config", "data"), State("backend-status", "data")],
        prevent_initial_call=True,
    )
    def start_stop_analysis(n_clicks, config, status):
        """Start or stop the analysis based on current state."""
        if not n_clicks:
            return no_update

        if status.get("running", False):
            # Stop the analysis
            success, message = backend_manager.stop()
            color = "success" if success else "danger"

            return {
                "title": "Analysis Stopped" if success else "Error",
                "message": message,
                "color": color,
            }
        else:
            # Start the analysis
            success, message = backend_manager.start()
            color = "success" if success else "danger"

            return {
                "title": "Analysis Started" if success else "Error",
                "message": message,
                "color": color,
            }

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
            Output("prepare-progress", "value"),
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
        # Default values for returns
        no_changes = [no_update, no_update, no_update, no_update, no_update, no_update]

        # Handle modal closing
        if close_clicks and ctx.triggered_id == "close-prepare-modal":
            return [False] + no_changes[1:]

        # Handle preparation cancellation
        if cancel_clicks and ctx.triggered_id == "cancel-prepare-button":
            # Can add cancellation functionality here if needed
            return [False] + no_changes[1:] + [{"display": "none"}, {
                "title": "Cancelled",
                "message": "Data preparation was cancelled",
                "color": "warning",
            }]

        # Start preparation
        if prepare_clicks and ctx.triggered_id == "prepare-data-button":
            if not config:
                return no_changes[:-1] + [{
                    "title": "Error",
                    "message": "No configuration loaded. Please configure the application first.",
                    "color": "danger",
                }]

            # Start the preparation process
            success, message = backend_manager.prepare_data()
            if not success:
                return no_changes[:-1] + [{
                    "title": "Error",
                    "message": f"Failed to start data preparation: {message}",
                    "color": "danger",
                }]

            # Preparation started successfully
            return [
                True,  # Open modal
                "Starting data preparation...",  # Status message
                0,  # Progress value
                True,  # Close button disabled
                {"display": "block"},  # Cancel button visible
                no_update  # No notification
            ]

        # Update progress during preparation
        if is_open and ctx.triggered_id == "update-interval":
            status = backend_manager.get_preparation_status()

            if not status["running"]:
                # Preparation finished
                if status["errors"]:
                    # Preparation failed
                    return [
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
                    ]
                else:
                    # Preparation succeeded
                    return [
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
                    ]
            else:
                # Preparation still running
                return [
                    True,  # Keep modal open
                    status["message"],  # Current status message
                    status["progress"],  # Current progress value
                    True,  # Keep close button disabled
                    {"display": "block"},  # Show cancel button
                    no_update  # No notification
                ]

        # Default return if no conditions met
        return no_changes

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Input("update-interval", "n_intervals"),
        [
            State("prepare-data-modal", "is_open"),
            State("app-config", "data")
        ],
        prevent_initial_call=True,
    )
    def update_config_after_preparation(n_intervals, modal_open, current_config):
        """
        Update the app configuration after data preparation completes.
        This ensures any taxonomy IDs discovered during preparation are reflected in the UI.
        """
        if not modal_open:
            return no_update

        status = backend_manager.get_preparation_status()

        if not status["running"] and status["progress"] >= 100 and not status["errors"]:
            # Preparation completed successfully
            # Return the updated configuration
            return backend_manager.config

        return no_update