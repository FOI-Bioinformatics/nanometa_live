"""The verdict banner must flip ACTIVE -> COMPLETE promptly, not on a timer.

Measured on the 2026-08-19 realtime banner audit: the pipeline exited at
14:18:59, the header status chip showed "Complete" at 14:19:17 (one status
poll), but the verdict banner's run-state chip stayed "ACTIVE" until
14:21:23 -- 2m06s after exit, rescued only by the render-memo TTL. The
banner's redundancy gate keys on the results fingerprint alone, and the
session-end files land BEFORE the status flip, so the fingerprint is already
quiet when ``running`` turns False: nothing re-renders the banner even
though its run-state text is now wrong. A green ACTIVE chip on a finished
run misstates the run for minutes.

The gate now also bypasses when the run-state (ACTIVE/COMPLETE/STANDBY)
differs from what the banner last rendered, so a status flip re-renders on
the next interval tick regardless of the fingerprint.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback

from dash import Dash

from nanometa_live.app.utils.debounce import mark_rendered, reset_debounce
from tests.dash_test_utils import get_callback_fn


FP = {"fp": "quiet", "ts": 1.0}


@contextmanager
def _ctx(triggered_id):
    import nanometa_live.app.tabs.dashboard_tab as dt

    with patch.object(dt, "ctx", MagicMock(triggered_id=triggered_id,
                                           triggered=[{"value": 1}])):
        yield


@pytest.fixture()
def banner_fn():
    import nanometa_live.app.tabs.dashboard_tab as dt

    reset_debounce()
    dt._VERDICT_LAST_RUN_STATE.clear()
    app = Dash(__name__)
    dt.register_dashboard_callbacks(app)
    return get_callback_fn(app, "dashboard-verdict-banner",
                           input_contains="results-fingerprint")


def _call(fn, status):
    return fn(FP, None, 7, {"analysis_name": "x"}, status, None, None, None)


class TestCompletionFlip:
    def test_completion_rerenders_on_a_quiet_fingerprint(self, banner_fn):
        # Render once while running: the banner memoizes ACTIVE and the
        # fingerprint memo records FP.
        with _ctx("update-interval"):
            out = _call(banner_fn, {"running": True, "start_time": None})
        assert out[3] == "ACTIVE"

        # The run finishes; the fingerprint has NOT changed (session-end
        # files landed before the status poll flipped). The next interval
        # tick must re-render and show COMPLETE, not PreventUpdate.
        with _ctx("update-interval"):
            out = _call(banner_fn, {"running": False, "completed": True})
        assert out[3] == "COMPLETE", (
            "the banner told the operator the run was ACTIVE for over two "
            "minutes after the pipeline exited (2026-08-19 banner audit)"
        )

    def test_unchanged_state_on_quiet_fingerprint_still_skips(self, banner_fn):
        from dash.exceptions import PreventUpdate

        with _ctx("update-interval"):
            _call(banner_fn, {"running": False, "completed": True})
        with _ctx("update-interval"):
            with pytest.raises(PreventUpdate):
                _call(banner_fn, {"running": False, "completed": True})

    def test_running_never_gated(self, banner_fn):
        # The pre-existing rule: an active run re-renders every tick so the
        # countdown and elapsed keep moving.
        with _ctx("update-interval"):
            _call(banner_fn, {"running": True, "start_time": None})
        with _ctx("update-interval"):
            out = _call(banner_fn, {"running": True, "start_time": None})
        assert out[3] == "ACTIVE"
