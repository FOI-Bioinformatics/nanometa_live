"""Tests for two realtime-path validation parser modules.

Covers:
- ``core/parsers/minimap2_stats.py`` — individual ``*.minimap2_stats.json``
  parsing and aggregation (the path that keeps the Coverage sub-tab populated
  mid-realtime run).
- ``core/parsers/validation_batch.py`` — per-batch result selection and
  ``batch_id`` parsing for the realtime drill-down view.
"""

import json
from pathlib import Path

from nanometa_live.core.parsers.blast_validation_parser import (
    ValidationParser,
    ValidationStatus,
)
from nanometa_live.core.parsers.minimap2_stats import (
    collect_minimap2_results,
    minimap2_stats_dirs,
    parse_minimap2_stats_json,
)
from nanometa_live.core.parsers.validation_batch import collect_batch_results


def _write_mm2_stats(path: Path, **overrides) -> Path:
    """Write a well-formed ``*.minimap2_stats.json`` and return its path."""
    data = {
        "sample_id": "barcode01",
        "taxid": 1280,
        "species": "Staphylococcus aureus",
        "total_reads": 200,
        "mapped_reads": 180,
        "hit_rate": 0.9,
        "avg_identity": 97.5,
        "avg_coverage": 85.0,
        "avg_mapq": 55.0,
        "ref_name": "NZ_CP012345.1",
        "timestamp": "2026-06-02T12:00:00Z",
    }
    data.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def _write_blast_tsv(path: Path, n_hits: int = 3) -> Path:
    """Write a minimal BLAST outfmt-6 (15-col) tsv with ``n_hits`` rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # qseqid sseqid pident length mismatch gapopen qstart qend
    # sstart send evalue bitscore qlen slen qcovs
    lines = []
    for i in range(n_hits):
        lines.append(
            f"read{i}\tNZ_CP012345.1\t98.0\t1000\t10\t1\t1\t1000"
            f"\t1\t1000\t0.0\t1800\t1000\t5000\t100"
        )
    path.write_text("\n".join(lines) + "\n")
    return path


class TestParseMinimap2StatsJson:
    """Single-file ``parse_minimap2_stats_json`` behaviour."""

    def test_wellformed_json_returns_structured_result(self, tmp_path: Path) -> None:
        stats = _write_mm2_stats(tmp_path / "barcode01_taxid1280.minimap2_stats.json")

        result = parse_minimap2_stats_json(stats)

        assert result is not None
        assert result.sample_id == "barcode01"
        assert result.taxid == 1280
        assert result.species == "Staphylococcus aureus"
        assert result.total_reads == 200
        assert result.validated_reads == 180  # from mapped_reads
        assert result.validation_method == "minimap2"
        assert result.reference_accession == "NZ_CP012345.1"
        # hit_rate 0.9 (<=1.0) is rescaled to a percent.
        assert result.percent_validated == 90.0
        assert result.percent_identity_mean == 97.5
        assert result.coverage_breadth == 85.0
        assert result.avg_mapq == 55.0
        # 90% validated with 97.5 identity -> CONFIRMED.
        assert result.status == ValidationStatus.CONFIRMED

    def test_hit_rate_already_percent_is_passed_through(self, tmp_path: Path) -> None:
        stats = _write_mm2_stats(
            tmp_path / "barcode01_taxid1280.minimap2_stats.json", hit_rate=72.0
        )

        result = parse_minimap2_stats_json(stats)

        assert result is not None
        # hit_rate > 1.0 is treated as an already-percent value, not rescaled.
        assert result.percent_validated == 72.0
        assert result.status == ValidationStatus.PARTIAL

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.minimap2_stats.json"

        assert parse_minimap2_stats_json(missing) is None

    def test_malformed_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.minimap2_stats.json"
        bad.write_text("{ this is not valid json ")

        assert parse_minimap2_stats_json(bad) is None

    def test_missing_taxid_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "notaxid.minimap2_stats.json"
        bad.write_text(json.dumps({"sample_id": "barcode01", "mapped_reads": 5}))

        assert parse_minimap2_stats_json(bad) is None

    def test_invalid_taxid_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "badtaxid.minimap2_stats.json"
        bad.write_text(json.dumps({"sample_id": "barcode01", "taxid": "not-a-number"}))

        assert parse_minimap2_stats_json(bad) is None

    def test_partial_json_defaults_applied(self, tmp_path: Path) -> None:
        """Only taxid present -> numeric fields default, status NO_DATA."""
        partial = tmp_path / "partial.minimap2_stats.json"
        partial.write_text(json.dumps({"taxid": 1280}))

        result = parse_minimap2_stats_json(partial)

        assert result is not None
        assert result.taxid == 1280
        assert result.sample_id == ""
        assert result.total_reads == 0
        assert result.validated_reads == 0
        assert result.percent_validated == 0.0
        assert result.status == ValidationStatus.NO_DATA


class TestMinimap2StatsDirs:
    """``minimap2_stats_dirs`` candidate-directory resolution."""

    def test_canonical_validation_minimap2_dir_found(self, tmp_path: Path) -> None:
        mm2 = tmp_path / "validation" / "minimap2"
        mm2.mkdir(parents=True)

        dirs = minimap2_stats_dirs(tmp_path, None)

        assert mm2 in dirs

    def test_nonexistent_dirs_excluded(self, tmp_path: Path) -> None:
        # Nothing created on disk.
        assert minimap2_stats_dirs(tmp_path, None) == []

    def test_validation_dir_variants_deduped(self, tmp_path: Path) -> None:
        mm2 = tmp_path / "validation" / "minimap2"
        mm2.mkdir(parents=True)
        validation_dir = tmp_path / "validation"

        dirs = minimap2_stats_dirs(tmp_path, validation_dir)

        # Same resolved directory reached two ways -> de-duplicated to one entry.
        assert dirs.count(mm2) == 1


class TestCollectMinimap2Results:
    """End-to-end scan via ``collect_minimap2_results``."""

    def test_collects_from_validation_minimap2(self, tmp_path: Path) -> None:
        mm2 = tmp_path / "validation" / "minimap2"
        _write_mm2_stats(mm2 / "barcode01_taxid1280.minimap2_stats.json")

        results = collect_minimap2_results(tmp_path, None, None, None, existing=[])

        assert len(results) == 1
        assert results[0].sample_id == "barcode01"
        assert results[0].taxid == 1280

    def test_skips_duplicate_minimap2_already_present(self, tmp_path: Path) -> None:
        mm2 = tmp_path / "validation" / "minimap2"
        _write_mm2_stats(mm2 / "barcode01_taxid1280.minimap2_stats.json")
        existing = collect_minimap2_results(tmp_path, None, None, None, existing=[])

        # Re-scanning while passing the prior result as existing yields nothing new.
        again = collect_minimap2_results(tmp_path, None, None, None, existing=existing)

        assert again == []

    def test_filters_by_sample_and_taxid(self, tmp_path: Path) -> None:
        mm2 = tmp_path / "validation" / "minimap2"
        _write_mm2_stats(mm2 / "barcode01_taxid1280.minimap2_stats.json")
        _write_mm2_stats(
            mm2 / "barcode02_taxid632.minimap2_stats.json",
            sample_id="barcode02",
            taxid=632,
        )

        only_b2 = collect_minimap2_results(tmp_path, None, "barcode02", 632, existing=[])

        assert len(only_b2) == 1
        assert only_b2[0].sample_id == "barcode02"
        assert only_b2[0].taxid == 632

    def test_taxid_filter_same_sample(self, tmp_path: Path) -> None:
        """Same sample, two taxids -> taxid filter selects one (line for taxid skip)."""
        mm2 = tmp_path / "validation" / "minimap2"
        _write_mm2_stats(mm2 / "barcode01_taxid1280.minimap2_stats.json", taxid=1280)
        _write_mm2_stats(mm2 / "barcode01_taxid632.minimap2_stats.json", taxid=632)

        only_632 = collect_minimap2_results(
            tmp_path, None, "barcode01", 632, existing=[]
        )

        assert len(only_632) == 1
        assert only_632[0].taxid == 632

    def test_malformed_file_skipped_not_fatal(self, tmp_path: Path) -> None:
        mm2 = tmp_path / "validation" / "minimap2"
        _write_mm2_stats(mm2 / "barcode01_taxid1280.minimap2_stats.json")
        (mm2 / "broken.minimap2_stats.json").write_text("{ broken ")

        results = collect_minimap2_results(tmp_path, None, None, None, existing=[])

        assert len(results) == 1


class TestCollectBatchResults:
    """Per-batch drill-down selection in ``validation_batch``."""

    def _blast_fn(self, results_dir: Path):
        return ValidationParser(results_dir).parse_blast_tabular

    def _seed_batches(self, results_dir: Path) -> None:
        """Create minimap2 + blast per-batch files for batches 1, 2, 10."""
        mm2 = results_dir / "validation" / "minimap2" / "batch"
        blast = results_dir / "validation" / "blast" / "batch"
        for batch_id in ("1", "2", "10"):
            _write_mm2_stats(
                mm2 / f"barcode01_taxid1280_{batch_id}.minimap2_stats.json",
                # Stamp mapped_reads so batches are distinguishable.
                mapped_reads=int(batch_id),
            )
            _write_blast_tsv(
                blast / f"barcode01_taxid1280_{batch_id}.blast.tsv", n_hits=2
            )

    def test_selects_only_requested_batch(self, tmp_path: Path) -> None:
        self._seed_batches(tmp_path)

        results = collect_batch_results(
            tmp_path, "2", None, None, self._blast_fn(tmp_path)
        )

        # One minimap2 + one blast result for batch 2.
        methods = sorted(r.validation_method for r in results)
        assert methods == ["blast", "minimap2"]
        mm2_result = next(r for r in results if r.validation_method == "minimap2")
        assert mm2_result.validated_reads == 2  # mapped_reads stamped == batch_id

    def test_batch_id_not_lexicographic_collision(self, tmp_path: Path) -> None:
        """Requesting batch '1' must not also pick up batch '10'.

        A naive ``startswith`` / prefix match would conflate 1 and 10; the
        ``_<batch_id>`` suffix anchoring must keep them distinct.
        """
        self._seed_batches(tmp_path)

        batch1 = collect_batch_results(tmp_path, "1", None, None, self._blast_fn(tmp_path))
        batch10 = collect_batch_results(tmp_path, "10", None, None, self._blast_fn(tmp_path))

        mm2_b1 = next(r for r in batch1 if r.validation_method == "minimap2")
        mm2_b10 = next(r for r in batch10 if r.validation_method == "minimap2")
        assert mm2_b1.validated_reads == 1
        assert mm2_b10.validated_reads == 10
        # Exactly one minimap2 result each — no cross-contamination.
        assert sum(r.validation_method == "minimap2" for r in batch1) == 1
        assert sum(r.validation_method == "minimap2" for r in batch10) == 1

    def test_absent_batch_returns_empty(self, tmp_path: Path) -> None:
        self._seed_batches(tmp_path)

        assert collect_batch_results(tmp_path, "99", None, None, self._blast_fn(tmp_path)) == []

    def test_no_batch_dir_returns_empty(self, tmp_path: Path) -> None:
        # No validation/*/batch dirs created at all.
        assert collect_batch_results(tmp_path, "1", None, None, self._blast_fn(tmp_path)) == []

    def test_blast_filename_taxid_parsed(self, tmp_path: Path) -> None:
        self._seed_batches(tmp_path)

        results = collect_batch_results(tmp_path, "1", None, None, self._blast_fn(tmp_path))

        blast_result = next(r for r in results if r.validation_method == "blast")
        assert blast_result.sample_id == "barcode01"
        assert blast_result.taxid == 1280

    def test_filters_by_sample_and_taxid(self, tmp_path: Path) -> None:
        self._seed_batches(tmp_path)
        mm2 = tmp_path / "validation" / "minimap2" / "batch"
        blast = tmp_path / "validation" / "blast" / "batch"
        _write_mm2_stats(
            mm2 / "barcode02_taxid632_1.minimap2_stats.json",
            sample_id="barcode02",
            taxid=632,
        )
        _write_blast_tsv(blast / "barcode02_taxid632_1.blast.tsv")

        # barcode01 batch-1 files (from _seed_batches) must be filtered out by
        # the per-method sample filter.
        only_b2 = collect_batch_results(
            tmp_path, "1", "barcode02", 632, self._blast_fn(tmp_path)
        )

        assert all(r.sample_id == "barcode02" and r.taxid == 632 for r in only_b2)
        assert {r.validation_method for r in only_b2} == {"blast", "minimap2"}

    def test_malformed_filename_skipped(self, tmp_path: Path) -> None:
        """A blast file without ``_taxid`` in the stem is skipped, not fatal."""
        blast = tmp_path / "validation" / "blast" / "batch"
        _write_blast_tsv(blast / "weirdname_1.blast.tsv")

        results = collect_batch_results(tmp_path, "1", None, None, self._blast_fn(tmp_path))

        assert results == []

    def test_taxid_filter_drops_same_sample_other_taxid(self, tmp_path: Path) -> None:
        """Same sample, two taxids in one batch -> taxid filter keeps one.

        Exercises the per-method ``taxid`` filter continue (not the sample one).
        """
        mm2 = tmp_path / "validation" / "minimap2" / "batch"
        blast = tmp_path / "validation" / "blast" / "batch"
        _write_mm2_stats(mm2 / "barcode01_taxid1280_1.minimap2_stats.json", taxid=1280)
        _write_mm2_stats(mm2 / "barcode01_taxid632_1.minimap2_stats.json", taxid=632)
        _write_blast_tsv(blast / "barcode01_taxid1280_1.blast.tsv")
        _write_blast_tsv(blast / "barcode01_taxid632_1.blast.tsv")

        results = collect_batch_results(
            tmp_path, "1", "barcode01", 1280, self._blast_fn(tmp_path)
        )

        assert all(r.taxid == 1280 for r in results)
        assert {r.validation_method for r in results} == {"blast", "minimap2"}

    def test_malformed_minimap2_batch_file_skipped(self, tmp_path: Path) -> None:
        """An unparseable minimap2 batch stats file is skipped, not fatal."""
        mm2 = tmp_path / "validation" / "minimap2" / "batch"
        mm2.mkdir(parents=True)
        (mm2 / "barcode01_taxid1280_1.minimap2_stats.json").write_text("{ broken ")

        results = collect_batch_results(tmp_path, "1", None, None, self._blast_fn(tmp_path))

        assert results == []

    def test_blast_non_integer_taxid_skipped(self, tmp_path: Path) -> None:
        """A blast file with a non-numeric taxid segment is skipped."""
        blast = tmp_path / "validation" / "blast" / "batch"
        _write_blast_tsv(blast / "barcode01_taxidABC_1.blast.tsv")

        results = collect_batch_results(tmp_path, "1", None, None, self._blast_fn(tmp_path))

        assert results == []

    def test_only_minimap2_batch_when_blast_dir_absent(self, tmp_path: Path) -> None:
        """minimap2 batch results returned even if no blast/batch dir exists."""
        mm2 = tmp_path / "validation" / "minimap2" / "batch"
        _write_mm2_stats(mm2 / "barcode01_taxid1280_3.minimap2_stats.json")

        results = collect_batch_results(tmp_path, "3", None, None, self._blast_fn(tmp_path))

        assert len(results) == 1
        assert results[0].validation_method == "minimap2"
