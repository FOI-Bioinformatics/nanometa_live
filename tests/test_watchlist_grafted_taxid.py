"""A select agent must be caught even when the database renumbers it.

The in-house field databases are built with flextaxd: an NCBI backbone with
finer-resolution clades grafted in, the grafted nodes taking fresh identifiers
from a high block (4,000,000+). A watchlist entry carries the NCBI taxid, so on
such a database the taxids simply do not match and detection has to survive on
the organism name.

Verified against real output on 2026-07-28. The same barcode of Francisella
tularensis LVS classified as:

    k2_pluspfp_08_GB   taxid     263   34,096 reads
    bioshield26.0_8G   taxid 4007169   34,125 reads

Both raised the alert. This test pins that behaviour without needing either
database present, so a regression in name matching cannot reach a field build
where the taxids are guaranteed not to line up.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.watchlist.watchlist_manager import WatchlistManager

pytestmark = pytest.mark.unit

#: Francisella tularensis as NCBI numbers it, and as the Bioshield flextaxd
#: build numbers it. The second is a real observed value, not an invention.
NCBI_TAXID = 263
GRAFTED_TAXID = 4007169

CONFIG = {"watchlist": {"enabled": True, "builtin": ["cdc_bioterrorism"], "custom": []}}


def _detection(taxid: int, reads: int = 34125) -> list[dict]:
    return [{
        "taxid": taxid,
        "name": "Francisella tularensis",
        "reads": reads,
        "abundance": 99.9,
    }]


@pytest.fixture
def manager() -> WatchlistManager:
    m = WatchlistManager()
    m.load_config(CONFIG)
    assert m.get_active_entries(), "cdc_bioterrorism watchlist failed to load"
    return m


class TestGraftedTaxidStillAlerts:
    @pytest.mark.parametrize(
        "taxid,label",
        [(NCBI_TAXID, "NCBI backbone"), (GRAFTED_TAXID, "flextaxd grafted node")],
    )
    def test_select_agent_is_detected_under_either_numbering(
        self, manager, taxid, label
    ):
        alerts = manager.check_organisms(_detection(taxid))
        assert alerts, (
            f"Francisella tularensis at taxid {taxid} ({label}) raised no "
            f"alert. On a flextaxd database the taxid never equals the "
            f"watchlist's NCBI value, so a name-matching regression silently "
            f"disables select agent detection for every in-house build."
        )

    def test_the_alert_carries_the_database_taxid_for_attribution(self, manager):
        """Per-sample attribution keys on the report taxid, not the NCBI one.

        Without ``detected_taxid`` the detection resolves to no sample and
        renders identically to one that legitimately spans none.
        """
        alert = manager.check_organisms(_detection(GRAFTED_TAXID))[0]
        assert alert.get("detected_taxid") == GRAFTED_TAXID, (
            f"alert carries detected_taxid={alert.get('detected_taxid')!r}; "
            f"attribution needs the taxid as the report numbered it "
            f"({GRAFTED_TAXID})"
        )
        assert alert.get("taxid") == NCBI_TAXID, (
            "the alert should still identify the watchlist entry by its NCBI "
            "taxid so references and reporting resolve"
        )

    def test_an_unrelated_grafted_organism_does_not_alert(self, manager):
        """A high taxid must not alert on its own -- the name is what matched."""
        harmless = [{
            "taxid": GRAFTED_TAXID + 11,
            "name": "Limosilactobacillus fermentum",
            "reads": 4229,
            "abundance": 7.7,
        }]
        assert not manager.check_organisms(harmless), (
            "a non-watchlisted organism in the grafted taxid range raised an "
            "alert; matching is keying on the number range rather than identity"
        )
