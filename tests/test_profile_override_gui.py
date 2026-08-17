"""GUI writer for the database-profile override (G6, closed 2026-08-17).

The override file ({db_hash}_profile_override.json) always had core
save/clear helpers but no GUI writer -- operators had to hand-edit JSON.
These tests cover the Preparation-tab editor: the save/clear callback, the
live-singleton refresh that makes ``check_organisms`` see the new profile
without a restart, the control seeding, and the shared db_info builder that
keeps the store's three writers in lock-step (G7).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from dash import Dash

from nanometa_live.core.taxonomy.database_profile import (
    DatabaseProfile,
    Nomenclature,
    load_detected_profile,
    override_path,
)
from nanometa_live.core.taxonomy.taxid_mapping import (
    TaxidMappingCollection,
    get_database_hash,
    get_mapping_collection,
    set_mapping_collection,
)
from tests.dash_test_utils import get_callback_fn

pytestmark = pytest.mark.unit


@pytest.fixture
def prep_app():
    from nanometa_live.app.tabs.preparation_tab import (
        register_preparation_callbacks,
    )
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_preparation_callbacks(app)
    return app


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    """A dummy database dir + isolated mappings dir, with the collection
    singleton holding a GTDB-detected profile."""
    db_dir = tmp_path / "kraken_db"
    db_dir.mkdir()
    (db_dir / "hash.k2d").write_bytes(b"\x00" * 64)
    mappings_dir = tmp_path / "mappings"
    mappings_dir.mkdir()
    monkeypatch.setattr(
        "nanometa_live.core.utils.paths.get_mappings_dir_from_env",
        lambda: str(mappings_dir),
    )

    db_hash = get_database_hash(str(db_dir))
    assert db_hash

    detected = DatabaseProfile(
        taxids_are_ncbi=False,
        nomenclature=Nomenclature.GTDB,
        detected_by="rank prefixes",
    )
    (mappings_dir / f"{db_hash}_index.json").write_text(
        json.dumps({"profile": detected.to_dict()}))

    collection = TaxidMappingCollection(
        database_path=str(db_dir), database_hash=db_hash)
    collection.profile = detected
    set_mapping_collection(collection)

    return {"db_dir": str(db_dir), "db_hash": db_hash,
            "mappings_dir": mappings_dir}


def _ctx(module, triggered_id):
    return patch.object(
        module, "ctx", type("C", (), {"triggered_id": triggered_id})())


class TestOverrideCallback:
    def _fn(self, app):
        return get_callback_fn(app, "taxmap-override-status")

    def test_save_writes_file_and_flips_live_profile(self, prep_app, db_env):
        import nanometa_live.app.tabs.preparation_tab as pt
        config = {"kraken_db": db_env["db_dir"]}
        with _ctx(pt, "taxmap-override-save"):
            status, db_info = self._fn(prep_app)(
                1, 0, "true", "ncbi", config, {"stats": {"total_entries": 3}})

        assert override_path(db_env["db_hash"], db_env["mappings_dir"]).exists()
        # check_organisms reads THIS: the collection singleton's profile.
        live = get_mapping_collection().profile
        assert live.taxids_are_ncbi is True
        assert live.nomenclature == Nomenclature.NCBI
        assert live.overridden is True
        assert "Override applied" in status
        assert db_info["overridden"] is True
        assert db_info["taxids_are_ncbi"] is True
        # Stats from the prior store value are preserved, not blanked.
        assert db_info["stats"] == {"total_entries": 3}

    def test_clear_returns_to_detection(self, prep_app, db_env):
        import nanometa_live.app.tabs.preparation_tab as pt
        config = {"kraken_db": db_env["db_dir"]}
        with _ctx(pt, "taxmap-override-save"):
            self._fn(prep_app)(1, 0, "true", "ncbi", config, None)
        with _ctx(pt, "taxmap-override-clear"):
            status, db_info = self._fn(prep_app)(
                1, 1, "true", "ncbi", config, None)

        assert not override_path(
            db_env["db_hash"], db_env["mappings_dir"]).exists()
        live = get_mapping_collection().profile
        assert live.taxids_are_ncbi is False
        assert live.nomenclature == Nomenclature.GTDB
        assert live.overridden is False
        assert "detection says" in status
        assert db_info["overridden"] is False

    def test_save_persists_onto_mappings_cache(self, prep_app, db_env):
        # Background workers load {db_hash}_mappings.json standalone; the
        # profile copy on it must agree with the override.
        import nanometa_live.app.tabs.preparation_tab as pt
        config = {"kraken_db": db_env["db_dir"]}
        with _ctx(pt, "taxmap-override-save"):
            self._fn(prep_app)(1, 0, "true", "ncbi", config, None)
        cache = db_env["mappings_dir"] / f"{db_env['db_hash']}_mappings.json"
        assert cache.exists()
        data = json.loads(cache.read_text())
        assert data["profile"]["taxids_are_ncbi"] is True

    def test_no_database_path_is_a_clear_message(self, prep_app, db_env):
        import nanometa_live.app.tabs.preparation_tab as pt
        with _ctx(pt, "taxmap-override-save"):
            status, db_info = self._fn(prep_app)(1, 0, "true", "ncbi", {}, None)
        assert "Kraken2 database path" in status

    def test_evidence_not_nested_on_repeated_saves(self, prep_app, db_env):
        # The base for apply_override must be the DETECTED profile from disk,
        # not the (already overridden) singleton -- otherwise every save
        # nests "operator override (detector said: operator override ...)".
        import nanometa_live.app.tabs.preparation_tab as pt
        config = {"kraken_db": db_env["db_dir"]}
        for _ in range(3):
            with _ctx(pt, "taxmap-override-save"):
                self._fn(prep_app)(1, 0, "true", "ncbi", config, None)
        detected_by = get_mapping_collection().profile.detected_by
        assert detected_by.count("operator override") == 1


class TestSeedControls:
    def test_seeds_from_db_info(self, prep_app):
        fn = get_callback_fn(prep_app, "taxmap-override-taxids")
        taxids, nomenclature = fn(
            {"taxids_are_ncbi": True, "nomenclature": "gtdb"})
        assert taxids == "true"
        assert nomenclature == "gtdb"


class TestDbInfoBuilder:
    def test_key_set_is_stable(self):
        from nanometa_live.app.utils.db_info import build_db_info
        info = build_db_info(DatabaseProfile(), db_hash="h", path="p")
        assert set(info) == {"path", "type", "detected_by", "overridden",
                             "taxids_are_ncbi", "nomenclature", "hash"}

    def test_optional_sections_carry_through(self):
        from nanometa_live.app.utils.db_info import build_db_info
        info = build_db_info(
            None, stats={"a": 1}, coverage={"summary": "s"})
        assert info["stats"] == {"a": 1}
        assert info["coverage"] == {"summary": "s"}
        assert info["type"] == "unknown"


class TestLoadDetectedProfile:
    def test_ignores_override(self, db_env):
        from nanometa_live.core.taxonomy.database_profile import save_override
        save_override(db_env["db_hash"], db_env["mappings_dir"],
                      DatabaseProfile(taxids_are_ncbi=True,
                                      nomenclature=Nomenclature.NCBI))
        detected = load_detected_profile(db_env["db_dir"])
        assert detected.taxids_are_ncbi is False
        assert detected.nomenclature == Nomenclature.GTDB
        assert detected.overridden is False
