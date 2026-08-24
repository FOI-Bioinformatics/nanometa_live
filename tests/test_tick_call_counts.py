"""Integrated per-tick call-count pins at 96 barcodes.

One simulated warm tick over a synthetic 96-sample tree must not repeat
the work the round-2 fixes de-duplicated. Counts, never wall time, per
the repo's perf-gate philosophy. Each bound has generous headroom; the
pre-fix numbers were 3x organism builds, a fresh validation parser per
call, one glob per sample for the processed count, and a full results
walk on every watchlist-only config write.
"""

import os
import time
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

S = 96


@pytest.fixture
def tree(tmp_path):
    kraken = tmp_path / "kraken2"
    kraken.mkdir()
    report = (
        "100.00\t1000\t10\tR\t1\troot\n"
        + "".join(
            f" 10.00\t{50 + i}\t{50 + i}\tS\t{10000 + i}\tSpecies organismus{i}\n"
            for i in range(50)
        )
    )
    for i in range(S):
        (kraken / f"barcode{i:02d}.kraken2.report.txt").write_text(report)
    (tmp_path / "validation").mkdir()
    back = time.time() - 120
    for dirpath, _d, files in os.walk(tmp_path):
        for f in files:
            p = os.path.join(dirpath, f)
            os.utime(p, (back, back))
    return tmp_path


def _samples():
    return ["All Samples"] + [f"barcode{i:02d}" for i in range(S)]


class TestWarmTick:
    def test_organisms_built_once_across_the_three_call_sites(self, tree):
        from nanometa_live.core.utils import loader_utils
        from nanometa_live.app.utils import organisms_memo
        from nanometa_live.app.tabs import dashboard_helpers

        organisms_memo._memo.clear()
        loader_utils.check_data_freshness(str(tree))

        calls = {"n": 0}
        orig = dashboard_helpers._load_per_sample_organisms

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        with patch.object(organisms_memo, "_load_impl", counting):
            for _site in range(3):  # banner + panel + alerts
                organisms_memo.get_per_sample_organisms_cached(
                    str(tree), _samples(), None)
        assert calls["n"] == 1

    def test_validation_parser_not_constructed_on_a_warm_tick(self, tree):
        from nanometa_live.core.parsers import blast_validation_parser as bvp

        bvp.reset_validation_parsers()
        bvp.get_validation_parser(str(tree))  # warm

        calls = {"n": 0}
        orig = bvp.BlastValidationParser.__init__

        def counting(self, results_dir):
            calls["n"] += 1
            return orig(self, results_dir)

        with patch.object(bvp.BlastValidationParser, "__init__", counting):
            for _ in range(2):  # validation tab + dashboard lookup
                bvp.get_validation_parser(str(tree))
        assert calls["n"] == 0

    def test_processed_count_needs_zero_globs(self, tree):
        import glob as glob_module
        from nanometa_live.app.tabs import dashboard_helpers

        calls = {"n": 0}
        orig = glob_module.glob

        def counting(pattern, **kw):
            calls["n"] += 1
            return orig(pattern, **kw)

        with patch.object(dashboard_helpers.glob, "glob", counting):
            count = dashboard_helpers._count_processed_samples(
                str(tree), _samples()[1:])
        assert count == S
        assert calls["n"] == 0

    def test_watchlist_only_config_change_does_not_walk_the_tree(self, tree):
        """The fingerprint amplifier: a watchlist toggle must not re-walk
        the results tree (it fired the whole fingerprint cascade)."""
        from unittest.mock import MagicMock
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from dash.exceptions import PreventUpdate
        from nanometa_live.app.callbacks.status import register_status

        app = make_callback_app(lambda a: register_status(a, MagicMock()))
        derive = get_callback_fn(app, "results-dir-path")
        config = {"results_dir_override": str(tree),
                  "watchlist": {"custom": []}}
        first = derive(config, None)
        assert first == str(tree)

        walks = {"n": 0}
        orig_walk = os.walk

        def counting(path, **kw):
            walks["n"] += 1
            return orig_walk(path, **kw)

        toggled = dict(config, watchlist={"custom": [{"taxid": 1}]})
        with patch("os.walk", counting):
            with pytest.raises(PreventUpdate):
                derive(toggled, first)
        assert walks["n"] == 0