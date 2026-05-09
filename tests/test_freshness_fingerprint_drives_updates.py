"""Regression tests for the freshness fingerprint contract.

The ``last-update-time`` and ``dashboard-last-updated`` stores were
previously driven by the wall-clock polling tick, so they advanced on
every interval regardless of whether data had actually changed. The
companion stale-warning callback compared against a perpetually fresh
timestamp and could never fire.

These tests pin the contract callbacks now rely on:

1. When the directory contents do not change between calls,
   ``check_data_freshness`` returns the same hash. The Dash callback
   gates on this and raises PreventUpdate, which means downstream
   timestamp stores keep their prior value.
2. When a watched file's mtime advances, the fingerprint hash changes
   and the downstream timestamp stamps a new value.

We do not exercise the Dash callback directly here -- it is registered
on an app instance and tightly coupled to Inputs/Outputs. The
fingerprint primitive is the load-bearing piece; if it behaves the
callback semantics follow.
"""

from __future__ import annotations

import os
from pathlib import Path

from nanometa_live.core.utils.loader_utils import check_data_freshness


def _touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (mtime, mtime))


def test_unchanged_directory_yields_same_fingerprint(tmp_path):
    """Same fingerprint => downstream timestamp store does not advance."""
    for sub in ("kraken2", "fastp", "validation", "seqkit"):
        (tmp_path / sub).mkdir()
    _touch(tmp_path / "kraken2" / "sample.kraken2.report.txt", mtime=1_700_000_000)

    fp1 = check_data_freshness(str(tmp_path))
    fp2 = check_data_freshness(str(tmp_path))

    assert fp1 == fp2, (
        "Fingerprint must be stable when no file changes -- the "
        "fingerprint-driven last-update-time store relies on this to "
        "preserve the prior data-arrival timestamp."
    )


def test_changed_file_advances_fingerprint(tmp_path):
    """Different fingerprint => downstream timestamp store advances."""
    for sub in ("kraken2", "fastp", "validation", "seqkit"):
        (tmp_path / sub).mkdir()
    report = tmp_path / "kraken2" / "sample.kraken2.report.txt"
    _touch(report, mtime=1_700_000_000)

    fp1 = check_data_freshness(str(tmp_path))

    # Simulate a new batch arriving (mtime moves forward).
    _touch(report, mtime=1_700_000_500)

    fp2 = check_data_freshness(str(tmp_path))

    assert fp1 != fp2, (
        "Fingerprint must advance when a watched file's mtime moves; "
        "without this, the freshness badge and stale warning callbacks "
        "cannot tell that data has arrived."
    )
