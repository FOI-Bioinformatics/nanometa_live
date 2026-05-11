"""Regression tests for the fingerprint overflow behaviour past ``_MAX_FINGERPRINT_FILES``.

The 2026-05-10 threading audit (``docs/audit/threading-2026-05-10.md``) flagged
that the prior fingerprint silently plateaued once the file walker hit the
5000-file stat cap: post-cap files contributed nothing, so a long real-time
run with thousands of per-batch reports could deceive the loader cache into
serving stale data. The fix continues the walk past the cap, accumulating
``file_count`` without calling ``stat()``, so newly-added files past the cap
still bump the fingerprint and invalidate the cache.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import nanometa_live.core.utils.loader_utils as lu


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestFingerprintCountAdvancesPastCap:
    """Files past _MAX_FINGERPRINT_FILES still increment file_count."""

    def test_count_advances_past_stat_cap(self, tmp_path):
        # Lower the cap so the test does not have to create thousands
        # of files. The semantics are identical at any cap value.
        with patch.object(lu, "_MAX_FINGERPRINT_FILES", 5):
            # Create 10 files; only the first 5 will be stat()-ed.
            for i in range(10):
                _touch(tmp_path / f"file_{i:02d}.txt", "x")
            mtime, size, count = lu._get_path_fingerprint([str(tmp_path)])
            assert count == 10  # all files counted
            # Only first 5 stat'd; size reflects partial
            assert size == 5

    def test_size_caps_at_stat_limit(self, tmp_path):
        with patch.object(lu, "_MAX_FINGERPRINT_FILES", 3):
            for i in range(8):
                _touch(tmp_path / f"f_{i}.txt", "abc")  # 3 bytes each
            _, size, count = lu._get_path_fingerprint([str(tmp_path)])
            assert count == 8
            assert size == 9  # first 3 files * 3 bytes

    def test_new_file_past_cap_advances_fingerprint(self, tmp_path):
        with patch.object(lu, "_MAX_FINGERPRINT_FILES", 3):
            for i in range(5):
                _touch(tmp_path / f"existing_{i}.txt", "y")
            first = lu._get_path_fingerprint([str(tmp_path)])
            assert first[2] == 5

            # New file beyond the stat cap -- mtime and size do not advance
            # (we never stat it), but count does, so the fingerprint
            # tuple is different and the cache invalidates correctly.
            _touch(tmp_path / "new_after_cap.txt", "z")
            second = lu._get_path_fingerprint([str(tmp_path)])
            assert second[2] == 6
            assert second != first


class TestFingerprintCapEnvOverride:
    """``NANOMETA_MAX_FINGERPRINT_FILES`` overrides the default at import time."""

    def test_default_is_50000(self):
        # The module-level constant is read once at import. Without the env
        # var the default is 50000; that's enough headroom for a typical
        # PromethION run (24 barcodes x ~100 batches x intermediates).
        assert lu._MAX_FINGERPRINT_FILES >= 50000
