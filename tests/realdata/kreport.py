"""A minimal, dependency-free Kraken2 report reader for the real-data tests.

Deliberately separate from ``nanometa_live.core.utils.classification_loaders``.
Those loaders are part of what these tests exercise, so parsing the truth set
with them would let a loader bug hide itself: a report and its assertion would
agree because both came from the same code. This reader implements the Kraken2
report format directly from the specification instead.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    """One line of a Kraken2 report."""

    percent: float
    cumulative_reads: int  # reads at this clade including descendants
    direct_reads: int  # reads assigned directly to this taxon
    rank: str
    taxid: int
    name: str
    #: Nesting depth, from the leading indentation of the name field. Kraken2
    #: encodes the tree this way and nowhere else in the report, so it is the
    #: only way to find a row's parent without consulting the database.
    depth: int = 0


class Report:
    """Parsed Kraken2 report with lookups the assertions need."""

    def __init__(self, rows: list[Row], source: pathlib.Path):
        self.rows = rows
        self.source = source

    @classmethod
    def from_file(cls, path: pathlib.Path) -> "Report":
        rows = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            if len(fields) < 6:
                continue
            raw_name = fields[5]
            # Kraken2 indents by two spaces per level.
            indent = len(raw_name) - len(raw_name.lstrip(" "))
            try:
                rows.append(
                    Row(
                        percent=float(fields[0]),
                        cumulative_reads=int(fields[1]),
                        direct_reads=int(fields[2]),
                        rank=fields[3].strip(),
                        taxid=int(fields[4]),
                        name=raw_name.strip(),
                        depth=indent // 2,
                    )
                )
            except ValueError:
                # Header or malformed line; a real report has neither, and
                # skipping keeps a stray line from failing the whole run.
                continue
        return cls(rows, path)

    def by_taxid(self, taxid: int) -> Row | None:
        for row in self.rows:
            if row.taxid == taxid:
                return row
        return None

    def reads_for(self, taxid: int) -> int:
        """Cumulative reads at a taxon, 0 if the taxon is absent."""
        row = self.by_taxid(taxid)
        return row.cumulative_reads if row else 0

    def by_name(self, name: str) -> Row | None:
        wanted = name.strip().lower()
        for row in self.rows:
            if row.name.lower() == wanted:
                return row
        return None

    def parent_of(self, row: Row) -> Row | None:
        """The nearest preceding row one level shallower.

        Kraken2 writes the tree depth-first, so a row's parent is the closest
        earlier row with a smaller indent.
        """
        try:
            index = self.rows.index(row)
        except ValueError:
            return None
        for candidate in reversed(self.rows[:index]):
            if candidate.depth < row.depth:
                return candidate
        return None

    def ancestor_at_rank(self, row: Row, rank: str) -> Row | None:
        """Walk up to the enclosing row of a given rank, if any."""
        current = self.parent_of(row)
        while current is not None:
            if current.rank == rank:
                return current
            current = self.parent_of(current)
        return None

    def at_rank(self, rank: str) -> list[Row]:
        return [r for r in self.rows if r.rank == rank]

    def species(self) -> list[Row]:
        """Species-rank rows only.

        Uses ``S`` exactly, not ``S1``/``S2``: subspecies rows are nested
        inside their species and counting both double-counts reads.
        """
        return self.at_rank("S")

    @property
    def classified_reads(self) -> int:
        root = self.by_taxid(1)
        return root.cumulative_reads if root else 0

    @property
    def unclassified_reads(self) -> int:
        return self.reads_for(0)

    @property
    def total_reads(self) -> int:
        return self.classified_reads + self.unclassified_reads

    def top_species(self, n: int = 10) -> list[Row]:
        return sorted(self.species(), key=lambda r: r.cumulative_reads, reverse=True)[:n]

    def __repr__(self) -> str:
        return (
            f"<Report {self.source.name}: {len(self.rows)} rows, "
            f"{self.classified_reads} classified>"
        )
