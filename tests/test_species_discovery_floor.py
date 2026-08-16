"""The aggregate discovery floor must gate on the column it reports.

Three aggregate "All Samples" call sites (the verdict banner's status cache,
the pathogen alert panel, and the alerts list) filtered species rows with
``kraken_df["reads"] >= 5`` and then reported ``cumul_reads`` via
``_species_df_to_organisms``. On a subspecies-resolving database (flextaxd /
GTDB) a species node can carry almost no DIRECT reads while its cumulative
count is in the thousands -- the documented Bioshield report has the species
row at 3,406 direct against 9,602 cumulative, and in the degenerate case the
species row shows 0 direct with everything parked on S1 children. Gating on
the per-rank column dropped such a species before watchlist matching ever saw
it, so ``select_verdict`` returned ALL CLEAR over a real detection.

All discovery-floor consumers now filter through ``_species_discovery_df``,
which gates on ``cumul_reads`` (falling back to ``reads``), matching what
``_species_df_to_organisms`` reports. Audit 2026-08-16, finding D1.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from nanometa_live.app.tabs.dashboard_helpers import (
    _species_df_to_organisms,
    _species_discovery_df,
)

pytestmark = pytest.mark.unit


def _row(taxid, name, rank, reads, cumul_reads, pct=1.0):
    return {
        "taxid": taxid, "name": name, "rank": rank,
        "reads": reads, "cumul_reads": cumul_reads, "%": pct,
    }


class TestSpeciesDiscoveryFloor:
    def test_species_with_reads_on_subspecies_children_is_kept(self):
        """The false-negative case: 0 direct reads, everything on S1 nodes."""
        df = pd.DataFrame([
            _row(1, "root", "R", 0, 9602),
            _row(263, "Francisella tularensis", "S", 0, 9602, 99.87),
            _row(119857, "F. tularensis holarctica", "S1", 6196, 6196, 64.5),
        ])

        kept = _species_discovery_df(df)
        assert 263 in set(kept["taxid"]), (
            "a species whose reads sit on its subspecies children was "
            "dropped by the discovery floor; the verdict banner would "
            "render ALL CLEAR over a real detection"
        )

    def test_floor_and_report_use_the_same_column(self):
        """Whatever the floor keeps, the organism dict must report >= floor."""
        df = pd.DataFrame([
            _row(263, "Francisella tularensis", "S", 3406, 9602, 99.87),
            _row(562, "Escherichia coli", "S", 2, 3, 0.1),
        ])

        organisms = _species_df_to_organisms(_species_discovery_df(df))
        assert [o["taxid"] for o in organisms] == [263]
        assert organisms[0]["reads"] == 9602

    def test_below_floor_species_is_excluded(self):
        df = pd.DataFrame([_row(562, "Escherichia coli", "S", 2, 4, 0.1)])
        assert _species_discovery_df(df).empty

    def test_missing_cumul_column_falls_back_to_reads(self):
        df = pd.DataFrame([
            {"taxid": 562, "name": "Escherichia coli", "rank": "S",
             "reads": 100, "%": 1.0},
        ])
        kept = _species_discovery_df(df)
        assert len(kept) == 1

    def test_subspecies_rows_participate(self):
        """species_rank_mask covers S1-S3; a watched subspecies clears the
        floor on its own cumulative count."""
        df = pd.DataFrame([
            _row(119857, "F. tularensis holarctica", "S1", 40, 40, 5.0),
        ])
        assert len(_species_discovery_df(df)) == 1


class TestNoInlineFloorFilters:
    """No dashboard call site may reintroduce an inline per-rank floor.

    The gate and the displayed count must come from one definition; an inline
    ``kraken_df["reads"] >=`` filter beside ``_species_df_to_organisms`` is
    exactly the drift this test pins down.
    """

    def _source(self, module_name):
        import nanometa_live.app.tabs as tabs_pkg
        path = os.path.join(os.path.dirname(tabs_pkg.__file__), module_name)
        with open(path) as fh:
            return fh.read()

    def test_dashboard_tab_has_no_inline_reads_floor(self):
        src = self._source("dashboard_tab.py")
        assert 'kraken_df["reads"] >=' not in src
        assert src.count("_species_discovery_df(") >= 2

    def test_dashboard_helpers_floor_sites_use_the_helper(self):
        src = self._source("dashboard_helpers.py")
        # The definition contains the only allowed floor expression.
        assert src.count('kraken_df[floor_col] >=') == 1
        assert 'kraken_df["reads"] >= 5' not in src
