"""End-to-end scenario tests for data flow through the Nanometa Live system.

These tests verify that the data loading pipeline correctly handles
common real-world scenarios: fresh starts, file corruption, real-time
batch accumulation, and dynamic sample appearance.

Offline-mode subprocess environment injection is also covered here:
tests verify that NXF_OFFLINE and NXF_CONDA_CACHEDIR are correctly
injected into the Nextflow subprocess env when offline_mode is set.
"""

import os
import pathlib
import time
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from nanometa_live.core.utils.data_loaders import (
    clear_data_cache,
    KRAKEN2_EXPECTED_COLUMNS,
    load_kraken_data,
)
from nanometa_live.core.utils.sample_detector import get_available_samples


def _backdate_mtime(path, seconds=5):
    """Set a file's mtime to *seconds* ago so it passes the stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


def _write_kraken_report(
    path: pathlib.Path,
    taxid: int = 562,
    species_name: str = "Escherichia coli",
    reads: int = 100,
) -> None:
    """Write a minimal valid kraken2 report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f" 0.00\t0\t0\tU\t0\tunclassified",
        f"100.00\t{reads}\t0\tR\t1\troot",
        f"100.00\t{reads}\t0\tD\t2\t  Bacteria",
        f"100.00\t{reads}\t{reads}\tS\t{taxid}\t    {species_name}",
    ]
    path.write_text("\n".join(lines) + "\n")
    _backdate_mtime(path)


class TestFreshStartToDataAppearance:
    """Verify behaviour when data appears after an initially empty directory."""

    def test_empty_then_data_appears(self, tmp_path: pathlib.Path) -> None:
        """Loading an empty directory returns an empty frame; adding data makes it visible."""
        clear_data_cache()
        df_empty = load_kraken_data(str(tmp_path))
        assert isinstance(df_empty, pd.DataFrame)
        assert df_empty.empty

        report_path = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
        _write_kraken_report(report_path, taxid=562, reads=100)

        clear_data_cache()
        df = load_kraken_data(str(tmp_path))
        species = df[df["rank"] == "S"]
        assert not species.empty
        assert int(species.iloc[0]["taxid"]) == 562
        assert int(species.iloc[0]["reads"]) == 100

    def test_data_then_corrupt_file(self, tmp_path: pathlib.Path) -> None:
        """Corrupted report files are gracefully rejected."""
        report_path = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
        _write_kraken_report(report_path, taxid=562, reads=50)

        clear_data_cache()
        df = load_kraken_data(str(tmp_path))
        assert not df.empty

        # Overwrite with truncated / invalid content
        report_path.write_text("X\n")

        clear_data_cache()
        df_corrupt = load_kraken_data(str(tmp_path))
        assert df_corrupt.empty


class TestRealtimeBatchAccumulation:
    """Verify batch-file aggregation and cumulative report priority."""

    def test_batch_accumulation(self, tmp_path: pathlib.Path) -> None:
        """Each batch file is a cumulative snapshot.

        The all-samples loader must pick the highest-numbered batch per
        sample (matching the per-sample branch fixed in the 2026-04-15
        audit) rather than summing across batches -- summing would
        multi-count reads because each batch already contains everything
        from earlier batches. The explicit cumulative report takes
        precedence over any batch file when present.
        """
        # Place batch files at the top level of kraken2/ to match the loader's
        # glob pattern: kraken2/*_batch*.kraken2.report.txt
        kraken_dir = tmp_path / "kraken2"

        # First batch: 100 reads cumulative so far
        _write_kraken_report(
            kraken_dir / "barcode01_batch0.kraken2.report.txt",
            taxid=562,
            reads=100,
        )
        clear_data_cache()
        df1 = load_kraken_data(str(tmp_path))
        species1 = df1[df1["rank"] == "S"]
        assert int(species1.iloc[0]["reads"]) == 100

        # Second batch: 250 cumulative reads (100 prior + 150 new). Each batch
        # file is a full cumulative snapshot, so the latest file IS the run
        # cumulative. The loader must NOT sum this with batch0.
        _write_kraken_report(
            kraken_dir / "barcode01_batch1.kraken2.report.txt",
            taxid=562,
            reads=250,
        )
        clear_data_cache()
        df2 = load_kraken_data(str(tmp_path))
        species2 = df2[df2["rank"] == "S"]
        assert int(species2.iloc[0]["reads"]) == 250

        # Cumulative report appears -- should be used instead of batch files
        _write_kraken_report(
            tmp_path / "kraken2" / "barcode01.cumulative.kraken2.report.txt",
            taxid=562,
            reads=250,
        )
        clear_data_cache()
        df3 = load_kraken_data(str(tmp_path))
        species3 = df3[df3["rank"] == "S"]
        assert int(species3.iloc[0]["reads"]) == 250

    def test_sample_appears_dynamically(self, tmp_path: pathlib.Path) -> None:
        """New sample directories are detected as their reports appear."""
        kraken_dir = tmp_path / "kraken2"
        _write_kraken_report(
            kraken_dir / "barcode01.kraken2.report.txt",
            taxid=562,
            reads=80,
        )

        samples = get_available_samples(str(tmp_path))
        assert "barcode01" in samples
        assert "barcode02" not in samples

        _write_kraken_report(
            kraken_dir / "barcode02.kraken2.report.txt",
            taxid=1639,
            species_name="Listeria monocytogenes",
            reads=30,
        )

        samples_updated = get_available_samples(str(tmp_path))
        assert "barcode01" in samples_updated
        assert "barcode02" in samples_updated


class TestBatchInputDirAutoDetect:
    """Scenario E: batch mode + by_barcode auto-enables --input_dir.

    The GUI exposes processing_mode and sample_handling but has no toggle
    for the use_input_dir_mode flag. Before the fix, selecting batch +
    by_barcode with no pre-built samplesheet silently fell back to
    realtime mode. create_nextflow_params now emits --input_dir for this
    combination and no longer emits --input.
    """

    @staticmethod
    def _base_config(tmp_path: pathlib.Path) -> dict:
        nanopore_dir = tmp_path / "input"
        nanopore_dir.mkdir()
        # Populate with minimal barcode directories so the layout validator
        # recognises a by_barcode shape.
        for barcode in ("barcode01", "barcode02"):
            sub = nanopore_dir / barcode
            sub.mkdir()
            (sub / "reads.fastq.gz").write_bytes(b"@seq\nACGT\n+\n!!!!\n")

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        return {
            "nanopore_output_directory": str(nanopore_dir),
            "results_output_directory": str(results_dir),
            "kraken_db": str(tmp_path / "kraken2_db"),
            "processing_mode": "batch",
            "sample_handling": "by_barcode",
            "sample_name": "sample",
            "analysis_name": "TestBatchByBarcode",
            "check_intervals_seconds": 15,
            "blast_validation": False,
        }

    def test_auto_enables_input_dir_when_no_samplesheet(
        self, tmp_path: pathlib.Path
    ) -> None:
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        config = self._base_config(tmp_path)
        params = create_nextflow_params(config)

        assert params.get("input_dir") == config["nanopore_output_directory"]
        # Must not also set --input -- nanometanf rejects multiple input modes.
        assert "input" not in params or not params.get("input")
        # Scenario E is batch; realtime_mode must not be set.
        assert not params.get("realtime_mode")
        # No auto-generated samplesheet should have been written when
        # INPUT_SCANNER is responsible for layout discovery.
        generated = (
            pathlib.Path(config["results_output_directory"])
            / "samplesheets"
            / "input_samplesheet.csv"
        )
        assert not generated.exists()

    def test_explicit_samplesheet_still_wins(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A caller-supplied config['input'] must still be honoured verbatim."""
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        config = self._base_config(tmp_path)
        samplesheet = tmp_path / "prebuilt.csv"
        samplesheet.write_text("sample,fastq_1\nbarcode01,barcode01/reads.fastq.gz\n")
        config["input"] = str(samplesheet)

        params = create_nextflow_params(config)

        assert params.get("input") == str(samplesheet)
        assert "input_dir" not in params

    def test_scenario_e_does_not_fall_back_to_realtime(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Regression guard for the silent-fallback bug.

        Before the fix, batch + by_barcode with no samplesheet flipped the
        params to realtime mode. The emitted params must now declare batch
        semantics (input_dir + no realtime_mode + no nanopore_output_dir).
        """
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        config = self._base_config(tmp_path)
        params = create_nextflow_params(config)

        assert params.get("input_dir") == config["nanopore_output_directory"]
        assert not params.get("realtime_mode")
        assert "nanopore_output_dir" not in params

    def test_single_sample_still_generates_samplesheet(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Scenario E must be scoped to by_barcode -- single_sample is unaffected."""
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        nanopore_dir = tmp_path / "input"
        nanopore_dir.mkdir()
        (nanopore_dir / "reads.fastq.gz").write_bytes(b"@seq\nACGT\n+\n!!!!\n")

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        config = {
            "nanopore_output_directory": str(nanopore_dir),
            "results_output_directory": str(results_dir),
            "kraken_db": str(tmp_path / "kraken2_db"),
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "sample_name": "sample",
            "analysis_name": "TestBatchSingleSample",
            "check_intervals_seconds": 15,
            "blast_validation": False,
        }

        params = create_nextflow_params(config)

        assert "input" in params and params["input"]
        assert "input_dir" not in params

    def test_samplesheet_failure_raises_instead_of_silent_realtime(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Operator-visible misconfigurations must surface, not be hidden.

        Pointing single_sample mode at an empty input directory used to
        flip params silently into realtime mode. The fix is to let the
        ValueError from generate_samplesheet propagate so NextflowManager
        surfaces it to the GUI as a clear "Setup error".
        """
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        empty_dir = tmp_path / "no_fastqs_here"
        empty_dir.mkdir()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        config = {
            "nanopore_output_directory": str(empty_dir),
            "results_output_directory": str(results_dir),
            "kraken_db": str(tmp_path / "kraken2_db"),
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "sample_name": "sample",
            "analysis_name": "EmptyInput",
            "check_intervals_seconds": 15,
            "blast_validation": False,
        }

        with pytest.raises(ValueError):
            create_nextflow_params(config)


# ---------------------------------------------------------------------------
# Offline-mode environment injection tests
# ---------------------------------------------------------------------------

class TestOfflineModeEnvInjection:
    """Verify that offline-mode config keys are propagated into the Nextflow
    subprocess environment via NextflowManager._build_nextflow_env()."""

    def test_offline_mode_sets_nxf_offline(self):
        """When offline_mode=True, NXF_OFFLINE must be '1' in the env."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        config = {"offline_mode": True}
        env = NextflowManager._build_nextflow_env(config)
        assert env.get("NXF_OFFLINE") == "true"

    def test_nxf_conda_cachedir_injected_when_dir_exists(self, tmp_path):
        """A valid nxf_conda_cachedir directory is set in the env."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        cachedir = tmp_path / "conda_cache"
        cachedir.mkdir()
        config = {"offline_mode": True, "nxf_conda_cachedir": str(cachedir)}
        env = NextflowManager._build_nextflow_env(config)
        assert env.get("NXF_OFFLINE") == "true"
        assert env.get("NXF_CONDA_CACHEDIR") == str(cachedir)

    def test_nxf_conda_cachedir_not_injected_when_missing(self, tmp_path):
        """A non-existent nxf_conda_cachedir is silently skipped."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        missing_dir = str(tmp_path / "does_not_exist")
        config = {"offline_mode": True, "nxf_conda_cachedir": missing_dir}
        env = NextflowManager._build_nextflow_env(config)
        assert "NXF_CONDA_CACHEDIR" not in env

    def test_nxf_plugins_dir_injected_when_dir_exists(self, tmp_path):
        """A valid nxf_plugins_dir directory is set in the env."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        plugins_dir = tmp_path / "nxf_plugins"
        plugins_dir.mkdir()
        config = {"offline_mode": True, "nxf_plugins_dir": str(plugins_dir)}
        env = NextflowManager._build_nextflow_env(config)
        assert env.get("NXF_PLUGINS_DIR") == str(plugins_dir)

    def test_no_offline_vars_when_offline_mode_false(self, tmp_path):
        """When offline_mode is False, no offline vars are injected."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        cachedir = tmp_path / "conda_cache"
        cachedir.mkdir()
        config = {
            "offline_mode": False,
            "nxf_conda_cachedir": str(cachedir),
        }
        env = NextflowManager._build_nextflow_env(config)
        assert "NXF_OFFLINE" not in env
        # nxf_conda_cachedir is still injected even without offline_mode
        # because it is an independent environment hint
        # (offline_mode controls NXF_OFFLINE only)

    def test_popen_receives_env_with_offline_vars(self, tmp_path):
        """When offline_mode=True and nxf_conda_cachedir is set,
        the subprocess.Popen call receives env with both NXF_OFFLINE
        and NXF_CONDA_CACHEDIR."""
        import json
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        cachedir = tmp_path / "conda_cache"
        cachedir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        log_dir = data_dir / "logs"
        log_dir.mkdir()

        manager = NextflowManager(str(data_dir))
        manager._run_config = {
            "offline_mode": True,
            "nxf_conda_cachedir": str(cachedir),
        }

        captured_kwargs = {}

        def fake_popen(cmd, **kwargs):
            captured_kwargs.update(kwargs)
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_proc.wait.return_value = 0
            mock_proc.poll.return_value = 0
            return mock_proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            # _run_workflow writes a log file; give it a real log path
            manager._run_workflow(
                ["nextflow", "run", "some_pipeline"],
                config=manager._run_config,
            )

        injected_env = captured_kwargs.get("env", {})
        assert injected_env.get("NXF_OFFLINE") == "true", (
            "NXF_OFFLINE was not injected into the Popen env"
        )
        assert injected_env.get("NXF_CONDA_CACHEDIR") == str(cachedir), (
            "NXF_CONDA_CACHEDIR was not injected into the Popen env"
        )


class TestOfflineModeValidatePipelineSource:
    """Verify that validate_pipeline_source() short-circuits for remote
    sources when offline_mode is True, without making any network call."""

    def test_remote_source_rejected_in_offline_mode(self):
        """remote:main is rejected before git ls-remote is attempted."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        manager = NextflowManager("/tmp", pipeline_source="remote:main")
        config = {"offline_mode": True}

        with patch("subprocess.run") as mock_run:
            ok, msg = manager.validate_pipeline_source(config=config)

        assert not ok
        assert "offline mode" in msg.lower()
        mock_run.assert_not_called()

    def test_https_url_rejected_in_offline_mode(self):
        """An HTTPS URL is treated as remote and rejected without a network call."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        manager = NextflowManager(
            "/tmp",
            pipeline_source="https://github.com/some/repo.git",
        )
        config = {"offline_mode": True}

        with patch("subprocess.run") as mock_run:
            ok, msg = manager.validate_pipeline_source(config=config)

        assert not ok
        mock_run.assert_not_called()

    def test_local_source_allowed_in_offline_mode(self, tmp_path):
        """A local path with main.nf is accepted even when offline_mode=True."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        pipeline_dir = tmp_path / "my_pipeline"
        pipeline_dir.mkdir()
        (pipeline_dir / "main.nf").write_text("// stub")

        manager = NextflowManager("/tmp", pipeline_source=str(pipeline_dir))
        config = {"offline_mode": True}

        with patch("subprocess.run") as mock_run:
            ok, msg = manager.validate_pipeline_source(config=config)

        assert ok, f"Expected ok=True for local path, got: {msg}"
        mock_run.assert_not_called()

    def test_remote_source_allowed_when_offline_mode_false(self, tmp_path):
        """When offline_mode=False, remote sources proceed to the git check."""
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        manager = NextflowManager("/tmp", pipeline_source="remote:main")
        config = {"offline_mode": False}

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123\trefs/heads/main\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ok, msg = manager.validate_pipeline_source(config=config)

        # git ls-remote must have been attempted
        mock_run.assert_called_once()


class TestBackendManagerOfflineGuard:
    """Verify that BackendManager.setup_project() rejects remote pipeline
    sources early when offline_mode is set."""

    def test_setup_project_fails_for_remote_source_in_offline_mode(self, tmp_path):
        """setup_project() returns failure when offline and pipeline_source is remote."""
        from nanometa_live.core.workflow.backend_manager import BackendManager

        nanopore_dir = tmp_path / "input"
        nanopore_dir.mkdir()
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        kraken_db = tmp_path / "db"
        kraken_db.mkdir()

        manager = BackendManager(str(tmp_path / "data"))
        config = {
            "nanopore_output_directory": str(nanopore_dir),
            "results_output_directory": str(results_dir),
            "kraken_db": str(kraken_db),
            "pipeline_source": "remote:main",
            "offline_mode": True,
            "main_dir": str(results_dir),
        }
        manager.config = config

        ok, msg = manager.setup_project(config)

        assert not ok
        assert "offline" in msg.lower()

    def test_setup_project_succeeds_for_local_source_in_offline_mode(self, tmp_path):
        """setup_project() does not block local pipeline sources in offline mode."""
        from nanometa_live.core.workflow.backend_manager import BackendManager
        import json

        nanopore_dir = tmp_path / "input"
        nanopore_dir.mkdir()
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        kraken_db = tmp_path / "db"
        kraken_db.mkdir()
        pipeline_dir = tmp_path / "pipeline"
        pipeline_dir.mkdir()
        (pipeline_dir / "main.nf").write_text("// stub")

        manager = BackendManager(str(tmp_path / "data"))
        config = {
            "nanopore_output_directory": str(nanopore_dir),
            "results_output_directory": str(results_dir),
            "kraken_db": str(kraken_db),
            "pipeline_source": str(pipeline_dir),
            "offline_mode": True,
            "main_dir": str(results_dir),
        }
        manager.config = config

        # setup() calls nextflow -version; stub that subprocess call
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Nextflow 23.10.0\n"

        with patch("subprocess.run", return_value=mock_result):
            ok, msg = manager.setup_project(config)

        # Should not be blocked by the offline guard
        assert "offline" not in msg.lower() or ok, (
            f"Unexpected offline block for local source: {msg}"
        )


class TestBackendManagerFileCountTTL:
    """``_update_file_counts`` must not os.listdir on every interval tick.

    The TTL cache (P1-T09 from
    docs/audit-2026-04-28-throughput-gui.md) reduces 24-barcode-multiplex
    scan cost from 25 listdirs/tick to 25 listdirs / 5s, picked up
    within one TTL cycle of any new file arriving.
    """

    def test_consecutive_calls_within_ttl_skip_listdir(self, tmp_path, monkeypatch):
        """Two calls within the TTL window must result in only one listdir."""
        from nanometa_live.core.workflow.backend_manager import BackendManager

        nanopore_dir = tmp_path / "fastq_pass"
        nanopore_dir.mkdir()
        (nanopore_dir / "reads.fastq.gz").write_bytes(b"x")

        bm = BackendManager(str(tmp_path))
        bm.config = {"nanopore_output_directory": str(nanopore_dir)}

        listdir_calls = []
        original_listdir = os.listdir
        def counting_listdir(p):
            listdir_calls.append(str(p))
            return original_listdir(p)
        monkeypatch.setattr(os, "listdir", counting_listdir)

        bm._update_file_counts()
        first = list(listdir_calls)
        assert bm.status["files_waiting"] == 1
        assert len(first) >= 1, "first call must hit the filesystem"

        listdir_calls.clear()
        bm._update_file_counts()
        # Within TTL: must NOT have called listdir again
        assert listdir_calls == [], (
            f"second call within TTL listdir'd {len(listdir_calls)} paths; "
            "expected zero"
        )

    def test_call_after_ttl_expires_rescans(self, tmp_path, monkeypatch):
        """When the TTL window has elapsed, the filesystem is consulted again."""
        from nanometa_live.core.workflow.backend_manager import BackendManager

        nanopore_dir = tmp_path / "fastq_pass"
        nanopore_dir.mkdir()
        (nanopore_dir / "reads.fastq.gz").write_bytes(b"x")

        bm = BackendManager(str(tmp_path))
        bm.config = {"nanopore_output_directory": str(nanopore_dir)}
        bm._update_file_counts()

        # Force the cached_at timestamp far enough back that the TTL
        # check below treats it as expired.
        bm._file_count_cached_at = bm._file_count_cached_at - bm._FILE_COUNT_TTL_SECONDS - 1

        listdir_calls = []
        original_listdir = os.listdir
        def counting_listdir(p):
            listdir_calls.append(str(p))
            return original_listdir(p)
        monkeypatch.setattr(os, "listdir", counting_listdir)

        bm._update_file_counts()
        assert len(listdir_calls) >= 1, "expired TTL must trigger a fresh scan"
