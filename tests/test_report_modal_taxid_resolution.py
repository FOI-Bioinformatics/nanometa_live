"""The pathogen report modal must find reads by the taxid the report uses.

Reproduced live on 2026-08-19 (field bug report, Bioshield/GTDB database):
clicking the Alert card opened the modal with reads N/A, abundance N/A and
confidence N/A -- while the same organism sat at 28,724 reads / 52.4% on the
dashboard. The card's View Report button carries the WATCHLIST entry taxid
(an NCBI taxid, or a pseudo-taxid for a name-only entry), but
``_lookup_organism_reads`` matched it against the Kraken2 report's ``taxid``
column, which on a GTDB/flextaxd database holds the DATABASE taxid. The two
coincide only on an NCBI database, so the modal failed exactly on the field
builds this tool targets -- the same taxid-space split ``samples_for_detection``
already solves for the verdict banner ("Never index taxid_to_samples
directly", CLAUDE.md).

The fix resolves the watchlist entry FIRST and then looks reads up by every
candidate taxid: the one clicked, the entry's ``db_taxid`` from the database
scan, and the mapping collection's translation.
"""

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.tabs.dashboard_helpers import (
    _lookup_organism_reads,
    _lookup_sample_breakdown,
    _report_taxid_candidates,
    build_report_payload,
)
from nanometa_live.core.taxonomy.pseudo_taxid import PSEUDO_TAXID_BASE

DB_TAXID = 4007187          # what the Kraken2 report carries (GTDB graft node)
NCBI_TAXID = 263            # what the watchlist entry carries
PSEUDO = PSEUDO_TAXID_BASE + 42


KRAKEN_REPORT = """\
 50.00\t100\t10\tU\t0\tunclassified
 50.00\t100\t0\tR\t1\troot
 50.00\t100\t0\tD\t2\t  Bacteria
 50.00\t100\t100\tS\t{db_taxid}\t    Francisella tularensis
"""


@pytest.fixture()
def results_dir(tmp_path):
    kraken = tmp_path / "kraken2"
    kraken.mkdir()
    report = kraken / "barcode11.kraken2.report.txt"
    report.write_text(KRAKEN_REPORT.format(db_taxid=DB_TAXID))
    # Back-date so the loader's file-stability check passes.
    old = time.time() - 60
    import os
    os.utime(report, (old, old))
    return tmp_path


class _Entry:
    """Watchlist entry double: only the attributes the resolver reads."""

    def __init__(self, taxid, db_taxid=None):
        self.taxid = taxid
        self.db_taxid = db_taxid
        self.name = "Francisella tularensis"
        # Everything the payload builder may read off a watchlist entry.
        self.common_name = "tularemia"
        self.threat_level = "critical"
        self.bsl_level = None
        self.category = "Watchlist"
        self.notes = ""
        self.action_required = "Follow laboratory protocols"
        self.organism_type = "bacteria"
        self.annotation = ""
        self.ncbi_link = None
        self.gtdb_link = None
        self.validated = False
        self.validation_date = None
        self.lineage = None
        self.gtdb_taxonomy = None


class TestCandidateOrder:
    def test_clicked_taxid_comes_first(self):
        cands = _report_taxid_candidates(DB_TAXID, None)
        assert cands[0] == DB_TAXID

    def test_entry_db_taxid_is_a_candidate(self):
        cands = _report_taxid_candidates(NCBI_TAXID, _Entry(NCBI_TAXID, DB_TAXID))
        assert NCBI_TAXID in cands and DB_TAXID in cands

    def test_pseudo_taxid_entry_resolves_through_db_taxid(self):
        cands = _report_taxid_candidates(PSEUDO, _Entry(PSEUDO, DB_TAXID))
        assert DB_TAXID in cands

    def test_no_duplicates_and_no_none(self):
        cands = _report_taxid_candidates(DB_TAXID, _Entry(DB_TAXID, DB_TAXID))
        assert cands == [DB_TAXID]
        assert None not in _report_taxid_candidates(NCBI_TAXID, _Entry(NCBI_TAXID))


class TestReadsLookup:
    def test_db_taxid_still_matches_directly(self, results_dir):
        out = _lookup_organism_reads([DB_TAXID], {
            "results_output_directory": str(results_dir)}, None)
        assert out["reads"] != "N/A"
        assert out["reads_int"] == 100

    def test_watchlist_taxid_falls_through_to_db_taxid(self, results_dir):
        # The field failure: clicked taxid misses, db_taxid candidate hits.
        out = _lookup_organism_reads([NCBI_TAXID, DB_TAXID], {
            "results_output_directory": str(results_dir)}, None)
        assert out["reads_int"] == 100, (
            "the modal rendered N/A for an organism the dashboard showed at "
            "a six-figure read count (Bioshield field report, 2026-08-19)"
        )

    def test_no_match_stays_na(self, results_dir):
        out = _lookup_organism_reads([999999], {
            "results_output_directory": str(results_dir)}, None)
        assert out["reads"] == "N/A"

    def test_override_only_config_resolves_the_directory(self, results_dir):
        # Sibling of the validation-tab fix (ae63b3a): a config that has not
        # been through Start carries only results_dir_override.
        out = _lookup_organism_reads([DB_TAXID], {
            "results_dir_override": str(results_dir)}, None)
        assert out["reads_int"] == 100


class TestSampleBreakdown:
    def test_breakdown_resolves_through_candidates(self, results_dir):
        breakdown = _lookup_sample_breakdown([NCBI_TAXID, DB_TAXID], {
            "results_output_directory": str(results_dir)})
        assert breakdown, "per-sample breakdown lost on a GTDB database"
        assert breakdown[0]["sample"] == "barcode11"


class TestFullPayload:
    def test_payload_for_watchlist_taxid_carries_real_reads(self, results_dir):
        from unittest.mock import patch

        entry = _Entry(NCBI_TAXID, DB_TAXID)

        class _Mgr:
            def get_active_entries(self):
                return {NCBI_TAXID: entry}

        # dashboard_helpers binds the name at import time, so patch it there.
        with patch(
            "nanometa_live.app.tabs.dashboard_helpers.get_watchlist_manager",
            return_value=_Mgr(),
        ):
            payload = build_report_payload(
                NCBI_TAXID,
                {"results_output_directory": str(results_dir)},
                None,
            )
        # Payload layout: [is_open, name, common, annotation, category, bsl,
        #                  reads, abundance, confidence, ...]
        assert payload[0] is True
        assert payload[6] != "N/A", "modal reads regressed to N/A"


class TestViewReportIdTypesAreDistinctPerSurface:
    """The Dashboard alert cards and the Organisms tab cards must not share a
    pattern id type. A shared type means the SAME dict id exists twice in the
    layout whenever an organism appears on both surfaces (every watched
    detection); duplicate ids tear the n_clicks bookkeeping, and the modal
    callback's spurious-reopen guard then swallows genuine clicks -- the
    Dashboard's View Report button did nothing at all (2026-08-19 bug-report
    reproduction)."""

    COMPONENTS = Path(__file__).resolve().parents[1] / "nanometa_live" / "app" / "components"

    def test_organism_cards_use_their_own_type(self):
        src = (self.COMPONENTS / "organism_components.py").read_text()
        assert '"pathogen-view-report"' not in src, (
            "organism cards share the alert cards' id type again -- duplicate "
            "dict ids swallow real clicks on either surface"
        )
        assert '"organism-view-report"' in src

    def test_modal_callback_listens_to_both_types(self):
        src = (
            Path(__file__).resolve().parents[1]
            / "nanometa_live" / "app" / "tabs" / "dashboard_tab.py"
        ).read_text()
        assert '"organism-view-report"' in src, (
            "the Organisms tab's Details button no longer opens the modal"
        )
