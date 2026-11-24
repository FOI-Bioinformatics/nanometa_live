"""Add Custom Species refuses input it cannot use.

Live test 2026-11-24: taxid -5 and alert threshold 0 were accepted, and
adding the same species twice reported "Added" both times.
"""

from types import SimpleNamespace

import pytest

from nanometa_live.app.tabs.watchlist_add_helpers import custom_species_problem

pytestmark = pytest.mark.unit

EXISTING = {
    562: SimpleNamespace(name="Escherichia coli", taxid=562, db_taxid=None),
    4005020: SimpleNamespace(name="Bacillus_A anthracis", taxid=1392, db_taxid=4005020),
}


def _p(**kw):
    base = dict(name="Yersinia pestis", taxid=632, db_taxid=None, threshold=10,
                entries=EXISTING)
    base.update(kw)
    return custom_species_problem(**base)


def test_valid_entry_has_no_problem():
    assert _p() is None
    assert _p(taxid=None, threshold=None) is None  # optional fields


@pytest.mark.parametrize("taxid", [-5, 0, 1.5, "abc"])
def test_bad_taxid(taxid):
    assert "Taxonomy ID" in _p(taxid=taxid)


def test_bad_db_taxid():
    assert "Database taxid" in _p(db_taxid=-1)


@pytest.mark.parametrize("threshold", [0, -3, 2.5])
def test_bad_threshold(threshold):
    assert "threshold" in _p(threshold=threshold).lower()


def test_duplicate_taxid_pair_is_refused():
    assert "already on the watchlist" in _p(name="E. coli", taxid=562)


def test_duplicate_name_is_refused():
    assert "already on the watchlist" in _p(name="escherichia coli ", taxid=None)


def test_same_ncbi_taxid_with_a_different_db_node_is_allowed():
    # E. coli / E. coli_F: one NCBI taxid, distinct database nodes.
    assert _p(name="Escherichia coli_F", taxid=562, db_taxid=4000123) is None


def test_callback_refuses_a_duplicate_without_adding(monkeypatch):
    import dash
    from dash import no_update
    from nanometa_live.app.tabs import watchlist_tab
    from tests.dash_test_utils import get_callback_fn

    class Manager:
        added = []

        def get_all_entries(self):
            return EXISTING

        def add_custom_entry(self, data):
            self.added.append(data)

    manager = Manager()
    monkeypatch.setattr(watchlist_tab, "get_watchlist_manager", lambda: manager)
    app = dash.Dash(__name__)
    watchlist_tab.register_watchlist_callbacks(app)
    fn = get_callback_fn(app, "watchlist-add-feedback.children",
                         input_contains="watchlist-add-btn")
    out = fn(1, "Escherichia coli", 562, None, "high", 10, None, "", None)
    assert out[0] is no_update
    assert "already on the watchlist" in str(out[1].children)
    assert manager.added == []
