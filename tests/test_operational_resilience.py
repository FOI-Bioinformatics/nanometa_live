"""Operational resilience fixes (round 3, phase 5).

Small guards against operator-scale accidents during a live exercise:
a double-clicked Archive must not archive twice (result splitting), an
occupied port must produce an actionable message rather than a raw
traceback, and a laptop lid-close must not SIGTERM a healthy run when
the wall clock jumps on wake.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from dash import Dash
from dash.exceptions import PreventUpdate

pytestmark = pytest.mark.unit

from tests.dash_test_utils import get_callback_fn


def _collision_app(backend):
    from nanometa_live.app.callbacks.start_stop import register_start_stop
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_start_stop(app, backend)
    return app


class TestCollisionTransitionGuard:
    """handle_collision_choice was the one start path without the
    transition guard: a double-click on 'Move existing & start fresh'
    archived TWICE (two timestamped folders, results split) before the
    second start was refused."""

    def _backend(self):
        backend = MagicMock()
        backend.transition_in_progress.return_value = False
        backend.archive_existing_results.return_value = "/out/_archive_x"
        backend.start_async.return_value = (True, "started")
        return backend

    def _fire(self, app, backend, transition_in_progress):
        import nanometa_live.app.callbacks.start_stop as ss
        fn = get_callback_fn(app, "collision-modal.is_open",
                             input_contains="collision-archive-btn")
        backend.transition_in_progress.return_value = transition_in_progress
        with patch.object(ss.dash, "ctx") as ctx:
            ctx.triggered_id = "collision-archive-btn"
            return fn(1, 0, 0, {"outdir": "/out"}, {"analysis_name": "x"},
                      {})

    def test_archive_during_transition_is_refused(self):
        backend = self._backend()
        app = _collision_app(backend)
        self._fire(app, backend, transition_in_progress=True)
        backend.archive_existing_results.assert_not_called()

    def test_normal_archive_still_works(self):
        backend = self._backend()
        app = _collision_app(backend)
        self._fire(app, backend, transition_in_progress=False)
        backend.archive_existing_results.assert_called_once()


class TestPortInUseMessage:
    """A second GUI instance on the same port died with a raw OSError
    traceback. The launcher catches it and names the port, the cause,
    and the fix."""

    def test_run_app_reports_the_port(self):
        from nanometa_live.app.__main__ import _run_server
        app = MagicMock()
        import errno
        # errno.EADDRINUSE, not a literal: 48 on macOS but 98 on Linux, so a
        # hard-coded value escapes the handler on the CI runner.
        app.run.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
        with pytest.raises(SystemExit):
            with patch("builtins.print") as fake_print:
                _run_server(app, host="127.0.0.1", port=8050, debug=False)
        printed = " ".join(str(c) for c in fake_print.call_args_list)
        assert "8050" in printed
        assert "--port" in printed

    def test_other_oserrors_propagate(self):
        from nanometa_live.app.__main__ import _run_server
        app = MagicMock()
        app.run.side_effect = OSError(13, "Permission denied")
        with pytest.raises(OSError):
            _run_server(app, host="127.0.0.1", port=8050, debug=False)


class TestMonotonicInactivityTimeout:
    """The realtime inactivity timeout compared wall-clock timestamps, so
    a laptop asleep past the timeout had its healthy run SIGTERM'd the
    moment it woke. The elapsed measurement uses time.monotonic(), which
    freezes with the machine."""

    def test_wall_clock_jump_does_not_trip_the_timeout(self):
        from nanometa_live.core.workflow.backend_manager import BackendManager
        elapsed = BackendManager.inactivity_elapsed_s(
            last_progress_monotonic=1000.0, now_monotonic=1005.0)
        assert elapsed == pytest.approx(5.0)


class TestDiskSpaceGating:
    """Below a hard floor the disk check FAILS CRITICAL and gates Start
    (round 3): a WARNING-only check let a run launch onto a nearly full
    volume, and mid-run ENOSPC truncates reports -- the compound case
    the staleness registry then has to catch. An explicit env override
    (NANOMETA_ALLOW_LOW_DISK=1) downgrades to the old warning for
    operators who know their volume."""

    def _check(self, free_gb, monkeypatch, override=False):
        import shutil as shutil_mod
        from collections import namedtuple
        from nanometa_live.core.workflow.readiness_checker import (
            ReadinessChecker,
        )
        if override:
            monkeypatch.setenv("NANOMETA_ALLOW_LOW_DISK", "1")
        else:
            monkeypatch.delenv("NANOMETA_ALLOW_LOW_DISK", raising=False)
        Usage = namedtuple("usage", "total used free")
        monkeypatch.setattr(
            shutil_mod, "disk_usage",
            lambda p: Usage(100 * 1024**3, 0, int(free_gb * 1024**3)))
        checker = ReadinessChecker.__new__(ReadinessChecker)
        return checker._check_disk_space({"results_output_directory": "/"})

    def test_below_hard_floor_is_critical(self, monkeypatch):
        from nanometa_live.core.workflow.readiness_checker import Severity
        result = self._check(2.0, monkeypatch)
        assert not result.passed
        assert result.severity == Severity.CRITICAL

    def test_between_floors_is_warning(self, monkeypatch):
        from nanometa_live.core.workflow.readiness_checker import Severity
        result = self._check(7.0, monkeypatch)
        assert not result.passed
        assert result.severity == Severity.WARNING

    def test_ample_space_passes(self, monkeypatch):
        result = self._check(50.0, monkeypatch)
        assert result.passed

    def test_override_downgrades_to_warning(self, monkeypatch):
        from nanometa_live.core.workflow.readiness_checker import Severity
        result = self._check(2.0, monkeypatch, override=True)
        assert result.severity == Severity.WARNING


class TestRefreshReseed:
    """A browser refresh mid-run must not lose the dashboard.

    Only 3 of ~70 Stores persist; app-config reset to the boot default on
    refresh and nothing re-seeded it from the live backend, so the header
    said RUNNING while every tab said "no results" (round-3 audit). The
    reseed callback restores the applied config from the backend
    singleton within one tick. The once-guard is a memory Store: it
    resets on page load (re-arming the reseed) but persists across
    callbacks, so a deliberate Reset in the Configuration tab is never
    overridden.
    """

    def _app(self, backend):
        from nanometa_live.app.callbacks.startup import register_startup
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_startup(app, backend)
        return app

    def _backend(self, running=True, live_config=None):
        backend = MagicMock()
        backend.config = live_config
        backend.status = {"running": running,
                          "pipeline_status": "running" if running else "idle"}
        return backend

    def _fn(self, app):
        return get_callback_fn(app, "config-reseeded",
                               input_contains="update-interval")

    def test_refresh_during_run_restores_the_config(self):
        live = {"analysis_name": "run1",
                "results_dir_override": "/results/run1"}
        backend = self._backend(running=True, live_config=live)
        fn = self._fn(self._app(backend))
        config_out, reseeded = fn(1, {}, False)
        assert config_out == live
        assert reseeded is True

    def test_once_per_page_load(self):
        live = {"analysis_name": "run1",
                "results_dir_override": "/results/run1"}
        backend = self._backend(running=True, live_config=live)
        fn = self._fn(self._app(backend))
        with pytest.raises(PreventUpdate):
            fn(2, {}, True)

    def test_store_with_a_results_dir_is_left_alone(self):
        live = {"analysis_name": "run1",
                "results_dir_override": "/results/run1"}
        backend = self._backend(running=True, live_config=live)
        fn = self._fn(self._app(backend))
        with pytest.raises(PreventUpdate):
            fn(1, {"results_dir_override": "/results/other"}, False)

    def test_fresh_boot_without_backend_config_is_untouched(self):
        backend = self._backend(running=False, live_config=None)
        fn = self._fn(self._app(backend))
        with pytest.raises(PreventUpdate):
            fn(1, {}, False)

    def test_completed_run_also_reseeds(self):
        live = {"analysis_name": "run1",
                "results_dir_override": "/results/run1"}
        backend = self._backend(running=False, live_config=live)
        backend.status = {"running": False, "pipeline_status": "completed",
                          "completed": True}
        fn = self._fn(self._app(backend))
        config_out, reseeded = fn(1, {}, False)
        assert config_out == live


class TestExportWorkerWatchdog:
    """A dead DiskcacheManager worker froze the export at N% with the
    buttons disabled for the life of the session (round 3): running=
    never fires its off-state when the worker process dies. A
    main-process watchdog re-enables the modal and says so when a
    running export's progress has been frozen past the timeout."""

    def _decide(self, **kw):
        from nanometa_live.app.callbacks.worker_watchdog import (
            watchdog_decision,
        )
        defaults = dict(state=None, running=True, progress=40, now=1000.0,
                        timeout_s=300.0)
        defaults.update(kw)
        return watchdog_decision(**defaults)

    def test_idle_job_produces_no_state(self):
        state, fired = self._decide(running=False)
        assert state is None and not fired

    def test_running_job_starts_tracking(self):
        state, fired = self._decide(state=None)
        assert state == {"progress": 40, "since": 1000.0}
        assert not fired

    def test_advancing_progress_resets_the_clock(self):
        state, fired = self._decide(
            state={"progress": 40, "since": 500.0}, progress=55, now=900.0)
        assert state == {"progress": 55, "since": 900.0}
        assert not fired

    def test_frozen_progress_past_timeout_fires(self):
        state, fired = self._decide(
            state={"progress": 40, "since": 500.0}, progress=40, now=900.0)
        assert fired
        assert state is None, "fired watchdog clears its tracking state"

    def test_frozen_within_timeout_waits(self):
        state, fired = self._decide(
            state={"progress": 40, "since": 800.0}, progress=40, now=900.0)
        assert not fired
        assert state == {"progress": 40, "since": 800.0}
