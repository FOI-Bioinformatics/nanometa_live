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
from nanometa_live.core.utils.paths import set_data_dir_env, set_project_dir_env


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
        "--data-dir",
        help="Directory for SHARED app data -- taxonomy cache, reference "
             "genomes, BLAST and Kraken2 databases (default: ~/.nanometa)",
    )

    parser.add_argument(
        "--project",
        help="Project directory for this analysis. Per-analysis state "
             "(session config, watchlist selection, taxid mappings) is kept "
             "in <project>/.nanometa/ (default: current working directory)",
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
    # Raise the per-process file descriptor soft limit toward the hard
    # limit at the earliest possible moment, before any module-level
    # singletons (diskcache, watchlist manager, taxonomy api clients)
    # have a chance to open their first handles. Without this lift the
    # Linux default of 1024-4096 fds is exhausted within hours by the
    # combination of DiskcacheManager workers, the fingerprint walker
    # (up to 50000 stat calls per tick), psutil /proc scans, and
    # Werkzeug threaded request handling.
    from nanometa_live.core.utils.rlimit import raise_fd_soft_limit
    _fd_before, _fd_after = raise_fd_soft_limit()
    if _fd_after > _fd_before > 0:
        logging.info(
            "Raised RLIMIT_NOFILE soft limit: %d -> %d",
            _fd_before, _fd_after,
        )

    # Parse arguments
    args = parse_arguments()

    # Set up data directory. Normalise the operator-supplied value
    # so a stray ``~``, trailing ``/``, or accidental leading ``//``
    # (POSIX preserves ``//`` at the head of a path) does not flow
    # downstream into the Storage Locations panel and makedirs calls.
    if args.data_dir:
        data_dir = os.path.abspath(os.path.expanduser(args.data_dir))
    else:
        data_dir = os.path.expanduser("~/.nanometa")
    # os.path.abspath / normpath preserve a leading "//" by POSIX
    # rule; collapse it explicitly so Storage Locations renders the
    # same path the operator typed.
    while data_dir.startswith("//"):
        data_dir = data_dir[1:]

    # Set the env var BEFORE any module-level singleton (offline cache,
    # background-callback Diskcache) gets a chance to read the legacy
    # default. The env var is the only mechanism available to import-
    # time consumers; config-aware consumers prefer
    # ``NanometaPaths.from_config(config)``.
    set_data_dir_env(data_dir)

    # Project directory anchors per-analysis state (session, watchlist
    # selection, taxid mappings) under <project_dir>/.nanometa/. Set the env
    # too so project-scoped singletons (e.g. the taxid mapper, constructed
    # before a config is loaded) resolve to the same place as config-aware
    # callers via NanometaPaths.
    project_dir = (
        os.path.abspath(os.path.expanduser(args.project))
        if args.project else os.getcwd()
    )
    set_project_dir_env(project_dir)

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
        # Boot is always fresh. We never silently rehydrate
        # ~/.nanometa/configs/last-session.yaml -- a prior configuration
        # is restored deliberately from Configuration > Load, and a
        # finished run's data is viewed via the "Open Results" control
        # in the secondary bar. The autosave on Apply Settings still
        # populates the "Last Session" entry in the Load modal.
        config = config_loader.create_default_config()
        logging.info("Starting with default configuration (boot is fresh by design).")

    # Sync CLI arguments to config
    # data_dir is now a first-class config key so every subsystem can
    # read the resolved value via NanometaPaths.from_config(config),
    # rather than each module embedding its own ~/.nanometa fallback.
    config["data_dir"] = data_dir
    # Project directory anchors per-analysis state under
    # <project_dir>/.nanometa/ (see NanometaPaths). Defaults to the current
    # working directory so running the app from an analysis folder keeps that
    # project's session/watchlist/mappings local to it, while genomes and
    # caches stay shared under --data-dir. (project_dir + its env var were
    # resolved above, before singletons could read them.)
    config["project_dir"] = project_dir
    config["gui_port"] = args.port
    if args.main_dir:
        config["results_output_directory"] = os.path.abspath(args.main_dir)
        config["main_dir"] = os.path.abspath(args.main_dir)
        logging.info(f"Results directory set to {args.main_dir}")

    # Make the genome / BLAST cache follow --data-dir. The default in
    # ConfigLoader.create_default_config is the legacy "~/.nanometa"
    # value; when the operator points the app at a different
    # data_dir, downloaded genomes and BLAST indices should land
    # under that root rather than silently writing to ~/.nanometa.
    # Operator-explicit overrides (anything that does not match the
    # legacy default after expansion) are preserved.
    legacy_default = os.path.expanduser("~/.nanometa")
    current = config.get("genome_cache_dir") or ""
    if not current or os.path.expanduser(current) == legacy_default:
        if data_dir != legacy_default:
            logging.info(
                "Pointing genome_cache_dir at --data-dir (%s); "
                "previously-downloaded genomes under %s will not be reused.",
                data_dir, legacy_default,
            )
        config["genome_cache_dir"] = data_dir

    # Initialize backend manager (but don't start any processes yet)
    backend_manager = BackendManager(data_dir)

    # Create and start the Dash application
    app = create_app(config, data_dir, backend_manager)

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