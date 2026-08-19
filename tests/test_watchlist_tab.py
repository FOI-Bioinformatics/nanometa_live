"""
Unit tests for the Verify-Taxonomy callback in app/tabs/watchlist_tab.py.

The documented behaviour (CLAUDE.md, "API circuit breaker and taxonomy
auto-selection") is that validate_entries matches the validation API set to the
DETECTED nomenclature of the loaded database: an NCBI database must not trigger
GTDB calls and vice versa, so a degraded GTDB endpoint cannot stall an NCBI run.
A database whose nomenclature could not be determined queries both, since a
guess there would be the thing that strands the run. These tests drive the
registered callback with a mocked Dash callback context and a mocked watchlist
manager, asserting which APIs reach bulk_validate_entries.
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


def _with_nomenclature(nomenclature):
    """Patch the detected profile the callback reads.

    The profile is loaded from the database index cache, which these tests do
    not build; patching the loader keeps them focused on the API-narrowing
    decision rather than on index construction.
    """
    from nanometa_live.core.taxonomy import database_profile as dp
    return patch.object(
        dp, "load_profile_for_db",
        return_value=dp.DatabaseProfile(nomenclature=nomenclature),
    )


class TestApiSelectionHonoursTheOperator:
    """The database's nomenclature must not veto the operator's checkboxes.

    These three cases previously asserted the opposite -- an NCBI database
    suppressed a GTDB-only selection and vice versa. The narrowing was
    removed on 2026-08-19: validate_entry_via_api looks up the WATCHLIST
    ENTRY's name and taxid, never a database node name, so the loaded
    database's nomenclature does not determine which service can answer. On
    a GTDB-nomenclature build the narrowing disabled NCBI, which is the
    service that resolves the 76-of-129 name-only bioshield entries.
    """

    def test_gtdb_only_selection_runs_on_an_ncbi_database(self, validate_fn):
        from nanometa_live.core.taxonomy.database_profile import Nomenclature
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            with _with_nomenclature(Nomenclature.NCBI):
                _call(validate_fn, ["gtdb"], {"kraken_db": "/db"})
        kwargs = manager.bulk_validate_entries.call_args.kwargs
        assert kwargs["use_ncbi"] is False
        assert kwargs["use_gtdb"] is True

    def test_ncbi_only_selection_runs_on_a_gtdb_database(self, validate_fn):
        from nanometa_live.core.taxonomy.database_profile import Nomenclature
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            with _with_nomenclature(Nomenclature.GTDB):
                _call(validate_fn, ["ncbi"], {"kraken_db": "/db"})
        kwargs = manager.bulk_validate_entries.call_args.kwargs
        assert kwargs["use_ncbi"] is True, (
            "NCBI was disabled because the database uses GTDB names -- but "
            "the lookup queries the watchlist entry, not the database"
        )
        assert kwargs["use_gtdb"] is False

    def test_both_ticked_queries_both_on_any_database(self, validate_fn):
        from nanometa_live.core.taxonomy.database_profile import Nomenclature
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            with _with_nomenclature(Nomenclature.NCBI):
                _call(validate_fn, ["ncbi", "gtdb"], {"kraken_db": "/db"})
        kwargs = manager.bulk_validate_entries.call_args.kwargs
        assert kwargs["use_ncbi"] is True
        assert kwargs["use_gtdb"] is True

    def test_nothing_ticked_still_returns_no_databases(self, validate_fn):
        result = _call(validate_fn, [], {"kraken_db": "/db"})
        assert result == {"error": "no_databases"}

    def test_undetected_nomenclature_queries_both(self, validate_fn):
        """Unchanged: an unreadable database narrows nothing."""
        from nanometa_live.core.taxonomy.database_profile import Nomenclature
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            with _with_nomenclature(Nomenclature.UNKNOWN):
                _call(validate_fn, ["ncbi", "gtdb"], {"kraken_db": "/db"})
        kwargs = manager.bulk_validate_entries.call_args.kwargs
        assert kwargs["use_ncbi"] is True
        assert kwargs["use_gtdb"] is True

    def test_no_database_configured_queries_both(self, validate_fn):
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _call(validate_fn, ["ncbi", "gtdb"], {})
        kwargs = manager.bulk_validate_entries.call_args.kwargs
        assert kwargs["use_ncbi"] is True
        assert kwargs["use_gtdb"] is True


class TestGuards:
    def test_no_trigger_prevents_update(self, validate_fn):
        with patch.object(wt, "ctx", MagicMock(triggered_id=None)):
            with pytest.raises(PreventUpdate):
                validate_fn(MagicMock(), 1, [], ["ncbi"], [], {})

    def test_spurious_row_button_render_prevents_update(self, validate_fn):
        # Operator feedback #6: selecting a watchlist re-renders the table,
        # ADDING the per-row validate buttons. That fires this pattern-matching
        # callback with a freshly-added (never-clicked) button whose triggered
        # value is None -> it must NOT kick off a bogus "Validating 1/1".
        spurious = MagicMock(
            triggered_id={"type": "watchlist-row-validate", "index": 263},
            triggered=[{"prop_id": "{...}.n_clicks", "value": None}],
        )
        with patch.object(wt, "ctx", spurious):
            with pytest.raises(PreventUpdate):
                validate_fn(MagicMock(), None, [None], ["ncbi"],
                            [{"type": "watchlist-row-validate", "index": 263}], {})

    def test_real_row_click_proceeds(self, validate_fn):
        # A genuine click carries a positive n_clicks as the triggered value.
        manager = MagicMock()
        manager.bulk_validate_entries.return_value = {"validated": 1, "failed": 0}
        manager._entries = {}
        real = MagicMock(
            triggered_id={"type": "watchlist-row-validate", "index": 263},
            triggered=[{"prop_id": "{...}.n_clicks", "value": 1}],
        )
        with patch.object(wt, "ctx", real), \
                patch.object(wt, "get_watchlist_manager", return_value=manager):
            validate_fn(MagicMock(), None, [1], ["ncbi"], [], {"kraken_taxonomy": "ncbi"})
        assert manager.bulk_validate_entries.called

    def test_offline_mode_passed_through(self, validate_fn):
        manager = MagicMock()
        manager.get_entries_with_toggle_state.return_value = [{"taxid": 562}]
        manager.bulk_validate_entries.return_value = {"validated": 0, "failed": 0}
        with patch.object(wt, "get_watchlist_manager", return_value=manager):
            _call(validate_fn, ["ncbi"], {"offline_mode": True})
        assert manager.bulk_validate_entries.call_args.kwargs["offline_mode"] is True
