"""Replacing an uploaded watchlist replaces what it screens.

Upload mylist.yaml, then upload a changed mylist.yaml with "Replace
existing": the file on disk held only the new entries, but the manager
still screened the old ones as well (117 -> 118 entries in the live test of
2026-11-24), so an organism removed from a list kept being screened until
restart. Reloading a list withdraws its previous contribution first.
"""

from unittest.mock import patch

import pytest
import yaml

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    reset_watchlist_manager,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    reset_watchlist_manager()
    yield
    reset_watchlist_manager()


def _write(path, entries):
    path.write_text(yaml.safe_dump({
        "metadata": {"name": "mylist", "version": "2.0"},
        "pathogens": [{"name": n, "taxid_ncbi": t, "threat_level": "high"}
                      for n, t in entries],
    }))


def test_reload_withdraws_entries_the_new_file_dropped(tmp_path):
    f = tmp_path / "mylist.yaml"
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        m = WatchlistManager()
        _write(f, [("Imaginary organismus", 9100001)])
        m.reload_custom_yaml_file(str(f))
        assert any(e.name == "Imaginary organismus" for e in m.get_active_entries().values())

        _write(f, [("Imaginary organismus two", 9100002)])
        m.reload_custom_yaml_file(str(f))
        names = {e.name for e in m.get_active_entries().values()}
    assert "Imaginary organismus two" in names
    assert "Imaginary organismus" not in names


def test_finalize_uses_reload(tmp_path):
    """The import finalizer must reload, not add on top."""
    import inspect
    from nanometa_live.app.tabs import watchlist_tab
    src = inspect.getsource(watchlist_tab)
    i = src.index("def finalize_watchlist_import")
    body = src[i:src.index("@app.callback", i)]
    assert "reload_custom_yaml_file" in body
