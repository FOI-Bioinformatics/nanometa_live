"""Readiness must refresh after a background genome import/download/delete.

Genome changes touch neither config nor watchlist, so the fingerprint/TTL gate
skipped the recompute and the Watchlist-Genomes / BLAST-Databases checks stayed
stale; and because the recompute runs in a DiskcacheManager worker, that
worker's genome-manager singleton is stale too. So update_readiness_state now
takes genome-download-complete as a forcing trigger and passes reload_genomes,
and check_readiness reloads the singleton before the genome checks.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from dash import Dash

pytestmark = pytest.mark.callback

from dash_test_utils import ctx_with, get_callback_fn
from nanometa_live.app.callbacks.readiness import register_readiness
from nanometa_live.core.workflow.readiness_checker import ReadinessChecker


def _config(tmp_path):
    # offline + conda profile keep check_readiness to fast file/which probes
    # (no network, no heavy subprocess) for the test.
    return {
        "offline_mode": True,
        "pipeline_profile": "conda",
        "data_dir": str(tmp_path),
        "genome_cache_dir": str(tmp_path),
        "kraken_db": "/db",
    }


class TestCheckerReloadFlag:
    def test_reloads_singleton_when_flagged(self, tmp_path):
        mgr = MagicMock()
        with patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
                   return_value=mgr):
            ReadinessChecker().check_readiness(
                _config(tmp_path), watchlist_entries=[], reload_genomes=True)
        mgr.reload_metadata.assert_called_once()

    def test_no_reload_by_default(self, tmp_path):
        mgr = MagicMock()
        with patch("nanometa_live.core.utils.genome_manager.get_genome_manager",
                   return_value=mgr):
            ReadinessChecker().check_readiness(
                _config(tmp_path), watchlist_entries=[], reload_genomes=False)
        assert not mgr.reload_metadata.called


class TestCallbackForcing:
    def _fn(self):
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_readiness(app, MagicMock())
        return get_callback_fn(app, "readiness-state.data",
                               input_contains="genome-download-complete")

    def test_genome_change_forces_recompute_with_reload(self):
        fn = self._fn()
        checker = MagicMock()
        with patch("nanometa_live.core.workflow.readiness_checker.ReadinessChecker",
                   return_value=checker), \
             patch("nanometa_live.app.callbacks.readiness._serialize_report",
                   return_value={"ok": 1}), \
             ctx_with("genome-download-complete"):
            # (n_intervals, config, n_clicks, genome_change, prev_state, watchlist)
            out = fn(5, {"kraken_db": "/dbA"}, None, 3, None, [])
        checker.check_readiness.assert_called_once()
        _, kwargs = checker.check_readiness.call_args
        assert kwargs.get("reload_genomes") is True
        assert out == {"ok": 1}          # forced -> recompute returned, not deduped

    def test_idle_interval_does_not_reload(self):
        fn = self._fn()
        checker = MagicMock()
        with patch("nanometa_live.core.workflow.readiness_checker.ReadinessChecker",
                   return_value=checker), \
             patch("nanometa_live.app.callbacks.readiness._serialize_report",
                   return_value={"ok": 1}), \
             ctx_with("update-interval"):
            # distinct config so the fingerprint is not fresh and it recomputes
            fn(9, {"kraken_db": "/dbB-idle"}, None, None, None, [])
        if checker.check_readiness.called:
            _, kwargs = checker.check_readiness.call_args
            assert kwargs.get("reload_genomes") is False
