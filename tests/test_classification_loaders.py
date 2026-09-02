"""
Tests for classification_loaders module.

Covers Kraken2 report parsing edge cases, empty report handling,
and race-condition resilience (file disappearance, partial writes).
"""

import os
import time

import pandas as pd
import pytest

from unittest.mock import patch

from nanometa_live.core.utils.classification_loaders import (
    KRAKEN2_EXPECTED_COLUMNS,
    _is_incremental_layout,
    _is_standard_report,
    _parse_kraken2_report,
    _parse_kraken2_report_uncached,
    _deduplicate_batch_files,
    clear_report_frame_cache,
    load_kraken_data,
    load_kraken_latest_batch,
)


class TestIsStandardReport:
    """The shared cumulative/batch exclusion predicate used to select plain reports."""

    def test_plain_report_accepted(self):
        assert _is_standard_report("barcode01.kraken2.report.txt")
        assert _is_standard_report("sample.kraken2.report.txt")

    def test_cumulative_excluded(self):
        assert not _is_standard_report("sample.cumulative.kraken2.report.txt")

    def test_batch_variants_excluded(self):
        assert not _is_standard_report("sample_batch3.kraken2.report.txt")
        assert not _is_standard_report("sample.batch_3.kraken2.report.txt")
        assert not _is_standard_report("batch_3.kraken2.report.txt")


def _backdate_mtime(path, seconds=5):
    """Set a file's mtime to *seconds* ago so it passes the stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


_VALID_REPORT = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "80.00\t800\t0\tD\t2\t  Bacteria\n"
    "50.00\t500\t500\tS\t562\t    Escherichia coli\n"
)


class TestPerFileParseCache:
    """The per-file parsed-frame cache memoises _parse_kraken2_report on
    (path, mtime, size): the dominant per-poll win is that the same physical
    report parsed by the aggregate, per-sample, and summary loaders is parsed
    once, and a realtime incremental poll re-parses only the changed file."""

    def _write(self, tmp_path, name="r.cumulative.kraken2.report.txt"):
        report = tmp_path / name
        report.write_text(_VALID_REPORT)
        _backdate_mtime(report)
        return str(report)

    def test_unchanged_file_parsed_once(self, tmp_path):
        clear_report_frame_cache()
        path = self._write(tmp_path)
        with patch(
            "nanometa_live.core.utils.classification_loaders._parse_kraken2_report_uncached",
            wraps=_parse_kraken2_report_uncached,
        ) as spy:
            d1 = _parse_kraken2_report(path)
            d2 = _parse_kraken2_report(path)
            d3 = _parse_kraken2_report(path)
        assert spy.call_count == 1  # only the first call hit the parser
        assert len(d1) == 3 and d2 is d1 and d3 is d1

    def test_mtime_change_reparses(self, tmp_path):
        clear_report_frame_cache()
        path = self._write(tmp_path)
        with patch(
            "nanometa_live.core.utils.classification_loaders._parse_kraken2_report_uncached",
            wraps=_parse_kraken2_report_uncached,
        ) as spy:
            _parse_kraken2_report(path)
            new = time.time() - 3
            os.utime(path, (new, new))  # pipeline rewrote the report
            _parse_kraken2_report(path)
        assert spy.call_count == 2  # changed mtime invalidates the entry

    def test_check_stability_false_bypasses_cache(self, tmp_path):
        clear_report_frame_cache()
        path = self._write(tmp_path)
        with patch(
            "nanometa_live.core.utils.classification_loaders._parse_kraken2_report_uncached",
            wraps=_parse_kraken2_report_uncached,
        ) as spy:
            _parse_kraken2_report(path, check_stability=False)
            _parse_kraken2_report(path, check_stability=False)
        assert spy.call_count == 2  # test-only mode never shares a cache entry

    def test_transient_none_not_cached(self, tmp_path):
        """An empty file returns None and is not cached; once it gains content
        (same path, new mtime/size) the next poll parses it for real."""
        clear_report_frame_cache()
        report = tmp_path / "late.cumulative.kraken2.report.txt"
        report.write_text("")
        _backdate_mtime(report)
        assert _parse_kraken2_report(str(report)) is None
        report.write_text(_VALID_REPORT)
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report))
        assert df is not None and len(df) == 3


class TestParseKraken2ReportEdgeCases:
    """Edge cases for _parse_kraken2_report."""

    def test_empty_file_returns_none(self, tmp_path):
        """An empty file should return None."""
        report = tmp_path / "empty.kraken2.report.txt"
        report.write_text("")
        _backdate_mtime(report)
        assert _parse_kraken2_report(str(report), check_stability=False) is None

    def test_wrong_column_count_returns_none(self, tmp_path):
        """A file with wrong number of tab-separated columns should return None."""
        report = tmp_path / "bad_cols.kraken2.report.txt"
        report.write_text("col1\tcol2\tcol3\n")
        _backdate_mtime(report)
        assert _parse_kraken2_report(str(report), check_stability=False) is None

    def test_non_numeric_reads_coerced(self, tmp_path):
        """Non-numeric values in reads column should be coerced and dropped."""
        report = tmp_path / "bad_reads.kraken2.report.txt"
        content = (
            "50.00\t500\t500\tS\t562\t  Escherichia coli\n"
            "50.00\tNaN\tBAD\tS\t1280\t  Staphylococcus aureus\n"
        )
        report.write_text(content)
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report), check_stability=False)
        assert df is not None
        # Only E. coli row should survive; S. aureus has invalid reads/taxid
        assert len(df) >= 1
        assert 562 in df["taxid"].values

    def test_file_disappears_during_parse(self, tmp_path):
        """If a file is removed between exists-check and read, return None."""
        report = tmp_path / "ghost.kraken2.report.txt"
        # File does not exist
        assert _parse_kraken2_report(str(report), check_stability=False) is None

    def test_parent_taxid_hierarchy(self, tmp_path):
        """Verify parent_taxid is built from indentation hierarchy."""
        report = tmp_path / "hierarchy.kraken2.report.txt"
        content = (
            "100.00\t1000\t0\tR\t1\troot\n"
            "80.00\t800\t0\tD\t2\t  Bacteria\n"
            "50.00\t500\t500\tS\t562\t    Escherichia coli\n"
        )
        report.write_text(content)
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report), check_stability=False)
        assert df is not None
        assert len(df) == 3
        # root has no parent
        assert df.iloc[0]["parent_taxid"] == 0
        # Bacteria's parent is root (taxid 1)
        assert df.iloc[1]["parent_taxid"] == 1
        # E. coli's parent is Bacteria (taxid 2)
        assert df.iloc[2]["parent_taxid"] == 2

    def test_single_row_report(self, tmp_path):
        """A single-row report should parse correctly."""
        report = tmp_path / "single.kraken2.report.txt"
        content = "100.00\t1000\t1000\tU\t0\tunclassified\n"
        report.write_text(content)
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report), check_stability=False)
        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["taxid"] == 0


class TestDeduplicateBatchFiles:
    """Tests for _deduplicate_batch_files."""

    def test_empty_list(self):
        assert _deduplicate_batch_files([]) == []

    def test_no_batch_pattern(self):
        """Files without batch pattern should all be kept."""
        files = ["/path/sample1.kraken2.report.txt", "/path/sample2.kraken2.report.txt"]
        result = _deduplicate_batch_files(files)
        assert len(result) == 2

    def test_deduplicates_same_batch(self):
        """Same (sample, batch) from different dirs should be deduplicated."""
        files = [
            "/results/kraken2/sample1_batch0.kraken2.report.txt",
            "/results/kraken2/sample1/batch_reports/sample1_batch0.kraken2.report.txt",
        ]
        result = _deduplicate_batch_files(files)
        assert len(result) == 1
        # Should prefer batch_reports/
        assert "batch_reports" in result[0]

    def test_different_batches_kept(self):
        """Different batch numbers should all be kept."""
        files = [
            "/results/kraken2/sample1_batch0.kraken2.report.txt",
            "/results/kraken2/sample1_batch1.kraken2.report.txt",
            "/results/kraken2/sample1_batch2.kraken2.report.txt",
        ]
        result = _deduplicate_batch_files(files)
        assert len(result) == 3


class TestLoadKrakenDataRaceConditions:
    """Tests for load_kraken_data handling of race conditions and edge cases."""

    def test_missing_kraken_dir(self, tmp_path):
        """Missing kraken2/ directory should return empty DataFrame."""
        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 0
        assert list(df.columns) == KRAKEN2_EXPECTED_COLUMNS

    def test_empty_kraken_dir(self, tmp_path):
        """Empty kraken2/ directory should return empty DataFrame."""
        (tmp_path / "kraken2").mkdir()
        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 0

    def test_all_empty_reports(self, tmp_path):
        """If all report files are empty, return empty DataFrame."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        for name in ("s1.kraken2.report.txt", "s2.kraken2.report.txt"):
            p = kraken_dir / name
            p.write_text("")
            _backdate_mtime(p)

        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 0

    def test_sample_not_found(self, tmp_path):
        """Requesting a non-existent sample should return empty DataFrame."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        df = load_kraken_data(str(tmp_path), sample="nonexistent_barcode")
        assert df is not None
        assert len(df) == 0

    def test_cumulative_preferred_over_standard(self, tmp_path):
        """Cumulative reports should be preferred over standard reports."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        # Standard report with 100 reads
        standard = kraken_dir / "sample1.kraken2.report.txt"
        standard.write_text("100.00\t100\t100\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(standard)

        # Cumulative report with 500 reads (should be preferred)
        cumul = kraken_dir / "sample1.cumulative.kraken2.report.txt"
        cumul.write_text("100.00\t500\t500\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(cumul)

        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None
        assert len(df) == 1
        # Should have loaded the cumulative report (500 reads)
        assert df.iloc[0]["reads"] == 500


# ---------------------------------------------------------------------------
# Incremental vs legacy batch-report dispatch
# ---------------------------------------------------------------------------


def _write_batch_report(path, root_reads: int, species_taxid: int, species_name: str):
    """Write a minimal Kraken2 report containing root and one species row."""
    content = (
        f"100.00\t{root_reads}\t0\tR\t1\troot\n"
        f"100.00\t{root_reads}\t0\tD\t2\t  Bacteria\n"
        f"100.00\t{root_reads}\t{root_reads}\tS\t{species_taxid}\t    {species_name}\n"
    )
    path.write_text(content)
    _backdate_mtime(path)


def _build_incremental_layout(kraken_dir, sample: str, batch_reads, *, stats_marker=True):
    """Create a v1.5 incremental layout for *sample* with the given per-batch read counts.

    Each batch report contains only that batch's reads (a delta). With
    ``stats_marker=True`` a matching ``stats/batch_N_report_stats.json`` is
    written as well; ``stats_marker=False`` reproduces the window nanometanf
    leaves open on a live run, where KRAKEN2_OUTPUT_MERGER has published the
    batch report but KRAKEN2_REPORT_GENERATOR has not yet published the
    stats file (round-4 audit, finding H27).
    """
    sample_dir = kraken_dir / sample
    batch_reports = sample_dir / "batch_reports"
    stats_dir = sample_dir / "stats"
    batch_reports.mkdir(parents=True)
    if stats_marker:
        stats_dir.mkdir(parents=True)

    species_for_batch = [
        (562, "Escherichia coli"),
        (1639, "Listeria monocytogenes"),
        (1280, "Staphylococcus aureus"),
        (485, "Neisseria gonorrhoeae"),
    ]

    for idx, reads in enumerate(batch_reads):
        species_taxid, species_name = species_for_batch[idx % len(species_for_batch)]
        report = batch_reports / f"batch_{idx}.kraken2.report.txt"
        _write_batch_report(report, reads, species_taxid, species_name)

        if not stats_marker:
            continue
        stats_file = stats_dir / f"batch_{idx}_report_stats.json"
        stats_file.write_text(
            f'{{"sample_id": "{sample}", "batch_id": {idx}, "total_reads": {reads}}}'
        )
        _backdate_mtime(stats_file)


def _build_legacy_batch_layout(kraken_dir, sample: str, snapshot_reads):
    """Create a flat legacy layout where each batch is a CUMULATIVE snapshot.

    No ``stats/`` subdirectory is created; ``_is_incremental_layout``
    therefore treats this as the legacy non-incremental flow and selects
    the highest-numbered batch only.
    """
    for idx, reads in enumerate(snapshot_reads):
        report = kraken_dir / f"{sample}_batch{idx}.kraken2.report.txt"
        _write_batch_report(report, reads, 562, "Escherichia coli")


class TestIsIncrementalLayout:
    """Tests for the layout-detection helper."""

    def test_no_kraken_dir_returns_false(self, tmp_path):
        assert _is_incremental_layout(str(tmp_path / "missing")) is False

    def test_flat_layout_returns_false(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        # Flat cumulative report - no per-sample stats subdirectory
        (kraken_dir / "sample1.cumulative.kraken2.report.txt").write_text(
            "100.00\t500\t500\tS\t562\t  Escherichia coli\n"
        )
        assert _is_incremental_layout(str(kraken_dir)) is False

    def test_incremental_layout_returns_true(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_incremental_layout(kraken_dir, "barcode01", batch_reads=[59, 18])
        assert _is_incremental_layout(str(kraken_dir)) is True
        assert _is_incremental_layout(str(kraken_dir), "barcode01") is True

    def test_incremental_for_other_sample_only(self, tmp_path):
        """Restricting to a sample with no stats/ should return False."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_incremental_layout(kraken_dir, "barcode01", batch_reads=[10])
        # barcode02 has no stats directory
        (kraken_dir / "barcode02").mkdir()
        assert _is_incremental_layout(str(kraken_dir), "barcode02") is False

    def test_batch_reports_without_stats_marker_is_incremental(self, tmp_path):
        """A report under ``<sample>/batch_reports/`` is a delta by construction.

        nanometanf publishes ``batch_reports/`` only from the incremental
        flow, and the ``stats/batch_N_report_stats.json`` marker comes from a
        later process. On run R1 of the round-4 audit every batch-tier tick
        fell into that window, so the detector must not depend on the marker.
        """
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_incremental_layout(
            kraken_dir, "barcode01", batch_reads=[10, 20], stats_marker=False
        )
        assert not (kraken_dir / "barcode01" / "stats").exists()
        assert _is_incremental_layout(str(kraken_dir), "barcode01") is True
        assert _is_incremental_layout(str(kraken_dir)) is True

    def test_empty_batch_reports_dir_is_not_evidence(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        (kraken_dir / "barcode01" / "batch_reports").mkdir(parents=True)
        assert _is_incremental_layout(str(kraken_dir), "barcode01") is False


class TestLoadKrakenDataIncrementalLayout:
    """Per-sample loader behaviour under incremental vs legacy batch layouts."""

    def test_incremental_layout_sums_batch_deltas(self, tmp_path):
        """Each batch report is a delta; loader must SUM across batches."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        # Reproduces the run2_D scenario: 59 + 18 + 0 = 77 cumulative reads.
        _build_incremental_layout(
            kraken_dir, "combined_sample", batch_reads=[59, 18, 0]
        )

        df = load_kraken_data(str(tmp_path), sample="combined_sample")
        assert not df.empty
        root = df[df["taxid"] == 1]
        assert not root.empty
        # Root cumulative reads must sum to 77, not 18 (highest batch alone)
        # and not 59 (first batch alone).
        assert int(root.iloc[0]["cumul_reads"]) == 77

    def test_incremental_layout_distinct_taxa_preserved(self, tmp_path):
        """Different species across batches should all appear in the merged result."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        # batch_0 -> E. coli (562), batch_1 -> L. monocytogenes (1639)
        _build_incremental_layout(
            kraken_dir, "barcode01", batch_reads=[40, 30]
        )
        df = load_kraken_data(str(tmp_path), sample="barcode01")
        taxids = set(df["taxid"].astype(int).tolist())
        assert 562 in taxids
        assert 1639 in taxids
        # Total reads = 40 + 30 = 70 spread across both species
        assert int(df["reads"].sum()) == 70

    def test_legacy_layout_uses_highest_batch_only(self, tmp_path):
        """Flat ``{sample}_batch{N}`` snapshots: keep the highest only."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        # Legacy flow writes a cumulative snapshot per batch: batch1 already
        # contains batch0's reads, so the loader must pick the highest only.
        _build_legacy_batch_layout(
            kraken_dir, "sample1", snapshot_reads=[100, 200, 350]
        )

        df = load_kraken_data(str(tmp_path), sample="sample1")
        assert not df.empty
        root = df[df["taxid"] == 1]
        assert int(root.iloc[0]["cumul_reads"]) == 350

    def test_incremental_layout_all_samples_branch(self, tmp_path):
        """Aggregate across samples should also sum incremental deltas."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_incremental_layout(kraken_dir, "barcode01", batch_reads=[10, 20])
        _build_incremental_layout(kraken_dir, "barcode02", batch_reads=[5, 7])

        df = load_kraken_data(str(tmp_path), sample="All Samples")
        assert not df.empty
        root = df[df["taxid"] == 1]
        # Total = 10 + 20 + 5 + 7 = 42
        assert int(root.iloc[0]["cumul_reads"]) == 42

    def test_batch_reports_before_stats_marker_sum_deltas(self, tmp_path):
        """H27: the dashboard showed one batch's reads while the marker lagged.

        Live measurement (R1, 22:54:13 -> 22:54:15): sample ``unclassified``
        had batch reports of 288, 326 and 324 reads and no stats marker yet;
        the loader served exactly 326, then exactly 324, for a sample whose
        batches total 938. The per-sample and aggregate paths must both sum.
        """
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_incremental_layout(
            kraken_dir, "unclassified", batch_reads=[288, 326, 324],
            stats_marker=False,
        )
        _build_incremental_layout(
            kraken_dir, "barcode05", batch_reads=[288, 320], stats_marker=False
        )

        df = load_kraken_data(str(tmp_path), sample="unclassified")
        assert int(df[df["taxid"] == 1].iloc[0]["cumul_reads"]) == 938

        agg = load_kraken_data(str(tmp_path), sample="All Samples")
        assert int(agg[agg["taxid"] == 1].iloc[0]["cumul_reads"]) == 938 + 608


class TestLoadKrakenLatestBatchSemantics:
    """``load_kraken_latest_batch`` should return the most recent batch only."""

    def test_incremental_returns_latest_delta(self, tmp_path):
        """Incremental mode: latest batch holds only that batch's reads."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_incremental_layout(
            kraken_dir, "barcode01", batch_reads=[59, 18]
        )
        df = load_kraken_latest_batch(str(tmp_path), "barcode01")
        assert not df.empty
        root = df[df["taxid"] == 1]
        # Highest-numbered batch (batch_1) carries 18 reads
        assert int(root.iloc[0]["cumul_reads"]) == 18

    def test_legacy_returns_latest_snapshot(self, tmp_path):
        """Legacy mode: latest batch is a cumulative snapshot of all reads."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_legacy_batch_layout(
            kraken_dir, "sample1", snapshot_reads=[100, 200, 350]
        )
        df = load_kraken_latest_batch(str(tmp_path), "sample1")
        assert not df.empty
        root = df[df["taxid"] == 1]
        assert int(root.iloc[0]["cumul_reads"]) == 350


class TestLoadKrakenDataParseLock:
    """The per-key parse lock must serialize concurrent miss-then-parse callers.

    Closes the P0-G01 thundering-herd race documented in
    docs/audit-2026-04-28-throughput-gui.md: when N callbacks all miss the
    mtime + TTL caches at the same instant (because kraken2/ mtime
    advanced since their previous tick), only the first should perform
    the full parse; the others should wait briefly and take the cached
    result.
    """

    def test_concurrent_miss_serializes_to_one_parse(self, tmp_path, monkeypatch):
        """Eight threads racing a cold cache must produce exactly one parse.

        The test wraps the internal ``_parse_kraken_data_uncached`` helper
        so we can count invocations. With the per-key lock in place the
        first thread to win the lock parses; subsequent threads find the
        result already cached and return without re-entering the helper.
        """
        import threading
        from nanometa_live.core.utils import classification_loaders as cl
        from nanometa_live.core.utils import loader_utils

        # Build a minimal kraken2 dir with one cumulative report so the
        # parse path has actual work to do.
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        report = kraken_dir / "barcode01.cumulative.kraken2.report.txt"
        _write_batch_report(report, root_reads=100, species_taxid=562,
                            species_name="Escherichia coli")

        # Reset module-level caches so the test starts cold.
        with loader_utils._cache_lock:
            loader_utils._kraken_cache.clear()
            loader_utils._file_mtimes.clear()
        with loader_utils._parse_locks_lock:
            loader_utils._parse_locks.clear()

        parse_count = {"n": 0}
        original_parse = cl._parse_kraken_data_uncached

        def counting_parse(*args, **kwargs):
            parse_count["n"] += 1
            # Simulate a slow parse so the race window is real.
            import time
            time.sleep(0.05)
            return original_parse(*args, **kwargs)

        monkeypatch.setattr(cl, "_parse_kraken_data_uncached", counting_parse)

        results = []
        def worker():
            results.append(cl.load_kraken_data(str(tmp_path), "All Samples"))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8, "all 8 threads must produce a result"
        assert all(not df.empty for df in results), "all 8 must get the parsed df"
        assert parse_count["n"] == 1, (
            f"expected exactly one parse under per-key lock, got {parse_count['n']}"
        )


class TestLoadKrakenDataFlatLayout:
    """Regression tests for ``per_file`` and ``single_sample`` modes
    where nanometanf emits Kraken2 reports flat under ``kraken2/``
    rather than nested under ``kraken2/<sample>/``.
    """

    def _clear_caches(self):
        from nanometa_live.core.utils import loader_utils
        with loader_utils._cache_lock:
            loader_utils._kraken_cache.clear()
            loader_utils._file_mtimes.clear()

    def test_all_samples_flat_layout(self, tmp_path):
        """All-samples scan must find reports that sit flat in
        ``kraken2/`` (per_file or single_sample emission)."""
        self._clear_caches()
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        for sample_name, count in (("barcode01_chunk_0001", 100), ("barcode01_chunk_0002", 200)):
            report = kraken_dir / f"{sample_name}.kraken2.report.txt"
            report.write_text(f"100.00\t{count}\t{count}\tS\t562\t  Escherichia coli\n")
            _backdate_mtime(report)

        df = load_kraken_data(str(tmp_path), sample=None)
        assert df is not None and not df.empty
        assert int(df.loc[df["taxid"] == 562, "reads"].iloc[0]) == 300

    def test_per_sample_flat_layout(self, tmp_path):
        """Per-sample lookup must find a flat ``<sample>.kraken2.report.txt``
        when no ``<sample>/`` subdirectory exists."""
        self._clear_caches()
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        report = kraken_dir / "single_run.kraken2.report.txt"
        report.write_text("100.00\t42\t42\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(report)

        df = load_kraken_data(str(tmp_path), sample="single_run")
        assert df is not None and not df.empty
        assert int(df.iloc[0]["reads"]) == 42

    def test_nested_by_barcode_layout_still_works(self, tmp_path):
        """Guard the existing nested ``kraken2/<sample>/`` layout
        used by ``by_barcode`` mode against the flat-layout fallback
        regressing it."""
        self._clear_caches()
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        for barcode, count in (("barcode01", 10), ("barcode02", 20)):
            sample_dir = kraken_dir / barcode
            sample_dir.mkdir()
            report = sample_dir / f"{barcode}.kraken2.report.txt"
            report.write_text(f"100.00\t{count}\t{count}\tS\t562\t  Escherichia coli\n")
            _backdate_mtime(report)

        df_all = load_kraken_data(str(tmp_path), sample=None)
        assert df_all is not None and not df_all.empty
        assert int(df_all.loc[df_all["taxid"] == 562, "reads"].iloc[0]) == 30

        df_one = load_kraken_data(str(tmp_path), sample="barcode01")
        assert df_one is not None and not df_one.empty
        assert int(df_one.iloc[0]["reads"]) == 10

    def test_legacy_kreport2_extension_ignored(self, tmp_path):
        """The retired ``.kreport2.txt`` suffix from older nanometanf versions
        is no longer read; only ``.kraken2.report.txt`` is recognised."""
        self._clear_caches()
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        report = kraken_dir / "legacy_sample.kreport2.txt"
        report.write_text("100.00\t7\t7\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(report)

        df = load_kraken_data(str(tmp_path), sample="legacy_sample")
        assert df is None or df.empty
class TestEmptyKrakenDirDiagnostics:
    """When the loader returns empty, the warning must list directory state."""

    def test_all_samples_empty_warning_lists_contents(self, tmp_path, caplog):
        from nanometa_live.core.utils import classification_loaders as cl
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        with caplog.at_level("WARNING", logger=""):
            df = cl.load_kraken_data(str(tmp_path))
        assert df.empty
        msg = " ".join(rec.message for rec in caplog.records)
        assert "No Kraken2 reports" in msg
        assert "Patterns tried" in msg
        assert "Files present (0)" in msg

    def test_per_sample_empty_warning_names_sample(self, tmp_path, caplog):
        from nanometa_live.core.utils import classification_loaders as cl
        (tmp_path / "kraken2").mkdir()
        with caplog.at_level("WARNING", logger=""):
            df = cl.load_kraken_data(str(tmp_path), sample="ghost")
        assert df.empty
        msg = " ".join(rec.message for rec in caplog.records)
        assert "sample='ghost'" in msg
        assert "Patterns tried" in msg

    def test_diagnostic_helper_handles_unreadable_dir(self, tmp_path):
        from nanometa_live.core.utils.classification_loaders import (
            _diagnose_empty_kraken_dir,
        )
        msg = _diagnose_empty_kraken_dir(str(tmp_path / "does-not-exist"))
        assert "unreadable" in msg


# ---------------------------------------------------------------------------
# describe_kraken_scan_locations
# ---------------------------------------------------------------------------


class TestDescribeKrakenScanLocations:
    """Documents the loader's scan path for the Analyze-error toast."""

    def test_returns_absolute_path_and_pattern_list(self, tmp_path):
        from nanometa_live.core.utils.classification_loaders import (
            describe_kraken_scan_locations,
        )
        scan = describe_kraken_scan_locations(str(tmp_path))
        assert os.path.isabs(scan["kraken_dir"])
        assert scan["kraken_dir"].endswith("kraken2")
        assert scan["exists"] is False
        assert "*.cumulative.kraken2.report.txt" in scan["patterns"]
        assert "*.kraken2.report.txt" in scan["patterns"]

    def test_exists_flag_true_when_directory_present(self, tmp_path):
        from nanometa_live.core.utils.classification_loaders import (
            describe_kraken_scan_locations,
        )
        (tmp_path / "kraken2").mkdir()
        scan = describe_kraken_scan_locations(str(tmp_path))
        assert scan["exists"] is True

    def test_empty_main_dir_returns_empty_path(self):
        from nanometa_live.core.utils.classification_loaders import (
            describe_kraken_scan_locations,
        )
        scan = describe_kraken_scan_locations("")
        assert scan["kraken_dir"] == ""
        assert scan["exists"] is False
        assert isinstance(scan["patterns"], list)


class TestMixedReadinessAggregate:
    """The "All Samples" aggregate must include every sample even when samples
    sit at different report tiers (audit 2026-08-16, finding L1).

    In a realtime multi-barcode run, barcodes reach the cumulative report at
    staggered times. The report tier (cumulative > standard > batch) must be
    resolved per sample and the results unioned; a directory-wide tier choice
    silently drops every sample still on a lower tier from the aggregate that
    feeds the verdict banner.
    """

    def test_cumulative_and_standard_samples_both_included(self, tmp_path):
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        cumul = kraken_dir / "sample1.cumulative.kraken2.report.txt"
        cumul.write_text("100.00\t500\t500\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(cumul)

        # sample2 is still mid-run: only a standard report exists.
        standard = kraken_dir / "sample2.kraken2.report.txt"
        standard.write_text("100.00\t9999\t9999\tS\t1639\t  Listeria monocytogenes\n")
        _backdate_mtime(standard)

        df = load_kraken_data(str(tmp_path), sample=None)
        taxids = set(df["taxid"].astype(int).tolist())
        assert 562 in taxids, "cumulative-tier sample missing from aggregate"
        assert 1639 in taxids, (
            "standard-tier sample dropped from aggregate because another "
            "sample already has a cumulative report"
        )

    def test_per_sample_tier_priority_preserved(self, tmp_path):
        """A sample with BOTH cumulative and standard must contribute only the
        cumulative counts (no double counting), while a standard-only sibling
        still appears."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        cumul = kraken_dir / "sample1.cumulative.kraken2.report.txt"
        cumul.write_text("100.00\t500\t500\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(cumul)
        stale_standard = kraken_dir / "sample1.kraken2.report.txt"
        stale_standard.write_text("100.00\t100\t100\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(stale_standard)

        standard = kraken_dir / "sample2.kraken2.report.txt"
        standard.write_text("100.00\t50\t50\tS\t1639\t  Listeria monocytogenes\n")
        _backdate_mtime(standard)

        df = load_kraken_data(str(tmp_path), sample=None)
        ecoli = df[df["taxid"] == 562]
        assert int(ecoli.iloc[0]["reads"]) == 500, (
            "sample1 must contribute its cumulative report only, "
            "not cumulative + stale standard"
        )
        assert 1639 in set(df["taxid"].astype(int).tolist())

    def test_standard_and_batch_samples_both_included(self, tmp_path):
        """A sample that has only legacy batch snapshots must still appear in
        the aggregate beside a sample with a standard report."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        standard = kraken_dir / "sample1.kraken2.report.txt"
        standard.write_text("100.00\t500\t500\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(standard)

        # sample2: flat legacy snapshots only; the latest (200) must be used.
        _build_legacy_batch_layout(kraken_dir, "sample2", snapshot_reads=[100, 200])

        df = load_kraken_data(str(tmp_path), sample=None)
        taxids = set(df["taxid"].astype(int).tolist())
        assert 562 in taxids
        root = df[df["taxid"] == 1]
        assert not root.empty, "batch-tier sample dropped from aggregate"
        assert int(root.iloc[0]["cumul_reads"]) == 200

    def test_cumulative_and_incremental_batch_samples_both_included(self, tmp_path):
        """A sample still on incremental batch deltas appears (summed) beside a
        finished cumulative sample."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()

        cumul = kraken_dir / "sample1.cumulative.kraken2.report.txt"
        cumul.write_text("100.00\t500\t500\tS\t562\t  Escherichia coli\n")
        _backdate_mtime(cumul)

        # barcode02: incremental deltas only (batch_0 E. coli 40, batch_1
        # L. monocytogenes 30 per _build_incremental_layout's species cycle).
        _build_incremental_layout(kraken_dir, "barcode02", batch_reads=[40, 30])

        df = load_kraken_data(str(tmp_path), sample=None)
        taxids = set(df["taxid"].astype(int).tolist())
        assert 562 in taxids
        assert 1639 in taxids, "incremental-tier sample dropped from aggregate"
        root = df[df["taxid"] == 1]
        assert int(root.iloc[0]["cumul_reads"]) == 70


class TestNaNCumulReadsFallsBackToReads:
    """A row whose cumul_reads alone fails numeric coercion must stay usable.

    The NaN survived the reads/taxid dropna and then compared False against
    every threshold, so the row silently vanished from per-sample attribution
    and the discovery floor while remaining in the frame (audit 2026-08-16,
    finding L15).
    """

    def test_bad_cumul_value_falls_back_to_reads(self, tmp_path):
        report = tmp_path / "glitch.kraken2.report.txt"
        report.write_text(
            "50.00\t100\t0\tR\t1\troot\n"
            "50.00\tBAD\t100\tS\t562\t  Escherichia coli\n"
        )
        _backdate_mtime(report)
        df = _parse_kraken2_report(str(report))
        assert df is not None
        row = df[df["taxid"] == 562].iloc[0]
        assert not pd.isna(row["cumul_reads"])
        assert int(row["cumul_reads"]) == 100


class TestBatchDedupPrefersSamplePrefixedName:
    """The sample-prefixed tie-break was dead code via a chained comparison.

    `'batch_reports' in fp == 'batch_reports' in existing` parsed as
    `(... in fp) and (fp == 'batch_reports') and (...)`, never true for a
    real path (audit 2026-08-16, finding L16).
    """

    def test_prefixed_name_wins_over_generic_in_same_dir(self):
        generic = "/r/kraken2/s1/batch_reports/batch_0.kraken2.report.txt"
        prefixed = "/r/kraken2/s1/batch_reports/s1_batch0.kraken2.report.txt"
        result = _deduplicate_batch_files([generic, prefixed])
        assert result == [prefixed]

    def test_prefixed_copy_inside_stability_window_yields_to_stable_generic(self, tmp_path):
        """The copy that can be read this poll wins over the one preferred by name.

        nanometanf publishes each batch report twice, byte-identical: the
        merger's ``batch_N`` first, the report generator's ``<sample>_batchN``
        later, and the later copy tends to land together with the sample's
        first cumulative report. Replaying R1 at 22:54:35 showed every sample
        unmeasured for one poll: the tier fallback correctly chose the batch
        tier, then the dedup handed it the fresh copies and nothing parsed.
        """
        bdir = tmp_path / "kraken2" / "s1" / "batch_reports"
        bdir.mkdir(parents=True)
        generic = bdir / "batch_0.kraken2.report.txt"
        prefixed = bdir / "s1_batch0.kraken2.report.txt"
        _write_batch_report(generic, 50, 562, "Escherichia coli")
        _write_batch_report(prefixed, 50, 562, "Escherichia coli")
        now = time.time()
        os.utime(prefixed, (now, now))
        result = _deduplicate_batch_files([str(generic), str(prefixed)])
        assert result == [str(generic)]

    def test_prefixed_copy_wins_once_both_are_stable(self, tmp_path):
        bdir = tmp_path / "kraken2" / "s1" / "batch_reports"
        bdir.mkdir(parents=True)
        generic = bdir / "batch_0.kraken2.report.txt"
        prefixed = bdir / "s1_batch0.kraken2.report.txt"
        _write_batch_report(generic, 50, 562, "Escherichia coli")
        _write_batch_report(prefixed, 50, 562, "Escherichia coli")
        result = _deduplicate_batch_files([str(generic), str(prefixed)])
        assert result == [str(prefixed)]

    def test_loader_reads_the_batch_tier_while_the_prefixed_copies_are_fresh(self, tmp_path):
        """Per-sample and aggregate loads stay measured on the arrival poll."""
        kraken_dir = tmp_path / "kraken2"
        kraken_dir.mkdir()
        _build_incremental_layout(
            kraken_dir, "unclassified", batch_reads=[288, 326, 324], stats_marker=False
        )
        bdir = kraken_dir / "unclassified" / "batch_reports"
        now = time.time()
        for idx in range(3):
            copy = bdir / f"unclassified_batch{idx}.kraken2.report.txt"
            copy.write_bytes((bdir / f"batch_{idx}.kraken2.report.txt").read_bytes())
            os.utime(copy, (now, now))
        fresh_cumulative = kraken_dir / "unclassified.cumulative.kraken2.report.txt"
        _write_batch_report(fresh_cumulative, 938, 562, "Escherichia coli")
        os.utime(fresh_cumulative, (now, now))

        df = load_kraken_data(str(tmp_path), sample="unclassified")
        assert df is not None and not df.empty
        assert int(df[df["taxid"] == 1].iloc[0]["cumul_reads"]) == 938

        agg = load_kraken_data(str(tmp_path), sample="All Samples")
        assert agg is not None and not agg.empty
        assert int(agg[agg["taxid"] == 1].iloc[0]["cumul_reads"]) == 938
