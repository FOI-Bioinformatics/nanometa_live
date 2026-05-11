"""Regression tests for the watched-organisms badge vs cards mismatch (2026-05-11).

User reported on the server that the "Watched Organisms" header said
"5 detected" but the Detected section under it was empty -- all
matched entries had silently collapsed into the (collapsed by default)
"Not Detected" section.

Root cause: ``filter_detected_species`` (drives the badge count) and
``get_all_watchlist_with_detection`` (drives the cards) used
DIFFERENT matching criteria. The first matched by taxid OR species
NAME; the second matched by taxid ONLY. A watchlist entry whose taxid
didn't match a kraken2 row but whose NAME did got counted in the
badge yet rendered as "Not Detected" in the cards.

Secondary issue: ``filter_detected_species`` returned matched rows
without filtering on read count, so zero-read placeholder rows in
the kraken2 report inflated the badge.

Fix: add a name-keyed lookup to ``get_all_watchlist_with_detection``
so it agrees with the matching criteria of ``filter_detected_species``.
Switch both functions to ``cumul_reads`` (the F1-audit canonical
"actually detected" signal) and filter
``filter_detected_species`` to ``cumul_reads > 0``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nanometa_live.app.tabs.main_tab import (
    filter_detected_species,
    get_all_watchlist_with_detection,
)


def _kraken_df(rows: list[dict]) -> pd.DataFrame:
    """Build a kraken_df with the columns the main_tab consumers expect."""
    return pd.DataFrame(rows)


class TestBadgeAndCardsAgreeOnNameOnlyMatch:
    """A watchlist entry that matches by name only must appear in BOTH
    the badge count (via filter_detected_species) AND the detected
    cards (via get_all_watchlist_with_detection)."""

    def test_name_match_only(self):
        # Kraken2 reports the species under a different taxid than the
        # watchlist's NCBI taxid (common with GTDB or reclassified taxa).
        kraken_df = _kraken_df([
            {
                "taxid": "9999",        # different taxid in DB
                "name": "Bacillus anthracis",
                "rank": "S",
                "reads": 0,             # per-rank assignment is zero
                "cumul_reads": 42,      # but cumulative is non-zero
                "%": 5.0,
            },
            {
                "taxid": "1",
                "name": "root",
                "rank": "R",
                "reads": 42,
                "cumul_reads": 42,
                "%": 100.0,
            },
        ])
        watchlist = [{"taxid": 1392, "name": "Bacillus anthracis"}]

        detected = filter_detected_species(kraken_df, watchlist)
        all_with_status = get_all_watchlist_with_detection(
            kraken_df, watchlist
        )

        assert len(detected) == 1, (
            "filter_detected_species must match by name when taxid differs"
        )
        # The badge count is `len(detected)`; the cards detection flag
        # is `entry['detected']`. They MUST agree on this row.
        detected_via_cards = sum(
            1 for e in all_with_status if e.get("detected")
        )
        assert detected_via_cards == 1, (
            "get_all_watchlist_with_detection must also pick up the "
            "name match. Otherwise the badge says 'X detected' but no "
            "cards render."
        )


class TestZeroReadPlaceholdersFilteredOut:
    """A kraken2 row with cumul_reads=0 must not inflate the badge."""

    def test_zero_cumul_reads_excluded(self):
        kraken_df = _kraken_df([
            {
                "taxid": "1392",
                "name": "Bacillus anthracis",
                "rank": "S",
                "reads": 0,
                "cumul_reads": 0,       # zero-read placeholder
                "%": 0.0,
            },
        ])
        watchlist = [{"taxid": 1392, "name": "Bacillus anthracis"}]

        detected = filter_detected_species(kraken_df, watchlist)

        assert detected == [], (
            "filter_detected_species must filter out zero-cumul_reads "
            "placeholder rows so the badge doesn't inflate"
        )


class TestCumulReadsUsedConsistently:
    """Both functions should use cumul_reads as the detection criterion."""

    def test_filter_detected_uses_cumul_reads(self):
        # The per-rank ``reads`` column is zero but cumul is non-zero.
        # The species is genuinely detected; the badge must count it.
        kraken_df = _kraken_df([
            {
                "taxid": "1392",
                "name": "Bacillus anthracis",
                "rank": "S",
                "reads": 0,
                "cumul_reads": 100,
                "%": 12.5,
            },
        ])
        watchlist = [{"taxid": 1392, "name": "Bacillus anthracis"}]

        detected = filter_detected_species(kraken_df, watchlist)

        assert len(detected) == 1
        assert detected[0]["reads"] == 100, (
            "filter_detected_species must report cumul_reads as the "
            "'reads' field so the alert banner and badge surface the "
            "F1-corrected total"
        )

    def test_cards_use_cumul_reads(self):
        kraken_df = _kraken_df([
            {
                "taxid": "1392",
                "name": "Bacillus anthracis",
                "rank": "S",
                "reads": 0,
                "cumul_reads": 100,
                "%": 12.5,
            },
        ])
        watchlist = [{"taxid": 1392, "name": "Bacillus anthracis"}]

        all_with_status = get_all_watchlist_with_detection(
            kraken_df, watchlist
        )

        match = next(
            (e for e in all_with_status if e["ncbi_taxid"] == 1392),
            None,
        )
        assert match is not None
        assert match["detected"] is True, (
            "Card detection flag must be True when cumul_reads > 0 "
            "even if the per-rank 'reads' column is zero"
        )
        assert match["reads"] == 100, (
            "Cards must surface cumul_reads (not per-rank reads) so "
            "the displayed total matches the F1-audit canonical count"
        )
