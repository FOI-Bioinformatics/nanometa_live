"""Taxid coordination between the Kraken2 database and the watchlist.

2026-08-17 reaudit, findings G1-G9: an operator-declared ``db_taxid`` was
honored by live detection but invisible to the mapping collection, the
snapshot, the preparer and every status UI; Scan Database destroyed
operator verification; the Alerts-panel path compared NCBI taxids raw
against any database; readiness called stale mappings green.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.taxonomy.database_profile import DatabaseProfile
from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
    MappingConfidence,
    TaxidMapper,
)


def _index_with(nodes):
    index = DatabaseTaxonomyIndex(
        database_path="/db",
        profile=DatabaseProfile(taxids_are_ncbi=False),
    )
    for node in nodes:
        index.by_taxid[node.taxid] = node
        index.by_name.setdefault(node.name.lower(), []).append(node.taxid)
    return index


def _mapper(index):
    mapper = TaxidMapper()
    mapper._index = index
    mapper._database_path = "/db"
    return mapper


GRAFTED = DatabaseTaxonomyNode(
    taxid=4005020, name="Bacillus_A anthracis", rank="S"
)


class TestOperatorDbTaxidEntersTheCollection:
    """G1: the declaration IS the mapping."""

    def test_declared_node_becomes_manual_mapping(self):
        mapper = _mapper(_index_with([GRAFTED]))
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="HASH_A",
        ):
            collection = mapper.generate_mappings([
                {"name": "Bacillus anthracis", "taxid": 1392,
                 "db_taxid": 4005020},
            ])
        mapping = collection.mappings[1392]
        assert mapping.db_taxid == 4005020
        assert mapping.confidence == MappingConfidence.MANUAL
        assert mapping.manually_verified
        assert mapping.match_method == "operator_db_taxid"
        assert mapping.db_name == "Bacillus_A anthracis"

    def test_declared_node_absent_is_recorded_not_trusted(self):
        mapper = _mapper(_index_with([GRAFTED]))
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="HASH_A",
        ):
            collection = mapper.generate_mappings([
                {"name": "Yersinia pestis", "taxid": 632,
                 "db_taxid": 9999999},
            ])
        mapping = collection.mappings[632]
        assert mapping.db_taxid is None
        assert mapping.confidence == MappingConfidence.UNMAPPED
        assert mapping.match_method == "operator_db_taxid_absent"


class TestScanPreservesOperatorWork:
    """G8: rescans of the same database keep verified mappings."""

    def test_manual_mapping_survives_rescan_of_same_db(self):
        mapper = _mapper(_index_with([GRAFTED]))
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="HASH_A",
        ):
            first = mapper.generate_mappings([
                {"name": "Bacillus anthracis", "taxid": 1392,
                 "db_taxid": 4005020},
            ])
            assert first.mappings[1392].manually_verified
            # Rescan WITHOUT the declaration (e.g. snapshot regressed):
            # preserve_manual must keep the verified mapping.
            second = mapper.generate_mappings(
                [{"name": "Bacillus anthracis", "taxid": 1392}],
                preserve_manual=True,
            )
        assert second.mappings[1392].db_taxid == 4005020
        assert second.mappings[1392].manually_verified

    def test_different_database_hash_rebuilds(self):
        mapper = _mapper(_index_with([GRAFTED]))
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="HASH_A",
        ):
            mapper.generate_mappings([
                {"name": "Bacillus anthracis", "taxid": 1392,
                 "db_taxid": 4005020},
            ])
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping.get_database_hash",
            return_value="HASH_B",
        ):
            rebuilt = mapper.generate_mappings(
                [{"name": "Bacillus anthracis", "taxid": 1392}],
                preserve_manual=True,
            )
        assert rebuilt.database_hash == "HASH_B"
        assert not rebuilt.mappings[1392].manually_verified


class TestSnapshotAndPreparerCarryDbTaxid:
    """G2: every consumer downstream of the snapshot must see db_taxid."""

    def test_preparer_injected_entries_honor_db_taxid(self):
        from nanometa_live.core.workflow.mobile_lab_preparer import (
            MobileLabPreparer,
        )

        preparer = MobileLabPreparer(config={})
        preparer._injected_entries = [
            {"name": "Bacillus anthracis", "taxid": 1392,
             "db_taxid": 4005020, "names_alt": []},
        ]
        with patch(
            "nanometa_live.core.taxonomy.taxid_mapping"
            ".get_mapping_collection", return_value=None,
        ):
            entries = preparer._get_watchlist_entries()
        assert entries[0]["kraken_taxid"] == 4005020


class TestAlertsPathConsultsProfile:
    """G3/G4: the Alerts-panel detection path."""

    @staticmethod
    def _detections():
        return [{"taxid": 1392, "name": "Bacillus anthracis", "reads": 500}]

    def test_taxid_shortcut_disabled_without_ncbi_profile(self):
        from nanometa_live.core.utils import pathogen_database as pdb

        with patch.object(pdb, "_database_taxids_are_ncbi",
                          return_value=False):
            alerts = pdb.check_for_dangerous_pathogens(self._detections())
        # Name matching still finds it; the raw-taxid shortcut did not decide.
        assert alerts, "name matching must still detect the organism"

    def test_alert_carries_both_taxids(self):
        from nanometa_live.core.utils import pathogen_database as pdb

        with patch.object(pdb, "_database_taxids_are_ncbi",
                          return_value=True):
            alerts = pdb.check_for_dangerous_pathogens(self._detections())
        assert alerts
        assert alerts[0]["detected_taxid"] == 1392
        assert alerts[0]["taxid"] == 1392


class TestReadinessMappingStaleness:
    """G9: a mapping file missing active entries is called out."""

    def test_missing_active_entries_counted(self, tmp_path):
        import json

        from nanometa_live.core.workflow.readiness_checker import (
            ReadinessChecker,
        )

        mapping_file = tmp_path / "x_mappings.json"
        mapping_file.write_text(json.dumps({
            "mappings": [{"ncbi_taxid": 1392}],
        }))
        active = [
            {"taxid": 1392, "enabled": True},
            {"taxid": 632, "enabled": True},              # not mapped
            {"taxid": 111, "db_taxid": 4005020},          # declared: exempt
        ]
        assert ReadinessChecker._count_unmapped_active(
            mapping_file, active
        ) == 1

    def test_no_watchlist_means_no_complaint(self, tmp_path):
        from nanometa_live.core.workflow.readiness_checker import (
            ReadinessChecker,
        )

        assert ReadinessChecker._count_unmapped_active(
            tmp_path / "absent.json", None
        ) == 0


class TestInDatabaseColumnShowsDeclaration:
    """G1 (UI): operator-set db_taxid renders as such, never 'Not Scanned'."""

    def test_operator_set_badge(self):
        from nanometa_live.app.layouts.watchlist_layout import (
            create_pathogen_row,
        )

        row = str(create_pathogen_row(
            {"taxid": 1392, "name": "Bacillus anthracis",
             "threat_level": "critical", "enabled": True}, 0,
            mapping_info={"confidence": "manual", "db_taxid": 4005020,
                          "db_name": "Bacillus_A anthracis",
                          "match_method": "operator_db_taxid"},
        ))
        assert "Operator-set" in row

    def test_declared_absent_badge(self):
        from nanometa_live.app.layouts.watchlist_layout import (
            create_pathogen_row,
        )

        row = str(create_pathogen_row(
            {"taxid": 632, "name": "Yersinia pestis",
             "threat_level": "critical", "enabled": True}, 0,
            mapping_info={"confidence": "unmapped", "db_taxid": None,
                          "db_name": "",
                          "match_method": "operator_db_taxid_absent"},
        ))
        assert "Declared, absent" in row
