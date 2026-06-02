"""Tests for ``check_data_freshness`` -- the fingerprint primitive that
gates the event-driven refresh added in the 2026-05-01 update-frequency
audit.

These tests pin two things:

1. The freshness fingerprint includes ``seqkit/`` as well as
   ``kraken2/``, ``fastp/``, and ``validation/``. seqkit is the QC
   output directory for chopper / filtlong runs, so a freshness check
   that excludes it would silently miss every QC update on the
   default ONT pipeline.

2. The fingerprint is stable across calls when no file has changed and
   advances when a watched file's mtime moves. That is the contract
   the ``compute_results_fingerprint`` callback in ``app/callbacks.py``
   relies on -- if the fingerprint does not advance, downstream
   callbacks raise PreventUpdate and the tick is free.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from nanometa_live.core.utils.loader_utils import check_data_freshness


def _touch(path: Path, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("data")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class TestSeqkitInFreshnessScan:
    def test_seqkit_change_advances_fingerprint(self, tmp_path):
        # Establish a baseline with empty kraken2 / fastp / validation
        # dirs and one seqkit stats file.
        for sub in ("kraken2", "fastp", "validation", "seqkit"):
            (tmp_path / sub).mkdir()
        seqkit_file = tmp_path / "seqkit" / "barcode01.tsv"
        _touch(seqkit_file, mtime=1_700_000_000)

        fp1 = check_data_freshness(str(tmp_path))

        # Advance the seqkit file's mtime. With chopper as the QC tool,
        # this is the only thing that changes for a QC-only update --
        # if the freshness check ignores seqkit/, fp2 will equal fp1
        # and the dashboard will not refresh.
        _touch(seqkit_file, mtime=1_700_000_999)
        fp2 = check_data_freshness(str(tmp_path))

        assert fp1 != fp2

    def test_no_change_keeps_fingerprint_stable(self, tmp_path):
        for sub in ("kraken2", "fastp", "validation", "seqkit"):
            (tmp_path / sub).mkdir()
        _touch(tmp_path / "kraken2" / "sample.kraken2.report.txt", mtime=1_700_000_000)
        _touch(tmp_path / "seqkit" / "sample.tsv", mtime=1_700_000_000)

        fp1 = check_data_freshness(str(tmp_path))
        fp2 = check_data_freshness(str(tmp_path))
        assert fp1 == fp2


class TestKraken2InFreshnessScan:
    def test_kraken2_change_advances_fingerprint(self, tmp_path):
        for sub in ("kraken2", "fastp", "validation", "seqkit"):
            (tmp_path / sub).mkdir()
        kr_file = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
        _touch(kr_file, mtime=1_700_000_000)

        fp1 = check_data_freshness(str(tmp_path))
        _touch(kr_file, mtime=1_700_000_999)
        fp2 = check_data_freshness(str(tmp_path))
        assert fp1 != fp2


class TestValidationInFreshnessScan:
    def test_validation_change_advances_fingerprint(self, tmp_path):
        for sub in ("kraken2", "fastp", "validation", "seqkit"):
            (tmp_path / sub).mkdir()
        v_file = tmp_path / "validation" / "validation_results.json"
        _touch(v_file, mtime=1_700_000_000)

        fp1 = check_data_freshness(str(tmp_path))
        _touch(v_file, mtime=1_700_000_999)
        fp2 = check_data_freshness(str(tmp_path))
        assert fp1 != fp2


class TestNestedKraken2BatchReports:
    """Realtime mode writes per-sample, per-batch kraken2 reports under
    ``kraken2/<sample>/batch_reports/*``. The freshness fingerprint must
    advance when a new batch lands there, so any callback gated on the
    centralized fingerprint sees fresh data. A non-recursive scan of
    ``kraken2/`` finds zero direct files in this layout and would lock
    the fingerprint at a constant value (B1 in the 2026-05-07 audit).
    """

    def test_nested_batch_report_advances_fingerprint(self, tmp_path):
        for sub in ("kraken2", "fastp", "validation", "seqkit"):
            (tmp_path / sub).mkdir()

        fp1 = check_data_freshness(str(tmp_path))

        nested = tmp_path / "kraken2" / "barcode01" / "batch_reports" / "batch_1.kraken2.report.txt"
        _touch(nested, mtime=1_700_000_000)
        fp2 = check_data_freshness(str(tmp_path))
        assert fp2 != fp1

        # Update the same nested file's mtime -- fingerprint must advance again.
        _touch(nested, mtime=1_700_000_999)
        fp3 = check_data_freshness(str(tmp_path))
        assert fp3 != fp2


class TestEmptyDirsDoNotRaise:
    def test_missing_subdirs_do_not_raise(self, tmp_path):
        # Pipeline output that hasn't started yet may be missing some
        # of the four scanned subdirs. The freshness check must
        # tolerate this rather than raising and stalling the gate.
        fp = check_data_freshness(str(tmp_path))
        assert isinstance(fp, str)
        assert len(fp) == 32  # md5 hex
