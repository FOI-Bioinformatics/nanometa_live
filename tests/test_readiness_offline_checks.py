"""Readiness checks for offline deployments (2026-08-27 audit, findings 7/9).

- The Nextflow floor is 26.04.0 (nanometanf's manifest and the bundle's
  ``min_versions``), not the 23.0 the checklist used to accept -- a field
  machine on 24.x got a green check and failed at Start Analysis.
- Offline mode gains two checks the checklist never made: the Nextflow
  plugins dir (an empty one sends Nextflow to the online registry) and the
  pre-warmed conda cache for the conda profile (an unwired or empty cache
  means a network solve on an air-gapped machine).
"""

from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.workflow.readiness_checker import (
    ReadinessChecker,
    Severity,
)

pytestmark = pytest.mark.unit


def _version_proc(text):
    proc = MagicMock()
    proc.stdout = text
    proc.stderr = ""
    proc.returncode = 0
    return proc


class TestNextflowFloor:
    def _check(self, version_line):
        with patch(
            "nanometa_live.core.workflow.readiness_checker.subprocess.run",
            return_value=_version_proc(version_line),
        ):
            return ReadinessChecker()._check_nextflow_version()

    def test_24x_fails_the_floor(self):
        result = self._check("nextflow version 24.10.0.5889")
        assert result.passed is False
        assert "26.04" in result.message

    def test_26_04_passes(self):
        result = self._check("nextflow version 26.04.6.6018")
        assert result.passed is True

    def test_27_passes(self):
        result = self._check("nextflow version 27.1.0")
        assert result.passed is True


class TestOfflinePluginsCheck:
    def test_missing_plugins_dir_offline_is_critical(self, tmp_path):
        config = {
            "offline_mode": True,
            "nxf_plugins_dir": str(tmp_path / "nope"),
        }
        result = ReadinessChecker()._check_nextflow_plugins(config)
        assert result.passed is False
        assert result.severity == Severity.CRITICAL

    def test_empty_plugins_dir_offline_is_critical(self, tmp_path):
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        config = {"offline_mode": True, "nxf_plugins_dir": str(plugins)}
        result = ReadinessChecker()._check_nextflow_plugins(config)
        assert result.passed is False

    def test_populated_plugins_dir_passes(self, tmp_path):
        plugins = tmp_path / "plugins"
        (plugins / "nf-schema-2.4.2").mkdir(parents=True)
        config = {"offline_mode": True, "nxf_plugins_dir": str(plugins)}
        result = ReadinessChecker()._check_nextflow_plugins(config)
        assert result.passed is True

    def test_online_mode_is_informational(self):
        result = ReadinessChecker()._check_nextflow_plugins(
            {"offline_mode": False}
        )
        assert result.passed is True


class TestOfflineCondaCacheCheck:
    def _complete_env(self, cache, name="env-abc"):
        env = cache / name
        (env / "conda-meta").mkdir(parents=True)
        (env / "conda-meta" / "history").write_text("done\n")
        (env / "bin").mkdir()
        (env / "bin" / "tool").write_text("#!/bin/sh\n")

    def test_missing_cache_offline_conda_is_critical(self, tmp_path):
        config = {
            "offline_mode": True,
            "pipeline_profile": "conda",
            "nxf_conda_cachedir": str(tmp_path / "nope"),
        }
        result = ReadinessChecker()._check_offline_conda_cache(config)
        assert result.passed is False
        assert result.severity == Severity.CRITICAL

    def test_cache_with_complete_env_passes(self, tmp_path):
        cache = tmp_path / "conda_cache"
        cache.mkdir()
        self._complete_env(cache)
        config = {
            "offline_mode": True,
            "pipeline_profile": "conda",
            "nxf_conda_cachedir": str(cache),
        }
        result = ReadinessChecker()._check_offline_conda_cache(config)
        assert result.passed is True

    def test_unconfigured_cache_offline_conda_warns(self):
        config = {"offline_mode": True, "pipeline_profile": "conda"}
        result = ReadinessChecker()._check_offline_conda_cache(config)
        assert result.passed is False
        assert result.severity in (Severity.WARNING, Severity.CRITICAL)

    def test_docker_profile_not_flagged(self, tmp_path):
        config = {"offline_mode": True, "pipeline_profile": "docker"}
        result = ReadinessChecker()._check_offline_conda_cache(config)
        assert result.passed is True


class TestChecksAreWired:
    def test_offline_checks_appear_in_report(self, tmp_path):
        """The two offline checks must reach the report, not just exist."""
        config = {
            "offline_mode": True,
            "pipeline_profile": "conda",
            "kraken_db": "",
        }
        report = ReadinessChecker().check_readiness(config)
        names = [c.name for c in report.checks]
        assert any("plugin" in n.lower() for n in names)
        assert any("conda cache" in n.lower() for n in names)
