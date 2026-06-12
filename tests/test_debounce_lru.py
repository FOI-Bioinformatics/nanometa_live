"""Tests for the LRU bound on the debounce dict.

The audit (P1-T08) flagged ``_debounce_timestamps`` as unbounded. With
pattern-matching callback ids (which embed sample names, taxids, etc.)
the dict could grow indefinitely over a long real-time session. The
fix bounds it to ``_DEBOUNCE_MAX_KEYS`` entries with LRU eviction.
"""

import time
from types import SimpleNamespace

from nanometa_live.app.utils import debounce as dbm


class TestDebounceLruBound:
    """``_debounce_timestamps`` must not grow without bound."""

    def setup_method(self):
        # Reset state so tests do not leak through one another.
        dbm.reset_debounce()

    def test_dict_capped_at_max_keys(self):
        """Inserting more than ``_DEBOUNCE_MAX_KEYS`` keys must not exceed cap."""
        cap = dbm._DEBOUNCE_MAX_KEYS
        for i in range(cap + 100):
            dbm.should_skip_update(f"callback-{i}", debounce_ms=0)

        assert len(dbm._debounce_timestamps) <= cap, (
            f"Debounce dict exceeded cap: "
            f"{len(dbm._debounce_timestamps)} > {cap}"
        )

    def test_oldest_entry_evicted_when_at_cap(self):
        """When the cap is hit, the least-recently-used key is evicted."""
        cap = dbm._DEBOUNCE_MAX_KEYS

        # Fill to capacity and remember the first key inserted.
        first_key = "callback-0"
        for i in range(cap):
            dbm.should_skip_update(f"callback-{i}", debounce_ms=0)
        assert first_key in dbm._debounce_timestamps

        # Insert one more key. The first should be evicted.
        dbm.should_skip_update("callback-overflow", debounce_ms=0)
        assert first_key not in dbm._debounce_timestamps
        assert "callback-overflow" in dbm._debounce_timestamps

    def test_recently_used_key_not_evicted(self):
        """A key consulted by ``should_skip_update`` (even when skipped)
        is moved to the end of the LRU order and protected from eviction.
        """
        cap = dbm._DEBOUNCE_MAX_KEYS

        protected = "callback-protected"
        # Insert the protected key first; let some time pass so subsequent
        # consults return False (executes).
        dbm.should_skip_update(protected, debounce_ms=0)
        time.sleep(0.001)

        # Fill the rest of the cap with unique keys.
        for i in range(cap - 1):
            dbm.should_skip_update(f"callback-{i}", debounce_ms=0)

        # Re-consult the protected key. With debounce_ms=0 it executes
        # again, which by the implementation moves it to the end.
        time.sleep(0.001)
        dbm.should_skip_update(protected, debounce_ms=0)

        # Insert another key to push capacity over.
        dbm.should_skip_update("callback-new", debounce_ms=0)

        # The protected key must still be present; some other older key
        # should have been evicted.
        assert protected in dbm._debounce_timestamps

    def test_skipped_call_also_extends_lru_lifetime(self):
        """A consult that *returns True* (debounce skip) must still mark
        the key as recently used so it does not get evicted while it is
        still being actively gated."""
        # Set a long debounce so subsequent consults are skip-paths.
        key = "callback-active"
        dbm.should_skip_update(key, debounce_ms=10_000)  # records timestamp

        cap = dbm._DEBOUNCE_MAX_KEYS
        # Fill the cap with new keys; if the active key were not LRU-
        # touched on the skip-path, it would be evicted as the oldest.
        for i in range(cap):
            dbm.should_skip_update(f"filler-{i}", debounce_ms=0)
            # Re-consult the active key after each insert; this is a
            # skip-path under the long debounce window.
            dbm.should_skip_update(key, debounce_ms=10_000)

        assert key in dbm._debounce_timestamps, (
            "Skipped consults must extend LRU lifetime"
        )


class TestFingerprintRenderGate:
    """interval_render_is_redundant / mark_rendered: an interval-driven
    backstop must re-render only when the results fingerprint advances or the
    callback has not yet rendered the current fingerprint."""

    def setup_method(self):
        dbm._render_fp.clear()

    def test_unseen_fingerprint_is_not_redundant(self):
        # Never rendered -> not redundant (fresh tab view must render once).
        assert dbm.interval_render_is_redundant("cb", {"fp": "A"}) is False

    def test_same_fingerprint_after_mark_is_redundant(self):
        dbm.mark_rendered("cb", {"fp": "A"})
        assert dbm.interval_render_is_redundant("cb", {"fp": "A"}) is True

    def test_advanced_fingerprint_is_not_redundant(self):
        dbm.mark_rendered("cb", {"fp": "A"})
        assert dbm.interval_render_is_redundant("cb", {"fp": "B"}) is False

    def test_accepts_raw_fp_string_or_dict(self):
        dbm.mark_rendered("cb", "Z")
        assert dbm.interval_render_is_redundant("cb", {"fp": "Z"}) is True
        assert dbm.interval_render_is_redundant("cb", "Z") is True

    def test_per_callback_isolation(self):
        dbm.mark_rendered("cbA", {"fp": "A"})
        # A different callback has not seen fp "A".
        assert dbm.interval_render_is_redundant("cbB", {"fp": "A"}) is False

    def test_render_fp_memo_is_bounded(self):
        for i in range(dbm._DEBOUNCE_MAX_KEYS + 50):
            dbm.mark_rendered(f"cb-{i}", {"fp": str(i)})
        assert len(dbm._render_fp) <= dbm._DEBOUNCE_MAX_KEYS


class TestIntervalTickIsRedundant:
    """interval_tick_is_redundant collapses the
    ``get_trigger_type(ctx) == "interval" and interval_render_is_redundant(...)``
    predicate every results-driven tab callback opens with."""

    def setup_method(self):
        dbm._render_fp.clear()

    def _ctx(self, triggered_id):
        return SimpleNamespace(triggered_id=triggered_id)

    def test_interval_tick_unchanged_fp_is_redundant(self):
        dbm.mark_rendered("cb", {"fp": "A"})
        assert dbm.interval_tick_is_redundant(self._ctx("update-interval"), "cb", {"fp": "A"}) is True

    def test_interval_tick_advanced_fp_is_not_redundant(self):
        dbm.mark_rendered("cb", {"fp": "A"})
        assert dbm.interval_tick_is_redundant(self._ctx("update-interval"), "cb", {"fp": "B"}) is False

    def test_non_interval_trigger_always_proceeds(self):
        # A user action (e.g. a sort button) must render even if the fingerprint
        # is unchanged -- only interval backstop ticks are gated.
        dbm.mark_rendered("cb", {"fp": "A"})
        assert dbm.interval_tick_is_redundant(self._ctx("sort-button"), "cb", {"fp": "A"}) is False
