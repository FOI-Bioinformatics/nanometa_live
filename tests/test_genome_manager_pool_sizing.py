"""Regression tests for the auto-derived ThreadPoolExecutor sizes in GenomeManager.

The hardcoded ``max_workers=3`` (downloads) and ``max_workers=2`` (BLAST DB
builds) capped concurrency regardless of host. The 2026-05-10 threading audit
(see ``docs/audit/threading-2026-05-10.md``) flagged this as the GUI's worst
per-host scaling penalty: a 96-thread server was running with the same fixed
3 / 2 worker pools as an 8-thread laptop. The defaults now scale with
``os.cpu_count()`` while preserving the prior floor for tiny hosts.
"""

from __future__ import annotations

from unittest.mock import patch

from nanometa_live.core.utils.genome_manager import (
    _default_blast_build_workers,
    _default_download_workers,
)


class TestDownloadWorkersScaling:
    """``_default_download_workers`` is network-bound and capped at 16."""

    def test_floor_at_3_for_tiny_host(self):
        with patch("os.cpu_count", return_value=2):
            assert _default_download_workers() == 3

    def test_floor_at_3_for_4_core_host(self):
        with patch("os.cpu_count", return_value=4):
            assert _default_download_workers() == 4

    def test_scales_to_8_on_eight_core_laptop(self):
        with patch("os.cpu_count", return_value=8):
            assert _default_download_workers() == 8

    def test_scales_to_16_on_forty_core_server(self):
        with patch("os.cpu_count", return_value=40):
            assert _default_download_workers() == 16

    def test_capped_at_16_on_ninety_six_core_server(self):
        with patch("os.cpu_count", return_value=96):
            assert _default_download_workers() == 16

    def test_handles_none_cpu_count(self):
        with patch("os.cpu_count", return_value=None):
            # Falls back to 4 then floors at 3
            assert _default_download_workers() == 4


class TestBlastBuildWorkersScaling:
    """``_default_blast_build_workers`` is CPU-bound; half-cpus, capped at 8."""

    def test_floor_at_2_for_tiny_host(self):
        with patch("os.cpu_count", return_value=2):
            assert _default_blast_build_workers() == 2

    def test_floor_at_2_for_4_core_host(self):
        with patch("os.cpu_count", return_value=4):
            # 4 // 2 = 2, floor preserves
            assert _default_blast_build_workers() == 2

    def test_scales_to_4_on_eight_core_laptop(self):
        with patch("os.cpu_count", return_value=8):
            assert _default_blast_build_workers() == 4

    def test_caps_at_8_on_forty_core_server(self):
        with patch("os.cpu_count", return_value=40):
            # 40 // 2 = 20, capped at 8
            assert _default_blast_build_workers() == 8

    def test_caps_at_8_on_ninety_six_core_server(self):
        with patch("os.cpu_count", return_value=96):
            assert _default_blast_build_workers() == 8

    def test_handles_none_cpu_count(self):
        with patch("os.cpu_count", return_value=None):
            # Falls back to 4 // 2 = 2, floor preserves
            assert _default_blast_build_workers() == 2
