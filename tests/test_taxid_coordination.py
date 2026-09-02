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


class TestOneDetectionPerWatchlistEntry:
    """Reaudit finding from the real LVS run: the species row plus 11
    subspecies/strain rows each produced their own detection for the SAME
    entry, so the banner announced "12 of 35 watched pathogens" for one
    organism and the reads double-counted (the species row's cumulative
    count already contains its descendants)."""

    @staticmethod
    def _organisms():
        # Species node + two strain nodes, all resolving to entry 263.
        return [
            {"taxid": 263, "name": "Francisella tularensis",
             "reads": 34103, "abundance": 99.0},
            {"taxid": 119857, "name": "Francisella tularensis subsp. holarctica",
             "reads": 1056, "abundance": 3.0},
            {"taxid": 264, "name": "Francisella tularensis subsp. novicida",
             "reads": 3245, "abundance": 9.0},
        ]

    def test_check_organisms_dedupes_to_dominant_node(self):
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager,
        )

        m = WatchlistManager()
        m.enable_watchlist("cdc_bioterrorism")
        hits = m.check_organisms(self._organisms())
        entry_hits = [h for h in hits if h.get("taxid") == 263]
        assert len(entry_hits) == 1, (
            f"one watchlist entry must yield one detection, got "
            f"{len(entry_hits)}"
        )
        assert entry_hits[0]["reads"] == 34103
        assert entry_hits[0]["detected_taxid"] == 263

    def test_distinct_entries_sharing_an_ncbi_taxid_each_keep_their_alert(self):
        """One detection per ENTRY, where entry identity is (NCBI taxid, db_taxid).

        The Bioshield list carries *Escherichia coli*, *E. coli_E* and
        *E. coli_F* as three entries with distinct db_taxids and the same
        NCBI taxid 562 (GTDB splits the polyphyletic species; NCBI has one
        id). The manager stores them under three keys (``_identity_key``),
        but the alert dedup keyed on the NCBI taxid alone and collapsed them:
        replaying run R1 of the round-4 audit, *E. coli_F* at 11 reads
        (threshold 10) vanished from the alarm list behind *E. coli* at 22,
        and which variant survived flipped with the frame's row order.
        """
        from unittest.mock import patch

        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager,
        )

        with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
            m = WatchlistManager()
            for name, db_taxid in (("Escherichia coli", 4000549),
                                   ("Escherichia coli_E", 4000558),
                                   ("Escherichia coli_F", 4000553)):
                m.add_custom_entry({
                    "taxid": 562, "db_taxid": db_taxid, "name": name,
                    "threat_level": "high", "enabled": True,
                    "alert_threshold": 10,
                })
            m._loaded = True
            assert len(m.get_active_entries()) == 3

            organisms = [
                {"taxid": 4000549, "name": "Escherichia coli", "reads": 22, "abundance": 2.4},
                {"taxid": 4000553, "name": "Escherichia coli_F", "reads": 11, "abundance": 1.2},
                {"taxid": 4000558, "name": "Escherichia coli_E", "reads": 3, "abundance": 0.3},
            ]
            above, below = m.check_organisms_split(organisms)

        assert sorted(a["detected_taxid"] for a in above) == [4000549, 4000553]
        assert [a["detected_taxid"] for a in below] == [4000558]
        # And the reverse row order must not change who survives.
        with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
            above_rev, _ = m.check_organisms_split(list(reversed(organisms)))
        assert sorted(a["detected_taxid"] for a in above_rev) == [4000549, 4000553]

    def test_check_organisms_with_mapping_dedupes_too(self):
        from nanometa_live.core.watchlist.watchlist_manager import (
            WatchlistManager,
        )

        m = WatchlistManager()
        m.enable_watchlist("cdc_bioterrorism")
        hits = m.check_organisms_with_mapping(self._organisms())
        entry_hits = [h for h in hits if h.get("taxid") == 263]
        assert len(entry_hits) == 1
        assert entry_hits[0]["reads"] == 34103


class TestAlertPanelTriggerSet:
    """The alert-card panel must re-run when the watchlist changes: with
    only results-fingerprint as Input, enabling a watchlist on a static
    results dir flipped the verdict to ACTION REQUIRED while the cards
    stayed hidden forever (2026-08-17 reaudit, live E2E walkthrough)."""

    def test_panel_listens_to_watchlist_and_interval(self):
        from dash_test_utils import make_callback_app
        from nanometa_live.app.tabs.dashboard_tab import (
            register_dashboard_callbacks,
        )

        app = make_callback_app(register_dashboard_callbacks)
        for cb_id, spec in app.callback_map.items():
            if "dashboard-pathogen-alert-container" in cb_id:
                inputs = str(spec.get("inputs"))
                assert "watchlist-tab-state" in inputs
                assert "update-interval" in inputs
                assert "results-fingerprint" in inputs
                return
        raise AssertionError("alert panel callback not found")


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
