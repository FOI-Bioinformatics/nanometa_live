"""
Tests for the previously-untested auto_detect functions.

test_auto_detect.py covers detect_sample_handling / find_sample_subdirs /
get_barcode_list / detect_file_format. This adds is_barcode_named,
detect_kraken_taxonomy (name hints, seqid map, inspect patterns, fallback) and
estimate_update_interval (batch vs realtime, clamping). File mtimes are
backdated rather than slept on.

Note: detect_kraken_taxonomy inspects the db's *parent* directory name for
'gtdb'/'ncbi' hints, so tests place the db under a neutrally-named intermediate
directory rather than directly in tmp_path (whose name echoes the test name).
"""

import os

import pytest

from nanometa_live.core.utils.auto_detect import (
    detect_kraken_taxonomy,
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


class TestDetectKrakenTaxonomy:
    def test_missing_db_defaults_gtdb(self, tmp_path):
        ttype, _ = detect_kraken_taxonomy(str(tmp_path / "nope"))
        assert ttype == "gtdb"

    def test_name_hint_gtdb(self, tmp_path):
        db = _dbroot(tmp_path) / "kraken2_gtdb_bac120"
        db.mkdir()
        assert detect_kraken_taxonomy(str(db))[0] == "gtdb"

    def test_name_hint_ncbi(self, tmp_path):
        db = _dbroot(tmp_path) / "standard_ncbi"
        db.mkdir()
        assert detect_kraken_taxonomy(str(db))[0] == "ncbi"

    def test_seqid_map_gtdb_accessions(self, tmp_path):
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        (db / "seqid2taxid.map").write_text(
            "".join(f"GB_GCA_{i:06d}.1\t{i}\n" for i in range(60))
        )
        assert detect_kraken_taxonomy(str(db))[0] == "gtdb"

    def test_inspect_ncbi_naming(self, tmp_path):
        root = _dbroot(tmp_path)
        db = root / "customdb"
        db.mkdir()
        # globbed from the db's parent directory (root)
        (root / "db_inspect.txt").write_text(
            "50.0\t100\t100\tS\t562\tEscherichia coli\n"
        )
        assert detect_kraken_taxonomy(str(db))[0] == "ncbi"

    def test_unmarked_db_defaults_gtdb(self, tmp_path):
        db = _dbroot(tmp_path) / "customdb"
        db.mkdir()
        ttype, reason = detect_kraken_taxonomy(str(db))
        assert ttype == "gtdb"
        assert "could not determine" in reason.lower()


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
