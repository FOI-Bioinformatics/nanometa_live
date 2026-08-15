"""
Tests for the previously-untested auto_detect functions.

test_auto_detect.py covers detect_sample_handling / find_sample_subdirs /
get_barcode_list / detect_file_format. This adds is_barcode_named and
estimate_update_interval (batch vs realtime, clamping). File mtimes are
backdated rather than slept on.

The taxonomy-detection tests here previously exercised detect_kraken_taxonomy,
which has been replaced by two-axis detection on the database index. Their
fixtures survive against the sidecar-file fallback that took over the signals
the index cannot see; see tests/test_database_profile.py for the name-based
axis. Databases are still placed under a neutrally-named intermediate
directory, now to prove the directory name is NOT consulted.
"""

import os

import pytest

from nanometa_live.core.taxonomy.database_indexer import (
    DatabaseIndexBuilder,
    _nomenclature_hints_from_files,
)
from nanometa_live.core.taxonomy.database_profile import Nomenclature
from nanometa_live.core.utils.auto_detect import (
    estimate_update_interval,
    is_barcode_named,
)

pytestmark = pytest.mark.unit


def _dbroot(tmp_path):
    root = tmp_path / "dbroot"
    root.mkdir()
    return root


class TestIsBarcodeNamed:
    @pytest.mark.parametrize("name,expected", [
        ("barcode01", True), ("barcode99", True), ("barcode09", True),
        ("sample1", False), ("Turex", False), ("unclassified", False),
    ])
    def test_pattern(self, name, expected):
        assert is_barcode_named(name) is expected


class TestNomenclatureHintsFromFiles:
    """Sidecar-file signals, migrated from the removed detect_kraken_taxonomy.

    These two files carry evidence the inspect dump does not, so they remain
    the fallback when taxon names alone are inconclusive. The fixtures are
    kept from the original tests because they are the best coverage in the
    repo for the gzipped and accession-prefix cases.

    Two behaviours from the old detector are deliberately NOT carried over and
    are asserted against below: guessing from the directory name, and
    defaulting to GTDB when nothing matched.
    """

    def test_seqid_map_gtdb_accessions(self, tmp_path):
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        (db / "seqid2taxid.map").write_text(
            "".join(f"GB_GCA_{i:06d}.1\t{i}\n" for i in range(60))
        )
        nom, evidence = _nomenclature_hints_from_files(db)
        assert nom is Nomenclature.GTDB
        assert "seqid2taxid" in evidence

    def test_gzipped_seqid_map_gtdb_accessions(self, tmp_path):
        import gzip
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        with gzip.open(db / "seqid2taxid.map.gz", "wt") as fh:
            fh.write("".join(f"GB_GCA_{i:06d}.1\t{i}\n" for i in range(60)))
        assert _nomenclature_hints_from_files(db)[0] is Nomenclature.GTDB

    def test_a_few_gtdb_accessions_are_not_enough(self, tmp_path):
        """An NCBI database may legitimately include some GTDB-sourced rows."""
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        (db / "seqid2taxid.map").write_text(
            "".join(f"GB_GCA_{i:06d}.1\t{i}\n" for i in range(5))
            + "".join(f"NC_{i:06d}.1\t{i}\n" for i in range(100))
        )
        assert _nomenclature_hints_from_files(db)[0] is Nomenclature.UNKNOWN

    def test_library_report_gtdb(self, tmp_path):
        db = _dbroot(tmp_path) / "customdb"
        (db / "library").mkdir(parents=True)
        (db / "library" / "library_report.tsv").write_text(
            "d__Bacteria;p__Pseudomonadota;s__Escherichia coli\n"
        )
        nom, evidence = _nomenclature_hints_from_files(db)
        assert nom is Nomenclature.GTDB
        assert "library report" in evidence

    def test_library_report_ncbi(self, tmp_path):
        db = _dbroot(tmp_path) / "customdb"
        (db / "library").mkdir(parents=True)
        (db / "library" / "library_report.tsv").write_text(
            "cellular organisms; Bacteria; Pseudomonadota\n"
        )
        assert _nomenclature_hints_from_files(db)[0] is Nomenclature.NCBI

    def test_directory_name_is_no_longer_a_signal(self, tmp_path):
        """The old detector guessed from the path; "/data/gtdb_and_ncbi/" broke it."""
        db = _dbroot(tmp_path) / "kraken2_gtdb_bac120"
        db.mkdir()
        assert _nomenclature_hints_from_files(db)[0] is Nomenclature.UNKNOWN

    def test_unmarked_database_stays_unknown(self, tmp_path):
        """No more defaulting to GTDB.

        UNKNOWN is honest and safe: it makes callers query both APIs and
        generate the GTDB name variants anyway.
        """
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        nom, evidence = _nomenclature_hints_from_files(db)
        assert nom is Nomenclature.UNKNOWN
        assert "no nomenclature markers" in evidence


class TestNomenclatureEndToEnd:
    """Through the real build_index path, not the helper in isolation."""

    def test_gzipped_inspect_with_gtdb_suffixes(self, tmp_path):
        """A remapped database shipping only inspect.txt.gz.

        Its GTDB genus suffixes are the only giveaway, and this must be a
        positive detection rather than a fallthrough.
        """
        import gzip
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        with gzip.open(db / "inspect.txt.gz", "wt") as fh:
            fh.write("0.1\t100\t0\tG\t4007157\tBurkholderia\n")
            for i, sp in enumerate(("ambifaria", "lata", "cepacia")):
                fh.write(f"0.05\t50\t50\tS\t400715{i}\tBurkholderia_A {sp}\n")
        index = DatabaseIndexBuilder().build_index(str(db))
        assert index.profile.nomenclature is Nomenclature.GTDB
        assert index.profile.generates_gtdb_variants is True

    def test_seqid_map_rescues_an_otherwise_unreadable_database(self, tmp_path):
        """Names give nothing; the sidecar file decides."""
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        (db / "inspect.txt").write_text(
            "".join(f"0.1\t10\t10\tS\t{900000 + i}\tcontig{i:05d}\n"
                    for i in range(20))
        )
        (db / "seqid2taxid.map").write_text(
            "".join(f"RS_GCF_{i:06d}.1\t{i}\n" for i in range(60))
        )
        index = DatabaseIndexBuilder().build_index(str(db))
        assert index.profile.nomenclature is Nomenclature.GTDB



class TestEstimateUpdateInterval:
    def _fastqs(self, d, n, age_seconds=0):
        for i in range(n):
            f = d / f"r{i}.fastq"
            f.write_text("@r\nACGT\n+\nIIII\n")
            if age_seconds:
                old = os.path.getmtime(f) - age_seconds
                os.utime(f, (old, old))

    def test_missing_dir(self, tmp_path):
        interval, _ = estimate_update_interval(str(tmp_path / "nope"))
        assert interval == 30

    def test_empty_dir_recommends_longer(self, tmp_path):
        interval, reason = estimate_update_interval(str(tmp_path))
        assert interval == 60
        assert "No files" in reason

    def test_old_files_are_batch_mode(self, tmp_path):
        self._fastqs(tmp_path, 3, age_seconds=3600)  # 1h old
        interval, reason = estimate_update_interval(str(tmp_path))
        assert interval == 60
        assert "batch" in reason.lower()

    def test_recent_files_clamped_to_min(self, tmp_path):
        # Freshly written files (~0s apart) -> recommended clamps to min_interval.
        self._fastqs(tmp_path, 3)
        interval, _ = estimate_update_interval(str(tmp_path), min_interval=10)
        assert interval == 10
