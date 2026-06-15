"""Gap 2: Reports tab discovery + safe serving of pipeline report artifacts.

The Reports tab links the MultiQC + Nextflow execution reports the GUI never
surfaced. These tests pin the discovery (present vs absent), the serve-path
resolution (whitelisted keys only, traversal guard), and the link/embed builders.
"""

import os
from pathlib import Path

import pytest

from nanometa_live.core.utils.reports_loader import (
    detect_reports, resolve_report_path, set_reports_dir,
)
from nanometa_live.app.tabs.reports_helpers import (
    build_pipeline_reports_card, build_multiqc_embed,
)

pytestmark = pytest.mark.unit


def _results_with(tmp_path, *, multiqc=False, exec_report=False):
    if multiqc:
        (tmp_path / "multiqc").mkdir()
        (tmp_path / "multiqc" / "multiqc_report.html").write_text("<html>mqc</html>")
    if exec_report:
        (tmp_path / "pipeline_info").mkdir(exist_ok=True)
        (tmp_path / "pipeline_info" / "execution_report_2026-06-15.html").write_text("<html>e</html>")
    return str(tmp_path)


class TestDetect:
    def test_present_and_absent(self, tmp_path):
        d = _results_with(tmp_path, multiqc=True, exec_report=True)
        rep = {r["key"]: r for r in detect_reports(d)}
        assert rep["multiqc"]["exists"] is True
        assert rep["exec_report"]["exists"] is True
        assert rep["exec_timeline"]["exists"] is False
        assert rep["multiqc"]["url"] == "/reports/multiqc"

    def test_empty_dir(self, tmp_path):
        assert all(not r["exists"] for r in detect_reports(str(tmp_path)))

    def test_none_dir(self):
        assert all(not r["exists"] for r in detect_reports(None))


class TestResolve:
    def test_present_key_resolves(self, tmp_path):
        d = _results_with(tmp_path, multiqc=True)
        set_reports_dir(d)
        p = resolve_report_path("multiqc")
        assert p is not None and p.name == "multiqc_report.html"

    def test_absent_key_is_none(self, tmp_path):
        set_reports_dir(_results_with(tmp_path, multiqc=True))
        assert resolve_report_path("exec_timeline") is None

    def test_unknown_key_is_none(self, tmp_path):
        set_reports_dir(_results_with(tmp_path, multiqc=True))
        # An arbitrary/traversal-looking key is not in REPORT_SPECS -> rejected.
        assert resolve_report_path("../../etc/passwd") is None
        assert resolve_report_path("anything") is None

    def test_symlink_escaping_results_dir_is_rejected(self, tmp_path):
        # A symlink inside the results dir pointing outside must not be served.
        outside = tmp_path.parent / "secret.html"
        outside.write_text("secret")
        (tmp_path / "multiqc").mkdir()
        link = tmp_path / "multiqc" / "multiqc_report.html"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported here")
        set_reports_dir(str(tmp_path))
        assert resolve_report_path("multiqc") is None  # traversal guard

    def test_no_dir_set_is_none(self):
        set_reports_dir(None)
        assert resolve_report_path("multiqc") is None


class TestHelpers:
    def test_card_links_present_reports(self, tmp_path):
        d = _results_with(tmp_path, multiqc=True)
        card = build_pipeline_reports_card(detect_reports(d))
        text = str(card)
        assert "MultiQC Report" in text and "/reports/multiqc" in text
        assert "Open" in text and "Not produced" in text  # exec reports absent

    def test_card_all_absent_message(self, tmp_path):
        card = build_pipeline_reports_card(detect_reports(str(tmp_path)))
        assert "No pipeline reports found" in str(card)

    def test_multiqc_embed_present_and_absent(self, tmp_path):
        present = build_multiqc_embed(detect_reports(_results_with(tmp_path, multiqc=True)))
        assert "iframe" in str(present).lower() or "Iframe" in str(present)
        absent = build_multiqc_embed(detect_reports(str(tmp_path / "empty")))
        assert absent == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
