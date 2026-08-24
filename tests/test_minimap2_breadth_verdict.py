"""The genome-coverage verdict must consider genome coverage.

The minimap2 status came from hit rate and identity alone, so a read that
mapped cleanly to a sliver of a genome was CONFIRMED in the Genome Coverage
sub-tab. Measured on the Bioshield exercise run (2026-08-18), where every
one of these was "confirmed" by hit rate and identity:

    barcode11 holarctica  28,308 reads  98.14% breadth  78.9x   <- real
    barcode11 species      5,294 reads  71.72% breadth   5.3x   <- real
    barcode16 holarctica       5 reads   1.23% breadth   0.01x  <- carryover
    barcode14 holarctica       1 read    0.15% breadth   0.00x  <- carryover
    barcode16 species          1 read    0.07% breadth   0.00x  <- carryover

Breadth separates them by three orders of magnitude. It is NOT the
``avg_coverage`` field -- that is per-read query coverage (span/qlen) and is
~0.95 for all five -- but it is computable from the PAF, which sits beside
the stats file.

Amplicon data must not be punished for it: a PCR product legitimately
covers a tiny fraction of the genome at high local depth, so the
concentrated-coverage test that already governs the plots governs this too.
"""

import json
import os
import time

import pytest

from nanometa_live.core.parsers.blast_validation_parser import (
    ValidationParser,
    ValidationStatus,
)

pytestmark = pytest.mark.unit

REF_LEN = 1_900_000


def _paf_line(qname, qlen, tstart, tend, mapq=60):
    span = tend - tstart
    return (f"{qname}\t{qlen}\t0\t{span}\t+\tNZ_TEST\t{REF_LEN}\t"
            f"{tstart}\t{tend}\t{span}\t{span}\t{mapq}\n")


def _tree(tmp_path, *, reads, intervals, sample="bc01", taxid=4007187):
    """A minimap2 result whose PAF spans the given reference intervals."""
    mm2 = tmp_path / "validation" / "minimap2"
    mm2.mkdir(parents=True)
    stem = f"{sample}_taxid{taxid}"
    (mm2 / f"{stem}.paf").write_text("".join(
        _paf_line(f"r{i}", e - s, s, e) for i, (s, e) in enumerate(intervals)))
    (mm2 / f"{stem}.minimap2_stats.json").write_text(json.dumps({
        "sample_id": sample, "taxid": taxid, "total_reads": reads,
        "mapped_reads": reads, "hit_rate": 1.0, "avg_identity": 99.8,
        "avg_coverage": 0.95, "avg_mapq": 60, "ref_name": "NZ_TEST",
        "ref_length": REF_LEN,
    }))
    return tmp_path


def _status(tmp_path, **kw):
    res = ValidationParser(str(_tree(tmp_path, **kw))).get_validation_results()
    mm2 = [r for r in res if r.validation_method == "minimap2"]
    assert mm2, "the minimap2 result must still be produced"
    return mm2[0].status


class TestBreadthGovernsTheCoverageVerdict:
    def test_whole_genome_coverage_confirms(self, tmp_path):
        # 20 reads spread across ~95% of the reference.
        intervals = [(i * 95_000, i * 95_000 + 90_000) for i in range(20)]
        assert _status(tmp_path, reads=20, intervals=intervals) == \
            ValidationStatus.CONFIRMED

    def test_sliver_of_genome_does_not_confirm(self, tmp_path):
        # The negative-control shape: a handful of reads over ~1% of the
        # genome. Perfect identity and hit rate, but not a confirmation.
        intervals = [(1000 + i * 200, 1000 + i * 200 + 3000) for i in range(20)]
        assert _status(tmp_path, reads=20, intervals=intervals) != \
            ValidationStatus.CONFIRMED

    def test_sliver_still_shows_its_evidence(self, tmp_path):
        intervals = [(1000 + i * 200, 1000 + i * 200 + 3000) for i in range(20)]
        assert _status(tmp_path, reads=20, intervals=intervals) in (
            ValidationStatus.PARTIAL, ValidationStatus.LOW_CONFIDENCE,
            ValidationStatus.UNCERTAIN)

    def test_amplicon_is_not_punished(self, tmp_path):
        # A PCR product: ~1.5 kb of a 1.9 Mb genome (0.08% breadth) but 40
        # reads stacked on it. This is the yesterday's-amplicon case and must
        # remain confirmable.
        intervals = [(943_350, 944_850)] * 40
        assert _status(tmp_path, reads=40, intervals=intervals) == \
            ValidationStatus.CONFIRMED

    def test_missing_paf_falls_back_to_the_old_rule(self, tmp_path):
        # Breadth is an enrichment: without a PAF the verdict must still be
        # reachable from hit rate and identity alone.
        mm2 = tmp_path / "validation" / "minimap2"
        mm2.mkdir(parents=True)
        (mm2 / "bc01_taxid4007187.minimap2_stats.json").write_text(json.dumps({
            "sample_id": "bc01", "taxid": 4007187, "total_reads": 500,
            "mapped_reads": 490, "hit_rate": 0.98, "avg_identity": 99.5,
            "avg_coverage": 0.95, "avg_mapq": 60,
        }))
        res = ValidationParser(str(tmp_path)).get_validation_results()
        assert res and res[0].status == ValidationStatus.CONFIRMED

    def test_blast_results_are_unaffected(self, tmp_path):
        # Breadth is a genome-centric measure; the BLAST verdict keeps its
        # own rule (read support + identity).
        blast = tmp_path / "validation" / "blast"
        blast.mkdir(parents=True)
        (blast / "bc01_taxid4007187.blast.tsv").write_text("".join(
            f"r{i}\tNZ_TEST\t99.0\t500\t2\t0\t1\t500\t10\t510\t1e-50\t900\n"
            for i in range(50)))
        # Backdate past the round-3 mid-write stability gate.
        _t = time.time() - 120
        os.utime(blast / "bc01_taxid4007187.blast.tsv", (_t, _t))
        (blast / "bc01_taxid4007187.blast_stats.json").write_text(json.dumps({
            "sample_id": "bc01", "taxid": 4007187, "total_reads": 50,
            "blast_hits": 50, "hit_rate": 1.0, "avg_identity": 99.0,
            "avg_coverage": 0.95,
        }))
        res = ValidationParser(str(tmp_path)).get_validation_results()
        assert res and res[0].status == ValidationStatus.CONFIRMED
