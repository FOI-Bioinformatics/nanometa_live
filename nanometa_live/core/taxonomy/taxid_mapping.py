"""
Taxonomy ID Mapping System for Nanometa Live.

This module provides data structures and logic for mapping NCBI taxonomy IDs
to Kraken2 database taxonomy IDs, supporting GTDB-based databases with custom
IDs and mixed databases.

The mapping system:
- Tracks NCBI taxids (canonical reference) and their database equivalents
- Supports automatic mapping generation via name matching
- Allows manual overrides for unmapped or incorrectly mapped entries
- Persists mappings to JSON for reuse across sessions
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC timestamp, replacing the deprecated stdlib utcnow().

    ``datetime.now(timezone.utc).replace(tzinfo=None)`` is identical in value
    to the old ``utcnow()`` (naive, UTC), so isoformat strings and round-trips
    via ``fromisoformat`` are unchanged.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MappingConfidence(Enum):
    """Confidence level for taxid mappings."""
    EXACT = "exact"              # Exact name match or verified NCBI taxid
    FUZZY = "fuzzy"              # Matched via name normalization
    PARTIAL = "partial"          # Partial name match (genus only)
    MANUAL = "manual"            # User-provided override
    UNMAPPED = "unmapped"        # No mapping found


class DatabaseTaxonomyType(Enum):
    """Type of taxonomy used in the Kraken2 database."""
    NCBI = "ncbi"       # Database uses standard NCBI taxids
    CUSTOM = "custom"   # Database uses custom/arbitrary taxids (e.g., GTDB-based)
    MIXED = "mixed"     # Mixed taxid sources
    UNKNOWN = "unknown"


@dataclass
class AlternativeMatch:
    """A potential alternative match for review."""
    db_taxid: int
    db_name: str
    score: float
    match_method: str
    rank: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "db_taxid": self.db_taxid,
            "db_name": self.db_name,
            "score": self.score,
            "match_method": self.match_method,
            "rank": self.rank
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlternativeMatch":
        """Create from dictionary."""
        return cls(
            db_taxid=data.get("db_taxid", 0),
            db_name=data.get("db_name", ""),
            score=data.get("score", 0.0),
            match_method=data.get("match_method", ""),
            rank=data.get("rank", "")
        )


@dataclass
class TaxidMapping:
    """
    Mapping between NCBI taxid and Kraken2 database taxid.

    This structure tracks the relationship between canonical NCBI
    taxonomy identifiers and the internal IDs used by a specific
    Kraken2 database.
    """
    # Canonical reference (from watchlist)
    ncbi_taxid: int                                    # NCBI taxid (0 if unknown)
    canonical_name: str                                # Scientific name as in watchlist

    # Database-specific mapping
    db_taxid: Optional[int] = None                     # Taxid in current Kraken2 database
    db_name: Optional[str] = None                      # Name as it appears in database

    # Mapping metadata
    confidence: MappingConfidence = MappingConfidence.UNMAPPED
    match_score: float = 0.0                           # 0.0 to 1.0 similarity score
    match_method: str = ""                             # Description of how match was made

    # Alternative matches (for review)
    alternative_matches: List[AlternativeMatch] = field(default_factory=list)

    # Manual override tracking
    manually_verified: bool = False
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    override_reason: Optional[str] = None

    # Timestamps
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def is_mapped(self) -> bool:
        """Check if this entry has a valid database mapping."""
        return self.db_taxid is not None and self.confidence != MappingConfidence.UNMAPPED

    def needs_review(self) -> bool:
        """Check if this mapping should be manually reviewed."""
        if self.manually_verified:
            return False
        return (
            self.confidence in [MappingConfidence.FUZZY, MappingConfidence.PARTIAL] or
            (self.confidence == MappingConfidence.UNMAPPED and len(self.alternative_matches) > 0)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "ncbi_taxid": self.ncbi_taxid,
            "canonical_name": self.canonical_name,
            "db_taxid": self.db_taxid,
            "db_name": self.db_name,
            "confidence": self.confidence.value,
            "match_score": self.match_score,
            "match_method": self.match_method,
            "alternative_matches": [m.to_dict() for m in self.alternative_matches],
            "manually_verified": self.manually_verified,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "override_reason": self.override_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxidMapping":
        """Create from dictionary."""
        return cls(
            ncbi_taxid=data.get("ncbi_taxid", 0),
            canonical_name=data.get("canonical_name", ""),
            db_taxid=data.get("db_taxid"),
            db_name=data.get("db_name"),
            confidence=MappingConfidence(data.get("confidence", "unmapped")),
            match_score=data.get("match_score", 0.0),
            match_method=data.get("match_method", ""),
            alternative_matches=[
                AlternativeMatch.from_dict(m)
                for m in data.get("alternative_matches", [])
            ],
            manually_verified=data.get("manually_verified", False),
            verified_by=data.get("verified_by"),
            verified_at=datetime.fromisoformat(data["verified_at"]) if data.get("verified_at") else None,
            override_reason=data.get("override_reason"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else _utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else _utcnow()
        )


@dataclass
class DatabaseTaxonomyNode:
    """A single node from the Kraken2 database taxonomy."""
    taxid: int
    name: str
    rank: str                                          # S, G, F, O, C, P, D, R, U
    parent_taxid: Optional[int] = None

    # Normalized forms for matching
    name_normalized: str = ""                          # Lowercase, spaces instead of underscores
    name_gtdb_style: str = ""                          # With s__ prefix and underscores

    # Additional metadata from inspect
    clade_reads: int = 0
    direct_reads: int = 0
    abundance_percent: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "taxid": self.taxid,
            "name": self.name,
            "rank": self.rank,
            "parent_taxid": self.parent_taxid,
            "name_normalized": self.name_normalized,
            "name_gtdb_style": self.name_gtdb_style,
            "clade_reads": self.clade_reads,
            "direct_reads": self.direct_reads,
            "abundance_percent": self.abundance_percent
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseTaxonomyNode":
        """Create from dictionary."""
        return cls(
            taxid=data["taxid"],
            name=data["name"],
            rank=data["rank"],
            parent_taxid=data.get("parent_taxid"),
            name_normalized=data.get("name_normalized", ""),
            name_gtdb_style=data.get("name_gtdb_style", ""),
            clade_reads=data.get("clade_reads", 0),
            direct_reads=data.get("direct_reads", 0),
            abundance_percent=data.get("abundance_percent", 0.0),
        )


@dataclass
class DatabaseTaxonomyIndex:
    """
    Index of all taxonomy nodes in a Kraken2 database.

    Built from kraken2-inspect output or taxonomy files.
    Includes optimized caching for frequently-accessed data.
    """
    database_path: str
    database_type: DatabaseTaxonomyType = DatabaseTaxonomyType.UNKNOWN

    # Primary indices
    by_taxid: Dict[int, DatabaseTaxonomyNode] = field(default_factory=dict)
    by_name: Dict[str, List[int]] = field(default_factory=dict)       # name_normalized -> taxids
    by_name_gtdb: Dict[str, List[int]] = field(default_factory=dict)  # gtdb style -> taxids

    # Prefix index for fast searches (2-char prefix -> taxids)
    by_prefix: Dict[str, List[int]] = field(default_factory=dict)

    # Metadata
    total_nodes: int = 0
    species_count: int = 0
    built_at: Optional[datetime] = None
    inspect_file_path: Optional[str] = None

    # Internal caches (not serialized - rebuilt on demand)
    _species_cache: Optional[List[DatabaseTaxonomyNode]] = field(default=None, repr=False)

    def build_prefix_index(self) -> None:
        """Build 2-character prefix index for faster name searches."""
        self.by_prefix.clear()
        for name_lower, taxids in self.by_name.items():
            if len(name_lower) >= 2:
                prefix = name_lower[:2]
                if prefix not in self.by_prefix:
                    self.by_prefix[prefix] = []
                self.by_prefix[prefix].extend(taxids)

        # Also index GTDB names
        for name_gtdb, taxids in self.by_name_gtdb.items():
            if len(name_gtdb) >= 2:
                prefix = name_gtdb[:2]
                if prefix not in self.by_prefix:
                    self.by_prefix[prefix] = []
                self.by_prefix[prefix].extend(taxids)

        # Remove duplicates from each prefix list
        for prefix in self.by_prefix:
            self.by_prefix[prefix] = list(set(self.by_prefix[prefix]))

    def get_by_name(self, name: str) -> List[DatabaseTaxonomyNode]:
        """Find nodes matching a name (tries multiple normalizations)."""
        # Try normalized name
        name_lower = name.lower().replace("_", " ").strip()
        taxids = self.by_name.get(name_lower, [])

        # Try GTDB style
        if not taxids:
            gtdb_name = name.lower().replace(" ", "_")
            taxids = self.by_name_gtdb.get(gtdb_name, [])

        return [self.by_taxid[tid] for tid in taxids if tid in self.by_taxid]

    def search_by_prefix(self, prefix: str, limit: int = 100) -> List[DatabaseTaxonomyNode]:
        """
        Fast prefix-based search for autocomplete.

        Args:
            prefix: At least 2 characters to search for
            limit: Maximum results to return

        Returns:
            List of matching nodes
        """
        if len(prefix) < 2:
            return []

        prefix_key = prefix[:2].lower()
        candidate_taxids = self.by_prefix.get(prefix_key, [])

        if not candidate_taxids:
            return []

        # Filter candidates that actually match the full prefix
        prefix_lower = prefix.lower()
        results = []
        for tid in candidate_taxids:
            if len(results) >= limit:
                break
            node = self.by_taxid.get(tid)
            if node and (node.name_normalized.startswith(prefix_lower) or
                         node.name_gtdb_style.startswith(prefix_lower)):
                results.append(node)

        return results

    def get_species(self) -> List[DatabaseTaxonomyNode]:
        """Get all species-level nodes (cached for performance)."""
        if self._species_cache is None:
            self._species_cache = [node for node in self.by_taxid.values() if node.rank == "S"]
        return self._species_cache

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": "1.0",
            "database_path": self.database_path,
            "database_type": self.database_type.value,
            "total_nodes": self.total_nodes,
            "species_count": self.species_count,
            "built_at": self.built_at.isoformat() if self.built_at else None,
            "inspect_file_path": self.inspect_file_path,
            "nodes": [node.to_dict() for node in self.by_taxid.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseTaxonomyIndex":
        """Reconstruct index from dictionary.

        Rebuilds all lookup indices (by_name, by_name_gtdb, by_prefix)
        from the serialized node list rather than storing them
        redundantly.
        """
        db_type_str = data.get("database_type", "unknown")
        index = cls(
            database_path=data.get("database_path", ""),
            database_type=DatabaseTaxonomyType(db_type_str),
            total_nodes=data.get("total_nodes", 0),
            species_count=data.get("species_count", 0),
            built_at=(
                datetime.fromisoformat(data["built_at"])
                if data.get("built_at") else None
            ),
            inspect_file_path=data.get("inspect_file_path"),
        )

        # Reconstruct nodes and indices
        for node_data in data.get("nodes", []):
            node = DatabaseTaxonomyNode.from_dict(node_data)
            index.by_taxid[node.taxid] = node

            # Rebuild by_name index
            if node.name_normalized:
                index.by_name.setdefault(node.name_normalized, []).append(node.taxid)

            # Rebuild by_name_gtdb index
            if node.name_gtdb_style:
                index.by_name_gtdb.setdefault(node.name_gtdb_style, []).append(node.taxid)

        # Rebuild prefix index
        index.build_prefix_index()

        return index

    def get_by_taxid(self, taxid: int) -> Optional[DatabaseTaxonomyNode]:
        """Get a node by its taxid."""
        return self.by_taxid.get(taxid)

    def get_lineage(self, taxid: int, max_depth: int = 10) -> List[DatabaseTaxonomyNode]:
        """
        Get the taxonomic lineage for a taxid by following parent links.

        Args:
            taxid: The taxid to get lineage for
            max_depth: Maximum depth to traverse (prevents infinite loops)

        Returns:
            List of nodes from root to species (domain -> ... -> species)
        """
        lineage = []
        current_taxid = taxid
        seen = set()

        for _ in range(max_depth):
            if current_taxid in seen or current_taxid is None:
                break
            seen.add(current_taxid)

            node = self.by_taxid.get(current_taxid)
            if not node:
                break

            lineage.append(node)
            current_taxid = node.parent_taxid

            # Stop at root (parent_taxid == 0 or 1 typically)
            if current_taxid is None or current_taxid <= 1:
                break

        # Reverse to get domain -> species order
        lineage.reverse()
        return lineage

    def get_lineage_string(self, taxid: int) -> str:
        """Get a human-readable lineage string for a taxid."""
        lineage = self.get_lineage(taxid)
        if not lineage:
            return ""

        # Map rank codes to names for display
        rank_names = {
            "D": "Domain", "P": "Phylum", "C": "Class", "O": "Order",
            "F": "Family", "G": "Genus", "S": "Species", "S1": "Subspecies",
            "R": "Root", "U": "Unclassified"
        }

        parts = []
        for node in lineage:
            rank_name = rank_names.get(node.rank, node.rank)
            parts.append(f"{rank_name}: {node.name}")

        return " > ".join(parts)


@dataclass
class TaxidMappingCollection:
    """
    Collection of all taxid mappings for a specific database.

    Persisted to JSON for reuse across sessions.
    """
    # Identity
    database_path: str
    database_hash: str = ""                            # Hash of database files for change detection
    database_type: DatabaseTaxonomyType = DatabaseTaxonomyType.UNKNOWN
    watchlist_version: str = ""                        # Version of watchlist used

    # Mappings
    mappings: Dict[int, TaxidMapping] = field(default_factory=dict)  # ncbi_taxid -> mapping

    # Summary statistics
    total_entries: int = 0
    mapped_exact: int = 0
    mapped_fuzzy: int = 0
    mapped_manual: int = 0
    mapped_partial: int = 0
    unmapped: int = 0
    needs_review: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def get_mapping(self, ncbi_taxid: int) -> Optional[TaxidMapping]:
        """Get mapping for an NCBI taxid."""
        return self.mappings.get(ncbi_taxid)

    def get_db_taxid(self, ncbi_taxid: int) -> Optional[int]:
        """Get the database taxid for an NCBI taxid."""
        mapping = self.mappings.get(ncbi_taxid)
        if mapping and mapping.is_mapped():
            return mapping.db_taxid
        return None

    def update_statistics(self) -> None:
        """Recalculate statistics from mappings."""
        self.total_entries = len(self.mappings)
        self.mapped_exact = sum(
            1 for m in self.mappings.values()
            if m.confidence == MappingConfidence.EXACT
        )
        self.mapped_fuzzy = sum(
            1 for m in self.mappings.values()
            if m.confidence == MappingConfidence.FUZZY
        )
        self.mapped_manual = sum(
            1 for m in self.mappings.values()
            if m.confidence == MappingConfidence.MANUAL
        )
        self.mapped_partial = sum(
            1 for m in self.mappings.values()
            if m.confidence == MappingConfidence.PARTIAL
        )
        self.unmapped = sum(
            1 for m in self.mappings.values()
            if m.confidence == MappingConfidence.UNMAPPED
        )
        self.needs_review = sum(
            1 for m in self.mappings.values()
            if m.needs_review()
        )
        self.updated_at = _utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": "1.0",
            "database_path": self.database_path,
            "database_hash": self.database_hash,
            "database_type": self.database_type.value,
            "watchlist_version": self.watchlist_version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "statistics": {
                "total_entries": self.total_entries,
                "mapped_exact": self.mapped_exact,
                "mapped_fuzzy": self.mapped_fuzzy,
                "mapped_manual": self.mapped_manual,
                "mapped_partial": self.mapped_partial,
                "unmapped": self.unmapped,
                "needs_review": self.needs_review
            },
            "mappings": [m.to_dict() for m in self.mappings.values()]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxidMappingCollection":
        """Create from dictionary."""
        # Handle legacy "gtdb" value (renamed to "custom")
        db_type_str = data.get("database_type", "unknown")
        if db_type_str == "gtdb":
            db_type_str = "custom"

        collection = cls(
            database_path=data.get("database_path", ""),
            database_hash=data.get("database_hash", ""),
            database_type=DatabaseTaxonomyType(db_type_str),
            watchlist_version=data.get("watchlist_version", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else _utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else _utcnow()
        )

        # Load statistics
        stats = data.get("statistics", {})
        collection.total_entries = stats.get("total_entries", 0)
        collection.mapped_exact = stats.get("mapped_exact", 0)
        collection.mapped_fuzzy = stats.get("mapped_fuzzy", 0)
        collection.mapped_manual = stats.get("mapped_manual", 0)
        collection.mapped_partial = stats.get("mapped_partial", 0)
        collection.unmapped = stats.get("unmapped", 0)
        collection.needs_review = stats.get("needs_review", 0)

        # Load mappings
        for mapping_data in data.get("mappings", []):
            mapping = TaxidMapping.from_dict(mapping_data)
            collection.mappings[mapping.ncbi_taxid] = mapping

        return collection

    def save(self, filepath: str) -> bool:
        """Save collection to JSON file."""
        try:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump(self.to_dict(), f, indent=2)
            logger.info(f"Saved mapping collection to {filepath}")
            return True
        except (FileNotFoundError, PermissionError, OSError, TypeError, ValueError) as e:
            logger.exception(f"Failed to save mapping collection: {e}")
            return False

    @classmethod
    def load(cls, filepath: str) -> Optional["TaxidMappingCollection"]:
        """Load collection from JSON file."""
        try:
            path = Path(filepath)
            if not path.exists():
                return None
            with open(path, 'r') as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.exception(f"Failed to load mapping collection: {e}")
            return None


def get_database_hash(database_path: str) -> str:
    """
    Calculate a hash for the database to detect changes.

    Uses the hash.k2d file if present, otherwise falls back to
    hashing directory modification times.
    """
    path = Path(database_path)
    hash_file = path / "hash.k2d"

    if hash_file.exists():
        # Hash file content header + size for stability across machines.
        # Using mtime would produce different hashes when copying the DB
        # to another computer, breaking cached mapping lookups.
        stat = hash_file.stat()
        with open(hash_file, 'rb') as f:
            header = f.read(65536)
        content = header + str(stat.st_size).encode()
        return hashlib.md5(content).hexdigest()[:12]

    # Fall back to directory-level hash using path and size
    if path.exists():
        stat = path.stat()
        content = f"{stat.st_size}:{database_path}".encode()
        return hashlib.md5(content).hexdigest()[:12]

    return ""


def get_mapping_cache_path(database_path: str) -> Path:
    """Get the cache file path for a database's mappings.

    The cache lives under ``<data_dir>/mappings/`` where ``data_dir`` is
    whatever the running process selected at startup (the CLI entry
    point in nanometa_live.py exports ``NANOMETA_DATA_DIR`` via
    ``set_data_dir_env`` from a ``--data-dir`` flag or the loaded
    config). This mirrors the ``TaxidMapper._cache_dir`` default at
    line 675 and the readiness checker's lookup path at
    ``readiness_checker.py:265`` so the writer and reader always meet.

    Earlier revisions hardcoded ``Path.home() / ".nanometa"``; that
    left mappings stranded at ``~/.nanometa/mappings/`` while readiness
    looked under the operator-configured ``data_dir``, producing a
    persistent "Taxid mappings not generated" verdict on hosts where
    the two paths differed (typical on a server with
    ``/mnt/<vol>/nanometa_data/`` etc.).
    """
    from nanometa_live.core.utils.paths import get_mappings_dir_from_env

    db_hash = get_database_hash(database_path)
    cache_dir = Path(get_mappings_dir_from_env())
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{db_hash}_mappings.json"


# Singleton instances for easy access
_mapping_collection: Optional[TaxidMappingCollection] = None
_database_index: Optional[DatabaseTaxonomyIndex] = None


def get_mapping_collection() -> Optional[TaxidMappingCollection]:
    """Get the current mapping collection."""
    return _mapping_collection


def set_mapping_collection(collection: TaxidMappingCollection) -> None:
    """Set the current mapping collection."""
    global _mapping_collection
    _mapping_collection = collection


def set_database_index(index: DatabaseTaxonomyIndex) -> None:
    """Set the current database index."""
    global _database_index
    _database_index = index


class TaxidMapper:
    """
    Generate and manage taxid mappings between watchlist and Kraken2 database.

    This is the main entry point for the taxid mapping system. It coordinates
    database indexing, matching strategies, and confidence scoring.

    Usage:
        mapper = TaxidMapper()
        mapper.load_database("/path/to/kraken2/db")

        # Generate mappings for watchlist entries
        collection = mapper.generate_mappings(watchlist_entries)

        # Get mapping for a specific taxid
        db_taxid = collection.get_db_taxid(1392)  # Bacillus anthracis

        # Manual override
        mapper.set_manual_mapping(1392, 45123, "Verified correct species")
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the mapper.

        Args:
            cache_dir: Directory for caching mappings. When unset,
                resolves to ``<data_dir>/mappings`` where data_dir is
                read from the NANOMETA_DATA_DIR env var (set by the
                CLI entry point from ``--data-dir``) or falls back to
                ``~/.nanometa``.
        """
        if cache_dir:
            self._cache_dir = Path(cache_dir)
        else:
            from nanometa_live.core.utils.paths import get_mappings_dir_from_env
            self._cache_dir = Path(get_mappings_dir_from_env())
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._index: Optional[DatabaseTaxonomyIndex] = None
        self._collection: Optional[TaxidMappingCollection] = None
        self._database_path: Optional[str] = None

        # Import here to avoid circular imports
        from nanometa_live.core.taxonomy.database_indexer import get_index_builder
        from nanometa_live.core.watchlist.validation.match_strategies import get_match_strategy
        from nanometa_live.core.watchlist.validation.confidence_scorer import get_confidence_scorer

        self._index_builder = get_index_builder()
        self._match_strategy = get_match_strategy()
        self._scorer = get_confidence_scorer()

    def load_database(
        self,
        database_path: str,
        inspect_file: Optional[str] = None,
        force_rebuild: bool = False
    ) -> bool:
        """
        Load a Kraken2 database for mapping.

        Args:
            database_path: Path to Kraken2 database directory
            inspect_file: Optional path to pre-generated inspect file
            force_rebuild: Force rebuilding the index even if cached

        Returns:
            True if database loaded successfully
        """
        import time

        self._database_path = database_path
        db_hash = get_database_hash(database_path)

        # Use JSON for safe serialization (pickle is not used due to
        # arbitrary code execution risk during deserialization)
        cache_path = self._cache_dir / f"{db_hash}_index.json"

        # Remove any legacy pickle cache files to prevent accidental
        # loading by older code versions
        legacy_pkl = self._cache_dir / f"{db_hash}_index.pkl"
        if legacy_pkl.exists():
            try:
                legacy_pkl.unlink()
                logger.info(f"Removed legacy pickle cache: {legacy_pkl}")
            except OSError as e:
                logger.warning(f"Could not remove legacy pickle cache: {e}")

        index_loaded = False

        if not force_rebuild and cache_path.exists():
            # Load cached index from JSON
            try:
                start_time = time.time()
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise TypeError(
                        f"Cached index has unexpected format: {type(data).__name__}"
                    )
                self._index = DatabaseTaxonomyIndex.from_dict(data)
                load_time = time.time() - start_time
                # Treat an empty by_taxid as a stale or corrupt cache: a
                # prior run may have written a partial index (e.g. crashed
                # mid-build, or serialised before nodes were populated).
                # Silently accepting it would surface every watchlist entry
                # as UNMAPPED ("Not Found") with no way to recover short of
                # manually wiping ~/.nanometa.
                if not self._index.by_taxid:
                    logger.warning(
                        "Cached database index at %s is empty; deleting and "
                        "rebuilding from %s",
                        cache_path, database_path,
                    )
                    try:
                        cache_path.unlink()
                    except OSError as unlink_err:
                        logger.warning(
                            "Could not delete empty cache %s: %s",
                            cache_path, unlink_err,
                        )
                    self._index = None
                    index_loaded = False
                else:
                    logger.info(
                        f"Loaded cached database index: {len(self._index.by_taxid)} nodes "
                        f"in {load_time:.2f}s"
                    )
                    index_loaded = True
            except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                logger.exception(f"Failed to load cached index, rebuilding: {e}")
                index_loaded = False

        if not index_loaded:
            # Build new index from database files
            start_time = time.time()
            self._index = self._index_builder.build_index(database_path, inspect_file)
            build_time = time.time() - start_time

            if self._index:
                logger.info(
                    f"Built database index: {len(self._index.by_taxid)} nodes "
                    f"in {build_time:.2f}s"
                )
                # Save to JSON cache for next time
                try:
                    with open(cache_path, 'w') as f:
                        json.dump(self._index.to_dict(), f)
                    logger.info(f"Saved database index to cache: {cache_path}")
                except (FileNotFoundError, PermissionError, OSError, TypeError, ValueError) as e:
                    logger.exception(f"Failed to cache database index: {e}")

        if self._index is None:
            logger.error(f"Failed to build index for {database_path}")
            return False

        # A built index with zero nodes is structurally indistinguishable
        # from a missing one for downstream callers. Refuse rather than
        # silently produce an all-UNMAPPED collection.
        if not self._index.by_taxid:
            raise RuntimeError(
                f"Database index built from {database_path} contains zero "
                f"taxa. Inspect the database directory for missing or "
                f"unreadable taxonomy files (e.g. inspect.txt, taxo.k2d)."
            )

        # Update global index
        set_database_index(self._index)

        # Try to load existing mappings
        mapping_cache = get_mapping_cache_path(database_path)
        if mapping_cache.exists():
            self._collection = TaxidMappingCollection.load(str(mapping_cache))
            if self._collection:
                set_mapping_collection(self._collection)
                logger.info(f"Loaded cached mappings: {self._collection.total_entries} entries")

        return True

    def generate_mappings(
        self,
        watchlist_entries: List[Dict[str, Any]],
        preserve_manual: bool = True,
        auto_accept_threshold: float = 0.85,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> TaxidMappingCollection:
        """
        Generate mappings for all watchlist entries.

        Args:
            watchlist_entries: List of dicts with 'name' and 'taxid' keys
            preserve_manual: Keep existing manual overrides
            auto_accept_threshold: Auto-accept matches above this score
            progress_callback: Optional callback(current, total, name) for progress updates

        Returns:
            TaxidMappingCollection with generated mappings
        """
        if not self._index or not self._index.by_taxid:
            raise RuntimeError(
                "Database index is not loaded or is empty. Call "
                "load_database() with a valid Kraken2 database before "
                "generating mappings; if the cache file under "
                "~/.nanometa/mappings/ is suspect, rerun with "
                "force_rebuild=True."
            )

        # Create or update collection
        if self._collection is None or not preserve_manual:
            self._collection = TaxidMappingCollection(
                database_path=self._database_path or "",
                database_hash=get_database_hash(self._database_path or ""),
                database_type=self._index.database_type
            )

        total_entries = len(watchlist_entries)

        # Process each entry
        for i, entry in enumerate(watchlist_entries):
            ncbi_taxid = entry.get("taxid") or entry.get("taxid_ncbi", 0)
            name = entry.get("name", "")
            alt_names = entry.get("names_alt", [])

            # Report progress
            if progress_callback:
                progress_callback(i + 1, total_entries, name)

            if not name:
                continue

            # Check for existing manual override
            if preserve_manual and ncbi_taxid in self._collection.mappings:
                existing = self._collection.mappings[ncbi_taxid]
                if existing.manually_verified:
                    logger.debug(f"Preserving manual mapping for {name}")
                    continue

            # Run matching
            match_result = self._match_strategy.match(name, ncbi_taxid, self._index, alt_names=alt_names)

            # Find alternatives (excluding the matched entry itself)
            alternatives = self._match_strategy.find_alternatives(name, self._index, limit=5)
            matched_taxid = match_result.matched_taxid
            alt_count = len([
                a for a in alternatives
                if a[1] > 0.5 and a[0].taxid != matched_taxid
            ])

            # Check if this is a custom database (taxid verification not applicable)
            is_custom = self._index.database_type == DatabaseTaxonomyType.CUSTOM

            # Calculate confidence
            score = self._scorer.calculate_score(
                match_result,
                query_taxid=ncbi_taxid,
                alternative_count=alt_count,
                is_custom_database=is_custom
            )

            # Determine confidence level
            if score.final_score >= auto_accept_threshold * 100:
                confidence = MappingConfidence.EXACT
            elif score.final_score >= 70:
                confidence = MappingConfidence.FUZZY
            elif match_result.matched_node:
                confidence = MappingConfidence.PARTIAL
            else:
                confidence = MappingConfidence.UNMAPPED

            # Create mapping
            mapping = TaxidMapping(
                ncbi_taxid=ncbi_taxid,
                canonical_name=name,
                db_taxid=match_result.matched_taxid,
                db_name=match_result.matched_name,
                confidence=confidence,
                match_score=match_result.score,
                match_method=match_result.match_type.value,
                alternative_matches=[
                    AlternativeMatch(
                        db_taxid=node.taxid,
                        db_name=node.name,
                        score=s,
                        match_method="alternative",
                        rank=node.rank
                    )
                    for node, s in alternatives[:5]
                ]
            )

            self._collection.mappings[ncbi_taxid] = mapping

        # Update statistics
        self._collection.update_statistics()

        # Save to cache
        cache_path = get_mapping_cache_path(self._database_path or "")
        self._collection.save(str(cache_path))

        # Update global collection
        set_mapping_collection(self._collection)

        return self._collection

    def set_manual_mapping(
        self,
        ncbi_taxid: int,
        db_taxid: int,
        reason: str = "",
        verified_by: str = "user"
    ) -> bool:
        """
        Set a manual mapping override.

        Args:
            ncbi_taxid: NCBI taxonomy ID
            db_taxid: Target database taxid
            reason: Reason for the override
            verified_by: Who verified this mapping

        Returns:
            True if mapping was set successfully
        """
        if not self._index:
            logger.error("Database not loaded")
            return False

        if not self._collection:
            logger.error("No mapping collection loaded")
            return False

        # Look up the database node
        node = self._index.get_by_taxid(db_taxid)
        if not node:
            logger.warning(f"Database taxid {db_taxid} not found")
            return False

        # Update or create mapping
        if ncbi_taxid in self._collection.mappings:
            mapping = self._collection.mappings[ncbi_taxid]
            mapping.db_taxid = db_taxid
            mapping.db_name = node.name
            mapping.confidence = MappingConfidence.MANUAL
            mapping.match_score = 1.0
            mapping.match_method = "manual_override"
            mapping.manually_verified = True
            mapping.verified_by = verified_by
            mapping.verified_at = _utcnow()
            mapping.override_reason = reason
            mapping.updated_at = _utcnow()
        else:
            mapping = TaxidMapping(
                ncbi_taxid=ncbi_taxid,
                canonical_name="",  # Unknown
                db_taxid=db_taxid,
                db_name=node.name,
                confidence=MappingConfidence.MANUAL,
                match_score=1.0,
                match_method="manual_override",
                manually_verified=True,
                verified_by=verified_by,
                verified_at=_utcnow(),
                override_reason=reason
            )
            self._collection.mappings[ncbi_taxid] = mapping

        # Update statistics and save
        self._collection.update_statistics()
        cache_path = get_mapping_cache_path(self._database_path or "")
        self._collection.save(str(cache_path))

        return True

    def get_lineage(self, db_taxid: int) -> str:
        """
        Get the taxonomy lineage string for a database taxid.

        Args:
            db_taxid: Database taxonomy ID

        Returns:
            Human-readable lineage string (e.g., "Domain: Bacteria > ... > Species: E. coli")
        """
        if not self._index:
            return ""
        return self._index.get_lineage_string(db_taxid)

    def get_statistics(self) -> Dict[str, Any]:
        """Get current mapping statistics."""
        if not self._collection:
            return {
                "total_entries": 0,
                "mapped_exact": 0,
                "mapped_fuzzy": 0,
                "mapped_manual": 0,
                "mapped_partial": 0,
                "unmapped": 0,
                "needs_review": 0,
                "database_type": "unknown"
            }

        return {
            "total_entries": self._collection.total_entries,
            "mapped_exact": self._collection.mapped_exact,
            "mapped_fuzzy": self._collection.mapped_fuzzy,
            "mapped_manual": self._collection.mapped_manual,
            "mapped_partial": getattr(self._collection, "mapped_partial", 0),
            "unmapped": self._collection.unmapped,
            "needs_review": self._collection.needs_review,
            "database_type": self._collection.database_type.value
        }

    def rescan_database(
        self,
        preserve_manual: bool = True,
        auto_accept_threshold: float = 0.85
    ) -> Dict[str, int]:
        """
        Rescan database and regenerate mappings.

        Args:
            preserve_manual: Keep existing manual overrides
            auto_accept_threshold: Auto-accept score threshold

        Returns:
            Dict with scan results
        """
        if not self._database_path:
            raise RuntimeError("No database loaded")

        # Reload database
        self.load_database(self._database_path, force_rebuild=True)

        # Get current entries to remap
        entries = []
        if self._collection:
            for mapping in self._collection.mappings.values():
                entries.append({
                    "taxid": mapping.ncbi_taxid,
                    "name": mapping.canonical_name
                })

        if not entries:
            return {"new_matches": 0, "preserved": 0, "unmapped": 0}

        old_stats = self.get_statistics()

        # Regenerate mappings
        self.generate_mappings(
            entries,
            preserve_manual=preserve_manual,
            auto_accept_threshold=auto_accept_threshold
        )

        new_stats = self.get_statistics()

        return {
            "new_matches": (
                new_stats["mapped_exact"] + new_stats["mapped_fuzzy"]
            ) - (
                old_stats["mapped_exact"] + old_stats["mapped_fuzzy"]
            ),
            "preserved": new_stats["mapped_manual"],
            "unmapped": new_stats["unmapped"]
        }


# Singleton mapper instance
_mapper: Optional[TaxidMapper] = None


def get_taxid_mapper() -> TaxidMapper:
    """Get the global TaxidMapper instance."""
    global _mapper
    if _mapper is None:
        _mapper = TaxidMapper()
    return _mapper
