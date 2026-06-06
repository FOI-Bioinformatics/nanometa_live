"""Callback-level tests for the Organisms (main) tab.

test_main_tab.py exercises the loaders/helpers; this file invokes the actual
registered @app.callback bodies (extracted via dash_test_utils) so the callback
orchestration itself is covered, not just the pure helpers it delegates to.
"""

from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
from dash import Dash
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs import main_tab as main_tab_mod
from nanometa_live.app.tabs.main_tab import register_main_callbacks
from dash_test_utils import get_callback_fn


@contextmanager
def ctx_with(triggered_id):
    """Patch the module-local ``ctx`` in main_tab (it does ``from dash import
    ctx``, so patching ``dash.ctx`` would not reach it)."""
    fake = MagicMock(
        triggered_id=triggered_id,
        triggered=[{"prop_id": f"{triggered_id}.n_clicks", "value": 1}],
    )
    with patch.object(main_tab_mod, "ctx", fake):
        yield


@pytest.fixture(scope="module")
def main_app():
    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
    register_main_callbacks(app)
    return app


# --------------------------------------------------------------------------- #
# toggle_show_more_organisms
# --------------------------------------------------------------------------- #

def test_toggle_show_more_opens_and_relabels(main_app):
    fn = get_callback_fn(main_app, "show-more-organisms-btn")
    # closed -> open
    is_open, label = fn(1, False)
    assert is_open is True
    assert "fewer" in str(label).lower()
    # open -> closed
    is_open, label = fn(2, True)
    assert is_open is False
    assert "more" in str(label).lower()


def test_toggle_show_more_no_click_is_noupdate(main_app):
    from dash import no_update
    fn = get_callback_fn(main_app, "show-more-organisms-btn")
    assert fn(0, False) == (no_update, no_update)


# --------------------------------------------------------------------------- #
# toggle_export_modal
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("trigger,fmt", [
    ("export-all-txt", "txt"),
    ("export-all-csv", "csv"),
    ("export-all-xlsx", "xlsx"),
])
def test_export_modal_opens_with_format(main_app, trigger, fmt):
    fn = get_callback_fn(main_app, "export-modal")
    with ctx_with(trigger):
        is_open, value = fn(1, 1, 1, 0, 0, False, "txt")
    assert is_open is True
    assert value == fmt


def test_export_modal_closes_on_confirm_and_cancel(main_app):
    fn = get_callback_fn(main_app, "export-modal")
    with ctx_with("confirm-export"):
        is_open, value = fn(0, 0, 0, 1, 0, True, "csv")
    assert is_open is False
    assert value == "csv"  # format preserved
    with ctx_with("cancel-export"):
        is_open, _ = fn(0, 0, 0, 0, 1, True, "csv")
    assert is_open is False


# --------------------------------------------------------------------------- #
# export_organism_data
# --------------------------------------------------------------------------- #

def test_export_organism_data_builds_payload(main_app):
    fn = get_callback_fn(main_app, "download-organism-data")
    rows = [{"name": "Escherichia coli", "taxid": 562, "reads": 900, "%": 95.0}]
    out = fn(1, "csv", "organisms", rows, {})
    assert isinstance(out, dict)
    # dcc.Download payloads carry content + filename
    assert "content" in out and "filename" in out
    assert out["filename"].endswith(".csv")
    assert "Escherichia coli" in out["content"]


def test_export_organism_data_noupdate_without_rows(main_app):
    from dash import no_update
    fn = get_callback_fn(main_app, "download-organism-data")
    assert fn(1, "csv", "organisms", [], {}) is no_update
    assert fn(0, "csv", "organisms", [{"x": 1}], {}) is no_update


# --------------------------------------------------------------------------- #
# update_organisms_freshness_row
# --------------------------------------------------------------------------- #

def test_freshness_row_hidden_for_single_sample(main_app):
    fn = get_callback_fn(main_app, "organisms-freshness-row")
    assert fn({}, ["All Samples"]) == []
    assert fn({}, ["barcode01"]) == []      # one real sample -> no pills
    assert fn({}, None) == []


def test_freshness_row_renders_pills_for_multiplex(main_app):
    fn = get_callback_fn(main_app, "organisms-freshness-row")
    children = fn({"barcode01": 1.0, "barcode02": 2.0}, ["barcode01", "barcode02"])
    assert isinstance(children, list)
    assert len(children) == 2


# --------------------------------------------------------------------------- #
# update_main_results (empty-data path)
# --------------------------------------------------------------------------- #

def test_update_main_results_empty_returns_nine_outputs(main_app):
    fn = get_callback_fn(main_app, "organism-cards-container")
    with ctx_with("apply-organism-filters"):
        result = fn(
            None, 1, None, [], 0,    # fingerprint, apply, sample, watchlist, n_intervals
            10, 0, ["S"],            # top_count, min_abundance, tax_ranks
            {}, {}, {},              # config, status, overall_status_cache
        )
    # 9 outputs: summary, cards, table, total-count, results-count,
    # watched-alert, watched-section-style, watched-cards, watched-count
    assert isinstance(result, tuple)
    assert len(result) == 9
    # empty data -> zero organism count
    assert result[3] == "0"
