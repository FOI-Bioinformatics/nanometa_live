"""An uploaded custom watchlist must actually screen.

``tests/test_watchlist_upload.py`` covers that upload persists a file and that
the file is discovered. What it does not cover is whether the entries in that
file are *active* afterwards -- and they are not.

``_load_custom_yaml_file`` passes the raw YAML dict to
``WatchlistEntry.from_dict``, which reads ``data.get("enabled", False)``. An
operator's YAML has no ``enabled`` key, so every entry lands disabled. The same
method then adds the watchlist id to ``_enabled_watchlists``, so the toggle
renders ON and ``enable_watchlist`` short-circuits on
``if watchlist_id in self._enabled_watchlists: return 0``.

The result is the failure mode this project already guards against three times
over in the verdict banner: the interface says a watchlist is active while
nothing is being screened against it. An operator uploading their own pathogen
list -- the whole point of the feature -- gets ALL CLEAR over an unscreened
sample.

The second test covers the same method's other half: ``_enable_watchlist_locked``
rebuilds ``entry_data`` field by field and omits ``db_taxid``, which
``_load_yaml_watchlists`` does pass. On a flextaxd/GTDB database, where the
operator sets ``db_taxid`` precisely because the NCBI taxid does not appear in
the database, that silently drops the only reliable match.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager


CUSTOM_YAML = """\
version: "2.0"
metadata:
  name: "Operator field list"
pathogens:
  - name: "Francisella tularensis"
    taxid_ncbi: 263
    threat_level: "critical"
    alert_threshold: 5
  - name: "Bacillus anthracis"
    taxid_ncbi: 1392
    threat_level: "critical"
    alert_threshold: 5
"""

# The operator sets db_taxid when the database is a flextaxd/GTDB build whose
# node for this organism is not the NCBI taxid (Bioshield grafts B. anthracis
# in at 4005020 under the GTDB name Bacillus_A anthracis).
DB_TAXID_YAML = """\
version: "2.0"
metadata:
  name: "Grafted database list"
pathogens:
  - name: "Bacillus anthracis"
    taxid_ncbi: 1392
    db_taxid: 4005020
    threat_level: "critical"
    alert_threshold: 5
"""


@pytest.fixture(autouse=True)
def _clear_sandbox_project_dir(monkeypatch):
    # The suite-wide home sandbox (tests/conftest.py) exports
    # NANOMETA_PROJECT_DIR, which outranks the data dir these tests set up
    # themselves. Clear it so the resolution under test is the one asserted.
    monkeypatch.delenv("NANOMETA_PROJECT_DIR", raising=False)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


class TestUploadedWatchlistIsActive:
    def test_uploaded_entries_are_enabled(self, tmp_path):
        """Entries from an uploaded file must be active, not inert."""
        manager = WatchlistManager()
        manager._load_custom_yaml_file(str(_write(tmp_path, "field.yaml", CUSTOM_YAML)))

        active = manager.get_active_entries()
        assert active, (
            "Uploaded watchlist produced no active entries. The file loaded and "
            "the watchlist id was marked enabled, so the UI reports it as ON "
            "while nothing is screened against it."
        )
        assert {e.name for e in active.values()} == {
            "Francisella tularensis",
            "Bacillus anthracis",
        }

    def test_enable_after_upload_is_not_a_noop(self, tmp_path):
        """Toggling an uploaded watchlist on must have an effect.

        ``_load_custom_yaml_file`` already added the id to
        ``_enabled_watchlists``, so ``enable_watchlist`` returns 0 without doing
        anything. The operator's only recourse today is to toggle off (which
        deletes the entries) and back on again.
        """
        manager = WatchlistManager()
        manager._load_custom_yaml_file(str(_write(tmp_path, "field.yaml", CUSTOM_YAML)))

        manager.enable_watchlist("field")

        active = manager.get_active_entries()
        assert active, (
            "Enabling an uploaded watchlist left every entry inactive: the "
            "id was already in _enabled_watchlists so the call short-circuited."
        )


class TestEnablePreservesDbTaxid:
    def test_db_taxid_survives_enable_watchlist(self, tmp_path, monkeypatch):
        """The enable path must not drop the operator's db_taxid.

        On a grafted database the NCBI taxid does not identify the node; the
        db_taxid does. Losing it disables the exact-taxid match and leaves only
        name matching, which is what GTDB renaming breaks.
        """
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
        wl_dir = tmp_path / "watchlists"
        wl_dir.mkdir(parents=True, exist_ok=True)
        _write(wl_dir, "grafted.yaml", DB_TAXID_YAML)

        from nanometa_live.core.watchlist import watchlist_loader as wl_loader
        from nanometa_live.core.watchlist import watchlist_manager as wl_manager

        wl_loader.reset_watchlist_loader()
        # The manager caches its own loader reference, which
        # reset_watchlist_loader() does not clear.
        monkeypatch.setattr(wl_manager, "_watchlist_loader", None, raising=False)

        manager = WatchlistManager()
        added = manager.enable_watchlist("grafted")
        assert added == 1, f"expected the grafted watchlist to load 1 entry, got {added}"

        entry = next(iter(manager.get_active_entries().values()))
        assert entry.db_taxid == 4005020, (
            "db_taxid was dropped by _enable_watchlist_locked: its entry_data "
            "dict omits the key that _load_yaml_watchlists passes, so the "
            "operator's explicit database taxid never reaches the matcher."
        )
