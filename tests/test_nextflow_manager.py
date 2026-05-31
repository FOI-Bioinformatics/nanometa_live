"""
Unit tests for core/workflow/nextflow_manager.py (was 31%).

Covers the deterministic, mockable surface of NextflowManager: pipeline-source
parsing/validation, the docker/singularity/conda availability probes (with
``subprocess.run`` mocked), the offline-mode subprocess-env builder, trace-file
and realtime-stats parsing, and Nextflow log error extraction. The threaded
``start``/``_run_workflow``/``_monitor_status`` paths are intentionally left to
the integration tier -- nothing here spawns a process or hits the network.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.workflow.nextflow_manager import NextflowManager

pytestmark = pytest.mark.unit


@pytest.fixture
def manager(tmp_path):
    return NextflowManager(str(tmp_path), pipeline_source="remote:dev")


def _completed(returncode=0, stdout="", stderr=""):
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


class TestInit:
    def test_creates_log_and_work_dirs(self, tmp_path):
        m = NextflowManager(str(tmp_path))
        assert os.path.isdir(m.log_dir)
        assert os.path.isdir(m.work_dir)
        assert m.running is False
        assert m.status["running"] is False

    def test_default_pipeline_source(self, tmp_path):
        m = NextflowManager(str(tmp_path))
        assert m.pipeline_source == "remote:dev"


class TestParsePipelineSource:
    def test_remote_with_branch(self, manager):
        path, rev = manager._parse_pipeline_source()
        assert path == NextflowManager.DEFAULT_REMOTE_REPO
        assert rev == "dev"

    def test_remote_master(self, tmp_path):
        m = NextflowManager(str(tmp_path), pipeline_source="remote:master")
        path, rev = m._parse_pipeline_source()
        assert rev == "master"

    def test_local_prefix_path(self, tmp_path):
        m = NextflowManager(str(tmp_path), pipeline_source=f"local:{tmp_path}")
        path, rev = m._parse_pipeline_source()
        assert path == str(tmp_path)
        assert rev is None

    def test_bare_existing_dir(self, tmp_path):
        m = NextflowManager(str(tmp_path), pipeline_source=str(tmp_path))
        path, rev = m._parse_pipeline_source()
        assert path == str(tmp_path)
        assert rev is None

    def test_bare_branch_keyword(self, tmp_path):
        m = NextflowManager(str(tmp_path), pipeline_source="master")
        path, rev = m._parse_pipeline_source()
        assert path == NextflowManager.DEFAULT_REMOTE_REPO
        assert rev == "master"

    def test_unknown_treated_as_local(self, tmp_path):
        m = NextflowManager(str(tmp_path), pipeline_source="/does/not/exist")
        path, rev = m._parse_pipeline_source()
        assert path == "/does/not/exist"
        assert rev is None


class TestSetPipelineSource:
    def test_updates_source(self, manager):
        manager.set_pipeline_source("remote:master")
        assert manager.pipeline_source == "remote:master"


class TestValidatePipelineSource:
    def test_offline_rejects_remote(self, manager):
        ok, msg = manager.validate_pipeline_source({"offline_mode": True})
        assert ok is False
        assert "offline" in msg.lower()

    def test_local_missing_dir_fails(self, tmp_path):
        m = NextflowManager(str(tmp_path), pipeline_source="/no/such/pipeline")
        ok, msg = m.validate_pipeline_source()
        assert ok is False
        assert "readable directory" in msg

    def test_local_without_main_nf_fails(self, tmp_path):
        src = tmp_path / "pipe"
        src.mkdir()
        m = NextflowManager(str(tmp_path), pipeline_source=str(src))
        ok, msg = m.validate_pipeline_source()
        assert ok is False
        assert "main.nf" in msg

    def test_local_with_main_nf_passes(self, tmp_path):
        src = tmp_path / "pipe"
        src.mkdir()
        (src / "main.nf").write_text("// nextflow")
        m = NextflowManager(str(tmp_path), pipeline_source=str(src))
        ok, msg = m.validate_pipeline_source()
        assert ok is True
        assert "Local pipeline" in msg

    def test_remote_branch_resolves(self, manager):
        with patch("subprocess.run", return_value=_completed(0, stdout="abc123\trefs/heads/dev")):
            ok, msg = manager.validate_pipeline_source()
        assert ok is True
        assert "dev" in msg

    def test_remote_branch_not_found_fails(self, tmp_path):
        m = NextflowManager(str(tmp_path), pipeline_source="remote:nope")
        with patch("subprocess.run", return_value=_completed(0, stdout="")):
            ok, msg = m.validate_pipeline_source()
        assert ok is False
        assert "not found" in msg

    def test_remote_git_missing_is_soft_pass(self, manager):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok, msg = manager.validate_pipeline_source()
        # git unavailable -> can't validate, but don't hard-fail first run.
        assert ok is True
        assert "skipping" in msg.lower()

    def test_remote_network_error_is_soft_pass(self, manager):
        with patch("subprocess.run", return_value=_completed(1, stderr="could not connect")):
            ok, msg = manager.validate_pipeline_source()
        assert ok is True


class TestToolAvailabilityChecks:
    def test_docker_available(self, manager):
        with patch("subprocess.run", return_value=_completed(0)):
            ok, msg = manager._check_docker_available()
        assert ok is True

    def test_docker_daemon_down(self, manager):
        with patch("subprocess.run", return_value=_completed(1, stderr="Cannot connect to the Docker daemon")):
            ok, msg = manager._check_docker_available()
        assert ok is False
        assert "daemon is not running" in msg

    def test_docker_not_installed(self, manager):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok, msg = manager._check_docker_available()
        assert ok is False
        assert "not found" in msg.lower()

    def test_singularity_available(self, manager):
        with patch("subprocess.run", return_value=_completed(0, stdout="singularity version 3.8")):
            ok, msg = manager._check_singularity_available()
        assert ok is True
        assert "available" in msg.lower()

    def test_singularity_falls_back_to_apptainer(self, manager):
        # First call (singularity) raises FileNotFoundError, second (apptainer) succeeds.
        outcomes = [FileNotFoundError(), _completed(0, stdout="apptainer version 1.1")]

        def _side(cmd, **kw):
            r = outcomes.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with patch("subprocess.run", side_effect=_side):
            ok, msg = manager._check_singularity_available()
        assert ok is True
        assert "Apptainer" in msg

    def test_singularity_neither_found(self, manager):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok, msg = manager._check_singularity_available()
        assert ok is False
        assert "Neither" in msg

    def test_conda_available(self, manager):
        with patch("subprocess.run", return_value=_completed(0, stdout="conda 24.1.0")):
            ok, msg = manager._check_conda_available()
        assert ok is True

    def test_conda_not_found(self, manager):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok, msg = manager._check_conda_available()
        assert ok is False
        assert "not found" in msg.lower()


class TestBuildNextflowEnv:
    def test_none_config_returns_environ_copy(self):
        env = NextflowManager._build_nextflow_env(None)
        assert env == os.environ.copy()

    def test_offline_mode_injects_flags(self):
        env = NextflowManager._build_nextflow_env({"offline_mode": True})
        assert env["NXF_OFFLINE"] == "true"  # literal string, not "1"
        assert env["NXF_DISABLE_CHECK_LATEST"] == "true"

    def test_no_offline_no_flags(self):
        env = NextflowManager._build_nextflow_env({"offline_mode": False})
        assert "NXF_OFFLINE" not in env

    def test_conda_cachedir_set_when_dir_exists(self, tmp_path):
        cache = tmp_path / "conda_cache"
        cache.mkdir()
        env = NextflowManager._build_nextflow_env({"nxf_conda_cachedir": str(cache)})
        assert env["NXF_CONDA_CACHEDIR"] == str(cache)

    def test_conda_cachedir_skipped_when_missing(self, tmp_path):
        env = NextflowManager._build_nextflow_env(
            {"nxf_conda_cachedir": str(tmp_path / "nope")}
        )
        assert "NXF_CONDA_CACHEDIR" not in env

    def test_plugins_dir_sets_both_vars(self, tmp_path):
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        env = NextflowManager._build_nextflow_env({"nxf_plugins_dir": str(plugins)})
        assert env["NXF_PLUGINS_PATH"] == str(plugins)
        assert env["NXF_PLUGINS_DIR"] == str(plugins)

    def test_results_dir_anchors_nxf_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NXF_HOME", raising=False)
        monkeypatch.delenv("NXF_TEMP", raising=False)
        results = tmp_path / "results"
        results.mkdir()
        env = NextflowManager._build_nextflow_env(
            {"results_output_directory": str(results)}
        )
        assert env["NXF_HOME"] == os.path.join(str(results), ".nextflow")
        assert env["NXF_TEMP"] == os.path.join(str(results), ".nextflow_tmp")

    def test_operator_nxf_home_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NXF_HOME", "/operator/home")
        results = tmp_path / "results"
        results.mkdir()
        env = NextflowManager._build_nextflow_env(
            {"results_output_directory": str(results)}
        )
        assert env["NXF_HOME"] == "/operator/home"


class TestParseTraceFile:
    def _write_trace(self, manager, lines):
        path = os.path.join(manager.log_dir, "trace.txt")
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        # Backdate mtime so the <1s stability guard does not short-circuit.
        old = os.stat(path).st_mtime - 100
        os.utime(path, (old, old))
        return path

    def test_missing_file_returns_empty(self, manager):
        assert manager._parse_trace_file() == {}

    def test_header_only_returns_empty(self, manager):
        self._write_trace(manager, ["name\tstatus"])
        assert manager._parse_trace_file() == {}

    def test_missing_required_columns(self, manager):
        self._write_trace(manager, ["foo\tbar", "a\tb"])
        assert manager._parse_trace_file() == {}

    def test_counts_statuses_and_stages(self, manager):
        self._write_trace(manager, [
            "name\tstatus",
            "NANOMETANF:QC:FASTQC (bc01)\tCOMPLETED",
            "NANOMETANF:QC:FASTQC (bc02)\tCOMPLETED",
            "NANOMETANF:CLASSIFY:KRAKEN2 (bc01)\tRUNNING",
            "NANOMETANF:CLASSIFY:KRAKEN2 (bc02)\tFAILED",
        ])
        out = manager._parse_trace_file()
        assert out["processes_complete"] == 2
        assert out["processes_running"] == 1
        assert out["processes_failed"] == 1
        assert out["total_processes"] == 4
        assert out["current_stage"] == "KRAKEN2"
        # FASTQC stage fully completed; KRAKEN2 has a running task.
        stages = {s["name"]: s for s in out["stages"]}
        assert stages["FASTQC"]["status"] == "completed"
        assert stages["KRAKEN2"]["status"] == "running"

    def test_recently_written_file_returns_cached(self, manager):
        path = os.path.join(manager.log_dir, "trace.txt")
        with open(path, "w") as f:
            f.write("name\tstatus\nA:B:P (x)\tCOMPLETED\n")
        # Fresh mtime (now) -> within the 1s window -> returns cached (empty) value.
        manager._last_trace_status = {"sentinel": True}
        assert manager._parse_trace_file() == {"sentinel": True}


class TestParseRealtimeStats:
    def test_no_params_file_returns_empty(self, manager):
        assert manager._parse_realtime_stats() == {}

    def test_no_stats_dir_returns_empty(self, manager, tmp_path):
        params = os.path.join(manager.log_dir, "params.json")
        with open(params, "w") as f:
            json.dump({"outdir": str(tmp_path / "out")}, f)
        manager.params_file_path = params
        assert manager._parse_realtime_stats() == {}

    def test_aggregates_file_counts(self, manager, tmp_path):
        outdir = tmp_path / "out"
        stats_dir = outdir / "realtime_batch_stats"
        stats_dir.mkdir(parents=True)
        (stats_dir / "batch_1_snapshot.json").write_text(
            json.dumps({"file_statistics": {"file_count": 3}})
        )
        (stats_dir / "batch_2_snapshot.json").write_text(
            json.dumps({"batch_info": {"file_count": 2}})
        )
        params = os.path.join(manager.log_dir, "params.json")
        with open(params, "w") as f:
            json.dump({"outdir": str(outdir)}, f)
        manager.params_file_path = params

        out = manager._parse_realtime_stats()
        assert out["files_processed"] == 5
        assert out["current_batch"] == 2

    def test_corrupt_snapshot_is_skipped(self, manager, tmp_path):
        outdir = tmp_path / "out"
        stats_dir = outdir / "realtime_batch_stats"
        stats_dir.mkdir(parents=True)
        (stats_dir / "batch_1_snapshot.json").write_text("{not json")
        (stats_dir / "batch_2_snapshot.json").write_text(
            json.dumps({"files_in_batch": 7})
        )
        params = os.path.join(manager.log_dir, "params.json")
        with open(params, "w") as f:
            json.dump({"outdir": str(outdir)}, f)
        manager.params_file_path = params

        out = manager._parse_realtime_stats()
        # The corrupt file is skipped; the legacy "files_in_batch" key is read.
        assert out["files_processed"] == 7
        assert out["current_batch"] == 2


class TestExtractErrorFromLog:
    def _log(self, manager, text):
        path = os.path.join(manager.log_dir, "nextflow.log")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_missing_file_returns_empty(self, manager):
        assert manager._extract_error_from_log("/no/such.log") == ""

    def test_param_validation_pattern(self, manager):
        path = self._log(manager, "Validation of pipeline parameters failed\nmore\n")
        msg = manager._extract_error_from_log(path)
        assert "Validation of pipeline parameters failed" in msg

    def test_strips_ansi_and_timestamp(self, manager):
        path = self._log(
            manager,
            "[2026-05-31 10:00:00] \x1b[31mERROR ~ Error executing process\x1b[0m\n",
        )
        msg = manager._extract_error_from_log(path)
        assert "\x1b[" not in msg
        assert "Error executing process" in msg

    def test_no_pattern_returns_last_line(self, manager):
        path = self._log(manager, "line one\nthe final boring line\n")
        msg = manager._extract_error_from_log(path)
        assert msg == "the final boring line"
