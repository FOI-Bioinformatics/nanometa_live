"""Gap 1 (richer validation detail): the parser surfaces reference identity/size
and enriches the identity range from blast.tsv, and the result card renders them.

The aggregate validation_results.json carries only mean identity + coverage and
previously dropped ref_name/ref_length; the per-read identity range and alignment
length live in the per-(sample,taxid) blast.tsv. These tests pin that the parser
now captures the reference fields and enriches the range, and that the card shows
the detail line.
"""

import json

import pytest

from nanometa_live.core.parsers.blast_validation_parser import ValidationParser
from nanometa_live.app.layouts.validation_layout import create_validation_result_card

pytestmark = pytest.mark.unit


def _write_results(tmp_path, *, with_tsv: bool):
    vdir = tmp_path / "validation"
    (vdir / "blast").mkdir(parents=True)
    agg = {
        "validation_method": "blast",
        "timestamp": "2026-06-15T00:00:00Z",
        "results": {
            "barcode14": {
                "263": {
                    "taxid": 263, "species": "Francisella tularensis",
                    "validation_method": "blast",
                    "kraken_reads": 100, "blast_hits": 95, "hit_rate": 0.95,
                    "avg_identity": 97.0, "avg_coverage": 0.91,
                    "ref_name": "NZ_CP009607.1", "ref_length": 1870206,
                }
            }
        },
    }
    (vdir / "validation_results.json").write_text(json.dumps(agg))
    if with_tsv:
        # outfmt 6, 12 cols: qseqid sseqid pident length mismatch gapopen
        # qstart qend sstart send evalue bitscore
        rows = [
            "r1\tNZ_CP009607.1\t99.0\t400\t4\t0\t1\t400\t1\t400\t0.0\t700",
            "r2\tNZ_CP009607.1\t95.0\t300\t15\t0\t1\t300\t1\t300\t0.0\t500",
        ]
        (vdir / "blast" / "barcode14_taxid263.blast.tsv").write_text("\n".join(rows) + "\n")
    return tmp_path


class TestParserEnrichment:
    def test_reference_fields_captured_from_aggregate(self, tmp_path):
        _write_results(tmp_path, with_tsv=False)
        results = ValidationParser(str(tmp_path)).get_validation_results()
        r = next(x for x in results if x.taxid == 263 and x.validation_method == "blast")
        assert r.reference_accession == "NZ_CP009607.1"
        assert r.reference_length == 1870206

    def test_identity_range_enriched_from_blast_tsv(self, tmp_path):
        _write_results(tmp_path, with_tsv=True)
        results = ValidationParser(str(tmp_path)).get_validation_results()
        r = next(x for x in results if x.taxid == 263 and x.validation_method == "blast")
        # min/max identity + mean alignment length come from the tsv (95.0..99.0).
        assert r.percent_identity_min == pytest.approx(95.0)
        assert r.percent_identity_max == pytest.approx(99.0)
        assert r.alignment_length_mean == pytest.approx(350.0)

    def test_no_tsv_leaves_range_zero(self, tmp_path):
        _write_results(tmp_path, with_tsv=False)
        results = ValidationParser(str(tmp_path)).get_validation_results()
        r = next(x for x in results if x.taxid == 263 and x.validation_method == "blast")
        assert r.percent_identity_min == 0.0 and r.percent_identity_max == 0.0


class TestCardDetailLine:
    def test_card_renders_detail_when_populated(self):
        card = create_validation_result_card(
            species="Francisella tularensis", taxid=263, status="confirmed",
            percent_validated=95.0, percent_identity=97.0, total_reads=100,
            validated_reads=95, coverage=0.91, sample_id="barcode14",
            percent_identity_min=95.0, percent_identity_max=99.0,
            alignment_length_mean=350.0, reference_accession="NZ_CP009607.1",
            reference_length=1870206,
        )
        text = str(card)
        assert "Identity range 95.0-99.0%" in text
        assert "Mean align 350 bp" in text
        assert "NZ_CP009607.1" in text and "1.87 Mbp" in text

    def test_card_hides_detail_when_absent(self):
        card = create_validation_result_card(
            species="X", taxid=1, status="no_data", percent_validated=0,
            percent_identity=0, total_reads=0, validated_reads=0,
        )
        # No identity range / reference text when nothing is populated.
        assert "Identity range" not in str(card)
        assert "Ref:" not in str(card)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
