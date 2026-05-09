#!/usr/bin/env python3
"""
Main entry point for Nanometa Live application.

This script starts the Nanometa Live application directly, without requiring any
prior configuration or setup. The user can configure the application via the UI
and start the analysis workflow from there.
"""

import datetime
import os
import sys
import argparse
import logging
import signal
import time
import threading
from pathlib import Path

from . import __version__
from nanometa_live.app.app import create_app
from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.utils.logging_utils import setup_logging


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Nanometa Live: Real-time metagenomic analysis"
    )

    parser.add_argument(
        "--config", help="Path to a configuration file to load on startup (overrides auto-loaded last session)"
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the server to (default: 127.0.0.1, use 0.0.0.0 for network access)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Port to run the dashboard on (default: 8050)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run in debug mode with more verbose output",
    )

    parser.add_argument(
        "--main_dir", "--main-dir",
        help="Path to pipeline results directory (sets results_output_directory in config)",
    )

    parser.add_argument(
        "--data-dir", help="Directory to store application data (default: ~/.nanometa)"
    )

    parser.add_argument(
        "--version", action="version", version=f"Nanometa Live v{__version__}"
    )

    return parser.parse_args()


def create_default_dirs(data_dir):
    """Create default directories for the application if they don't exist."""
    dirs = [
        data_dir,
        os.path.join(data_dir, "configs"),
        os.path.join(data_dir, "data"),
        os.path.join(data_dir, "reports"),
        os.path.join(data_dir, "logs"),
    ]

    for d in dirs:
        os.makedirs(d, exist_ok=True)
        logging.debug(f"Ensuring directory exists: {d}")


def handle_exit(app_runner, backend_manager):
    """Handle graceful exit for the application."""

    def signal_handler(sig, frame):
        logging.info("Shutting down Nanometa Live...")
        if backend_manager:
            backend_manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main():
    """Main function to run the Nanometa Live application."""
    # Parse arguments
    args = parse_arguments()

    # Set up data directory
    if args.data_dir:
        data_dir = args.data_dir
    else:
        data_dir = os.path.expanduser("~/.nanometa")

    create_default_dirs(data_dir)

    # Setup logging with file output
    log_file = setup_logging(args.debug, os.path.join(data_dir, "logs"))
    logging.info(f"Logging to {log_file}")

    # Load configuration
    config_loader = ConfigLoader(os.path.join(data_dir, "configs"))

    deferred_session = None
    if args.config:
        try:
            config = config_loader.load_config(args.config)
            logging.info(f"Loaded configuration from {args.config}")
        except Exception as e:
            logging.error(f"Failed to load configuration from {args.config}: {e}")
            config = config_loader.create_default_config()
    else:
        # Boot with a fresh default config. Visualising already-
        # processed data should be an explicit choice, not the
        # default behaviour, so we no longer silently rehydrate
        # ~/.nanometa/configs/last-session.yaml on every restart.
        # If the file exists, the GUI surfaces a Resume/Discard
        # banner via the deferred-last-session store and the
        # operator chooses whether to load it.
        last_session = os.path.join(data_dir, "configs", "last-session.yaml")
        config = config_loader.create_default_config()
        if os.path.exists(last_session):
            try:
                mtime = os.path.getmtime(last_session)
                deferred_session = {
                    "path": last_session,
                    "mtime": mtime,
                    "mtime_iso": datetime.datetime.fromtimestamp(mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }
                logging.info(
                    "Found previous session at %s (saved %s); "
                    "GUI will offer Resume/Discard.",
                    last_session,
                    deferred_session["mtime_iso"],
                )
            except OSError as e:
                logging.warning("Could not stat %s: %s", last_session, e)
        else:
            logging.info("No previous session found; starting with default configuration.")

    # Sync CLI arguments to config
    config["gui_port"] = args.port
    if args.main_dir:
        config["results_output_directory"] = os.path.abspath(args.main_dir)
        config["main_dir"] = os.path.abspath(args.main_dir)
        logging.info(f"Results directory set to {args.main_dir}")

    # Initialize backend manager (but don't start any processes yet)
    backend_manager = BackendManager(data_dir)

    # Create and start the Dash application
    app = create_app(config, data_dir, backend_manager, deferred_session=deferred_session)

    # Dash resets its own logger to INFO during construction, undoing
    # the WARNING level we set in setup_logging. Re-apply here so the
    # duplicate "Dash is running on..." line stays suppressed.
    if not args.debug:
        logging.getLogger("dash.dash").setLevel(logging.WARNING)
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # Set up signal handlers for graceful exit
    handle_exit(app, backend_manager)

    # Start the Dash server
    logging.info(f"Starting Nanometa Live v{__version__} server on port {args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()