"""Per-sample attribution must count reads the way the rest of the app does.

``_load_per_sample_organisms`` filtered and reported on the per-rank ``reads``
column. Every other surface uses ``cumul_reads`` -- the Organisms tab says so
in a comment ("for consistency with the organism cards"), and CLAUDE.md warns
specifically that the per-rank column is the wrong one.

At species rank the difference is the reads assigned to subspecies below it,
which are the same organism. Measured on a real Bioshield run:

    barcode11   reads=29,721   cumul_reads=34,096   (4,375 at F. t. holarctica)
    barcode16   reads=4        cumul_reads=6

Two consequences. The dashboard attributed 29,721 reads to a detection the
Organisms tab reported as 34,096 -- the same organism, two numbers, one screen
apart. And barcode16, the run's negative control, fell one read below
PER_SAMPLE_DISCOVERY_FLOOR (5) on the undercount, so its contamination was
invisible: not shown, not labelled, not attributable.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nanometa_live.app.tabs.dashboard_helpers import _species_df_to_organisms

pytestmark = pytest.mark.unit


def _species_row(taxid, name, reads, cumul_reads, pct):
    return {
        "taxid": taxid, "name": name, "rank": "S",
        "reads": reads, "cumul_reads": cumul_reads, "%": pct,
    }


class TestCumulativeReadsAreReported:
    def test_subspecies_reads_are_included(self):
        """The barcode11 case: 4,375 reads sit at F. t. holarctica."""
        df = pd.DataFrame([
            _species_row(263, "Francisella tularensis", 29721, 34096, 99.87)
        ])

        organisms = _species_df_to_organisms(df)

        assert organisms[0]["reads"] == 34096, (
            "attribution reported the per-rank count, so the dashboard "
            "disagrees with the Organisms tab about the same organism"
        )

    def test_a_species_with_no_children_is_unchanged(self):
        """cumul_reads == reads when nothing sits below; no double counting."""
        df = pd.DataFrame([_species_row(1280, "Staphylococcus aureus", 500, 500, 12.5)])

        assert _species_df_to_organisms(df)[0]["reads"] == 500

    def test_a_missing_cumul_column_falls_back(self):
        """Older or partial frames must not crash attribution."""
        df = pd.DataFrame([{
            "taxid": 263, "name": "Francisella tularensis", "rank": "S",
            "reads": 42, "%": 1.0,
        }])

        assert _species_df_to_organisms(df)[0]["reads"] == 42

    def test_abundance_is_untouched(self):
        df = pd.DataFrame([_species_row(263, "F. tularensis", 29721, 34096, 99.87)])

        assert _species_df_to_organisms(df)[0]["abundance"] == pytest.approx(99.87)


class TestTheDiscoveryFloorSeesTheSameNumber:
    """The filter and the reported value must use one column.

    barcode16 carried 6 F. tularensis reads cumulatively and 4 directly. With
    a floor of 5 the two columns disagree about whether the run's negative
    control contained the organism at all.
    """

    def test_a_sample_above_the_floor_cumulatively_is_kept(self):
        from nanometa_live.app.tabs.dashboard_helpers import (
            PER_SAMPLE_DISCOVERY_FLOOR,
        )

        assert PER_SAMPLE_DISCOVERY_FLOOR == 5
        df = pd.DataFrame([_species_row(263, "Francisella tularensis", 4, 6, 54.55)])

        organisms = _species_df_to_organisms(df)
        kept = [o for o in organisms if o["reads"] >= PER_SAMPLE_DISCOVERY_FLOOR]

        assert kept, (
            "a sample carrying 6 reads of a select agent was dropped below "
            "the discovery floor by counting only 4 of them"
        )
