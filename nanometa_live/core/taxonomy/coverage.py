"""What a watchlist can and cannot actually detect in a given database.

A watchlist states what an operator wants to screen for. Whether the loaded
Kraken2 database can *deliver* that is a separate question, and on a minimized
field database the answer is often no for some entries: taxa are pruned to fit
the RAM budget of a field laptop, so an organism on the watchlist may simply
not exist in the database.

That gap is safety-relevant and was previously invisible. An ALL CLEAR verdict
for an organism the database physically cannot report is not a negative
result -- it is no result -- but it renders identically.

Four outcomes are distinguished, because they need different operator
responses:

``detectable``
    Mapped to a species-level node. Works as intended.
``genus_only``
    The watchlist named a *species* but only a genus or broader node matched,
    so a hit says "something in this genus" rather than "this species", and
    many genera contain harmless commensals. An entry that names a genus or
    family in the first place (``Adenoviridae``, ``Enterovirus``) is not
    listed here -- a broad match is what it asked for, and flagging it would
    train operators to ignore the report.
``ambiguous``
    Several watchlist entries resolve to the *same* database node, so a
    detection cannot say which of them it was. Common on GTDB-derived
    databases, where e.g. every *Shigella* species sits under *Escherichia
    coli*. Previously these silently overwrote one another in the reverse
    lookup, so all but one entry disappeared without a warning.
``absent``
    No mapping at all. The database cannot detect this organism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nanometa_live.core.taxonomy.taxid_mapping import (
        DatabaseTaxonomyIndex, TaxidMappingCollection,
    )

#: Kraken2 rank codes that identify a species or finer. Anything else is a
#: genus-or-broader match for the purposes of this report.
_SPECIES_OR_FINER = ("S",)


@dataclass(frozen=True)
class WatchlistCoverage:
    """How much of a watchlist a database can actually report on."""

    detectable: List[str] = field(default_factory=list)
    genus_only: List[Tuple[str, str]] = field(default_factory=list)
    ambiguous: Dict[str, List[str]] = field(default_factory=dict)
    absent: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.detectable)
            + len(self.genus_only)
            + len(self.absent)
        )

    @property
    def has_gaps(self) -> bool:
        return bool(self.genus_only or self.ambiguous or self.absent)

    def summary(self) -> str:
        """One line for the status area."""
        if not self.total:
            return "No watchlist entries to check"
        parts = [f"{len(self.detectable)}/{self.total} detectable at species level"]
        if self.genus_only:
            parts.append(f"{len(self.genus_only)} genus-only")
        if self.ambiguous:
            parts.append(f"{len(self.ambiguous)} shared node(s)")
        if self.absent:
            parts.append(f"{len(self.absent)} absent from database")
        return "; ".join(parts)

    def warnings(self) -> List[str]:
        """Operator-facing detail, most consequential first.

        ``absent`` leads because it is the one an operator cannot work
        around by reading a result more carefully: there will be no result.
        """
        out: List[str] = []
        if self.absent:
            out.append(
                "Not in this database, so they cannot be detected at all: "
                + ", ".join(sorted(self.absent))
            )
        if self.ambiguous:
            for db_name, names in sorted(self.ambiguous.items()):
                out.append(
                    f"Share one database node ({db_name}), so a detection "
                    f"cannot tell them apart: " + ", ".join(sorted(names))
                )
        if self.genus_only:
            out.append(
                "Matched only at genus level, so a hit indicates the genus "
                "rather than the species: "
                + ", ".join(f"{n} -> {db}" for n, db in sorted(self.genus_only))
            )
        return out


def analyse_coverage(
    collection: "TaxidMappingCollection",
    index: Optional["DatabaseTaxonomyIndex"] = None,
) -> WatchlistCoverage:
    """Classify every mapping in ``collection`` into the four outcomes.

    ``index`` supplies the rank of each matched node. Without it, rank is
    inferred from the matched name -- a single-token name is a genus -- which
    is weaker but still catches the common case.
    """
    from nanometa_live.core.taxonomy.taxid_mapping import MappingConfidence

    detectable: List[str] = []
    genus_only: List[Tuple[str, str]] = []
    absent: List[str] = []
    by_node: Dict[int, List[str]] = {}
    node_names: Dict[int, str] = {}

    for mapping in collection.mappings.values():
        name = mapping.canonical_name
        if (
            mapping.confidence == MappingConfidence.UNMAPPED
            or not mapping.db_taxid
        ):
            absent.append(name)
            continue

        db_name = mapping.db_name or str(mapping.db_taxid)
        by_node.setdefault(mapping.db_taxid, []).append(name)
        node_names[mapping.db_taxid] = db_name

        if _is_species_level(mapping.db_taxid, db_name, index):
            detectable.append(name)
        elif _names_a_species(name):
            genus_only.append((name, db_name))
        else:
            # The entry itself is a genus/family; a broad match is correct.
            detectable.append(name)

    ambiguous = {
        node_names[taxid]: names
        for taxid, names in by_node.items()
        if len(names) > 1
    }
    return WatchlistCoverage(
        detectable=detectable,
        genus_only=genus_only,
        ambiguous=ambiguous,
        absent=absent,
    )


def _names_a_species(entry_name: str) -> bool:
    """Whether a watchlist entry names a species rather than a broader clade.

    A binomial has at least two tokens. Family and higher ranks are single
    tokens, usually with a recognisable suffix.
    """
    tokens = str(entry_name).replace("_", " ").split()
    if len(tokens) < 2:
        return False
    return not tokens[0].lower().endswith(("viridae", "virales", "aceae"))


def _is_species_level(
    db_taxid: int,
    db_name: str,
    index: Optional["DatabaseTaxonomyIndex"],
) -> bool:
    """Whether a matched node identifies a species rather than a clade."""
    if index is not None:
        node = index.by_taxid.get(db_taxid)
        if node is not None and node.rank:
            return node.rank.startswith(_SPECIES_OR_FINER)
    # Fallback: a binomial has at least two tokens; a bare genus has one.
    return len(str(db_name).replace("_", " ").split()) >= 2
