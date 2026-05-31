"""Equality tests for the phase-B hot-path vectorizations.

Each vectorized routine must produce exactly what the previous Python-loop
implementation did. These tests pin the behaviour against an independent
reference computed the slow, obvious way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nanometa_live.app.tabs.kraken2_helpers import recalculate_cumulative_reads
from nanometa_live.app.components.coverage_plots import (
    create_cumulative_coverage_figure,
)
from nanometa_live.core.parsers.paf_coverage_parser import CoverageData


class TestRecalculateCumulativeReads:
    def test_matches_reference_loop(self):
        df = pd.DataFrame({
            "name": ["  Bacteria", "  Proteobacteria ", "Firmicutes"],
            "rank": ["D", "P", "P"],
            "cumul_reads": [100, 60, 40],
            "reads": [1, 2, 3],
        })
        # Reference: composite key f"{rank}_{name.strip()}" -> cumul_reads.
        expected = {
            "D_Bacteria": 100,
            "P_Proteobacteria": 60,
            "P_Firmicutes": 40,
        }
        assert recalculate_cumulative_reads(df) == expected

    def test_falls_back_to_reads_when_no_cumul(self):
        df = pd.DataFrame({
            "name": ["A", "B"],
            "rank": ["S", "S"],
            "reads": [7, 9],
        })
        assert recalculate_cumulative_reads(df) == {"S_A": 7, "S_B": 9}

    def test_last_wins_on_duplicate_composite_key(self):
        # Two rows with identical rank+name -> dict keeps the last, exactly
        # as repeated assignment in the old loop did.
        df = pd.DataFrame({
            "name": ["X", "X"],
            "rank": ["G", "G"],
            "cumul_reads": [5, 11],
        })
        assert recalculate_cumulative_reads(df) == {"G_X": 11}

    def test_empty_df(self):
        assert recalculate_cumulative_reads(pd.DataFrame()) == {}

    def test_zero_when_no_count_columns(self):
        df = pd.DataFrame({"name": ["A"], "rank": ["S"]})
        assert recalculate_cumulative_reads(df) == {"S_A": 0}


class TestCumulativeCoverageFigure:
    @staticmethod
    def _reference_fractions(depth, ref_length):
        max_d = min(
            int(np.percentile(depth[depth > 0], 99)) if np.any(depth > 0) else 1,
            500,
        )
        thresholds = np.arange(0, max_d + 1)
        return np.array([
            np.sum(depth >= t) / ref_length * 100 for t in thresholds
        ])

    def test_curve_matches_reference_loop(self):
        # Deterministic, varied depth profile (no RNG).
        depth = np.array(
            ([0] * 50) + list(range(1, 51)) + ([120] * 30) + ([3] * 70),
            dtype=np.uint32,
        )
        ref_length = depth.size
        cov = CoverageData(ref_name="chr1", ref_length=ref_length, depth_array=depth)
        fig = create_cumulative_coverage_figure(cov)
        got = np.asarray(fig.data[0].y, dtype=float)
        expected = self._reference_fractions(depth, ref_length)
        assert got.shape == expected.shape
        assert np.allclose(got, expected)

    def test_all_zero_depth(self):
        depth = np.zeros(200, dtype=np.uint32)
        cov = CoverageData(ref_name="chr1", ref_length=depth.size, depth_array=depth)
        fig = create_cumulative_coverage_figure(cov)
        got = np.asarray(fig.data[0].y, dtype=float)
        expected = self._reference_fractions(depth, depth.size)
        assert np.allclose(got, expected)
