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
from nanometa_live.core.workflow.nextflow_manager import NextflowManager


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
