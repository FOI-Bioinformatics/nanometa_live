"""The sample selector must not be rewritten on every polling tick.

Dash marks a component as pending while a callback that outputs to it is in
flight, and defers every callback keyed on that component's properties. The
sample selector's options carried a second-resolution freshness age
("12s"), so `update_sample_selector_options` produced new children on every
poll and the component was pending essentially all the time.

Measured on the 2026-08-19 dilution run: zero calls in 35 seconds to either
`update_selected_sample` or the dashboard metrics callback, while the
overall-status store already held 8,469 reads and 148 organisms. Sequences
Analyzed and Species Detected read 0 for the whole run. Keying the tiles on
the `selected-sample` store instead of the component did not help, because
that store is itself the output of a callback keyed on the component -- the
block propagates down the chain.

The fix removes the churn at its source: the option label carries a coarse
freshness bucket rather than a ticking second count, and the callback
short-circuits when the option signature is unchanged. The precise age is
still shown by the per-sample freshness pills elsewhere in the UI.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.callbacks.samples import (
    _freshness_bucket,
    _selector_signature,
)


class TestFreshnessBucket:
    def test_seconds_apart_share_a_bucket(self):
        assert _freshness_bucket(12) == _freshness_bucket(41)

    def test_minutes_apart_do_not(self):
        assert _freshness_bucket(30) != _freshness_bucket(400)

    def test_unknown_age_is_its_own_bucket(self):
        assert _freshness_bucket(None) == _freshness_bucket(None)
        assert _freshness_bucket(None) != _freshness_bucket(10)

    def test_buckets_are_monotonic_in_age(self):
        seq = [_freshness_bucket(a) for a in (5, 90, 600, 7200)]
        assert len(set(seq)) == 4, "each band must be distinguishable"


class TestSelectorSignature:
    SAMPLES = ["All Samples", "barcode01", "barcode02"]

    def test_identical_state_gives_identical_signature(self):
        a = _selector_signature(self.SAMPLES, {"barcode01": 10.0}, set())
        b = _selector_signature(self.SAMPLES, {"barcode01": 42.0}, set())
        assert a == b, (
            "a few seconds of age must not rewrite the selector; that churn "
            "keeps the component pending and starves every callback keyed "
            "on it"
        )

    def test_a_new_sample_changes_the_signature(self):
        a = _selector_signature(self.SAMPLES, {}, set())
        b = _selector_signature(self.SAMPLES + ["barcode03"], {}, set())
        assert a != b

    def test_a_sample_going_stale_changes_the_signature(self):
        a = _selector_signature(self.SAMPLES, {"barcode01": 10.0}, set())
        b = _selector_signature(self.SAMPLES, {"barcode01": 9999.0}, set())
        assert a != b, "a sample going quiet must still be visible"

    def test_a_sample_losing_data_changes_the_signature(self):
        a = _selector_signature(self.SAMPLES, {}, set())
        b = _selector_signature(self.SAMPLES, {}, {"barcode02"})
        assert a != b
