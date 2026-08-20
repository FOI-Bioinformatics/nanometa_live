"""The project watchlist tier must follow the project dir, not the results dir.

`WatchlistLoader`'s own docstring, and the architecture notes, both say the
highest-priority watchlist source is ``<project_dir>/watchlists/``. The manager
was instead handing the loader ``results_output_directory`` (falling back to
``main_dir``), so the two notions of "project" inside one class disagreed:
toggle state resolved under ``project_dir`` while watchlist discovery searched
the results directory.

That was survivable while the project dir defaulted to the working directory
and results were written beneath it. Once the project dir became
``~/nanometa-projects/<name>`` and results moved to
``<project>/results/<slug>``, the two stopped overlapping and a watchlist
placed where the docs say it goes was never found.

The results directory is still searched, because `import_watchlist` with
``destination="project"`` has been writing operator uploads there; dropping it
would strand watchlists that are already on disk.
"""

import pytest

from nanometa_live.core.watchlist.watchlist_loader import WatchlistLoader
from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager


MINIMAL_WATCHLIST = """
version: "2.0"
metadata:
  name: "{name}"
  description: "fixture"
pathogens:
  - name: "Francisella tularensis holarctica"
    db_taxid: 4007187
    taxid_ncbi: 119857
    threat_level: "critical"
    alert_threshold: 25
"""


def _write_watchlist(directory, stem, name):
    wl_dir = directory / "watchlists"
    wl_dir.mkdir(parents=True, exist_ok=True)
    (wl_dir / f"{stem}.yaml").write_text(MINIMAL_WATCHLIST.format(name=name))
    return wl_dir


class TestLoaderSearchPaths:
    def test_project_dir_is_searched(self, tmp_path):
        project = tmp_path / "project"
        _write_watchlist(project, "in_project", "In Project")
        loader = WatchlistLoader(project_dir=project)

        found = {w.id for w in loader.discover_watchlists()}

        assert "in_project" in found

    def test_additional_dirs_are_searched_after_the_project_dir(self, tmp_path):
        project = tmp_path / "project"
        results = tmp_path / "project" / "results" / "run"
        _write_watchlist(project, "in_project", "In Project")
        _write_watchlist(results, "in_results", "In Results")

        loader = WatchlistLoader(project_dir=project)
        loader.set_project_dir(project, additional_dirs=[results])
        found = {w.id for w in loader.discover_watchlists()}

        assert {"in_project", "in_results"} <= found

    def test_project_dir_wins_on_stem_collision(self, tmp_path):
        project = tmp_path / "project"
        results = tmp_path / "results"
        _write_watchlist(project, "shared", "From Project")
        _write_watchlist(results, "shared", "From Results")

        loader = WatchlistLoader(project_dir=project)
        loader.set_project_dir(project, additional_dirs=[results])
        found = {w.id: w for w in loader.discover_watchlists()}

        assert found["shared"].name == "From Project"

    def test_additional_dirs_reset_when_omitted(self, tmp_path):
        project = tmp_path / "project"
        results = tmp_path / "results"
        _write_watchlist(project, "in_project", "In Project")
        _write_watchlist(results, "in_results", "In Results")

        loader = WatchlistLoader(project_dir=project)
        loader.set_project_dir(project, additional_dirs=[results])
        loader.set_project_dir(project)
        found = {w.id for w in loader.discover_watchlists()}

        assert "in_results" not in found

    def test_a_nonexistent_additional_dir_is_skipped(self, tmp_path):
        project = tmp_path / "project"
        _write_watchlist(project, "in_project", "In Project")

        loader = WatchlistLoader(project_dir=project)
        loader.set_project_dir(project, additional_dirs=[tmp_path / "gone"])

        assert "in_project" in {w.id for w in loader.discover_watchlists()}


class TestManagerWiring:
    """The manager is what actually chooses the directories."""

    @pytest.fixture(autouse=True)
    def _reset_loader(self):
        from nanometa_live.core.watchlist import watchlist_loader

        watchlist_loader.reset_watchlist_loader()
        yield
        watchlist_loader.reset_watchlist_loader()

    def test_project_dir_config_key_finds_the_watchlist(self, tmp_path):
        project = tmp_path / "project"
        _write_watchlist(project, "subsp", "Subspecies")

        manager = WatchlistManager()
        manager.load_config({"project_dir": str(project)})

        assert manager.enable_watchlist("subsp") == 1

    def test_results_dir_is_still_searched(self, tmp_path):
        """Uploads saved to "project" have been landing here; do not strand them."""
        project = tmp_path / "project"
        results = project / "results" / "run"
        _write_watchlist(results, "legacy", "Legacy Upload")

        manager = WatchlistManager()
        manager.load_config({
            "project_dir": str(project),
            "results_output_directory": str(results),
        })

        assert manager.enable_watchlist("legacy") == 1

    def test_both_tiers_load_together(self, tmp_path):
        project = tmp_path / "project"
        results = project / "results" / "run"
        _write_watchlist(project, "subsp", "Subspecies")
        _write_watchlist(results, "legacy", "Legacy Upload")

        manager = WatchlistManager()
        manager.load_config({
            "project_dir": str(project),
            "results_output_directory": str(results),
        })

        available = {w["id"] for w in manager.get_available_watchlists()}
        assert {"subsp", "legacy"} <= available

    def test_main_dir_still_works_without_a_project_dir(self, tmp_path):
        main = tmp_path / "viz"
        _write_watchlist(main, "viz_only", "Visualization Only")

        manager = WatchlistManager()
        manager.load_config({"main_dir": str(main)})

        assert manager.enable_watchlist("viz_only") == 1
