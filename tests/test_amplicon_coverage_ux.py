"""Amplicon (full-length 16S) coverage UX + cross-species guard tests.

Covers the amplicon-awareness added so a 16S validation run no longer reads as a
false "low coverage" and so a conserved-region confirmation carries a specificity
caveat:

- create_coverage_stats_summary: focused-coverage interpretation + "Covered
  Region" stat for concentrated coverage; unchanged RED verdict for genuine
  low-coverage WGS.
- create_coverage_depth_figure: x-range zoomed to the covered locus.
- validation_guards: reference-organism genus mismatch + conserved-region caveat.
"""

import numpy as np
import pytest

from nanometa_live.core.parsers.paf_coverage_parser import CoverageData
from nanometa_live.app.components.coverage_plots import (
    create_coverage_stats_summary,
    create_coverage_depth_figure,
    create_cumulative_coverage_figure,
    create_depth_histogram_figure,
)
from nanometa_live.core.parsers.validation_guards import (
    check_reference_organism,
    conserved_region_caveat,
    reference_organism_from_fasta,
)
from tests.dash_test_utils import collect_string_ids  # noqa: F401  (kept for parity)


def _amplicon_cov(depth_val=200):
    ref_len = 1_870_206
    depth = np.zeros(ref_len, dtype=np.uint32)
    depth[943_350:944_850] = depth_val  # 1500 bp 16S locus
    return CoverageData(ref_name="NZ_CP009607.1", ref_length=ref_len, depth_array=depth)


def _wgs_low_cov():
    # Genuine low coverage: a little coverage scattered, low depth, NOT amplicon.
    ref_len = 2_000_000
    depth = np.zeros(ref_len, dtype=np.uint32)
    depth[::50_000] = 1  # sparse single-base hits spread genome-wide
    return CoverageData(ref_name="chrW", ref_length=ref_len, depth_array=depth)


def _text(component) -> str:
    return str(component)


class TestCoverageStatsSummaryAmplicon:
    def test_concentrated_renders_focused_not_red(self):
        out = _text(create_coverage_stats_summary(_amplicon_cov(depth_val=200)))
        assert "Focused coverage" in out
        assert "Covered Region" in out          # the extra stat
        assert "Depth in Region" in out
        # must NOT show the misleading low-coverage verdict
        assert "Low coverage - insufficient" not in out

    def test_multicopy_16s_renders_focused(self):
        # 3 rRNA operons megabases apart, deep -> still focused, not RED.
        ref_len = 1_870_206
        depth = np.zeros(ref_len, dtype=np.uint32)
        for start in (433_809, 943_402, 1_416_013):
            depth[start:start + 1500] = 130
        cov = CoverageData(ref_name="NZ_CP009607.1", ref_length=ref_len, depth_array=depth)
        out = _text(create_coverage_stats_summary(cov))
        assert "Focused coverage" in out
        assert "Low coverage - insufficient" not in out

    def test_concentrated_emits_conserved_region_caveat(self):
        out = _text(create_coverage_stats_summary(_amplicon_cov(depth_val=200)))
        assert "short conserved region" in out
        assert "close relatives" in out

    def test_genuine_low_coverage_still_red(self):
        cov = _wgs_low_cov()
        assert cov.is_concentrated is False
        out = _text(create_coverage_stats_summary(cov))
        assert "Low coverage - insufficient" in out
        assert "Covered Region" not in out
        assert "short conserved region" not in out


class TestDepthFigureZoom:
    def test_concentrated_zooms_x_axis_to_locus(self):
        fig = create_coverage_depth_figure(_amplicon_cov(depth_val=50), threshold=10)
        rng = fig.layout.xaxis.range
        assert rng is not None
        lo, hi = rng
        # Window centred on the 16S locus (943350-944850), not the full 1.87 Mb.
        assert lo >= 940_000 and hi <= 948_000
        assert "zoomed" in (fig.layout.xaxis.title.text or "").lower()

    def test_wgs_not_zoomed(self):
        fig = create_coverage_depth_figure(_wgs_low_cov(), threshold=10)
        assert fig.layout.xaxis.range is None


class TestCumulativeCurveAmplicon:
    def test_concentrated_scales_to_covered_region(self):
        # 1500 bp at 200x in a 1.87 Mb genome: normalised to the genome the
        # whole curve sits below 0.1% and renders as a flat zero line. The
        # concentrated view must scale to the covered region instead.
        fig = create_cumulative_coverage_figure(_amplicon_cov(depth_val=200))
        y = np.asarray(fig.data[0].y, dtype=float)
        assert y.max() > 90
        assert "covered region" in (fig.layout.yaxis.title.text or "").lower()

    def test_wgs_still_genome_normalized(self):
        fig = create_cumulative_coverage_figure(_wgs_low_cov())
        y = np.asarray(fig.data[0].y, dtype=float)
        assert y[0] == pytest.approx(100.0)  # threshold 0: every position >= 0x
        assert "genome" in (fig.layout.yaxis.title.text or "").lower()


class TestHistogramCoveredPositions:
    def test_zero_positions_excluded_for_amplicon(self):
        # Previously the ~1.87 M uncovered positions landed in bin 0 and made
        # every real bar invisible. Only covered positions may be histogrammed.
        fig = create_depth_histogram_figure(_amplicon_cov(depth_val=200))
        counts = np.asarray(fig.data[0].y, dtype=float)
        assert counts.sum() == 1500

    def test_zero_positions_excluded_for_wgs(self):
        fig = create_depth_histogram_figure(_wgs_low_cov())
        counts = np.asarray(fig.data[0].y, dtype=float)
        assert counts.sum() == 40  # the 40 covered single-base hits

    def test_mean_marker_uses_covered_mean(self):
        # Genome-wide mean is ~0.16x for the amplicon fixture; the marker must
        # state the mean over covered positions (200x) to match the bars.
        fig = create_depth_histogram_figure(_amplicon_cov(depth_val=200))
        texts = [a.text or "" for a in fig.layout.annotations]
        assert any("200" in t for t in texts)

    def test_all_zero_coverage_does_not_raise(self):
        cov = CoverageData(
            ref_name="empty", ref_length=1000,
            depth_array=np.zeros(1000, dtype=np.uint32),
        )
        fig = create_depth_histogram_figure(cov)
        assert fig.data


class TestStatsOrderAmplicon:
    def test_covered_region_leads_genome_breadth(self):
        out = _text(create_coverage_stats_summary(_amplicon_cov()))
        assert out.index("Covered Region") < out.index("Genome Covered")

    def test_genomewide_depth_stats_hidden_when_concentrated(self):
        # Genome-wide "Avg. Depth 0.2x" beside "Depth in Region 200x" reads as
        # a contradiction; the concentrated summary drops the genome-wide pair.
        out = _text(create_coverage_stats_summary(_amplicon_cov()))
        assert "Avg. Depth" not in out
        assert "Typical Depth" not in out

    def test_wgs_keeps_genomewide_depth_stats(self):
        out = _text(create_coverage_stats_summary(_wgs_low_cov()))
        assert "Avg. Depth" in out
        assert "Typical Depth" in out


class TestReferenceOrganismGuard:
    def test_matching_genus_no_warning(self, tmp_path):
        f = tmp_path / "263.fasta"
        f.write_text(">NZ_CP009607.1 Francisella tularensis subsp. novicida D9876\nACGT\n")
        assert check_reference_organism(f, "Francisella tularensis") is None

    def test_genus_mismatch_warns(self, tmp_path):
        f = tmp_path / "263.fasta"
        f.write_text(">NZ_CP009607.1 Francisella tularensis subsp. novicida\nACGT\n")
        warn = check_reference_organism(f, "Bacillus anthracis")
        assert warn is not None
        assert "does not match" in warn
        assert "Francisella" in warn and "Bacillus" in warn

    def test_unknown_sides_are_not_mismatch(self, tmp_path):
        f = tmp_path / "x.fasta"
        f.write_text(">acc_only_no_organism\nACGT\n")
        assert check_reference_organism(f, "Francisella tularensis") is None
        assert check_reference_organism(f, "") is None

    def test_reference_organism_parsing(self, tmp_path):
        f = tmp_path / "g.fasta"
        f.write_text(">NZ_CP009607.1 Francisella tularensis subsp. novicida\nACGT\n")
        assert reference_organism_from_fasta(f).startswith("Francisella tularensis")
        assert reference_organism_from_fasta(tmp_path / "missing.fasta") is None


class TestConservedRegionCaveat:
    def test_fires_for_concentrated(self):
        assert conserved_region_caveat(_amplicon_cov()) is not None

    def test_silent_for_wgs(self):
        assert conserved_region_caveat(_wgs_low_cov()) is None

    @pytest.mark.parametrize("status", ["no_data", "failed"])
    def test_suppressed_for_negative_status(self, status):
        assert conserved_region_caveat(_amplicon_cov(), status=status) is None

    def test_present_for_confirmed_status(self):
        assert conserved_region_caveat(_amplicon_cov(), status="confirmed") is not None
