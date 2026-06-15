"""Gap 4: taxpasta + assembly loaders and Reports-tab panels.

nanometanf publishes taxpasta/*.tsv (standardized profiles) and, when assembly
runs, canonical/assembly/*.json -- neither was surfaced. These tests pin the
loaders (incl. the two taxpasta TSV shapes) and the panels (empty when absent,
populated otherwise; taxpasta taxa labelled from a name map).
"""

import json

import pytest

from nanometa_live.core.utils.taxpasta_loader import load_taxpasta_long
from nanometa_live.core.utils.assembly_loader import load_assembly_stats
from nanometa_live.app.tabs.reports_helpers import (
    build_taxpasta_panel, build_assembly_panel,
)

pytestmark = pytest.mark.unit


class TestTaxpastaLoader:
    def test_per_sample_standardise_shape(self, tmp_path):
        tp = tmp_path / "taxpasta"
        tp.mkdir()
        (tp / "barcode14.tsv").write_text("taxonomy_id\tcount\n263\t3554\n1392\t9\n")
        (tp / "barcode15.tsv").write_text("taxonomy_id\tcount\n263\t12\n")
        rows = load_taxpasta_long(str(tmp_path))
        assert {"sample": "barcode14", "taxid": 263, "count": 3554} in rows
        assert {"sample": "barcode15", "taxid": 263, "count": 12} in rows

    def test_merged_wide_shape(self, tmp_path):
        tp = tmp_path / "taxpasta"
        tp.mkdir()
        (tp / "merged.tsv").write_text("taxonomy_id\tbarcode14\tbarcode15\n263\t3554\t12\n")
        rows = load_taxpasta_long(str(tmp_path))
        assert {"sample": "barcode14", "taxid": 263, "count": 3554} in rows
        assert {"sample": "barcode15", "taxid": 263, "count": 12} in rows

    def test_absent_is_empty(self, tmp_path):
        assert load_taxpasta_long(str(tmp_path)) == []
        assert load_taxpasta_long(None) == []


class TestTaxpastaPanel:
    def test_empty_when_no_rows(self):
        assert build_taxpasta_panel([]) == ""

    def test_labels_taxa_with_name_map(self):
        rows = [
            {"sample": "b14", "taxid": 263, "count": 3554},
            {"sample": "b15", "taxid": 263, "count": 12},
        ]
        panel = build_taxpasta_panel(rows, {263: "Francisella tularensis"})
        text = str(panel)
        assert "Standardized abundance (taxpasta)" in text
        assert "Francisella tularensis" in text
        assert "3,554" in text and "12" in text

    def test_falls_back_to_taxid_without_name(self):
        panel = build_taxpasta_panel([{"sample": "b14", "taxid": 999, "count": 5}], {})
        assert "taxid 999" in str(panel)


class TestAssembly:
    def test_loader_absent_is_empty(self, tmp_path):
        assert load_assembly_stats(str(tmp_path)) == []
        assert load_assembly_stats(None) == []

    def test_loader_reads_stats(self, tmp_path):
        adir = tmp_path / "canonical" / "assembly"
        adir.mkdir(parents=True)
        (adir / "barcode14.assembly_stats.json").write_text(json.dumps({
            "sample_id": "barcode14",
            "summary": {"total_contigs": 2, "total_length": 1900000, "n50": 1800000,
                        "largest_contig": 1800000, "circular_contigs": 1},
            "contigs": [{"name": "contig_1", "length": 1800000, "coverage": 42.0,
                         "is_circular": True}],
        }))
        # a sidecar must be ignored
        (adir / "barcode14.assembly_stats.sidecar.json").write_text("{}")
        out = load_assembly_stats(str(tmp_path))
        assert len(out) == 1
        assert out[0]["sample"] == "barcode14"
        assert out[0]["summary"]["n50"] == 1800000

    def test_panel_empty_and_populated(self, tmp_path):
        assert build_assembly_panel([]) == ""
        panel = build_assembly_panel([{
            "sample": "barcode14",
            "summary": {"total_contigs": 2, "total_length": 1900000, "n50": 1800000,
                        "largest_contig": 1800000, "circular_contigs": 1},
            "contigs": [{"name": "contig_1", "length": 1800000, "coverage": 42.0,
                         "is_circular": True}],
        }])
        text = str(panel)
        assert "Assembly" in text and "barcode14" in text and "contig_1" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
