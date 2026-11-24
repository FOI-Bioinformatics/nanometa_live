"""A watchlist file toggle re-fired by Dash must not write the session file.

Dash fires an ALL callback when matching components are ADDED to the layout,
with their current values (CLAUDE.md, large-watchlist invariants). On page
load ``toggle_watchlist_file`` therefore "applied" every watchlist's current
state and wrote ``last-session.yaml``, so the header badge flipped from "Not
saved" to "Auto-saved" seconds after load with no operator action, and the
session file was rewritten on every page load. ``toggle_nested_pathogen``
already ignores a value equal to the current state; the file toggle now does
the same.
"""

from unittest.mock import MagicMock, patch

import pytest
from dash.exceptions import PreventUpdate

from tests.dash_test_utils import get_callback_fn, make_callback_app

pytestmark = pytest.mark.callback


@pytest.fixture
def toggle_fn():
    from nanometa_live.app.tabs.watchlist_tab import register_watchlist_callbacks
    app = make_callback_app(register_watchlist_callbacks)
    return get_callback_fn(app, "watchlist-table-refresh.data",
                           input_contains="watchlist-file-toggle")


def _call(toggle_fn, enabled_ids, changed, value):
    from nanometa_live.app.tabs import watchlist_tab as wt

    manager = MagicMock()
    manager.get_enabled_watchlists.return_value = set(enabled_ids)
    manager.export_config.return_value = {}
    saves = MagicMock()
    ids = [{"type": "watchlist-file-toggle", "index": changed}]
    with patch.object(wt, "get_watchlist_manager", return_value=manager), \
         patch.object(wt, "_save_last_session", saves), \
         patch.object(wt, "ctx") as mock_ctx:
        mock_ctx.triggered_id = ids[0]
        try:
            toggle_fn([value], ids, 0, {})
            prevented = False
        except PreventUpdate:
            prevented = True
    return prevented, saves.call_count, manager


def test_refire_with_the_current_state_changes_nothing(toggle_fn):
    prevented, saves, manager = _call(toggle_fn, {"cdc"}, "cdc", True)
    assert prevented
    assert saves == 0
    manager.enable_watchlist.assert_not_called()


def test_refire_of_a_disabled_list_changes_nothing(toggle_fn):
    prevented, saves, _ = _call(toggle_fn, set(), "who", False)
    assert prevented and saves == 0


def test_a_real_toggle_is_applied_and_saved(toggle_fn):
    prevented, saves, manager = _call(toggle_fn, set(), "cdc", True)
    assert not prevented
    assert saves == 1
    manager.enable_watchlist.assert_called_once_with("cdc")
