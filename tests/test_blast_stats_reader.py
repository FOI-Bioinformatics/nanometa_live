"""BLAST per-pair stats files must be read, like the minimap2 ones.

Found auditing the Validation tab (2026-08-18). nanometanf publishes
``validation/blast/<sample>_taxid<tid>.blast_stats.json`` beside the
``.blast.tsv``, carrying total_reads / hit_rate / avg_identity /
avg_coverage -- the same shape minimap2 gets through
``core/parsers/minimap2_stats.py``. The parser globbed only the TSV, so in a
realtime run (where the aggregate validation_results.json is not written
until session end) every BLAST result arrived with the read count it was
measured against set to ZERO.

Measured before the fix, on a tree holding both a blast.tsv with 40 hits and
a blast_stats.json saying total_reads=50:

    blast     validated=40  total=0   pct=0.0   status=UNCERTAIN  ("Low Confidence")
    minimap2  validated=48  total=50  pct=96.0  status=CONFIRMED

Identical evidence, opposite verdicts -- and the BLAST one is wrong, because
determine_status falls through to UNCERTAIN when the denominator is unknown.
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


def _backdate(path):
    """Age a fixture past the round-3 mid-write stability gate."""
    t = time.time() - 120
    os.utime(path, (t, t))


def _realtime_tree(tmp_path, *, with_stats=True, hits=40, total=50):
    """A realtime-shaped tree: per-pair files, no aggregate yet."""
    blast = tmp_path / "validation" / "blast"
    mm2 = tmp_path / "validation" / "minimap2"
    blast.mkdir(parents=True)
    mm2.mkdir(parents=True)
    (blast / "bc01_taxid263.blast.tsv").write_text("\n".join(
        f"r{i}\tNZ_X\t99.0\t500\t2\t0\t1\t500\t10\t510\t1e-50\t900\t500\t1900000\t95"
        for i in range(hits)) + "\n")
    _backdate(blast / "bc01_taxid263.blast.tsv")
    if with_stats:
        (blast / "bc01_taxid263.blast_stats.json").write_text(json.dumps({
            "sample_id": "bc01", "taxid": 263, "total_reads": total,
            "blast_hits": hits, "hit_rate": hits / total,
            "avg_identity": 99.0, "avg_coverage": 0.95,
            "validation_status": "confirmed",
        }))
    (mm2 / "bc01_taxid263.minimap2_stats.json").write_text(json.dumps({
        "sample_id": "bc01", "taxid": 263, "total_reads": total,
        "mapped_reads": 48, "hit_rate": 0.96, "avg_identity": 99.5,
        "avg_coverage": 0.9, "avg_mapq": 58, "validation_status": "confirmed",
    }))
    return tmp_path


def _by_method(results):
    return {r.validation_method: r for r in results}


class TestBlastStatsAreRead:
    def test_denominator_comes_from_the_stats_file(self, tmp_path):
        res = _by_method(ValidationParser(
            str(_realtime_tree(tmp_path))).get_validation_results())
        blast = res["blast"]
        assert blast.total_reads == 50, (
            "BLAST must take its read count from blast_stats.json, not 0")
        assert blast.percent_validated == pytest.approx(80.0, abs=0.5)

    def test_status_is_not_downgraded_to_uncertain(self, tmp_path):
        res = _by_method(ValidationParser(
            str(_realtime_tree(tmp_path))).get_validation_results())
        assert res["blast"].status == ValidationStatus.CONFIRMED, (
            "a clean BLAST validation must not read as Low Confidence "
            "merely because the aggregate has not been written yet")

    def test_coverage_breadth_surfaces(self, tmp_path):
        res = _by_method(ValidationParser(
            str(_realtime_tree(tmp_path))).get_validation_results())
        assert res["blast"].coverage_breadth == pytest.approx(0.95), (
            "Read Alignment % rendered 0.0 for every disk-derived result")

    def test_both_methods_still_present(self, tmp_path):
        res = _by_method(ValidationParser(
            str(_realtime_tree(tmp_path))).get_validation_results())
        assert set(res) == {"blast", "minimap2"}

    def test_tsv_without_stats_file_still_parses(self, tmp_path):
        # The stats file is an enrichment, not a requirement: a tree with only
        # the TSV must keep working exactly as before.
        res = _by_method(ValidationParser(
            str(_realtime_tree(tmp_path, with_stats=False))
        ).get_validation_results())
        assert "blast" in res
        assert res["blast"].validated_reads == 40

    def test_aggregate_still_wins_when_present(self, tmp_path):
        tree = _realtime_tree(tmp_path)
        (tree / "validation" / "validation_results.json").write_text(json.dumps({
            "validation_method": "both",
            "results": {"bc01": {"263": {
                "taxid": 263, "species": "Francisella tularensis",
                "validation_method": "blast", "kraken_reads": 999,
                "blast_hits": 900, "hit_rate": 0.9, "avg_identity": 98.0,
                "avg_coverage": 0.8, "validation_status": "confirmed"}}},
        }))
        res = _by_method(ValidationParser(str(tree)).get_validation_results())
        assert res["blast"].total_reads == 999, (
            "the aggregate remains authoritative for pairs it covers")
