"""
Unit tests for core/config/config_manager.py.

ConfigManager is the stateful wrapper over ConfigLoader + validate_config. Tests
run against a real tmp_path data_dir (never the operator's home) and focus on the
manager's own contracts: the no-config guards, the boolean coercion in
update_config, reset-to-defaults, and a save -> reload round-trip.
"""

import pytest

from nanometa_live.core.config.config_manager import ConfigManager


@pytest.fixture
def manager(tmp_path):
    return ConfigManager(str(tmp_path))


class TestInit:
    def test_config_dir_is_under_data_dir(self, tmp_path):
        mgr = ConfigManager(str(tmp_path))
        assert mgr.config_dir == str(tmp_path / "configs")
        assert mgr.current_config is None


class TestGuards:
    def test_get_config_without_load_raises(self, manager):
        with pytest.raises(ValueError):
            manager.get_config()

    def test_update_without_load_raises(self, manager):
        with pytest.raises(ValueError):
            manager.update_config({"x": 1})

    def test_save_without_config_raises(self, manager):
        with pytest.raises(ValueError):
            manager.save_config()


class TestResetToDefaults:
    def test_returns_dict_and_sets_current(self, manager):
        cfg = manager.reset_to_defaults()
        assert isinstance(cfg, dict)
        assert cfg
        assert manager.get_config() is cfg
        assert manager.config_path is None


class TestUpdateConfigBooleanCoercion:
    @pytest.mark.parametrize(
        "raw,expected",
        [("yes", True), ("true", True), ("1", True), ("no", False), ("false", False)],
    )
    def test_blast_validation_string_coerced_to_bool(self, manager, raw, expected):
        manager.reset_to_defaults()
        result = manager.update_config({"blast_validation": raw})
        assert result["blast_validation"] is expected

    def test_memory_mapping_flag_form(self, manager):
        manager.reset_to_defaults()
        result = manager.update_config({"kraken_memory_mapping": "--memory-mapping"})
        assert result["kraken_memory_mapping"] is True


class TestSaveAndReload:
    def test_save_creates_file_and_lists_it(self, manager):
        manager.reset_to_defaults()
        path = manager.save_config("roundtrip.yaml")
        import os

        assert os.path.exists(path)
        listed = {c["path"] for c in manager.get_available_configs()}
        assert path in listed

    def test_round_trip_preserves_boolean(self, tmp_path):
        writer = ConfigManager(str(tmp_path))
        writer.reset_to_defaults()
        writer.update_config({"blast_validation": "yes"})
        path = writer.save_config("rt.yaml")

        reader = ConfigManager(str(tmp_path))
        loaded = reader.load_config(path)
        assert loaded["blast_validation"] is True
