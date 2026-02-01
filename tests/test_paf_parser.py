"""Tests for the PAF coverage parser."""

from pathlib import Path

import numpy as np

from nanometa_live.core.parsers.paf_coverage_parser import CoverageData, parse_paf_coverage


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
