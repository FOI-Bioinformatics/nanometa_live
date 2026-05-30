"""
Tests for ReadinessReport and the check orchestration in
core/workflow/readiness_checker.py (was 40% covered).

test_readiness_checker.py covers several individual _check_* methods; this adds
the ReadinessReport aggregation model, _check_output_directory, and a fully
offline check_readiness run (network probe skipped via offline_mode; shutil.which
and subprocess.run mocked) that exercises the whole orchestration deterministically.
"""

from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.workflow import readiness_checker as rc
from nanometa_live.core.workflow.readiness_checker import (
    CheckResult,
    ReadinessChecker,
    ReadinessReport,
    Severity,
)

pytestmark = pytest.mark.unit


def _result(name, passed, severity):
    return CheckResult(name, passed, severity, f"{name} message")


class TestReadinessReport:
    def test_ready_when_all_critical_pass(self):
        report = ReadinessReport(checks=[
            _result("a", True, Severity.CRITICAL),
            _result("b", False, Severity.WARNING),  # warning failure does not block
        ])
        assert report.ready is True

    def test_not_ready_when_critical_fails(self):
        report = ReadinessReport(checks=[_result("a", False, Severity.CRITICAL)])
        assert report.ready is False

    def test_critical_failures_and_warnings_lists(self):
        report = ReadinessReport(checks=[
            _result("crit", False, Severity.CRITICAL),
            _result("warn", False, Severity.WARNING),
            _result("ok", True, Severity.CRITICAL),
        ])
        assert [c.name for c in report.critical_failures] == ["crit"]
        assert [c.name for c in report.warnings] == ["warn"]

    def test_summary_counts(self):
        report = ReadinessReport(checks=[
            _result("a", True, Severity.CRITICAL),
            _result("b", False, Severity.CRITICAL),
            _result("c", False, Severity.WARNING),
        ])
        s = report.summary()
        assert s == {
            "ready": False, "total": 3, "passed": 1, "failed": 2,
            "critical_failures": 1, "warnings": 1,
        }


class TestCheckOutputDirectory:
    def test_no_dir_configured(self):
        r = ReadinessChecker()._check_output_directory({})
        assert r.passed is False

    def test_existing_writable_dir(self, tmp_path):
        r = ReadinessChecker()._check_output_directory(
            {"results_output_directory": str(tmp_path)}
        )
        assert r.passed is True
        assert "exists" in r.message

    def test_creatable_when_parent_exists(self, tmp_path):
        r = ReadinessChecker()._check_output_directory(
            {"results_output_directory": str(tmp_path / "new_out")}
        )
        assert r.passed is True
        assert "will be created" in r.message

    def test_not_creatable_when_parent_missing(self, tmp_path):
        r = ReadinessChecker()._check_output_directory(
            {"results_output_directory": str(tmp_path / "a" / "b" / "c")}
        )
        assert r.passed is False


class TestCheckReadinessOrchestration:
    def test_offline_run_produces_full_report(self, tmp_path):
        config = {
            "offline_mode": True,          # skip network probe (no real calls)
            "blast_validation": False,
            "results_output_directory": str(tmp_path),
        }
        with patch.object(rc.shutil, "which", return_value=None), \
             patch.object(rc.subprocess, "run", side_effect=FileNotFoundError("absent")):
            report = ReadinessChecker().check_readiness(config, nanometa_home=str(tmp_path))

        assert report.checks, "orchestration produced no checks"
        summary = report.summary()
        assert set(summary) == {
            "ready", "total", "passed", "failed", "critical_failures", "warnings"
        }
        assert isinstance(report.ready, bool)
        # The output directory check should pass (tmp_path is writable).
        out_check = next(c for c in report.checks if c.name == "Output Directory")
        assert out_check.passed is True
