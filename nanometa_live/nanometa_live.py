#!/usr/bin/env python3
"""
Main entry point for Nanometa Live application.

This script starts the Nanometa Live application directly, without requiring any
prior configuration or setup. The user can configure the application via the UI
and start the analysis workflow from there.
"""

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

    if args.config:
        try:
            config = config_loader.load_config(args.config)
            logging.info(f"Loaded configuration from {args.config}")
        except Exception as e:
            logging.error(f"Failed to load configuration from {args.config}: {e}")
            config = config_loader.create_default_config()
    else:
        # Try to load last session config
        last_session = os.path.join(data_dir, "configs", "last-session.yaml")
        if os.path.exists(last_session):
            try:
                config = config_loader.load_config(last_session)
                logging.info(f"Loaded last session configuration from {last_session}")
            except Exception as e:
                logging.warning(f"Failed to load last session config: {e}")
                config = config_loader.create_default_config()
        else:
            config = config_loader.create_default_config()
            logging.info("Created default configuration (no previous session found)")

    # Sync CLI port argument to config so GUI shows correct value
    config["gui_port"] = args.port

    # Initialize backend manager (but don't start any processes yet)
    backend_manager = BackendManager(data_dir)

    # Create and start the Dash application
    app = create_app(config, data_dir, backend_manager)

    # Set up signal handlers for graceful exit
    handle_exit(app, backend_manager)

    # Start the Dash server
    logging.info(f"Starting Nanometa Live v{__version__} server on port {args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()