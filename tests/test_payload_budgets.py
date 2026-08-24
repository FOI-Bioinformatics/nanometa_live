"""Wire-payload budgets: the app-config Store carries a SLIM watchlist.

Measured in the round-2 audit (2026-08-22): config["watchlist"] was 96-99%
of the app-config Store — 189 kB at 129 validated entries, 721 kB at 500 —
and rode 24 per-tick callbacks as State (4.4-16.9 MB of browser upload per
tick) plus a 17-callback fan-out on every toggle (~3.5 MB per click). No
consumer reads the fat fields off the wire; the disk (last-session.yaml)
must keep the FULL form, which is why the writers are split.
"""

import json
from unittest.mock import patch

import pytest
import yaml

from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    reset_watchlist_manager,
)

pytestmark = pytest.mark.unit

SLIM_KEYS = {"taxid", "db_taxid", "enabled", "alert_threshold",
             "threat_level", "name"}

FAT_ENTRY = {
    "taxid": 1392, "name": "Bacillus anthracis", "threat_level": "critical",
    "enabled": True, "alert_threshold": 5, "db_taxid": 4005020,
    "notes": "Select agent." * 20,
    "action_required": "Immediately notify the on-call officer. " * 10,
    "names_alt": ["Bacillus_A anthracis", "Anthrax bacillus"],
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    reset_watchlist_manager()
    yield
    reset_watchlist_manager()


@pytest.fixture
def manager():
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        mgr = WatchlistManager()
        mgr._entries.clear()
        mgr._name_index.clear()
        mgr.add_custom_entry(dict(FAT_ENTRY))
        for i in range(128):
            mgr.add_custom_entry({
                "taxid": 91000 + i, "name": f"Fillerus organismus{i}",
                "threat_level": "high", "enabled": True, "alert_threshold": 10,
                "names_alt": [f"Fillerus_A organismus{i}"],
                "notes": "filler notes " * 5,
            })
        mgr._loaded = True
        yield mgr


class TestSlimExport:
    def test_slim_entries_carry_only_the_whitelisted_keys(self, manager):
        exported = manager.export_config(slim=True)
        assert exported["custom"], "custom entries must still be present"
        for entry in exported["custom"]:
            assert set(entry) <= SLIM_KEYS, set(entry) - SLIM_KEYS

    def test_slim_budget_under_200_bytes_per_entry(self, manager):
        exported = manager.export_config(slim=True)
        payload = json.dumps(exported, separators=(",", ":"))
        per_entry = len(payload) / len(exported["custom"])
        assert per_entry < 200, f"{per_entry:.0f} B/entry"

    def test_default_export_is_unchanged_full_form(self, manager):
        exported = manager.export_config()
        anthrax = next(e for e in exported["custom"] if e["taxid"] == 1392)
        assert "action_required" in anthrax and "notes" in anthrax

    def test_slim_roundtrip_preserves_screening(self, manager):
        """load_config on a slim store block screens identically."""
        slim_config = {"watchlist": manager.export_config(slim=True)}
        detected = [{"taxid": 1392, "name": "Bacillus anthracis",
                     "reads": 100, "abundance": 1.0}]
        expected = manager.check_organisms(detected)

        reset_watchlist_manager()
        with patch.object(WatchlistManager, "_save_toggle_state",
                          lambda self: None):
            fresh = WatchlistManager()
            fresh._entries.clear()
            fresh._name_index.clear()
            fresh.load_config(slim_config)
            got = fresh.check_organisms(detected)
        assert [(a["taxid"], a["reads"], a["threat_level"]) for a in got] == \
               [(a["taxid"], a["reads"], a["threat_level"]) for a in expected]


class TestDiskKeepsTheFullForm:
    def test_save_last_session_writes_fat_fields_from_the_singleton(
            self, manager, tmp_path, monkeypatch):
        """A toggle with a SLIM store config must not strip the persisted
        watchlist block."""
        from nanometa_live.app.tabs import watchlist_tab
        with patch.object(watchlist_tab, "get_watchlist_manager",
                          return_value=manager):
            slim_store_config = {
                "watchlist": manager.export_config(slim=True),
                "data_dir": str(tmp_path),
            }
            watchlist_tab._save_last_session(slim_store_config)

        from nanometa_live.core.utils.paths import NanometaPaths
        from pathlib import Path
        session = (Path(NanometaPaths.from_config(slim_store_config).configs)
                   / "last-session.yaml")
        persisted = yaml.safe_load(session.read_text())
        anthrax = next(e for e in persisted["watchlist"]["custom"]
                       if e["taxid"] == 1392)
        assert "action_required" in anthrax, (
            "last-session.yaml lost the full watchlist form; the disk "
            "writers must pull slim=False from the live singleton"
        )

    def test_empty_singleton_never_overwrites_a_full_persisted_block(
            self, tmp_path, monkeypatch):
        """Fresh-boot edge: writing with an empty manager must keep the
        persisted full block rather than replacing it with slim data."""
        from nanometa_live.app.tabs import watchlist_tab
        from nanometa_live.core.utils.paths import NanometaPaths
        from pathlib import Path

        config = {"data_dir": str(tmp_path)}
        session_dir = Path(NanometaPaths.from_config(config).configs)
        session_dir.mkdir(parents=True, exist_ok=True)
        full_block = {"enabled": True, "builtin": [],
                      "custom": [dict(FAT_ENTRY)], "overrides": []}
        (session_dir / "last-session.yaml").write_text(
            yaml.safe_dump({"watchlist": full_block, "data_dir": str(tmp_path)}))

        empty = WatchlistManager()
        empty._entries.clear()
        with patch.object(watchlist_tab, "get_watchlist_manager",
                          return_value=empty):
            slim_config = {
                "watchlist": {"enabled": True, "builtin": [], "custom": [
                    {k: FAT_ENTRY[k] for k in SLIM_KEYS}], "overrides": []},
                "data_dir": str(tmp_path),
            }
            watchlist_tab._save_last_session(slim_config)

        persisted = yaml.safe_load(
            (session_dir / "last-session.yaml").read_text())
        anthrax = persisted["watchlist"]["custom"][0]
        assert "action_required" in anthrax


class TestTaxmapStoreSlim:
    """The taxmap-collection Store ships only the fields its consumers
    read (confidence, db_taxid, match_score, db_name, match_method) —
    14 fields incl. alternative_matches and audit timestamps were crossing
    the wire (~111 kB at 129 entries) and re-uploaded per table page turn."""

    STORE_FIELDS = {"ncbi_taxid", "confidence", "db_taxid", "match_score",
                    "db_name", "match_method"}

    def _collection_dict(self):
        return {
            "mappings": [
                {"ncbi_taxid": 1392, "confidence": "exact", "db_taxid": 4005020,
                 "match_score": 1.0, "db_name": "Bacillus_A anthracis",
                 "match_method": "exact_taxid", "canonical_name": "…",
                 "created_at": "2026-01-01", "updated_at": "2026-01-01",
                 "manually_verified": False, "verified_by": None,
                 "verified_at": None, "override_reason": None,
                 "alternative_matches": [{"db_taxid": 1, "score": 0.5}] * 5},
            ],
            "statistics": {"total": 1},
        }

    def test_slim_payload_keeps_only_read_fields(self):
        from nanometa_live.core.taxonomy.taxid_mapping import (
            slim_mapping_store_payload,
        )
        payload = slim_mapping_store_payload(self._collection_dict())
        mapping = payload["mappings"]["1392"]
        assert set(mapping) <= self.STORE_FIELDS, (
            set(mapping) - self.STORE_FIELDS
        )
        assert payload["statistics"] == {"total": 1}

    def test_table_renders_identically_from_slim_data(self, manager):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.tabs import watchlist_tab
        from nanometa_live.app.tabs.watchlist_tab import (
            register_watchlist_callbacks,
        )
        from nanometa_live.core.taxonomy.taxid_mapping import (
            slim_mapping_store_payload,
        )
        full = {
            "mappings": {
                str(m["ncbi_taxid"]): m
                for m in self._collection_dict()["mappings"]
            },
            "statistics": {"total": 1},
        }
        slim = slim_mapping_store_payload(self._collection_dict())
        app = make_callback_app(register_watchlist_callbacks)
        fn = get_callback_fn(app, "watchlist-pathogens-table")

        def render(store):
            with patch.object(watchlist_tab, "get_watchlist_manager",
                              return_value=manager), \
                 patch.object(watchlist_tab, "ctx") as mock_ctx:
                mock_ctx.triggered_id = "watchlist-table-refresh"
                return str(fn({"last_update": "x"}, 1, "", None, store, 1, {}))

        assert render(full) == render(slim)


class TestStoreWritersAreSlim:
    def test_nested_toggle_writes_a_slim_store_config(self, manager):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.tabs import watchlist_tab
        from nanometa_live.app.tabs.watchlist_tab import (
            register_watchlist_callbacks,
        )
        app = make_callback_app(register_watchlist_callbacks)
        fn = get_callback_fn(
            app, "watchlist-tab-state",
            input_contains="watchlist-nested-pathogen-toggle")
        trig = {"type": "watchlist-nested-pathogen-toggle",
                "index": 1392, "watchlist": "x"}
        with patch.object(watchlist_tab, "get_watchlist_manager",
                          return_value=manager), \
             patch.object(watchlist_tab, "_save_last_session",
                          lambda cfg: None), \
             patch.object(watchlist_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = trig
            _state, updated_config = fn([False], [trig], {})
        for entry in updated_config["watchlist"]["custom"]:
            assert set(entry) <= SLIM_KEYS

class TestValidationStoreEntrySlim:
    """Store-bound validation entries ship without empty fields (round 3).

    At the pairs envelope the store carried ~25k dicts x 24 fields; the
    None/empty third of every dict was pure wire cost. Zeros stay: 0.0
    is a measurement."""

    def test_empty_fields_dropped_zeros_kept(self):
        from nanometa_live.app.tabs.validation_tab_helpers import (
            _slim_result_dict,
        )
        slim = _slim_result_dict({
            "sample_id": "bc01", "taxid": 5, "errors": [],
            "reference_accession": None, "species": "",
            "hit_rate": 0.0, "validated_reads": 0,
        })
        assert slim == {"sample_id": "bc01", "taxid": 5,
                        "hit_rate": 0.0, "validated_reads": 0}
