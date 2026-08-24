"""Per-tick memo for the per-sample organism attribution dict.

`_load_per_sample_organisms` ran up to three times per dashboard tick (alert
panel, dashboard alerts, verdict banner on detection), each pass re-deriving
the organism dicts from every sample's cached frame — ~3S+3 passes over the
species table per tick at S barcodes (round-2 audit, 2026-08-22). The memo
shares one build per tick across all call sites, keyed on the loader
freshness epoch: it bumps whenever the results tree changes, and epoch 0
(process never polled — CLI, tests, report generation) bypasses the memo so
those callers can never be served stale data.
"""

from unittest.mock import patch

import pytest

from nanometa_live.app.utils import organisms_memo

pytestmark = pytest.mark.unit

FAKE = {123: [{"sample": "barcode01", "reads": 10, "abundance": 1.0,
               "is_negative_control": False}]}


@pytest.fixture(autouse=True)
def _reset():
    organisms_memo._memo.clear()
    yield
    organisms_memo._memo.clear()


@pytest.fixture
def epoch():
    from nanometa_live.core.utils import loader_utils
    before = loader_utils._freshness_epoch
    loader_utils._freshness_epoch = 7
    yield loader_utils
    loader_utils._freshness_epoch = before


def _call(counter, samples=("All Samples", "barcode01", "barcode02"),
          main_dir="/run", config=None):
    def counting_loader(md, s, cfg=None):
        counter["n"] += 1
        return dict(FAKE)

    with patch.object(organisms_memo, "_load_impl", counting_loader):
        return organisms_memo.get_per_sample_organisms_cached(
            main_dir, list(samples), config)


class TestMemoSharing:
    def test_repeat_call_in_same_epoch_builds_once(self, epoch):
        calls = {"n": 0}
        first = _call(calls)
        second = _call(calls)
        assert calls["n"] == 1
        assert first == FAKE and second == FAKE

    def test_epoch_bump_invalidates(self, epoch):
        calls = {"n": 0}
        _call(calls)
        epoch._freshness_epoch = 8
        _call(calls)
        assert calls["n"] == 2

    def test_different_sample_set_recomputes(self, epoch):
        calls = {"n": 0}
        _call(calls, samples=("All Samples", "barcode01"))
        _call(calls, samples=("All Samples", "barcode01", "barcode02"))
        assert calls["n"] == 2

    def test_negative_control_config_is_part_of_the_key(self, epoch):
        calls = {"n": 0}
        _call(calls, config={"negative_control_samples": []})
        _call(calls, config={"negative_control_samples": ["barcode02"]})
        assert calls["n"] == 2, (
            "the NC declaration changes is_negative_control flags inside "
            "the attribution dict; the memo must not serve one config's "
            "result to the other"
        )

    def test_epoch_zero_bypasses_the_memo(self):
        from nanometa_live.core.utils import loader_utils
        before = loader_utils._freshness_epoch
        loader_utils._freshness_epoch = 0
        try:
            calls = {"n": 0}
            _call(calls)
            _call(calls)
            assert calls["n"] == 2, (
                "epoch 0 means check_data_freshness never ran; CLI/report "
                "callers must stay on the uncached path"
            )
        finally:
            loader_utils._freshness_epoch = before

    def test_lru_bound_holds(self, epoch):
        calls = {"n": 0}
        for i in range(8):
            _call(calls, main_dir=f"/run{i}")
        assert len(organisms_memo._memo) <= organisms_memo._MEMO_MAX


class TestEquivalence:
    def test_memoized_output_equals_direct_call(self, epoch, tmp_path):
        """Against the real loader on a synthetic report tree."""
        import os
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        report = (
            " 90.00\t90\t10\tR\t1\troot\n"
            " 80.00\t80\t80\tS\t666\tTestus organismus\n"
        )
        for sample in ("barcode01", "barcode02"):
            p = kraken / f"{sample}.kraken2.report.txt"
            p.write_text(report)
            back = os.stat(p).st_mtime - 60
            os.utime(p, (back, back))

        from nanometa_live.app.tabs.dashboard_helpers import (
            _load_per_sample_organisms,
        )
        samples = ["All Samples", "barcode01", "barcode02"]
        direct = _load_per_sample_organisms(str(tmp_path), samples, None)
        memoized = organisms_memo.get_per_sample_organisms_cached(
            str(tmp_path), samples, None)
        assert memoized == direct
        assert 666 in memoized
