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
import pandas as pd
import subprocess
import zipfile, shutil

from nanometa_live.core.utils.file_utils import check_command_exists
from nanometa_live.core.workflow.nextflow_manager import NextflowManager
from nanometa_live.core.utils.database_utils import download_and_prepare_kraken_database
from nanometa_live.core.utils.data_utils import fetch_species_data, test_gtdb_api_directly


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
        self._prep_status_lock = threading.Lock()  # Thread safety for prep_status updates
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
                self.status["errors"].extend(workflow_status.get("errors", []))
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

            # Count files in nanopore directory
            waiting_files = 0
            if os.path.exists(nanopore_dir):
                waiting_files = len(
                    [
                        f
                        for f in os.listdir(nanopore_dir)
                        if f.endswith((".fastq", ".fastq.gz"))
                    ]
                )

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
                        self.status["errors"].extend(workflow_status.get("errors", []))
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

    def _update_progress(self, progress: int, message: str):
        """
        Update preparation progress.
        This is a helper method for callbacks.
        Thread-safe: uses _prep_status_lock.
        """
        with self._prep_status_lock:
            # Calculate the actual progress value based on the stage
            if self.prep_status["progress"] < 30:
                # We're in the database preparation stage (0-30%)
                self.prep_status["progress"] = progress
            else:
                # We're in a later stage, adjust progress accordingly
                self.prep_status["progress"] = 30 + int(progress * 0.7)

            self.prep_status["message"] = message
            self.prep_status["last_update"] = time.time()

    def _update_prep_status(
        self,
        message: Optional[str] = None,
        progress: Optional[int] = None,
        running: Optional[bool] = None,
        error: Optional[str] = None
    ):
        """
        Thread-safe helper to update prep_status fields.

        Args:
            message: Status message to set (optional)
            progress: Progress percentage 0-100 (optional)
            running: Running state (optional)
            error: Error message to append to errors list (optional)
        """
        with self._prep_status_lock:
            if message is not None:
                self.prep_status["message"] = message
            if progress is not None:
                self.prep_status["progress"] = progress
            if running is not None:
                self.prep_status["running"] = running
            if error is not None:
                self.prep_status["errors"].append(error)
            self.prep_status["last_update"] = time.time()

    def handle_external_kraken_database(self):
        """
        Check for and handle external Kraken2 database if specified in config.
        This method should be called from _run_data_preparation.
        Thread-safe: uses _update_prep_status() for status updates.
        """
        try:
            config = self.config

            # Check if an external Kraken2 database is specified
            external_db_key = (config.get("external_kraken2_db") or "").strip()
            external_db_info = config.get("external_kraken2_info", {})

            if external_db_key and external_db_key in external_db_info:
                self._update_prep_status(
                    message=f"Checking external Kraken2 database: {external_db_key}",
                    progress=10
                )

                # Prepare database folders
                kraken_db_folder = os.path.join(self.data_dir, "kraken2_databases")
                os.makedirs(kraken_db_folder, exist_ok=True)

                # Download and prepare the database
                success, message, db_path = download_and_prepare_kraken_database(
                    external_db_key,
                    external_db_info,
                    kraken_db_folder,
                    progress_callback=self._update_progress
                )

                if not success:
                    self._update_prep_status(
                        message=f"Error: {message}",
                        progress=100,
                        running=False,
                        error=message
                    )
                    return False

                # Update configuration with new database path
                if db_path:
                    # Get taxonomy from database info
                    db_details = external_db_info[external_db_key]
                    kraken_taxonomy = db_details.get("kraken_taxonomy", config.get("kraken_taxonomy", "gtdb"))

                    # Update config
                    config["kraken_db"] = os.path.abspath(db_path)
                    config["kraken_taxonomy"] = kraken_taxonomy
                    self.config = config

                    self._update_prep_status(
                        message=f"Successfully prepared external Kraken2 database: {external_db_key}",
                        progress=30
                    )

                return True

            return True  # No external database specified, continue with preparation

        except Exception as e:
            error_msg = f"Error handling external Kraken2 database: {str(e)}"
            self._update_prep_status(
                message=f"Error: {error_msg}",
                progress=100,
                running=False,
                error=error_msg
            )
            return False

    def prepare_data(self) -> Tuple[bool, str]:
        """
        Prepare data for analysis by:
        1. Checking for required external dependencies
        2. Extracting taxonomy IDs from Kraken database
        3. Downloading genome sequences for species of interest
        4. Building BLAST databases for validation

        Returns:
            Tuple of (success, message)
        """
        if not self.config:
            return False, "No configuration loaded"

        # Check for required external dependencies
        missing_deps = []
        if not check_command_exists("kraken2"):
            missing_deps.append("kraken2")
        if not check_command_exists("kraken2-inspect"):
            missing_deps.append("kraken2-inspect")
        if self.config.get("blast_validation", True):
            if not check_command_exists("makeblastdb"):
                missing_deps.append("makeblastdb")
            if not check_command_exists("blastn"):
                missing_deps.append("blastn")

        if missing_deps:
            missing_str = ", ".join(missing_deps)
            return False, f"Missing required dependencies: {missing_str}. Please install and ensure they are in your PATH."

        # Create a temporary progress file to track preparation progress
        self.prep_status = {
            "running": True,
            "progress": 0,
            "message": "Initializing data preparation...",
            "errors": [],
            "last_update": time.time()
        }

        # Start the preparation process in a background thread
        prep_thread = threading.Thread(target=self._run_data_preparation, daemon=True)
        prep_thread.start()

        return True, "Data preparation started"

    def get_preparation_status(self) -> Dict[str, Any]:
        """
        Get the current status of data preparation.
        Thread-safe: uses _prep_status_lock.

        Returns:
            Dictionary with preparation status information (copy to prevent external modification)
        """
        if not hasattr(self, 'prep_status'):
            return {
                "running": False,
                "progress": 0,
                "message": "No preparation in progress",
                "errors": [],
                "last_update": None
            }
        # Return a copy to prevent external modification
        with self._prep_status_lock:
            return dict(self.prep_status)

    def _run_data_preparation(self):
        """Run data preparation in a background thread."""
        try:
            config = self.config

            # STEP 1: Validate inputs and dependencies
            kraken_db = config.get("kraken_db", "")
            main_dir = config.get("main_dir", "")
            species_list = [s.get("name", "") for s in config.get("species_of_interest", [])]

            # Validate Kraken database
            if not kraken_db:
                self._update_prep_status(
                    message="Error: Kraken database path not specified",
                    progress=100, running=False,
                    error="Kraken database path not specified"
                )
                return

            if not os.path.exists(kraken_db):
                self._update_prep_status(
                    message=f"Error: Kraken database directory not found: {kraken_db}",
                    progress=100, running=False,
                    error=f"Kraken database directory not found: {kraken_db}"
                )
                return

            # Check if it's a valid Kraken database
            required_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]
            missing_files = [f for f in required_files if not os.path.exists(os.path.join(kraken_db, f))]

            if missing_files:
                missing_str = ", ".join(missing_files)
                self._update_prep_status(
                    message=f"Error: Invalid Kraken2 database: missing files {missing_str}",
                    progress=100, running=False,
                    error=f"Invalid Kraken2 database: missing files {missing_str}"
                )
                return

            # Validate species list
            if not species_list and not any(s.get("taxid") for s in config.get("species_of_interest", [])):
                self._update_prep_status(
                    message="Error: No species of interest defined. Please add species in the Configuration tab.",
                    progress=100, running=False,
                    error="No species of interest defined"
                )
                return

            # STEP 1.5: Check for external Kraken2 database
            if not self.handle_external_kraken_database():
                return  # Error occurred during database handling

            # STEP 2: Extract taxonomy IDs from Kraken database
            self._update_prep_status(
                message="Extracting taxonomy IDs from Kraken database...",
                progress=10
            )

            # Create data directories
            data_dir = os.path.join(main_dir, "data-files")
            os.makedirs(data_dir, exist_ok=True)

            # Run kraken2-inspect to get taxonomy IDs
            inspect_file = os.path.join(data_dir, f"{os.path.basename(kraken_db)}-inspect.txt")

            if not os.path.exists(inspect_file):
                try:
                    self._update_prep_status(
                        message="Running kraken2-inspect...",
                        progress=20
                    )

                    # Validate kraken_db path before subprocess call
                    self._validate_path(kraken_db, "Kraken database path")

                    cmd = ["kraken2-inspect", "--db", os.path.abspath(kraken_db)]
                    with open(inspect_file, 'w') as f:
                        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True)
                except subprocess.CalledProcessError as e:
                    self._update_prep_status(
                        message="Error running kraken2-inspect. Check if Kraken2 is properly installed.",
                        progress=100, running=False,
                        error=f"Error running kraken2-inspect: {e.stderr.decode() if e.stderr else str(e)}"
                    )
                    return

            # Parse the inspect file to extract taxonomy IDs
            self._update_prep_status(
                message="Parsing taxonomy information...",
                progress=30
            )

            # Define taxonomic level mappings
            level_mappings = {
                'S': 'species',
                'G': 'genus',
                'F': 'family',
                'O': 'order',
                'C': 'class',
                'P': 'phylum',
                'D': 'superkingdom',
                'K': 'kingdom'
            }

            species_taxids = {}
            try:
                with open(inspect_file, 'r') as f:
                    for line in f:
                        parts = line.strip().split('\t')
                        if len(parts) >= 6:  # At least 6 columns expected
                            # Column format: %krakenuniq, cumul reads, reads, level_type, taxid, name
                            level_type = parts[3]
                            taxid = parts[4]
                            name = parts[5].strip()

                            # Only process species level entries - checking both abbreviated and full names
                            if level_type == 'S' or level_type == 'species' or level_mappings.get(level_type) == 'species':
                                # Check if any of our species match this name
                                for species in species_list:
                                    if species and species.lower() in name.lower():
                                        species_taxids[species] = taxid
            except Exception as e:
                self._update_prep_status(
                    message=f"Error parsing taxonomy data: {str(e)}",
                    progress=100, running=False,
                    error=f"Error parsing inspect file: {e}"
                )
                return

            # Update config with taxonomy IDs
            self._update_prep_status(
                message="Updating configuration with taxonomy IDs...",
                progress=40
            )

            updated_species = []
            matched_species_count = 0

            for species in config.get("species_of_interest", []):
                name = species.get("name", "")
                taxid = species.get("taxid", "")

                # If taxid already provided, keep it
                if taxid:
                    updated_species.append(species)
                    matched_species_count += 1
                # Otherwise try to match by name
                elif name in species_taxids:
                    updated_species.append({
                        "name": name,
                        "taxid": species_taxids[name]
                    })
                    matched_species_count += 1
                else:
                    # Keep the original entry even if no match found
                    updated_species.append(species)

            # Check if we matched any species
            if matched_species_count == 0:
                self._update_prep_status(
                    message="Error: No species matched in the database. Check species names.",
                    progress=100, running=False,
                    error="No species matched in the database. Check species names."
                )
                return
            else:
                self._update_prep_status(
                    message=f"Found taxonomy IDs for {matched_species_count} out of {len(config.get('species_of_interest', []))} species.",
                    progress=45
                )

            self.config["species_of_interest"] = updated_species

            # STEP 3: Prepare directories for genome data
            self._update_prep_status(
                message="Setting up directories for genome data...",
                progress=45
            )

            # Create data directories
            data_dir = os.path.join(main_dir, "data-files")
            genomes_dir = os.path.join(data_dir, "genomes")
            os.makedirs(data_dir, exist_ok=True)
            os.makedirs(genomes_dir, exist_ok=True)

            # STEP 4: Check which genomes need to be downloaded
            self._update_prep_status(
                message="Checking for missing genome files...",
                progress=50
            )

            # Create a dictionary mapping species names to taxonomy IDs
            # FIXED: Make sure to include all species with valid taxids, even newly found ones
            species_to_taxid = {}
            for species in self.config["species_of_interest"]:
                name = species.get("name", "")
                taxid = species.get("taxid", "")
                if name and taxid:
                    species_to_taxid[name] = taxid

            # Check which genomes are missing
            missing_species = []
            for species, taxid in species_to_taxid.items():
                genome_file = os.path.join(genomes_dir, f"{taxid}.fasta")
                if not os.path.exists(genome_file):
                    missing_species.append(species)

            # STEP 5: Download missing genomes using GTDB API
            # Modified: Always proceed to download section, but with proper handling for empty list
            self._update_prep_status(
                message=f"Found {len(missing_species)} missing genomes. Preparing to download...",
                progress=55
            )


            # STEP 5: Download missing genomes using GTDB API
            if missing_species:

                try:
                    # Initialize results dictionary
                    results = {}
                    kraken_taxonomy = config.get("kraken_taxonomy", "gtdb")

                    # Fetch data for each missing species from GTDB
                    for species in missing_species:
                        # Test API directly first - for diagnostic purposes
                        test_result = test_gtdb_api_directly(species)
                        if test_result:
                            logging.info(f"Direct API test successful for {species}")
                        else:
                            logging.error(f"Direct API test failed for {species}")

                        # Now use the fetch_species_data function
                        search_query = f"s__{species.replace(' ', '_')}"
                        logging.info(f"Querying GTDB API for: {search_query}")

                        species_data = fetch_species_data(search_query, kraken_taxonomy)

                        # Log diagnostics
                        logging.info(f"Species data type: {type(species_data)}")
                        logging.info(f"Species data length: {len(species_data) if species_data else 0}")

                        # Store results
                        if species_data:
                            results[species] = {"rows": species_data}
                            logging.info(f"Stored results for {species}")
                        else:
                            logging.warning(f"No data found for {species}")

                    # Update results with taxonomy IDs
                    for species_name in results.keys():
                        tax_id = species_to_taxid.get(species_name, None)
                        if tax_id is not None:
                            results[species_name]["tax_id"] = tax_id
                        else:
                            results[species_name]["tax_id"] = "N/A"

                    logging.info(f"Species list: {species_list}")
                    logging.info(f"API results: {results}")

                    # Filter results to include only exact matches
                    filtered_results = {}
                    for species, species_info in results.items():
                        if "rows" not in species_info:
                            continue

                        exact_matches = []
                        for row in species_info["rows"]:
                            # Get the taxonomy field based on the taxonomy database
                            if kraken_taxonomy == "gtdb":
                                taxonomy = row.get("gtdbTaxonomy", "")
                            else:  # ncbi
                                taxonomy = row.get("ncbiTaxonomy", "")

                            # Check for exact match
                            if taxonomy and (taxonomy.endswith(f"s__{species}") or taxonomy.endswith(f"s__{species.replace(' ', '_')}")):
                                exact_matches.append(row)

                        if exact_matches:
                            filtered_results[species] = {"rows": exact_matches, "tax_id": species_info.get("tax_id", "N/A")}

                    # Convert to DataFrame
                    parsed_data = []
                    logging.info(f"Starting taxonomy filtering on {len(results)} species")
                    for species, species_info in filtered_results.items():
                        for row in species_info["rows"]:
                            row_dict = {
                                "Species": species,
                                "Tax_ID": species_info.get("tax_id", "N/A"),
                                "SearchQuery": f"s__{species.replace(' ', '_')}",
                                "GID": row.get("gid", "N/A"),
                                "Accession": row.get("accession", "N/A"),
                                "NCBI_OrgName": row.get("ncbiOrgName", "N/A"),
                                "NCBI_Taxonomy": row.get("ncbiTaxonomy", "N/A"),
                                "GTDB_Taxonomy": row.get("gtdbTaxonomy", "N/A"),
                                "Is_GTDB_Species_Rep": row.get("isGtdbSpeciesRep", "N/A"),
                                "Is_NCBI_Type_Material": row.get("isNcbiTypeMaterial", "N/A"),
                            }
                            parsed_data.append(row_dict)

                    df = pd.DataFrame(parsed_data)
                    logging.info(f"Created DataFrame with {len(df)} rows")

                    # Extract accessions for download
                    if df is not None and not df.empty and "GID" in df.columns:
                        self._update_prep_status(
                            message="Preparing to download genomes from NCBI...",
                            progress=60
                        )

                        # Get accessions
                        accessions = df["GID"].tolist()
                        if accessions:
                            logging.info(f"Found {len(accessions)} accessions: {accessions}")

                            # SECURITY: Validate all accessions before using in subprocess
                            # Genome IDs should be alphanumeric with underscores/dots only
                            import re
                            valid_gid_pattern = re.compile(r'^[A-Za-z0-9_.\-]+$')
                            validated_accessions = []
                            for acc in accessions:
                                acc_str = str(acc).strip()
                                if not valid_gid_pattern.match(acc_str):
                                    logging.warning(f"Skipping invalid genome ID: {acc_str}")
                                    continue
                                if ".." in acc_str or "/" in acc_str or "\\" in acc_str:
                                    logging.warning(f"Skipping potentially malicious genome ID: {acc_str}")
                                    continue
                                validated_accessions.append(acc_str)

                            if not validated_accessions:
                                self._update_prep_status(
                                    error="No valid genome IDs found after validation"
                                )
                                logging.error("All genome IDs failed validation")
                            else:
                                # Write validated accessions to file
                                accession_file = os.path.join(data_dir, "ncbi_download_list.txt")
                                # Validate output path
                                accession_file = self._validate_path_for_output(accession_file, "accession file")

                                with open(accession_file, "w") as f:
                                    f.write("\n".join(validated_accessions) + "\n")

                                # Download genomes
                                self._update_prep_status(
                                    message=f"Downloading {len(validated_accessions)} genomes from NCBI...",
                                    progress=65
                                )
                                download_prefix = "nanometa"
                                output_zip = os.path.join(data_dir, f"{download_prefix}_ncbi_download.zip")
                                # Validate output path
                                output_zip = self._validate_path_for_output(output_zip, "download zip file")

                                # Use datasets command line tool to download genomes
                                cmd = [
                                    "datasets", "download", "genome", "accession",
                                    "--inputfile", accession_file,
                                    "--filename", output_zip
                                ]
                                try:
                                    subprocess.run(cmd, check=True)

                                    # Decompress and rename
                                    self._update_prep_status(
                                        message="Processing downloaded genomes...",
                                        progress=75
                                    )

                                    # Extract zip file
                                    with zipfile.ZipFile(output_zip, 'r') as zip_ref:
                                        zip_ref.extractall(data_dir)

                                    # Rename files based on taxids
                                    for species, taxid in species_to_taxid.items():
                                        if species in missing_species:
                                            species_rows = df[df["Species"] == species]
                                            if not species_rows.empty:
                                                gid = str(species_rows.iloc[0]["GID"]).strip()

                                                # SECURITY: Validate GID before using in path
                                                if not valid_gid_pattern.match(gid):
                                                    logging.warning(f"Skipping invalid genome ID for {species}: {gid}")
                                                    continue
                                                if ".." in gid or "/" in gid or "\\" in gid:
                                                    logging.warning(f"Skipping path traversal in genome ID for {species}: {gid}")
                                                    continue

                                                ncbi_data_dir = os.path.join(data_dir, "ncbi_dataset", "data")
                                                accession_path = os.path.join(ncbi_data_dir, gid)

                                                # SECURITY: Ensure accession_path is within expected directory
                                                if not os.path.abspath(accession_path).startswith(os.path.abspath(ncbi_data_dir)):
                                                    logging.warning(f"Path escape detected for {species}: {accession_path}")
                                                    continue

                                                if os.path.isdir(accession_path):
                                                    # Find FNA file
                                                    for filename in os.listdir(accession_path):
                                                        if filename.endswith(".fna"):
                                                            source_file = os.path.join(accession_path, filename)
                                                            target_file = os.path.join(genomes_dir, f"{taxid}.fasta")
                                                            shutil.copy(source_file, target_file)
                                                            break
                                except subprocess.CalledProcessError as e:
                                    self._update_prep_status(
                                        error=f"Error downloading genomes: {str(e)}"
                                    )
                        else:
                            logging.warning("DataFrame has GID column but no accessions found")
                            self._update_prep_status(
                                error="No accessions found for download. Check species names and try again."
                            )
                    else:
                        if df is None:
                            logging.error("DataFrame is None - API results parsing failed")
                        elif df.empty:
                            logging.error("DataFrame is empty - no results from API")
                        else:
                            logging.error(f"GID column missing from DataFrame. Available columns: {df.columns.tolist()}")

                        self._update_prep_status(
                            message="Continuing preparation without genome downloads...",
                            error="Failed to find accessions for download. Check species names and try again."
                        )

                except Exception as e:
                    self._update_prep_status(
                        error=f"Error downloading genomes: {str(e)}"
                    )

            # STEP 6: Build BLAST databases
            self._update_prep_status(
                message="Building BLAST databases for validation...",
                progress=85
            )

            # Check which BLAST databases are missing
            missing_dbs = []
            blast_dir = os.path.join(data_dir, "blast")
            os.makedirs(blast_dir, exist_ok=True)

            for species, taxid in species_to_taxid.items():
                blast_db_file = os.path.join(blast_dir, f"{taxid}.fasta.nhr")
                if not os.path.exists(blast_db_file):
                    missing_dbs.append(str(taxid))

            # Build missing BLAST databases
            if missing_dbs:
                input_folder = os.path.join(data_dir, "genomes")
                for taxid in missing_dbs:
                    # SECURITY: Validate taxid is numeric before using in subprocess
                    try:
                        taxid_int = int(taxid)
                        if taxid_int <= 0:
                            raise ValueError("Taxid must be positive")
                        taxid_str = str(taxid_int)  # Ensure clean string
                    except (ValueError, TypeError) as e:
                        logging.warning(f"Skipping invalid taxid for BLAST db: {taxid}")
                        continue

                    file_path = os.path.join(input_folder, f"{taxid_str}.fasta")
                    database_name = os.path.join(blast_dir, f"{taxid_str}.fasta")

                    # Validate paths before subprocess
                    try:
                        file_path = self._validate_path(file_path, "genome file")
                        database_name = self._validate_path_for_output(database_name, "BLAST database")
                    except ValueError as e:
                        logging.warning(f"Path validation failed for taxid {taxid_str}: {e}")
                        continue

                    if os.path.exists(file_path):
                        system_cmd = [
                            "makeblastdb",
                            "-in", file_path,
                            "-dbtype", "nucl",
                            "-out", database_name,
                        ]

                        try:
                            subprocess.run(system_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                        except subprocess.CalledProcessError as e:
                            self._update_prep_status(
                                error=f"Error building BLAST database for {taxid_str}: {e.stderr.decode() if e.stderr else str(e)}"
                            )

            # STEP 7: Complete preparation
            self._update_prep_status(
                message="Data preparation completed successfully!",
                progress=100,
                running=False
            )

        except Exception as e:
            self._update_prep_status(
                message=f"Error: {str(e)}",
                progress=100,
                running=False,
                error=str(e)
            )

