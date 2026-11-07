"""Readiness: the Kraken2 database against this machine's memory.

Field audit 2026-10-28, H1: the launch sized the Kraken2 request from
``hash.k2d`` and nothing compared that to the laptop, so a database larger
than RAM passed every readiness check and the run aborted at its first
classifier task with a message the dashboard did not recognise.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.workflow import readiness_checker as rc
from nanometa_live.core.workflow.readiness_checker import (
    ReadinessChecker,
    Severity,
)

pytestmark = pytest.mark.unit

GIB = 1024 ** 3


def _db(root: Path, hash_gb: float) -> Path:
    db = root / "db"
    db.mkdir(parents=True)
    for f in ("opts.k2d", "taxo.k2d"):
        (db / f).write_bytes(b"x")
    # A sparse file reports the full size without writing it.
    with open(db / "hash.k2d", "wb") as fh:
        fh.truncate(int(hash_gb * GIB))
    return db


def _check(tmp_path, hash_gb, host_gb, **cfg):
    db = _db(tmp_path, hash_gb)
    config = {"kraken_db": str(db), **cfg}
    with patch.object(rc, "_host_memory_bytes", return_value=host_gb * GIB):
        return ReadinessChecker()._check_kraken_db_memory(config)


class TestDatabaseMemoryCheck:
    def test_database_larger_than_memory_is_critical(self, tmp_path):
        r = _check(tmp_path, hash_gb=25, host_gb=16)
        assert r.severity == Severity.CRITICAL
        assert r.passed is False
        assert "larger than this machine's memory" in r.message
        assert "25.0 GB" in r.message and "16 GB" in r.message

    def test_headroom_counts_against_the_database(self, tmp_path):
        # 15 GB hash on a 16 GB machine: the OS and the JVM need the rest.
        r = _check(tmp_path, hash_gb=15, host_gb=16)
        assert r.severity == Severity.CRITICAL

    def test_mmap_off_needs_the_full_private_load(self, tmp_path):
        # 11 GB hash + the 4 GB the request carries = 15 GB private, over
        # the 14 GB a 16 GB machine can give a task; with mmap the same
        # database is only a WARNING (page cache, one task at a time).
        r = _check(tmp_path, hash_gb=11, host_gb=16, kraken_memory_mapping=False)
        assert r.severity == Severity.CRITICAL
        assert "Memory mapping is off" in r.message
        r2 = _check(tmp_path / "mm", hash_gb=11, host_gb=16)
        assert r2.severity == Severity.WARNING

    def test_mmap_off_but_fits_passes(self, tmp_path):
        r = _check(tmp_path, hash_gb=4, host_gb=16, kraken_memory_mapping=False)
        assert r.passed is True

    def test_tight_fit_under_mmap_is_a_warning(self, tmp_path):
        r = _check(tmp_path, hash_gb=12, host_gb=16)
        assert r.severity == Severity.WARNING
        assert r.passed is False
        assert "one task at a time" in r.message

    def test_comfortable_fit_passes_with_figures(self, tmp_path):
        r = _check(tmp_path, hash_gb=8, host_gb=32)
        assert r.passed is True
        assert "8.0 GB" in r.message and "32 GB" in r.message and "25%" in r.message

    def test_no_database_is_not_this_checks_finding(self, tmp_path):
        with patch.object(rc, "_host_memory_bytes", return_value=16 * GIB):
            r = ReadinessChecker()._check_kraken_db_memory({"kraken_db": ""})
        assert r.passed is True and r.severity == Severity.INFO

    def test_unknown_host_memory_is_informational(self, tmp_path):
        r = _check(tmp_path, hash_gb=25, host_gb=0)
        assert r.passed is True and r.severity == Severity.INFO

    def test_wired_into_the_report(self, tmp_path):
        db = _db(tmp_path, 25)
        with patch.object(rc, "_host_memory_bytes", return_value=16 * GIB):
            report = ReadinessChecker().check_readiness(
                {"kraken_db": str(db)}, nanometa_home=str(tmp_path / "home"),
                watchlist_entries=[],
            )
        names = [c.name for c in report.checks]
        assert "Database Memory" in names
        row = next(c for c in report.checks if c.name == "Database Memory")
        assert row.severity == Severity.CRITICAL and not row.passed
