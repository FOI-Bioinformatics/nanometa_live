"""Tests for auto_detect.py -- the sample-handling layout selector.

Audit followup F9 (docs/audit-2026-05-02-followups.md): the
2026-05-02 frontend audit flagged auto_detect.py as untested.
A misclassification of the input layout produces empty
dashboards (the loaders look in the wrong subdirectory shape),
so pinning the detection rules guards a class of operator-
visible regressions.

The three layout decisions covered here:
  - by_barcode    : at least one barcodeNN/ subdirectory with FASTQs
  - per_file      : flat layout with multiple distinct sample stems
  - single_sample : flat layout with sequential names or a single
                    consistent stem

Plus the two helpers operators rely on indirectly:
  - get_barcode_list: returns sorted list of barcodeNN names that
    actually contain FASTQ data
  - detect_file_format: reports compressed/uncompressed counts
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanometa_live.core.utils.auto_detect import (
    detect_file_format,
    detect_sample_handling,
    get_barcode_list,
)


def _touch(path: Path, content: str = "data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# detect_sample_handling
# ---------------------------------------------------------------------------


class TestDetectSampleHandlingMissingDir:
    def test_missing_dir_returns_default(self, tmp_path):
        mode, reason = detect_sample_handling(str(tmp_path / "missing"))
        assert mode == "by_barcode"
        assert "not found" in reason.lower()

    def test_path_to_file_returns_default(self, tmp_path):
        f = tmp_path / "file.txt"
        _touch(f)
        mode, reason = detect_sample_handling(str(f))
        assert mode == "by_barcode"
        assert "not a directory" in reason.lower()


class TestDetectSampleHandlingByBarcode:
    def test_two_barcodes_with_fastq(self, tmp_path):
        for bc in ("barcode01", "barcode02"):
            _touch(tmp_path / bc / "reads.fastq.gz")
        mode, reason = detect_sample_handling(str(tmp_path))
        assert mode == "by_barcode"
        assert "barcode" in reason.lower()

    def test_barcode_dirs_no_fastq_falls_through(self, tmp_path):
        # Empty barcode dirs do not classify as by_barcode (no FASTQ).
        # The function then falls through to the flat-dir analysis.
        for bc in ("barcode01", "barcode02"):
            (tmp_path / bc).mkdir()
        # Add some flat FASTQs so we don't trip the no-files default.
        for i in range(6):
            _touch(tmp_path / f"reads_{i}.fastq.gz")
        mode, reason = detect_sample_handling(str(tmp_path))
        # With 6 sequentially-named files, single_sample is the
        # documented outcome.
        assert mode in ("single_sample", "per_file"), (
            f"unexpected fallthrough mode: {mode}"
        )

    def test_uppercase_barcode_pattern(self, tmp_path):
        # The regex is case-insensitive per the source.
        _touch(tmp_path / "BARCODE01" / "x.fastq")
        mode, _ = detect_sample_handling(str(tmp_path))
        assert mode == "by_barcode"


class TestDetectSampleHandlingFlat:
    def test_no_fastq_anywhere_returns_default(self, tmp_path):
        _touch(tmp_path / "readme.md", "hi")
        mode, reason = detect_sample_handling(str(tmp_path))
        assert mode == "by_barcode"
        assert "no fastq" in reason.lower()

    def test_fastq_in_non_barcode_subdirs(self, tmp_path):
        # Subdirs that aren't barcodeNN but DO contain FASTQs are
        # valid per-sample folders (e.g. Turex/, Zymo/, mock-community
        # pools). They now classify as by_barcode because "by_barcode"
        # means "subdirectory-per-sample" regardless of folder naming.
        # See core.utils.auto_detect.find_sample_subdirs for the rule.
        _touch(tmp_path / "sample_A" / "reads.fastq.gz")
        _touch(tmp_path / "sample_B" / "reads.fastq.gz")
        mode, reason = detect_sample_handling(str(tmp_path))
        assert mode == "by_barcode"
        assert "sample_A" in reason or "sample_B" in reason

    def test_distinct_sample_prefixes_per_file(self, tmp_path):
        # The "distinct prefixes" branch fires when N unique prefixes
        # are at most half of N files. Two unique prefixes with four
        # files (2/4 == 0.5) satisfies the cutoff.
        _touch(tmp_path / "alpha_001.fastq.gz")
        _touch(tmp_path / "alpha_002.fastq.gz")
        _touch(tmp_path / "beta_001.fastq.gz")
        _touch(tmp_path / "beta_002.fastq.gz")
        mode, reason = detect_sample_handling(str(tmp_path))
        assert mode == "per_file"
        assert "distinct" in reason.lower()

    def test_sequential_names_single_sample(self, tmp_path):
        # Names like pass_0001 trigger the sequential-pattern branch.
        for i in range(8):
            _touch(tmp_path / f"pass_{i:04d}.fastq.gz")
        mode, reason = detect_sample_handling(str(tmp_path))
        assert mode == "single_sample"
        assert "sequential" in reason.lower()

    def test_many_uniform_files_single_sample(self, tmp_path):
        # > 5 FASTQs without distinct prefixes or sequential markers
        # falls into the file-count default.
        for i in range(8):
            _touch(tmp_path / f"reads_{i}.fastq.gz")
        mode, _ = detect_sample_handling(str(tmp_path))
        assert mode == "single_sample"

    def test_few_distinct_files_per_file(self, tmp_path):
        # 2 files, both distinct prefixes -> per_file (file count <= 5).
        _touch(tmp_path / "alpha.fastq.gz")
        _touch(tmp_path / "beta.fastq.gz")
        mode, _ = detect_sample_handling(str(tmp_path))
        assert mode == "per_file"


# ---------------------------------------------------------------------------
# get_barcode_list
# ---------------------------------------------------------------------------


class TestGetBarcodeList:
    def test_missing_dir_returns_empty(self, tmp_path):
        assert get_barcode_list(str(tmp_path / "nope")) == []

    def test_returns_only_barcodes_with_fastq(self, tmp_path):
        _touch(tmp_path / "barcode01" / "x.fastq.gz")
        _touch(tmp_path / "barcode02" / "x.fastq")
        # barcode03 exists but is empty -- should be excluded.
        (tmp_path / "barcode03").mkdir()
        # An unclassified dir is not a barcode and is excluded.
        _touch(tmp_path / "unclassified" / "x.fastq.gz")
        out = get_barcode_list(str(tmp_path))
        assert out == ["barcode01", "barcode02"]

    def test_sorted_output(self, tmp_path):
        _touch(tmp_path / "barcode05" / "x.fastq")
        _touch(tmp_path / "barcode02" / "x.fastq")
        _touch(tmp_path / "barcode10" / "x.fastq")
        out = get_barcode_list(str(tmp_path))
        # Lexicographic sort: 02 < 05 < 10 here because the two-digit
        # form is consistent across the fixture.
        assert out == ["barcode02", "barcode05", "barcode10"]


# ---------------------------------------------------------------------------
# detect_file_format
# ---------------------------------------------------------------------------


class TestDetectFileFormat:
    def test_missing_dir_returns_skeleton(self, tmp_path):
        result = detect_file_format(str(tmp_path / "missing"))
        assert result["primary_format"] is None
        assert result["total_files"] == 0
        assert result["compressed"] is False

    def test_compressed_fastq_detected(self, tmp_path):
        _touch(tmp_path / "a.fastq.gz")
        _touch(tmp_path / "b.fastq.gz")
        result = detect_file_format(str(tmp_path))
        assert result["primary_format"] == "fastq"
        assert result["compressed"] is True
        assert result["total_files"] == 2

    def test_uncompressed_fastq(self, tmp_path):
        _touch(tmp_path / "a.fastq")
        _touch(tmp_path / "b.fq")
        result = detect_file_format(str(tmp_path))
        assert result["primary_format"] == "fastq"
        assert result["compressed"] is False
        assert result["total_files"] == 2

    def test_recursive_walk(self, tmp_path):
        _touch(tmp_path / "barcode01" / "a.fastq.gz")
        _touch(tmp_path / "barcode02" / "b.fastq.gz")
        result = detect_file_format(str(tmp_path))
        assert result["total_files"] == 2
        assert result["compressed"] is True
