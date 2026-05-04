"""Tests for readiness_checker module."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.workflow.readiness_checker import (
    CheckResult,
    ReadinessChecker,
    ReadinessReport,
    Severity,
)


@pytest.fixture
def checker():
    return ReadinessChecker()


# -- Tool check tests --


class TestToolCheck:
    def test_tool_found(self, checker):
        with patch("shutil.which", return_value="/usr/bin/nextflow"):
            result = checker._check_tool("nextflow", Severity.CRITICAL)
        assert result.passed is True
        assert "Found" in result.message

    def test_tool_not_found(self, checker):
        with patch("shutil.which", return_value=None):
            result = checker._check_tool("nextflow", Severity.CRITICAL)
        assert result.passed is False
        assert "not found" in result.message

    def test_tool_with_purpose(self, checker):
        with patch("shutil.which", return_value=None):
            result = checker._check_tool(
                "datasets", Severity.WARNING, purpose="downloading genomes"
            )
        assert "downloading genomes" in result.message

    def test_tool_severity_preserved(self, checker):
        with patch("shutil.which", return_value=None):
            result = checker._check_tool("blastn", Severity.WARNING)
        assert result.severity == Severity.WARNING


# -- Kraken2 DB validation --


class TestKrakenDbCheck:
    def test_valid_kraken_db(self, checker, tmp_path):
        db_dir = tmp_path / "kraken2_db"
        db_dir.mkdir()
        for f in ["hash.k2d", "opts.k2d", "taxo.k2d"]:
            (db_dir / f).write_text("data")

        config = {"kraken_db": str(db_dir)}
        result = checker._check_kraken_db(config)
        assert result.passed is True

    def test_invalid_kraken_db_missing_files(self, checker, tmp_path):
        db_dir = tmp_path / "kraken2_db"
        db_dir.mkdir()
        (db_dir / "hash.k2d").write_text("data")
        # Missing opts.k2d and taxo.k2d

        config = {"kraken_db": str(db_dir)}
        result = checker._check_kraken_db(config)
        assert result.passed is False
        assert "opts.k2d" in result.message
        assert "taxo.k2d" in result.message

    def test_no_kraken_db_configured(self, checker):
        config = {}
        result = checker._check_kraken_db(config)
        assert result.passed is False
        assert result.severity == Severity.CRITICAL

    def test_empty_kraken_db_path(self, checker):
        config = {"kraken_db": ""}
        result = checker._check_kraken_db(config)
        assert result.passed is False


# -- Network connectivity check --


class TestNetworkConnectivity:
    def test_network_reachable(self, checker):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock()
            results = checker._check_network_connectivity()

        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_network_unreachable(self, checker):
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            results = checker._check_network_connectivity()

        assert len(results) == 2
        assert all(not r.passed for r in results)
        assert all("unreachable" in r.message for r in results)

    def test_partial_connectivity(self, checker):
        def side_effect(url, **kwargs):
            if "ncbi" in url:
                return MagicMock()
            raise Exception("connection refused")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            results = checker._check_network_connectivity()

        ncbi = [r for r in results if "NCBI" in r.name][0]
        gtdb = [r for r in results if "GTDB" in r.name][0]
        assert ncbi.passed is True
        assert gtdb.passed is False

    def test_offline_mode_skips_probe(self, checker):
        """In offline mode the probe must NOT issue urlopen calls."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            results = checker._check_network_connectivity({"offline_mode": True})

        assert mock_urlopen.call_count == 0, (
            "Network probe must not run in offline mode"
        )
        assert len(results) == 1
        assert results[0].passed is True
        assert "skipped" in results[0].message.lower()


# -- Container runtime check --


class TestContainerRuntime:
    def test_docker_found_and_running(self, checker):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=mock_result):
            result = checker._check_container_runtime({"pipeline_profile": "docker"})
        assert result.passed is True

    def test_docker_not_found(self, checker):
        with patch("shutil.which", return_value=None):
            result = checker._check_container_runtime({"pipeline_profile": "docker"})
        assert result.passed is False
        assert "docker" in result.message

    def test_singularity_profile(self, checker):
        with patch("shutil.which", return_value="/usr/bin/singularity"):
            result = checker._check_container_runtime(
                {"pipeline_profile": "singularity"}
            )
        assert result.passed is True

    def test_standard_profile_no_container_needed(self, checker):
        result = checker._check_container_runtime({"pipeline_profile": "standard"})
        assert result.passed is True
        assert "no container" in result.message.lower()

    def test_conda_profile(self, checker):
        with patch("shutil.which", return_value="/usr/bin/conda"):
            result = checker._check_container_runtime({"pipeline_profile": "conda"})
        assert result.passed is True


# -- Input/output directory checks --


class TestInputDirectory:
    def test_input_dir_with_fastq(self, checker, tmp_path):
        (tmp_path / "reads.fastq.gz").write_text("data")
        config = {"nanopore_output_directory": str(tmp_path)}
        result = checker._check_input_directory(config)
        assert result.passed is True
        assert "FASTQ" in result.message

    def test_input_dir_with_barcodes(self, checker, tmp_path):
        (tmp_path / "barcode01").mkdir()
        (tmp_path / "barcode02").mkdir()
        config = {"nanopore_output_directory": str(tmp_path)}
        result = checker._check_input_directory(config)
        assert result.passed is True
        assert "barcode" in result.message

    def test_no_input_configured(self, checker):
        result = checker._check_input_directory({})
        assert result.passed is False

    def test_input_dir_not_exists(self, checker, tmp_path):
        config = {"nanopore_output_directory": str(tmp_path / "nonexistent")}
        result = checker._check_input_directory(config)
        assert result.passed is False


# -- Disk space check --


class TestDiskSpace:
    def test_sufficient_disk_space(self, checker, tmp_path):
        config = {"results_output_directory": str(tmp_path)}
        # Real disk check on tmp_path - should usually have > 10 GB
        result = checker._check_disk_space(config)
        # Just check it returns a valid result
        assert isinstance(result, CheckResult)

    def test_no_output_configured(self, checker):
        result = checker._check_disk_space({})
        assert result.passed is False


# -- ReadinessReport tests --


class TestReadinessReport:
    def test_ready_when_all_critical_pass(self):
        report = ReadinessReport(checks=[
            CheckResult("A", True, Severity.CRITICAL, "ok"),
            CheckResult("B", True, Severity.CRITICAL, "ok"),
            CheckResult("C", False, Severity.WARNING, "warn"),
        ])
        assert report.ready is True

    def test_not_ready_when_critical_fails(self):
        report = ReadinessReport(checks=[
            CheckResult("A", True, Severity.CRITICAL, "ok"),
            CheckResult("B", False, Severity.CRITICAL, "failed"),
        ])
        assert report.ready is False

    def test_summary(self):
        report = ReadinessReport(checks=[
            CheckResult("A", True, Severity.CRITICAL, "ok"),
            CheckResult("B", False, Severity.CRITICAL, "fail"),
            CheckResult("C", False, Severity.WARNING, "warn"),
        ])
        s = report.summary()
        assert s["total"] == 3
        assert s["passed"] == 1
        assert s["failed"] == 2
        assert s["critical_failures"] == 1
        assert s["warnings"] == 1

    def test_empty_report_is_ready(self):
        report = ReadinessReport()
        assert report.ready is True
        assert report.summary()["total"] == 0
