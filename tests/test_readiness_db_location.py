"""Readiness check: warn when the Kraken2 database sits on a removable volume.

Kraken2 memory-maps ``hash.k2d`` in place, and classification touches it in
random page-sized reads. On the 2026-08-18 release check a database on a USB
exFAT volume that reads 63 MB/s sequentially paged for 20+ minutes per task;
the same database on local disk classified in ~70 s. Nothing warned the
operator. The check is a WARNING, not a blocker: the run works, just slowly,
and the fix (copy the DB to local disk) is safe because the ``db_hash`` is
content-derived so cached indexes and mappings stay valid.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.readiness_checker import (
    ReadinessChecker,
    Severity,
    _database_on_removable_volume,
)


class TestRemovableVolumeDetection:
    @pytest.mark.parametrize("path,system", [
        ("/Volumes/Untitled/Bioshield/db", "Darwin"),
        ("/media/user/usbdrive/db", "Linux"),
        ("/mnt/usb/db", "Linux"),
        ("/run/media/user/stick/db", "Linux"),
    ])
    def test_removable_paths_flagged(self, path, system):
        assert _database_on_removable_volume(path, system=system) is True

    @pytest.mark.parametrize("path,system", [
        ("/tmp/nanometa_e2e/db", "Darwin"),
        ("/Users/operator/db", "Darwin"),
        ("/home/operator/db", "Linux"),
        ("/opt/databases/kraken", "Linux"),
        # Prefix must match on a path-component boundary, not a substring.
        ("/mnt2/db", "Linux"),
        ("/Volumes2/db", "Darwin"),
    ])
    def test_local_paths_not_flagged(self, path, system):
        assert _database_on_removable_volume(path, system=system) is False


class TestKrakenDbLocationCheck:
    def _make_db(self, root: Path) -> Path:
        db = root / "db"
        db.mkdir(parents=True)
        for f in ("hash.k2d", "opts.k2d", "taxo.k2d"):
            (db / f).write_bytes(b"x")
        return db

    def test_local_database_passes(self, tmp_path):
        db = self._make_db(tmp_path)
        result = ReadinessChecker()._check_kraken_db_location(
            {"kraken_db": str(db)}
        )
        assert result.passed is True

    def test_removable_database_warns_with_remedy(self, tmp_path, monkeypatch):
        db = self._make_db(tmp_path)
        import nanometa_live.core.workflow.readiness_checker as rc
        monkeypatch.setattr(
            rc, "_database_on_removable_volume", lambda p, system=None: True
        )
        result = ReadinessChecker()._check_kraken_db_location(
            {"kraken_db": str(db)}
        )
        assert result.passed is False
        assert result.severity == Severity.WARNING, (
            "a slow-but-working setup must warn, not block the run"
        )
        assert "local" in result.message.lower(), (
            "the warning must state the remedy (copy to local disk), not "
            "just the condition"
        )

    def test_unset_or_missing_path_is_not_this_checks_business(self):
        result = ReadinessChecker()._check_kraken_db_location({"kraken_db": ""})
        assert result.passed is True
        result = ReadinessChecker()._check_kraken_db_location(
            {"kraken_db": "/nonexistent/db"}
        )
        assert result.passed is True, (
            "a missing database is the Kraken2 Database check's finding; "
            "duplicating it here would double-report one problem"
        )

    def test_registered_in_check_readiness(self):
        # Wiring pin without running the full checklist (which probes
        # network APIs): the check must be appended by check_readiness.
        import inspect
        src = inspect.getsource(ReadinessChecker.check_readiness)
        assert "_check_kraken_db_location" in src, (
            "the location check exists but check_readiness never runs it"
        )
