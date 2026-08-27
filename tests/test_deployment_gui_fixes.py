"""GUI fixes from the 2026-08-27 deployment audit.

Covers, at callback level:

- a docker/singularity export with no resolvable local pipeline checkout is
  BLOCKED with an actionable message (the pull was silently skipped before,
  shipping a green bundle with zero images);
- a docker export with the daemon down is blocked at click time;
- the pre-export readiness gate checks the runtime for the ENGINE the
  operator selected, not always conda;
- ``finalize_import`` pushes the imported config into the ``app-config``
  store and reloads the live watchlist manager, so the running app matches
  what was just installed (OFFLINE badge, readiness inputs, watchlists);
- the verify (dry-run) renderer;
- the wizard single-step callback is a background callback (it used to run
  a full bundle export on the request thread);
- a wizard step that ended in "warning" renders a visible badge, not an
  empty span.
"""
from __future__ import annotations

import re
from pathlib import Path
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


def _alert_text(component):
    from nanometa_live.app.tabs.preparation_helpers import _alert_text

    return _alert_text(component)


class TestContainerExportGuards:
    def _fn(self, app):
        return get_callback_fn(
            app, "export-result.children", input_contains="export-bundle-btn"
        )

    def test_docker_without_local_pipeline_blocks(self, app):
        checker = MagicMock()
        checker.check_readiness.return_value = _report()
        with patch(
            "nanometa_live.core.workflow.readiness_checker.ReadinessChecker",
            return_value=checker,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager."
            "_resolve_pipeline_checkout",
            return_value=None,
        ), patch.object(prep, "_export_preflight", return_value=None), \
             patch.object(prep, "_run_export", return_value="EXPORTED") as run:
            out = self._fn(app)(
                MagicMock(), 1, "/tmp/out", "b.tar.gz", False, "docker",
                "linux/amd64",
                {"kraken_db": "/db", "pipeline_source": "remote:dev"}, [],
            )
        assert not run.called, (
            "a container export with nothing to inventory must not proceed "
            "-- it ships a bundle with zero images"
        )
        text = _alert_text(out[0]) + _alert_text(out[2])
        assert "pipeline" in text.lower()

    def test_docker_daemon_down_blocks(self, app, tmp_path):
        (tmp_path / "main.nf").write_text("workflow {}\n")
        checker = MagicMock()
        checker.check_readiness.return_value = _report()
        with patch(
            "nanometa_live.core.workflow.readiness_checker.ReadinessChecker",
            return_value=checker,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager."
            "_resolve_pipeline_checkout",
            return_value=tmp_path,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager._docker_daemon_ok",
            return_value=False,
        ), patch.object(prep, "_export_preflight", return_value=None), \
             patch.object(prep, "_run_export", return_value="EXPORTED") as run:
            out = self._fn(app)(
                MagicMock(), 1, "/tmp/out", "b.tar.gz", False, "docker",
                "linux/amd64",
                {"kraken_db": "/db", "pipeline_source": str(tmp_path)}, [],
            )
        assert not run.called
        text = _alert_text(out[0]) + _alert_text(out[2])
        assert "docker" in text.lower()

    def test_readiness_gate_checks_selected_engine(self, app, tmp_path):
        (tmp_path / "main.nf").write_text("workflow {}\n")
        checker = MagicMock()
        checker.check_readiness.return_value = _report()
        with patch(
            "nanometa_live.core.workflow.readiness_checker.ReadinessChecker",
            return_value=checker,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager."
            "_resolve_pipeline_checkout",
            return_value=tmp_path,
        ), patch(
            "nanometa_live.core.workflow.bundle_manager._docker_daemon_ok",
            return_value=True,
        ), patch.object(prep, "_export_preflight", return_value=None), \
             patch.object(prep, "_run_export", return_value="EXPORTED"):
            self._fn(app)(
                MagicMock(), 1, "/tmp/out", "b.tar.gz", False, "docker",
                "linux/amd64",
                {"kraken_db": "/db", "pipeline_source": str(tmp_path),
                 "pipeline_profile": "conda"}, [],
            )
        checked_config = checker.check_readiness.call_args[0][0]
        assert checked_config.get("pipeline_profile") == "docker", (
            "the gate must check the runtime for the engine the operator "
            "selected, not whatever profile the config carries"
        )


class TestFinalizeImportRefreshesApp:
    def _fn(self, app):
        return get_callback_fn(
            app, "import-result.children",
            input_contains="import-bundle-result-store",
        )

    def test_success_pushes_imported_config_and_reloads_watchlists(self, app):
        imported_cfg = {"offline_mode": True, "kraken_db": "/field/db"}
        payload = {
            "_click": 1,
            "result": {"success": True, "imported_config": imported_cfg},
        }
        with patch("nanometa_live.app.app._init_offline_mode") as init_off, \
             patch.object(prep, "_reload_watchlists_from_config") as reload_wm:
            out = self._fn(app)(payload)
        init_off.assert_called_once_with(True)
        reload_wm.assert_called_once_with(imported_cfg)
        # Outputs: (import-result children, app-config data)
        assert out[1] == imported_cfg

    def test_failure_leaves_app_config_untouched(self, app):
        from dash import no_update

        payload = {"_click": 1, "result": {"success": False, "warnings": ["x"]}}
        with patch("nanometa_live.app.app._init_offline_mode") as init_off, \
             patch.object(prep, "_reload_watchlists_from_config") as reload_wm:
            out = self._fn(app)(payload)
        assert not init_off.called
        assert not reload_wm.called
        assert out[1] is no_update

    def test_success_without_imported_config_skips_store(self, app):
        from dash import no_update

        payload = {"_click": 1, "result": {"success": True}}
        with patch("nanometa_live.app.app._init_offline_mode"), \
             patch.object(prep, "_reload_watchlists_from_config"):
            out = self._fn(app)(payload)
        assert out[1] is no_update


class TestVerifyRenderer:
    def test_blockers_render_red(self):
        from nanometa_live.app.tabs.preparation_helpers import (
            _render_verify_result,
        )

        alert = _render_verify_result({
            "success": False,
            "blockers": [{"message": "checksum mismatch on 3 files"}],
            "warnings": [],
        })
        assert alert.color == "danger"
        assert "checksum mismatch" in _alert_text(alert)

    def test_warnings_render_amber(self):
        from nanometa_live.app.tabs.preparation_helpers import (
            _render_verify_result,
        )

        alert = _render_verify_result({
            "success": True,
            "blockers": [],
            "warnings": ["db hash differs"],
        })
        assert alert.color == "warning"
        assert "db hash differs" in _alert_text(alert)

    def test_clean_renders_green(self):
        from nanometa_live.app.tabs.preparation_helpers import (
            _render_verify_result,
        )

        alert = _render_verify_result(
            {"success": True, "blockers": [], "warnings": []}
        )
        assert alert.color == "success"


class TestWizardStepIsBackground:
    def test_run_wizard_step_declares_background_and_running(self):
        """Step 7 runs a full bundle export; on the request thread that
        freezes the UI for up to ~30 min with no cancel. The decorator must
        declare background=True plus running feedback."""
        src = Path(prep.__file__).read_text()
        # The decorator block immediately preceding `def run_wizard_step`.
        m = re.search(
            r"@app\.callback\((?P<deco>[^@]*?)\)\s*\n\s*def run_wizard_step\(",
            src,
            re.DOTALL,
        )
        assert m, "run_wizard_step callback not found"
        deco = m.group("deco")
        assert "background=True" in deco
        assert "running=" in deco
        assert "watchlist-entries-snapshot" in deco, (
            "worker singletons are empty; the step executor needs the "
            "snapshot for the watchlist-dependent steps"
        )


class TestWizardWarningBadge:
    def test_warning_state_renders_visible_badge(self, app):
        fn = get_callback_fn(
            app, "wizard-overall-progress.value",
            input_contains="wizard-step-state",
        )
        state = {"steps": {"0": "warning", "1": "pending"}}
        statuses, _pct, _label = fn(state)
        text = _alert_text(statuses[0])
        assert text.strip(), (
            "a step that ran-with-warnings must be visually distinct from "
            "one never run"
        )


class TestExportProgress:
    def test_export_callback_declares_progress(self):
        src = Path(prep.__file__).read_text()
        m = re.search(
            r"@app\.callback\((?P<deco>[^@]*?)\)\s*\n\s*def export_bundle\(",
            src, re.DOTALL,
        )
        assert m, "export_bundle callback not found"
        assert "progress=" in m.group("deco"), (
            "a ~30-min export with only a disabled button and a spinner "
            "gives the operator no stage feedback"
        )

    def test_run_export_forwards_progress_cb(self, tmp_path):
        from nanometa_live.app.tabs import preparation_helpers
        from nanometa_live.core.workflow.bundle_manager import ExportResult

        out = tmp_path / "b.tar.gz"
        out.write_bytes(b"x")
        cb = MagicMock()
        with patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager."
            "export_bundle",
            return_value=ExportResult(path=out, warnings=[], manifest={}),
        ) as exp:
            preparation_helpers._run_export(
                {"kraken_db": ""}, directory=str(tmp_path), progress_cb=cb
            )
        assert exp.call_args.kwargs.get("progress_cb") is cb

    def test_bundle_export_reports_stages(self, tmp_path):
        from nanometa_live.core.workflow.bundle_manager import BundleManager

        home = tmp_path / "home"
        (home / "genomes").mkdir(parents=True)
        (home / "genomes" / "1.fasta").write_text(">x\nA\n")
        messages = []
        BundleManager().export_bundle(
            str(tmp_path / "b.tar.gz"),
            config={"kraken_db": ""},
            nanometa_home=str(home),
            progress_cb=messages.append,
        )
        assert messages, "export must report at least one stage"


class TestTargetPlatformAndForceControls:
    def test_export_states_include_target_platform(self):
        src = Path(prep.__file__).read_text()
        m = re.search(
            r"@app\.callback\((?P<deco>[^@]*?)\)\s*\n\s*def export_bundle\(",
            src, re.DOTALL,
        )
        assert "bundle-target-platform" in m.group("deco")

    def test_import_states_include_force_check(self):
        src = Path(prep.__file__).read_text()
        m = re.search(
            r"@app\.callback\((?P<deco>[^@]*?)\)\s*\n\s*def import_bundle_worker\(",
            src, re.DOTALL,
        )
        assert "import-force-check" in m.group("deco")

    def test_run_export_passes_target_platform(self, tmp_path):
        from nanometa_live.app.tabs import preparation_helpers
        from nanometa_live.core.workflow.bundle_manager import ExportResult

        out = tmp_path / "b.tar.gz"
        out.write_bytes(b"x")
        with patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager."
            "export_bundle",
            return_value=ExportResult(path=out, warnings=[], manifest={}),
        ) as exp:
            preparation_helpers._run_export(
                {"kraken_db": ""}, directory=str(tmp_path),
                containerization="docker", target_platform="linux/arm64",
            )
        assert exp.call_args.kwargs.get("target_platform") == "linux/arm64"


class TestImportWorkerHome:
    def test_worker_resolves_home_from_config(self, app, tmp_path):
        bundle = tmp_path / "b.tar.gz"
        bundle.write_bytes(b"x" * 64)
        fn = get_callback_fn(
            app, "import-bundle-result-store.data",
            input_contains="import-bundle-btn",
        )
        manager = MagicMock()
        manager.import_bundle.return_value = {"success": True, "warnings": []}
        config = {"data_dir": str(tmp_path / "custom_home")}
        with patch(
            "nanometa_live.core.workflow.bundle_manager.BundleManager",
            return_value=manager,
        ):
            fn(MagicMock(), 1, str(bundle), str(tmp_path), False, config)
        kwargs = manager.import_bundle.call_args.kwargs
        assert kwargs.get("nanometa_home"), (
            "the worker must resolve the data home from the app config the "
            "way export does, not from the env default"
        )
        assert "custom_home" in kwargs["nanometa_home"]
