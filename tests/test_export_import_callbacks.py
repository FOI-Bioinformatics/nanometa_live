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
from dash.exceptions import PreventUpdate

from dash_test_utils import get_callback_fn
import nanometa_live.app.tabs.preparation_tab as prep
from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks
from nanometa_live.app.tabs.preparation_helpers import _render_import_result


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


class TestRenderImportResult:
    """Pure renderer for the import outcome (shared by the finalize callback).
    Offline activation is NOT its job -- that lives in finalize_import.
    """

    def test_success_with_action_required(self):
        out = _render_import_result({
            "success": True, "warnings": [],
            "kraken_db_unset": True, "plugins_empty": True,
        })
        s = str(out)
        assert "Offline mode activated" in s
        assert "Action required" in s and "Kraken2 database path" in s and "plugins" in s

    def test_success_clean(self):
        out = _render_import_result({"success": True, "warnings": []})
        assert "Offline mode activated" in str(out)
        assert "Action required" not in str(out)

    def test_db_hash_mismatch_renders_regenerate_button(self):
        out = _render_import_result({
            "success": True, "warnings": [], "db_hash_mismatch": True,
        })
        s = str(out)
        assert "Action required" in s and "mapping" in s.lower()
        assert "regenerate-mappings-btn" in s

    def test_clean_import_has_no_regenerate_button(self):
        out = _render_import_result({"success": True, "warnings": []})
        assert "regenerate-mappings-btn" not in str(out)

    def test_failure_surfaces_detail(self):
        out = _render_import_result({
            "success": False, "warnings": ["platform mismatch", "checksum failed"],
        })
        s = str(out)
        assert "Import failed" in s and "platform mismatch" in s and "checksum failed" in s

    def test_early_error_uses_its_color(self):
        out = _render_import_result({
            "success": False, "early_error": "Bundle not found: /x", "color": "danger",
        })
        assert out.color == "danger"
        assert "not found" in str(out.children)

    def test_exception_surfaces_as_failure(self):
        out = _render_import_result({"success": False, "exception": "boom"})
        assert out.color == "danger"
        assert "Import failed" in str(out.children) and "boom" in str(out.children)


class TestImportBundleWorker:
    """Background worker: validates, imports, and writes a wrapped result to
    the Store. It must NOT activate offline mode (wrong process).
    """

    def _fn(self, app):
        return get_callback_fn(
            app, "import-bundle-result-store.data",
            input_contains="import-bundle-btn",
        )

    def _drive(self, app, result, tmp_path):
        bundle = tmp_path / "b.tar.gz"
        bundle.write_bytes(b"x" * 100)
        mgr = MagicMock()
        mgr.import_bundle.return_value = result
        set_progress = MagicMock()
        with patch("nanometa_live.core.workflow.bundle_manager.BundleManager",
                   return_value=mgr), \
             patch("nanometa_live.app.app._init_offline_mode") as init:
            out = self._fn(app)(set_progress, 1, str(bundle), "/db")
        return out, init, set_progress

    def test_success_wraps_manager_result_without_offline_init(self, app, tmp_path):
        payload, init, set_progress = self._drive(
            app, {"success": True, "warnings": []}, tmp_path
        )
        assert payload["result"] == {"success": True, "warnings": []}
        assert payload["_click"] == 1          # wrapped for finalize re-fire
        assert not init.called                 # worker must not touch singletons
        assert set_progress.called             # spinner shown while working

    def test_missing_paths_return_early_error(self, app, tmp_path):
        set_progress = MagicMock()
        out = self._fn(app)(set_progress, 1, "", "/db")
        assert "bundle path" in out["result"]["early_error"]
        b = tmp_path / "b.tar.gz"; b.write_bytes(b"x")
        out = self._fn(app)(set_progress, 1, str(b), "")
        assert "Kraken2 database path" in out["result"]["early_error"]

    def test_bundle_not_found_early_error(self, app):
        out = self._fn(app)(MagicMock(), 1, "/does/not/exist.tar.gz", "/db")
        assert "not found" in out["result"]["early_error"]
        assert out["result"]["color"] == "danger"

    def test_no_clicks_prevents_update(self, app):
        with pytest.raises(PreventUpdate):
            self._fn(app)(MagicMock(), None, "/b", "/db")


class TestFinalizeImport:
    """Main-process finalizer: activates offline mode on success, renders."""

    def _fn(self, app):
        return get_callback_fn(
            app, "import-result.children",
            input_contains="import-bundle-result-store",
        )

    def test_success_activates_offline_and_renders(self, app):
        with patch("nanometa_live.app.app._init_offline_mode") as init:
            out = self._fn(app)({"_click": 1, "result": {"success": True, "warnings": []}})
        init.assert_called_once_with(True)
        assert "Offline mode activated" in str(out)

    def test_failure_does_not_activate_offline(self, app):
        with patch("nanometa_live.app.app._init_offline_mode") as init:
            out = self._fn(app)({"_click": 1, "result": {
                "success": False, "warnings": ["checksum failed"]}})
        assert not init.called
        assert "Import failed" in str(out) and "checksum failed" in str(out)

    def test_empty_store_prevents_update(self, app):
        with pytest.raises(PreventUpdate):
            self._fn(app)(None)


class TestRegenerateMappingsCallback:
    def _fn(self, app):
        return get_callback_fn(
            app, "regenerate-mappings-result.children",
            input_contains="regenerate-mappings-btn",
        )

    def test_prefers_import_db_and_forwards_snapshot(self, app):
        snap = [{"name": "Francisella tularensis", "taxid": 263}]
        set_progress = MagicMock()
        with patch.object(prep, "_regenerate_mappings", return_value="REGEN") as rg:
            out = self._fn(app)(
                set_progress, 1, {"kraken_db": "/bundle/db"}, "/local/db", snap
            )
        assert out == "REGEN"
        # The import-form DB path wins over the (stale) app-config value.
        args, kwargs = rg.call_args
        assert args[0]["kraken_db"] == "/local/db"
        assert kwargs.get("watchlist_entries") == snap
        # A running spinner was pushed before the work.
        assert set_progress.called

    def test_no_clicks_prevents_update(self, app):
        with pytest.raises(PreventUpdate):
            self._fn(app)(MagicMock(), None, {}, None, None)
