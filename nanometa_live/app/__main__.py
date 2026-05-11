#!/usr/bin/env python3
"""
Entry point for running the app package as a module.

Allows: python -m nanometa_live.app --main_dir /path/to/data
"""

import os
import sys
import argparse
import logging

# Import the main entry point
from nanometa_live.nanometa_live import main as nanometa_main
from nanometa_live import __version__
from nanometa_live.app.app import create_app
from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.utils.logging_utils import setup_logging


def parse_arguments():
    """Parse command-line arguments with support for --main_dir."""
    parser = argparse.ArgumentParser(
        description="Nanometa Live: Real-time metagenomic analysis"
    )

    parser.add_argument(
        "--main_dir",
        "--main-dir",
        dest="main_dir",
        help="Directory containing nanometanf output for visualization only (no pipeline execution)",
    )

    parser.add_argument(
        "--config", help="Path to an existing configuration file to load on startup"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Port to run the dashboard on (default: 8050)",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the server to (default: 127.0.0.1, use 0.0.0.0 for network access)",
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


logger = logging.getLogger(__name__)


def main():
    """Main entry point for app module."""
    # Raise the per-process file descriptor soft limit toward the hard
    # limit at startup. See nanometa_live/core/utils/rlimit.py for the
    # rationale -- defaults of 1024-4096 are too low for the GUI's
    # long-running DiskcacheManager + Werkzeug + fingerprint walker
    # combination.
    from nanometa_live.core.utils.rlimit import raise_fd_soft_limit
    _fd_before, _fd_after = raise_fd_soft_limit()
    if _fd_after > _fd_before > 0:
        logger.info(
            "Raised RLIMIT_NOFILE soft limit: %d -> %d",
            _fd_before, _fd_after,
        )

    args = parse_arguments()

    # If --main_dir is provided, run in visualization-only mode
    if args.main_dir:
        # Set up minimal logging
        if args.debug:
            logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
        else:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

        # Simple visualization mode - parse existing data and display
        logger.info("Starting Nanometa Live in visualization mode")
        logger.info("Data directory: %s", args.main_dir)
        logger.info("Server: http://localhost:%s", args.port)
        logger.info("No pipeline execution - displaying existing data only")

        # Verify directory exists
        if not os.path.exists(args.main_dir):
            logger.error("Directory not found: %s", args.main_dir)
            sys.exit(1)

        # Create minimal data directory
        data_dir = args.data_dir if args.data_dir else os.path.expanduser("~/.nanometa")
        os.makedirs(data_dir, exist_ok=True)

        # Set NANOMETA_DATA_DIR before any singleton (offline cache,
        # background-callback Diskcache) reads the legacy default. The
        # full-mode entry point in nanometa_live.py does the same thing.
        from nanometa_live.core.utils.paths import set_data_dir_env
        set_data_dir_env(data_dir)

        # Create config pointing to the main_dir
        config = {
            "data_dir": data_dir,
            "main_dir": args.main_dir,
            "visualization_only": True,
        }

        # Initialize backend manager (won't start any processes)
        backend_manager = BackendManager(data_dir)

        # Create app
        app = create_app(config, data_dir, backend_manager)

        # Start server
        app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)

    else:
        # Full mode - use the main nanometa_live entry point
        nanometa_main()


if __name__ == "__main__":
    main()
