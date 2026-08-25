"""load_blast_validation_data must not scale with pairs x watchlist.

Round-3 audit: the main-tab poll path did a linear watchlist scan per
aggregate entry (12,384 x 129 = 1.6 M comparisons), two globs over the
whole blast dir per watchlist entry, and cached nothing. The fixes:
dict-by-taxid lookups, one directory listing indexed by taxid, and the
standard mtime-cache idiom around the whole call.
"""

import glob as glob_module
import json
import os
import time
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import validation_loaders


WATCHLIST = [{"taxid": 500 + i, "name": f"Organism {i}"} for i in range(50)]


@pytest.fixture(autouse=True)
def _fresh():
    from nanometa_live.core.utils import loader_utils
    loader_utils.clear_all_loader_caches()
    loader_utils._freshness_epoch = 0
    yield
    loader_utils.clear_all_loader_caches()


def _tree(tmp_path, disk_pairs=6):
    blast = tmp_path / "validation" / "blast"
    blast.mkdir(parents=True)
    t = time.time() - 120
    for i in range(disk_pairs):
        f = blast / f"barcode01_taxid{500 + i}.blast.tsv"
        f.write_text(f"r{i}\tref\t99.0\t500\t2\t0\t1\t500\t10\t510"
                     "\t1e-50\t900\n")
        os.utime(f, (t, t))
    agg = tmp_path / "validation" / "validation_results.json"
    agg.write_text(json.dumps({
        "results": {"barcode01": {
            "540": {"blast_hits": 10, "hit_rate": 0.9, "kraken_reads": 11,
                    "avg_identity": 99.0, "validation_status": "confirmed"},
        }},
    }))
    os.utime(agg, (t, t))
    return tmp_path


class TestEquivalenceAndCost:
    def test_disk_and_aggregate_tiers_still_load(self, tmp_path):
        tree = _tree(tmp_path)
        res = validation_loaders.load_blast_validation_data(
            str(tree), WATCHLIST)
        assert 540 in res, "aggregate tier entry lost"
        assert 500 in res and res[500]["validated_reads"] == 1, (
            "disk tier entry lost")

    def test_globs_do_not_scale_with_watchlist(self, tmp_path):
        tree = _tree(tmp_path)
        calls = {"n": 0}
        orig = glob_module.glob

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        with patch.object(glob_module, "glob", counting):
            validation_loaders.load_blast_validation_data(
                str(tree), WATCHLIST)
        assert calls["n"] <= 4, (
            f"{calls['n']} globs for a 50-entry watchlist -- the disk tier "
            "must index the directory once, not glob per entry"
        )

    def test_warm_call_reads_no_files(self, tmp_path, monkeypatch):
        import builtins
        from nanometa_live.core.utils import loader_utils
        tree = _tree(tmp_path)
        monkeypatch.setattr(loader_utils, "_freshness_epoch", 5)
        validation_loaders.load_blast_validation_data(str(tree), WATCHLIST)

        calls = {"n": 0}
        orig = builtins.open

        def counting(file, *a, **kw):
            if "validation" in str(file):
                calls["n"] += 1
            return orig(file, *a, **kw)

        with patch.object(builtins, "open", counting):
            res = validation_loaders.load_blast_validation_data(
                str(tree), WATCHLIST)
        assert calls["n"] == 0, "an unchanged tick must be a cache hit"
        assert 540 in res

    def test_watchlist_change_is_not_served_from_the_old_key(self, tmp_path,
                                                             monkeypatch):
        from nanometa_live.core.utils import loader_utils
        tree = _tree(tmp_path)
        monkeypatch.setattr(loader_utils, "_freshness_epoch", 5)
        validation_loaders.load_blast_validation_data(str(tree), WATCHLIST)
        smaller = WATCHLIST[:1]
        res = validation_loaders.load_blast_validation_data(
            str(tree), smaller)
        assert set(res) <= {500}, (
            "a different watchlist must not reuse the previous cache entry"
        )


class TestBatchEnumerationGateAndCap:
    """_enumerate_batch_ids iterated + regexed EVERY file in the batch
    dirs on every fingerprint tick -- the dirs grow as pairs x batches
    (millions at the envelope). The id set only changes when a file is
    added, which bumps the dir mtime, so a dir-mtime memo makes the
    quiet tick free; the dropdown caps at the most recent N with an
    explicit 'latest N of M' label (a cap on a navigation list, stated,
    never hidden state)."""

    def _batch_tree(self, tmp_path, batches=5):
        for tool in ("blast", "minimap2"):
            bdir = tmp_path / "validation" / tool / "batch"
            bdir.mkdir(parents=True)
            t = time.time() - 120
            for b in range(batches):
                ext = "blast.tsv" if tool == "blast" else "paf"
                f = bdir / f"barcode01_taxid500_{b}.{ext}"
                f.write_text("x\n")
                os.utime(f, (t, t))
            os.utime(bdir, (t, t))
        return {"results_dir_override": str(tmp_path)}

    def test_repeat_call_does_not_iterate(self, tmp_path):
        from nanometa_live.app.tabs import validation_tab_helpers as vth
        cfg = self._batch_tree(tmp_path)
        vth._enumerate_batch_ids(cfg)

        calls = {"n": 0}
        orig = os.scandir

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        with patch.object(os, "scandir", counting):
            ids = vth._enumerate_batch_ids(cfg)
        assert calls["n"] == 0, "unchanged batch dirs must be memoized"
        assert ids == ["4", "3", "2", "1", "0"]

    def test_new_batch_file_invalidates(self, tmp_path):
        from nanometa_live.app.tabs import validation_tab_helpers as vth
        cfg = self._batch_tree(tmp_path)
        assert len(vth._enumerate_batch_ids(cfg)) == 5
        bdir = tmp_path / "validation" / "blast" / "batch"
        f = bdir / "barcode01_taxid500_9.blast.tsv"
        f.write_text("x\n")
        t = time.time() - 60
        os.utime(f, (t, t))
        os.utime(bdir, (t, t))
        assert vth._enumerate_batch_ids(cfg)[0] == "9"

    def test_dropdown_caps_with_a_stated_label(self, tmp_path):
        from nanometa_live.app.tabs import validation_tab_helpers as vth
        cfg = self._batch_tree(tmp_path, batches=vth.BATCH_DROPDOWN_CAP + 20)
        controls, col, options, value = vth._batch_selector_state(
            cfg, "batch", None)
        assert len(options) == vth.BATCH_DROPDOWN_CAP + 1, (
            "cap plus one disabled 'latest N of M' notice row")
        notice = options[-1]
        assert notice.get("disabled")
        assert "of" in str(notice.get("label"))
        assert value == options[0]["value"]

    def test_below_the_cap_no_notice(self, tmp_path):
        from nanometa_live.app.tabs import validation_tab_helpers as vth
        cfg = self._batch_tree(tmp_path, batches=3)
        _c, _col, options, _v = vth._batch_selector_state(cfg, "batch", None)
        assert len(options) == 3
        assert not any(o.get("disabled") for o in options)
