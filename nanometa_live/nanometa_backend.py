#!/usr/bin/env python3
"""
Backend process for Nanometa Live.

This script handles the execution of the Snakemake workflow for processing
nanopore sequence data. It can be run independently of the main application
for headless processing.
"""

import os
import sys
import argparse
import logging
import time
import signal
from pathlib import Path

# Update this import
from snakemake.api import SnakemakeApi

from nanometa_live import __version__
from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.workflow.snakemake_manager import SnakemakeManager


def setup_logging(debug=False, log_file=None):
    """
    Set up logging configuration.

    Args:
        debug: Whether to use debug level logging
        log_file: Optional file to write logs to
    """
    log_level = logging.DEBUG if debug else logging.INFO
    log_format = "%(asctime)s - %(levelname)s - %(message)s"

    # Configure root logger
    logging.basicConfig(
        level=log_level, format=log_format, handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(log_format))
        logging.getLogger().addHandler(file_handler)


def parse_arguments():
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Nanometa Live Backend: Run metagenomic analysis workflow"
    )

    parser.add_argument(
        "--config", help="Path to the configuration file", required=True
    )

    parser.add_argument(
        "--cores", type=int, default=1, help="Number of CPU cores to use (default: 1)"
    )

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    parser.add_argument("--log-file", help="Path to write log file")

    parser.add_argument(
        "--version", action="version", version=f"Nanometa Live Backend v{__version__}"
    )

    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Perform a dry run without executing commands",
    )

    parser.add_argument(
        "--unlock", action="store_true", help="Unlock the working directory"
    )

    return parser.parse_args()


def handle_exit(snakemake_manager):
    """
    Set up signal handlers for graceful exit.

    Args:
        snakemake_manager: SnakemakeManager instance to stop on exit
    """

    def signal_handler(sig, frame):
        """Handle signals by stopping workflow and exiting."""
        logging.info("Stopping workflow...")
        snakemake_manager.stop()
        sys.exit(0)

    # Set up handlers for various signals
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Kill command


def unlock_workdir(config_path):
    """
    Unlock the Snakemake working directory.

    Args:
        config_path: Path to the configuration file

    Returns:
        True if successful, False otherwise
    """
    try:
        # Find the Snakefile
        import nanometa_live

        package_dir = os.path.dirname(nanometa_live.__file__)
        snakefile_path = os.path.join(package_dir, "Snakefile")

        # Get the working directory
        config_loader = ConfigLoader("")
        config = config_loader.load_config(config_path)
        workdir = config.get("main_dir", os.path.dirname(config_path))

        # Unlock the working directory using the new API - use correct parameters
        api = SnakemakeApi(
            snakefile=snakefile_path,  # Use snakefile, not workflow
            unlock=True,
            workdir=workdir,
            quiet=False
        )
        success = api.execute()

        return success
    except Exception as e:
        logging.error(f"Error unlocking working directory: {e}")
        return False


def main():
    """
    Main function to run the Nanometa Live backend.
    """
    # Parse arguments
    args = parse_arguments()

    # Set up logging
    setup_logging(args.debug, args.log_file)

    # Log startup information
    logging.info(f"Nanometa Live Backend v{__version__}")
    logging.info(f"Configuration file: {args.config}")
    logging.info(f"CPU cores: {args.cores}")

    # Unlock mode if requested
    if args.unlock:
        logging.info("Unlocking working directory...")
        if unlock_workdir(args.config):
            logging.info("Working directory unlocked successfully.")
            return 0
        else:
            logging.error("Failed to unlock working directory.")
            return 1

    # Create data directory
    data_dir = os.path.dirname(args.config)
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)

    # Initialize SnakemakeManager
    snakemake_manager = SnakemakeManager(data_dir)

    # Set up signal handlers
    handle_exit(snakemake_manager)

    # Set up workflow
    success, message = snakemake_manager.setup(args.config)
    if not success:
        logging.error(f"Failed to set up workflow: {message}")
        return 1

    logging.info(message)

    # Start workflow
    success, message = snakemake_manager.start(cores=args.cores, dryrun=args.dryrun)
    if not success:
        logging.error(f"Failed to start workflow: {message}")
        return 1

    logging.info(message)

    # Wait for workflow to complete or be interrupted
    try:
        while snakemake_manager.running:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Stopping workflow...")
        snakemake_manager.stop()
        return 1

    # Check for errors
    status = snakemake_manager.get_status()
    if status.get("errors"):
        logging.error("Workflow completed with errors:")
        for error in status.get("errors", []):
            logging.error(f"  - {error}")
        return 1

    logging.info("Workflow completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())