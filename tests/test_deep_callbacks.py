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
        assert text == "(2 done · 1 active)"
        assert style["display"] == "flex"


# --------------------------------------------------------------------------
# Stale-data warning + last-update tracking
# --------------------------------------------------------------------------

class TestStaleDataWarning:
    _RUNNING = {"running": True}

    def test_no_config_hidden(self, app_backend):
        fn = _fn(app_backend[0], "stale-data-warning.style")
        assert fn(1, None, self._RUNNING, None) == {"display": "none"}

    def test_recent_update_not_stale(self, app_backend):
        fn = _fn(app_backend[0], "stale-data-warning.style")
        now_iso = _dt.datetime.now().isoformat()
        assert fn(1, now_iso, self._RUNNING, {"update_interval_seconds": 10}) == {"display": "none"}

    def test_old_update_is_stale_while_running(self, app_backend):
        fn = _fn(app_backend[0], "stale-data-warning.style")
        old_iso = (_dt.datetime.now() - _dt.timedelta(hours=1)).isoformat()
        assert fn(1, old_iso, self._RUNNING, {"update_interval_seconds": 10}) == {"display": "flex"}

    def test_old_update_hidden_when_completed(self, app_backend):
        fn = _fn(app_backend[0], "stale-data-warning.style")
        old_iso = (_dt.datetime.now() - _dt.timedelta(hours=1)).isoformat()
        completed = {"running": True, "completed": True}
        assert fn(1, old_iso, completed, {"update_interval_seconds": 10}) == {"display": "none"}


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
    # display_toast now renders both the toast-message and notification-trigger
    # channels into one container: fn(toast_data, notification_data, current).
    def test_appends_toast_message(self, app_backend):
        fn = _fn(app_backend[0], "toast-container.children")
        with _ctx("toast-message"):
            result = fn({"type": "success", "title": "Done"}, None, [])
        assert len(result) == 1

    def test_renders_notification_trigger_channel(self, app_backend):
        # A notification-trigger payload (color, not type) must also render.
        fn = _fn(app_backend[0], "toast-container.children")
        with _ctx("notification-trigger"):
            result = fn(None, {"title": "Started", "message": "x", "color": "success"}, [])
        assert len(result) == 1

    def test_no_data_keeps_current(self, app_backend):
        fn = _fn(app_backend[0], "toast-container.children")
        with _ctx("toast-message"):
            assert fn(None, None, ["existing"]) == ["existing"]


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

    def test_preparation_to_deployment(self, app_backend):
        fn = _fn(app_backend[0], "tabs.active_tab", input_contains="merged-next-deployment")
        assert fn(1) == "deployment-tab"

    def test_proxy_prep_start_bumps_header(self, app_backend):
        fn = _fn(app_backend[0], "start-stop-button.n_clicks", input_contains="preparation-start-analysis-btn")
        assert fn(1, 5) == 6

    def test_proxy_no_click_prevents(self, app_backend):
        fn = _fn(app_backend[0], "start-stop-button.n_clicks", input_contains="preparation-start-analysis-btn")
        with pytest.raises(PreventUpdate):
            fn(0, 5)


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


# --------------------------------------------------------------------------
# Open Results (explicit results-folder loading) -- Part 2 of the session
# handling redesign. Viewing a folder is transient: it writes the in-memory
# app-config only and never persists a session.
# --------------------------------------------------------------------------

class TestOpenResults:
    def test_apply_open_results_sets_view_only(self, app_backend, tmp_path):
        app, _ = app_backend
        fn = _fn(app, "app-config.data", input_contains="confirm-directory-select")
        new_cfg, is_open, toast, sample = fn(1, str(tmp_path), "open-results", {"foo": "bar"})
        assert new_cfg["results_output_directory"] == str(tmp_path)
        assert new_cfg["main_dir"] == str(tmp_path)
        assert new_cfg["visualization_only"] is True
        assert new_cfg["foo"] == "bar"  # preserves existing config
        assert is_open is False
        assert sample == "All Samples"
        assert toast["type"] == "success"

    def test_apply_open_results_ignores_other_targets(self, app_backend, tmp_path):
        app, _ = app_backend
        fn = _fn(app, "app-config.data", input_contains="confirm-directory-select")
        with pytest.raises(PreventUpdate):
            fn(1, str(tmp_path), "nanopore-dir-input", {})

    def test_apply_open_results_missing_dir_errors(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "app-config.data", input_contains="confirm-directory-select")
        new_cfg, is_open, toast, sample = fn(1, "/no/such/dir", "open-results", {})
        assert new_cfg is no_update
        assert toast["type"] == "error"

    def test_current_results_display_empty_state(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "current-results-display.children")
        out = fn({})
        assert "no results loaded" in str(out)

    def test_current_results_display_shows_path(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "current-results-display.children")
        assert fn({"results_output_directory": "/data/run12"}) == "/data/run12"


# --------------------------------------------------------------------------
# Collision modal: foreign-data guard -- Part 4. A folder with result-shaped
# data but no .nanometa.run.json is "foreign" and must not be resumed over.
# --------------------------------------------------------------------------

class TestCollisionForeignData:
    def test_foreign_data_shows_red_banner_and_no_resume(self):
        from nanometa_live.app.components.collision_modal import render_collision_body
        body = str(render_collision_body("/x", ["kraken2"], input_match=None, has_metadata=False))
        assert "not created by Nanometa Live" in body
        assert "Continue (resume)" not in body

    def test_nanometa_mismatch_keeps_resume_bullet(self):
        from nanometa_live.app.components.collision_modal import render_collision_body
        body = str(render_collision_body("/x", ["kraken2"], input_match=False, has_metadata=True))
        assert "Input differs from the previous run" in body
        assert "Continue (resume)" in body

    def test_matching_run_has_resume_and_no_banner(self):
        from nanometa_live.app.components.collision_modal import render_collision_body
        body = str(render_collision_body("/x", ["kraken2"], input_match=True, has_metadata=True))
        assert "Continue (resume)" in body
        assert "not created by Nanometa Live" not in body
        assert "Input differs" not in body

    def test_resume_button_hidden_for_foreign(self, app_backend):
        app, _ = app_backend
        fn = _fn(app, "collision-resume-btn.style")
        assert fn({"has_metadata": False}) == {"display": "none"}
        assert fn({"has_metadata": True}) == {}
