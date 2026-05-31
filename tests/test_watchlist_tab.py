"""
Unit tests for the Verify-Taxonomy callback in app/tabs/watchlist_tab.py.

The documented behaviour (CLAUDE.md, "API circuit breaker and taxonomy
auto-selection") is that validate_entries matches the validation API set to the
configured kraken_taxonomy: an NCBI database must not trigger GTDB calls and
vice versa, so a degraded GTDB endpoint cannot stall an NCBI run. These tests
drive the registered callback with a mocked Dash callback context and a mocked
watchlist manager, asserting which APIs reach bulk_validate_entries.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.callback
from dash import Dash
from dash.exceptions import PreventUpdate

from dash_test_utils import get_callback_fn
from nanometa_live.app.tabs import watchlist_tab as wt
from nanometa_live.app.tabs.watchlist_tab import register_watchlist_callbacks


@pytest.fixture
def validate_fn():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_watchlist_callbacks(app)
    # validate_entries is now a background callback whose real output is the
    # watchlist-validation-results store (the progress bar/modal are driven
    # via progress=/running=).
    return get_callback_fn(app, "watchlist-validation-results.data")


def _call(fn, api_options, config, triggered_id="watchlist-validate-all-btn"):
    # Background callback signature: (set_progress, validate_all,
    # validate_row_clicks, api_options, row_ids, config).
    set_progress = MagicMock()
    with patch.object(wt, "ctx", MagicMock(triggered_id=triggered_id)):
        return fn(set_progress, 1, [], api_options, [], config)


class TestApiSelectionByTaxonomy:
    def test_ncbi_database_suppresses_gtdb_only_selection(self, validate_fn):
        # Only GTDB ticked, but the database is NCBI -> GTDB is dropped, leaving
        # no API selected, so the callback returns the "no databases" payload
        # without ever instantiating the watchlist manager.
        result = _call(validate_fn, ["gtdb"], {"kraken_taxonomy": "ncbi"})
        assert result == {"error": "no_databases"}

    def test_gtdb_database_suppresses_ncbi_only_selection(self, validate_fn):
        result = _call(validate_fn, ["ncbi"], {"kraken_taxonomy": "gtdb"})
        assert result == {"error": "no_databases"}

    def test_ncbi_database_runs_ncbi_only(self, validate_fn):
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _call(validate_fn, ["ncbi", "gtdb"], {"kraken_taxonomy": "ncbi"})
        kwargs = manager.bulk_validate_entries.call_args.kwargs
        assert kwargs["use_ncbi"] is True
        assert kwargs["use_gtdb"] is False

    def test_both_selected_without_taxonomy_constraint(self, validate_fn):
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _call(validate_fn, ["ncbi", "gtdb"], {})  # no kraken_taxonomy
        kwargs = manager.bulk_validate_entries.call_args.kwargs
        assert kwargs["use_ncbi"] is True
        assert kwargs["use_gtdb"] is True


class TestGuards:
    def test_no_trigger_prevents_update(self, validate_fn):
        with patch.object(wt, "ctx", MagicMock(triggered_id=None)):
            with pytest.raises(PreventUpdate):
                validate_fn(MagicMock(), 1, [], ["ncbi"], [], {})

    def test_offline_mode_passed_through(self, validate_fn):
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 0, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _call(validate_fn, ["ncbi"], {"offline_mode": True})
        assert manager.bulk_validate_entries.call_args.kwargs["offline_mode"] is True
