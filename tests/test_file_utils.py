"""
Unit tests for core/utils/file_utils.py.

A broad set of small filesystem helpers. All real I/O is confined to tmp_path;
the one network function (download_file) and the command probe are mocked so no
external resource is touched.
"""

import gzip
import hashlib
import os
import tarfile
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from nanometa_live.core.utils import file_utils as fu


class TestEnsureDirectory:
    def test_creates_nested_directory(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"
        assert fu.ensure_directory(str(target)) is True
        assert target.is_dir()

    def test_existing_directory_is_ok(self, tmp_path):
        assert fu.ensure_directory(str(tmp_path)) is True


class TestCleanPath:
    def test_expands_user(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/op")
        assert fu.clean_path("~/data") == "/home/op/data"

    def test_normalises_redundant_segments(self):
        assert fu.clean_path("/a/./b/../c") == "/a/c"

    def test_expands_env_var(self, monkeypatch):
        monkeypatch.setenv("MYROOT", "/srv/data")
        assert fu.clean_path("$MYROOT/db") == "/srv/data/db"


class TestCopyFile:
    def test_missing_source_returns_false(self, tmp_path):
        assert fu.copy_file(str(tmp_path / "no.txt"), str(tmp_path / "out.txt")) is False

    def test_copies_content(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("payload")
        dst = tmp_path / "sub" / "dst.txt"
        assert fu.copy_file(str(src), str(dst)) is True
        assert dst.read_text() == "payload"

    def test_no_overwrite_blocks_existing(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("new")
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        assert fu.copy_file(str(src), str(dst), overwrite=False) is False
        assert dst.read_text() == "old"

    def test_overwrite_true_replaces(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("new")
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        assert fu.copy_file(str(src), str(dst), overwrite=True) is True
        assert dst.read_text() == "new"


class TestExtractArchive:
    def test_zip(self, tmp_path):
        archive = tmp_path / "a.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("inner.txt", "hi")
        out = tmp_path / "out"
        assert fu.extract_archive(str(archive), str(out)) is True
        assert (out / "inner.txt").read_text() == "hi"

    def test_tar_gz(self, tmp_path):
        payload = tmp_path / "inner.txt"
        payload.write_text("data")
        archive = tmp_path / "a.tar.gz"
        with tarfile.open(archive, "w:gz") as t:
            t.add(payload, arcname="inner.txt")
        out = tmp_path / "out"
        assert fu.extract_archive(str(archive), str(out)) is True
        assert (out / "inner.txt").read_text() == "data"

    def test_gz_single_file(self, tmp_path):
        archive = tmp_path / "report.txt.gz"
        with gzip.open(archive, "wt") as f:
            f.write("content")
        out = tmp_path / "out"
        assert fu.extract_archive(str(archive), str(out)) is True
        assert (out / "report.txt").read_text() == "content"

    def test_unsupported_format_returns_false(self, tmp_path):
        archive = tmp_path / "a.rar"
        archive.write_text("x")
        assert fu.extract_archive(str(archive), str(tmp_path / "out")) is False

    def test_missing_archive_returns_false(self, tmp_path):
        assert fu.extract_archive(str(tmp_path / "no.zip"), str(tmp_path / "out")) is False


class TestDownloadFile:
    def test_skips_when_exists_and_no_overwrite(self, tmp_path):
        dst = tmp_path / "f.bin"
        dst.write_text("present")
        with patch("requests.get") as get:
            assert fu.download_file("http://x/f.bin", str(dst)) is True
        get.assert_not_called()

    def test_writes_downloaded_chunks(self, tmp_path):
        dst = tmp_path / "sub" / "f.bin"
        resp = MagicMock()
        resp.headers = {"content-length": "6"}
        resp.iter_content.return_value = [b"abc", b"def"]
        with patch("requests.get", return_value=resp):
            assert fu.download_file("http://x/f.bin", str(dst)) is True
        assert dst.read_bytes() == b"abcdef"

    def test_network_error_returns_false(self, tmp_path):
        import requests

        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            assert fu.download_file("http://x/f.bin", str(tmp_path / "f.bin")) is False


class TestCalculateFileHash:
    def test_md5_matches_hashlib(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"hello world")
        expected = hashlib.md5(b"hello world").hexdigest()
        assert fu.calculate_file_hash(str(f)) == expected

    def test_sha256(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"data")
        assert fu.calculate_file_hash(str(f), "sha256") == hashlib.sha256(b"data").hexdigest()

    def test_missing_file_returns_empty(self, tmp_path):
        assert fu.calculate_file_hash(str(tmp_path / "no.txt")) == ""

    def test_unsupported_hash_type_raises(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"x")
        with pytest.raises(ValueError):
            fu.calculate_file_hash(str(f), "crc32")


class TestGetFileList:
    def test_lists_files_non_recursive(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.txt").write_text("")
        (tmp_path / "sub").mkdir()
        result = fu.get_file_list(str(tmp_path))
        assert sorted(os.path.basename(p) for p in result) == ["a.txt", "b.txt"]

    def test_pattern_filter(self, tmp_path):
        (tmp_path / "r1.fastq").write_text("")
        (tmp_path / "r2.fastq").write_text("")
        (tmp_path / "notes.txt").write_text("")
        result = fu.get_file_list(str(tmp_path), pattern="*.fastq")
        assert len(result) == 2

    def test_recursive(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("")
        result = fu.get_file_list(str(tmp_path), recursive=True)
        assert len(result) == 2

    def test_missing_dir_returns_empty(self, tmp_path):
        assert fu.get_file_list(str(tmp_path / "no")) == []


class TestReadWriteFileLines:
    def test_round_trip_plain(self, tmp_path):
        f = tmp_path / "lines.txt"
        assert fu.write_file_lines(str(f), ["one", "two"]) is True
        assert fu.read_file_lines(str(f)) == ["one", "two"]

    def test_round_trip_gzip(self, tmp_path):
        f = tmp_path / "lines.txt.gz"
        assert fu.write_file_lines(str(f), ["a", "b"]) is True
        assert fu.read_file_lines(str(f)) == ["a", "b"]

    def test_read_missing_returns_empty(self, tmp_path):
        assert fu.read_file_lines(str(tmp_path / "no.txt")) == []


class TestRemoveTempFiles:
    def test_removes_file_and_dir(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        d = tmp_path / "d"
        d.mkdir()
        (d / "inner.txt").write_text("y")
        assert fu.remove_temp_files([str(f), str(d)]) is True
        assert not f.exists()
        assert not d.exists()

    def test_missing_path_is_noop_success(self, tmp_path):
        assert fu.remove_temp_files([str(tmp_path / "gone")]) is True


class TestCreateTempDirectory:
    def test_creates_prefixed_dir(self):
        path = fu.create_temp_directory()
        try:
            assert path is not None
            assert os.path.isdir(path)
            assert os.path.basename(path).startswith("nanometa_")
        finally:
            if path and os.path.isdir(path):
                fu.remove_temp_files([path])


class TestGetMostRecentFile:
    def test_returns_newest(self, tmp_path):
        old = tmp_path / "old.txt"
        old.write_text("x")
        os.utime(old, (1, 1))  # far in the past
        new = tmp_path / "new.txt"
        new.write_text("y")
        assert fu.get_most_recent_file(str(tmp_path)) == str(new)

    def test_empty_dir_returns_none(self, tmp_path):
        assert fu.get_most_recent_file(str(tmp_path)) is None


class TestCheckCommandExists:
    def test_present_command(self):
        # 'ls' exists on every POSIX dev/CI host this runs on.
        assert fu.check_command_exists("ls") is True

    def test_absent_command(self):
        assert fu.check_command_exists("definitely_not_a_real_command_xyz") is False
