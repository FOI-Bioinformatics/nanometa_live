"""
Empty-state regression for the watchlist pathogens table.

When the taxonomy index has not been built (taxmap-collection store
empty AND the global mapping collection is empty), the table used to
render every entry as "Not Found", misleading the operator into
thinking the species were absent from the database. The fix turns
that into a single empty-state card pointing at the Preparation tab's
Scan Database control. This test pins that contract.
"""
from unittest.mock import patch

from nanometa_live.app.tabs.watchlist_tab import register_watchlist_callbacks


def _stub_app_recorder():
    """Capture the function registered with @app.callback so we can call it."""
    captured = {}

    class StubApp:
        def callback(self, *args, **kwargs):
            def decorator(fn):
                # update_pathogens_table is the first callback that takes
                # taxmap-collection as an Input; capture it by name.
                if fn.__name__ == "update_pathogens_table":
                    captured["fn"] = fn
                return fn
            return decorator

    return StubApp(), captured


class _StubManager:
    """Pretend to be a WatchlistManager with two enabled entries."""
    _loaded = True

    def load_config(self, _config):
        self._loaded = True

    def get_entries_with_toggle_state(self):
        return [
            {"taxid": 562, "name": "Escherichia coli", "enabled": True,
             "threat_level": "moderate", "common_name": "E. coli"},
            {"taxid": 1280, "name": "Staphylococcus aureus", "enabled": True,
             "threat_level": "high", "common_name": "S. aureus"},
        ]


def test_empty_taxmap_collection_renders_empty_state_not_not_found():
    app, captured = _stub_app_recorder()
    register_watchlist_callbacks(app)
    fn = captured.get("fn")
    assert fn is not None, "update_pathogens_table not registered"

    with patch(
        "nanometa_live.app.tabs.watchlist_tab.get_watchlist_manager",
        return_value=_StubManager(),
    ), patch(
        "nanometa_live.core.taxonomy.taxid_mapping.get_mapping_collection",
        return_value=None,
    ):
        rows, count, badge_style = fn(
            tab_state={},
            table_refresh=0,
            search_term="",
            rescan_complete=None,
            taxmap_collection={},  # empty store
            config={},
        )

    # The count badge still reflects the watchlist size...
    assert count == "2"
    assert badge_style == {"display": "inline-block"}
    # ...but a single empty-state card stands in for the rows.
    assert len(rows) == 1, "exactly one empty-state node, not N 'Not Found' rows"

    # The empty-state copy should name the Preparation tab and the Scan
    # Database control so the operator knows where to act.
    rendered = str(rows[0])
    assert "Taxonomy index" in rendered
    assert "Preparation" in rendered
    assert "Scan Database" in rendered
    # And must not render the legacy "Not Found" text per row.
    assert "Not Found" not in rendered
