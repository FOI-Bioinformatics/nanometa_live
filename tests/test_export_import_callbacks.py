"""Callback-level tests for the Deployment tab export/import (previously a gap).

The `export_bundle` background callback runs in a DiskcacheManager worker where
the WatchlistManager singleton is empty; its readiness gate MUST read the
`watchlist-entries-snapshot` State or it mis-evaluates the watchlist-active
check. These tests drive the unwrapped callbacks directly with mocked backends.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback

from dash import Dash

from dash_test_utils import get_callback_fn
import nanometa_live.app.tabs.preparation_tab as prep
from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks


@pytest.fixture
def app():
    a = Dash(__name__, suppress_callback_exceptions=True)
    register_preparation_callbacks(a)
    return a


def _report(critical=(), warnings=()):
    r = MagicMock()
    r.critical_failures = list(critical)
    r.warnings = list(warnings)
    return r


class TestExportBundleReadinessGate:
    """The readiness gate branches + the singleton-snapshot regression guard."""

    def _fn(self, app):
        return get_callback_fn(app, "export-result.children", input_contains="export-bundle-btn")

    def _drive(self, app, report, snapshot):
        checker = MagicMock()
        checker.check_readiness.return_value = report
        with patch("nanometa_live.core.workflow.readiness_checker.ReadinessChecker",
                   return_value=checker), \
             patch("nanometa_live.core.workflow.readiness_checker.Severity"), \
             patch.object(prep, "_export_preflight", return_value=None), \
             patch.object(prep, "_run_export", return_value="EXPORTED") as run:
            out = self._fn(app)(
                1, "/tmp/out", "bundle.tar.gz", False, "conda",
                {"kraken_db": "/db"}, snapshot,
            )
        return out, checker, run

    def test_snapshot_is_forwarded_to_readiness(self, app):
        # The regression guard: the worker-empty singleton means the snapshot
        # MUST reach check_readiness, or the watchlist check is wrong.
        snap = [{"name": "Francisella tularensis", "taxid": 263}]
        _out, checker, _run = self._drive(app, _report(), snap)
        _args, kwargs = checker.check_readiness.call_args
        assert kwargs.get("watchlist_entries") == snap

    def test_all_pass_runs_export(self, app):
        out, _checker, run = self._drive(app, _report(), [])
        # 4-tuple: (issues, force-style, result, force-check). Result is the export.
        assert run.called
        assert out[2] == "EXPORTED"
        assert out[1] == {"display": "none"}  # no force area

    def test_warnings_reveal_force_area(self, app):
        w = MagicMock(name="Watchlist", message="no species enabled")
        out, _checker, run = self._drive(app, _report(warnings=[w]), [])
        assert not run.called           # not exported yet
        assert out[1] == {"display": "block"}  # force area revealed

    def test_critical_blocks_export(self, app):
        c = MagicMock(name="Kraken DB", message="missing")
        out, _checker, run = self._drive(app, _report(critical=[c]), [])
        assert not run.called
        assert out[1] == {"display": "none"}  # force area stays hidden on critical


class TestImportBundleRendering:
    def _fn(self, app):
        return get_callback_fn(app, "import-result.children", input_contains="import-bundle-btn")

    def _drive(self, app, result, tmp_path):
        bundle = tmp_path / "b.tar.gz"
        bundle.write_bytes(b"x" * 100)
        mgr = MagicMock()
        mgr.import_bundle.return_value = result
        with patch("nanometa_live.core.workflow.bundle_manager.BundleManager", return_value=mgr), \
             patch("nanometa_live.app.app._init_offline_mode"):
            return self._fn(app)(1, str(bundle), "/db")

    def test_success_with_action_required(self, app, tmp_path):
        out = self._drive(app, {
            "success": True, "warnings": [], "kraken_db_unset": True, "plugins_empty": True,
        }, tmp_path)
        s = str(out)
        assert "Offline mode activated" in s
        assert "Action required" in s and "Kraken2 database path" in s and "plugins" in s

    def test_success_clean(self, app, tmp_path):
        out = self._drive(app, {"success": True, "warnings": []}, tmp_path)
        assert "Offline mode activated" in str(out)
        assert "Action required" not in str(out)

    def test_failure_surfaces_detail(self, app, tmp_path):
        out = self._drive(app, {
            "success": False, "warnings": ["platform mismatch", "checksum failed"],
        }, tmp_path)
        s = str(out)
        assert "Import failed" in s and "platform mismatch" in s and "checksum failed" in s

    def test_missing_paths_warn(self, app, tmp_path):
        assert "bundle path" in str(self._fn(app)(1, "", "/db"))
        b = tmp_path / "b.tar.gz"; b.write_bytes(b"x")
        assert "Kraken2 database path" in str(self._fn(app)(1, str(b), ""))
