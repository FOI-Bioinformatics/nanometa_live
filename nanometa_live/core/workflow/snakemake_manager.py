"""
Snakemake workflow manager for Nanometa Live.

This module provides a clean interface to the Snakemake workflow system,
handling configuration, execution, and monitoring of the pipeline.
"""

import os
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import snakemake


class SnakemakeManager:
    """Manages Snakemake workflow execution and monitoring."""

    def __init__(self, data_dir: str):
        """
        Initialize the Snakemake manager.

        Args:
            data_dir: Base directory for storing data and logs
        """
        self.data_dir = data_dir
        self.log_dir = os.path.join(data_dir, "logs")
        self.snakefile_path = None
        self.config_path = None
        self.workflow = None
        self.execution_lock = threading.Lock()
        self.running = False
        self.status = {
            "running": False,
            "rules_complete": 0,
            "rules_running": 0,
            "total_jobs": 0,
            "jobs_complete": 0,
            "jobs_running": 0,
            "last_updated": None,
            "errors": [],
        }

        # Create logs directory
        os.makedirs(self.log_dir, exist_ok=True)

    def setup(self, config_path: str) -> Tuple[bool, str]:
        """
        Set up the Snakemake workflow.

        Args:
            config_path: Path to the configuration file

        Returns:
            Tuple of (success, message)
        """
        try:
            self.config_path = config_path

            # Find the Snakefile
            import nanometa_live

            package_dir = os.path.dirname(nanometa_live.__file__)
            self.snakefile_path = os.path.join(package_dir, "Snakefile")

            if not os.path.exists(self.snakefile_path):
                return False, f"Snakefile not found at {self.snakefile_path}"

            return True, "Snakemake workflow setup successfully"

        except Exception as e:
            logging.error(f"Error setting up Snakemake workflow: {e}")
            return False, f"Error setting up Snakemake workflow: {e}"

    def start(self, cores: int = 1, dryrun: bool = False) -> Tuple[bool, str]:
        """
        Start the Snakemake workflow.

        Args:
            cores: Number of CPU cores to use
            dryrun: Whether to perform a dry run

        Returns:
            Tuple of (success, message)
        """
        with self.execution_lock:
            if self.running:
                return False, "Workflow is already running"

            if not self.snakefile_path or not self.config_path:
                return False, "Workflow not set up. Call setup() first."

            try:
                # Start the workflow in a separate thread
                threading.Thread(
                    target=self._run_workflow, args=(cores, dryrun), daemon=True
                ).start()

                # Update status
                self.running = True
                self.status["running"] = True
                self.status["last_updated"] = time.time()

                return True, f"Snakemake workflow started with {cores} cores"

            except Exception as e:
                logging.error(f"Error starting Snakemake workflow: {e}")
                return False, f"Error starting Snakemake workflow: {e}"

    def stop(self) -> Tuple[bool, str]:
        """
        Stop the Snakemake workflow.

        Returns:
            Tuple of (success, message)
        """
        with self.execution_lock:
            if not self.running:
                return False, "Workflow is not running"

            try:
                # Flag to stop the workflow
                self.running = False

                # Update status
                self.status["running"] = False
                self.status["last_updated"] = time.time()

                return True, "Snakemake workflow stopping (may take a moment)"

            except Exception as e:
                logging.error(f"Error stopping Snakemake workflow: {e}")
                return False, f"Error stopping Snakemake workflow: {e}"

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the workflow.

        Returns:
            Dictionary with status information
        """
        return self.status

    def _run_workflow(self, cores: int, dryrun: bool):
        """
        Run the Snakemake workflow.

        Args:
            cores: Number of CPU cores to use
            dryrun: Whether to perform a dry run
        """
        try:
            log_file = os.path.join(self.log_dir, "snakemake.log")

            with open(log_file, "w") as log:
                # Run Snakemake using the Python API
                success = snakemake.snakemake(
                    self.snakefile_path,
                    cores=cores,
                    configfiles=[self.config_path],
                    workdir=os.path.dirname(self.config_path),
                    dryrun=dryrun,
                    printshellcmds=True,
                    printreason=True,
                    printrulegraph=True,
                    stats=os.path.join(self.log_dir, "stats.json"),
                    unlock=False,
                    keepgoing=True,
                    quiet=False,
                    log_handler=[log],
                )

                if not success:
                    self.status["errors"].append("Snakemake workflow failed")

        except Exception as e:
            logging.error(f"Error in Snakemake workflow: {e}")
            self.status["errors"].append(str(e))

        finally:
            # Update status on completion
            self.running = False
            self.status["running"] = False
            self.status["last_updated"] = time.time()


class SnakemakeExecutor:
    """Executes Snakemake workflow via subprocess (alternative implementation)."""

    def __init__(self, data_dir: str):
        """
        Initialize the Snakemake executor.

        Args:
            data_dir: Base directory for storing data and logs
        """
        self.data_dir = data_dir
        self.log_dir = os.path.join(data_dir, "logs")
        self.process = None
        self.status_thread = None
        self.running = False
        self.status = {"running": False, "last_updated": None, "errors": []}

        # Create logs directory
        os.makedirs(self.log_dir, exist_ok=True)

    def start(self, config_path: str, cores: int = 1) -> Tuple[bool, str]:
        """
        Start the Snakemake workflow as a subprocess.

        Args:
            config_path: Path to the configuration file
            cores: Number of CPU cores to use

        Returns:
            Tuple of (success, message)
        """
        if self.running:
            return False, "Workflow is already running"

        try:
            log_file = os.path.join(self.log_dir, "snakemake.log")

            with open(log_file, "w") as log:
                # Find the Snakefile
                import nanometa_live

                package_dir = os.path.dirname(nanometa_live.__file__)
                snakefile_path = os.path.join(package_dir, "Snakefile")

                # Build the command
                cmd = [
                    "snakemake",
                    "--snakefile",
                    snakefile_path,
                    "--configfile",
                    config_path,
                    "--cores",
                    str(cores),
                    "--printshellcmds",
                    "--verbose",
                ]

                # Start the process
                self.process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=os.path.dirname(config_path),
                )

                # Start monitoring thread
                self.running = True
                self.status["running"] = True
                self.status["last_updated"] = time.time()

                self.status_thread = threading.Thread(
                    target=self._monitor_status, daemon=True
                )
                self.status_thread.start()

                return True, f"Snakemake workflow started with {cores} cores"

        except Exception as e:
            logging.error(f"Error starting Snakemake workflow: {e}")
            return False, f"Error starting Snakemake workflow: {e}"

    def stop(self) -> Tuple[bool, str]:
        """
        Stop the Snakemake workflow.

        Returns:
            Tuple of (success, message)
        """
        if not self.running:
            return False, "Workflow is not running"

        try:
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()

            self.running = False
            self.status["running"] = False
            self.status["last_updated"] = time.time()

            return True, "Snakemake workflow stopped"

        except Exception as e:
            logging.error(f"Error stopping Snakemake workflow: {e}")
            return False, f"Error stopping Snakemake workflow: {e}"

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the workflow.

        Returns:
            Dictionary with status information
        """
        return self.status

    def _monitor_status(self):
        """Monitor the status of the Snakemake subprocess."""
        while self.running and self.process:
            # Check if process is still running
            if self.process.poll() is not None:
                self.running = False
                self.status["running"] = False

                if self.process.returncode != 0:
                    self.status["errors"].append(
                        f"Snakemake process exited with code {self.process.returncode}"
                    )

                break

            # Update timestamp
            self.status["last_updated"] = time.time()

            # Sleep for a bit
            time.sleep(5)
