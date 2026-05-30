"""
Unit tests for core/utils/loader_utils.py freshness/fingerprint helpers.

The headline behaviour is the recursive fingerprint walk: realtime mode lands
Kraken2 reports under nested ``kraken2/<sample>/batch_reports/`` directories,
and a non-recursive scan finds nothing directly under ``kraken2/`` — which is
exactly the bug that left the dashboard pinned at zero. These tests assert the
walk counts nested files and that the fingerprint advances when files arrive.

File stability is tested with backdated mtimes rather than sleeps so the suite
stays deterministic under xdist.
"""

import os

import pytest

from nanometa_live.core.utils import loader_utils
from nanometa_live.core.utils.loader_utils import (
    _get_dir_latest_mtime,
    _get_path_fingerprint,
    _is_file_stable,
    check_data_freshness,
    clear_data_cache,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    clear_data_cache()
    yield
    clear_data_cache()


def _backdate(path, seconds=5):
    old = os.path.getmtime(path) - seconds
    os.utime(path, (old, old))


class TestGetPathFingerprint:
    def test_empty_for_nonexistent_path(self, tmp_path):
        assert _get_path_fingerprint([str(tmp_path / "missing")]) == (0.0, 0, 0)

    def test_regular_file(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("hello world")
        mtime, size, count = _get_path_fingerprint([str(f)])
        assert count == 1
        assert size == len("hello world")
        assert mtime > 0

    def test_counts_nested_directory_files(self, tmp_path):
        # Regression anchor: realtime kraken2/<sample>/batch_reports/ layout.
        nested = tmp_path / "kraken2" / "barcode01" / "batch_reports"
        nested.mkdir(parents=True)
        (nested / "batch0.report.txt").write_text("aaa")
        (nested / "batch1.report.txt").write_text("bbbb")
        mtime, size, count = _get_path_fingerprint([str(tmp_path / "kraken2")])
        assert count == 2
        assert size == 3 + 4
        assert mtime > 0

    def test_fingerprint_advances_when_file_added(self, tmp_path):
        kraken = tmp_path / "kraken2" / "s"
        kraken.mkdir(parents=True)
        (kraken / "a.txt").write_text("aaa")
        before = _get_path_fingerprint([str(tmp_path / "kraken2")])
        (kraken / "b.txt").write_text("bbb")
        after = _get_path_fingerprint([str(tmp_path / "kraken2")])
        assert after != before
        assert after[2] == before[2] + 1  # file_count incremented


class TestGetDirLatestMtime:
    def test_missing_dir_returns_zero(self, tmp_path):
        assert _get_dir_latest_mtime(str(tmp_path / "nope")) == 0.0

    def test_returns_latest_nested_mtime(self, tmp_path):
        sub = tmp_path / "kraken2" / "s"
        sub.mkdir(parents=True)
        old_file = sub / "old.txt"
        old_file.write_text("x" * 20)
        _backdate(old_file, seconds=100)
        new_file = sub / "new.txt"
        new_file.write_text("y" * 20)
        latest = _get_dir_latest_mtime(str(tmp_path / "kraken2"))
        assert latest == pytest.approx(os.path.getmtime(new_file))


class TestCheckDataFreshness:
    def test_returns_stable_hex_fingerprint(self, tmp_path):
        (tmp_path / "kraken2").mkdir()
        fp1 = check_data_freshness(str(tmp_path))
        fp2 = check_data_freshness(str(tmp_path))
        assert len(fp1) == 32  # md5 hexdigest
        assert fp1 == fp2

    def test_fingerprint_changes_when_data_lands(self, tmp_path):
        kraken = tmp_path / "kraken2"
        kraken.mkdir()
        before = check_data_freshness(str(tmp_path))
        report = kraken / "barcode01.kraken2.report.txt"
        report.write_text("100.00\t10\t10\tS\t562\tEscherichia coli\n")
        after = check_data_freshness(str(tmp_path))
        assert before != after


class TestIsFileStable:
    def test_stable_when_old_and_large(self, tmp_path):
        f = tmp_path / "stable.txt"
        f.write_text("x" * 100)
        _backdate(f, seconds=5)
        assert _is_file_stable(str(f)) is True

    def test_unstable_when_too_small(self, tmp_path):
        f = tmp_path / "tiny.txt"
        f.write_text("x")  # below FILE_STABILITY_MIN_SIZE_BYTES (10)
        _backdate(f, seconds=5)
        assert _is_file_stable(str(f)) is False

    def test_unstable_when_recently_modified(self, tmp_path):
        f = tmp_path / "fresh.txt"
        f.write_text("x" * 100)  # mtime is now, age < 1s threshold
        assert _is_file_stable(str(f)) is False

    def test_missing_file_is_unstable(self, tmp_path):
        assert _is_file_stable(str(tmp_path / "gone.txt")) is False
