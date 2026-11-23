"""backend-status must change only when the status does.

``update_backend_status`` wrote ``get_status()`` into the Store on every
tick, and two fields changed every time whatever the run was doing:
``auto_stop_remaining_s`` (a countdown) and ``last_update`` (the monitor
thread's clock). About 13 callbacks take ``backend-status`` as an Input, so
each tick of a real-time run re-fired all of them (2026-11-23 bug hunt).

The status now publishes the auto-stop DEADLINE, which moves only when a new
input file resets the pipeline's timer, the verdict banner computes the time
left from it, and the Store write is skipped when nothing but ``last_update``
changed.
"""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from dash.exceptions import PreventUpdate

from nanometa_live.core.workflow.backend_manager import BackendManager
from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.unit


def _realtime_manager(tmp_path):
    m = BackendManager(str(tmp_path))
    m.config = {"processing_mode": "realtime", "realtime_timeout_minutes": 3}
    m.status["running"] = True
    m.status["start_time"] = datetime.now().isoformat()
    return m


def test_status_publishes_a_stable_deadline(tmp_path):
    m = _realtime_manager(tmp_path)
    with patch.object(m, "_update_file_counts", lambda: None):
        first = m.get_status()
        with patch("time.time", return_value=time.time() + 20):
            second = m.get_status()
    assert "auto_stop_remaining_s" not in first
    assert first["auto_stop_deadline"] == second["auto_stop_deadline"]
    remaining = first["auto_stop_deadline"] - time.time()
    assert 7 * 60 < remaining <= 8 * 60   # 3 min timeout + 5 min grace


def test_remaining_seconds_from_the_deadline():
    from nanometa_live.app.utils.countdown import remaining_from_deadline
    assert remaining_from_deadline(None, 100.0) is None
    assert remaining_from_deadline(160.0, 100.0) == 60
    assert remaining_from_deadline(90.0, 100.0) == 0


@pytest.fixture
def store_fn():
    from nanometa_live.app.callbacks.status import register_status
    backend = MagicMock()
    app = make_callback_app(lambda a: register_status(a, backend))
    return get_callback_fn(app, "backend-status.data"), backend


def test_a_tick_that_changes_only_last_update_writes_nothing(store_fn):
    fn, backend = store_fn
    prev = {"running": True, "files_processed": 3, "last_update": 1.0,
            "auto_stop_deadline": 500}
    backend.get_status.return_value = {**prev, "last_update": 6.0}
    with pytest.raises(PreventUpdate):
        fn(1, prev)


def test_a_real_change_is_written(store_fn):
    fn, backend = store_fn
    prev = {"running": True, "files_processed": 3, "last_update": 1.0}
    new = {**prev, "files_processed": 4, "last_update": 6.0}
    backend.get_status.return_value = new
    assert fn(1, prev) == new


def test_the_first_tick_is_written(store_fn):
    fn, backend = store_fn
    backend.get_status.return_value = {"running": False}
    assert fn(1, None) == {"running": False}
