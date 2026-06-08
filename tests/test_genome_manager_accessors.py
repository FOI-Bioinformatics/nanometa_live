"""
Tests for the filesystem accessors of core/utils/genome_manager.py (was 14%).

The download/network/subprocess code is out of scope here (it belongs under
@pytest.mark.slow integration); this covers the pure-state surface that the GUI
relies on: genome/BLAST-db presence, missing-genome filtering, per-entry status,
statistics, deletion, metadata scanning, and GenomeMetadata serialization. All
against a tmp cache_dir in offline mode (no network).
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.utils.genome_manager import (
    GenomeDownloadManager,
    GenomeMetadata,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def manager(tmp_path):
    cache = tmp_path / "cache"
    (cache / "genomes").mkdir(parents=True)
    (cache / "blast").mkdir(parents=True)
    # Pre-create genome files so __init__'s _scan_existing_genomes registers them.
    (cache / "genomes" / "562.fasta").write_text(">seq\nACGTACGT\n")
    (cache / "genomes" / "1280.fasta").write_text(">seq\nTTTT\n")
    # _scan_existing_genomes auto-builds BLAST dbs for scanned genomes when
    # makeblastdb is on PATH; stub it out so blast-db presence is controlled
    # explicitly by the test, not the environment.
    with patch.object(GenomeDownloadManager, "build_blast_db", lambda self, taxid: False):
        mgr = GenomeDownloadManager(cache_dir=str(cache), offline_mode=True)
    # A BLAST db (just the .nhr marker) for taxid 562 only, added after the scan.
    (cache / "blast" / "562.fasta.nhr").write_text("x")
    return mgr


class TestGenomePresence:
    def test_has_genome_true_for_present(self, manager):
        assert manager.has_genome(562) is True
        assert manager.get_genome_path(562) is not None

    def test_has_genome_false_for_absent(self, manager):
        assert manager.has_genome(99999) is False
        assert manager.get_genome_path(99999) is None

    def test_has_blast_db(self, manager):
        assert manager.has_blast_db(562) is True
        assert manager.has_blast_db(1280) is False  # genome but no .nhr

    def test_get_last_error_none_by_default(self, manager):
        assert manager.get_last_error(562) is None


class TestMissingAndStatus:
    def test_get_missing_genomes(self, manager):
        entries = [
            {"taxid": 562, "name": "E. coli"},
            {"taxid": 99999, "name": "Absent"},
        ]
        missing = manager.get_missing_genomes(entries)
        assert [e["taxid"] for e in missing] == [99999]

    def test_get_all_genome_status(self, manager):
        status = manager.get_all_genome_status([{"taxid": 562}, {"taxid": 1280}])
        assert status[562] == {"genome": True, "blast_db": True}
        assert status[1280] == {"genome": True, "blast_db": False}


class TestBlastDbStatus:
    """Operator feedback #1/#7: missing BLAST DBs leave BLAST empty while
    minimap2 (FASTA-direct) still works; the status must distinguish present /
    missing / no-genome so the gap is explainable."""

    def test_blast_db_status_partitions_taxids(self, manager):
        status = manager.blast_db_status([562, 1280, 99999])
        assert status["present"] == [562]      # genome + .nhr
        assert status["missing"] == [1280]     # genome, no BLAST DB
        assert status["no_genome"] == [99999]  # nothing on disk

    def test_detailed_report_counts_present_built_and_failed(self, manager):
        # 562 already has a DB (already_present); 1280 has a genome but no DB.
        # Stub the actual build + makeblastdb presence so the test is
        # deterministic and offline regardless of the host toolchain.
        def _ok(self, taxid):
            (manager.blast_dir / f"{taxid}.fasta.nhr").write_text("x")
            return True, None
        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/makeblastdb"), \
                patch.object(type(manager), "_build_blast_db_with_reason", _ok):
            report = manager.build_missing_blast_dbs_detailed(retry=True)
        assert report["already_present"] == 1
        assert report["built"] == 1
        assert report["failed"] == []

    def test_detailed_report_records_failures_with_reason(self, manager):
        def _fail(self, taxid):
            return False, "bad FASTA"
        with patch("nanometa_live.core.utils.genome_manager.shutil.which",
                   return_value="/usr/bin/makeblastdb"), \
                patch.object(type(manager), "_build_blast_db_with_reason", _fail):
            report = manager.build_missing_blast_dbs_detailed(retry=False)
        assert report["built"] == 0
        assert len(report["failed"]) == 1
        assert report["failed"][0]["taxid"] == 1280
        assert report["failed"][0]["reason"] == "bad FASTA"


class TestStatistics:
    def test_counts_scanned_genomes(self, manager):
        stats = manager.get_statistics()
        assert stats["total_genomes"] == 2
        assert stats["with_blast_db"] == 1
        assert "by_kingdom" in stats and "by_source" in stats


class TestDeletion:
    def test_delete_genome_removes_file_and_metadata(self, manager):
        assert manager.has_genome(1280) is True
        assert manager.delete_genome(1280) is True
        assert manager.has_genome(1280) is False
        assert manager.get_statistics()["total_genomes"] == 1


class TestGenomeMetadata:
    def test_to_from_dict_round_trip(self):
        meta = GenomeMetadata(
            taxid=562, species_name="Escherichia coli", accession="GCF_000005845.2",
            source="ncbi", kingdom="Bacteria", fasta_path="/g/562.fasta",
            file_size=1234,
        )
        restored = GenomeMetadata.from_dict(meta.to_dict())
        assert restored == meta
