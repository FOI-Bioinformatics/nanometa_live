"""A report skipped for instability must not poison the aggregate caches.

Live find (2026-08-26, demo-4 build): the last barcode of a completed batch
run vanished from the verdict banner. Its report was written seconds before
the poll, so ``_parse_kraken2_report`` skipped it via the 1-second
file-stability gate -- and the REDUCED aggregate was then cached under the
directory fingerprint. A completed run's tree never changes again, so the
fingerprint never advances, and the frozen union served "3 of 4 barcodes"
indefinitely: Staphylococcus aureus (barcode04, 52 reads on disk) was
missing from ACTION REQUIRED until the app was restarted.

The stability skip is transient by definition (the file merely has to age
past one second, which changes no mtime), so its result must never be
stored in a cache keyed on mtimes. Both layers had the hazard: the
per-sample accumulation cache (``report_accumulation``) and the
``_cache_and_return`` tiers in the loader's aggregate and multi-file
branches. A corrupt (stable but unparseable) file is different: its cache
entry is legitimate, because healing it requires a rewrite, which changes
the mtime and the key.
"""

import os
import time

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import classification_loaders as cl
from nanometa_live.core.utils import loader_utils


REPORT = (
    "100.00\t100\t10\tR\t1\troot\n"
    " 50.00\t{n}\t{n}\tS\t{taxid}\tSpecies {name}\n"
)


def _write_report(path, taxid, name, n=50, age=None):
    path.write_text(REPORT.format(n=n, taxid=taxid, name=name))
    if age is not None:
        back = time.time() - age
        os.utime(path, (back, back))


@pytest.fixture(autouse=True)
def _fresh_loader_state():
    loader_utils.clear_all_loader_caches()
    loader_utils._freshness_epoch = 0
    yield
    loader_utils.clear_all_loader_caches()


class TestAggregateNotFrozenByUnstableReport:
    def test_sample_skipped_while_young_appears_once_stable(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        _write_report(kraken / "barcode01.kraken2.report.txt",
                      101, "alpha", age=120)
        # barcode02's report is fresh: inside the 1 s stability window.
        _write_report(kraken / "barcode02.kraken2.report.txt", 202, "beta")

        df1 = cl.load_kraken_data(str(tmp_path), "All Samples")
        assert 101 in set(df1["taxid"]), "stable sample must load"
        assert 202 not in set(df1["taxid"]), (
            "precondition: the young report is skipped on the first poll")

        # The file ages past the stability window. No mtime changes, so a
        # cache keyed on mtimes cannot tell the difference -- which is why
        # the reduced union must not have been cached.
        time.sleep(1.2)
        df2 = cl.load_kraken_data(str(tmp_path), "All Samples")
        assert 202 in set(df2["taxid"]), (
            "the skipped sample must appear once its report is stable; the "
            "reduced aggregate was served from cache")

    def test_multi_batch_sample_not_frozen(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        _write_report(kraken / "barcode01_batch0.kraken2.report.txt",
                      101, "alpha", age=120)
        _write_report(kraken / "barcode01_batch1.kraken2.report.txt",
                      202, "beta")

        df1 = cl.load_kraken_data(str(tmp_path), "barcode01")
        assert 202 not in set(df1["taxid"]), (
            "precondition: the young batch is skipped on the first poll")
        time.sleep(1.2)
        df2 = cl.load_kraken_data(str(tmp_path), "barcode01")
        assert 202 in set(df2["taxid"]), (
            "the skipped batch must appear once stable")

    def test_stable_tree_is_still_cached(self, tmp_path):
        """The fix must not disable caching for healthy trees."""
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        _write_report(kraken / "barcode01.kraken2.report.txt",
                      101, "alpha", age=120)
        _write_report(kraken / "barcode02.kraken2.report.txt",
                      202, "beta", age=120)
        cl.load_kraken_data(str(tmp_path), "All Samples")

        calls = {"n": 0}
        orig = cl._parse_kraken2_report_uncached

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        from unittest.mock import patch
        with patch.object(cl, "_parse_kraken2_report_uncached", counting):
            df = cl.load_kraken_data(str(tmp_path), "All Samples")
        assert {101, 202} <= set(df["taxid"])
        assert calls["n"] == 0, (
            "a quiet stable tree must be served from cache with no re-parse")
