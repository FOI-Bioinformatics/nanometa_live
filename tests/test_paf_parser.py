"""Tests for the PAF coverage parser."""

from pathlib import Path

import numpy as np

from nanometa_live.core.parsers.paf_coverage_parser import CoverageData, parse_paf_coverage, aggregate_contig_coverage


class TestPAFParser:
    """Tests for parse_paf_coverage functionality."""

    def test_basic_coverage(self, tmp_path: Path) -> None:
        """Verify single-alignment coverage depth, breadth, and bounds."""
        paf = tmp_path / "basic.paf"
        paf.write_text(
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60\n"
        )

        result = parse_paf_coverage(paf)

        assert "ref1" in result
        cov = result["ref1"]
        assert cov.ref_length == 5000
        assert np.all(cov.depth_array[100:600] == 1)
        assert np.all(cov.depth_array[:100] == 0)
        assert np.all(cov.depth_array[600:] == 0)
        assert cov.breadth == 500 / 5000

    def test_overlapping_alignments(self, tmp_path: Path) -> None:
        """Overlapping regions should accumulate depth."""
        paf = tmp_path / "overlap.paf"
        lines = [
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60",
            "read2\t1000\t0\t1000\t+\tref1\t5000\t400\t900\t500\t500\t60",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf)
        depth = result["ref1"].depth_array

        assert depth[400] == 2
        assert depth[200] == 1
        assert depth[0] == 0

    def test_minus_strand_contributes_depth(self, tmp_path: Path) -> None:
        """Reverse-strand alignments (strand '-') use the same target start/end
        coordinates and must accrue depth identically to forward-strand ones.
        The parser reads target coords (cols 8/9), not strand (col 5)."""
        paf = tmp_path / "minus.paf"
        paf.write_text(
            "read1\t1000\t0\t1000\t-\tref1\t5000\t100\t600\t500\t500\t60\n"
        )
        result = parse_paf_coverage(paf)
        cov = result["ref1"]
        assert np.all(cov.depth_array[100:600] == 1)
        assert cov.breadth == 500 / 5000

    def test_mapq_filter(self, tmp_path: Path) -> None:
        """Alignments below min_mapq should be excluded."""
        paf = tmp_path / "mapq.paf"
        lines = [
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60",
            "read2\t1000\t0\t1000\t+\tref1\t5000\t700\t900\t200\t200\t5",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf, min_mapq=10)
        depth = result["ref1"].depth_array

        assert depth[150] == 1
        assert depth[750] == 0

    def test_short_lines_skipped(self, tmp_path: Path) -> None:
        """Lines with fewer than 12 fields should be silently skipped."""
        paf = tmp_path / "short.paf"
        lines = [
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60",
            "bad\tline\twith\tfew\tfields",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf)

        assert "ref1" in result
        assert len(result) == 1

    def test_multiple_references(self, tmp_path: Path) -> None:
        """Alignments to different references produce separate CoverageData entries."""
        paf = tmp_path / "multi.paf"
        lines = [
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60",
            "read2\t1000\t0\t1000\t+\tref2\t3000\t200\t800\t600\t600\t60",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf)

        assert len(result) == 2
        assert result["ref1"].ref_length == 5000
        assert result["ref2"].ref_length == 3000

    def test_empty_paf(self, tmp_path: Path) -> None:
        """An empty PAF file should return an empty dict."""
        paf = tmp_path / "empty.paf"
        paf.write_text("")

        result = parse_paf_coverage(paf)

        assert result == {}

    def test_nonexistent_paf(self, tmp_path: Path) -> None:
        """A missing PAF file should return an empty dict."""
        paf = tmp_path / "missing.paf"
        result = parse_paf_coverage(paf)
        assert result == {}

    def test_non_integer_numeric_fields(self, tmp_path: Path) -> None:
        """Lines with non-integer values in numeric columns should be skipped."""
        paf = tmp_path / "bad_numbers.paf"
        lines = [
            # Valid line
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60",
            # tlen is not an integer
            "read2\t1000\t0\t1000\t+\tref1\tABC\t100\t600\t500\t500\t60",
            # mapq is not an integer
            "read3\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\tN/A",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf)
        assert "ref1" in result
        # Only the valid alignment should contribute
        assert result["ref1"].max_depth == 1

    def test_invalid_coordinates_skipped(self, tmp_path: Path) -> None:
        """Lines with invalid alignment coordinates should be skipped."""
        paf = tmp_path / "bad_coords.paf"
        lines = [
            # Valid line
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60",
            # tstart > tend (reversed)
            "read2\t1000\t0\t1000\t+\tref1\t5000\t600\t100\t500\t500\t60",
            # tend > tlen (out of bounds)
            "read3\t1000\t0\t1000\t+\tref1\t5000\t100\t6000\t500\t500\t60",
            # tstart negative
            "read4\t1000\t0\t1000\t+\tref1\t5000\t-1\t600\t500\t500\t60",
            # tstart == tend (zero-length alignment)
            "read5\t1000\t0\t1000\t+\tref1\t5000\t300\t300\t0\t0\t60",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf)
        assert "ref1" in result
        # Only the first valid alignment should contribute
        assert result["ref1"].max_depth == 1
        assert np.all(result["ref1"].depth_array[100:600] == 1)

    def test_oversized_reference_skipped(self, tmp_path: Path) -> None:
        """References exceeding MAX_GENOME_SIZE should be skipped."""
        from nanometa_live.core.parsers.paf_coverage_parser import MAX_GENOME_SIZE

        paf = tmp_path / "huge_ref.paf"
        huge_len = MAX_GENOME_SIZE + 1
        lines = [
            # Normal reference
            f"read1\t1000\t0\t1000\t+\tsmall_ref\t5000\t100\t600\t500\t500\t60",
            # Reference exceeding limit
            f"read2\t1000\t0\t1000\t+\thuge_ref\t{huge_len}\t100\t600\t500\t500\t60",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf)
        assert "small_ref" in result
        assert "huge_ref" not in result

    def test_blank_and_whitespace_lines(self, tmp_path: Path) -> None:
        """Blank lines and whitespace-only lines should be skipped gracefully."""
        paf = tmp_path / "blanks.paf"
        lines = [
            "read1\t1000\t0\t1000\t+\tref1\t5000\t100\t600\t500\t500\t60",
            "",
            "   ",
            "read2\t1000\t0\t1000\t+\tref1\t5000\t600\t900\t300\t300\t60",
        ]
        paf.write_text("\n".join(lines) + "\n")

        result = parse_paf_coverage(paf)
        assert "ref1" in result
        assert result["ref1"].max_depth == 1


class TestAggregateContigCoverage:
    """Tests for aggregate_contig_coverage functionality."""

    def test_single_contig_passthrough(self) -> None:
        """A single contig should be returned as-is."""
        depth = np.array([0, 1, 2, 1, 0], dtype=np.uint32)
        cov = CoverageData(ref_name="contig1", ref_length=5, depth_array=depth)
        result = aggregate_contig_coverage({"contig1": cov})
        assert result.ref_name == "contig1"
        assert result.ref_length == 5
        assert np.array_equal(result.depth_array, depth)

    def test_multi_contig_concatenation(self) -> None:
        """Multiple contigs should be concatenated with correct total length."""
        cov1 = CoverageData(
            ref_name="contig1", ref_length=3,
            depth_array=np.array([1, 1, 0], dtype=np.uint32),
        )
        cov2 = CoverageData(
            ref_name="contig2", ref_length=4,
            depth_array=np.array([0, 2, 2, 0], dtype=np.uint32),
        )
        result = aggregate_contig_coverage({"contig1": cov1, "contig2": cov2})
        assert result.ref_length == 7
        assert len(result.depth_array) == 7
        assert result.breadth == 4 / 7  # 4 positions with depth >= 1

    def test_empty_dict(self) -> None:
        """An empty dict should return a zero-length CoverageData."""
        result = aggregate_contig_coverage({})
        assert result.ref_length == 0
        assert len(result.depth_array) == 0


class TestAmpliconConcentration:
    """CoverageData local metrics that distinguish amplicon (16S) coverage --
    deep reads in a short window of a large reference -- from genome-wide WGS
    coverage. See app/components/coverage_plots.py for how these drive the GUI."""

    def _amplicon_cov(self) -> CoverageData:
        # 1.87 Mb reference; a 1500 bp locus covered ~50x, rest empty (16S amplicon).
        ref_len = 1_870_206
        depth = np.zeros(ref_len, dtype=np.uint32)
        depth[943_350:944_850] = 50
        return CoverageData(ref_name="NZ_CP009607.1", ref_length=ref_len, depth_array=depth)

    def test_amplicon_is_concentrated(self) -> None:
        cov = self._amplicon_cov()
        assert cov.is_concentrated is True
        assert cov.covered_span == 1500
        assert cov.covered_bp == 1500
        assert cov.local_breadth == 1.0
        assert cov.local_mean_depth == 50.0  # mean depth across covered positions
        # genome-relative breadth is tiny -- the misleading number the GUI must
        # NOT judge on for amplicons.
        assert cov.breadth < 0.001

    def test_multicopy_16s_is_concentrated(self) -> None:
        # Three rrn operons megabases apart (the real F. tularensis layout): the
        # min..max span is ~1 Mb but only ~4.5 kb is covered, deeply. Must still
        # be flagged concentrated via depth-over-covered, not span.
        ref_len = 1_870_206
        depth = np.zeros(ref_len, dtype=np.uint32)
        for start in (433_809, 943_402, 1_416_013):
            depth[start:start + 1500] = 130
        cov = CoverageData(ref_name="NZ_CP009607.1", ref_length=ref_len, depth_array=depth)
        assert cov.is_concentrated is True
        assert cov.covered_bp == 4500             # 3 x 1500, total covered
        assert cov.covered_span > 900_000          # min..max spans the operons
        assert cov.local_mean_depth == 130.0       # deep where covered
        assert cov.breadth < 0.005

    def test_wgs_is_not_concentrated(self) -> None:
        # Reads spread across the whole genome at modest depth -> not amplicon.
        ref_len = 2_000_000
        rng = np.random.default_rng(0)
        depth = rng.integers(0, 3, size=ref_len, dtype=np.uint32)
        cov = CoverageData(ref_name="chrW", ref_length=ref_len, depth_array=depth)
        assert cov.is_concentrated is False
        assert cov.covered_span > ref_len * 0.5

    def test_sparse_shallow_locus_not_concentrated(self) -> None:
        # A short covered span but only depth 1-2 is not a confident amplicon hit.
        ref_len = 1_000_000
        depth = np.zeros(ref_len, dtype=np.uint32)
        depth[500_000:501_000] = 2  # below _CONCENTRATION_MIN_DEPTH (5)
        cov = CoverageData(ref_name="r", ref_length=ref_len, depth_array=depth)
        assert cov.is_concentrated is False

    def test_no_coverage_metrics_safe(self) -> None:
        cov = CoverageData(ref_name="r", ref_length=1000,
                           depth_array=np.zeros(1000, dtype=np.uint32))
        assert cov.is_concentrated is False
        assert cov.covered_span == 0
        assert cov.covered_start == -1
        assert cov.local_breadth == 0.0
