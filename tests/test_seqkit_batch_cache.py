"""The seqkit incremental path must not re-read every batch every poll.

Round-3 measurement (perf harness, 24 barcodes x 100 batches): one
incremental tick re-read all 2,400 batch TSVs -- 2,414 pandas.read_csv
calls, 19.6 s -- because `_load_seqkit_incremental` had no per-file cache
and its aggregate fingerprint covers the whole seqkit dir, so any
sample's new batch re-parsed every batch of every sample. Batch TSVs are
immutable once stable, so a per-file `(realpath, mtime_ns, size)` cache
(the `_report_frame_cache` idiom) makes a new batch cost exactly one
read.
"""

import os
import time
from unittest.mock import patch

import pandas as pd
import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.utils import qc_loaders
from nanometa_live.core.utils import seqkit_batch_cache


HEADER = ("file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len"
          "\tQ1\tQ2\tQ3\tsum_gap\tN50\tN50_num\tQ20(%)\tQ30(%)\tAvgQual"
          "\tGC(%)\tsum_n\n")


def _write_batch(dirpath, name, num=100):
    row = (f"batch.fastq\tFASTQ\tDNA\t{num}\t{num * 500}\t100\t500.0\t900"
           f"\t300\t500\t700\t0\t550\t40\t95.0\t90.0\t14.5\t42.0\t0\n")
    p = dirpath / name
    p.write_text(HEADER + row)
    t = time.time() - 120
    os.utime(p, (t, t))
    return p


def _tree(tmp_path, samples=3, batches=4):
    seqkit = tmp_path / "seqkit"
    for i in range(1, samples + 1):
        bdir = seqkit / f"barcode{i:02d}" / "batch_stats"
        bdir.mkdir(parents=True)
        for b in range(batches):
            _write_batch(bdir, f"batch_{b}.tsv")
    return str(seqkit)


@pytest.fixture(autouse=True)
def _fresh_cache():
    seqkit_batch_cache.clear_seqkit_batch_cache()
    yield
    seqkit_batch_cache.clear_seqkit_batch_cache()


def _count_reads(fn, *args):
    calls = {"n": 0}
    orig = pd.read_csv

    def counting(*a, **kw):
        calls["n"] += 1
        return orig(*a, **kw)

    with patch.object(pd, "read_csv", counting):
        result = fn(*args)
    return calls["n"], result


class TestPerBatchFileCache:
    def test_second_load_reads_nothing(self, tmp_path):
        seqkit = _tree(tmp_path)
        n1, df1 = _count_reads(qc_loaders._load_seqkit_incremental, seqkit)
        assert n1 == 12
        n2, df2 = _count_reads(qc_loaders._load_seqkit_incremental, seqkit)
        assert n2 == 0, "unchanged batch TSVs must be served from the cache"
        pd.testing.assert_frame_equal(
            df1.reset_index(drop=True), df2.reset_index(drop=True))

    def test_one_new_batch_costs_exactly_one_read(self, tmp_path):
        seqkit = _tree(tmp_path)
        qc_loaders._load_seqkit_incremental(seqkit)
        _write_batch(tmp_path / "seqkit" / "barcode02" / "batch_stats",
                     "batch_4.tsv")
        n, df = _count_reads(qc_loaders._load_seqkit_incremental, seqkit)
        assert n == 1
        row = df[df["sample"] == "barcode02"] if "sample" in df.columns else df
        assert not row.empty

    def test_output_identical_to_uncached(self, tmp_path):
        seqkit = _tree(tmp_path)
        cached = qc_loaders._load_seqkit_incremental(seqkit)
        seqkit_batch_cache.clear_seqkit_batch_cache()
        fresh = qc_loaders._load_seqkit_incremental(seqkit)
        pd.testing.assert_frame_equal(
            cached.reset_index(drop=True), fresh.reset_index(drop=True))

    def test_rewritten_batch_is_reparsed(self, tmp_path):
        # Immutability is an expectation, not a guarantee: a rewrite (new
        # mtime/size) must miss the cache and update the aggregate.
        seqkit = _tree(tmp_path, samples=1, batches=2)
        df1 = qc_loaders._load_seqkit_incremental(seqkit)
        _write_batch(tmp_path / "seqkit" / "barcode01" / "batch_stats",
                     "batch_1.tsv", num=900)
        df2 = qc_loaders._load_seqkit_incremental(seqkit)
        assert int(df2["num_seqs"].iloc[0]) != int(df1["num_seqs"].iloc[0])

    def test_unstable_batch_is_not_cached(self, tmp_path):
        seqkit = _tree(tmp_path, samples=1, batches=1)
        fresh = (tmp_path / "seqkit" / "barcode01" / "batch_stats"
                 / "batch_1.tsv")
        row = ("b.fastq\tFASTQ\tDNA\t50\t25000\t100\t500.0\t900\t300\t500"
               "\t700\t0\t550\t40\t95.0\t90.0\t14.5\t42.0\t0\n")
        fresh.write_text(HEADER + row)  # mtime = now -> unstable
        df1 = qc_loaders._load_seqkit_incremental(seqkit)
        assert int(df1["num_seqs"].iloc[0]) == 100  # only the stable batch
        t = time.time() - 120
        os.utime(fresh, (t, t))
        df2 = qc_loaders._load_seqkit_incremental(seqkit)
        assert int(df2["num_seqs"].iloc[0]) == 150

    def test_cache_registered_for_run_reset(self, tmp_path):
        from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
        seqkit = _tree(tmp_path, samples=1, batches=1)
        qc_loaders._load_seqkit_incremental(seqkit)
        assert seqkit_batch_cache.cache_len() > 0
        clear_all_loader_caches()
        assert seqkit_batch_cache.cache_len() == 0


class TestLatestBatchPathMemo:
    """load_kraken_latest_batch must not glob every batch file per poll.

    At 96 barcodes x 300 batches the per-sample-per-poll globs enumerate
    28,800 paths with two regex passes each (round-3 audit). Adding a
    file to a directory bumps the directory's mtime on POSIX, so the
    winning path can be memoized on the (kraken_dir, batch_dir) mtimes.
    """

    def _tree(self, tmp_path, batches=3):
        bdir = tmp_path / "kraken2" / "barcode01" / "batch_reports"
        bdir.mkdir(parents=True)
        report = ("100.00\t100\t10\tR\t1\troot\n"
                  " 10.00\t50\t50\tS\t101\tSpecies testus\n")
        t = time.time() - 120
        for b in range(batches):
            p = bdir / f"batch_{b}.kraken2.report.txt"
            p.write_text(report)
            os.utime(p, (t, t))
        os.utime(bdir, (t, t))
        os.utime(tmp_path / "kraken2", (t, t))
        return tmp_path

    def _count_globs(self, fn, *args):
        import glob as glob_module
        calls = {"n": 0}
        orig = glob_module.glob

        def counting(*a, **kw):
            calls["n"] += 1
            return orig(*a, **kw)

        with patch.object(glob_module, "glob", counting):
            result = fn(*args)
        return calls["n"], result

    def test_repeat_call_does_not_reglob(self, tmp_path):
        from nanometa_live.core.utils import classification_loaders as cl
        self._tree(tmp_path)
        cl.load_kraken_latest_batch(str(tmp_path), "barcode01")
        n, df = self._count_globs(
            cl.load_kraken_latest_batch, str(tmp_path), "barcode01")
        assert n == 0, "unchanged batch dirs must be served from the memo"
        assert not df.empty

    def test_new_batch_invalidates_the_memo(self, tmp_path):
        from nanometa_live.core.utils import classification_loaders as cl
        self._tree(tmp_path)
        df1 = cl.load_kraken_latest_batch(str(tmp_path), "barcode01")
        bdir = tmp_path / "kraken2" / "barcode01" / "batch_reports"
        p = bdir / "batch_9.kraken2.report.txt"
        p.write_text("100.00\t900\t90\tR\t1\troot\n"
                     " 10.00\t500\t500\tS\t101\tSpecies testus\n")
        t = time.time() - 60
        os.utime(p, (t, t))
        # A new file bumps the dir mtime; make it explicit for filesystems
        # with coarse timestamps.
        os.utime(bdir, (t, t))
        df2 = cl.load_kraken_latest_batch(str(tmp_path), "barcode01")
        assert int(df2["cumul_reads"].iloc[0]) == 900
        assert int(df1["cumul_reads"].iloc[0]) == 100
