"""Which Kraken2 rank codes count as "a species-level organism".

Kraken2 reports a rank code per row. Below species it emits ``S1``, ``S2``,
``S3`` for subspecies / strain levels, and the distinction is clinical rather
than cosmetic: a Bioshield report resolves *Francisella tularensis* into
holarctica (Type B, the LVS vaccine lineage), tularensis (Type A, markedly
more virulent), novicida and mediasiatica. An operator screening for Type A
needs the subspecies row; a filter of ``rank == "S"`` drops it.

Reads are NOT double counted by including them. Kraken2's ``reads`` column is
what was assigned directly at a node and ``cumul_reads`` is that node plus its
descendants, so on that report the species row carries 3,406 direct and 9,602
cumulative while its four children carry 6,184 + 6 + 4 + 2 = 6,196 -- the
cumulative figure already contains them. Each row is a distinct taxid, so a
per-taxon consumer (watchlist matching, per-sample attribution, organism
cards) can safely treat them as independent candidates.

What is NOT safe is SUMMING across ranks: adding a species row to its own
children counts the same reads twice. The report's abundance table therefore
stays species-only on purpose -- listing a species beside its own subspecies
in a "most abundant organisms" ranking reads as double counting even when the
arithmetic is right.
"""

from __future__ import annotations

from typing import Any

#: Rank codes treated as a species-level organism. ``S`` plus the subspecies /
#: strain levels Kraken2 emits beneath it.
SPECIES_RANKS = frozenset({"S", "S1", "S2", "S3"})


def is_species_rank(rank: Any) -> bool:
    """True for ``S`` and the subspecies ranks below it.

    Tolerates whitespace and non-string input, because rank arrives from a
    parsed report column and may be NaN on a malformed row.
    """
    if rank is None:
        return False
    return str(rank).strip() in SPECIES_RANKS


def species_rank_mask(df):
    """Boolean mask selecting species-level rows of a Kraken2 report frame.

    Kept here so the several consumers cannot drift apart on what counts as a
    species -- they previously used three different rules: ``== "S"``,
    ``in {"S","S1","S2"}``, and a normalisation table that was never called.
    """
    return df["rank"].map(is_species_rank)
