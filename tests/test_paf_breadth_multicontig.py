"""``paf_breadth`` must treat each reference sequence as its own coordinate space.

A reference genome is often several records: a chromosome and plasmids, or a
draft assembly in many contigs (common among GTDB representatives). PAF
coordinates are per target sequence, so merging intervals across targets
counts position 500 on contig B as overlapping position 500 on contig A, and
taking ``max(tlen)`` as the genome length ignores every other contig.

The verdict path (``paf_breadth`` -> ``genome_breadth`` -> the 5% breadth
gate) must agree with the plot path (``parse_paf_coverage`` +
``aggregate_contig_coverage``), which already keeps contigs apart and sums
their lengths.
"""

import pytest

from nanometa_live.core.parsers import paf_coverage_parser as pcp

pytestmark = pytest.mark.unit


def _line(tname, tlen, tstart, tend, mapq=60):
    span = tend - tstart
    return (f"r_{tname}_{tstart}\t{span}\t0\t{span}\t+\t{tname}\t{tlen}\t"
            f"{tstart}\t{tend}\t{span}\t{span}\t{mapq}\n")


@pytest.fixture(autouse=True)
def _clear_cache():
    pcp._breadth_cache.clear()
    yield
    pcp._breadth_cache.clear()


def test_overlapping_coordinates_on_different_contigs_are_not_merged(tmp_path):
    # Same coordinates on two 1000 bp contigs: 400 bp covered on each,
    # 800 of 2000 bp in total.
    paf = tmp_path / "s_taxid1.paf"
    paf.write_text(_line("ctgA", 1000, 0, 400) + _line("ctgB", 1000, 0, 400))

    summary = pcp.paf_breadth(paf)

    assert summary.ref_length == 2000
    assert summary.covered_bp == 800
    assert summary.breadth == pytest.approx(0.40)


def test_disjoint_coordinates_on_different_contigs_use_summed_length(tmp_path):
    # ctgA 0-400 and ctgB 500-900: 800 of 2000 bp. The merged-space version
    # reported 800 / max(tlen)=1000 = 0.80.
    paf = tmp_path / "s_taxid1.paf"
    paf.write_text(_line("ctgA", 1000, 0, 400) + _line("ctgB", 1000, 500, 900))

    assert pcp.paf_breadth(paf).breadth == pytest.approx(0.40)


def test_verdict_breadth_matches_plot_breadth(tmp_path):
    paf = tmp_path / "s_taxid1.paf"
    paf.write_text(
        _line("chrom", 5000, 0, 1000)
        + _line("chrom", 5000, 800, 1500)
        + _line("plasmid", 1000, 200, 700)
    )

    plot = pcp.aggregate_contig_coverage(pcp.parse_paf_coverage(str(paf)))
    verdict = pcp.paf_breadth(paf)

    assert verdict.ref_length == plot.ref_length
    assert verdict.breadth == pytest.approx(plot.breadth, abs=1e-9)
