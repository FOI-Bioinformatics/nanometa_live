"""Tests for C (name-first genome download) and D (kingdom without the NCBI API).

C: an entry with no real NCBI taxid (a name-only / GTDB-custom pseudo-taxid)
must resolve its genome via the species-name GTDB path instead of failing on an
NCBI kingdom/accession lookup.

D: a caller hint (or a GTDB taxonomy string) supplies the kingdom so download
never calls the live NCBI taxonomy API.
"""

from unittest.mock import MagicMock

import pytest

from nanometa_live.core.utils.genome_manager import (
    GenomeDownloadManager,
    _is_real_ncbi_taxid,
    _kingdom_from_gtdb_taxonomy,
    _PSEUDO_TAXID_MIN,
)

pytestmark = pytest.mark.unit


class TestHelpers:
    def test_is_real_ncbi_taxid(self):
        assert _is_real_ncbi_taxid(562) is True
        assert _is_real_ncbi_taxid(1392) is True
        assert _is_real_ncbi_taxid(0) is False
        assert _is_real_ncbi_taxid(-5) is False
        assert _is_real_ncbi_taxid(_PSEUDO_TAXID_MIN + 123) is False  # pseudo band
        assert _is_real_ncbi_taxid("not-a-number") is False

    def test_kingdom_from_gtdb_taxonomy(self):
        assert _kingdom_from_gtdb_taxonomy("d__Bacteria;p__Bacillota;s__X") == "Bacteria"
        assert _kingdom_from_gtdb_taxonomy("d__Archaea;p__Y") == "Archaea"
        assert _kingdom_from_gtdb_taxonomy("") is None
        assert _kingdom_from_gtdb_taxonomy(None) is None
        assert _kingdom_from_gtdb_taxonomy("Escherichia coli") is None


def _manager(tmp_path):
    mgr = GenomeDownloadManager(cache_dir=str(tmp_path))
    mgr.offline_mode = False
    mgr.has_genome = MagicMock(return_value=False)
    fasta = tmp_path / "out.fasta"
    fasta.write_text(">seq\nACGT\n")
    mgr._download_ncbi_genome = MagicMock(return_value=fasta)
    return mgr, fasta


class TestNameFirstDownload:
    def test_pseudo_taxid_uses_gtdb_name_path_and_skips_ncbi(self, tmp_path):
        mgr, fasta = _manager(tmp_path)
        mgr.get_kingdom = MagicMock(side_effect=AssertionError("NCBI kingdom must not be queried for a pseudo-taxid"))
        mgr.fetch_ncbi_accession = MagicMock(side_effect=AssertionError("NCBI accession must not be queried for a pseudo-taxid"))
        mgr.fetch_gtdb_accession = MagicMock(return_value=("GCF_000001", {"gtdbTaxonomy": "d__Bacteria"}))

        pseudo = _PSEUDO_TAXID_MIN + 57_967_092
        path = mgr.download_genome(pseudo, "Bacillus anthracis")

        assert path == fasta
        mgr.fetch_gtdb_accession.assert_called_once_with("Bacillus anthracis")

    def test_kingdom_hint_skips_ncbi_kingdom_lookup_for_real_taxid(self, tmp_path):
        mgr, fasta = _manager(tmp_path)
        mgr.get_kingdom = MagicMock(side_effect=AssertionError("kingdom hint must short-circuit the NCBI lookup"))
        mgr.fetch_gtdb_accession = MagicMock(return_value=("GCF_000002", {}))

        path = mgr.download_genome(1392, "Bacillus anthracis", kingdom="Bacteria")

        assert path == fasta
        mgr.fetch_gtdb_accession.assert_called_once()

    def test_gtdb_taxonomy_string_supplies_kingdom(self, tmp_path):
        mgr, fasta = _manager(tmp_path)
        mgr.get_kingdom = MagicMock(side_effect=AssertionError("gtdb_taxonomy must supply the kingdom"))
        mgr.fetch_gtdb_accession = MagicMock(return_value=("GCF_000003", {}))

        path = mgr.download_genome(1392, "Methanobrevibacter smithii",
                                   gtdb_taxonomy="d__Archaea;p__Methanobacteriota")

        assert path == fasta
        mgr.fetch_gtdb_accession.assert_called_once()

    def test_real_taxid_no_hint_still_queries_ncbi_kingdom(self, tmp_path):
        # Regression guard: the normal NCBI path is unchanged when no hint and a
        # real taxid is given.
        mgr, fasta = _manager(tmp_path)
        mgr.get_kingdom = MagicMock(return_value="Bacteria")
        mgr.fetch_gtdb_accession = MagicMock(return_value=("GCF_000004", {}))

        path = mgr.download_genome(562, "Escherichia coli")

        assert path == fasta
        mgr.get_kingdom.assert_called_once_with(562)
