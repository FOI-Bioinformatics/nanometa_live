"""Unit tests for the first_batch_seen flag (U4, 2026-05-09 spec)."""

import os

import pytest

from nanometa_live.app.utils.first_batch import (
    TRACKED_SUBDIRS,
    first_batch_seen,
)


def test_first_batch_seen_missing_dir(tmp_path):
    assert first_batch_seen(str(tmp_path / "does-not-exist")) is False


def test_first_batch_seen_empty_outdir(tmp_path):
    # An outdir with no subdirectories at all has no batch yet.
    assert first_batch_seen(str(tmp_path)) is False


def test_first_batch_seen_only_empty_files(tmp_path):
    # Empty placeholder files do not count as a real first batch.
    krk = tmp_path / "kraken2"
    krk.mkdir()
    (krk / "barcode01.kraken2.report.txt").write_text("")
    assert first_batch_seen(str(tmp_path)) is False


def test_first_batch_seen_flips_true_on_nonempty_file(tmp_path):
    krk = tmp_path / "kraken2"
    krk.mkdir()
    # Pre-condition: still empty.
    assert first_batch_seen(str(tmp_path)) is False
    (krk / "barcode01.kraken2.report.txt").write_text("data")
    # Post-condition: a non-empty file flips the flag.
    assert first_batch_seen(str(tmp_path)) is True


def test_first_batch_seen_nested_paths(tmp_path):
    # Realtime layout puts incremental reports several levels deep.
    nested = tmp_path / "kraken2" / "barcode01" / "batch_reports"
    nested.mkdir(parents=True)
    (nested / "batch_001.kraken2.report.txt").write_text("rows")
    assert first_batch_seen(str(tmp_path)) is True


def test_first_batch_seen_picks_up_any_tracked_subdir(tmp_path):
    # Detection is OR across tracked subdirs; populate validation only.
    val_dir = tmp_path / "validation" / "blast"
    val_dir.mkdir(parents=True)
    (val_dir / "barcode01.blast.tsv").write_text("hit")
    assert first_batch_seen(str(tmp_path)) is True


def test_first_batch_seen_ignores_unknown_subdir(tmp_path):
    other = tmp_path / "scratch"
    other.mkdir()
    (other / "noise.txt").write_text("data")
    assert first_batch_seen(str(tmp_path)) is False


def test_tracked_subdirs_match_pipeline_layout():
    # Sanity: the kraken2 subdir is the canonical signal and must be tracked.
    assert "kraken2" in TRACKED_SUBDIRS
