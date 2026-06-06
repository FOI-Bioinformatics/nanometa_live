"""Callback-level tests for the Quality Control tab.

Invokes the real @app.callback bodies (modal toggles + the empty-data paths of
the figure/stat/table builders) which were previously uncovered.
"""

from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
from dash import Dash
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs import qc_tab as qc_mod
from nanometa_live.app.tabs.qc_tab import register_qc_callbacks
from dash_test_utils import get_callback_fn


@pytest.fixture(scope="module")
def qc_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_qc_callbacks(app)
    return app


@contextmanager
def ctx_trigger(triggered_id):
    """Patch qc_tab's module-local ctx (it does ``from dash import ctx``)."""
    fake = MagicMock(triggered_id=triggered_id,
                     triggered=[{"prop_id": f"{triggered_id}.n_clicks"}])
    with patch.object(qc_mod, "ctx", fake):
        yield


# --------------------------------------------------------------------------- #
# modal toggles
# --------------------------------------------------------------------------- #

def test_help_modal_toggles(qc_app):
    fn = get_callback_fn(qc_app, "qc-help-modal")
    assert fn(1, 0, False) is True       # help opens
    assert fn(0, 1, True) is False       # close closes
    assert fn(0, 0, True) is True        # no click -> unchanged


def test_export_modal_toggles(qc_app):
    fn = get_callback_fn(qc_app, "qc-export-modal")
    assert fn(1, 0, 0, False) is True
    assert fn(0, 1, 0, True) is False
    assert fn(None, None, None, True) is True


# --------------------------------------------------------------------------- #
# big data callbacks: empty-data paths
# --------------------------------------------------------------------------- #

def test_update_qc_stats_empty_returns_defaults(qc_app):
    fn = get_callback_fn(qc_app, "qc-reads-pre-filtering")
    with ctx_trigger("selected-sample"):
        result = fn(None, "All Samples", 0, {}, {})
    assert isinstance(result, (list, tuple))
    assert len(result) == 10               # ten stat tiles
    joined = " ".join(result)
    assert "passed filtering: 0" in joined
    assert "Files processed: 0" in joined


def test_update_qc_plots_empty_returns_four_figures(qc_app):
    fn = get_callback_fn(qc_app, "cumul-reads-graph")
    with ctx_trigger("selected-sample"):
        result = fn(None, "All Samples", 0, {}, {})
    assert isinstance(result, (list, tuple))
    assert len(result) == 4                # cumul-reads, cumul-bp, reads, bp
    # each output is a plotly figure (dict-like with 'data'/'layout' or Figure)
    for fig in result:
        assert fig is not None


def test_update_per_sample_table_empty_returns_list(qc_app):
    fn = get_callback_fn(qc_app, "per-sample-table")
    with ctx_trigger("selected-sample"):
        result = fn(None, "All Samples", 0, {}, {})
    assert isinstance(result, list)
