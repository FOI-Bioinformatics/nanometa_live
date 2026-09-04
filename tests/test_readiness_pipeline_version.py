"""The readiness checklist names a nanometanf below the parameter floor.

Without this the checklist is green and the run fails at Start with an
nf-schema message naming a parameter (SWOT 2026-09-04, weakness 2).
"""

import pytest

from nanometa_live.core.workflow.readiness_checker import ReadinessChecker, Severity

pytestmark = pytest.mark.unit


def _checkout(tmp_path, version):
    (tmp_path / "main.nf").write_text("workflow { }\n")
    (tmp_path / "nextflow.config").write_text(
        f"manifest {{\n    name = 'nanometanf'\n    version = '{version}'\n}}\n"
    )
    return str(tmp_path)


def _find(report, name):
    matches = [c for c in report.checks if c.name == name]
    assert len(matches) == 1, [c.name for c in report.checks]
    return matches[0]


class TestPipelineVersionCheck:
    def test_below_floor_is_critical(self, tmp_path):
        result = ReadinessChecker()._check_pipeline_version(
            {"pipeline_source": _checkout(tmp_path, "1.4.1dev")}
        )
        assert result.name == "Pipeline Version"
        assert result.passed is False
        assert result.severity == Severity.CRITICAL
        assert "1.4.1dev" in result.message and "1.10.0" in result.message

    def test_at_floor_is_info_pass(self, tmp_path):
        result = ReadinessChecker()._check_pipeline_version(
            {"pipeline_source": _checkout(tmp_path, "1.10.0")}
        )
        assert result.passed is True
        assert result.severity == Severity.INFO

    def test_unreadable_is_warning(self, tmp_path):
        result = ReadinessChecker()._check_pipeline_version(
            {"pipeline_source": str(tmp_path)}
        )
        assert result.passed is False
        assert result.severity == Severity.WARNING

    # offline_mode: True keeps _check_network_connectivity from probing the
    # NCBI and GTDB endpoints during a unit test (the pattern in
    # tests/test_readiness_offline_checks.py::TestChecksAreWired).
    def test_report_carries_the_check_when_a_source_is_set(self, tmp_path):
        config = {
            "pipeline_source": _checkout(tmp_path, "1.10.0"),
            "kraken_db": "",
            "offline_mode": True,
            "pipeline_profile": "conda",
        }
        report = ReadinessChecker().check_readiness(config, nanometa_home=str(tmp_path))
        assert _find(report, "Pipeline Version").passed is True

    def test_report_omits_the_check_without_a_source(self, tmp_path):
        config = {
            "pipeline_source": "",
            "kraken_db": "",
            "offline_mode": True,
            "pipeline_profile": "conda",
        }
        report = ReadinessChecker().check_readiness(config, nanometa_home=str(tmp_path))
        assert not [c for c in report.checks if c.name == "Pipeline Version"]
