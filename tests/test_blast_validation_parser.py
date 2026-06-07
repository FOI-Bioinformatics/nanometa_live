"""
Unit tests for the two previously-untested parser entry points in
core/parsers/blast_validation_parser.py:

- ``ValidationParser.parse_blast_tabular`` — legacy BLAST outfmt-6 parsing,
  including the 12- vs 15-column autodetection and the qseqid-dedup invariant
  that keeps the validated-read count (and hence the hit rate) bounded. This is
  the GUI-side counterpart to the pipeline blastn YAML fix, which dedups hits by
  qseqid so hit_rate stays within [0, 1].
- ``ValidationParser.parse_nanometanf_aggregate_json`` — the current aggregate
  output format, including the combined-method ("both") expansion into separate
  BLAST and minimap2 results, sample/taxid filters, and malformed-input handling.

The well-covered ``parse_validation_json`` path is intentionally left to the
existing test_validation_system.py suite.
"""

import json
from pathlib import Path

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    ValidationParser,
    ValidationResult,
    ValidationStatus,
)


@pytest.fixture
def parser(tmp_path):
    # results_dir only drives directory probing; the parse_* methods under test
    # take an explicit filepath, so an empty tmp dir is sufficient.
    return ValidationParser(str(tmp_path))


def _write_blast(path: Path, rows, cols=12):
    """Write BLAST outfmt-6 rows. Each row is a tuple of field values."""
    assert all(len(r) == cols for r in rows)
    path.write_text("".join("\t".join(str(v) for v in r) + "\n" for r in rows))


# 12-column outfmt 6: qseqid sseqid pident length mismatch gapopen qstart qend
#                     sstart send evalue bitscore
ROWS_12 = [
    ("read1", "ref1", 98.5, 150, 2, 0, 1, 150, 1, 150, "1e-50", 300),
    ("read1", "ref1", 95.0, 140, 5, 0, 1, 140, 5, 145, "1e-40", 250),  # dup qseqid
    ("read2", "ref1", 92.0, 130, 8, 0, 1, 130, 1, 130, "1e-30", 200),
]


class TestParseBlastTabular:
    def test_dedups_by_qseqid(self, parser, tmp_path):
        # Regression anchor: three HSPs but two unique reads -> validated_reads
        # must be 2, not 3, so hit rate cannot exceed 1.
        f = tmp_path / "barcode01_562.blast.txt"
        _write_blast(f, ROWS_12)
        result = parser.parse_blast_tabular(f, "barcode01", 562, total_reads=4)
        assert result.validated_reads == 2
        assert result.percent_validated == pytest.approx(50.0)

    def test_identity_statistics(self, parser, tmp_path):
        f = tmp_path / "b.blast.txt"
        _write_blast(f, ROWS_12)
        result = parser.parse_blast_tabular(f, "barcode01", 562, total_reads=4)
        assert result.percent_identity_max == pytest.approx(98.5)
        assert result.percent_identity_min == pytest.approx(92.0)
        assert result.percent_identity_mean == pytest.approx((98.5 + 95.0 + 92.0) / 3)
        assert result.alignment_length_mean == pytest.approx((150 + 140 + 130) / 3)

    def test_high_validation_is_confirmed(self, parser, tmp_path):
        f = tmp_path / "b.blast.txt"
        _write_blast(f, ROWS_12)
        # total_reads == unique reads -> 100% validated, identity mean >= 90.
        result = parser.parse_blast_tabular(f, "barcode01", 562, total_reads=2)
        assert result.percent_validated == pytest.approx(100.0)
        assert result.status == ValidationStatus.CONFIRMED

    def test_zero_total_reads_uses_presence(self, parser, tmp_path):
        f = tmp_path / "b.blast.txt"
        _write_blast(f, ROWS_12)
        result = parser.parse_blast_tabular(f, "barcode01", 562, total_reads=0)
        assert result.percent_validated == pytest.approx(100.0)

    def test_15_column_format_is_autodetected(self, parser, tmp_path):
        rows15 = [r + (200, 5000, 95) for r in ROWS_12]  # + qlen slen qcovs
        f = tmp_path / "b15.blast.txt"
        _write_blast(f, rows15, cols=15)
        result = parser.parse_blast_tabular(f, "barcode01", 562, total_reads=4)
        # Extra trailing columns must not corrupt the qseqid dedup.
        assert result.validated_reads == 2

    def test_empty_file_is_no_data(self, parser, tmp_path):
        f = tmp_path / "empty.blast.txt"
        f.write_text("")
        result = parser.parse_blast_tabular(f, "barcode01", 562)
        assert result.status == ValidationStatus.NO_DATA
        assert result.validated_reads == 0

    def test_missing_file_is_no_data(self, parser, tmp_path):
        result = parser.parse_blast_tabular(
            tmp_path / "does_not_exist.txt", "barcode01", 562
        )
        assert result.status == ValidationStatus.NO_DATA


class TestDetermineStatusBoundaries:
    """Exact-threshold behaviour of ValidationResult.determine_status().

    Authoritative rule (blast_validation_parser.py): CONFIRMED iff
    percent_validated >= 80 AND percent_identity_mean >= 90; PARTIAL iff
    percent_validated >= 50; LOW_CONFIDENCE iff > 0; else NO_DATA; FAILED on
    errors. The boundaries are inclusive on the >= side.
    """

    @pytest.mark.parametrize("pv,ident,expected", [
        (80.0, 90.0, ValidationStatus.CONFIRMED),     # both exactly on boundary
        (100.0, 90.0, ValidationStatus.CONFIRMED),
        (80.0, 89.9, ValidationStatus.PARTIAL),       # identity just below floor
        (79.9, 99.0, ValidationStatus.PARTIAL),       # validated just below 80
        (50.0, 99.0, ValidationStatus.PARTIAL),       # 50 boundary inclusive
        (49.9, 99.0, ValidationStatus.LOW_CONFIDENCE),
        (0.0, 99.0, ValidationStatus.NO_DATA),        # no reads validated
    ])
    def test_threshold_boundaries(self, pv, ident, expected):
        # validated/total kept > 0 so the (0,0) early NO_DATA branch is not hit
        # for the non-zero cases; for the pv==0 case validated_reads stays 0.
        validated = 0 if pv == 0.0 else 10
        r = ValidationResult(
            sample_id="s", taxid=1, total_reads=100,
            validated_reads=validated, percent_validated=pv,
            percent_identity_mean=ident, validation_method="blast",
        )
        assert r.determine_status() == expected

    def test_errors_force_failed_even_with_high_metrics(self):
        r = ValidationResult(
            sample_id="s", taxid=1, total_reads=100, validated_reads=100,
            percent_validated=100.0, percent_identity_mean=99.0,
            validation_method="blast",
        )
        r.errors.append("boom")
        assert r.determine_status() == ValidationStatus.FAILED

    def test_zero_reads_and_zero_total_is_no_data(self):
        r = ValidationResult(sample_id="s", taxid=1, total_reads=0,
                             validated_reads=0, validation_method="blast")
        assert r.determine_status() == ValidationStatus.NO_DATA


def _aggregate(results, timestamp="2026-05-30T00:00:00", method="blast"):
    return {"timestamp": timestamp, "validation_method": method, "results": results}


class TestParseNanometanfAggregateJson:
    def test_single_blast_entry(self, parser, tmp_path):
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {
                "562": {
                    "species": "Escherichia coli",
                    "kraken_reads": 100,
                    "blast_hits": 90,
                    "hit_rate": 0.9,
                    "avg_identity": 97.0,
                }
            }
        })))
        results = parser.parse_nanometanf_aggregate_json(f)
        assert len(results) == 1
        r = results[0]
        assert r.sample_id == "barcode01"
        assert r.taxid == 562
        assert r.species == "Escherichia coli"
        assert r.validated_reads == 90
        assert r.percent_validated == pytest.approx(90.0)
        assert r.status == ValidationStatus.CONFIRMED

    def test_both_method_expands_to_two_results(self, parser, tmp_path):
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {
                "562": {
                    "species": "Escherichia coli",
                    "kraken_reads": 100,
                    "blast_hits": 80,
                    "hit_rate": 0.8,
                    "avg_identity": 96.0,
                    "minimap2_mapped": 85,
                    "minimap2_hit_rate": 0.85,
                    "minimap2_identity": 98.0,
                }
            }
        }, method="both")))
        results = parser.parse_nanometanf_aggregate_json(f)
        # The primary result keeps the entry/default method ("both"); the
        # presence of minimap2 fields appends a second, minimap2-tagged result.
        assert len(results) == 2
        methods = sorted(r.validation_method for r in results)
        assert methods == ["both", "minimap2"]
        mm2 = next(r for r in results if r.validation_method == "minimap2")
        assert mm2.validated_reads == 85
        assert mm2.percent_validated == pytest.approx(85.0)

    def test_sample_filter(self, parser, tmp_path):
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {"562": {"kraken_reads": 10, "blast_hits": 5, "hit_rate": 0.5}},
            "barcode02": {"562": {"kraken_reads": 10, "blast_hits": 5, "hit_rate": 0.5}},
        })))
        results = parser.parse_nanometanf_aggregate_json(f, sample="barcode02")
        assert len(results) == 1
        assert results[0].sample_id == "barcode02"

    def test_taxid_filter(self, parser, tmp_path):
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {
                "562": {"kraken_reads": 10, "blast_hits": 5, "hit_rate": 0.5},
                "1280": {"kraken_reads": 10, "blast_hits": 5, "hit_rate": 0.5},
            },
        })))
        results = parser.parse_nanometanf_aggregate_json(f, taxid=1280)
        assert len(results) == 1
        assert results[0].taxid == 1280

    def test_empty_results_yields_empty_list(self, parser, tmp_path):
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({})))
        assert parser.parse_nanometanf_aggregate_json(f) == []

    def test_missing_file_yields_empty_list(self, parser, tmp_path):
        assert parser.parse_nanometanf_aggregate_json(tmp_path / "nope.json") == []

    def test_malformed_json_yields_empty_list(self, parser, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not valid json")
        assert parser.parse_nanometanf_aggregate_json(f) == []

    def test_both_method_without_minimap2_fields_does_not_expand(self, parser, tmp_path):
        # A "both"-declared run can have an entry where minimap2 produced nothing
        # for this taxid (no ``minimap2_mapped`` key). The parser must NOT
        # synthesise a phantom minimap2 result from absent fields.
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {
                "562": {
                    "species": "Escherichia coli",
                    "kraken_reads": 100,
                    "blast_hits": 90,
                    "hit_rate": 0.9,
                    "avg_identity": 97.0,
                }
            }
        }, method="both")))
        results = parser.parse_nanometanf_aggregate_json(f)
        assert len(results) == 1
        assert results[0].validation_method == "both"

    def test_minimap2_mapped_zero_still_expands(self, parser, tmp_path):
        # ``minimap2_mapped: 0`` is a real (mapped-nothing) outcome, distinct from
        # an absent key — it must expand to a NO_DATA minimap2 result, not be
        # silently dropped.
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {
                "562": {
                    "kraken_reads": 100, "blast_hits": 90, "hit_rate": 0.9,
                    "avg_identity": 97.0, "minimap2_mapped": 0,
                    "minimap2_hit_rate": 0.0, "minimap2_identity": 0.0,
                }
            }
        }, method="both")))
        results = parser.parse_nanometanf_aggregate_json(f)
        assert len(results) == 2
        mm2 = next(r for r in results if r.validation_method == "minimap2")
        assert mm2.validated_reads == 0
        assert mm2.status == ValidationStatus.NO_DATA

    def test_mixed_methods_across_taxids_split_correctly(self, parser, tmp_path):
        # One taxid is "both" (-> 2 results), another is blast-only (-> 1). Total 3.
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {
                "562": {
                    "kraken_reads": 100, "blast_hits": 90, "hit_rate": 0.9,
                    "avg_identity": 97.0, "minimap2_mapped": 88,
                    "minimap2_hit_rate": 0.88, "minimap2_identity": 98.0,
                },
                "1280": {
                    "kraken_reads": 100, "blast_hits": 70, "hit_rate": 0.7,
                    "avg_identity": 95.0,
                },
            }
        }, method="both")))
        results = parser.parse_nanometanf_aggregate_json(f)
        assert len(results) == 3
        by_taxid = {}
        for r in results:
            by_taxid.setdefault(r.taxid, []).append(r.validation_method)
        assert sorted(by_taxid[562]) == ["both", "minimap2"]
        assert by_taxid[1280] == ["both"]   # blast-only entry, method defaults to run method

    def test_taxid_filter_keeps_both_expansion(self, parser, tmp_path):
        # Filtering to the "both" taxid must still yield both expanded results.
        f = tmp_path / "validation_results.json"
        f.write_text(json.dumps(_aggregate({
            "barcode01": {
                "562": {
                    "kraken_reads": 100, "blast_hits": 90, "hit_rate": 0.9,
                    "avg_identity": 97.0, "minimap2_mapped": 88,
                    "minimap2_hit_rate": 0.88, "minimap2_identity": 98.0,
                },
                "1280": {"kraken_reads": 100, "blast_hits": 70, "hit_rate": 0.7},
            }
        }, method="both")))
        results = parser.parse_nanometanf_aggregate_json(f, taxid=562)
        assert len(results) == 2
        assert {r.taxid for r in results} == {562}
