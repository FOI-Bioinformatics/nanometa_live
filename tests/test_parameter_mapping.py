"""Tests for parameter_mapping and pipeline-source configuration.

Regression tests for items F1 / F2 / F3 / F7 / F8 / F11 / F13 from the
2026-04-21 audit. See FINAL_AUDIT_REPORT.md for the full triage list.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.config.parameter_mapping import (
    _validate_single_input_source,
    create_nextflow_config,
    create_nextflow_params,
    validate_sample_handling_layout,
)
from nanometa_live.core.workflow.nextflow_manager import NextflowManager


@pytest.fixture
def base_config(tmp_path):
    """A minimal batch-mode config that create_nextflow_params will accept."""
    nanopore_dir = tmp_path / "input"
    nanopore_dir.mkdir()
    (nanopore_dir / "sample1.fastq.gz").write_bytes(b"@seq\nACGT\n+\n!!!!\n")

    results_dir = tmp_path / "results"
    results_dir.mkdir()

    return {
        "nanopore_output_directory": str(nanopore_dir),
        "results_output_directory": str(results_dir),
        "kraken_db": str(tmp_path / "kraken2_db"),
        "processing_mode": "batch",
        "sample_handling": "single_sample",
        "sample_name": "test_sample",
        "analysis_name": "TestRun",
        "check_intervals_seconds": 15,
        "blast_validation": False,
    }


# ---- F1 / P1-3: default pipeline_source -------------------------------------


class TestDefaultPipelineSource:
    def test_default_is_not_broken_master(self):
        """Fresh install should not default to the known-broken remote:master."""
        loader = ConfigLoader(config_dir=tempfile.mkdtemp())
        defaults = loader.create_default_config()
        assert defaults["pipeline_source"] != "remote:master", (
            "remote:master is the default that blocked every fresh install in "
            "the 2026-04-21 audit. Default must be remote:dev or a local path."
        )

    def test_default_is_resolvable_spec(self):
        loader = ConfigLoader(config_dir=tempfile.mkdtemp())
        defaults = loader.create_default_config()
        source = defaults["pipeline_source"]
        assert source.startswith(("remote:", "local:", "/")), (
            f"pipeline_source default {source!r} is not a recognized format"
        )


class TestValidatePipelineSource:
    def test_local_path_valid(self, tmp_path):
        (tmp_path / "main.nf").write_text("// stub")
        mgr = NextflowManager(
            data_dir=str(tmp_path / "data"),
            pipeline_source=f"local:{tmp_path}",
        )
        ok, msg = mgr.validate_pipeline_source()
        assert ok is True
        assert "Local pipeline" in msg

    def test_local_path_missing_main_nf(self, tmp_path):
        mgr = NextflowManager(
            data_dir=str(tmp_path / "data"),
            pipeline_source=f"local:{tmp_path}",
        )
        ok, msg = mgr.validate_pipeline_source()
        assert ok is False
        assert "main.nf" in msg

    def test_local_path_does_not_exist(self, tmp_path):
        mgr = NextflowManager(
            data_dir=str(tmp_path / "data"),
            pipeline_source=f"local:{tmp_path}/does-not-exist",
        )
        ok, msg = mgr.validate_pipeline_source()
        assert ok is False

    def test_remote_missing_branch_reports_fatal(self, tmp_path):
        mgr = NextflowManager(
            data_dir=str(tmp_path / "data"),
            pipeline_source="remote:definitely-not-a-branch-xyz",
        )
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=fake_result):
            ok, msg = mgr.validate_pipeline_source()
        assert ok is False
        assert "definitely-not-a-branch-xyz" in msg

    def test_remote_offline_is_soft_skip(self, tmp_path):
        mgr = NextflowManager(
            data_dir=str(tmp_path / "data"),
            pipeline_source="remote:dev",
        )
        fake_result = MagicMock(returncode=128, stdout="", stderr="fatal: unable to access")
        with patch("subprocess.run", return_value=fake_result):
            ok, msg = mgr.validate_pipeline_source()
        # Offline/network failure must not hard-fail -- we skip the check.
        assert ok is True
        assert "skipping pre-flight check" in msg


# ---- F7 / P1-7: sample_handling vs directory-layout validation -------------


class TestSampleHandlingLayoutValidation:
    def test_per_file_with_barcode_subdirs_raises(self, tmp_path):
        (tmp_path / "barcode01").mkdir()
        (tmp_path / "barcode01" / "a.fastq.gz").write_bytes(b"")
        (tmp_path / "barcode02").mkdir()
        (tmp_path / "barcode02" / "b.fastq.gz").write_bytes(b"")

        with pytest.raises(ValueError) as exc:
            validate_sample_handling_layout("per_file", str(tmp_path))
        assert "per_file" in str(exc.value)

    def test_per_file_with_flat_layout_passes(self, tmp_path):
        (tmp_path / "a.fastq.gz").write_bytes(b"")
        (tmp_path / "b.fastq.gz").write_bytes(b"")
        validate_sample_handling_layout("per_file", str(tmp_path))

    def test_by_barcode_with_barcode_subdirs_passes(self, tmp_path):
        (tmp_path / "barcode01").mkdir()
        (tmp_path / "barcode01" / "a.fastq.gz").write_bytes(b"")
        validate_sample_handling_layout("by_barcode", str(tmp_path))

    def test_missing_dir_does_not_raise(self, tmp_path):
        # Fail-soft when the directory is absent -- other code paths raise a
        # more actionable error for this case.
        validate_sample_handling_layout("per_file", str(tmp_path / "missing"))


# ---- F2 / P1-4: honor pre-supplied input samplesheet -----------------------


class TestInputSamplesheetHonored:
    def test_prebuilt_input_is_kept_verbatim(self, base_config, tmp_path):
        samplesheet = tmp_path / "my_samplesheet.csv"
        samplesheet.write_text("sample,fastq_1,fastq_2\nsample1,/tmp/s1.fq.gz,\n")

        base_config["input"] = str(samplesheet)
        params = create_nextflow_params(base_config)

        assert params["input"] == str(samplesheet)
        gen = Path(base_config["results_output_directory"]) / "samplesheets" / "input_samplesheet.csv"
        assert not gen.exists(), (
            "Auto-generated samplesheet must not overwrite the user-supplied input"
        )

    def test_missing_input_falls_back_to_autogen(self, base_config, tmp_path):
        base_config["input"] = str(tmp_path / "does-not-exist.csv")
        params = create_nextflow_params(base_config)

        gen = Path(base_config["results_output_directory"]) / "samplesheets" / "input_samplesheet.csv"
        assert params["input"] == str(gen)
        assert gen.exists()


# ---- F3 / P1-5: use_input_dir_mode -----------------------------------------


class TestInputDirMode:
    def test_input_dir_mode_skips_samplesheet(self, base_config):
        base_config["use_input_dir_mode"] = True
        params = create_nextflow_params(base_config)

        assert params.get("input_dir") == base_config["nanopore_output_directory"]
        assert "input" not in params or params.get("input") is None
        gen = Path(base_config["results_output_directory"]) / "samplesheets" / "input_samplesheet.csv"
        assert not gen.exists()

    def test_default_still_generates_samplesheet(self, base_config):
        params = create_nextflow_params(base_config)
        assert "input" in params
        assert "input_dir" not in params


# ---- F11 / P2-9: ARM auto-disables kraken2_memory_mapping ------------------


class TestArmMemoryMappingDefault:
    def test_arm_disables_memory_mapping(self, base_config):
        with patch("platform.machine", return_value="arm64"):
            params = create_nextflow_params(base_config)
        assert params["kraken2_memory_mapping"] is False

    def test_aarch64_disables_memory_mapping(self, base_config):
        with patch("platform.machine", return_value="aarch64"):
            params = create_nextflow_params(base_config)
        assert params["kraken2_memory_mapping"] is False

    def test_x86_keeps_memory_mapping_on(self, base_config):
        with patch("platform.machine", return_value="x86_64"):
            params = create_nextflow_params(base_config)
        assert params["kraken2_memory_mapping"] is True

    def test_explicit_override_wins_on_arm(self, base_config):
        base_config["kraken_memory_mapping"] = True
        with patch("platform.machine", return_value="arm64"):
            params = create_nextflow_params(base_config)
        # Explicit user override is respected.
        assert params["kraken2_memory_mapping"] is True


# ---- F8 / P2-1..P2-3: custom.config template cleanup -----------------------


class TestCustomConfigTemplate:
    def test_no_max_cpus_params_block(self, base_config):
        cfg = create_nextflow_config(base_config)
        # max_cpus / max_memory / max_time are not in nanometanf's schema.
        assert "max_cpus" not in cfg
        assert "max_memory =" not in cfg
        assert "max_time =" not in cfg

    def test_fastp_block_only_emitted_for_fastp(self, base_config):
        base_config["qc_tool"] = "chopper"
        cfg_chopper = create_nextflow_config(base_config)
        assert "'FASTP'" not in cfg_chopper

        base_config["qc_tool"] = "fastp"
        cfg_fastp = create_nextflow_config(base_config)
        assert "'FASTP'" in cfg_fastp

    def test_no_double_brace_interpolation_artifacts(self, base_config):
        cfg = create_nextflow_config(base_config)
        # Groovy uses single braces; double-brace sequences indicate a leftover
        # Python f-string interpolation artefact (P2-2).
        assert "{{" not in cfg
        assert "}}" not in cfg


# ---- _validate_single_input_source helper guard ----------------------------


class TestSingleInputGuard:
    """Direct unit tests for the dual-input guard helper.

    The helper enforces that exactly one of nanometanf's mutually exclusive
    input-source keys is populated. Zero or more than one is rejected.
    """

    INPUT_KEYS = (
        "input",
        "input_dir",
        "fastq_input_dir",
        "barcode_input_dir",
        "nanopore_output_dir",
    )

    def test_zero_input_keys_raises(self):
        with pytest.raises(ValueError) as exc:
            _validate_single_input_source({"outdir": "/tmp/out"})
        assert "no input mode" in str(exc.value)

    def test_zero_input_keys_with_only_falsy_values_raises(self):
        # Empty strings and None are not populated.
        params = {key: "" for key in self.INPUT_KEYS}
        params["nanopore_output_dir"] = None
        with pytest.raises(ValueError) as exc:
            _validate_single_input_source(params)
        assert "no input mode" in str(exc.value)

    @pytest.mark.parametrize("key", INPUT_KEYS)
    def test_exactly_one_input_key_passes(self, key):
        params = {key: "/some/path"}
        # Must return None silently and not raise.
        assert _validate_single_input_source(params) is None

    def test_two_input_keys_raises(self):
        params = {
            "input": "/tmp/sheet.csv",
            "nanopore_output_dir": "/tmp/sequencer",
        }
        with pytest.raises(ValueError) as exc:
            _validate_single_input_source(params)
        msg = str(exc.value)
        assert "multiple input modes" in msg
        assert "input" in msg
        assert "nanopore_output_dir" in msg

    def test_three_input_keys_raises(self):
        params = {
            "input": "/tmp/sheet.csv",
            "input_dir": "/tmp/in",
            "nanopore_output_dir": "/tmp/sequencer",
        }
        with pytest.raises(ValueError) as exc:
            _validate_single_input_source(params)
        assert "multiple input modes" in str(exc.value)

    def test_all_five_input_keys_raises(self):
        params = {key: "/some/path" for key in self.INPUT_KEYS}
        with pytest.raises(ValueError) as exc:
            _validate_single_input_source(params)
        assert "multiple input modes" in str(exc.value)
