"""Export outcome must reach the operator (2026-08-27 audit, GUI finding 2).

``export_bundle`` used to return a bare Path, so every warning it recorded
-- a skipped container pull, a failed pre-warm, an arch mismatch -- was
unreachable to the caller: the GUI rendered an unconditional green
"Bundle exported" and the CLI printed unconditional green success. A
bundle whose entire pre-warm failed shipped with a green light.

Contract pinned here:

- ``export_bundle`` returns an ``ExportResult`` with ``path``,
  ``warnings`` (mirroring the manifest's ``export_warnings``) and
  ``manifest``;
- the GUI's ``_run_export`` renders amber and lists the warnings when any
  exist, green only for a clean export.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.workflow.bundle_manager import (
    BundleManager,
    ExportResult,
)

pytestmark = pytest.mark.unit


class TestExportResult:
    def test_clean_export_returns_path_and_empty_warnings(self, tmp_path):
        home = tmp_path / "home"
        (home / "genomes").mkdir(parents=True)
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")
        out = tmp_path / "b.tar.gz"
        result = BundleManager().export_bundle(
            str(out), config={"kraken_db": ""}, nanometa_home=str(home)
        )
        assert isinstance(result, ExportResult)
        assert result.path == out
        assert result.warnings == []
        assert result.manifest["export_warnings"] == []

    def test_failed_prewarm_surfaces_in_warnings(self, tmp_path):
        home = tmp_path / "home"
        (home / "genomes").mkdir(parents=True)
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")
        pipeline = tmp_path / "pipeline"
        pipeline.mkdir()
        (pipeline / "main.nf").write_text("workflow {}\n")
        out = tmp_path / "b.tar.gz"
        mgr = BundleManager()
        with patch.object(
            mgr,
            "_run_pre_warm_scenario",
            side_effect=lambda **kw: (False, "solver exploded"),
        ):
            with patch(
                "nanometa_live.core.workflow.bundle_manager.shutil.which",
                return_value="/usr/bin/nextflow",
            ):
                result = mgr.export_bundle(
                    str(out),
                    config={"kraken_db": "", "pipeline_source": str(pipeline)},
                    nanometa_home=str(home),
                    pre_warm_conda_envs=True,
                    pipeline_path=str(pipeline),
                )
        assert any("pre-warm" in w for w in result.warnings)
        assert any("WITHOUT per-process conda envs" in w for w in result.warnings)


class TestRunExportRendering:
    def _alert_text(self, component):
        from nanometa_live.app.tabs.preparation_helpers import _alert_text

        return _alert_text(component)

    def test_export_with_warnings_renders_amber_and_lists_them(self, tmp_path):
        from nanometa_live.app.tabs import preparation_helpers

        out = tmp_path / "b.tar.gz"
        out.write_bytes(b"x" * 128)
        fake = ExportResult(
            path=out,
            warnings=["[conda pre-warm] Scenario 'realtime' failed: boom"],
            manifest={"export_warnings": ["..."]},
        )
        with patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager."
            "export_bundle",
            return_value=fake,
        ):
            alert = preparation_helpers._run_export(
                {"kraken_db": ""}, directory=str(tmp_path)
            )
        assert alert.color == "warning"
        text = self._alert_text(alert)
        assert "realtime" in text and "boom" in text

    def test_clean_export_renders_green(self, tmp_path):
        from nanometa_live.app.tabs import preparation_helpers

        out = tmp_path / "b.tar.gz"
        out.write_bytes(b"x" * 128)
        fake = ExportResult(path=out, warnings=[], manifest={})
        with patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager."
            "export_bundle",
            return_value=fake,
        ):
            alert = preparation_helpers._run_export(
                {"kraken_db": ""}, directory=str(tmp_path)
            )
        assert alert.color == "success"
