"""
Backend manager for Nanometa Live.

This module manages the backend processes for the application, including:
- Starting/stopping the Nextflow workflow (nanometanf pipeline)
- Monitoring the processing status
- Checking files and directories
"""

import os
import time
import json
import hashlib
import logging
import platform
import threading
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows: file locking not available
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, IO

from nanometa_live.core.workflow.nextflow_manager import NextflowManager


def _parse_bool(value):
    """Parse a boolean value that may be a string."""
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "y", "1")
    return bool(value)


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
        except (ValueError, TypeError, OSError) as e:
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

    @staticmethod
    def _process_exists(pid: int) -> bool:
        """
        Check whether a process with the given PID is still running.

        Args:
            pid: Process ID to check

        Returns:
            True if the process exists, False otherwise
        """
        try:
            os.kill(pid, 0)  # Signal 0 checks existence without affecting process
            return True
        except (OSError, ProcessLookupError):
            return False

    def _acquire_lock(self, results_dir: str) -> Tuple[bool, str]:
        """
        Acquire exclusive lock on results directory to prevent multi-user collisions.

        Uses file-based locking (fcntl) to ensure only one pipeline can write
        to a given results directory at a time. Detects and removes stale lock
        files left behind by crashed processes.

        Args:
            results_dir: Path to the results directory to lock

        Returns:
            Tuple of (success: bool, message: str)
        """
        lock_file = os.path.join(results_dir, ".nanometa.lock")
        self._lock_file_path = lock_file

        # Check for stale lock from a crashed process
        if os.path.exists(lock_file):
            try:
                with open(lock_file, 'r') as f:
                    lock_data = json.load(f)
                pid = lock_data.get("pid")
                if pid and not self._process_exists(pid):
                    logging.info(
                        f"Removing stale lock file (PID {pid} no longer running)"
                    )
                    os.remove(lock_file)
            except (json.JSONDecodeError, OSError):
                pass  # If we cannot read the lock file, proceed to try acquire

        try:
            # Create/open lock file
            self._lock_fd = open(lock_file, 'w')

            # Try to acquire exclusive, non-blocking lock
            if fcntl:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write lock info for debugging
            lock_info = {
                "pid": os.getpid(),
                "hostname": platform.node(),
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
            except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError):
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

        except (PermissionError, OSError, ValueError) as e:
            logging.exception(f"Error acquiring lock: {e}")
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
                if fcntl:
                    fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                self._lock_fd.close()
                logging.info("Released lock on results directory")
            except (OSError, ValueError) as e:
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
            self.config["kraken_memory_mapping"] = _parse_bool(self.config["kraken_memory_mapping"])

        if "blast_validation" in self.config:
            self.config["blast_validation"] = _parse_bool(self.config["blast_validation"])

        if "remove_temp_files" in self.config:
            self.config["remove_temp_files"] = _parse_bool(self.config["remove_temp_files"])

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
        pipeline_source = self.config.get("pipeline_source")
        if not pipeline_source:
            pipeline_source = "remote:dev"
            logging.warning(
                "config['pipeline_source'] is missing; falling back to "
                "'remote:dev'. Set pipeline_source explicitly in config.yaml "
                "(e.g. 'local:/path/to/nanometanf' or 'remote:dev') to silence "
                "this warning."
            )
        self.workflow_manager.set_pipeline_source(pipeline_source)

        # Offline guard: reject remote sources before any network attempt.
        if _parse_bool(self.config.get("offline_mode", False)):
            is_remote = (
                pipeline_source.startswith("remote:")
                or pipeline_source.startswith("https://")
                or pipeline_source.startswith("git@")
                or pipeline_source in ("master", "main", "dev")
            )
            if is_remote:
                msg = (
                    "Offline mode is active but pipeline_source is remote "
                    f"('{pipeline_source}'). Set pipeline_source to a local "
                    "path in config.yaml before starting an offline run."
                )
                logging.error(msg)
                return False, msg

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

    # Subdirectory names that nanometanf writes into the results dir.
    # detect_existing_results scans for these so the GUI can warn the
    # operator before silently mixing data from different runs.
    RESULT_SUBDIRS = (
        "kraken2",
        "fastp",
        "seqkit",
        "validation",
        "taxpasta",
        "multiqc",
        "on_demand_validation",
        "logs",
        "nanoplot",
    )

    @staticmethod
    def detect_existing_results(outdir: str) -> list:
        """Return the names of result subdirs that already contain files.

        A subdir counts as "non-empty" only if it exists AND contains at
        least one regular file (recursively). An empty directory does
        not trigger the collision modal because the pipeline will refill
        it harmlessly.

        Returns an empty list when outdir does not exist or has no
        result-shaped contents -- i.e. when a fresh run is safe.
        """
        if not outdir or not os.path.isdir(outdir):
            return []

        found = []
        for name in BackendManager.RESULT_SUBDIRS:
            sub = os.path.join(outdir, name)
            if not os.path.isdir(sub):
                continue
            try:
                has_file = any(
                    os.path.isfile(os.path.join(root, f))
                    for root, _, files in os.walk(sub)
                    for f in files
                )
            except OSError:
                has_file = False
            if has_file:
                found.append(name)
        return found

    # File written into the output directory at every successful
    # pipeline start. Read on the next launch so the GUI can warn the
    # operator when they are about to point a *different* input at an
    # outdir that holds results from a prior, *different* run -- the
    # exact case where silently mixing data would be hardest to spot
    # after the fact.
    RUN_METADATA_FILENAME = ".nanometa.run.json"

    # Config keys that, taken together, identify the logical "input"
    # of a run. Two runs with identical values for these keys are
    # considered the same input and are safe to resume against.
    _FINGERPRINT_KEYS = (
        "nanopore_output_directory",
        "sample_handling",
        "processing_mode",
        "kraken_db",
    )

    @staticmethod
    def compute_input_fingerprint(config: Dict[str, Any]) -> str:
        """Return a stable hash of the input-identifying config keys.

        The hash deliberately excludes runtime-only knobs (port,
        update interval, validation toggles) so that turning BLAST on
        or off between runs against the same data is *not* flagged as
        an input change. Order-independent: keys are sorted before
        hashing so dict iteration order does not matter.
        """
        if not config:
            return ""
        parts = []
        for key in BackendManager._FINGERPRINT_KEYS:
            value = config.get(key, "")
            parts.append(f"{key}={value}")
        payload = "\n".join(parts).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def read_run_metadata(outdir: str) -> Optional[Dict[str, Any]]:
        """Return the persisted run metadata for ``outdir`` or None.

        Never raises; a missing or malformed metadata file just means
        we have no prior fingerprint to compare against.
        """
        if not outdir:
            return None
        path = os.path.join(outdir, BackendManager.RUN_METADATA_FILENAME)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def write_run_metadata(outdir: str, config: Dict[str, Any]) -> None:
        """Persist input fingerprint + identifying fields under outdir.

        Best-effort: a write failure is logged but never fails the
        run. The metadata is informational; missing it just means the
        next launch falls back to "input identical/unknown" handling.
        """
        if not outdir or not os.path.isdir(outdir):
            return
        payload = {
            "fingerprint": BackendManager.compute_input_fingerprint(config),
            "written_at": datetime.now().isoformat(timespec="seconds"),
            "inputs": {
                key: config.get(key, "")
                for key in BackendManager._FINGERPRINT_KEYS
            },
        }
        path = os.path.join(outdir, BackendManager.RUN_METADATA_FILENAME)
        try:
            # Atomic temp+replace so a crash mid-write can never leave a
            # truncated metadata file that the next launch would have to
            # treat as a corrupt fingerprint.
            from nanometa_live.core.utils.atomic_write import atomic_write_json
            atomic_write_json(path, payload)
        except OSError as e:
            logging.warning(f"Could not write run metadata to {path}: {e}")

    @staticmethod
    def fingerprint_matches(outdir: str, config: Dict[str, Any]) -> Optional[bool]:
        """Compare current config to the prior run's fingerprint.

        Returns True if matched, False if mismatched, or None when no
        prior fingerprint is available (so the caller can decide
        whether to warn or stay silent).
        """
        prior = BackendManager.read_run_metadata(outdir)
        if not prior or "fingerprint" not in prior:
            return None
        return prior["fingerprint"] == BackendManager.compute_input_fingerprint(config)

    @staticmethod
    def archive_existing_results(outdir: str) -> Optional[str]:
        """Move detected result subdirs into ``<outdir>/_archive_<ts>/``.

        Returns the absolute path of the archive directory, or None when
        nothing needed archiving. The timestamp is local-time
        ``YYYY-MM-DD_HH-MM-SS``; if a same-second collision occurs (two
        rapid clicks), a numeric suffix ``_2``, ``_3`` is appended so
        prior archives are never overwritten.
        """
        found = BackendManager.detect_existing_results(outdir)
        if not found:
            return None

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archive_path = os.path.join(outdir, f"_archive_{timestamp}")
        suffix = 2
        while os.path.exists(archive_path):
            archive_path = os.path.join(
                outdir, f"_archive_{timestamp}_{suffix}"
            )
            suffix += 1

        os.makedirs(archive_path, exist_ok=False)
        for name in found:
            src = os.path.join(outdir, name)
            dst = os.path.join(archive_path, name)
            os.rename(src, dst)

        logging.info(
            f"Archived {len(found)} existing result subdirs to {archive_path}"
        )
        return archive_path

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

        # Persist input fingerprint so the next launch can detect when
        # the operator is about to point a different input at this
        # outdir (the case where mixing data is hardest to spot later).
        outdir_for_meta = (
            self.config.get("results_output_directory")
            or self.config.get("main_dir")
            or results_dir
        )
        BackendManager.write_run_metadata(outdir_for_meta, self.config)

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
            self.status["errors"] = []  # Clear errors from user-initiated stop
            self.status["last_update"] = time.time()

        # Clear workflow manager errors from the expected non-zero exit
        if hasattr(self.workflow_manager, 'status'):
            self.workflow_manager.status["errors"] = []

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
                # Pipeline subprocess stopped but backend still marked running.
                # The monitor thread will handle the detailed status transition;
                # report as "stopping" until the monitor thread completes its check.
                self.status["pipeline_status"] = "stopping"
            elif self.status.get("pipeline_status") == "completed":
                # Preserve completed status (set by monitor thread)
                pass
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

            # Surface remaining seconds until the realtime timeout fires
            # so the dashboard verdict banner can render an "Auto-stop
            # in Nm Ss" countdown (U3, 2026-05-09 UX spec). The monitor
            # thread already enforces the timeout; this is read-only.
            self.status["auto_stop_remaining_s"] = self._compute_auto_stop_remaining()

            # Expose a top-level boolean `completed` derived from pipeline_status.
            # Consumers (verdict banner run-state badge, header indicator, load
            # gating) read status.get("completed"); without this it was never
            # written, so a finished run rendered as STANDBY instead of COMPLETE.
            self.status["completed"] = (
                self.status.get("pipeline_status") == "completed"
            )

            # Return a copy to prevent external modification
            return dict(self.status)

    def _compute_auto_stop_remaining(self) -> Optional[int]:
        """Return seconds until the realtime timeout fires, or None.

        ``None`` covers the cases where (a) the pipeline is not running,
        (b) no realtime_timeout_minutes is configured, or (c) the saved
        start_time cannot be parsed.
        """
        if not self.status.get("running"):
            return None
        if not self.config:
            return None
        # The countdown only applies to the realtime inactivity timeout; batch
        # runs are not auto-stopped (see _monitor_status).
        if self.config.get("processing_mode") != "realtime":
            return None
        timeout_minutes = self.config.get("realtime_timeout_minutes")
        if not timeout_minutes:
            return None
        start_iso = self.status.get("start_time")
        if not start_iso:
            return None
        try:
            from datetime import datetime as _dt
            start_dt = _dt.fromisoformat(start_iso)
            elapsed = (_dt.now() - start_dt).total_seconds()
        except (TypeError, ValueError):
            return None
        remaining = int(int(timeout_minutes) * 60 - elapsed)
        return max(0, remaining)

    # TTL for the cached file count below. Each interval tick on the
    # dashboard ends up calling _update_file_counts at least once; on a
    # 24-barcode multiplex run that means 25 os.listdir calls per tick
    # (root + 24 barcode subdirs) for a quantity that does not change
    # meaningfully between ticks. Caching for 5 seconds reduces this
    # to one scan per ~5 ticks at the default 30 s interval, while
    # still picking up newly arrived files within one cycle of the
    # human-perceptible "files waiting" indicator. Closes P1-T09 from
    # docs/audit-2026-04-28-throughput-gui.md.
    _FILE_COUNT_TTL_SECONDS = 5.0

    def _update_file_counts(self):
        """Update the file processing counts from the file system."""
        try:
            now = time.time()
            cached_at = getattr(self, "_file_count_cached_at", 0.0)
            if (now - cached_at) < self._FILE_COUNT_TTL_SECONDS:
                cached = getattr(self, "_file_count_cached_value", None)
                if cached is not None:
                    self.status["files_waiting"] = cached
                    return

            nanopore_dir = self.config.get("nanopore_output_directory", "")

            # Count files in nanopore directory (including barcode subdirs)
            waiting_files = 0
            extensions = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
            if os.path.exists(nanopore_dir):
                for f in os.listdir(nanopore_dir):
                    if f.endswith(extensions):
                        waiting_files += 1
                # Also count files in per-sample subdirectories. The
                # canonical detector accepts conventional barcode<NN>
                # plus custom-named subdirs (Turex/, Zymo/, ...) so
                # this counter stays accurate for non-multiplex
                # layouts that still use by_barcode mode.
                from nanometa_live.core.utils.auto_detect import find_sample_subdirs
                for sample_dir in find_sample_subdirs(nanopore_dir):
                    try:
                        for f in os.listdir(str(sample_dir)):
                            if f.endswith(extensions):
                                waiting_files += 1
                    except OSError:
                        continue

            # Update status with waiting files
            # Processed files comes from workflow_manager status
            self.status["files_waiting"] = waiting_files
            self._file_count_cached_value = waiting_files
            self._file_count_cached_at = now

        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.exception(f"Error updating file counts: {e}")

    def _monitor_status(self):
        """Monitor the status of the backend processes in a separate thread."""
        logging.info("BackendManager status monitoring started")

        # Determine realtime timeout from config (in minutes, converted to seconds).
        # This is a REALTIME-only inactivity stop. The config validator defaults
        # realtime_timeout_minutes to 60 regardless of mode, so without this
        # processing_mode guard a long batch run would be killed at 60 minutes.
        timeout_seconds = None
        if self.config and self.config.get("processing_mode") == "realtime":
            timeout_minutes = self.config.get("realtime_timeout_minutes")
            if timeout_minutes:
                timeout_seconds = int(timeout_minutes) * 60
                logging.info(
                    f"Realtime timeout enforcement enabled: {timeout_minutes} minutes"
                )

        start_time = time.time()
        # Inactivity tracking for the realtime timeout. The timeout is an
        # INACTIVITY stop (as its config documents), NOT a wall-clock cap: a run
        # still actively draining work (classification/validation tasks
        # completing) must not be killed mid-flight, or its downstream results
        # are truncated -- the symptom behind nanometanf issue #29, where the
        # GUI SIGTERM'd a run at realtime_timeout_minutes while hundreds of
        # validation tasks were still pending. The pipeline has its own bounds
        # (max_files .take / its realtime timer) that close the watchPath stream;
        # this GUI stop is a last-resort backstop for a GENUINELY stalled run, so
        # we only fire it when no task has completed for timeout_seconds.
        last_progress_time = start_time
        last_complete_count = -1

        while self.status.get("running"):
            try:
                # Get workflow manager status (also drives progress tracking)
                workflow_status = self.workflow_manager.get_status()

                # Advance the inactivity clock whenever task progress is made.
                complete_count = workflow_status.get("processes_complete", 0)
                if complete_count != last_complete_count:
                    last_complete_count = complete_count
                    last_progress_time = time.time()

                # Check realtime timeout (inactivity-based)
                if timeout_seconds is not None:
                    idle = time.time() - last_progress_time
                    if idle >= timeout_seconds:
                        logging.warning(
                            f"Realtime inactivity timeout reached after "
                            f"{idle / 60:.1f} minutes with no task progress, "
                            f"stopping pipeline"
                        )
                        with self._status_lock:
                            self.status["running"] = False
                            self.status["pipeline_status"] = "stopped"
                            self.status["errors"].append(
                                f"Pipeline stopped: realtime inactivity timeout "
                                f"({int(timeout_seconds / 60)} minutes with no "
                                f"task progress) reached"
                            )
                        # Stop the underlying Nextflow process
                        try:
                            self.workflow_manager.stop()
                        except (OSError, RuntimeError, AttributeError) as e:
                            logging.exception(f"Error stopping pipeline after timeout: {e}")
                        break

                # Thread-safe status update
                with self._status_lock:
                    # Detect pipeline termination (crash or completion)
                    if not workflow_status.get("running"):
                        workflow_errors = workflow_status.get("errors", [])

                        if len(workflow_errors) > 0:
                            # Pipeline terminated with errors
                            self.status["pipeline_status"] = "error"
                            existing = set(self.status["errors"])
                            for err in workflow_errors:
                                if err not in existing:
                                    self.status["errors"].append(err)
                                    existing.add(err)
                            self.status["running"] = False
                            logging.error("Pipeline encountered errors, stopping")

                        else:
                            # Pipeline terminated without errors (normal completion
                            # or undetected crash). Check if it completed
                            # successfully by looking at process counts.
                            processes_failed = workflow_status.get("processes_failed", 0)
                            processes_complete = workflow_status.get("processes_complete", 0)

                            if processes_failed > 0:
                                # Pipeline had failed processes but no explicit error
                                self.status["pipeline_status"] = "error"
                                self.status["errors"].append(
                                    f"Pipeline terminated with {processes_failed} "
                                    f"failed process(es)"
                                )
                                self.status["running"] = False
                                logging.error(
                                    f"Pipeline terminated with {processes_failed} "
                                    f"failed processes"
                                )

                            elif processes_complete > 0:
                                # Pipeline completed successfully
                                self.status["pipeline_status"] = "completed"
                                self.status["running"] = False
                                logging.info("Pipeline completed successfully")

                            else:
                                # Pipeline terminated unexpectedly with no
                                # completed processes and no errors -- likely a
                                # crash during startup or configuration
                                self.status["pipeline_status"] = "error"
                                self.status["errors"].append(
                                    "Pipeline process terminated unexpectedly. "
                                    "Check the Nextflow log for details."
                                )
                                self.status["running"] = False
                                logging.error(
                                    "Pipeline process terminated unexpectedly "
                                    "(no completed processes, no errors reported)"
                                )

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
                # Background-thread top-of-loop guard: keep broad catch so the
                # monitor thread survives unexpected errors per cycle 4 D1 rule.
                logging.exception(f"Error in monitoring thread: {e}")
                time.sleep(5)

        # Release lock when monitoring thread exits (pipeline completed or stopped)
        self._release_lock()
        logging.info("BackendManager status monitoring stopped")


