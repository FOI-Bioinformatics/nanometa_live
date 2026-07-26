"""Synthetic taxids for watchlist entries that have no NCBI identity.

A watchlist entry may name an organism that NCBI does not have a taxid for --
typically a GTDB-only species, or one an operator typed in by name. Such an
entry still needs an integer key: it identifies the entry in the manager's
dict, names its downloaded genome file (``{taxid}.fasta``), keys the
taxid-mapping cache, and becomes the ``index`` of its pattern-matching Dash
component id.

Those keys are minted in a reserved high band so they can never be mistaken
for a real NCBI taxid, and so any code about to make an NCBI-by-taxid call
can cheaply refuse. That refusal matters beyond correctness: NCBI's esummary
returns HTTP 400 for a nonexistent taxid, which would trip the shared
per-host circuit breaker and stall lookups for every *other* organism in the
run.

The constant and the predicate lived in four modules independently, which is
three too many for a value that only works if everyone agrees on it.
"""

from __future__ import annotations

#: Lower bound of the synthetic-taxid band. Real NCBI taxids are well below
#: this (currently ~10^7), so the band cannot collide.
PSEUDO_TAXID_BASE: int = 2_000_000_000

#: Width of the band. Keys are ``PSEUDO_TAXID_BASE + crc32(name) % PSEUDO_TAXID_SPAN``.
PSEUDO_TAXID_SPAN: int = 1_000_000_000


def is_real_ncbi_taxid(taxid) -> bool:
    """True for a plausible real NCBI taxid: positive and below the band.

    Non-numeric and missing values are False rather than an error, because
    callers reach this with values straight out of YAML and Kraken2 reports.
    """
    try:
        value = int(taxid)
    except (TypeError, ValueError):
        return False
    return 0 < value < PSEUDO_TAXID_BASE


def is_pseudo_taxid(taxid) -> bool:
    """True for a synthetic key minted by ``stable_pseudo_taxid``."""
    try:
        value = int(taxid)
    except (TypeError, ValueError):
        return False
    return PSEUDO_TAXID_BASE <= value < PSEUDO_TAXID_BASE + PSEUDO_TAXID_SPAN


def stable_pseudo_taxid(name: str) -> int:
    """A deterministic synthetic taxid for a name.

    Must be stable across process restarts: Python's builtin ``hash()``
    randomises string hashing per process (PYTHONHASHSEED), which orphaned
    downloaded genomes and the mapping cache on every restart. crc32 is
    stable by specification.
    """
    import zlib

    digest = zlib.crc32((name or "").strip().lower().encode("utf-8"))
    return PSEUDO_TAXID_BASE + (digest % PSEUDO_TAXID_SPAN)
