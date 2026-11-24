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


def count_organisms_found(kraken_df) -> int:
    """The Organisms tab's "Organisms Found": species with reads, plus genera
    whose reads resolve no further than the genus.

    Counts cumulative reads, so a species whose reads all sit in its
    subspecies is found (the direct ``reads`` column is 0 there), and a genus
    is counted only when none of its species carries reads -- otherwise a
    genus with a few unresolved reads was a second organism beside its own
    species. Species are linked to their genus through ``parent_taxid``;
    without that column every genus with reads is counted as before.
    """
    if kraken_df is None or kraken_df.empty:
        return 0
    col = "cumul_reads" if "cumul_reads" in kraken_df.columns else "reads"
    ranks = kraken_df["rank"].astype(str).str.strip()
    reads = kraken_df[col].fillna(0).astype(int)
    taxids = kraken_df["taxid"].fillna(0).astype(int)
    present = (reads > 0) & (taxids > 1)

    species = taxids[present & (ranks == "S")].tolist()
    genera = set(taxids[present & (ranks == "G")].tolist())

    if "parent_taxid" in kraken_df.columns:
        parent = dict(zip(taxids.tolist(),
                          kraken_df["parent_taxid"].fillna(0).astype(int).tolist()))
        rank_of = dict(zip(taxids.tolist(), ranks.tolist()))
        covered = set()
        for tid in species:
            node, hops = parent.get(tid), 0
            while node and node not in covered and hops < 50:
                if rank_of.get(node) == "G":
                    covered.add(node)
                    break
                node, hops = parent.get(node), hops + 1
        genera -= covered
    return len(species) + len(genera)
