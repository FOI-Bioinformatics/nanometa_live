"""
Tests for the output-collision / run-fingerprint helpers in
core/workflow/backend_manager.py (was 37% covered).

These are @staticmethods (no pipeline needed): detect_existing_results,
compute_input_fingerprint, read/write_run_metadata, fingerprint_matches,
archive_existing_results. They drive the collision modal documented in CLAUDE.md.
"""

import os

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


class TestDetectExistingResults:
    def test_empty_and_missing(self, tmp_path):
        assert BackendManager.detect_existing_results("") == []
        assert BackendManager.detect_existing_results(str(tmp_path / "nope")) == []

    def test_only_nonempty_subdirs_count(self, tmp_path):
        (tmp_path / "kraken2").mkdir()
        (tmp_path / "kraken2" / "r.txt").write_text("x")
        (tmp_path / "fastp").mkdir()  # empty -> ignored
        found = BackendManager.detect_existing_results(str(tmp_path))
        assert found == ["kraken2"]


class TestComputeInputFingerprint:
    BASE = {
        "nanopore_output_directory": "/data/in",
        "sample_handling": "by_barcode",
        "processing_mode": "batch",
        "kraken_db": "/db",
    }

    def test_empty_config(self):
        assert BackendManager.compute_input_fingerprint({}) == ""

    def test_stable_and_order_independent(self):
        fp1 = BackendManager.compute_input_fingerprint(dict(self.BASE))
        reordered = {k: self.BASE[k] for k in reversed(list(self.BASE))}
        assert fp1 == BackendManager.compute_input_fingerprint(reordered)

    def test_runtime_only_key_does_not_change_fingerprint(self):
        fp1 = BackendManager.compute_input_fingerprint(dict(self.BASE))
        fp2 = BackendManager.compute_input_fingerprint({**self.BASE, "blast_validation": True})
        assert fp1 == fp2

    def test_input_key_changes_fingerprint(self):
        fp1 = BackendManager.compute_input_fingerprint(dict(self.BASE))
        fp2 = BackendManager.compute_input_fingerprint({**self.BASE, "kraken_db": "/other"})
        assert fp1 != fp2


class TestRunMetadata:
    CONFIG = {"nanopore_output_directory": "/in", "kraken_db": "/db",
              "sample_handling": "single_sample", "processing_mode": "realtime"}

    def test_write_then_read_round_trip(self, tmp_path):
        BackendManager.write_run_metadata(str(tmp_path), self.CONFIG)
        data = BackendManager.read_run_metadata(str(tmp_path))
        assert data is not None
        assert data["fingerprint"] == BackendManager.compute_input_fingerprint(self.CONFIG)
        assert data["inputs"]["kraken_db"] == "/db"

    def test_read_missing_returns_none(self, tmp_path):
        assert BackendManager.read_run_metadata(str(tmp_path)) is None

    def test_read_malformed_returns_none(self, tmp_path):
        (tmp_path / BackendManager.RUN_METADATA_FILENAME).write_text("{not json")
        assert BackendManager.read_run_metadata(str(tmp_path)) is None


class TestFingerprintMatches:
    CONFIG = {"nanopore_output_directory": "/in", "kraken_db": "/db",
              "sample_handling": "single_sample", "processing_mode": "realtime"}

    def test_none_without_prior_metadata(self, tmp_path):
        assert BackendManager.fingerprint_matches(str(tmp_path), self.CONFIG) is None

    def test_true_when_same_input(self, tmp_path):
        BackendManager.write_run_metadata(str(tmp_path), self.CONFIG)
        assert BackendManager.fingerprint_matches(str(tmp_path), self.CONFIG) is True

    def test_false_when_input_changed(self, tmp_path):
        BackendManager.write_run_metadata(str(tmp_path), self.CONFIG)
        changed = {**self.CONFIG, "kraken_db": "/different"}
        assert BackendManager.fingerprint_matches(str(tmp_path), changed) is False


class TestArchiveExistingResults:
    def test_nothing_to_archive(self, tmp_path):
        assert BackendManager.archive_existing_results(str(tmp_path)) is None

    def test_moves_subdirs_into_timestamped_archive(self, tmp_path):
        (tmp_path / "kraken2").mkdir()
        (tmp_path / "kraken2" / "r.txt").write_text("x")
        archive = BackendManager.archive_existing_results(str(tmp_path))
        assert archive is not None
        assert os.path.isdir(archive)
        # Original moved into the archive; no longer at the top level.
        assert not (tmp_path / "kraken2").exists()
        assert (os.path.join(archive, "kraken2", "r.txt"))
        assert os.path.isfile(os.path.join(archive, "kraken2", "r.txt"))
