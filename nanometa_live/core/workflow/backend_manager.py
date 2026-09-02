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

from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
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
        # Set BEFORE the Nextflow process is signalled so the monitor thread,
        # which polls every 5 s and may see the dead process first, records
        # the run as stopped rather than completed or errored (round-4 audit,
        # H3). Cleared at the next start().
        self._stop_intent: Optional[str] = None
        # Note: legacy _prep_status_lock removed along with prepare_data methods
        self._lock_fd: Optional[IO] = None  # File lock descriptor for multi-user safety
        self._lock_file_path: Optional[str] = None  # Path to lock file
        # Start/stop transition state for the async click path. start() and
        # stop() block for tens of seconds (preflight probes, process.wait);
        # the GUI runs them in a daemon THREAD in this process -- the
        # subprocess handles live here, so a DiskcacheManager worker process
        # cannot own them -- and the status tick surfaces the terminal
        # result via consume_transition_result() (round-2 audit,
        # 2026-08-22).
        self._transition_lock = threading.Lock()
        self._transition: Optional[Dict[str, Any]] = None
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

    def _lock_target_dir(self) -> str:
        """The directory the exclusive run lock must guard.

        This is the pipeline's real output directory
        (``results_output_directory``, matching parameter_mapping's outdir
        precedence), falling back to ``main_dir`` and then the data dir only
        when it is unset.
        """
        return (
            self.config.get("results_output_directory")
            or self.config.get("main_dir")
            or self.data_dir
        )

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

        # Pre-flight the source through the one validator that knows every
        # failure mode: offline+remote is rejected before any network call,
        # a local path must exist and contain main.nf, and a remote branch
        # is resolved via ls-remote so a typo fails here with a clear
        # message instead of mid-launch. This validator existed with zero
        # production callers while a partial inline copy of its offline
        # branch lived here (2026-08-17 audit, finding G1).
        ok, msg = self.workflow_manager.validate_pipeline_source(self.config)
        if not ok:
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
    # "canonical" matters more than it looks: the loaders consult
    # canonical/_manifest.json and canonical/classification/ BEFORE any
    # cache or freshness check, so a canonical tree left behind by a prior
    # run keeps serving that run's sample list and classification to the
    # GUI for as long as it exists (2026-08-17 audit, finding C1).
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
        "canonical",
        "pipeline_info",
        # GENERATE_SNAPSHOT_STATS output; the header's "Files processed"
        # sums it, so a previous run's snapshots left behind inflate the
        # count (round-4 audit, H36).
        "realtime_batch_stats",
        # The auto-generated operator report describes the run that wrote
        # it; leaving it behind would show run A's verdict on the Reports
        # tab during run B.
        "report",
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
    def compute_watchlist_fingerprint() -> str:
        """Stable hash of the currently enabled watchlist entry set.

        Keyed on the sorted taxids of the active entries. Recorded
        separately from the input fingerprint: the input hash decides
        whether resuming mixes unrelated DATA, while this one only warns
        that the same data would be SCREENED differently (2026-08-17
        audit, finding C10 -- resuming with a different watchlist looked
        identical to resuming with the same one). Empty string when no
        entries are enabled or the manager is unavailable.
        """
        try:
            from nanometa_live.core.watchlist.watchlist_manager import (
                get_watchlist_manager,
            )
            taxids = sorted(get_watchlist_manager().get_active_entries().keys())
        except Exception as e:
            logging.debug(f"Watchlist fingerprint unavailable: {e}")
            return ""
        if not taxids:
            return ""
        payload = ",".join(str(t) for t in taxids).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _enabled_watchlist_ids() -> list:
        """Sorted enabled watchlist ids, or [] when the manager is unusable."""
        try:
            from nanometa_live.core.watchlist.watchlist_manager import (
                get_watchlist_manager,
            )
            return get_watchlist_manager().enabled_watchlist_ids()
        except Exception as e:
            logging.debug(f"Enabled watchlist ids unavailable: {e}")
            return []

    @staticmethod
    def watchlist_matches(outdir: str) -> Optional[bool]:
        """Compare the active watchlist to the prior run's recorded set.

        Returns None when the prior metadata carries no watchlist
        fingerprint (pre-C10 runs) so callers stay silent rather than
        crying wolf over old run records.
        """
        prior = BackendManager.read_run_metadata(outdir)
        if not prior or "watchlist_fingerprint" not in prior:
            return None
        return (
            prior["watchlist_fingerprint"]
            == BackendManager.compute_watchlist_fingerprint()
        )

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
            "watchlist_fingerprint": (
                BackendManager.compute_watchlist_fingerprint()
            ),
            # The ids, not just the fingerprint above: nanometa-report reads
            # these to reproduce the run's pathogen screen post hoc, where a
            # hash alone cannot say WHICH lists to enable.
            "watchlists": BackendManager._enabled_watchlist_ids(),
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

        # The loaders cache in module globals keyed by directory path, so
        # the just-archived data would otherwise keep answering from the
        # TTL/mtime caches until they expire (finding C2/C3).
        clear_all_loader_caches()

        logging.info(
            f"Archived {len(found)} existing result subdirs to {archive_path}"
        )
        return archive_path

    # ------------------------------------------------------------------
    # Async start/stop (round-2 audit, 2026-08-22)
    # ------------------------------------------------------------------

    def _launch_transition(self, kind: str, fn) -> Tuple[bool, str]:
        """Run ``fn`` (start or stop) in a daemon thread, one at a time."""
        with self._transition_lock:
            if self._transition is not None and not self._transition.get("done"):
                return False, (
                    f"A {self._transition.get('kind', 'start/stop')} is "
                    f"already in progress."
                )
            self._transition = {"kind": kind, "done": False}

        def _run():
            try:
                success, message = fn()
            except Exception as exc:  # a silent preflight failure is worse
                logging.exception("Async %s failed", kind)
                success, message = False, str(exc)
            with self._transition_lock:
                self._transition = {
                    "kind": kind, "done": True,
                    "success": bool(success), "message": message,
                }

        threading.Thread(
            target=_run, name=f"backend-{kind}", daemon=True).start()
        return True, f"{kind.capitalize()} running in the background..."

    def start_async(self, profile: str = None,
                    resume: bool = False) -> Tuple[bool, str]:
        """Non-blocking :meth:`start`; the click path must return instantly."""
        return self._launch_transition(
            "start", lambda: self.start(profile=profile, resume=resume))

    def stop_async(self) -> Tuple[bool, str]:
        """Non-blocking :meth:`stop` (process.wait can take 30+ s)."""
        return self._launch_transition("stop", self.stop)

    def transition_in_progress(self) -> bool:
        with self._transition_lock:
            return (self._transition is not None
                    and not self._transition.get("done"))

    def consume_transition_result(self) -> Optional[Dict[str, Any]]:
        """The finished transition's result, exactly once, else None."""
        with self._transition_lock:
            if self._transition is None or not self._transition.get("done"):
                return None
            result = {
                "kind": self._transition["kind"],
                "success": self._transition["success"],
                "message": self._transition["message"],
            }
            self._transition = None
            return result

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

        # Acquire an exclusive lock on the directory the pipeline actually
        # writes to. Locking main_dir was useless for its stated purpose:
        # setup_project generates a fresh, uniquely timestamped main_dir on
        # every launch, so two operators pointing different instances at the
        # SAME results_output_directory each locked their own never-colliding
        # path and both pipelines wrote the same output tree concurrently.
        results_dir = self._lock_target_dir()
        os.makedirs(results_dir, exist_ok=True)
        lock_success, lock_message = self._acquire_lock(results_dir)
        if not lock_success:
            return False, lock_message

        # Get profile from config if not explicitly passed
        if profile is None:
            profile = self.config.get("pipeline_profile", "conda")

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

        # A new run begins: whatever the loader caches hold belongs to the
        # previous run (or the previous view of this outdir). Drop it all so
        # the first poll parses what the pipeline actually writes.
        clear_all_loader_caches()

        # Mark as running with start time for elapsed time tracking (thread-safe)
        with self._status_lock:
            self._mark_started_locked()

        # Start status monitoring thread
        self.status_thread = threading.Thread(target=self._monitor_status, daemon=True)
        self.status_thread.start()

        logging.info(f"Backend started successfully with profile: {profile}")
        return True, f"Backend started successfully with profile: {profile}"

    def _auto_generate_report(self) -> Optional[str]:
        """Write the operator HTML report into ``<outdir>/report/`` best-effort.

        Called when a run ends (completion detected by the monitor thread,
        or an operator Stop of a realtime run). Without this, the verdict
        and pathogen screen existed only inside the running dashboard: an
        operator who closed the app without clicking Export Results kept
        the raw pipeline output but no human-readable summary of what the
        run concluded (2026-08-17 storage audit, finding R1).

        Raw files are never copied here (``include_raw=False``): the report
        lands INSIDE the results directory, so copying raw/ would duplicate
        the whole tree into itself. The report HTML is self-contained.

        Best-effort by design: a report failure must never fail a stop or
        mask a completed run. Disable with ``auto_report: false``.
        Returns the report path, or None when skipped or failed.
        """
        config = self.config or {}
        if not config.get("auto_report", True):
            return None
        outdir = (
            config.get("results_output_directory")
            or config.get("main_dir")
            or ""
        )
        if not outdir or not os.path.isdir(outdir):
            return None
        try:
            from nanometa_live.core.export.report_generator import (
                ReportGenerator,
            )
            report_path = ReportGenerator(outdir, config).generate(
                output_dir=os.path.join(outdir, "report"),
                include_raw=False,
            )
            logging.info(f"Run report written to {report_path}")
            return str(report_path)
        except Exception as e:
            logging.warning(f"Automatic run report failed: {e}")
            return None

    def stop(self) -> Tuple[bool, str]:
        """
        Stop the backend processes.

        Returns:
            Tuple of (success, message)
        """
        if not self.status.get("running"):
            return False, "Backend is not running"

        # Declare the intent first: workflow_manager.stop() blocks for up to
        # 30 s, and the monitor thread polls in that window (round-4 H3).
        self._mark_stop_intent("operator")

        # Stop the Nextflow workflow
        success, message = self.workflow_manager.stop()
        if not success:
            # Still release lock even if stop fails
            self._release_lock()
            return False, message

        # Release exclusive lock on results directory
        self._release_lock()

        # Mark as stopped (thread-safe) and leave the terminal record the
        # exported report reads (round-4 H2: three live Stop drills left no
        # final_status, so the report over an aborted run read like one over
        # a run that drained its input).
        with self._status_lock:
            self._finish_stopped_locked("operator")

        # A realtime run ends via Stop, so this is its natural moment to
        # leave a report behind; best-effort, never fails the stop.
        self._auto_generate_report()

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

            # Keep the input file count current after the run too: in
            # real-time mode files that land after the timer are never
            # classified, and comparing the inbox with files_processed is
            # the only way to say so (round-4 audit, H5: 14 of 47 files
            # unprocessed, nothing on any surface). The 5 s TTL keeps it
            # to one directory listing per poll.
            if self.config:
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
            # "stopped" doubles as the idle state above, so a real stop is
            # the one that carries a reason (round-4 H2).
            self.status["stopped_run"] = bool(
                self.status.get("pipeline_status") == "stopped"
                and self.status.get("stop_reason")
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
            anchor = _dt.fromisoformat(start_iso).timestamp()
        except (TypeError, ValueError):
            return None
        # nanometanf's timer runs from the LAST detected input file (every
        # file resets it), so the countdown anchors on the newest input
        # file when one is newer than the start.
        newest = getattr(self, "_newest_input_mtime", None)
        if newest and newest > anchor:
            anchor = newest
        elapsed = time.time() - anchor
        # The pipeline's timer fires at timeout PLUS its grace period
        # (nanometanf realtime_processing_grace_period, default 5). The chip
        # used to count only the timeout and vanished five minutes before
        # the run actually ended (round-4 audit, H2).
        try:
            grace = int(self.config.get("realtime_processing_grace_period", 5) or 0)
        except (TypeError, ValueError):
            grace = 5
        remaining = int((int(timeout_minutes) + grace) * 60 - elapsed)
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
            newest_mtime = 0.0
            if os.path.exists(nanopore_dir):
                # Per-sample subdirectories too. The canonical detector
                # accepts conventional barcode<NN> plus custom-named subdirs
                # (Turex/, Zymo/, ...) so this counter stays accurate for
                # non-multiplex layouts that still use by_barcode mode.
                from nanometa_live.core.utils.auto_detect import find_sample_subdirs
                dirs = [nanopore_dir] + [str(d) for d in find_sample_subdirs(nanopore_dir)]
                for d in dirs:
                    try:
                        names = os.listdir(d)
                    except OSError:
                        continue
                    for f in names:
                        if not f.endswith(extensions):
                            continue
                        waiting_files += 1
                        try:
                            newest_mtime = max(newest_mtime, os.stat(os.path.join(d, f)).st_mtime)
                        except OSError:
                            continue

            # Update status with waiting files
            # Processed files comes from workflow_manager status
            self.status["files_waiting"] = waiting_files
            # The newest input file anchors the auto-stop countdown: the
            # pipeline's inactivity timer runs from the last detected file.
            self._newest_input_mtime = newest_mtime or None
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
        # time.monotonic(), not time.time(): the monotonic clock freezes
        # while the machine sleeps on macOS/Linux, so a laptop lid-close
        # longer than realtime_timeout_minutes no longer SIGTERMs a
        # healthy run the moment it wakes (round 3). Wall-clock deltas
        # jumped by the whole sleep interval.
        last_progress_monotonic = time.monotonic()
        last_finished_count = -1
        pipeline_has_worked = False

        while self.status.get("running"):
            try:
                # Get workflow manager status (also drives progress tracking)
                workflow_status = self.workflow_manager.get_status()

                # Progress signal: tasks running now, or the cumulative finished
                # (completed + failed) count advanced since the last poll. Either
                # resets the inactivity clock so an actively-working run is not
                # killed. A long conda-env build at the start of a fresh run
                # produces NO task activity, so we also defer the timeout until
                # the pipeline has done at least some task work -- otherwise the
                # build window looks like inactivity and the run is killed before
                # any task runs.
                finished_count = (
                    workflow_status.get("processes_complete", 0)
                    + workflow_status.get("processes_failed", 0)
                )
                running_now = workflow_status.get("processes_running", 0)
                if running_now > 0 or finished_count != last_finished_count:
                    last_finished_count = finished_count
                    last_progress_monotonic = time.monotonic()
                    if running_now > 0 or finished_count > 0:
                        pipeline_has_worked = True

                # Check realtime timeout (inactivity-based, once work has begun)
                if timeout_seconds is not None and pipeline_has_worked:
                    idle = self.inactivity_elapsed_s(
                        last_progress_monotonic, time.monotonic())
                    if idle >= timeout_seconds:
                        self._stop_for_inactivity(timeout_seconds, idle)
                        break

                # Thread-safe status update. Report generation is deferred
                # to after the lock is released: it takes seconds, and the
                # GUI's status polls block on this same lock.
                run_completed = False
                with self._status_lock:
                    # Detect pipeline termination (crash or completion)
                    if not workflow_status.get("running"):
                        run_completed = self._apply_terminal_workflow_status(
                            workflow_status)

                    # Update process information
                    self.status["processes_running"] = workflow_status.get("processes_running", 0)
                    self.status["processes_complete"] = workflow_status.get("processes_complete", 0)
                    self.status["files_processed"] = workflow_status.get("files_processed", 0)
                    self.status["current_batch"] = workflow_status.get("current_batch", 0)

                    # Update file counts
                    self._update_file_counts()

                    # Update last update time
                    self.status["last_update"] = time.time()

                if run_completed:
                    # Outside the lock on purpose (see above). Leave the
                    # operator report behind so the verdict survives
                    # closing the dashboard.
                    self._auto_generate_report()

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

    def _apply_terminal_workflow_status(self, workflow_status: dict) -> bool:
        """Classify a finished run and update ``self.status``.

        Returns True when the run completed (the caller then generates the
        operator report). Call with ``self._status_lock`` held.

        **The Nextflow exit code decides, not the failed-task count.**
        nanometanf isolates per-sample failures (``errorStrategy 'ignore'`` in
        conf/error_isolation.config), so one barcode failing is by design:
        every other sample runs to completion, all outputs publish, and
        Nextflow exits 0 with "completed successfully, but with errored
        process(es)". The trace still records that task as FAILED -- it has no
        "ignored" status -- so counting failures alone declared a successful
        3-barcode run failed and, worse, suppressed the auto-report that is
        supposed to outlive the dashboard (found in the 2026-08-17 multiplex
        assembly E2E, where the negative control had too few reads to
        assemble). The isolated failure is still reported, as a warning naming
        the tasks, so nothing is hidden.
        """
        if self._stop_intent:
            # A deliberate stop is in progress; the dead process is what was
            # asked for. stop() owns the report, so do not signal completion.
            self._finish_stopped_locked(self._stop_intent)
            return False

        workflow_errors = workflow_status.get("errors", [])
        if workflow_errors:
            self._fail_run(workflow_errors)
            self._record_final_status()
            return False

        processes_failed = workflow_status.get("processes_failed", 0)
        processes_complete = workflow_status.get("processes_complete", 0)
        exit_code = workflow_status.get("exit_code")
        failed_tasks = workflow_status.get("failed_tasks") or []

        if processes_failed > 0 and exit_code == 0:
            named = ", ".join(failed_tasks) if failed_tasks else (
                f"{processes_failed} task(s)")
            self.status["pipeline_status"] = "completed"
            self.status.setdefault("warnings", []).append(
                f"Run completed; {named} did not produce output and was "
                "isolated. Other samples are unaffected."
            )
            self.status["running"] = False
            logging.warning(
                "Pipeline completed with %d isolated task failure(s): %s",
                processes_failed, named,
            )
            self._record_final_status()
            return True

        if processes_failed > 0:
            self._fail_run(
                [f"Pipeline terminated with {processes_failed} failed process(es)"])
            self._record_final_status()
            return False

        if processes_complete > 0:
            self.status["pipeline_status"] = "completed"
            self.status["running"] = False
            logging.info("Pipeline completed successfully")
            self._record_final_status()
            return True

        # No completed processes and no errors -- likely a crash during
        # startup or configuration.
        self._fail_run(["Pipeline process terminated unexpectedly. "
                        "Check the Nextflow log for details."])
        self._record_final_status()
        return False

    @staticmethod
    def inactivity_elapsed_s(last_progress_monotonic: float,
                             now_monotonic: float) -> float:
        """Idle seconds for the realtime timeout, on the monotonic clock."""
        return max(0.0, now_monotonic - last_progress_monotonic)

    def _mark_started_locked(self) -> None:
        """Flip the status to running and drop the previous run's stop record.

        Call with ``self._status_lock`` held.
        """
        self.status["running"] = True
        self.status["pipeline_status"] = "running"
        self.status["start_time"] = datetime.now().isoformat()
        self.status["last_update"] = time.time()
        self.status.pop("stop_reason", None)
        self.status.pop("ended_at", None)
        self._stop_intent = None

    def _mark_stop_intent(self, reason: str) -> None:
        """Record that the run is being stopped on purpose (lock-free flag)."""
        self._stop_intent = reason

    def _finish_stopped_locked(self, reason: str) -> None:
        """Classify the run as stopped and leave the terminal record.

        Call with ``self._status_lock`` held. Idempotent: the monitor thread
        and stop() may both reach it for the same run.
        """
        self.status["running"] = False
        self.status["pipeline_status"] = "stopped"
        self.status["stop_reason"] = reason
        self.status["ended_at"] = datetime.now().isoformat(timespec="seconds")
        # A deliberate stop makes Nextflow exit non-zero; that is not an error.
        self.status["errors"] = []
        self.status["last_update"] = time.time()
        self._record_final_status()

    def _stop_for_inactivity(self, timeout_seconds: int, idle_s: float) -> None:
        """The GUI's inactivity backstop: stop, record why, leave a report."""
        reason = (
            f"inactivity timeout: no task progress for "
            f"{int(timeout_seconds / 60)} minutes"
        )
        logging.warning(
            f"Realtime inactivity timeout reached after {idle_s / 60:.1f} "
            f"minutes with no task progress, stopping pipeline"
        )
        self._mark_stop_intent(reason)
        try:
            self.workflow_manager.stop()
        except (OSError, RuntimeError, AttributeError) as e:
            logging.exception(f"Error stopping pipeline after timeout: {e}")
        with self._status_lock:
            self._finish_stopped_locked(reason)
        self._auto_generate_report()

    def _record_final_status(self) -> None:
        """Merge the terminal classification into .nanometa.run.json.

        The exported report reads ``final_status``/``final_errors`` from
        here (the export worker cannot see the live backend singleton), so
        a report generated over a crashed run refuses the green banner --
        the round-3 every-surface-says-the-same-thing rule. Best-effort:
        a missing outdir or a write failure never affects the run
        classification itself.
        """
        try:
            outdir = (self.config or {}).get("results_output_directory") or ""
            if not outdir or not os.path.isdir(outdir):
                return
            path = os.path.join(outdir, self.RUN_METADATA_FILENAME)
            meta = self.read_run_metadata(outdir) or {}
            meta["final_status"] = self.status.get("pipeline_status")
            meta["final_errors"] = list(self.status.get("errors") or [])
            # Why and when the run ended, and how far it got: the report
            # states these so a stopped run cannot read like a finished one.
            if self.status.get("stop_reason"):
                meta["stop_reason"] = self.status["stop_reason"]
            meta["ended_at"] = self.status.get("ended_at") or datetime.now().isoformat(
                timespec="seconds")
            meta["files_processed"] = int(self.status.get("files_processed") or 0)
            # The inbox at the end: the report can then state how many input
            # files the run never classified (round-4 audit, H5).
            try:
                self._update_file_counts()
                meta["input_files_at_end"] = int(self.status.get("files_waiting") or 0)
            except Exception:
                pass
            from nanometa_live.core.utils.atomic_write import atomic_write_json
            atomic_write_json(path, meta)
        except Exception:
            logging.warning("Could not record final run status", exc_info=True)

    def _fail_run(self, errors) -> None:
        """Mark the run failed, appending each error once. Lock held."""
        self.status["pipeline_status"] = "error"
        existing = set(self.status["errors"])
        for err in errors:
            if err not in existing:
                self.status["errors"].append(err)
                existing.add(err)
        self.status["running"] = False
        logging.error("Pipeline failed: %s", "; ".join(errors))


