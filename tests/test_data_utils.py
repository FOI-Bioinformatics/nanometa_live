"""
Unit tests for core/utils/data_utils.py.

These are small, pure file parsers used across the loaders. Each returns a safe
default (empty frame / zeros) rather than raising on a missing or malformed
input, so tests cover both the happy path and the documented fallback.
"""

import gzip
import json

import pandas as pd

from nanometa_live.core.utils.data_utils import (
    extract_classified_reads,
    parse_blast_results,
    parse_fastp_report,
    parse_fastq_file,
    parse_kraken_output,
    parse_kraken_report,
)

KRAKEN_COLS = ["%", "cumul_reads", "reads", "rank", "taxid", "name"]


class TestParseKrakenReport:
    def test_valid_report(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(
            "10.0\t50\t50\tU\t0\tunclassified\n"
            "90.0\t450\t0\tR\t1\troot\n"
        )
        df = parse_kraken_report(str(f))
        assert list(df.columns) == KRAKEN_COLS
        assert len(df) == 2

    def test_missing_file_returns_empty_frame(self, tmp_path):
        df = parse_kraken_report(str(tmp_path / "nope.txt"))
        assert df.empty
        assert list(df.columns) == KRAKEN_COLS


class TestParseKrakenOutput:
    def test_counts_by_taxid(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text(
            "C\tread1\t562\t150\tlca\n"
            "C\tread2\t562\t150\tlca\n"
            "C\tread3\t1280\t150\tlca\n"
            "U\tread4\t0\t150\tlca\n"
        )
        assert parse_kraken_output(str(f)) == {562: 2, 1280: 1, 0: 1}

    def test_handles_taxid_prefixed_format_and_skips_short_lines(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text(
            "C\tread1\ttaxid 562\t150\tlca\n"
            "short\tline\n"  # < 3 fields, skipped
        )
        assert parse_kraken_output(str(f)) == {562: 1}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert parse_kraken_output(str(tmp_path / "nope.txt")) == {}


class TestParseFastqFile:
    def test_counts_reads_and_bases(self, tmp_path):
        f = tmp_path / "reads.fastq"
        f.write_text(
            "@r1\nACGTACGT\n+\nIIIIIIII\n"
            "@r2\nACGT\n+\nIIII\n"
        )
        assert parse_fastq_file(str(f)) == (2, 12)

    def test_gzipped_fastq(self, tmp_path):
        f = tmp_path / "reads.fastq.gz"
        with gzip.open(f, "wt") as fh:
            fh.write("@r1\nACGTA\n+\nIIIII\n")
        assert parse_fastq_file(str(f)) == (1, 5)

    def test_missing_file_returns_zeros(self, tmp_path):
        assert parse_fastq_file(str(tmp_path / "nope.fastq")) == (0, 0)


class TestParseFastpReport:
    def test_extracts_filtering_result(self, tmp_path):
        f = tmp_path / "fastp.json"
        f.write_text(json.dumps({
            "filtering_result": {
                "passed_filter_reads": 950,
                "low_quality_reads": 30,
                "too_many_N_reads": 5,
                "too_short_reads": 15,
            }
        }))
        stats = parse_fastp_report(str(f))
        assert stats["passed_filter_reads"] == 950
        assert stats["low_quality_reads"] == 30
        assert stats["too_short_reads"] == 15

    def test_malformed_json_returns_zeroed_stats(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json")
        stats = parse_fastp_report(str(f))
        assert stats == {
            "passed_filter_reads": 0,
            "low_quality_reads": 0,
            "too_many_N_reads": 0,
            "too_short_reads": 0,
        }


class TestParseBlastResults:
    def test_unique_reads_and_total_alignments(self, tmp_path):
        f = tmp_path / "blast.txt"
        f.write_text(
            "read1\tref\t98.0\t150\t2\t0\t1\t150\t1\t150\t1e-50\t300\n"
            "read1\tref\t95.0\t140\t5\t0\t1\t140\t1\t140\t1e-40\t250\n"
            "read2\tref\t92.0\t130\t8\t0\t1\t130\t1\t130\t1e-30\t200\n"
        )
        assert parse_blast_results(str(f)) == (2, 3)

    def test_missing_file_returns_zeros(self, tmp_path):
        assert parse_blast_results(str(tmp_path / "nope.txt")) == (0, 0)


class TestExtractClassifiedReads:
    def test_classification_stats_from_root_and_unclassified(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text(
            "10.0\t50\t50\tU\t0\tunclassified\n"
            "90.0\t450\t0\tR\t1\troot\n"
        )
        classified, unclassified, pct_class, pct_unclass = extract_classified_reads(str(f))
        assert unclassified == 50
        assert classified == 450  # root cumul_reads (450) + unclassified (50) - unclassified
        assert pct_unclass == 10.0
        assert pct_class == 90.0

    def test_missing_file_returns_zeros(self, tmp_path):
        assert extract_classified_reads(str(tmp_path / "nope.txt")) == (0, 0, 0.0, 0.0)
