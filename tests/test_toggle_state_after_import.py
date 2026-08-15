"""An imported bundle's watchlist selection must survive on the field machine.

Toggle state is which watchlist entries the operator has switched off. It is
written project-scoped, but ``import_bundle`` can only write it to the data
dir -- a bundle is machine-portable and cannot know the field machine's
project directory.

The GUI always sets a project dir (to the working directory), so the
project-scoped path shadowed the imported file, ``_restore_toggle_state``
found nothing, and every entry the operator had deliberately disabled came
back **enabled** on the field machine with no indication anything was lost.

That direction matters for triage: the failure adds alerts rather than
removing them, so it is noisy rather than silent -- but an operator who
switched an organism off had a reason, and a field deployment is the worst
place to rediscover it.
"""

from __future__ import annotations

import pathlib

import pytest

from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager

pytestmark = pytest.mark.unit

WATCHLIST = (
    "metadata:\n  name: Field list\npathogens:\n"
    "  - name: Bacillus anthracis\n    taxid_ncbi: 1392\n    alert_threshold: 5\n"
    "  - name: Yersinia pestis\n    taxid_ncbi: 632\n    alert_threshold: 5\n"
)


@pytest.fixture
def field_machine(tmp_path, monkeypatch):
    """A freshly imported home: watchlists plus a data-dir toggle file."""
    home = tmp_path / "fieldlaptop"
    (home / "watchlists").mkdir(parents=True)
    (home / "watchlists" / "field.yaml").write_text(WATCHLIST)
    # What import_bundle writes.
    (home / "watchlist_toggle_state.yaml").write_text("disabled_taxids:\n  - 632\n")
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(home))
    return home


def _config(home, project_dir=None):
    cfg = {
        "watchlist": {"enabled": True, "builtin": ["field"], "custom": []},
        "data_dir": str(home),
    }
    if project_dir is not None:
        cfg["project_dir"] = str(project_dir)
    return cfg


def _active(config):
    manager = WatchlistManager()
    manager.load_config(config)
    return sorted(manager.get_active_entries())


class TestImportedSelectionSurvives:
    def test_project_dir_does_not_shadow_the_imported_state(
        self, tmp_path, field_machine
    ):
        """The regression. The GUI always sets a project dir."""
        project = tmp_path / "project"
        project.mkdir()
        active = _active(_config(field_machine, project))
        assert 632 not in active, (
            "the operator's disabled entry came back enabled after import"
        )
        assert 1392 in active

    def test_still_works_without_a_project_dir(self, tmp_path, field_machine):
        """The CLI path, which never had the bug."""
        active = _active(_config(field_machine))
        assert 632 not in active
        assert 1392 in active


class TestProjectStateWins:
    def test_a_project_with_its_own_selection_is_not_overridden(
        self, tmp_path, field_machine
    ):
        """The fallback seeds a fresh project; it must not override a set one.

        Otherwise an operator's per-analysis choices would be silently
        reverted to whatever the bundle shipped every time it reloaded.
        """
        project = tmp_path / "project"
        (project / ".nanometa").mkdir(parents=True)
        (project / ".nanometa" / "watchlist_toggle_state.yaml").write_text(
            "disabled_taxids:\n  - 1392\n"
        )
        active = _active(_config(field_machine, project))
        assert 1392 not in active, "project-scoped selection was ignored"
        assert 632 in active, "data-dir state leaked past the project's own"

    def test_saving_writes_the_project_scoped_path(self, tmp_path, field_machine):
        """Writes stay project-scoped; only reads fall back."""
        project = tmp_path / "project"
        project.mkdir()
        manager = WatchlistManager()
        manager.load_config(_config(field_machine, project))
        manager._entries[1392].enabled = False
        manager._save_toggle_state()

        written = project / ".nanometa" / "watchlist_toggle_state.yaml"
        assert written.exists(), f"expected a write to {written}"
        assert "1392" in written.read_text()


class TestNoState:
    def test_absent_everywhere_leaves_everything_enabled(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / "watchlists").mkdir(parents=True)
        (home / "watchlists" / "field.yaml").write_text(WATCHLIST)
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(home))
        assert sorted(_active(_config(home))) == [632, 1392]
