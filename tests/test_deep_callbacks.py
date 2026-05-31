"""
Tests for the deep stateful UI callbacks in app/callbacks.py.

These are the header/live-indicator/session/navigation callbacks that were only
hit indirectly. Each is registered on a throwaway Dash app and pulled out of
callback_map (disambiguated by input id where several callbacks share an
output), then driven directly. ctx.triggered_id and backend_manager are mocked;
nothing launches a pipeline or opens a file manager.
"""

import datetime as _dt
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback
from dash import Dash, no_update
from dash.exceptions import PreventUpdate

import nanometa_live.app.callbacks as cb
from nanometa_live.app.callbacks import register_core_callbacks


@pytest.fixture
def app_backend():
    app = Dash(__name__, suppress_callback_exceptions=True)
    backend = MagicMock()
    register_core_callbacks(app, backend)
    return app, backend


from dash_test_utils import get_callback_fn as _fn, ctx_with as _ctx


# --------------------------------------------------------------------------
# Sample selector / freshness / selected sample
# --------------------------------------------------------------------------

class TestSampleSelector:
    def test_options_built_and_reset_on_invalid_value(self, app_backend):
        fn = _fn(app_backend[0], "sample-selector.options")
        options, value = fn(["All Samples", "barcode01"], {}, "gone")
        assert len(options) == 2
        assert value == "All Samples"  # current selection no longer valid

    def test_valid_value_not_reset(self, app_backend):
        fn = _fn(app_backend[0], "sample-selector.options")
        _options, value = fn(["All Samples", "barcode01"], {}, "barcode01")
        assert value is no_update

    def test_selected_sample_defaults_to_all(self, app_backend):
        fn = _fn(app_backend[0], "selected-sample.data")
        assert fn("") == "All Samples"
        assert fn("barcode02") == "barcode02"


# --------------------------------------------------------------------------
# Live indicator
# --------------------------------------------------------------------------

class TestLiveIndicator:
    def test_visualization_only(self, app_backend):
        fn = _fn(app_backend[0], "live-indicator-dot.className")
        dot, text, label = fn(None, None, {"visualization_only": True})
        assert text == "View Only"
        assert label == "no data yet"

    def test_running_with_data_timestamp(self, app_backend):
        fn = _fn(app_backend[0], "live-indicator-dot.className")
        dot, text, label = fn({"running": True}, {"ts": 1_700_000_000.0}, {})
        assert text == "LIVE"
        assert label.startswith("Updated:")

    def test_completed(self, app_backend):
        fn = _fn(app_backend[0], "live-indicator-dot.className")
        _dot, text, _label = fn({"completed": True}, None, {})
        assert text == "Complete"

    def test_standby(self, app_backend):
        fn = _fn(app_backend[0], "live-indicator-dot.className")
        _dot, text, _label = fn({"running": False}, None, {})
        assert text == "Standby"


# --------------------------------------------------------------------------
# Pipeline stage display
# --------------------------------------------------------------------------

class TestPipelineStageDisplay:
    def test_hidden_when_not_running(self, app_backend):
        fn = _fn(app_backend[0], "current-pipeline-stage.children")
        stage, text, style = fn({"running": False})
        assert style == {"display": "none"}

    def test_progress_text_with_active_processes(self, app_backend):
        fn = _fn(app_backend[0], "current-pipeline-stage.children")
        status = {
            "running": True, "current_stage": "Alignment",
            "processes_complete": 2, "processes_running": 1, "processes_failed": 0,
        }
        _stage, text, style = fn(status)
        assert text == "(2/3, 1 active)"
        assert style["display"] == "flex"


# --------------------------------------------------------------------------
# Stale-data warning + last-update tracking
# --------------------------------------------------------------------------

class TestStaleDataWarning:
    def test_no_config_hidden(self, app_backend):
        fn = _fn(app_backend[0], "stale-data-warning.style")
        assert fn(1, None, None) == {"display": "none"}

    def test_recent_update_not_stale(self, app_backend):
        fn = _fn(app_backend[0], "stale-data-warning.style")
        now_iso = _dt.datetime.now().isoformat()
        assert fn(1, now_iso, {"update_interval_seconds": 10}) == {"display": "none"}

    def test_old_update_is_stale(self, app_backend):
        fn = _fn(app_backend[0], "stale-data-warning.style")
        old_iso = (_dt.datetime.now() - _dt.timedelta(hours=1)).isoformat()
        assert fn(1, old_iso, {"update_interval_seconds": 10}) == {"display": "flex"}


class TestTrackLastUpdateTime:
    def test_no_config_returns_none(self, app_backend):
        fn = _fn(app_backend[0], "last-update-time.data")
        assert fn({"fp": "x"}, None) is None

    def test_existing_dir_stamps_iso(self, app_backend, tmp_path):
        fn = _fn(app_backend[0], "last-update-time.data")
        result = fn({"fp": "x"}, {"results_output_directory": str(tmp_path)})
        assert result is not None
        _dt.datetime.fromisoformat(result)  # parses cleanly

    def test_missing_dir_returns_none(self, app_backend, tmp_path):
        fn = _fn(app_backend[0], "last-update-time.data")
        assert fn({"fp": "x"}, {"main_dir": str(tmp_path / "nope")}) is None


# --------------------------------------------------------------------------
# Toast + tab navigation
# --------------------------------------------------------------------------

class TestDisplayToast:
    def test_appends_toast(self, app_backend):
        fn = _fn(app_backend[0], "toast-container.children")
        result = fn({"type": "success", "title": "Done"}, [])
        assert len(result) == 1

    def test_no_data_keeps_current(self, app_backend):
        fn = _fn(app_backend[0], "toast-container.children")
        assert fn(None, ["existing"]) == ["existing"]


class TestSwitchToResultsTab:
    def test_navigate_to_field_navigates(self, app_backend):
        # Navigation now keys on the explicit navigate_to field set by the
        # start callbacks, not the (locale-sensitive) title string.
        fn = _fn(app_backend[0], "tabs.active_tab", input_contains="notification-trigger")
        assert fn({"navigate_to": "dashboard-tab"}, "config-tab") == "dashboard-tab"

    def test_title_match_alone_does_not_navigate(self, app_backend):
        # The old fragile contract: a toast that merely shares the title must
        # no longer hijack navigation.
        fn = _fn(app_backend[0], "tabs.active_tab", input_contains="notification-trigger")
        assert fn({"title": "Analysis Started", "color": "success"}, "config-tab") is no_update

    def test_other_notification_noop(self, app_backend):
        fn = _fn(app_backend[0], "tabs.active_tab", input_contains="notification-trigger")
        assert fn({"title": "Something else"}, "config-tab") is no_update


class TestAutoNavigateOnCompletion:
    def test_completion_navigates_to_dashboard(self, app_backend):
        fn = _fn(app_backend[0], "previous-running-state.data")
        tab, prev, toast = fn({"running": False}, True, "config-tab", {"analysis_name": "Run"})
        assert tab == "dashboard-tab"
        assert prev is False
        assert toast["title"] == "Analysis Complete"

    def test_still_running_just_tracks_state(self, app_backend):
        fn = _fn(app_backend[0], "previous-running-state.data")
        tab, prev, toast = fn({"running": True}, False, "dashboard-tab", {})
        assert tab is no_update
        assert prev is True


# --------------------------------------------------------------------------
# Stop confirmation + collision choice (ctx + backend)
# --------------------------------------------------------------------------

class TestHandleStopConfirmation:
    def test_modal_closed_is_noop(self, app_backend):
        fn = _fn(app_backend[0], "stop-confirm-modal.is_open", input_contains="confirm-stop-analysis")
        assert fn(1, 0, False) == (no_update, no_update)

    def test_confirm_stops_backend(self, app_backend):
        app, backend = app_backend
        backend.stop.return_value = (True, "stopped")
        fn = _fn(app, "stop-confirm-modal.is_open", input_contains="confirm-stop-analysis")
        with _ctx("confirm-stop-analysis"):
            is_open, notif = fn(1, 0, True)
        assert is_open is False
        assert notif["title"] == "Analysis Stopped"
        backend.stop.assert_called_once()

    def test_cancel_closes_without_stop(self, app_backend):
        app, backend = app_backend
        fn = _fn(app, "stop-confirm-modal.is_open", input_contains="confirm-stop-analysis")
        with _ctx("cancel-stop-analysis"):
            is_open, notif = fn(0, 1, True)
        assert is_open is False
        assert notif is no_update
        backend.stop.assert_not_called()


class TestHandleCollisionChoice:
    def test_cancel_closes_with_info(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "collision-modal.is_open", input_contains="collision-archive-btn")
        with _ctx("collision-cancel-btn"):
            modal, notif, cfg, status = fn(0, 0, 1, {"outdir": "/o"}, {"x": 1}, {})
        assert modal is False
        assert notif["color"] == "info"

    def test_archive_starts_fresh_run(self, app_backend):
        app, backend = app_backend
        backend.archive_existing_results.return_value = "/o/_archive_1"
        backend.start.return_value = (True, "started")
        fn = _fn(app, "collision-modal.is_open", input_contains="collision-archive-btn")
        with _ctx("collision-archive-btn"):
            modal, notif, cfg, status = fn(1, 0, 0, {"outdir": "/o"}, {"x": 1}, {})
        backend.start.assert_called_once_with(resume=False)
        assert notif["title"] == "Analysis Started"
        assert status["running"] is True

    def test_resume_uses_resume_flag(self, app_backend):
        app, backend = app_backend
        backend.start.return_value = (True, "resumed")
        fn = _fn(app, "collision-modal.is_open", input_contains="collision-archive-btn")
        with _ctx("collision-resume-btn"):
            fn(0, 1, 0, {"outdir": "/o"}, {"x": 1}, {})
        backend.start.assert_called_once_with(resume=True)


# --------------------------------------------------------------------------
# Welcome modal + step navigation
# --------------------------------------------------------------------------

class TestWelcomeModal:
    def test_close_goes_to_config(self, app_backend):
        fn = _fn(app_backend[0], "welcome-modal.is_open")
        with _ctx("close-welcome-modal"):
            assert fn(False, 1) == (False, "config-tab")

    def test_first_visit_opens(self, app_backend):
        fn = _fn(app_backend[0], "welcome-modal.is_open")
        with _ctx("welcome-shown"):
            is_open, tab = fn(False, 0)
        assert is_open is True

    def test_mark_shown(self, app_backend):
        fn = _fn(app_backend[0], "welcome-shown.data")
        assert fn(1) is True


class TestStepNavigation:
    def test_config_to_watchlist_bumps_apply(self, app_backend):
        fn = _fn(app_backend[0], "apply-config-button.n_clicks")
        tab, n_apply = fn(1, 3)
        assert tab == "watchlist-tab"
        assert n_apply == 4

    def test_watchlist_to_preparation(self, app_backend):
        fn = _fn(app_backend[0], "tabs.active_tab", input_contains="watchlist-next-preparation")
        assert fn(1) == "preparation-tab"

    def test_proxy_prep_start_bumps_header(self, app_backend):
        fn = _fn(app_backend[0], "start-stop-button.n_clicks", input_contains="preparation-start-analysis-btn")
        assert fn(1, 5) == 6

    def test_proxy_no_click_prevents(self, app_backend):
        fn = _fn(app_backend[0], "start-stop-button.n_clicks", input_contains="preparation-start-analysis-btn")
        with pytest.raises(PreventUpdate):
            fn(0, 5)


# --------------------------------------------------------------------------
# Resume / load / discard session
# --------------------------------------------------------------------------

class TestResumeSessionBanner:
    def test_no_deferred_closed(self, app_backend):
        fn = _fn(app_backend[0], "resume-session-banner-body.children")
        body, is_open = fn(None)
        assert is_open is False

    def test_deferred_opens_banner(self, app_backend):
        fn = _fn(app_backend[0], "resume-session-banner-body.children")
        body, is_open = fn({"path": "/cfg/last.yaml", "mtime_iso": "2026-05-30T10:00"})
        assert is_open is True
        assert body is not no_update


class TestLoadDeferredSession:
    def test_no_clicks_prevents(self, app_backend):
        fn = _fn(app_backend[0], "deferred-last-session.data", input_contains="resume-session-load-btn")
        with pytest.raises(PreventUpdate):
            fn(0, {"path": "/x"}, "/data")

    def test_no_deferred_prevents(self, app_backend):
        fn = _fn(app_backend[0], "deferred-last-session.data", input_contains="resume-session-load-btn")
        with pytest.raises(PreventUpdate):
            fn(1, None, "/data")


class TestDiscardDeferredSession:
    def test_removes_file_and_clears(self, app_backend, tmp_path):
        session = tmp_path / "last-session.yaml"
        session.write_text("x")
        fn = _fn(app_backend[0], "deferred-last-session.data", input_contains="resume-session-discard-btn")
        deferred, toast = fn(1, {"path": str(session)})
        assert deferred is None
        assert not session.exists()
        assert toast["title"] == "Previous session discarded"

    def test_missing_file_still_succeeds(self, app_backend, tmp_path):
        fn = _fn(app_backend[0], "deferred-last-session.data", input_contains="resume-session-discard-btn")
        deferred, toast = fn(1, {"path": str(tmp_path / "gone.yaml")})
        assert deferred is None

    def test_no_clicks_prevents(self, app_backend):
        fn = _fn(app_backend[0], "deferred-last-session.data", input_contains="resume-session-discard-btn")
        with pytest.raises(PreventUpdate):
            fn(0, {"path": "/x"})


# --------------------------------------------------------------------------
# Storage locations
# --------------------------------------------------------------------------

class TestStorageLocations:
    def test_no_data_dir(self, app_backend):
        fn = _fn(app_backend[0], "storage-locations-table.children")
        result = fn(None, {})
        # returns an html.Div placeholder, not the [header, table] list
        assert not isinstance(result, list)

    def test_renders_header_and_table(self, app_backend, tmp_path):
        fn = _fn(app_backend[0], "storage-locations-table.children")
        result = fn(str(tmp_path), {})
        assert isinstance(result, list)
        assert len(result) == 2  # [header alert, table]

    def test_open_storage_location_success(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "toast-message.data", input_contains="storage-open-btn")
        with _ctx({"type": "storage-open-btn", "path": "/some/dir"}), \
             patch("nanometa_live.app.utils.file_manager_open.open_in_file_manager", return_value=None):
            toast = fn([1])
        assert toast["title"] == "Opened in file manager"

    def test_open_storage_location_error(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "toast-message.data", input_contains="storage-open-btn")
        with _ctx({"type": "storage-open-btn", "path": "/some/dir"}), \
             patch("nanometa_live.app.utils.file_manager_open.open_in_file_manager", return_value="boom"):
            toast = fn([1])
        assert toast["title"] == "Could not open location"

    def test_open_storage_no_click_prevents(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "toast-message.data", input_contains="storage-open-btn")
        with _ctx({"type": "storage-open-btn", "path": "/some/dir"}):
            with pytest.raises(PreventUpdate):
                fn([0])
