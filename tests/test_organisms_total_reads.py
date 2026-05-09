"""Regression test pinning the Organisms tab total-reads metric.

The Organisms tab previously computed total_reads as
``int(kraken_df['reads'].sum())``. The per-rank ``reads`` column collapses
to zero when every read is parked at root level (degenerate small inputs),
which made Organisms disagree with the Dashboard tile. The Dashboard tile
uses ``get_classification_stats`` (root.cumul_reads + unclassified.cumul_reads).

This test asserts the two callers now compute the same total. It does so
by importing ``main_tab`` to confirm the helper symbol is in scope and
exercising the helper directly on the same minimal frame the Organisms
callback would receive.
"""

from __future__ import annotations

import pandas as pd

from nanometa_live.app.utils.callback_helpers import (
    get_classification_stats,
    get_total_kraken_reads,
)


KRAKEN_COLUMNS = ["%", "cumul_reads", "reads", "rank", "taxid", "name", "parent_taxid"]


def _row(pct, cumul, reads_col, rank, taxid, name, parent):
    return [pct, cumul, reads_col, rank, taxid, name, parent]


def test_organisms_helper_imported_in_main_tab():
    """The Organisms tab must import the shared helper, not reimplement it."""
    from nanometa_live.app.tabs import main_tab

    assert hasattr(main_tab, "get_classification_stats"), (
        "main_tab must import get_classification_stats so the Organisms "
        "tab agrees with the Dashboard tile."
    )


def test_organisms_total_reads_matches_dashboard_for_root_only_input():
    # Degenerate single-read scenario: one read at root, no leaf assignment,
    # no unclassified row. The legacy sum(reads) returned 0 here.
    df = pd.DataFrame(
        [_row(100.0, 1, 0, "R", 1, "root", 0)],
        columns=KRAKEN_COLUMNS,
    )

    classified, unclassified, _rate = get_classification_stats(df)
    organisms_total = classified + unclassified
    dashboard_total = get_total_kraken_reads(df)

    assert organisms_total == dashboard_total == 1
    # And confirm the legacy formula would have disagreed.
    assert int(df["reads"].sum()) == 0


def test_organisms_total_reads_matches_dashboard_with_unclassified():
    df = pd.DataFrame(
        [
            _row(100.0, 80, 0, "R", 1, "root", 0),
            _row(0.0, 20, 20, "U", 0, "unclassified", 0),
        ],
        columns=KRAKEN_COLUMNS,
    )

    classified, unclassified, _rate = get_classification_stats(df)
    organisms_total = classified + unclassified
    dashboard_total = get_total_kraken_reads(df)

    assert organisms_total == dashboard_total == 100
