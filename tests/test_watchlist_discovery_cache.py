"""Watchlist discovery consults its cache instead of re-parsing every YAML.

`discover_watchlists` wrote `_cached_watchlists` at the end but never read
it at the top (verified plain bug, round-2 audit 2026-08-22), so every
watchlist-tab-state change re-parsed the whole corpus THREE times (file
list, quick-start styles, invalid sweep). The cache now keys on a corpus
fingerprint (per-tier scandir of names/mtimes/sizes), and
`find_invalid_watchlist_files` caches its sweep on the same fingerprint.
"""

import time

import pytest

from nanometa_live.core.watchlist.watchlist_loader import WatchlistLoader

pytestmark = pytest.mark.unit

VALID_YAML = """\
version: "2.0"
metadata:
  name: "List {n}"
pathogens:
  - name: "Testus organismus{n}"
    taxid_ncbi: {taxid}
"""


@pytest.fixture
def loader(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path / "home"))
    user_dir = tmp_path / "home" / "watchlists"
    user_dir.mkdir(parents=True)
    for n in range(3):
        (user_dir / f"list{n}.yaml").write_text(
            VALID_YAML.format(n=n, taxid=1000 + n))
    # An empty builtin tier keeps the corpus fully under test control.
    app_root = tmp_path / "approot"
    (app_root / "core" / "config" / "data" / "watchlists").mkdir(parents=True)
    return WatchlistLoader(app_root=app_root, user_dir=user_dir)


class TestDiscoveryCache:
    def test_second_discovery_parses_nothing(self, loader, monkeypatch):
        import yaml as yaml_module
        from nanometa_live.core.watchlist import watchlist_loader as wl_mod
        first = loader.discover_watchlists()
        assert len(first) == 3

        calls = {"n": 0}
        orig = yaml_module.safe_load

        def counting(stream):
            calls["n"] += 1
            return orig(stream)

        monkeypatch.setattr(wl_mod.yaml, "safe_load", counting)
        second = loader.discover_watchlists()
        assert {m.id for m in second} == {m.id for m in first}
        assert calls["n"] == 0, (
            f"{calls['n']} YAML parses on an unchanged corpus; discovery "
            f"must serve from its cache"
        )

    def test_a_new_file_is_discovered(self, loader):
        loader.discover_watchlists()
        time.sleep(0.01)
        (loader.user_watchlist_dir / "list9.yaml").write_text(
            VALID_YAML.format(n=9, taxid=1009))
        ids = {m.id for m in loader.discover_watchlists()}
        assert "list9" in ids

    def test_an_edited_file_is_reread(self, loader):
        loader.discover_watchlists()
        time.sleep(0.01)
        target = loader.user_watchlist_dir / "list0.yaml"
        target.write_text(VALID_YAML.format(n=0, taxid=1000).replace(
            "List 0", "Renamed List"))
        names = {m.name for m in loader.discover_watchlists()}
        assert "Renamed List" in names

    def test_invalidate_cache_forces_a_rescan(self, loader, monkeypatch):
        import yaml as yaml_module
        from nanometa_live.core.watchlist import watchlist_loader as wl_mod
        loader.discover_watchlists()
        calls = {"n": 0}
        orig = yaml_module.safe_load

        def counting(stream):
            calls["n"] += 1
            return orig(stream)

        monkeypatch.setattr(wl_mod.yaml, "safe_load", counting)
        loader.invalidate_cache()
        loader.discover_watchlists()
        assert calls["n"] >= 3


class TestInvalidSweepCache:
    def test_second_sweep_validates_nothing(self, loader, monkeypatch):
        (loader.user_watchlist_dir / "broken.yaml").write_text("pathogens: 1")
        first = loader.find_invalid_watchlist_files()
        assert [name for name, _ in first] == ["broken.yaml"]

        calls = {"n": 0}
        orig = WatchlistLoader.validate_and_parse

        def counting(self, path, progress_cb=None):
            calls["n"] += 1
            return orig(self, path, progress_cb)

        monkeypatch.setattr(WatchlistLoader, "validate_and_parse", counting)
        second = loader.find_invalid_watchlist_files()
        assert second == first
        assert calls["n"] == 0

    def test_fixing_the_file_clears_the_finding(self, loader):
        bad = loader.user_watchlist_dir / "broken.yaml"
        bad.write_text("pathogens: 1")
        assert loader.find_invalid_watchlist_files()
        time.sleep(0.01)
        bad.write_text(VALID_YAML.format(n=7, taxid=1007))
        assert loader.find_invalid_watchlist_files() == []