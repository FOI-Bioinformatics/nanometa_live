"""
Nextflow workflow manager for Nanometa Live.

This module provides a clean interface to the nanometanf Nextflow pipeline,
handling configuration, execution, and monitoring. It replaces the Snakemake
workflow manager while maintaining a compatible interface.
"""

import os
import json
import shutil
import signal
import time
import glob
import logging
import subprocess
import threading
import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from nanometa_live.core.config.parameter_mapping import (
    create_nextflow_params,
    create_nextflow_config,
    validate_nanometanf_params
)


class NextflowManager:
    """Manages Nextflow pipeline execution and monitoring for nanometanf."""

    # Default remote repository
    DEFAULT_REMOTE_REPO = "foi-bioinformatics/nanometanf"

    def __init__(self, data_dir: str, pipeline_source: str = "remote:dev"):
        """
        Initialize the Nextflow manager.

        Args:
            data_dir: Base directory for storing data, logs, and work files
            pipeline_source: Pipeline source specification. Options:
                - "remote:dev" - GitHub repo, dev branch (default; active development)
                - "remote:master" - GitHub repo, master branch (legacy default branch)
                - "local:/path/to/nanometanf" - Local filesystem path
                - "/path/to/nanometanf" - Local filesystem path (no prefix)
            Note: the upstream FOI-Bioinformatics/nanometanf repository
            does not have a "main" branch; use "remote:dev" or
            "remote:master" instead.
        """
        self.data_dir = data_dir
        self.log_dir = os.path.join(data_dir, "logs")
        self.work_dir = os.path.join(data_dir, "work")
        self.params_file_path = None
        self.config_file_path = None
        self.execution_lock = threading.Lock()
        self.running = False
        self.process = None
        self.monitor_thread = None

        # Pipeline source configuration
        self.pipeline_source = pipeline_source

        # Run configuration stored by setup() for use in _run_workflow()
        self._run_config: Optional[Dict[str, Any]] = None

        self._last_trace_status = {}

        # Status dictionary matching SnakemakeManager interface
        self.status = {
            "running": False,
            "processes_complete": 0,
            "processes_running": 0,
            "processes_failed": 0,
            "total_processes": 0,
            "files_processed": 0,
            "current_batch": 0,
            "last_updated": None,
            "errors": [],
            "nextflow_pid": None,
            # Stage-level tracking for dashboard display
            "stages": [],  # List of {"name": str, "status": str, "count": int, "duration": str}
            "current_stage": None,  # Name of the currently active stage
            "stage_progress": {}  # {"STAGE_NAME": {"completed": N, "running": N, "failed": N}}
        }

        # Create directory structure
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.work_dir, exist_ok=True)

        logging.info(f"NextflowManager initialized with data_dir: {data_dir}")
        logging.info(f"Pipeline source: {pipeline_source}")

    def _check_docker_available(self) -> Tuple[bool, str]:
        """
        Check if Docker is available and running.

        Returns:
            Tuple of (available: bool, message: str)
        """
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                # Docker is installed but daemon may not be running
                if "Cannot connect to the Docker daemon" in result.stderr:
                    return False, "Docker daemon is not running. Please start Docker Desktop."
                elif "permission denied" in result.stderr.lower():
                    return False, "Docker permission denied. Add your user to the docker group."
                else:
                    return False, f"Docker error: {result.stderr.strip()[:100]}"
            return True, "Docker is available"
        except FileNotFoundError:
            return False, "Docker not found. Please install Docker Desktop."
        except subprocess.TimeoutExpired:
            return False, "Docker check timed out. Docker may be unresponsive."
        except (subprocess.CalledProcessError, PermissionError, OSError) as e:
            logging.exception("Docker availability check failed")
            return False, f"Error checking Docker: {e}"

    def _check_singularity_available(self) -> Tuple[bool, str]:
        """
        Check if Singularity/Apptainer is available.

        Supports both Singularity and Apptainer (the renamed community fork).

        Returns:
            Tuple of (available: bool, message: str)
        """
        # Try singularity first, then apptainer
        for cmd in ["singularity", "apptainer"]:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    version = result.stdout.strip()
                    logging.info(f"Found container runtime: {version}")
                    return True, f"{cmd.capitalize()} is available ({version})"
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                return False, f"{cmd.capitalize()} check timed out."
            except (subprocess.CalledProcessError, PermissionError, OSError):
                logging.exception(f"Error checking {cmd}")
                continue

        return False, (
            "Neither Singularity nor Apptainer found. "
            "Please install Singularity or Apptainer for containerized execution."
        )

    def _check_conda_available(self) -> Tuple[bool, str]:
        """
        Check if Conda is available for the conda profile.

        Returns:
            Tuple of (available: bool, message: str)
        """
        try:
            result = subprocess.run(
                ["conda", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                return True, f"Conda is available ({version})"
            return False, "Conda returned an error"
        except FileNotFoundError:
            return False, "Conda not found. Please install Conda/Miniconda/Miniforge."
        except subprocess.TimeoutExpired:
            return False, "Conda check timed out."
        except (subprocess.CalledProcessError, PermissionError, OSError) as e:
            logging.exception("Conda availability check failed")
            return False, f"Error checking Conda: {e}"

    @staticmethod
    def _purge_broken_conda_envs(work_dir: str) -> list:
        """Remove half-built conda env dirs in ``<work_dir>/conda``.

        Nextflow stores per-recipe conda envs as
        ``<work_dir>/conda/env-<hash>/``. A successful build leaves a
        ``conda-meta/history`` file (written last by conda). If a
        previous nanometa-live run was killed mid-build, the env dir
        exists but ``conda-meta/history`` does not, and Nextflow's
        cache treats the directory as already built. Subsequent runs
        then activate an empty env and fail with "command not found".

        Returns the list of paths removed (empty if everything was
        clean or the conda cache directory does not exist yet).
        """
        conda_cache = os.path.join(work_dir, "conda")
        if not os.path.isdir(conda_cache):
            return []
        removed = []
        for name in os.listdir(conda_cache):
            if not name.startswith("env-"):
                continue
            env_path = os.path.join(conda_cache, name)
            if not os.path.isdir(env_path):
                continue
            history_marker = os.path.join(env_path, "conda-meta", "history")
            if os.path.isfile(history_marker):
                # Fully-built env; leave it alone.
                continue
            try:
                shutil.rmtree(env_path)
                removed.append(env_path)
            except OSError as e:
                logging.warning(
                    "Could not remove half-built conda env %s: %s",
                    env_path, e,
                )
        return removed

    def _parse_pipeline_source(self) -> Tuple[str, Optional[str]]:
        """
        Parse the pipeline source configuration.

        Returns:
            Tuple of (pipeline_path, revision) where:
            - pipeline_path: GitHub repo name or local filesystem path
            - revision: Git branch/tag (e.g., 'master', 'dev') or None for local
        """
        source = self.pipeline_source

        if source.startswith("remote:"):
            # Remote repository with branch specification
            branch = source.split(":", 1)[1] if ":" in source else "master"
            return self.DEFAULT_REMOTE_REPO, branch

        elif source.startswith("local:"):
            # Local filesystem path with explicit prefix - strip the prefix
            local_path = source.split(":", 1)[1]
            if os.path.isdir(local_path):
                return local_path, None
            else:
                logging.warning(
                    f"Local pipeline path '{local_path}' not found. "
                    f"Attempting to use anyway."
                )
                return local_path, None

        elif os.path.isdir(source):
            # Local filesystem path (no prefix)
            return source, None

        elif source in ("master", "dev"):
            return self.DEFAULT_REMOTE_REPO, source

        else:
            # Assume it's a local path (may not exist yet)
            logging.warning(
                f"Pipeline source '{source}' not found as directory. "
                f"Treating as local path."
            )
            return source, None

    def set_pipeline_source(self, source: str) -> None:
        """
        Update the pipeline source configuration.

        Args:
            source: Pipeline source specification:
                - "remote:master" - GitHub repo with master branch (stable)
                - "remote:dev" - GitHub repo with dev branch (development)
                - "/path/to/local" - Local filesystem path
        """
        self.pipeline_source = source
        logging.info(f"Pipeline source updated to: {source}")

    def validate_pipeline_source(self, config: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """
        Validate that the configured pipeline source is resolvable.

        For local paths: check the directory exists and contains main.nf.
        For remote specs: check the GitHub branch resolves via ls-remote.
        In offline mode, remote sources are rejected immediately without
        any network call.

        Args:
            config: Optional configuration dict. When offline_mode is set
                and the source is remote, returns failure without a network
                call.

        Returns:
            Tuple of (ok: bool, message: str). A failure message describes
            what to fix (e.g., "branch 'master' not found on origin;
            try 'remote:dev' or a local path").
        """
        # Offline guard: reject remote sources before any network attempt.
        if config and config.get("offline_mode"):
            source = self.pipeline_source
            is_remote = (
                source.startswith("remote:")
                or source.startswith("https://")
                or source.startswith("git@")
                or source in ("master", "main", "dev")
            )
            if is_remote:
                return False, (
                    "Cannot use remote pipeline_source in offline mode. "
                    "Set pipeline_source to a local path in config.yaml."
                )

        pipeline_path, revision = self._parse_pipeline_source()

        # Local path: verify directory has a Nextflow entrypoint
        if revision is None:
            p = Path(pipeline_path)
            if not p.is_dir():
                return False, (
                    f"Pipeline source '{self.pipeline_source}' is not a "
                    f"readable directory. Set pipeline_source in config.yaml "
                    f"to a valid local path or a 'remote:<branch>' spec."
                )
            if not (p / "main.nf").exists():
                return False, (
                    f"Pipeline directory '{p}' does not contain main.nf; "
                    f"this does not look like a Nextflow pipeline checkout."
                )
            return True, f"Local pipeline at {p}"

        # Remote path: try to resolve the branch via git ls-remote.
        # This is network-dependent; a failure is not fatal here -- the
        # startup validator treats "couldn't reach GitHub" as a warning, but
        # a reachable-remote-with-missing-branch as a fatal misconfig.
        remote_url = f"https://github.com/{pipeline_path}.git"
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--heads", remote_url, revision],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            return True, (
                f"git not available to validate remote '{remote_url}' "
                f"branch '{revision}'; skipping pre-flight check."
            )
        except subprocess.TimeoutExpired:
            return True, (
                f"git ls-remote timed out while validating "
                f"remote:{revision}; skipping pre-flight check."
            )
        except (subprocess.CalledProcessError, PermissionError, OSError) as exc:  # pragma: no cover - defensive
            logging.exception(
                "Could not validate remote:%s via git ls-remote", revision,
            )
            return True, (
                f"Could not validate remote:{revision} ({exc}); "
                f"skipping pre-flight check."
            )

        if result.returncode != 0:
            # Network or auth error -- don't hard-fail on first run.
            return True, (
                f"git ls-remote returned non-zero for {remote_url}; "
                f"skipping pre-flight check. stderr: {result.stderr.strip()}"
            )

        if not result.stdout.strip():
            return False, (
                f"Branch '{revision}' not found on {pipeline_path}. "
                f"Set pipeline_source to an existing branch "
                f"(e.g. 'remote:dev' or 'remote:master') or to a local path."
            )

        return True, f"Remote pipeline at {pipeline_path} (revision: {revision})"

    def setup(self, config_path: str) -> Tuple[bool, str]:
        """
        Set up the Nextflow pipeline with configuration.

        Args:
            config_path: Path to Nanometa Live configuration file (YAML or JSON)

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            logging.info(f"Setting up Nextflow pipeline with config: {config_path}")

            # Load configuration
            with open(config_path, 'r') as f:
                if config_path.endswith('.yaml') or config_path.endswith('.yml'):
                    config = yaml.safe_load(f)
                else:
                    config = json.load(f)

            # Store a copy of the run config for env injection in _run_workflow()
            self._run_config = dict(config)

            # Convert to nanometanf parameters
            params = create_nextflow_params(config)
            custom_config = create_nextflow_config(config)

            # Validate parameters
            valid, message = validate_nanometanf_params(params)
            if not valid:
                logging.error(f"Parameter validation failed: {message}")
                return False, f"Parameter validation failed: {message}"

            # Write params file
            params_path = os.path.join(self.log_dir, "params.json")
            with open(params_path, 'w') as f:
                json.dump(params, f, indent=2)
            self.params_file_path = params_path
            logging.info(f"Wrote parameters to: {params_path}")

            # Write custom config
            config_path = os.path.join(self.log_dir, "custom.config")
            with open(config_path, 'w') as f:
                f.write(custom_config)
            self.config_file_path = config_path
            logging.info(f"Wrote custom config to: {config_path}")

            # Validate nextflow installation
            try:
                result = subprocess.run(
                    ["nextflow", "-version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode != 0:
                    return False, "Nextflow not found. Please install Nextflow."

                version_output = result.stdout
                logging.info(f"Nextflow version: {version_output.strip()}")

            except FileNotFoundError:
                return False, "Nextflow not found in PATH. Please install Nextflow."
            except subprocess.TimeoutExpired:
                return False, "Nextflow version check timed out"

            return True, "Nextflow pipeline setup successful"

        except FileNotFoundError as e:
            logging.error(f"Configuration file not found: {e}")
            return False, f"Configuration file not found: {config_path}"
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON configuration: {e}")
            return False, f"Invalid JSON configuration: {e}"
        except (PermissionError, OSError, UnicodeDecodeError) as e:
            logging.exception("File I/O error during Nextflow setup")
            return False, f"Setup error: {e}"
        except (ValueError, KeyError, TypeError) as e:
            logging.exception("Invalid configuration during Nextflow setup")
            return False, f"Setup error: {e}"
        except yaml.YAMLError as e:
            logging.exception("Invalid YAML configuration")
            return False, f"Invalid YAML configuration: {e}"

    def start(
        self,
        profile: str = "docker",
        cores: int = None,
        resume: bool = False
    ) -> Tuple[bool, str]:
        """
        Start the Nextflow pipeline execution.

        Args:
            profile: Nextflow profile to use (docker, singularity, conda)
            cores: Number of CPU cores (None uses config default)
            resume: Whether to resume from previous run

        Returns:
            Tuple of (success: bool, message: str)
        """
        with self.execution_lock:
            if self.running:
                return False, "Pipeline is already running"

            if not self.params_file_path or not self.config_file_path:
                return False, "Pipeline not set up. Call setup() first."

            try:
                logging.info(f"Starting Nextflow pipeline with profile: {profile}")

                # Check container runtime availability based on profile
                if profile == "docker":
                    docker_check = self._check_docker_available()
                    if not docker_check[0]:
                        return False, docker_check[1]
                    logging.info(docker_check[1])

                elif profile == "singularity":
                    singularity_check = self._check_singularity_available()
                    if not singularity_check[0]:
                        return False, singularity_check[1]
                    logging.info(singularity_check[1])

                elif profile == "conda":
                    conda_check = self._check_conda_available()
                    if not conda_check[0]:
                        return False, conda_check[1]
                    logging.info(conda_check[1])
                    # Sweep half-built conda env dirs from a previously
                    # interrupted run. Nextflow's conda cache treats the
                    # presence of an env directory as "already built" and
                    # will silently activate an empty env, producing a
                    # downstream "command not found" failure such as
                    # `multiqc: command not found`. Removing the partial
                    # dir forces a clean rebuild on this run.
                    purged = self._purge_broken_conda_envs(self.work_dir)
                    if purged:
                        logging.warning(
                            "Purged %d incomplete conda env(s) from prior "
                            "interrupted run: %s",
                            len(purged),
                            ", ".join(os.path.basename(p) for p in purged),
                        )

                # Parse pipeline source configuration
                pipeline_path, revision = self._parse_pipeline_source()
                logging.info(
                    f"Pipeline source: {pipeline_path}"
                    + (f" (revision: {revision})" if revision else " (local)")
                )

                # Build command
                cmd = ["nextflow", "run", pipeline_path]

                # Add revision flag for remote repositories
                if revision:
                    cmd.extend(["-r", revision])

                # Add common flags
                cmd.extend([
                    "-params-file", self.params_file_path,
                    "-c", self.config_file_path,
                    "-profile", profile,
                    "-work-dir", self.work_dir,
                    "-with-trace", os.path.join(self.log_dir, "trace.txt"),
                    "-with-report", os.path.join(self.log_dir, "report.html"),
                    "-with-timeline", os.path.join(self.log_dir, "timeline.html")
                ])

                if resume:
                    cmd.append("-resume")
                    logging.info("Resume mode enabled")

                logging.info(f"Command: {' '.join(cmd)}")

                # Start workflow in background thread
                threading.Thread(
                    target=self._run_workflow,
                    args=(cmd, self._run_config),
                    daemon=True
                ).start()

                # Update status
                self.running = True
                self.status["running"] = True
                self.status["last_updated"] = time.time()

                return True, f"Nextflow pipeline started with profile: {profile}"

            except (OSError, RuntimeError, ValueError) as e:
                logging.exception("Error starting Nextflow pipeline")
                return False, f"Start error: {e}"

    def stop(self) -> Tuple[bool, str]:
        """
        Stop the Nextflow pipeline execution.

        Returns:
            Tuple of (success: bool, message: str)
        """
        with self.execution_lock:
            if not self.running:
                return False, "Pipeline is not running"

            try:
                logging.info("Stopping Nextflow pipeline...")
                self._user_stopped = True

                if self.process and self.process.poll() is None:
                    # Terminate the entire process group (Nextflow + child processes
                    # such as Docker, Kraken2, etc.) so nothing is left running.
                    try:
                        pgid = os.getpgid(self.process.pid)
                        os.killpg(pgid, signal.SIGTERM)
                        logging.info(
                            f"Sent SIGTERM to process group {pgid}"
                        )
                    except (ProcessLookupError, PermissionError):
                        # Process group already gone; fall back to direct terminate
                        self.process.terminate()
                        logging.info("Sent SIGTERM to Nextflow process")

                    try:
                        self.process.wait(timeout=30)
                        message = "Pipeline stopped gracefully"
                        logging.info(message)
                    except subprocess.TimeoutExpired:
                        # Force kill the process group if still alive
                        try:
                            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            self.process.kill()
                        self.process.wait()
                        message = "Pipeline forcefully stopped (timeout)"
                        logging.warning(message)

                # Update status
                self.running = False
                self.status["running"] = False
                self.status["last_updated"] = time.time()

                return True, message

            except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError, OSError) as e:
                logging.exception("Error stopping Nextflow pipeline")
                return False, f"Stop error: {e}"

    def get_status(self) -> Dict[str, Any]:
        """
        Get current pipeline execution status.

        Returns:
            Dictionary with status information
        """
        return self.status.copy()

    @staticmethod
    def _build_nextflow_env(config: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """
        Build the subprocess environment for a Nextflow run.

        Starts from the current process environment and injects offline-mode
        variables when the corresponding config keys are set.

        Args:
            config: Run configuration dict (may be None).

        Returns:
            A copy of os.environ augmented with any offline-mode variables.
        """
        env = os.environ.copy()
        if not config:
            return env

        if config.get("offline_mode"):
            # The Nextflow bash launcher checks `NXF_OFFLINE == true` (string
            # equality, lowercase) to skip its self-update curl probe. The
            # JVM side accepts boolean-ish values, so "true" satisfies both.
            env["NXF_OFFLINE"] = "true"
            env["NXF_DISABLE_CHECK_LATEST"] = "true"
            logging.info("Offline mode active: NXF_OFFLINE=true and NXF_DISABLE_CHECK_LATEST=true injected.")

        cachedir = config.get("nxf_conda_cachedir", "")
        if cachedir:
            abs_cachedir = os.path.abspath(cachedir)
            if os.path.isdir(abs_cachedir):
                env["NXF_CONDA_CACHEDIR"] = abs_cachedir
                logging.info(f"NXF_CONDA_CACHEDIR set to: {abs_cachedir}")
            else:
                logging.warning(
                    f"nxf_conda_cachedir '{cachedir}' is not an existing directory; "
                    f"NXF_CONDA_CACHEDIR will not be set."
                )

        plugins_dir = config.get("nxf_plugins_dir", "")
        if plugins_dir:
            abs_plugins_dir = os.path.abspath(plugins_dir)
            if os.path.isdir(abs_plugins_dir):
                # NXF_PLUGINS_PATH is the load path that suppresses Nextflow's
                # registry.nextflow.io probe (Nextflow >= 25.x). NXF_PLUGINS_DIR
                # is the install target and does not stop the probe; we set
                # both so legacy versions still resolve plugins from the cache.
                env["NXF_PLUGINS_PATH"] = abs_plugins_dir
                env["NXF_PLUGINS_DIR"] = abs_plugins_dir
                logging.info(f"NXF_PLUGINS_PATH and NXF_PLUGINS_DIR set to: {abs_plugins_dir}")
            else:
                logging.warning(
                    f"nxf_plugins_dir '{plugins_dir}' is not an existing directory; "
                    f"NXF_PLUGINS_PATH/NXF_PLUGINS_DIR will not be set."
                )

        # NXF_HOME and NXF_TEMP. Nextflow writes plugin metadata, the
        # history file, and ~/.nextflow.log under NXF_HOME (default
        # ~/.nextflow). On a field machine where ~ is read-only or a
        # network share, those writes fail with NoSuchFileException
        # and surface as opaque "tmp folder" errors. Anchor both to
        # the results_output_directory when it is set so all Nextflow
        # state lands on the writable working filesystem.
        results_dir = config.get("results_output_directory", "")
        if results_dir:
            abs_results = os.path.abspath(results_dir)
            try:
                os.makedirs(abs_results, exist_ok=True)
            except OSError as exc:
                logging.warning(
                    f"Could not create results_output_directory "
                    f"'{abs_results}' for NXF_HOME/NXF_TEMP: {exc}"
                )
            else:
                nxf_home = os.path.join(abs_results, ".nextflow")
                nxf_temp = os.path.join(abs_results, ".nextflow_tmp")
                # Only set NXF_HOME if the calling environment did not
                # already pick one (operator override wins).
                if not env.get("NXF_HOME"):
                    env["NXF_HOME"] = nxf_home
                    logging.info(f"NXF_HOME set to: {nxf_home}")
                if not env.get("NXF_TEMP"):
                    env["NXF_TEMP"] = nxf_temp
                    logging.info(f"NXF_TEMP set to: {nxf_temp}")

        return env

    def _run_workflow(self, cmd: List[str], config: Optional[Dict[str, Any]] = None) -> None:
        """
        Execute the Nextflow command in subprocess.

        Args:
            cmd: Nextflow command as list of arguments
            config: Run configuration dict used to build the subprocess
                environment (offline-mode variables, conda cache dir, etc.)
        """
        self._user_stopped = False
        try:
            log_file = os.path.join(self.log_dir, "nextflow.log")
            logging.info(f"Nextflow output will be logged to: {log_file}")

            env = self._build_nextflow_env(config)

            with open(log_file, "w") as log:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=self.data_dir,
                    start_new_session=True,
                    env=env,
                )

                self.status["nextflow_pid"] = self.process.pid
                logging.info(f"Nextflow started with PID: {self.process.pid}")

                # Start monitoring thread
                self.monitor_thread = threading.Thread(
                    target=self._monitor_status,
                    daemon=True
                )
                self.monitor_thread.start()

                # Wait for completion
                exit_code = self.process.wait()

                if exit_code != 0:
                    if getattr(self, '_user_stopped', False):
                        # User-initiated stop: non-zero exit is expected
                        logging.info(f"Nextflow stopped by user (exit code {exit_code})")
                    else:
                        # Actual pipeline failure
                        error_details = self._extract_error_from_log(log_file)
                        error_msg = f"Nextflow exited with code {exit_code}"
                        if error_details:
                            error_msg = f"{error_msg}: {error_details}"
                        self.status["errors"].append(error_msg)
                        logging.error(error_msg)
                else:
                    logging.info("Nextflow completed successfully")

        except Exception as e:
            # Background thread top-of-loop: keep broad catch so a single
            # unexpected failure cannot leave the manager flagged as running
            # forever. logger.exception() preserves the stack trace.
            error_msg = f"Error in Nextflow workflow: {e}"
            logging.exception(error_msg)
            self.status["errors"].append(str(e))

        finally:
            # Update status on completion
            self.running = False
            self.status["running"] = False
            self.status["last_updated"] = time.time()
            logging.info("Nextflow workflow execution finished")

    def _monitor_status(self) -> None:
        """
        Monitor pipeline execution status via trace file and batch stats.

        Polls every 5 seconds while running.
        """
        logging.info("Status monitoring thread started")
        trace_path = os.path.join(self.log_dir, "trace.txt")

        while self.running and self.process:
            try:
                # Check if process is still running
                if self.process.poll() is not None:
                    logging.info("Nextflow process has terminated")
                    self.running = False
                    break

                # Parse trace file if it exists
                if os.path.exists(trace_path):
                    trace_status = self._parse_trace_file()
                    self.status.update(trace_status)

                # Parse real-time batch statistics
                realtime_stats = self._parse_realtime_stats()
                self.status.update(realtime_stats)

                # Update timestamp
                self.status["last_updated"] = time.time()

                # Sleep before next poll
                time.sleep(5)

            except Exception:
                # Background polling loop: keep broad catch so a transient
                # parse error does not kill the monitor thread. logger.exception()
                # preserves the stack trace for diagnosis.
                logging.exception("Error in status monitoring")
                time.sleep(5)

        logging.info("Status monitoring thread stopped")

    def _parse_trace_file(self) -> Dict[str, Any]:
        """
        Parse Nextflow trace file for process execution status.

        Returns:
            Dictionary with process counts and stage-level information
        """
        trace_path = os.path.join(self.log_dir, "trace.txt")

        try:
            if not os.path.exists(trace_path):
                return {}

            # Check file stability — avoid reading while Nextflow is writing
            try:
                stat = os.stat(trace_path)
                age = time.time() - stat.st_mtime
                if age < 1.0:
                    return self._last_trace_status or {}
            except OSError:
                return {}

            with open(trace_path, 'r') as f:
                lines = f.readlines()

            if len(lines) <= 1:  # Only header or empty
                return {}

            # Parse header to find column indices
            header = lines[0].strip().split('\t')
            col_indices = {col: idx for idx, col in enumerate(header)}

            name_col = col_indices.get('name')
            status_col = col_indices.get('status')
            if name_col is None or status_col is None:
                logging.warning("Trace file missing required columns (name, status)")
                return {}

            name_idx = name_col
            status_idx = status_col

            # Parse process status (skip header)
            completed = 0
            running = 0
            failed = 0

            # Track per-stage statistics
            stage_progress = {}  # {"STAGE_NAME": {"completed": N, "running": N, "failed": N}}
            current_stage = None

            for line in lines[1:]:
                parts = line.strip().split('\t')
                if len(parts) <= max(name_idx, status_idx):
                    continue

                # Extract process name (format: "PIPELINE:SUBWORKFLOW:PROCESS (sample)")
                full_name = parts[name_idx] if name_idx < len(parts) else ""
                status = parts[status_idx] if status_idx < len(parts) else ""

                # Extract the process name (last component before the sample tag)
                # e.g., "NANOMETANF:QC_ANALYSIS:FASTQC (barcode01)" -> "FASTQC"
                process_name = full_name
                if '(' in full_name:
                    process_name = full_name.split('(')[0].strip()
                if ':' in process_name:
                    process_name = process_name.split(':')[-1].strip()

                # Initialize stage tracking if needed
                if process_name and process_name not in stage_progress:
                    stage_progress[process_name] = {
                        "completed": 0,
                        "running": 0,
                        "failed": 0,
                        "total": 0
                    }

                # Count status
                if status == "COMPLETED":
                    completed += 1
                    if process_name:
                        stage_progress[process_name]["completed"] += 1
                        stage_progress[process_name]["total"] += 1
                elif status in ["RUNNING", "SUBMITTED"]:
                    running += 1
                    if process_name:
                        stage_progress[process_name]["running"] += 1
                        stage_progress[process_name]["total"] += 1
                        current_stage = process_name  # Track currently running stage
                elif status in ["FAILED", "ABORTED"]:
                    failed += 1
                    if process_name:
                        stage_progress[process_name]["failed"] += 1
                        stage_progress[process_name]["total"] += 1

            total = completed + running + failed

            # Build stages list for display (ordered by appearance in trace)
            stages = []
            for stage_name, counts in stage_progress.items():
                if counts["running"] > 0:
                    stage_status = "running"
                elif counts["failed"] > 0:
                    stage_status = "failed"
                elif counts["completed"] > 0 and counts["completed"] == counts["total"]:
                    stage_status = "completed"
                else:
                    stage_status = "pending"

                stages.append({
                    "name": stage_name,
                    "status": stage_status,
                    "completed": counts["completed"],
                    "running": counts["running"],
                    "failed": counts["failed"],
                    "total": counts["total"]
                })

            result = {
                "processes_complete": completed,
                "processes_running": running,
                "processes_failed": failed,
                "total_processes": total,
                "stages": stages,
                "current_stage": current_stage,
                "stage_progress": stage_progress
            }
            self._last_trace_status = result
            return result

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, ValueError, IndexError) as e:
            logging.exception("Error parsing trace file")
            return self._last_trace_status or {}

    def _parse_realtime_stats(self) -> Dict[str, Any]:
        """
        Parse nanometanf real-time batch statistics.

        Parses the snapshot JSON files generated by GENERATE_SNAPSHOT_STATS module.
        Output files are named: batch_<timestamp>_snapshot.json

        Returns:
            Dictionary with batch processing stats
        """
        try:
            # Get outdir from params
            if not self.params_file_path:
                return {}

            with open(self.params_file_path, 'r') as f:
                params = json.load(f)

            outdir = params.get("outdir", "")
            stats_dir = os.path.join(outdir, "realtime_batch_stats")

            if not os.path.isdir(stats_dir):
                return {}

            # Find all batch snapshot files (format: batch_<timestamp>_snapshot.json)
            batch_files = glob.glob(os.path.join(stats_dir, "*_snapshot.json"))

            if not batch_files:
                return {}

            # Sort by file modification time (most recent last)
            batch_files.sort(key=lambda x: os.path.getmtime(x))

            # Count total files and batches
            total_files = 0
            batch_count = len(batch_files)

            for batch_file in batch_files:
                try:
                    with open(batch_file, 'r') as f:
                        batch_data = json.load(f)

                    # Extract file count from the snapshot structure
                    # GENERATE_SNAPSHOT_STATS outputs: { "file_statistics": { "file_count": N } }
                    file_stats = batch_data.get("file_statistics", {})
                    file_count = file_stats.get("file_count", 0)

                    # Fallback to batch_info.file_count if file_statistics not present
                    if file_count == 0:
                        batch_info = batch_data.get("batch_info", {})
                        file_count = batch_info.get("file_count", 0)

                    # Legacy support: check for files_in_batch
                    if file_count == 0:
                        file_count = batch_data.get("files_in_batch", 0)

                    total_files += file_count

                except (json.JSONDecodeError, FileNotFoundError, PermissionError, OSError, UnicodeDecodeError) as e:
                    logging.exception(f"Error parsing batch file {batch_file}")
                    continue

            return {
                "files_processed": total_files,
                "current_batch": batch_count
            }

        except (json.JSONDecodeError, FileNotFoundError, PermissionError, OSError, UnicodeDecodeError) as e:
            logging.exception("Error parsing realtime stats")
            return {}

    def _extract_error_from_log(self, log_file: str, max_lines: int = 50) -> str:
        """
        Extract error information from the Nextflow log file.

        Looks for common Nextflow error patterns and returns a concise
        error message for display to the user.

        Args:
            log_file: Path to the nextflow.log file
            max_lines: Maximum number of lines to read from the end of the file

        Returns:
            Extracted error message or empty string if no specific error found
        """
        try:
            if not os.path.exists(log_file):
                return ""

            # Read the last N lines of the log file
            with open(log_file, 'r') as f:
                lines = f.readlines()

            # Get last max_lines lines
            tail_lines = lines[-max_lines:] if len(lines) > max_lines else lines

            # Common Nextflow error patterns to look for (in priority order)
            error_patterns = [
                # Parameter validation errors (high priority)
                (r"Validation of pipeline parameters failed", "Parameter validation failed"),
                (r"is less than", "Parameter value too low"),
                (r"is greater than", "Parameter value too high"),
                (r"Required parameter is missing", "Required parameter missing"),
                # Parameter/config errors
                (r"Unknown config attribute", "Configuration error"),
                (r"Not a valid project name", "Invalid project/repository name"),
                (r"Cannot find revision", "Invalid branch or revision"),
                (r"No such file", "File not found"),
                (r"Missing required parameter", "Missing required parameter"),
                (r"Invalid value for", "Invalid parameter value"),
                # Docker/container errors
                (r"docker.*not found", "Docker not found or not running"),
                (r"singularity.*not found", "Singularity not found"),
                (r"Cannot pull container", "Failed to pull container image"),
                (r"Unable to pull", "Failed to pull container image"),
                # Process errors
                (r"Error executing process", "Process execution failed"),
                (r"Command exit status", "Command failed"),
                (r"Pipeline completed with errors", "Pipeline failed"),
                # Connection/network errors
                (r"Unable to access", "Unable to access resource"),
                (r"Connection refused", "Connection refused"),
                # General errors (lower priority)
                (r"ERROR ~", None),  # Nextflow error message format
            ]

            # Search for error patterns in the log
            error_lines = []
            for line in tail_lines:
                line_stripped = line.strip()

                # Skip empty lines
                if not line_stripped:
                    continue

                # Check for error patterns
                for pattern, error_type in error_patterns:
                    if re.search(pattern, line_stripped, re.IGNORECASE):
                        # Clean up the line
                        clean_line = line_stripped
                        # Remove ANSI color codes if present
                        clean_line = re.sub(r'\x1b\[[0-9;]*m', '', clean_line)
                        # Remove timestamp prefix if present
                        clean_line = re.sub(r'^\[\d{4}-\d{2}-\d{2}.*?\]\s*', '', clean_line)
                        # Remove leading special chars
                        clean_line = re.sub(r'^[\s\-\*\>]+', '', clean_line)

                        if clean_line and clean_line not in error_lines:
                            error_lines.append(clean_line)
                            # Capture "Caused by:" context from following lines
                            line_idx = tail_lines.index(line)
                            for offset in range(1, 4):
                                if line_idx + offset < len(tail_lines):
                                    ctx = tail_lines[line_idx + offset].strip()
                                    ctx = re.sub(r'\x1b\[[0-9;]*m', '', ctx)
                                    if ctx and ('Caused by' in ctx or 'Command error' in ctx or ctx.startswith('>')):
                                        error_lines.append(ctx)
                        break

            # Return the most relevant error lines (up to 3)
            if error_lines:
                # Prioritize lines with "ERROR" or specific error messages
                priority_errors = [ln for ln in error_lines if 'ERROR' in ln.upper()]
                if priority_errors:
                    return "; ".join(priority_errors[:2])
                return "; ".join(error_lines[:2])

            # If no specific error pattern found, return last few non-empty lines
            non_empty_lines = [ln.strip() for ln in tail_lines if ln.strip()]
            if non_empty_lines:
                return non_empty_lines[-1][:200]  # Last line, truncated

            return ""

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError) as e:
            logging.exception("Error extracting error from log")
            return ""


