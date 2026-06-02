"""
Focused unit tests for the safety-critical run-metadata logic in
core/workflow/backend_manager.py.

Covers the @staticmethod helpers that drive the output-collision modal and
the per-run fingerprint persisted to ``<outdir>/.nanometa.run.json``:
compute_input_fingerprint, write_run_metadata, read_run_metadata,
fingerprint_matches, archive_existing_results.

Complements (does not duplicate) tests/test_backend_manager_collision.py by
focusing on round-trip durability, atomicity/crash-safety of the metadata
write, corrupt-file resilience, and the same-second archive collision path.
All filesystem interaction uses real tmp_path dirs (no FS mocking).
"""

import json
import os

import pytest

import nanometa_live.core.utils.atomic_write as atomic_write_mod
from nanometa_live.core.workflow import backend_manager as bm_mod
from nanometa_live.core.workflow.backend_manager import BackendManager

pytestmark = pytest.mark.unit


BASE_CONFIG = {
    "nanopore_output_directory": "/data/in",
    "sample_handling": "by_barcode",
    "processing_mode": "batch",
    "kraken_db": "/db/kraken2",
}


class TestRoundTrip:
    def test_write_then_read_returns_same_fingerprint_and_inputs(self, tmp_path):
        BackendManager.write_run_metadata(str(tmp_path), BASE_CONFIG)
        data = BackendManager.read_run_metadata(str(tmp_path))

        assert data is not None
        assert data["fingerprint"] == BackendManager.compute_input_fingerprint(
            BASE_CONFIG
        )
        # Every fingerprint key is preserved verbatim in the inputs dict.
        for key in BackendManager._FINGERPRINT_KEYS:
            assert data["inputs"][key] == BASE_CONFIG[key]
        # And a written_at timestamp is recorded.
        assert "written_at" in data


class TestComputeInputFingerprint:
    def test_empty_config_returns_empty_string(self):
        assert BackendManager.compute_input_fingerprint({}) == ""
        assert BackendManager.compute_input_fingerprint(None) == ""

    def test_order_independent(self):
        fp1 = BackendManager.compute_input_fingerprint(dict(BASE_CONFIG))
        reordered = {k: BASE_CONFIG[k] for k in reversed(list(BASE_CONFIG))}
        fp2 = BackendManager.compute_input_fingerprint(reordered)
        assert fp1 == fp2

    def test_runtime_only_keys_excluded(self):
        fp_base = BackendManager.compute_input_fingerprint(dict(BASE_CONFIG))
        # Runtime-only knobs must not perturb the input fingerprint.
        fp_interval = BackendManager.compute_input_fingerprint(
            {**BASE_CONFIG, "update_interval_seconds": 5}
        )
        fp_blast = BackendManager.compute_input_fingerprint(
            {**BASE_CONFIG, "blast_validation": False}
        )
        assert fp_base == fp_interval == fp_blast

    def test_input_key_change_alters_fingerprint(self):
        fp_base = BackendManager.compute_input_fingerprint(dict(BASE_CONFIG))
        fp_changed = BackendManager.compute_input_fingerprint(
            {**BASE_CONFIG, "kraken_db": "/db/other"}
        )
        assert fp_base != fp_changed


class TestReadRunMetadataResilience:
    def test_missing_dir_returns_none(self, tmp_path):
        assert BackendManager.read_run_metadata(str(tmp_path / "nope")) is None

    def test_empty_outdir_arg_returns_none(self):
        assert BackendManager.read_run_metadata("") is None

    def test_missing_file_returns_none(self, tmp_path):
        assert BackendManager.read_run_metadata(str(tmp_path)) is None

    def test_corrupt_truncated_json_returns_none_and_does_not_raise(self, tmp_path):
        path = tmp_path / BackendManager.RUN_METADATA_FILENAME
        path.write_bytes(b'{"fingerprint": "abc", "inp')  # truncated garbage
        # Must never raise; a corrupt file is treated as "no prior metadata".
        assert BackendManager.read_run_metadata(str(tmp_path)) is None

    def test_non_dict_json_returns_none(self, tmp_path):
        path = tmp_path / BackendManager.RUN_METADATA_FILENAME
        path.write_text("[1, 2, 3]")  # valid json, wrong shape
        assert BackendManager.read_run_metadata(str(tmp_path)) is None


class TestWriteRunMetadataAtomicity:
    def test_write_to_missing_dir_is_noop(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        # Should not raise and should not create anything.
        BackendManager.write_run_metadata(str(missing), BASE_CONFIG)
        assert not missing.exists()

    def test_prior_file_intact_when_write_fails_midway(self, tmp_path, monkeypatch):
        # Lay down a valid prior metadata file.
        BackendManager.write_run_metadata(str(tmp_path), BASE_CONFIG)
        path = tmp_path / BackendManager.RUN_METADATA_FILENAME
        original_bytes = path.read_bytes()
        assert original_bytes  # sanity

        # Simulate a crash mid-write inside the atomic writer.
        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(atomic_write_mod, "atomic_write_json", boom)

        changed = {**BASE_CONFIG, "kraken_db": "/db/totally-different"}
        # Must swallow the OSError (log + return), never propagate.
        BackendManager.write_run_metadata(str(tmp_path), changed)

        # The prior file content is untouched -- temp+replace guarantees no
        # partial overwrite of the existing valid metadata.
        assert path.read_bytes() == original_bytes
        data = json.loads(path.read_text())
        assert data["fingerprint"] == BackendManager.compute_input_fingerprint(
            BASE_CONFIG
        )


class TestFingerprintMatches:
    def test_none_without_prior_metadata(self, tmp_path):
        assert BackendManager.fingerprint_matches(str(tmp_path), BASE_CONFIG) is None

    def test_true_on_identical_config(self, tmp_path):
        BackendManager.write_run_metadata(str(tmp_path), BASE_CONFIG)
        assert (
            BackendManager.fingerprint_matches(str(tmp_path), BASE_CONFIG) is True
        )

    def test_false_on_changed_input_key(self, tmp_path):
        BackendManager.write_run_metadata(str(tmp_path), BASE_CONFIG)
        changed = {**BASE_CONFIG, "nanopore_output_directory": "/data/other"}
        assert BackendManager.fingerprint_matches(str(tmp_path), changed) is False

    def test_true_on_runtime_only_change(self, tmp_path):
        BackendManager.write_run_metadata(str(tmp_path), BASE_CONFIG)
        runtime_changed = {**BASE_CONFIG, "update_interval_seconds": 99}
        assert (
            BackendManager.fingerprint_matches(str(tmp_path), runtime_changed)
            is True
        )


class _FixedDatetime:
    """datetime stand-in with a frozen now() for deterministic timestamps."""

    _fixed = None

    @classmethod
    def now(cls):
        return cls._fixed


class TestArchiveExistingResults:
    def test_nothing_to_archive_returns_none(self, tmp_path):
        assert BackendManager.archive_existing_results(str(tmp_path)) is None

    def test_moves_subdirs_into_timestamped_archive(self, tmp_path):
        (tmp_path / "kraken2").mkdir()
        (tmp_path / "kraken2" / "report.txt").write_text("x")
        (tmp_path / "validation").mkdir()
        (tmp_path / "validation" / "v.tsv").write_text("y")

        archive = BackendManager.archive_existing_results(str(tmp_path))

        assert archive is not None
        assert os.path.isdir(archive)
        assert os.path.basename(archive).startswith("_archive_")
        # Originals moved out of the top level...
        assert not (tmp_path / "kraken2").exists()
        assert not (tmp_path / "validation").exists()
        # ...and now live under the archive dir with files intact.
        assert os.path.isfile(os.path.join(archive, "kraken2", "report.txt"))
        assert os.path.isfile(os.path.join(archive, "validation", "v.tsv"))

    def test_same_second_collision_appends_suffix(self, tmp_path, monkeypatch):
        import datetime as real_datetime

        _FixedDatetime._fixed = real_datetime.datetime(2026, 6, 2, 21, 0, 0)
        monkeypatch.setattr(bm_mod, "datetime", _FixedDatetime)

        # Pre-create the first-second archive dir so the natural name collides.
        first = tmp_path / "_archive_2026-06-02_21-00-00"
        first.mkdir()

        (tmp_path / "kraken2").mkdir()
        (tmp_path / "kraken2" / "report.txt").write_text("x")

        archive = BackendManager.archive_existing_results(str(tmp_path))

        assert archive is not None
        assert os.path.basename(archive) == "_archive_2026-06-02_21-00-00_2"
        assert os.path.isfile(os.path.join(archive, "kraken2", "report.txt"))
        # The pre-existing first archive is untouched.
        assert first.is_dir()
