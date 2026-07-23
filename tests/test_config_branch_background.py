"""P2 audit finding: the pipeline-branch dropdown populate hits the GitHub API
on the Config tab's cold load and every Remote/Local toggle. It is now a
background callback so a cold fetch does not block the tab render.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import dash_bootstrap_components as dbc
import pytest
from dash import Dash

pytestmark = pytest.mark.callback

from nanometa_live.app.tabs.config_tab import register_config_callbacks


@pytest.fixture
def app():
    a = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
             suppress_callback_exceptions=True)
    register_config_callbacks(a, MagicMock())
    return a


def test_branch_populate_is_background(app):
    for cb, spec in app.callback_map.items():
        if "pipeline-branch-input" in cb and \
                "pipeline-source-type-input" in str(spec.get("inputs")):
            assert bool(spec.get("background")), \
                "populate_pipeline_branch_options must be a background callback"
            return
    raise AssertionError("branch populate callback not found")
