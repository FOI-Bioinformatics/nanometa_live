"""Watchlist file dataclasses (metadata + per-pathogen entry).

Split out of ``watchlist_loader`` for the code-size gate; the loader
re-exports both names, so importers are unaffected.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from nanometa_live.core.config.pathogen_loader import default_alert_threshold


@dataclass
class WatchlistMetadata:
    """Metadata for a watchlist file."""
    id: str  # Unique identifier (filename without extension)
    name: str
    description: str
    source: str  # "builtin", "user", "project"
    file_path: Path
    pathogen_count: int = 0
    version: str = "1.0"
    taxonomy_support: List[str] = field(default_factory=lambda: ["ncbi", "gtdb"])
    categories: List[str] = field(default_factory=list)


@dataclass
class WatchlistPathogenEntry:
    """A pathogen entry from a YAML watchlist file."""
    name: str
    names_alt: List[str] = field(default_factory=list)
    taxid_ncbi: Optional[int] = None
    # Optional taxid in the Kraken2 *database* (GTDB/custom DBs assign their own
    # integers). Carried through to WatchlistEntry.db_taxid for matching +
    # pipeline filtering. NCBI watchlists leave it unset.
    db_taxid: Optional[int] = None
    common_name: Optional[str] = None
    threat_level: str = "moderate"
    bsl_level: Optional[int] = None
    category: Optional[str] = None
    # None means "not stated"; __post_init__ derives it from threat_level via
    # the shared table. A flat default here disagreed with
    # WatchlistEntry.from_dict, so the same entry screened at different
    # thresholds depending on which path loaded it.
    alert_threshold: Optional[int] = None
    action_required: str = "Follow laboratory biosafety protocols"
    notes: str = ""
    # Organism kingdom/type declared by the operator (virus / bacteria /
    # fungi / archaea / parasite / other). Inference from taxonomy is no longer
    # required for grouping.
    organism_type: Optional[str] = None
    # Free-text extra information shown next to the species name (e.g. the toxin
    # a producer secretes). Distinct from ``notes`` (longer context).
    annotation: str = ""

    def __post_init__(self):
        # Derive the threshold only when the entry did not state one, so an
        # operator's explicit value is never overwritten.
        if self.alert_threshold is None:
            self.alert_threshold = default_alert_threshold(self.threat_level)
