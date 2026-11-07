"""The server-side readiness gate on Start (field audit 2026-10-28, H5).

The checklist looked like a gate and was not one: the header button's
disabled attribute was the only barrier, the Preparation tab's Start button
proxied past it, and the Start callback never read the readiness Store.
"""

from unittest.mock import MagicMock

import pytest
from dash import Dash, no_update

from dash_test_utils import get_callback_fn
from nanometa_live.app.callbacks import register_core_callbacks
from nanometa_live.app.utils.start_gate import (
    NOT_CHECKED_MESSAGE,
    START_WITHOUT_READINESS_ENV,
    readiness_blocks_start,
    refusal_message,
)

pytestmark = pytest.mark.unit


def _state(*checks):
    return {"ready": all(c[1] for c in checks if c[2] == "critical"),
            "checks": [{"name": n, "passed": p, "severity": s, "message": m}
                       for n, p, s, m in checks]}


class TestReadinessBlocksStart:
    def test_critical_failures_are_named(self):
        state = _state(
            ("Kraken2 Database", False, "critical", "No Kraken2 database path configured"),
            ("Tool: nextflow", False, "critical", "nextflow not found in PATH"),
            ("Disk Space", False, "warning", "9 GB free"),
            ("Container Runtime", True, "critical", "conda available"),
        )
        reasons = readiness_blocks_start(state, {})
        assert reasons == [
            "Kraken2 Database: No Kraken2 database path configured",
            "Tool: nextflow: nextflow not found in PATH",
        ]

    def test_warnings_alone_do_not_block(self):
        state = _state(("Disk Space", False, "warning", "9 GB free"),
                       ("Kraken2 Database", True, "critical", "ok"))
        assert readiness_blocks_start(state, {}) == []

    def test_never_computed_blocks(self):
        assert readiness_blocks_start(None, {}) == [NOT_CHECKED_MESSAGE]
        assert readiness_blocks_start({"ready": False, "checks": []}, {}) == [NOT_CHECKED_MESSAGE]

    def test_errored_computation_blocks_with_its_error(self):
        state = {"ready": False, "checks": [], "error": "boom"}
        assert readiness_blocks_start(state, {}) == ["Readiness check failed: boom"]

    def test_config_override(self):
        state = _state(("Kraken2 Database", False, "critical", "missing"))
        assert readiness_blocks_start(state, {"start_without_readiness": True}) == []

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(START_WITHOUT_READINESS_ENV, "1")
        state = _state(("Kraken2 Database", False, "critical", "missing"))
        assert readiness_blocks_start(state, {}) == []

    def test_refusal_message_names_rows_and_override(self):
        msg = refusal_message(["Kraken2 Database: missing"])
        assert "- Kraken2 Database: missing" in msg
        assert "start_without_readiness" in msg


@pytest.fixture
def start_stop():
    app = Dash(__name__, suppress_callback_exceptions=True)
    backend = MagicMock()
    register_core_callbacks(app, backend)
    return get_callback_fn(app, "collision-decision-pending.data"), backend


class TestStartCallbackGate:
    NOT_READY = _state(("Kraken2 Database", False, "critical", "No Kraken2 database path configured"))

    def test_critical_failure_refuses_and_names_it(self, start_stop):
        fn, backend = start_stop
        result = fn(1, {"results_dir_override": "/out"}, {"running": False}, self.NOT_READY)
        notif = result[0]
        assert notif["color"] == "danger"
        assert notif["title"] == "Not ready to start"
        assert "Kraken2 Database: No Kraken2 database path configured" in notif["message"]
        assert notif["navigate_to"] == "watchlist-tab"
        backend.start_async.assert_not_called()
        backend.detect_existing_results.assert_not_called()
        # Nothing else moves: no optimistic status, no config push.
        assert all(r is no_update for r in result[1:])

    def test_unchecked_readiness_refuses(self, start_stop):
        fn, backend = start_stop
        result = fn(1, {"results_dir_override": "/out"}, {"running": False}, None)
        assert result[0]["color"] == "danger"
        backend.start_async.assert_not_called()

    def test_override_in_config_launches(self, start_stop):
        fn, backend = start_stop
        backend.detect_existing_results.return_value = []
        backend.transition_in_progress.return_value = False
        backend.start_async.return_value = (True, "Starting")
        cfg = {"results_dir_override": "/out", "start_without_readiness": True}
        result = fn(1, cfg, {"running": False}, self.NOT_READY)
        backend.start_async.assert_called_once()
        assert result[0]["title"] == "Starting Analysis"

    def test_stop_prompt_is_not_gated(self, start_stop):
        # A running pipeline must always be stoppable, whatever readiness says.
        fn, _ = start_stop
        result = fn(1, {"results_dir_override": "/out"}, {"running": True}, self.NOT_READY)
        assert result[2] is True
