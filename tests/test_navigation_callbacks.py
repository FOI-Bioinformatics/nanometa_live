"""Callback tests for app/callbacks/navigation.py (wizard / modal navigation)."""

from unittest.mock import MagicMock

import pytest
from dash import Dash, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.app.callbacks.navigation import register_navigation
from dash_test_utils import get_callback_fn, ctx_with


@pytest.fixture(scope="module")
def nav_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_navigation(app, MagicMock())
    return app


# --------------------------------------------------------------------------- #
# welcome modal
# --------------------------------------------------------------------------- #

def test_welcome_modal_dismiss_routes_to_config(nav_app):
    fn = get_callback_fn(nav_app, "welcome-modal")
    with ctx_with("close-welcome-modal"):
        is_open, tab = fn(True, 1)
    assert is_open is False
    assert tab == "config-tab"


def test_welcome_modal_shows_on_first_visit(nav_app):
    fn = get_callback_fn(nav_app, "welcome-modal")
    with ctx_with("some-other-trigger"):
        is_open, tab = fn(False, 0)   # not already shown -> show
        assert is_open is True
        assert tab is no_update
        is_open2, _ = fn(True, 0)     # already shown -> stay hidden
        assert is_open2 is False


def test_mark_welcome_shown(nav_app):
    fn = get_callback_fn(nav_app, "welcome-shown")
    assert fn(1) is True


# --------------------------------------------------------------------------- #
# wizard navigation
# --------------------------------------------------------------------------- #

def test_config_to_watchlist_advances_and_applies(nav_app):
    fn = get_callback_fn(nav_app, "apply-config-button")
    tab, apply_clicks = fn(1, 3)
    assert tab == "watchlist-tab"
    assert apply_clicks == 4          # bumps apply-config n_clicks
    tab2, apply2 = fn(1, None)
    assert apply2 == 1                # None -> 1


def test_preparation_to_deployment(nav_app):
    fn = get_callback_fn(nav_app, "tabs", input_contains="merged-next-deployment-btn")
    assert fn(1) == "deployment-tab"


# --------------------------------------------------------------------------- #
# open-results modal close
# --------------------------------------------------------------------------- #

def test_close_open_results_modal(nav_app):
    fn = get_callback_fn(nav_app, "open-results-modal", input_contains="open-results-close-btn")
    assert fn(1) is False
    with pytest.raises(PreventUpdate):
        fn(0)
