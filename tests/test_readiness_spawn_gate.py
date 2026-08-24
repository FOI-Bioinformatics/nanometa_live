"""The readiness recompute must not spawn a worker process per tick.

Round-3 soak measurement: ``update_readiness_state`` had
``update-interval`` as a direct Input, so DiskcacheManager spawned a NEW
OS process on every tick just to evaluate the TTL guard and return
no_update -- and each spawn left parent-side pipe fds behind (4,500+
pipes after two hours; ~28-34 fds/min during a run). The fix is a cheap
synchronous MAIN-PROCESS gate: it applies the same fingerprint/TTL check
in-process and bumps ``readiness-recompute-due`` only when a recompute
is genuinely due; the background callback fires from that Store alone.
The gate also reaps finished spawn children so their plumbing is
released promptly.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from dash import Dash
from dash.exceptions import PreventUpdate

pytestmark = pytest.mark.unit

from tests.dash_test_utils import ctx_with, get_callback_fn


def _app():
    from nanometa_live.app.callbacks.readiness import register_readiness
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_readiness(app, MagicMock())
    return app


def _gate(app):
    return get_callback_fn(app, "readiness-recompute-due",
                           input_contains="update-interval")


CONFIG = {"kraken_db": "/db", "pipeline_profile": "conda"}


class TestGate:
    def test_fresh_ttl_prevents_update_without_wakeup(self):
        import nanometa_live.app.callbacks.readiness as rd
        app = _app()
        fn = _gate(app)
        fp = rd._readiness_fingerprint(CONFIG, None)
        stamp = {"fingerprint": fp, "ts": time.time()}
        rd._probe_wakeup.clear()
        with ctx_with("update-interval"):
            with pytest.raises(PreventUpdate):
                fn(5, CONFIG, 0, None, stamp, None, {"n": 3})
        assert not rd._probe_wakeup.is_set(), (
            "a fresh window must not wake the probe thread")

    def test_expired_ttl_wakes_the_probe_thread(self):
        # The periodic path never spawns a worker: an expired TTL wakes
        # the main-process probe thread and PreventUpdates.
        import nanometa_live.app.callbacks.readiness as rd
        app = _app()
        fn = _gate(app)
        fp = rd._readiness_fingerprint(CONFIG, None)
        stamp = {"fingerprint": fp, "ts": time.time() - 999}
        rd._probe_wakeup.clear()
        with ctx_with("update-interval"):
            with pytest.raises(PreventUpdate):
                fn(5, CONFIG, 0, None, stamp, None, {"n": 3})
        assert rd._probe_wakeup.is_set()
        rd._probe_wakeup.clear()

    def test_button_forces_and_flags(self):
        import nanometa_live.app.callbacks.readiness as rd
        app = _app()
        fn = _gate(app)
        fp = rd._readiness_fingerprint(CONFIG, None)
        stamp = {"fingerprint": fp, "ts": time.time()}  # fresh -- still forced
        with ctx_with("check-readiness-btn"):
            due = fn(5, CONFIG, 1, None, stamp, None, None)
        assert due["forced"] is True

    def test_genome_completion_wakes_thread_with_genome_flag(self):
        import nanometa_live.app.callbacks.readiness as rd
        app = _app()
        fn = _gate(app)
        fp = rd._readiness_fingerprint(CONFIG, None)
        stamp = {"fingerprint": fp, "ts": time.time()}
        rd._probe_wakeup.clear()
        with ctx_with("genome-download-complete"):
            with pytest.raises(PreventUpdate):
                fn(5, CONFIG, 0, {"x": 1}, stamp, None, {"n": 0})
        assert rd._probe_wakeup.is_set()
        with rd._probe_lock:
            assert rd._probe_input.get("genome_changed") is True
            rd._probe_input["genome_changed"] = False
        rd._probe_wakeup.clear()

    def test_gate_reaps_finished_children(self):
        import nanometa_live.app.callbacks.readiness as rd
        app = _app()
        fn = _gate(app)
        with patch.object(rd, "_reap_spawn_children") as reap:
            with ctx_with("update-interval"):
                try:
                    fn(5, CONFIG, 0, None, None, None, None)
                except PreventUpdate:
                    pass
        reap.assert_called_once()


class TestWorkerFiresFromTheStoreOnly:
    def test_worker_input_is_the_due_store(self):
        import inspect
        import nanometa_live.app.callbacks.readiness as rd
        src = inspect.getsource(rd)
        import re
        before = src.split("def update_readiness_state(")[0]
        dec = before[before.rindex("@app.callback("):]
        assert 'Input("readiness-recompute-due"' in dec
        assert 'Input("update-interval"' not in dec, (
            "the per-tick Input is exactly what spawned a process per tick"
        )
