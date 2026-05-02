"""Tests for output-directory collision detection and archiving.

The GUI calls these helpers before launching nanometanf so the
operator gets warned when an output directory already contains
result data from a previous run, rather than silently mixing it
with new output.

Pinned behaviours:
  * detect_existing_results returns only the result-subdir names
    that exist AND contain at least one regular file. An empty
    directory does not count.
  * It never raises on missing outdir or unreadable subdirs.
  * archive_existing_results moves the detected subdirs into a
    timestamped ``_archive_*`` folder under outdir, preserves
    file content, and never overwrites an existing archive
    folder if a same-second collision occurs.
  * Both helpers are idempotent across calls when nothing has
    changed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nanometa_live.core.workflow.backend_manager import BackendManager


def _touch(path: Path, content: str = "data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# detect_existing_results
# ---------------------------------------------------------------------------


class TestDetectExistingResults:
    def test_empty_string_returns_empty(self):
        assert BackendManager.detect_existing_results("") == []

    def test_missing_dir_returns_empty(self, tmp_path):
        assert BackendManager.detect_existing_results(
            str(tmp_path / "does_not_exist")
        ) == []

    def test_dir_with_no_result_subdirs_returns_empty(self, tmp_path):
        _touch(tmp_path / "random_file.txt")
        _touch(tmp_path / "unrelated_dir" / "file.txt")
        assert BackendManager.detect_existing_results(str(tmp_path)) == []

    def test_empty_kraken2_dir_does_not_count(self, tmp_path):
        # An empty subdir is harmless; the pipeline can refill it.
        (tmp_path / "kraken2").mkdir()
        assert BackendManager.detect_existing_results(str(tmp_path)) == []

    def test_kraken2_with_file_is_detected(self, tmp_path):
        _touch(tmp_path / "kraken2" / "sample.kreport2.txt")
        assert BackendManager.detect_existing_results(str(tmp_path)) == [
            "kraken2"
        ]

    def test_nested_file_in_subdir_is_detected(self, tmp_path):
        # Files several levels deep should still trigger detection.
        _touch(tmp_path / "validation" / "blast" / "barcode01.blast.tsv")
        assert BackendManager.detect_existing_results(str(tmp_path)) == [
            "validation"
        ]

    def test_multiple_subdirs_all_returned(self, tmp_path):
        _touch(tmp_path / "kraken2" / "sample.kreport2.txt")
        _touch(tmp_path / "fastp" / "sample.fastp.json")
        _touch(tmp_path / "seqkit" / "sample.tsv")
        result = BackendManager.detect_existing_results(str(tmp_path))
        assert set(result) == {"kraken2", "fastp", "seqkit"}

    def test_unknown_subdir_ignored(self, tmp_path):
        # Subdirs that aren't in the known list are not flagged.
        _touch(tmp_path / "kraken2" / "sample.kreport2.txt")
        _touch(tmp_path / "my_random_stuff" / "anything.txt")
        result = BackendManager.detect_existing_results(str(tmp_path))
        assert result == ["kraken2"]

    def test_idempotent_when_unchanged(self, tmp_path):
        _touch(tmp_path / "kraken2" / "sample.kreport2.txt")
        first = BackendManager.detect_existing_results(str(tmp_path))
        second = BackendManager.detect_existing_results(str(tmp_path))
        assert first == second


# ---------------------------------------------------------------------------
# archive_existing_results
# ---------------------------------------------------------------------------


class TestArchiveExistingResults:
    def test_no_op_when_nothing_to_archive(self, tmp_path):
        assert BackendManager.archive_existing_results(str(tmp_path)) is None

    def test_no_op_when_outdir_missing(self, tmp_path):
        assert (
            BackendManager.archive_existing_results(
                str(tmp_path / "missing")
            )
            is None
        )

    def test_archives_kraken2_dir(self, tmp_path):
        _touch(tmp_path / "kraken2" / "sample.kreport2.txt", "k2")

        archive = BackendManager.archive_existing_results(str(tmp_path))

        assert archive is not None
        archive_path = Path(archive)
        assert archive_path.exists()
        assert archive_path.is_dir()
        assert archive_path.name.startswith("_archive_")
        # Original kraken2 dir is gone, content preserved under archive
        assert not (tmp_path / "kraken2").exists()
        assert (archive_path / "kraken2" / "sample.kreport2.txt").exists()
        assert (
            archive_path / "kraken2" / "sample.kreport2.txt"
        ).read_text() == "k2"

    def test_archives_multiple_subdirs(self, tmp_path):
        _touch(tmp_path / "kraken2" / "a.txt")
        _touch(tmp_path / "fastp" / "b.json")
        _touch(tmp_path / "validation" / "c.tsv")

        archive = BackendManager.archive_existing_results(str(tmp_path))

        archive_path = Path(archive)
        for name in ("kraken2", "fastp", "validation"):
            assert not (tmp_path / name).exists()
            assert (archive_path / name).is_dir()

    def test_unrelated_files_left_in_place(self, tmp_path):
        _touch(tmp_path / "kraken2" / "a.txt")
        _touch(tmp_path / "config.yaml", "user-config")
        _touch(tmp_path / "my_notes.md", "notes")

        BackendManager.archive_existing_results(str(tmp_path))

        # The user's own files are not touched.
        assert (tmp_path / "config.yaml").read_text() == "user-config"
        assert (tmp_path / "my_notes.md").read_text() == "notes"

    def test_same_second_collision_uses_numeric_suffix(self, tmp_path):
        # If two archives are produced within the same second the
        # second one gets _2 appended so prior archive content is
        # never overwritten.
        _touch(tmp_path / "kraken2" / "first.txt", "first")

        first_archive = BackendManager.archive_existing_results(str(tmp_path))
        # Re-create kraken2 to set up a second archive call.
        _touch(tmp_path / "kraken2" / "second.txt", "second")
        second_archive = BackendManager.archive_existing_results(str(tmp_path))

        assert first_archive != second_archive
        assert Path(first_archive).exists()
        assert Path(second_archive).exists()
        # Both archives still hold their own content.
        assert (Path(first_archive) / "kraken2" / "first.txt").read_text() == "first"
        assert (Path(second_archive) / "kraken2" / "second.txt").read_text() == "second"

    def test_returns_archive_path_under_outdir(self, tmp_path):
        _touch(tmp_path / "kraken2" / "a.txt")
        archive = BackendManager.archive_existing_results(str(tmp_path))
        assert archive is not None
        assert Path(archive).parent == tmp_path
