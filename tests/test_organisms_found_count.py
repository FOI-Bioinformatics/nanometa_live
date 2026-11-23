"""The Organisms tab's "Organisms Found" count.

It counted species and genus rows with DIRECT reads > 0, which
- missed a species whose reads all sit in its subspecies (direct 0), the
  same direct-versus-cumulative trap CLAUDE.md records for attribution, and
- counted a genus with a few unresolved reads as a second organism beside
  its own species.
An organism is now a species with reads (subspecies included), plus a genus
whose reads resolve no further than the genus.
"""

import pandas as pd
import pytest

from nanometa_live.app.tabs.main_tab_helpers import count_organisms_found

pytestmark = pytest.mark.unit

COLS = ["%", "cumul_reads", "reads", "rank", "taxid", "name", "parent_taxid"]


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


def test_species_with_reads_only_in_subspecies_is_counted():
    df = _df([
        [100.0, 100, 0, "R", 1, "root", 0],
        [100.0, 100, 0, "G", 10, "Francisella", 1],
        [100.0, 100, 0, "S", 11, "Francisella tularensis", 10],
        [100.0, 100, 100, "S1", 12, "F. t. holarctica", 11],
    ])
    assert count_organisms_found(df) == 1


def test_genus_with_unresolved_reads_beside_its_species_is_one_organism():
    df = _df([
        [100.0, 100, 0, "R", 1, "root", 0],
        [100.0, 100, 10, "G", 10, "GenA", 1],
        [90.0, 90, 90, "S", 11, "GenA spA", 10],
    ])
    assert count_organisms_found(df) == 1


def test_genus_resolved_no_further_counts_once():
    df = _df([
        [100.0, 100, 0, "R", 1, "root", 0],
        [60.0, 60, 60, "G", 10, "GenA", 1],
        [40.0, 40, 0, "G", 20, "GenB", 1],
        [40.0, 40, 40, "S", 21, "GenB spB", 20],
        [0.0, 0, 0, "S", 22, "GenB spC", 20],
    ])
    # GenA (genus-only) + GenB spB; GenB itself and the empty spC are not.
    assert count_organisms_found(df) == 2


def test_species_under_an_intermediate_rank_still_covers_its_genus():
    df = _df([
        [100.0, 100, 0, "R", 1, "root", 0],
        [100.0, 100, 0, "G", 10, "GenA", 1],
        [100.0, 100, 0, "G1", 15, "GenA group", 10],
        [100.0, 100, 100, "S", 11, "GenA spA", 15],
    ])
    assert count_organisms_found(df) == 1
