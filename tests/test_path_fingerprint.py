"""Tests for _get_path_fingerprint nested-directory awareness.

Regression guard for the realtime-mode dashboard bug surfaced in the
2026-05-06 audit: nanometanf realtime mode emits Kraken2 reports under
``kraken2/<sample>/batch_reports/<sample>_batch<N>.kraken2.report.txt``.
The old fingerprint scanned only direct file children of the cache
root via os.scandir, so kraken2/ stayed at (0.0, 0) forever and the
mtime cache locked in an empty DataFrame. The dashboard tile read 0
sequences for the entire run.
"""

from __future__ import annotations

from pathlib import Path

from nanometa_live.core.utils.loader_utils import _get_path_fingerprint


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestPathFingerprint:
    def test_empty_dir_returns_zero(self, tmp_path):
        assert _get_path_fingerprint([str(tmp_path)]) == (0.0, 0)

    def test_direct_file_counts(self, tmp_path):
        _touch(tmp_path / "a.txt", "abc")
        mtime, size = _get_path_fingerprint([str(tmp_path)])
        assert mtime > 0
        assert size == 3

    def test_nested_file_counts(self, tmp_path):
        # The realtime layout: kraken2/<sample>/batch_reports/*.report.txt
        nested = tmp_path / "kraken2" / "barcode01" / "batch_reports"
        _touch(nested / "batch_0.kraken2.report.txt", "report-data")
        mtime, size = _get_path_fingerprint([str(tmp_path / "kraken2")])
        # Pre-fix this returned (0.0, 0). The nested file has length 11.
        assert mtime > 0
        assert size == 11

    def test_advances_when_new_nested_file_lands(self, tmp_path):
        kraken = tmp_path / "kraken2"
        # Initial state: barcode dir exists but no reports yet.
        (kraken / "barcode01" / "batch_reports").mkdir(parents=True)
        first_mtime, first_size = _get_path_fingerprint([str(kraken)])
        assert first_size == 0

        # New batch report lands. Fingerprint must advance so the cache
        # invalidates and the loader re-parses.
        _touch(
            kraken / "barcode01" / "batch_reports" / "batch_0.kraken2.report.txt",
            "first-batch",
        )
        second_mtime, second_size = _get_path_fingerprint([str(kraken)])
        assert second_size == len("first-batch")
        assert second_mtime > 0
        assert (second_mtime, second_size) != (first_mtime, first_size)

    def test_aggregates_across_multiple_samples(self, tmp_path):
        kraken = tmp_path / "kraken2"
        for bc in ("barcode01", "barcode02", "barcode03"):
            _touch(
                kraken / bc / "batch_reports" / "batch_0.kraken2.report.txt",
                "abcd",  # 4 bytes
            )
        _, size = _get_path_fingerprint([str(kraken)])
        assert size == 12  # 3 samples x 4 bytes

    def test_handles_missing_path(self, tmp_path):
        # Should not raise; missing path contributes nothing.
        mtime, size = _get_path_fingerprint([str(tmp_path / "does_not_exist")])
        assert (mtime, size) == (0.0, 0)

    def test_mixed_file_and_directory_paths(self, tmp_path):
        # _get_path_fingerprint accepts a list, possibly mixing file and
        # directory entries; both contribute.
        _touch(tmp_path / "loose.txt", "ab")
        nested = tmp_path / "subdir" / "deep"
        _touch(nested / "data.txt", "cdef")
        mtime, size = _get_path_fingerprint([
            str(tmp_path / "loose.txt"),
            str(tmp_path / "subdir"),
        ])
        assert size == 6
        assert mtime > 0
