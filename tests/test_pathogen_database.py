"""
Unit tests for core/utils/pathogen_database.py.

This is the backward-compatible facade over the YAML-backed pathogen loader.
Tests derive their fixtures from the loaded built-in database (rather than
hardcoding specific taxids) so they assert real behaviour without coupling to
the exact pathogen list, and cover the alert-merging logic in
check_for_dangerous_pathogens including the watchlist enable/disable rules.
"""

import pytest

from nanometa_live.core.utils import pathogen_database as pdb
from nanometa_live.core.utils.pathogen_database import (
    ThreatLevel,
    check_for_dangerous_pathogens,
    export_watchlist_template,
    get_all_dangerous_pathogens,
    get_critical_pathogens,
    get_pathogen_by_name,
    get_pathogen_by_taxid,
    reload_database,
)


@pytest.fixture(scope="module")
def all_pathogens():
    db = get_all_dangerous_pathogens()
    assert db, "built-in pathogen database failed to load"
    return db


@pytest.fixture(scope="module")
def sample_entry(all_pathogens):
    # An entry with a positive alert threshold so the < / >= boundary is testable.
    for entry in all_pathogens.values():
        if entry.alert_threshold and entry.alert_threshold > 0:
            return entry
    return next(iter(all_pathogens.values()))


class TestDatabaseLoad:
    def test_keys_are_int_taxids(self, all_pathogens):
        assert all(isinstance(k, int) for k in all_pathogens)

    def test_critical_pathogens_are_all_critical(self):
        for p in get_critical_pathogens():
            assert p.threat_level == ThreatLevel.CRITICAL


class TestLookups:
    def test_get_by_taxid(self, sample_entry):
        found = get_pathogen_by_taxid(sample_entry.taxid)
        assert found is not None
        assert found.taxid == sample_entry.taxid

    def test_get_by_taxid_missing(self):
        assert get_pathogen_by_taxid(-12345) is None

    def test_get_by_name_partial_match(self, sample_entry):
        # Names are matched case-insensitively as a partial; the genus alone
        # must resolve to some entry.
        genus = sample_entry.name.split()[0]
        assert get_pathogen_by_name(genus) is not None


class TestCheckForDangerousPathogens:
    def test_empty_input_no_alerts(self):
        assert check_for_dangerous_pathogens([]) == []

    def test_alert_when_reads_at_threshold(self, sample_entry):
        detected = [{
            "taxid": sample_entry.taxid,
            "name": sample_entry.name,
            "reads": sample_entry.alert_threshold,
        }]
        alerts = check_for_dangerous_pathogens(detected)
        assert len(alerts) == 1
        assert alerts[0]["taxid"] == sample_entry.taxid
        assert alerts[0]["source"] == "database"

    def test_no_alert_below_threshold(self, sample_entry):
        if sample_entry.alert_threshold <= 0:
            pytest.skip("entry has no positive threshold to test the boundary")
        detected = [{
            "taxid": sample_entry.taxid,
            "name": sample_entry.name,
            "reads": sample_entry.alert_threshold - 1,
        }]
        assert check_for_dangerous_pathogens(detected) == []

    def test_disabled_custom_entry_suppresses_alert(self, sample_entry):
        # A custom watchlist that explicitly disables a known pathogen must
        # suppress its alert even when reads are high.
        detected = [{
            "taxid": sample_entry.taxid,
            "name": sample_entry.name,
            "reads": 10_000,
        }]
        custom = [{"taxid": sample_entry.taxid, "name": sample_entry.name, "enabled": False}]
        assert check_for_dangerous_pathogens(detected, custom_watchlist=custom) == []

    def test_empty_watchlist_means_no_builtin_alerts(self, sample_entry):
        # An empty (not None) watchlist means "alert only on what I listed",
        # so a built-in pathogen not in the list is not alerted.
        detected = [{
            "taxid": sample_entry.taxid,
            "name": sample_entry.name,
            "reads": 10_000,
        }]
        assert check_for_dangerous_pathogens(detected, custom_watchlist=[]) == []


class TestTemplateAndReload:
    def test_export_template_shape(self):
        template = export_watchlist_template()
        assert len(template) <= 5
        for entry in template:
            assert {"taxid", "name", "threat_level", "alert_threshold"} <= set(entry)

    def test_reload_returns_true(self):
        assert reload_database() is True
        assert pdb._database is not None
