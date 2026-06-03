"""
Unit tests for the pure-logic callbacks in app/callbacks.py.

app/callbacks.py is ~1900 lines and was only exercised indirectly. These tests
register the core callbacks on a throwaway Dash app, pull each registered
function out of ``callback_map`` (unwrapping Dash's add_context decorator), and
drive it directly with constructed Store inputs -- the same technique used by
test_verdict_banner_callback.py. Coverage targets the deterministic helpers and
the start/stop + status state machines, plus the results-fingerprint gate.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.callback
from dash import Dash
from dash.exceptions import PreventUpdate

from dash_test_utils import get_callback_fn as _callback_fn
from nanometa_live.app.callbacks import register_core_callbacks


@pytest.fixture
def core_app():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_core_callbacks(app, MagicMock())
    return app


# The header readiness TTL cache (_readiness_cache_key) was removed when the
# header pill and Preparation checklist were unified onto the readiness-state
# Store; its dedicated tests went with it (the staleness it papered over was
# the reported "indicators out of sync" bug).


class TestUpdateInterval:
    # Adaptive cadence: configured rate while a run is active, slower idle rate
    # otherwise. The callback takes (config, backend-status).
    _RUNNING = {"running": True}
    _IDLE = {"running": False}

    def test_uses_config_seconds_while_running(self, core_app):
        fn = _callback_fn(core_app, "update-interval.interval")
        assert fn({"update_interval_seconds": 10}, self._RUNNING) == 10000

    def test_backs_off_when_idle(self, core_app):
        fn = _callback_fn(core_app, "update-interval.interval")
        # idle uses idle_update_interval_seconds (or max(base, 60))
        assert fn({"update_interval_seconds": 10,
                   "idle_update_interval_seconds": 60}, self._IDLE) == 60000

    def test_idle_default_floor_when_unset(self, core_app):
        fn = _callback_fn(core_app, "update-interval.interval")
        assert fn({"update_interval_seconds": 10}, self._IDLE) == 60000

    def test_starting_counts_as_active(self, core_app):
        fn = _callback_fn(core_app, "update-interval.interval")
        assert fn({"update_interval_seconds": 5}, {"starting": True}) == 5000


class TestToggleOfflineBadge:
    # The callback now returns (badge_style, toggle_value) so the header
    # toggle stays in sync with the config; assert on the style element.
    def test_visible_when_offline(self, core_app):
        fn = _callback_fn(core_app, "offline-mode-badge.style")
        style, value = fn({"offline_mode": True})
        assert style == {"fontSize": "0.7rem"}
        assert value is True

    def test_hidden_otherwise(self, core_app):
        fn = _callback_fn(core_app, "offline-mode-badge.style")
        style, value = fn({})
        assert style["display"] == "none"
        assert value is False


class TestUpdateStatusDisplay:
    def test_standby_when_no_status(self, core_app):
        fn = _callback_fn(core_app, "status-indicator.color")
        color, text, _ = fn(None, {})
        assert (color, text) == ("gray", "STANDBY")

    def test_visualization_mode(self, core_app):
        fn = _callback_fn(core_app, "status-indicator.color")
        color, text, _ = fn({"running": False}, {"visualization_only": True})
        assert (color, text) == ("blue", "VIEWING")

    def test_running_batch_clamps_processed_to_total(self, core_app):
        fn = _callback_fn(core_app, "status-indicator.color")
        status = {"running": True, "files_processed": 99, "files_waiting": 10}
        color, text, details = fn(status, {"processing_mode": "batch"})
        assert (color, text) == ("green", "RUNNING")
        assert "10 / 10" in details  # clamped to the inbox total

    def test_running_realtime_does_not_clamp(self, core_app):
        fn = _callback_fn(core_app, "status-indicator.color")
        status = {"running": True, "files_processed": 99, "files_waiting": 10}
        _, _, details = fn(status, {"processing_mode": "realtime"})
        assert "99 / 10" in details  # realtime inbox is a moving snapshot

    def test_error_status(self, core_app):
        fn = _callback_fn(core_app, "status-indicator.color")
        color, text, _ = fn({"pipeline_status": "error", "errors": ["boom"]}, {})
        assert (color, text) == ("red", "ERROR")


class TestUpdateControlButton:
    def test_disabled_without_status_or_config(self, core_app):
        fn = _callback_fn(core_app, "start-stop-button.children")
        children, color, disabled = fn(None, None, None)
        assert disabled is True

    def test_visualization_mode_disables(self, core_app):
        fn = _callback_fn(core_app, "start-stop-button.children")
        _, color, disabled = fn({"running": False}, {"visualization_only": True}, None)
        assert (color, disabled) == ("secondary", True)

    def test_running_shows_stop(self, core_app):
        # config must be truthy/non-empty to pass the `not config` guard.
        fn = _callback_fn(core_app, "start-stop-button.children")
        _, color, disabled = fn({"running": True}, {"processing_mode": "batch"}, None)
        assert (color, disabled) == ("danger", False)

    def test_ready_enables_start(self, core_app):
        fn = _callback_fn(core_app, "start-stop-button.children")
        _, _, disabled = fn({"running": False}, {"processing_mode": "batch"}, {"ready": True})
        assert disabled is False

    def test_not_ready_disables_start(self, core_app):
        fn = _callback_fn(core_app, "start-stop-button.children")
        _, _, disabled = fn({"running": False}, {"processing_mode": "batch"}, {"ready": False})
        assert disabled is True


class TestUpdateStartTooltip:
    def test_modes(self, core_app):
        fn = _callback_fn(core_app, "start-analysis-tooltip.children")
        assert "visualization mode" in fn({"visualization_only": True}, None)
        assert "Stop" in fn({}, {"running": True})
        assert "Begin processing" in fn({}, {"running": False})


class TestUpdateHeaderTitle:
    def test_uses_analysis_name(self, core_app):
        fn = _callback_fn(core_app, "header-title.children")
        assert fn({"analysis_name": "Run 7"}) == "Run 7"

    def test_default_title(self, core_app):
        fn = _callback_fn(core_app, "header-title.children")
        assert fn({}) == "Nanometa Live Analysis"


class TestComputeResultsFingerprint:
    def test_no_config_prevents_update(self, core_app):
        fn = _callback_fn(core_app, "results-fingerprint.data")
        with pytest.raises(PreventUpdate):
            fn(1, None, None)

    def test_emits_fingerprint_for_populated_dir(self, core_app, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        (kraken / "barcode01.kraken2.report.txt").write_text(
            "100.00\t10\t10\tS\t562\tEscherichia coli\n"
        )
        config = {
            "results_output_directory": str(tmp_path),
            "main_dir": str(tmp_path),
        }
        fn = _callback_fn(core_app, "results-fingerprint.data")
        result = fn(1, config, None)
        assert "fp" in result and result["fp"]

    def test_unchanged_fingerprint_prevents_update(self, core_app, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        (kraken / "barcode01.kraken2.report.txt").write_text(
            "100.00\t10\t10\tS\t562\tEscherichia coli\n"
        )
        config = {"results_output_directory": str(tmp_path), "main_dir": str(tmp_path)}
        fn = _callback_fn(core_app, "results-fingerprint.data")
        first = fn(1, config, None)
        with pytest.raises(PreventUpdate):
            fn(2, config, first)
