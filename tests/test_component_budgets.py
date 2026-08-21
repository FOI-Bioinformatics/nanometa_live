"""Component budgets for the large-watchlist rendering surfaces.

The 129-entry Bioshield watchlist put ~13,000 Dash components into the
always-mounted DOM (audit 2026-08-21): 311 nested pathogen rows pre-rendered
inside collapsed accordions, a 129-row pathogens table, 129 organism cards
each carrying a dbc.Tooltip, and a 129-item missing-genome list. Chrome froze
on React reconciliation, not on the server.

These tests pin the budgets that keep that from regressing. They count
components deterministically (no timing), so they run in the normal suite.
A future contributor re-embedding rows in a collapsed container fails here.
"""

from unittest.mock import patch

import pytest
from dash.development.base_component import Component

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    get_watchlist_manager,
    reset_watchlist_manager,
)

pytestmark = pytest.mark.unit


def count_components(node) -> int:
    """Number of Dash components in a tree (children-reachable)."""
    if isinstance(node, (list, tuple)):
        return sum(count_components(c) for c in node)
    if not isinstance(node, Component):
        return 0
    return 1 + count_components(getattr(node, "children", None))


def collect_pattern_ids(node, acc=None):
    """All dict (pattern-matching) ids in a tree."""
    if acc is None:
        acc = []
    if isinstance(node, (list, tuple)):
        for c in node:
            collect_pattern_ids(c, acc)
        return acc
    if not isinstance(node, Component):
        return acc
    cid = getattr(node, "id", None)
    if isinstance(cid, dict):
        acc.append(cid)
    collect_pattern_ids(getattr(node, "children", None), acc)
    return acc


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    reset_watchlist_manager()
    yield
    reset_watchlist_manager()


class TestWatchlistFileItem:
    WL = {
        "id": "bioshield", "name": "Bioshield", "description": "Field list",
        "pathogen_count": 129, "enabled": True, "source": "user",
        "file_path": "/data/watchlists/bioshield.yaml",
    }

    def test_collapsed_item_carries_no_nested_rows(self):
        from nanometa_live.app.layouts.watchlist_layout import (
            create_watchlist_file_item,
        )
        item = create_watchlist_file_item(self.WL)
        assert count_components(item) <= 30, (
            "a collapsed watchlist file item must not embed its pathogen "
            "rows; 129 entries x ~13 components each froze the browser"
        )
        kinds = {p.get("type") for p in collect_pattern_ids(item)}
        assert "watchlist-nested-pathogen-toggle" not in kinds

    def test_collapsed_item_has_the_lazy_content_placeholder(self):
        from nanometa_live.app.layouts.watchlist_layout import (
            create_watchlist_file_item,
        )
        kinds = {p.get("type")
                 for p in collect_pattern_ids(create_watchlist_file_item(self.WL))}
        assert "watchlist-pathogen-collapse-content" in kinds


class TestLazyExpandCallback:
    @pytest.fixture
    def app(self):
        from tests.dash_test_utils import make_callback_app
        from nanometa_live.app.tabs.watchlist_tab import (
            register_watchlist_callbacks,
        )
        return make_callback_app(register_watchlist_callbacks)

    def _expand_fn(self, app):
        from tests.dash_test_utils import get_callback_fn
        return get_callback_fn(app, "watchlist-expand-icon")

    def test_open_renders_the_pathogen_rows(self, app):
        fn = self._expand_fn(app)
        from nanometa_live.app.tabs import watchlist_tab
        with patch.object(watchlist_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = {
                "type": "watchlist-expand-trigger", "index": "cdc_bioterrorism"}
            is_open, _style, content = fn(1, False)
        assert is_open is True
        kinds = [p.get("type") for p in collect_pattern_ids(content)]
        assert kinds.count("watchlist-nested-pathogen-toggle") > 10, (
            "expanding a watchlist must render its pathogen rows"
        )

    def test_close_unmounts_the_pathogen_rows(self, app):
        fn = self._expand_fn(app)
        from nanometa_live.app.tabs import watchlist_tab
        with patch.object(watchlist_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = {
                "type": "watchlist-expand-trigger", "index": "cdc_bioterrorism"}
            is_open, _style, content = fn(1, True)
        assert is_open is False
        assert content == []


class TestPathogensTablePagination:
    """The 129-row table renders one 25-row page, not every row."""

    @pytest.fixture
    def app(self):
        from tests.dash_test_utils import make_callback_app
        from nanometa_live.app.tabs.watchlist_tab import (
            register_watchlist_callbacks,
        )
        return make_callback_app(register_watchlist_callbacks)

    @pytest.fixture
    def manager(self):
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: None):
            mgr = get_watchlist_manager()
            mgr._entries.clear()
            mgr._name_index.clear()
            for i in range(129):
                mgr.add_custom_entry({
                    "taxid": 91000 + i, "name": f"Fillerus organismus{i}",
                    "threat_level": "high", "enabled": True,
                    "alert_threshold": 10,
                })
            mgr._loaded = True
            yield mgr

    def _table_fn(self, app):
        from tests.dash_test_utils import get_callback_fn
        return get_callback_fn(app, "watchlist-pathogens-table")

    def _call(self, app, page=1, search="", trigger="watchlist-table-refresh"):
        fn = self._table_fn(app)
        from nanometa_live.app.tabs import watchlist_tab
        with patch.object(watchlist_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = trigger
            return fn({"last_update": "x"}, 1, search, None, {}, page, {})

    def test_one_page_of_rows_is_rendered(self, app, manager):
        children, count, _style, _max_value, _page = self._call(app)
        kinds = [p.get("type") for p in collect_pattern_ids(children)]
        assert kinds.count("watchlist-row-toggle") == 25, (
            "the table must render one page, not all 129 rows"
        )
        assert count == "129", "the count badge keeps the full filtered count"

    def test_second_page_shows_the_next_slice(self, app, manager):
        expected = manager.get_entries_with_toggle_state()[25]["taxid"]
        children, _c, _s, _m, _p = self._call(app, page=2)
        toggles = [p for p in collect_pattern_ids(children)
                   if p.get("type") == "watchlist-row-toggle"]
        assert toggles[0]["index"] == expected

    def test_search_resets_to_page_one(self, app, manager):
        _ch, _c, _s, _m, page = self._call(
            app, page=5, search="Fillerus",
            trigger="watchlist-search-input")
        assert page == 1

    def test_max_value_covers_all_pages(self, app, manager):
        _ch, _c, _s, max_value, _p = self._call(app)
        assert max_value == 6  # ceil(129 / 25)


class TestOrganismCardBudget:
    def _card(self, **kw):
        from nanometa_live.app.components.organism_components import OrganismCard
        defaults = dict(name="Testus organismus", abundance=1.2,
                        read_count=500, confidence="high", taxid=42,
                        rank="S", is_watched=True)
        defaults.update(kw)
        return OrganismCard(**defaults)

    def _walk(self, node):
        if isinstance(node, (list, tuple)):
            for c in node:
                yield from self._walk(c)
            return
        if not isinstance(node, Component):
            return
        yield node
        yield from self._walk(getattr(node, "children", None))

    def test_card_carries_no_tooltip_component(self):
        import dash_bootstrap_components as dbc
        tooltips = [n for n in self._walk(self._card())
                    if isinstance(n, dbc.Tooltip)]
        assert not tooltips, (
            "each dbc.Tooltip is a react-popper instance; 129 cards froze "
            "the browser. Use a native title= attribute instead."
        )

    def test_confidence_explanation_survives_as_native_title(self):
        titles = [getattr(n, "title", None) for n in self._walk(self._card())]
        assert any(t and "confidence" in t for t in titles if isinstance(t, str))


class TestNotDetectedLazyRender:
    SPECIES = [
        {"name": f"Quietus organismus{i}", "abundance": 0.0, "reads": 0,
         "taxid": 95000 + i, "annotation": "", "threat_level": "high",
         "blast": None}
        for i in range(30)
    ]

    @pytest.fixture
    def app(self):
        from tests.dash_test_utils import make_callback_app
        from nanometa_live.app.tabs.main_tab import register_main_callbacks
        return make_callback_app(register_main_callbacks)

    def _fn(self, app):
        from tests.dash_test_utils import get_callback_fn
        return get_callback_fn(app, "not-detected-collapse")

    def test_open_renders_the_cards(self, app):
        is_open, content = self._fn(app)(1, False, self.SPECIES)
        assert is_open is True
        cards = [p for p in collect_pattern_ids(content)
                 if p.get("type") == "confidence-badge"]
        assert len(cards) == 30

    def test_close_unmounts_the_cards(self, app):
        is_open, content = self._fn(app)(1, True, self.SPECIES)
        assert is_open is False
        assert content == []


class TestWatchedCardsOverflowCap:
    def test_more_than_max_visible_cards_are_collapsed(self):
        import dash_bootstrap_components as dbc
        from dash import html
        from nanometa_live.app.tabs.main_tab import (
            MAX_VISIBLE_CARDS, wrap_cards_with_overflow,
        )
        cards = [dbc.Col(html.Div(f"card{i}")) for i in range(30)]
        container = wrap_cards_with_overflow(
            cards, collapse_id="watched-cards-overflow",
            button_id="show-more-watched-btn", noun="watched organisms")
        text = str(container)
        assert count_components(container) > 30  # all cards present
        assert "watched-cards-overflow" in text
        assert f"Show {30 - MAX_VISIBLE_CARDS} more watched organisms" in text

    def test_few_cards_get_no_overflow_machinery(self):
        import dash_bootstrap_components as dbc
        from dash import html
        from nanometa_live.app.tabs.main_tab import wrap_cards_with_overflow
        cards = [dbc.Col(html.Div(f"card{i}")) for i in range(3)]
        container = wrap_cards_with_overflow(
            cards, collapse_id="watched-cards-overflow",
            button_id="show-more-watched-btn", noun="watched organisms")
        assert "watched-cards-overflow" not in str(container)


class TestGenomeStatsTabGate:
    """update_genome_stats must not recompute on every tab switch.

    Its Input("tabs", "active_tab") fires for EVERY tab; the body stats
    every enabled entry (~500 syscalls at 129 entries) and renders one
    item per missing genome, so switching to the QC tab paid the full
    Preparation-tab cost.
    """

    @pytest.fixture
    def app(self):
        from tests.dash_test_utils import make_callback_app
        from nanometa_live.app.tabs.preparation_tab import (
            register_preparation_callbacks,
        )
        return make_callback_app(register_preparation_callbacks)

    def test_switching_to_another_tab_skips_the_recompute(self, app):
        from dash.exceptions import PreventUpdate
        from tests.dash_test_utils import get_callback_fn
        fn = get_callback_fn(app, "genome-stat-downloaded")
        from nanometa_live.app.tabs import preparation_tab
        with patch.object(preparation_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = "tabs"
            with pytest.raises(PreventUpdate):
                fn(None, None, "qc-tab", {})


class TestWatchlistFilesCallback:
    @pytest.fixture
    def app(self):
        from tests.dash_test_utils import make_callback_app
        from nanometa_live.app.tabs.watchlist_tab import (
            register_watchlist_callbacks,
        )
        return make_callback_app(register_watchlist_callbacks)

    def test_file_lists_render_headers_only(self, app, monkeypatch):
        from tests.dash_test_utils import get_callback_fn
        fn = get_callback_fn(app, "watchlist-builtin-list")

        preview_calls = {"n": 0}
        orig = WatchlistManager.get_watchlist_pathogens_preview

        def counting(self, wl_id):
            preview_calls["n"] += 1
            return orig(self, wl_id)

        monkeypatch.setattr(
            WatchlistManager, "get_watchlist_pathogens_preview", counting)

        builtin_items, custom_items = fn({"last_update": "x"}, {})
        total = count_components(builtin_items) + count_components(custom_items)
        # 9 builtin lists x ~25 components/header. The pre-fix rendering
        # carried ~4,400 components (311 nested rows).
        assert total <= 400, total
        assert preview_calls["n"] == 0, (
            "the file list must not load every watchlist's pathogens up "
            "front; rows render on expand"
        )
