"""
Backend manager for Nanometa Live.

This module manages the backend processes for the application, including:
- Starting/stopping the Nextflow workflow (nanometanf pipeline)
- Monitoring the processing status
- Checking files and directories
"""

import os
import sys
import time
import json
import logging
import threading
import fcntl
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, IO
from pathlib import Path
import subprocess

from nanometa_live.core.workflow.nextflow_manager import NextflowManager


class BackendManager:
    """Manages backend processes for Nanometa Live using nanometanf pipeline."""

    def __init__(self, data_dir: str):
        """
        Initialize the BackendManager.

        Args:
            data_dir: Directory where application data is stored
        """
        self.data_dir = data_dir
        self.log_dir = os.path.join(data_dir, "logs")
        self.workflow_manager = NextflowManager(data_dir)  # Using NextflowManager
        self.config = None
        self.status_thread = None
        self._status_lock = threading.Lock()  # Thread safety for status updates
        # Note: legacy _prep_status_lock removed along with prepare_data methods
        self._lock_fd: Optional[IO] = None  # File lock descriptor for multi-user safety
        self._lock_file_path: Optional[str] = None  # Path to lock file
        self.status = {
            "running": False,
            "pipeline_status": "idle",
            "files_processed": 0,
            "files_waiting": 0,
            "current_batch": 0,
            "processes_running": 0,
            "processes_complete": 0,
            "last_update": None,
            "start_time": None,
            "errors": [],
        }

        # Create logs directory
        os.makedirs(self.log_dir, exist_ok=True)

        logging.info("BackendManager initialized with NextflowManager")

    # Blocked path prefixes for security
    BLOCKED_PATH_PREFIXES = [
        "/etc", "/usr", "/var", "/root", "/proc", "/sys", "/dev",
        "/boot", "/sbin", "/bin", "/lib", "/lib64"
    ]

    @staticmethod
    def _validate_path(
        path: str,
        description: str = "path",
        must_exist: bool = True,
        allow_creation: bool = False
    ) -> str:
        """
        Validate a path before using it in subprocess calls.

        Security checks:
        - Path traversal detection (..)
        - Blocked system directories
        - Path resolution to absolute path

        Args:
            path: Path to validate
            description: Description for error messages
            must_exist: If True, path must exist (default True for input paths)
            allow_creation: If True, allow paths that don't exist (for output dirs)

        Returns:
            Resolved absolute path if valid

        Raises:
            ValueError: If path fails validation
        """
        if not path or not path.strip():
            raise ValueError(f"Empty {description} provided")

        # Strip whitespace
        path = path.strip()

        # Check for path traversal attempts
        if ".." in path:
            logging.error(f"Path traversal detected in {description}: {path}")
            raise ValueError(
                f"Path traversal detected in {description}. "
                f"Paths containing '..' are not allowed for security reasons."
            )

        # Resolve to absolute path
        try:
            resolved = os.path.abspath(os.path.expanduser(path))
        except Exception as e:
            raise ValueError(f"Invalid {description}: {e}")

        # Check against blocked prefixes
        for prefix in BackendManager.BLOCKED_PATH_PREFIXES:
            if resolved.startswith(prefix):
                logging.error(f"Blocked path prefix detected in {description}: {resolved}")
                raise ValueError(
                    f"Access to system directory '{prefix}' is not allowed for {description}. "
                    f"Please use a path in your home directory or designated data directories."
                )

        # Check existence
        if must_exist and not allow_creation:
            if not os.path.exists(resolved):
                raise ValueError(f"{description} does not exist: {resolved}")

        # For output paths that can be created, check parent exists
        if allow_creation and not os.path.exists(resolved):
            parent = os.path.dirname(resolved)
            if parent and not os.path.exists(parent):
                raise ValueError(
                    f"Parent directory for {description} does not exist: {parent}"
                )

        logging.debug(f"Path validated for {description}: {resolved}")
        return resolved

    @staticmethod
    def _validate_path_for_output(path: str, description: str = "output path") -> str:
        """
        Validate a path intended for output (may not exist yet).

        Args:
            path: Path to validate
            description: Description for error messages

        Returns:
            Resolved absolute path if valid
        """
        return BackendManager._validate_path(
            path, description, must_exist=False, allow_creation=True
        )

    def _acquire_lock(self, results_dir: str) -> Tuple[bool, str]:
        """
        Acquire exclusive lock on results directory to prevent multi-user collisions.

        Uses file-based locking (fcntl) to ensure only one pipeline can write
        to a given results directory at a time.

        Args:
            results_dir: Path to the results directory to lock

        Returns:
            Tuple of (success: bool, message: str)
        """
        lock_file = os.path.join(results_dir, ".nanometa.lock")
        self._lock_file_path = lock_file

        try:
            # Create/open lock file
            self._lock_fd = open(lock_file, 'w')

            # Try to acquire exclusive, non-blocking lock
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write lock info for debugging
            lock_info = {
                "pid": os.getpid(),
                "hostname": os.uname().nodename,
                "user": os.environ.get("USER", "unknown"),
                "acquired_at": datetime.now().isoformat(),
                "data_dir": self.data_dir
            }
            self._lock_fd.write(json.dumps(lock_info, indent=2))
            self._lock_fd.flush()

            logging.info(f"Acquired lock on results directory: {results_dir}")
            return True, "Lock acquired successfully"

        except BlockingIOError:
            # Another process has the lock
            existing_info = ""
            try:
                with open(lock_file, 'r') as f:
                    existing_info = f.read()
            except Exception:
                pass

            error_msg = (
                f"Another pipeline is already running in this directory. "
                f"Lock file: {lock_file}"
            )
            if existing_info:
                error_msg += f"\nLock info: {existing_info}"

            logging.error(error_msg)
            self._lock_fd = None
            return False, error_msg

        except Exception as e:
            logging.error(f"Error acquiring lock: {e}")
            if self._lock_fd:
                self._lock_fd.close()
                self._lock_fd = None
            return False, f"Error acquiring lock: {e}"

    def _release_lock(self) -> None:
        """
        Release the exclusive lock on results directory.

        Safe to call even if no lock is held.
        """
        if self._lock_fd:
            try:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                self._lock_fd.close()
                logging.info("Released lock on results directory")
            except Exception as e:
                logging.warning(f"Error releasing lock: {e}")
            finally:
                self._lock_fd = None

        # Clean up lock file
        if self._lock_file_path and os.path.exists(self._lock_file_path):
            try:
                os.remove(self._lock_file_path)
            except OSError:
                pass  # File may already be removed
            self._lock_file_path = None

    def setup_project(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Set up a project with the given configuration."""
        # Ensure we're working with a copy
        self.config = dict(config)

        # Validate required directories
        if not self.config.get("nanopore_output_directory"):
            return False, "Nanopore output directory is required"

        if not self.config.get("kraken_db"):
            return False, "Kraken database is required"

        # Ensure boolean parameters are strictly boolean
        if "kraken_memory_mapping" in self.config:
            self.config["kraken_memory_mapping"] = bool(self.config["kraken_memory_mapping"])

        if "blast_validation" in self.config:
            self.config["blast_validation"] = bool(self.config["blast_validation"])

        if "remove_temp_files" in self.config:
            self.config["remove_temp_files"] = bool(self.config["remove_temp_files"])

        # Create required directories
        main_dir = self.config.get("main_dir")
        if not main_dir:
            # Create a timestamped directory in the data directory
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            main_dir = os.path.join(self.data_dir, "data", f"analysis_{timestamp}")
            self.config["main_dir"] = main_dir

        os.makedirs(main_dir, exist_ok=True)

        # Note: nanometanf creates its own output structure, but we keep config here
        # Write configuration to project directory (JSON format for Nextflow)
        config_path = os.path.join(main_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(self.config, f, indent=2)

        # Update pipeline source if specified in config
        pipeline_source = self.config.get("pipeline_source", "remote:main")
        self.workflow_manager.set_pipeline_source(pipeline_source)

        # Set up Nextflow workflow
        success, message = self.workflow_manager.setup(config_path)
        if not success:
            return False, message

        logging.info(f"Project set up successfully in {main_dir}")
        return True, f"Project set up successfully in {main_dir}"

    def can_resume(self) -> bool:
        """
        Check if a previous run can be resumed.

        Returns:
            True if work directory contains resumable state
        """
        work_dir = os.path.join(self.data_dir, "work")
        if not os.path.exists(work_dir):
            return False

        # Check for Nextflow cache files (indicates resumable state)
        # Nextflow stores task cache in .nextflow/ and work/
        nextflow_cache = os.path.join(self.data_dir, ".nextflow")
        has_cache = os.path.exists(nextflow_cache)

        # Also check for any completed tasks in work directory
        has_work = any(
            os.path.isdir(os.path.join(work_dir, d))
            for d in os.listdir(work_dir)
            if len(d) == 2  # Nextflow work dirs are 2-char hex prefixes
        )

        return has_cache or has_work

    def start(self, profile: str = None, resume: bool = False) -> Tuple[bool, str]:
        """
        Start the backend processes.

        Args:
            profile: Nextflow profile to use (docker, singularity, conda).
                     If None, uses the value from config or defaults to 'docker'.
            resume: Whether to resume from a previous run (uses Nextflow -resume flag).
                    When True, Nextflow will reuse cached results from prior execution.

        Returns:
            Tuple of (success, message)
        """
        if self.status.get("running"):
            return False, "Backend is already running"

        if not self.config:
            return False, "No configuration loaded"

        # Check if resume is requested but not possible
        if resume and not self.can_resume():
            logging.warning("Resume requested but no previous run found. Starting fresh.")
            resume = False

        # Set up the project
        success, message = self.setup_project(self.config)
        if not success:
            return False, message

        # Acquire exclusive lock on results directory to prevent multi-user collisions
        results_dir = self.config.get("main_dir", self.data_dir)
        lock_success, lock_message = self._acquire_lock(results_dir)
        if not lock_success:
            return False, lock_message

        # Get profile from config if not explicitly passed
        if profile is None:
            profile = self.config.get("pipeline_profile", "docker")

        # Start the Nextflow workflow
        cores = self.config.get("snakemake_cores", None)  # Keep param name for compatibility
        success, message = self.workflow_manager.start(profile=profile, cores=cores, resume=resume)
        if not success:
            self._release_lock()  # Release lock on failure
            return False, message

        # Mark as running with start time for elapsed time tracking (thread-safe)
        with self._status_lock:
            self.status["running"] = True
            self.status["pipeline_status"] = "running"
            self.status["start_time"] = datetime.now().isoformat()
            self.status["last_update"] = time.time()

        # Start status monitoring thread
        self.status_thread = threading.Thread(target=self._monitor_status, daemon=True)
        self.status_thread.start()

        logging.info(f"Backend started successfully with profile: {profile}")
        return True, f"Backend started successfully with profile: {profile}"

    def stop(self) -> Tuple[bool, str]:
        """
        Stop the backend processes.

        Returns:
            Tuple of (success, message)
        """
        if not self.status.get("running"):
            return False, "Backend is not running"

        # Stop the Nextflow workflow
        success, message = self.workflow_manager.stop()
        if not success:
            # Still release lock even if stop fails
            self._release_lock()
            return False, message

        # Release exclusive lock on results directory
        self._release_lock()

        # Mark as stopped (thread-safe)
        with self._status_lock:
            self.status["running"] = False
            self.status["pipeline_status"] = "stopped"
            self.status["last_update"] = time.time()

        logging.info("Backend stopped successfully")
        return True, "Backend stopped successfully"

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the backend.

        Returns:
            Dictionary with status information including pipeline stages
        """
        # Update with Nextflow workflow manager status
        workflow_status = self.workflow_manager.get_status()

        # Thread-safe status update
        with self._status_lock:
            # Update pipeline status based on workflow status
            if workflow_status.get("running"):
                self.status["pipeline_status"] = "running"
            elif len(workflow_status.get("errors", [])) > 0:
                self.status["pipeline_status"] = "error"
                # Replace errors with current workflow errors to prevent unbounded growth
                # from repeated polling; deduplicate to avoid duplicate entries
                existing = set(self.status["errors"])
                for err in workflow_status.get("errors", []):
                    if err not in existing:
                        self.status["errors"].append(err)
                        existing.add(err)
            elif self.status.get("running"):
                self.status["pipeline_status"] = "stopping"
            else:
                self.status["pipeline_status"] = "stopped"

            # Update process and batch information from workflow manager
            self.status["processes_running"] = workflow_status.get("processes_running", 0)
            self.status["processes_complete"] = workflow_status.get("processes_complete", 0)
            self.status["files_processed"] = workflow_status.get("files_processed", 0)
            self.status["current_batch"] = workflow_status.get("current_batch", 0)

            # Update stage-level tracking for dashboard display
            self.status["stages"] = workflow_status.get("stages", [])
            self.status["current_stage"] = workflow_status.get("current_stage", None)
            self.status["stage_progress"] = workflow_status.get("stage_progress", {})
            self.status["processes_failed"] = workflow_status.get("processes_failed", 0)
            self.status["total_processes"] = workflow_status.get("total_processes", 0)

            # If we're running, update additional file counts
            if self.status.get("running") and self.config:
                self._update_file_counts()

            # Return a copy to prevent external modification
            return dict(self.status)

    def _update_file_counts(self):
        """Update the file processing counts from the file system."""
        try:
            nanopore_dir = self.config.get("nanopore_output_directory", "")

            # Count files in nanopore directory (including barcode subdirs)
            waiting_files = 0
            extensions = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
            if os.path.exists(nanopore_dir):
                for f in os.listdir(nanopore_dir):
                    if f.endswith(extensions):
                        waiting_files += 1
                # Also count files in barcode subdirectories
                for subdir in os.listdir(nanopore_dir):
                    subdir_path = os.path.join(nanopore_dir, subdir)
                    if os.path.isdir(subdir_path) and subdir.startswith("barcode"):
                        for f in os.listdir(subdir_path):
                            if f.endswith(extensions):
                                waiting_files += 1

            # Update status with waiting files
            # Processed files comes from workflow_manager status
            self.status["files_waiting"] = waiting_files

        except Exception as e:
            logging.error(f"Error updating file counts: {e}")

    def _monitor_status(self):
        """Monitor the status of the backend processes in a separate thread."""
        logging.info("Status monitoring thread started")

        while self.status.get("running"):
            try:
                # Get workflow manager status
                workflow_status = self.workflow_manager.get_status()

                # Thread-safe status update
                with self._status_lock:
                    # Update status based on workflow status
                    if (
                        not workflow_status.get("running")
                        and len(workflow_status.get("errors", [])) > 0
                    ):
                        self.status["pipeline_status"] = "error"
                        # Deduplicate to avoid unbounded growth from repeated polling
                        existing = set(self.status["errors"])
                        for err in workflow_status.get("errors", []):
                            if err not in existing:
                                self.status["errors"].append(err)
                                existing.add(err)
                        self.status["running"] = False
                        logging.error("Pipeline encountered errors, stopping")

                    # Update process information
                    self.status["processes_running"] = workflow_status.get("processes_running", 0)
                    self.status["processes_complete"] = workflow_status.get("processes_complete", 0)
                    self.status["files_processed"] = workflow_status.get("files_processed", 0)
                    self.status["current_batch"] = workflow_status.get("current_batch", 0)

                    # Update file counts
                    self._update_file_counts()

                    # Update last update time
                    self.status["last_update"] = time.time()

                # Sleep for a bit
                time.sleep(5)

            except Exception as e:
                logging.error(f"Error in monitoring thread: {e}")
                time.sleep(5)

        # Release lock when monitoring thread exits (pipeline completed or stopped)
        self._release_lock()
        logging.info("Status monitoring thread stopped")


