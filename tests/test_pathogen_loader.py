"""
Unit tests for core/config/pathogen_loader.py.

The facade (core/utils/pathogen_database.py) is tested in test_pathogen_database.py;
this file covers the loader's own building blocks directly: the threat-level and
BSL parsers (with their fallbacks), per-entry and whole-file YAML validation,
dict->PathogenEntry conversion, and the PathogenDatabase load path including a
custom user watchlist merged onto the built-in database.
"""

import pytest
import yaml

from nanometa_live.core.config.pathogen_loader import (
    BiosaftyLevel,
    PathogenDatabase,
    PathogenEntry,
    ThreatLevel,
    _dict_to_pathogen_entry,
    _parse_bsl_level,
    _parse_threat_level,
    _validate_pathogen_entry,
    load_builtin_pathogens,
    validate_watchlist_yaml,
)


class TestParseThreatLevel:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("critical", ThreatLevel.CRITICAL),
            ("HIGH", ThreatLevel.HIGH),
            ("high_risk", ThreatLevel.HIGH),
            ("medium", ThreatLevel.MODERATE),
            ("info", ThreatLevel.LOW),
            ("garbage", ThreatLevel.UNKNOWN),
        ],
    )
    def test_mapping(self, raw, expected):
        assert _parse_threat_level(raw) == expected


class TestParseBslLevel:
    def test_int_and_str(self):
        assert _parse_bsl_level(3) == BiosaftyLevel.BSL3
        assert _parse_bsl_level("2") == BiosaftyLevel.BSL2

    def test_none_and_invalid(self):
        assert _parse_bsl_level(None) is None
        assert _parse_bsl_level(9) is None
        assert _parse_bsl_level("x") is None


class TestValidatePathogenEntry:
    def test_valid_entry_has_no_errors(self):
        entry = {"taxid": 1392, "name": "Bacillus anthracis", "threat_level": "critical"}
        assert _validate_pathogen_entry(entry, 0) == []

    def test_missing_taxid_and_name(self):
        errors = _validate_pathogen_entry({}, 0)
        assert any("taxid" in e for e in errors)
        assert any("name" in e for e in errors)

    def test_non_integer_taxid(self):
        errors = _validate_pathogen_entry({"taxid": "abc", "name": "X"}, 0)
        assert any("integer" in e for e in errors)

    def test_bad_threat_level_and_bsl(self):
        errors = _validate_pathogen_entry(
            {"taxid": 1, "name": "X", "threat_level": "nope", "bsl_level": 9}, 0
        )
        assert any("threat_level" in e for e in errors)
        assert any("bsl_level" in e for e in errors)

    def test_negative_alert_threshold(self):
        errors = _validate_pathogen_entry(
            {"taxid": 1, "name": "X", "alert_threshold": -5}, 0
        )
        assert any("non-negative" in e for e in errors)


class TestDictToPathogenEntry:
    def test_full_conversion(self):
        entry = _dict_to_pathogen_entry({
            "taxid": "1392",
            "name": "Bacillus anthracis",
            "threat_level": "critical",
            "bsl_level": 4,
            "alert_threshold": "25",
        })
        assert entry.taxid == 1392
        assert entry.threat_level == ThreatLevel.CRITICAL
        assert entry.bsl == BiosaftyLevel.BSL4
        assert entry.alert_threshold == 25

    def test_defaults_applied(self):
        entry = _dict_to_pathogen_entry({"taxid": 1, "name": "X"})
        assert entry.threat_level == ThreatLevel.MODERATE  # default
        assert entry.alert_threshold == 10

    def test_to_dict_round_trips_enum_values(self):
        entry = PathogenEntry(taxid=1, name="X", threat_level=ThreatLevel.HIGH, bsl=BiosaftyLevel.BSL3)
        d = entry.to_dict()
        assert d["threat_level"] == "high"
        assert d["bsl_level"] == 3


class TestValidateWatchlistYaml:
    def _write(self, tmp_path, data):
        p = tmp_path / "wl.yaml"
        p.write_text(yaml.safe_dump(data))
        return p

    def test_valid_file(self, tmp_path):
        p = self._write(tmp_path, {
            "pathogens": {
                "critical": [{"taxid": 1392, "name": "Bacillus anthracis", "threat_level": "critical"}]
            }
        })
        ok, errors = validate_watchlist_yaml(p)
        assert ok is True
        assert errors == []

    def test_invalid_entry_reports_errors(self, tmp_path):
        p = self._write(tmp_path, {
            "pathogens": {"critical": [{"name": "no taxid here"}]}
        })
        ok, errors = validate_watchlist_yaml(p)
        assert ok is False
        assert errors

    def test_missing_file(self, tmp_path):
        ok, errors = validate_watchlist_yaml(tmp_path / "nope.yaml")
        assert ok is False
        assert "not found" in errors[0]

    def test_non_dict_root(self, tmp_path):
        p = tmp_path / "wl.yaml"
        p.write_text(yaml.safe_dump(["just", "a", "list"]))
        ok, errors = validate_watchlist_yaml(p)
        assert ok is False


class TestPathogenDatabase:
    def test_builtin_loads(self):
        db = PathogenDatabase()
        assert db.load() is True
        assert db.is_loaded() is True
        assert db.get_all_pathogens()
        assert db.get_load_errors() == []

    def test_custom_watchlist_merged(self):
        custom = [{
            "taxid": 99901,
            "name": "Testus pathogenus",
            "threat_level": "critical",
            "bsl_level": 4,
            "alert_threshold": 5,
        }]
        db = PathogenDatabase(user_watchlist=custom)
        db.load()
        entry = db.get_pathogen_by_taxid(99901)
        assert entry is not None
        assert entry.name == "Testus pathogenus"

    def test_get_critical_pathogens_all_critical(self):
        db = PathogenDatabase()
        db.load()
        assert all(p.threat_level == ThreatLevel.CRITICAL for p in db.get_critical_pathogens())


class TestLoadBuiltinPathogens:
    def test_returns_int_keyed_dict(self):
        pathogens = load_builtin_pathogens()
        assert pathogens
        assert all(isinstance(k, int) for k in pathogens)
