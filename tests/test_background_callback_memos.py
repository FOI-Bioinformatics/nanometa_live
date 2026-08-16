"""Regression cover for memos that must survive the background-worker boundary.

``background=True`` callbacks run in a process DiskcacheManager spawns fresh for
every invocation (app.py forces the "spawn" start method), so any state kept in
a module-level dict is re-initialised on entry each time. Three callbacks relied
on exactly that: the interval-backstop guards in update_main_results and
update_qc_stats, and update_readiness_state's TTL around its docker/nextflow
subprocess probes. None of them ever fired.

These tests pin the replacement contract -- the memo round-trips through a
dcc.Store read as State -- and, in test_module_memo_does_not_cross_process,
demonstrate the underlying process-boundary fact so the reasoning is not just
asserted in a comment.
"""

import multiprocessing as mp

import pytest

pytestmark = pytest.mark.callback

from nanometa_live.app.utils.debounce import (
    fp_to_store,
    interval_tick_is_redundant_store,
)
from nanometa_live.app.callbacks.readiness import _probe_window_is_fresh, _READINESS_TTL
from dash_test_utils import ctx_with


FP = {"fp": "abc123", "ts": 111.0}


class TestIntervalTickIsRedundantStore:
    """The Store-backed variant of the interval-backstop guard."""

    def test_interval_tick_with_same_fp_is_redundant(self):
        with ctx_with("update-interval"):
            import dash
            assert interval_tick_is_redundant_store(dash.ctx, "abc123", FP) is True

    def test_interval_tick_with_advanced_fp_renders(self):
        with ctx_with("update-interval"):
            import dash
            assert interval_tick_is_redundant_store(dash.ctx, "OLDER", FP) is False

    def test_never_rendered_is_not_redundant(self):
        """A None memo means "this callback has not rendered yet". It must
        render, otherwise a tab opened on a quiet outdir stays on its empty
        initial layout forever."""
        with ctx_with("update-interval"):
            import dash
            assert interval_tick_is_redundant_store(dash.ctx, None, FP) is False

    def test_non_interval_trigger_always_renders(self):
        """User actions (sample switch, Apply, watchlist change) are not
        backstop ticks and must never be skipped, even at the same fingerprint."""
        with ctx_with("selected-sample"):
            import dash
            assert interval_tick_is_redundant_store(dash.ctx, "abc123", FP) is False

    def test_fp_to_store_matches_what_the_predicate_compares(self):
        """The writer and the reader must agree, or the guard never matches."""
        stored = fp_to_store(FP)
        with ctx_with("update-interval"):
            import dash
            assert interval_tick_is_redundant_store(dash.ctx, stored, FP) is True


class TestReadinessProbeWindow:
    """The readiness TTL now lives on readiness-probe-stamp, not a module global."""

    def test_fresh_same_fingerprint_skips(self):
        stamp = {"fingerprint": "fp1", "ts": 1000.0}
        assert _probe_window_is_fresh(stamp, "fp1", 1000.0 + 1) is True

    def test_expired_window_recomputes(self):
        stamp = {"fingerprint": "fp1", "ts": 1000.0}
        assert _probe_window_is_fresh(stamp, "fp1", 1000.0 + _READINESS_TTL + 1) is False

    def test_changed_fingerprint_recomputes(self):
        """A config/watchlist edit must re-probe immediately, TTL or not."""
        stamp = {"fingerprint": "fp1", "ts": 1000.0}
        assert _probe_window_is_fresh(stamp, "fp2", 1000.0 + 1) is False

    def test_no_stamp_recomputes(self):
        assert _probe_window_is_fresh(None, "fp1", 1000.0) is False

    @pytest.mark.parametrize("stamp", [
        {},                                     # never written
        {"fingerprint": "fp1"},                 # no ts
        {"fingerprint": "fp1", "ts": "junk"},   # unparseable ts
        "not-a-dict",
    ])
    def test_malformed_stamp_recomputes(self, stamp):
        """Fail open: a stamp we cannot read must never suppress a probe."""
        assert _probe_window_is_fresh(stamp, "fp1", 1000.0) is False


def _worker(queue):
    """Read the in-process memo dict, in a child process."""
    from nanometa_live.app.utils.debounce import _render_fp
    queue.put(dict(_render_fp))


def test_module_memo_does_not_cross_process():
    """The fact the Store-backed memo exists to work around.

    A module-level memo written in the parent is absent in a spawned child, so
    the in-process guard could never see what a previous invocation rendered.
    Uses stdlib multiprocessing with an explicit "spawn" context, matching what
    app.py forces for DiskcacheManager's workers.
    """
    from nanometa_live.app.utils.debounce import mark_rendered, _render_fp

    mark_rendered("cross_process_probe", FP)
    assert _render_fp.get("cross_process_probe") == "abc123"  # parent sees it

    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_worker, args=(queue,))
    proc.start()
    child_memo = queue.get(timeout=60)
    proc.join(timeout=60)

    assert "cross_process_probe" not in child_memo
