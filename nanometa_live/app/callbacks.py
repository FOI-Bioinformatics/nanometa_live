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
        config_complete = all(config.get(field) for field in required_fields)

        if status.get("running", False):
            return "Stop Analysis", "danger", False

        return "Start Analysis", "primary", not config_complete

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
