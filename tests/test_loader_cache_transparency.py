"""The loader caches must be transparent.

Every cached result has to equal what an uncached read of the same tree
returns, byte for byte. These tests pin that property directly, because the
per-sample fingerprint scoping and the freshness-epoch shortcut both make the
cache answer without touching the sample's files -- exactly the situations
where a scoping mistake would silently serve stale or cross-contaminated data.

The failure this guards against is not a crash. A cache keyed too narrowly
returns a stale frame and the dashboard shows an old read count, which looks
like a pipeline problem rather than a GUI one.
"""

from __future__ import annotations

import hashlib
import os
import time

import pandas as pd
import pytest

from nanometa_live.core.utils import loader_utils as lu
from nanometa_live.core.utils.classification_loaders import (
    clear_report_frame_cache, load_kraken_data,
)
from nanometa_live.core.utils.loader_utils import check_data_freshness
from nanometa_live.core.utils.qc_loaders import load_seqkit_stats
from nanometa_live.core.utils.sample_detector import (
    get_available_samples, invalidate_sample_cache,
)

pytestmark = pytest.mark.unit

SAMPLES = ["barcode01", "barcode02", "barcode03"]


def _reset_all() -> None:
    lu.clear_data_cache()
    lu._last_freshness_fingerprint = ""
    clear_report_frame_cache()
    invalidate_sample_cache()


def _backdate(root: str, age: float = 5.0) -> None:
    """Age files past the stability threshold so loaders accept them."""
    stamp = time.time() - age
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            os.utime(os.path.join(dirpath, name), (stamp, stamp))


def _report(reads_per_species: int) -> str:
    total = reads_per_species * 3
    unclassified = 100
    lines = [
        f"{unclassified / (total + unclassified) * 100:.2f}\t{unclassified}"
        f"\t{unclassified}\tU\t0\tunclassified",
        f"{total / (total + unclassified) * 100:.2f}\t{total}\t0\tR\t1\troot",
        f"50.00\t{total}\t0\tD\t2\t  Bacteria",
        f"50.00\t{total}\t0\tG\t10\t    Genus_a",
    ]
    for i in range(3):
        lines.append(
            f"16.00\t{reads_per_species}\t{reads_per_species}\tS\t{100 + i}"
            f"\t      Genus_a species_{i}"
        )
    return "\n".join(lines) + "\n"


def _seqkit_tsv(num_seqs: int) -> str:
    header = (
        "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\t"
        "Q1\tQ2\tQ3\tsum_gap\tN50\tN50_num\tQ20(%)\tQ30(%)\tAvgQual\tGC(%)"
    )
    row = (
        f"s.fastq\tFASTQ\tDNA\t{num_seqs}\t{num_seqs * 1000}\t200\t1000\t4000\t"
        f"750\t1000\t1500\t0\t1000\t{num_seqs // 2}\t95.0\t80.0\t14.0\t50.0"
    )
    return f"{header}\n{row}\n"


@pytest.fixture
def tree(tmp_path):
    """A three-sample flat results tree."""
    kraken = tmp_path / "kraken2"
    seqkit = tmp_path / "seqkit"
    kraken.mkdir()
    seqkit.mkdir()
    for i, sample in enumerate(SAMPLES, start=1):
        (kraken / f"{sample}.kraken2.report.txt").write_text(_report(1000 * i))
        (seqkit / f"{sample}.tsv").write_text(_seqkit_tsv(500 * i))
    (tmp_path / "validation").mkdir()
    _backdate(str(tmp_path))
    _reset_all()
    yield tmp_path
    _reset_all()


def _digest(df: pd.DataFrame) -> str:
    """Stable hash over the full frame, including the derived parent_taxid."""
    if df.empty:
        return "EMPTY"
    ordered = df.sort_values(list(df.columns)).reset_index(drop=True)
    return hashlib.sha256(
        ordered.to_csv(index=True).encode()
    ).hexdigest()


class TestCachedEqualsUncached:
    def test_kraken_per_sample_matches_cold_read(self, tree):
        """A warm per-sample load equals the same load from a cold cache."""
        main_dir = str(tree)
        warm = {}
        check_data_freshness(main_dir)
        for sample in SAMPLES:
            load_kraken_data(main_dir, sample)  # populate
        for sample in SAMPLES:
            warm[sample] = _digest(load_kraken_data(main_dir, sample))

        for sample in SAMPLES:
            _reset_all()
            cold = _digest(load_kraken_data(main_dir, sample))
            assert cold == warm[sample], (
                f"{sample}: cached frame differs from an uncached read"
            )

    def test_samples_do_not_share_results(self, tree):
        """Per-sample entries must stay distinct.

        The three samples have deliberately different read counts, so a cache
        key or fingerprint scope that collided would show up as equal digests.
        """
        main_dir = str(tree)
        check_data_freshness(main_dir)
        digests = {s: _digest(load_kraken_data(main_dir, s)) for s in SAMPLES}
        assert len(set(digests.values())) == len(SAMPLES), (
            f"samples returned identical frames: {digests}"
        )

    def test_aggregate_differs_from_single_sample(self, tree):
        main_dir = str(tree)
        check_data_freshness(main_dir)
        aggregate = _digest(load_kraken_data(main_dir, None))
        single = _digest(load_kraken_data(main_dir, SAMPLES[0]))
        assert aggregate != single

    def test_seqkit_cached_matches_cold_read(self, tree):
        main_dir = str(tree)
        check_data_freshness(main_dir)
        load_seqkit_stats(main_dir, SAMPLES[0])
        warm = _digest(load_seqkit_stats(main_dir, SAMPLES[0]))
        _reset_all()
        cold = _digest(load_seqkit_stats(main_dir, SAMPLES[0]))
        assert warm == cold


class TestInvalidation:
    def test_changed_sample_is_reloaded(self, tree):
        """A sample whose report advances must not keep serving the old frame."""
        main_dir = str(tree)
        target = SAMPLES[1]
        check_data_freshness(main_dir)
        before = _digest(load_kraken_data(main_dir, target))

        report = tree / "kraken2" / f"{target}.kraken2.report.txt"
        report.write_text(_report(99_000))
        _backdate(str(tree))
        # The poll gate runs first in the real app and is what advances the
        # freshness epoch; without it the shortcut would legitimately hold.
        check_data_freshness(main_dir)

        after = _digest(load_kraken_data(main_dir, target))
        assert after != before, "changed report still returned the cached frame"

    def test_untouched_samples_keep_their_own_data(self, tree):
        """One sample advancing must not corrupt the others.

        This is the cross-contamination direction of the narrowed fingerprint
        scope: sample 1 changing must invalidate sample 1 and nothing else,
        and the others must still return their own distinct data.
        """
        main_dir = str(tree)
        check_data_freshness(main_dir)
        before = {s: _digest(load_kraken_data(main_dir, s)) for s in SAMPLES}

        report = tree / "kraken2" / f"{SAMPLES[0]}.kraken2.report.txt"
        report.write_text(_report(77_000))
        _backdate(str(tree))
        check_data_freshness(main_dir)

        after = {s: _digest(load_kraken_data(main_dir, s)) for s in SAMPLES}
        assert after[SAMPLES[0]] != before[SAMPLES[0]]
        for sample in SAMPLES[1:]:
            assert after[sample] == before[sample]

    def test_new_sample_is_detected(self, tree):
        """A sample appearing mid-run must show up in the aggregate."""
        main_dir = str(tree)
        check_data_freshness(main_dir)
        before = _digest(load_kraken_data(main_dir, None))

        (tree / "kraken2" / "barcode04.kraken2.report.txt").write_text(
            _report(4242)
        )
        _backdate(str(tree))
        invalidate_sample_cache()
        check_data_freshness(main_dir)

        assert "barcode04" in get_available_samples(main_dir)
        assert _digest(load_kraken_data(main_dir, None)) != before


class TestFreshnessEpochShortcut:
    def test_shortcut_is_inactive_without_polling(self, tree):
        """Callers that never poll stay on the unconditional path check.

        The CLI, report generation and the test suite itself load without
        ever calling check_data_freshness. For them the epoch stays 0 and the
        mtime cache must keep validating against the files themselves, or a
        one-shot process would serve indefinitely stale data.
        """
        main_dir = str(tree)
        _reset_all()
        lu._freshness_epoch = 0

        target = SAMPLES[0]
        before = _digest(load_kraken_data(main_dir, target))
        assert lu._freshness_epoch == 0, (
            "loading data must not advance the epoch on its own"
        )

        (tree / "kraken2" / f"{target}.kraken2.report.txt").write_text(
            _report(55_000)
        )
        _backdate(str(tree))

        after = _digest(load_kraken_data(main_dir, target))
        assert after != before, (
            "without a poll, the cache must re-validate against the files"
        )

    def test_epoch_advances_only_when_the_tree_changes(self, tree):
        main_dir = str(tree)
        _reset_all()
        check_data_freshness(main_dir)
        first = lu._freshness_epoch
        assert first > 0

        check_data_freshness(main_dir)
        assert lu._freshness_epoch == first, "quiet poll advanced the epoch"

        (tree / "kraken2" / f"{SAMPLES[0]}.kraken2.report.txt").write_text(
            _report(31_000)
        )
        _backdate(str(tree))
        check_data_freshness(main_dir)
        assert lu._freshness_epoch > first, "changed tree did not advance the epoch"
