"""The Watchlist Files panel must say WHICH file it loaded.

The panel showed a name, a source badge ("User") and a pathogen count, but
never the path. That is not enough to identify the file, because the user tier
MOVES: ``get_watchlists_dir_from_env`` resolves to
``<project_dir>/.nanometa/watchlists`` when a project is set and
``<data_dir>/watchlists`` otherwise, and the project defaults to the current
working directory. Four copies of ``bioshield_agents.yaml`` accumulated across
a few days of runs, and the GUI reported the enabled watchlist identically for
each.

The cost was real: an operator edited the watchlist, reloaded, and saw none of
their changes, because the app was reading a different copy. Nothing on screen
could distinguish "your edit did not take" from "you edited the wrong file".

So the resolved path travels with the metadata and is rendered on the row.
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.layouts.watchlist_layout import create_watchlist_file_item


def _component_text(component) -> str:
    """Flatten a Dash component tree into searchable text incl. attributes."""
    out = []

    def walk(node):
        if node is None or isinstance(node, (str, int, float, bool)):
            if node is not None:
                out.append(str(node))
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        for attr in ("title", "children"):
            if hasattr(node, attr):
                walk(getattr(node, attr))

    walk(component)
    return " ".join(out)


WL = {
    "id": "bioshield_agents",
    "name": "Bioshield Agents",
    "description": "Exercise list",
    "source": "user",
    "pathogen_count": 129,
    "enabled": True,
    "file_path": "/Users/x/nanometa-projects/bioshield/.nanometa/watchlists/bioshield_agents.yaml",
}


class TestPathIsVisible:
    def test_the_resolved_path_is_rendered(self):
        text = _component_text(create_watchlist_file_item(WL))
        assert WL["file_path"] in text, (
            "the panel identifies a watchlist only by name and tier, so two "
            "copies in different directories are indistinguishable"
        )

    def test_the_existing_details_survive(self):
        text = _component_text(create_watchlist_file_item(WL))
        assert "Bioshield Agents" in text
        assert "129 pathogens" in text

    def test_a_missing_path_does_not_break_the_row(self):
        # Built-in watchlists and older callers may not supply one.
        wl = {k: v for k, v in WL.items() if k != "file_path"}
        text = _component_text(create_watchlist_file_item(wl))
        assert "Bioshield Agents" in text


class TestMetadataCarriesThePath:
    def test_available_watchlists_include_file_path(self):
        from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager

        m = WatchlistManager()
        available = m.get_available_watchlists()
        assert available, "no watchlists discovered; cannot verify the contract"
        for wl in available:
            assert wl.get("file_path"), (
                f"{wl.get('id')} carries no file_path, so the UI cannot show "
                f"which file it loaded"
            )
