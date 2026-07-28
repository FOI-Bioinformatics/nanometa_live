"""Fixtures for assertions that run against a real pipeline results tree.

These tests are the only ones in the suite that read output produced by an
actual nanometanf run over real ONT reads. Everything else in ``tests/`` uses
synthetic fixtures, which cannot catch a scientific regression -- a loader can
parse a mock report perfectly and still mis-attribute a select agent on real
data.

They are skipped unless ``NANOMETA_REALDATA_DIR`` points at a results tree, so
the default developer loop and CI are unaffected. To run them::

    NANOMETA_REALDATA_DIR=/path/to/results/R1 pytest tests/realdata -v

The truth set is described in ``tests/realdata/README.md``.
"""

from __future__ import annotations

import os
import pathlib

import pytest


def _results_root() -> pathlib.Path | None:
    raw = os.environ.get("NANOMETA_REALDATA_DIR")
    if not raw:
        return None
    path = pathlib.Path(raw).expanduser()
    return path if path.is_dir() else None


@pytest.fixture(scope="session")
def results_dir() -> pathlib.Path:
    """The root of a completed run's results tree."""
    root = _results_root()
    if root is None:
        pytest.skip(
            "set NANOMETA_REALDATA_DIR to a pipeline results directory to run "
            "the real-data assertions"
        )
    return root


@pytest.fixture(scope="session")
def compare_kraken_reports(request) -> dict[str, pathlib.Path]:
    """Kraken2 reports from a second run, for cross-run comparisons."""
    raw = os.environ.get("NANOMETA_REALDATA_COMPARE_DIR")
    if not raw:
        pytest.skip(
            "set NANOMETA_REALDATA_COMPARE_DIR to a second results directory "
            "to run the cross-run comparisons"
        )
    root = pathlib.Path(raw).expanduser()
    if not root.is_dir():
        pytest.skip(f"NANOMETA_REALDATA_COMPARE_DIR is not a directory: {root}")
    return _collect_kraken_reports(root)


def _collect_kraken_reports(results_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    """Map sample name to its Kraken2 report under a results tree.

    Prefers the cumulative report where one exists, matching the loader
    priority documented in CLAUDE.md, and excludes per-batch reports so a
    single batch is never mistaken for the whole run.
    """
    kraken_dir = results_dir / "kraken2"
    if not kraken_dir.is_dir():
        pytest.skip(f"no kraken2 directory under {results_dir}")

    reports: dict[str, pathlib.Path] = {}
    for report in sorted(kraken_dir.glob("*.kraken2.report.txt")):
        # AppleDouble sidecars appear when writing to exFAT on macOS.
        if report.name.startswith("._"):
            continue
        name = report.name.replace(".cumulative.kraken2.report.txt", "")
        name = name.replace(".kraken2.report.txt", "")
        if "_batch" in name:
            continue
        cumulative = ".cumulative." in report.name
        if name not in reports or cumulative:
            reports[name] = report
    if not reports:
        pytest.skip(f"no Kraken2 reports under {kraken_dir}")
    return reports


@pytest.fixture(scope="session")
def kraken_reports(results_dir) -> dict[str, pathlib.Path]:
    """Map of sample name to its Kraken2 report.

    See :func:`_collect_kraken_reports` for the selection rules.
    """
    return _collect_kraken_reports(results_dir)
