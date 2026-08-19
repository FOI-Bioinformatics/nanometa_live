"""Aggregate-seeded minimap2 results must not zero out fields the aggregate lacks.

nanometanf's session-end ``validation_results.json`` carries no ``avg_mapq``
(and often no ``ref_name``/``ref_length``) for its minimap2 entries, while the
per-pair ``*.minimap2_stats.json`` on disk does. The parser treats the
aggregate as authoritative for the tuples it lists and only ADDS missing
tuples from disk, so an aggregate-seeded entry kept ``avg_mapq=0.0`` even
though the sibling stats file said 59.96 -- and the Coverage tab's card
rendered "Mapping Confidence 0 / 60" under a "30+ reliable" hint. For an
operator that reads as "the mapping is unreliable", the opposite of the
truth. Found on the 2026-08-19 realtime sweep (barcode11 F. t. holarctica:
28,321 reads at MAPQ 60 shown as 0).

The disk scan now backfills fields the aggregate never carries into the
existing coverage-class entry instead of only deduping against it.
"""

import json

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.parsers.blast_validation_parser import BlastValidationParser


AGGREGATE = {
    "pipeline_version": "1.7.0",
    "validation_method": "both",
    "timestamp": "2026-08-19T15:40:00",
    "thresholds": {},
    "results": {
        "barcode11": {
            "4007187": {
                "taxid": 4007187,
                "species": "Francisella tularensis subsp. holarctica",
                "validation_method": "blast",
                "kraken_reads": 28718,
                "extracted_reads": 28718,
                "blast_hits": 28321,
                "hit_rate": 0.986,
                "avg_identity": 97.9,
                "avg_coverage": 0.94,
                "validation_status": "confirmed",
                # minimap2 sub-fields, but NO avg_mapq / ref_name / ref_length
                "minimap2_mapped": 28321,
                "minimap2_hit_rate": 0.986,
                "minimap2_identity": 99.8,
                "minimap2_status": "confirmed",
            }
        }
    },
    "summary": {},
}

STATS = {
    "sample_id": "barcode11",
    "taxid": 4007187,
    "species": "Francisella tularensis subsp. holarctica",
    "validation_method": "minimap2",
    "total_reads": 28718,
    "mapped_reads": 28321,
    "hit_rate": 0.986,
    "avg_mapq": 59.96,
    "avg_identity": 99.81,
    "avg_coverage": 0.91,
    "validation_status": "confirmed",
    "ref_name": "NZ_CP009607.1",
    "ref_length": 1870206,
}


@pytest.fixture()
def results_dir(tmp_path):
    vdir = tmp_path / "validation"
    (vdir / "minimap2").mkdir(parents=True)
    (vdir / "validation_results.json").write_text(json.dumps(AGGREGATE))
    (vdir / "minimap2" / "barcode11_taxid4007187.minimap2_stats.json").write_text(
        json.dumps(STATS)
    )
    return tmp_path


def _minimap2_entries(results):
    return [r for r in results
            if getattr(r, "validation_method", None) in ("minimap2", "both")]


class TestMapqBackfill:
    def test_aggregate_entry_gains_the_on_disk_mapq(self, results_dir):
        parser = BlastValidationParser(str(results_dir))
        mm2 = _minimap2_entries(parser.get_validation_results())
        assert len(mm2) == 1, "backfill must not create a duplicate entry"
        assert mm2[0].avg_mapq == pytest.approx(59.96), (
            "the card renders 'Mapping Confidence 0 / 60' for a MAPQ-60 "
            "mapping when the aggregate's zero shadows the stats file"
        )

    def test_reference_fields_backfilled(self, results_dir):
        parser = BlastValidationParser(str(results_dir))
        mm2 = _minimap2_entries(parser.get_validation_results())[0]
        assert mm2.reference_accession == "NZ_CP009607.1"
        assert mm2.reference_length == 1870206

    def test_aggregate_numbers_still_win_where_it_speaks(self, results_dir):
        # The aggregate stays authoritative for what it DOES carry.
        parser = BlastValidationParser(str(results_dir))
        mm2 = _minimap2_entries(parser.get_validation_results())[0]
        assert mm2.total_reads == 28718
        assert mm2.percent_identity_mean == pytest.approx(99.8)

    def test_disk_only_pair_still_added(self, tmp_path):
        vdir = tmp_path / "validation" / "minimap2"
        vdir.mkdir(parents=True)
        (vdir / "barcode11_taxid4007187.minimap2_stats.json").write_text(
            json.dumps(STATS))
        parser = BlastValidationParser(str(tmp_path))
        mm2 = _minimap2_entries(parser.get_validation_results())
        assert len(mm2) == 1
        assert mm2[0].avg_mapq == pytest.approx(59.96)
