"""The in-process render memo must expire, so a frozen panel self-heals.

The 2026-08-19 field report proved the failure shape: a callback renders,
``mark_rendered`` records the fingerprint in an IN-PROCESS dict, the browser
never applies that one response -- and every later interval tick consults the
memo, concludes the refresh is redundant, and PreventUpdates. On a quiet
outdir (a finished realtime run) the fingerprint never changes again, so the
panel is stale forever.

The validation and consensus stores got the exact fix (a store-backed memo
that rides the response, ``interval_tick_is_redundant_store``). Eleven other
callbacks -- the verdict banner, alert panel, status cache, classification
plot, reports list and six QC surfaces -- still use the in-process memo.
Rather than rewiring each with a companion Store, the memo itself now
expires after ``RENDER_MEMO_TTL_SECONDS``: one lost response costs at most
one TTL of staleness instead of the rest of the session, at the price of one
re-render per callback per TTL on a quiet outdir (cheap -- the loader mtime
caches absorb the parse cost; a full quiet poll measures ~59 ms).
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.utils import debounce
from nanometa_live.app.utils.debounce import (
    RENDER_MEMO_TTL_SECONDS,
    interval_render_is_redundant,
    mark_rendered,
)

FP = {"fp": "abc", "ts": 1.0}


@pytest.fixture(autouse=True)
def _clean_memo():
    debounce.reset_debounce()
    yield
    debounce.reset_debounce()


class TestTtlBackstop:
    def test_fresh_memo_is_redundant(self):
        mark_rendered("cb", FP)
        assert interval_render_is_redundant("cb", FP) is True

    def test_changed_fingerprint_is_never_redundant(self):
        mark_rendered("cb", FP)
        assert interval_render_is_redundant("cb", {"fp": "other"}) is False

    def test_expired_memo_is_not_redundant(self, monkeypatch):
        mark_rendered("cb", FP)
        real_time = debounce.time.time
        monkeypatch.setattr(
            debounce.time, "time",
            lambda: real_time() + RENDER_MEMO_TTL_SECONDS + 1,
        )
        assert interval_render_is_redundant("cb", FP) is False, (
            "an unexpiring memo makes one lost browser response freeze the "
            "panel for the rest of a quiet realtime run (2026-08-19 field "
            "report)"
        )

    def test_rerender_restamps_the_memo(self, monkeypatch):
        mark_rendered("cb", FP)
        real_time = debounce.time.time
        offset = RENDER_MEMO_TTL_SECONDS + 1
        monkeypatch.setattr(debounce.time, "time", lambda: real_time() + offset)
        # Backstop fired -> the callback re-renders and re-stamps ...
        assert interval_render_is_redundant("cb", FP) is False
        mark_rendered("cb", FP)
        # ... and the memo is fresh again relative to the shifted clock.
        assert interval_render_is_redundant("cb", FP) is True

    def test_ttl_is_a_bounded_backstop_not_a_poll(self):
        # Wide enough that normal 10 s active polling stays gated, bounded
        # enough that a stale panel repairs within a couple of idle ticks.
        assert 60 <= RENDER_MEMO_TTL_SECONDS <= 300
