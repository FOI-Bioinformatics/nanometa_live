"""Pin the dashboard's sequences-analyzed metric.

Regression guard for the metric mismatch caught in the 2026-05-06
audit, scenario 5: the dashboard tile previously read sum(reads),
which is the per-rank assignment column. With realistic data that's
fine; with degenerate small inputs (e.g. one read parked at root
because chopper filtering left almost nothing) every per-rank cell
is 0 and the tile reads "0 sequences" while the underlying Kraken2
report says one read was classified.

The fix: use root.cumul_reads + unclassified.cumul_reads, which is
what get_classification_stats already returns for every other
caller in the codebase.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nanometa_live.app.utils.callback_helpers import (
    get_classification_stats,
    get_total_kraken_reads,
)


KRAKEN_COLUMNS = ["%", "cumul_reads", "reads", "rank", "taxid", "name", "parent_taxid"]


def _row(pct, cumul, reads_col, rank, taxid, name, parent):
    return [pct, cumul, reads_col, rank, taxid, name, parent]


class TestGetClassificationStats:
    def test_empty_df_returns_zeros(self):
        df = pd.DataFrame(columns=KRAKEN_COLUMNS)
        assert get_classification_stats(df) == (0, 0, 0.0)

    def test_root_only_no_unclassified_counts_as_classified(self):
        # The exact scenario 5 case: one read landed at root and got
        # no further assignment, no unclassified row. Pre-fix the tile
        # showed 0; the corrected metric counts root.cumul_reads = 1.
        df = pd.DataFrame(
            [_row(100.0, 1, 0, "R", 1, "root", 0)],
            columns=KRAKEN_COLUMNS,
        )
        classified, unclassified, rate = get_classification_stats(df)
        assert classified == 1
        assert unclassified == 0
        assert rate == 100.0

    def test_classified_plus_unclassified(self):
        df = pd.DataFrame(
            [
                _row(100.0, 80, 0, "R", 1, "root", 0),
                _row(0.0, 20, 20, "U", 0, "unclassified", 0),
            ],
            columns=KRAKEN_COLUMNS,
        )
        classified, unclassified, rate = get_classification_stats(df)
        assert classified == 80
        assert unclassified == 20
        assert rate == pytest.approx(80.0)

    def test_name_column_with_indent_is_handled(self):
        # Kraken2 reports indent the name column with leading spaces;
        # the helper strips before matching.
        df = pd.DataFrame(
            [
                _row(100.0, 7, 0, "R", 1, "  root", 0),
                _row(0.0, 3, 3, "U", 0, "  unclassified", 0),
            ],
            columns=KRAKEN_COLUMNS,
        )
        classified, unclassified, _ = get_classification_stats(df)
        assert classified == 7
        assert unclassified == 3


class TestGetTotalKrakenReads:
    def test_total_is_classified_plus_unclassified(self):
        df = pd.DataFrame(
            [
                _row(100.0, 80, 0, "R", 1, "root", 0),
                _row(0.0, 20, 20, "U", 0, "unclassified", 0),
            ],
            columns=KRAKEN_COLUMNS,
        )
        assert get_total_kraken_reads(df) == 100

    def test_degenerate_single_root_read(self):
        # Pre-fix the dashboard would have shown 0 here (sum of reads
        # column is 0 because the single read was parked at root).
        df = pd.DataFrame(
            [_row(100.0, 1, 0, "R", 1, "root", 0)],
            columns=KRAKEN_COLUMNS,
        )
        assert get_total_kraken_reads(df) == 1

    def test_does_not_collapse_when_all_reads_at_root(self):
        # Even if every read is parked at root with 0 leaf assignments,
        # the metric must reflect the total number of reads ingested.
        df = pd.DataFrame(
            [_row(100.0, 250, 0, "R", 1, "root", 0)],
            columns=KRAKEN_COLUMNS,
        )
        assert get_total_kraken_reads(df) == 250

    def test_legacy_sum_reads_disagrees_for_degenerate_case(self):
        # Documents *why* the fix matters: the old code used
        # int(df['reads'].sum()) which collapses to 0 here while the
        # new metric correctly reports 1. If a future refactor
        # re-introduces sum(reads) this assertion will catch it.
        df = pd.DataFrame(
            [_row(100.0, 1, 0, "R", 1, "root", 0)],
            columns=KRAKEN_COLUMNS,
        )
        assert int(df["reads"].sum()) == 0  # the old, broken metric
        assert get_total_kraken_reads(df) == 1  # the corrected metric
