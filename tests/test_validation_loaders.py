"""
Unit tests for core/utils/validation_loaders.py (was 42% covered).

Covers the two public loaders against a synthetic nanometanf aggregate
validation_results.json: the flat list loader (load_validation_data) and the
watchlist-keyed loader (load_blast_validation_data, including status mapping,
watchlist filtering and sample filtering), plus the empty-directory paths.
"""

import json

import pytest

from nanometa_live.core.utils.validation_loaders import (
    load_blast_validation_data,
    load_validation_data,
)

pytestmark = pytest.mark.unit


def _aggregate(results_dir, results):
    vdir = results_dir / "validation"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "validation_results.json").write_text(json.dumps({
        "timestamp": "2026-05-30T00:00:00",
        "validation_method": "blast",
        "results": results,
    }))


@pytest.fixture
def results_dir(tmp_path):
    _aggregate(tmp_path, {
        "barcode01": {
            "562": {
                "species": "Escherichia coli",
                "kraken_reads": 1000,
                "blast_hits": 850,
                "hit_rate": 0.85,
                "avg_identity": 97.0,
                "validation_status": "confirmed",
            }
        }
    })
    return tmp_path


WATCHLIST = [{"taxid": 562, "name": "Escherichia coli"}]


class TestLoadValidationData:
    def test_returns_entries_from_aggregate(self, results_dir):
        rows = load_validation_data(str(results_dir))
        assert isinstance(rows, list)
        assert any(r["taxid"] == 562 for r in rows)

    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert load_validation_data(str(tmp_path)) == []


class TestLoadBlastValidationData:
    def test_maps_aggregate_entry_for_watched_taxid(self, results_dir):
        out = load_blast_validation_data(str(results_dir), WATCHLIST)
        assert 562 in out
        entry = out[562]
        assert entry["total_reads"] == 1000
        assert entry["validated_reads"] == 850
        assert entry["validation_rate"] == pytest.approx(85.0)
        assert entry["status"] == "validated"  # 'confirmed' -> 'validated'

    def test_unwatched_taxid_excluded(self, results_dir):
        out = load_blast_validation_data(str(results_dir), [{"taxid": 9999, "name": "x"}])
        assert out == {}

    def test_sample_filter_excludes_other_samples(self, results_dir):
        out = load_blast_validation_data(str(results_dir), WATCHLIST, sample="barcode02")
        assert out == {}

    def test_sample_filter_includes_matching_sample(self, results_dir):
        out = load_blast_validation_data(str(results_dir), WATCHLIST, sample="barcode01")
        assert 562 in out

    def test_no_validation_dir_returns_empty(self, tmp_path):
        assert load_blast_validation_data(str(tmp_path), WATCHLIST) == {}


class TestBlastTabularFallback:
    """No aggregate/canonical JSON present -> scan validation/blast/*_<taxid>.blast.tsv."""

    def test_counts_unique_reads_from_tabular_files(self, tmp_path):
        blast = tmp_path / "validation" / "blast"
        blast.mkdir(parents=True)
        # Two HSPs for read1, one for read2 -> 2 unique validated reads.
        (blast / "barcode01_562.blast.tsv").write_text(
            "read1\tref\t98.0\nread1\tref\t95.0\nread2\tref\t92.0\n"
        )
        out = load_blast_validation_data(str(tmp_path), WATCHLIST)
        assert 562 in out
        assert out[562]["validated_reads"] == 2
        # No kraken data here, so total_reads is 0 and the rate-based status
        # falls through to 'failed'.
        assert out[562]["total_reads"] == 0
        assert out[562]["status"] == "failed"

    def test_no_blast_files_for_taxid_reports_no_data(self, tmp_path):
        blast = tmp_path / "validation" / "blast"
        blast.mkdir(parents=True)
        (blast / "barcode01_999.blast.tsv").write_text("readX\tref\t98.0\n")  # different taxid
        out = load_blast_validation_data(str(tmp_path), WATCHLIST)
        assert out[562]["status"] == "no_data"
        assert out[562]["validated_reads"] == 0


class TestOnDiskBlastSupplementsAggregate:
    """The tiers must supplement per taxid, not short-circuit whole.

    load_blast_validation_data returned the first non-empty tier outright, so
    an aggregate covering only taxid A hid the on-disk blast.tsv for taxid B
    -- the Organisms tab's BLAST badge rendered no_data over a genuine
    confirmation. The disk glob also only matched the legacy bare-number
    naming, never nanometanf's `_taxid{tid}` files. Audit 2026-08-16,
    finding L14.
    """

    def _disk_blast(self, results_dir, sample, taxid, reads):
        bdir = results_dir / "validation" / "blast"
        bdir.mkdir(parents=True, exist_ok=True)
        rows = "".join(
            f"read{i}\tref1\t97.0\t150\t2\t0\t1\t150\t1\t150\t1e-50\t300\n"
            for i in range(reads)
        )
        (bdir / f"{sample}_taxid{taxid}.blast.tsv").write_text(rows)

    def test_disk_blast_for_uncovered_taxid_surfaces(self, results_dir):
        # Aggregate covers 562 only; 632 exists solely as an on-disk blast.tsv.
        self._disk_blast(results_dir, "barcode01", 632, reads=7)
        watchlist = [
            {"taxid": 562, "name": "Escherichia coli"},
            {"taxid": 632, "name": "Yersinia pestis"},
        ]

        out = load_blast_validation_data(str(results_dir), watchlist)

        assert 562 in out          # aggregate tier still wins for its taxids
        assert out[562]["validated_reads"] == 850
        assert 632 in out, (
            "on-disk blast.tsv hidden by the non-empty aggregate short-circuit"
        )
        assert out[632]["validated_reads"] == 7

    def test_taxid_prefixed_filename_is_matched(self, tmp_path):
        # No aggregate at all: only the current-pipeline naming on disk.
        self._disk_blast(tmp_path, "barcode01", 562, reads=3)
        out = load_blast_validation_data(str(tmp_path), WATCHLIST)
        assert 562 in out
        assert out[562]["validated_reads"] == 3
