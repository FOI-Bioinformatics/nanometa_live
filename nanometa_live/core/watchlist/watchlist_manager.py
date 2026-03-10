"""
Unified Watchlist Manager for Nanometa Live.

This module provides a unified interface for managing species watchlists,
combining the built-in pathogen database with user-defined species of interest.

The WatchlistManager supports:
- Built-in CDC/WHO pathogen categories (toggleable)
- YAML-based watchlist files from multiple locations
- Multi-taxonomy support (NCBI and GTDB)
- User-defined custom species
- Per-species override of thresholds and threat levels
- Enable/disable individual entries without removing them
- Import/export of watchlist configurations

This replaces the separate pathogen_database and species_of_interest systems
with a single, unified approach.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import yaml

from nanometa_live.core.config.pathogen_loader import (
    PathogenDatabase,
    PathogenEntry,
    ThreatLevel,
    BiosaftyLevel,
    get_pathogen_database,
)

logger = logging.getLogger(__name__)

# Import taxonomy and loader (with lazy initialization to avoid circular imports)
_taxonomy_matcher = None
_watchlist_loader = None


def _get_taxonomy_matcher():
    """Lazy import of TaxonomyMatcher."""
    global _taxonomy_matcher
    if _taxonomy_matcher is None:
        from .taxonomy_matcher import get_taxonomy_matcher
        _taxonomy_matcher = get_taxonomy_matcher()
    return _taxonomy_matcher


def _get_watchlist_loader():
    """Lazy import of WatchlistLoader."""
    global _watchlist_loader
    if _watchlist_loader is None:
        from .watchlist_loader import get_watchlist_loader
        _watchlist_loader = get_watchlist_loader()
    return _watchlist_loader


class WatchlistSource(Enum):
    """Source of a watchlist entry."""
    BUILTIN = "builtin"      # From pathogens.yaml
    USER = "user"            # User-defined custom entry
    IMPORTED = "imported"    # Imported from external file
    MIGRATED = "migrated"    # Migrated from legacy species_of_interest


@dataclass
class WatchlistEntry:
    """
    Unified watchlist entry combining pathogen database and user config.

    This dataclass represents a single species being watched, with all
    relevant metadata for alerting and display. Supports both NCBI and GTDB
    taxonomy systems through name-based matching.
    """
    taxid: int  # NCBI taxid (0 if unknown or GTDB-only)
    name: str  # Primary scientific name
    common_name: Optional[str] = None
    threat_level: ThreatLevel = ThreatLevel.MODERATE
    alert_threshold: int = 10
    bsl_level: Optional[BiosaftyLevel] = None
    category: Optional[str] = None
    notes: str = ""
    action_required: str = "Follow laboratory biosafety protocols"
    source: WatchlistSource = WatchlistSource.USER
    enabled: bool = False
    # Multi-taxonomy support
    names_alt: List[str] = field(default_factory=list)  # Alternative names for matching
    watchlist_id: Optional[str] = None  # Which watchlist file this came from (legacy, use watchlist_ids)
    watchlist_ids: Set[str] = field(default_factory=set)  # All contributing watchlists (for multi-source tracking)
    # User overrides (if entry is from builtin but user modified it)
    user_override: bool = False
    original_threshold: Optional[int] = None
    original_threat_level: Optional[ThreatLevel] = None
    # API validation fields
    validated: bool = False
    validation_date: Optional[str] = None  # ISO format datetime
    ncbi_link: Optional[str] = None
    gtdb_link: Optional[str] = None
    lineage: Optional[List[str]] = None
    api_sciname: Optional[str] = None  # Official name from API
    api_commonname: Optional[str] = None
    api_rank: Optional[str] = None
    gtdb_taxonomy: Optional[str] = None  # Full GTDB taxonomy string

    @classmethod
    def from_pathogen_entry(cls, pathogen: PathogenEntry) -> "WatchlistEntry":
        """Create a WatchlistEntry from a PathogenEntry."""
        return cls(
            taxid=pathogen.taxid,
            name=pathogen.name,
            common_name=pathogen.common_name,
            threat_level=pathogen.threat_level,
            alert_threshold=pathogen.alert_threshold,
            bsl_level=pathogen.bsl,
            category=pathogen.category,
            notes=pathogen.notes,
            action_required=pathogen.action_required,
            source=WatchlistSource.BUILTIN,
            enabled=False
        )

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        source: WatchlistSource = WatchlistSource.USER,
        watchlist_id: Optional[str] = None
    ) -> "WatchlistEntry":
        """Create a WatchlistEntry from a dictionary (e.g., from config or YAML)."""
        # Parse threat level
        threat_str = data.get("threat_level", "moderate")
        if isinstance(threat_str, str):
            threat_map = {
                "critical": ThreatLevel.CRITICAL,
                "high": ThreatLevel.HIGH,
                "high_risk": ThreatLevel.HIGH,
                "moderate": ThreatLevel.MODERATE,
                "medium": ThreatLevel.MODERATE,
                "low": ThreatLevel.LOW,
                "info": ThreatLevel.LOW,
            }
            threat_level = threat_map.get(threat_str.lower(), ThreatLevel.MODERATE)
        else:
            threat_level = ThreatLevel.MODERATE

        # Parse BSL level
        bsl_val = data.get("bsl_level") or data.get("bsl")
        bsl_level = None
        if bsl_val:
            try:
                bsl_int = int(bsl_val)
                bsl_map = {1: BiosaftyLevel.BSL1, 2: BiosaftyLevel.BSL2,
                          3: BiosaftyLevel.BSL3, 4: BiosaftyLevel.BSL4}
                bsl_level = bsl_map.get(bsl_int)
            except (ValueError, TypeError):
                pass

        # Default alert threshold based on threat level
        default_thresholds = {
            ThreatLevel.CRITICAL: 5,
            ThreatLevel.HIGH: 10,
            ThreatLevel.MODERATE: 50,
            ThreatLevel.LOW: 100,
        }
        alert_threshold = data.get("alert_threshold", default_thresholds.get(threat_level, 10))

        # Handle taxid - support both 'taxid' and 'taxid_ncbi' keys
        taxid = data.get("taxid") or data.get("taxid_ncbi") or 0
        try:
            taxid = int(taxid)
        except (ValueError, TypeError):
            taxid = 0

        # Handle alternative names for multi-taxonomy support
        names_alt = data.get("names_alt", [])
        if isinstance(names_alt, str):
            names_alt = [names_alt]

        # Handle lineage
        lineage = data.get("lineage")
        if isinstance(lineage, str):
            lineage = [lineage]

        return cls(
            taxid=taxid,
            name=data.get("name", "Unknown"),
            common_name=data.get("common_name"),
            threat_level=threat_level,
            alert_threshold=int(alert_threshold),
            bsl_level=bsl_level,
            category=data.get("category", "Custom"),
            notes=data.get("notes", ""),
            action_required=data.get("action_required", "Follow laboratory biosafety protocols"),
            source=source,
            enabled=data.get("enabled", False),
            names_alt=names_alt,
            watchlist_id=watchlist_id,
            watchlist_ids=set(data.get("watchlist_ids", [])) if data.get("watchlist_ids") else set(),
            # Validation fields
            validated=data.get("validated", False),
            validation_date=data.get("validation_date"),
            ncbi_link=data.get("ncbi_link"),
            gtdb_link=data.get("gtdb_link"),
            lineage=lineage,
            api_sciname=data.get("api_sciname"),
            api_commonname=data.get("api_commonname"),
            api_rank=data.get("api_rank"),
            gtdb_taxonomy=data.get("gtdb_taxonomy"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "taxid": self.taxid,
            "name": self.name,
            "common_name": self.common_name,
            "threat_level": self.threat_level.value,
            "alert_threshold": self.alert_threshold,
            "bsl_level": self.bsl_level.value if self.bsl_level else None,
            "category": self.category,
            "notes": self.notes,
            "action_required": self.action_required,
            "source": self.source.value,
            "enabled": self.enabled,
            # Always include validation fields for UI state
            "validated": self.validated,
            "ncbi_link": self.ncbi_link,
            "gtdb_link": self.gtdb_link,
        }
        # Include alt names if present
        if self.names_alt:
            result["names_alt"] = self.names_alt
        if self.watchlist_id:
            result["watchlist_id"] = self.watchlist_id
        if self.watchlist_ids:
            result["watchlist_ids"] = list(self.watchlist_ids)
        # Include additional validation fields if validated
        if self.validated:
            result["validation_date"] = self.validation_date
            result["lineage"] = self.lineage
            result["api_sciname"] = self.api_sciname
            result["api_commonname"] = self.api_commonname
            result["api_rank"] = self.api_rank
            result["gtdb_taxonomy"] = self.gtdb_taxonomy
        return result

    def to_pathogen_entry(self) -> PathogenEntry:
        """Convert back to PathogenEntry for compatibility."""
        return PathogenEntry(
            taxid=self.taxid,
            name=self.name,
            common_name=self.common_name,
            threat_level=self.threat_level,
            bsl=self.bsl_level,
            category=self.category,
            notes=self.notes,
            alert_threshold=self.alert_threshold,
            action_required=self.action_required
        )


# Built-in category definitions
BUILTIN_CATEGORIES = {
    # Federal Select Agent categories (cdc_bioterrorism.yaml)
    "select_agents_tier1": {
        "name": "Select Agents (Tier 1)",
        "description": "Highest risk select agents and toxins",
        "filter": lambda p: p.category and "Tier1" in p.category
    },
    "select_agents_hhs": {
        "name": "HHS Select Agents",
        "description": "HHS-regulated select agents",
        "filter": lambda p: p.category and "HHS-SA" in p.category
    },
    "select_agents_overlap": {
        "name": "Overlap Select Agents",
        "description": "USDA/HHS overlap select agents",
        "filter": lambda p: p.category and "Overlap-SA" in p.category
    },
    # Legacy CDC categories (pathogens.yaml built-in database)
    "cdc_category_a": {
        "name": "CDC Category A",
        "description": "Highest priority bioterrorism agents (legacy)",
        "filter": lambda p: p.category == "CDC-A"
    },
    "cdc_category_b": {
        "name": "CDC Category B",
        "description": "Second highest priority agents (legacy)",
        "filter": lambda p: p.category == "CDC-B"
    },
    "cdc_category_c": {
        "name": "CDC Category C",
        "description": "Emerging threat agents (legacy)",
        "filter": lambda p: p.category == "CDC-C"
    },
    "who_priority": {
        "name": "WHO Priority Pathogens",
        "description": "WHO 2024 priority pathogens for antimicrobial resistance",
        "filter": lambda p: p.category and "WHO" in p.category
    },
    "foodborne": {
        "name": "Foodborne Pathogens",
        "description": "Common food safety pathogens",
        "filter": lambda p: p.category == "Foodborne"
    },
    "critical_only": {
        "name": "Critical Threats Only",
        "description": "BSL-3/4 agents requiring immediate action",
        "filter": lambda p: p.threat_level == ThreatLevel.CRITICAL
    },
    "high_risk": {
        "name": "High Risk",
        "description": "High and critical threat pathogens",
        "filter": lambda p: p.threat_level in [ThreatLevel.CRITICAL, ThreatLevel.HIGH]
    }
}


class WatchlistManager:
    """
    Unified manager for species watchlists.

    Combines the built-in pathogen database with user-defined species
    into a single, manageable watchlist system. Supports both NCBI and
    GTDB taxonomy systems through name-based matching.

    Usage:
        manager = WatchlistManager()
        manager.load_config(config)  # Load from app config

        # Get all active entries
        entries = manager.get_active_entries()

        # Check for matches
        alerts = manager.check_organisms(detected_organisms)
    """

    def __init__(self):
        """Initialize the watchlist manager."""
        self._entries: Dict[int, WatchlistEntry] = {}
        self._name_index: Dict[str, int] = {}  # name.lower() -> taxid
        self._enabled_categories: Set[str] = set()
        self._enabled_watchlists: Set[str] = set()  # YAML watchlist IDs
        self._pathogen_db: Optional[PathogenDatabase] = None
        self._project_dir: Optional[Path] = None
        self._taxonomy_mode: str = "auto"  # "auto", "ncbi", "gtdb"
        self._loaded = False

    def load_config(self, config: Dict[str, Any]) -> None:
        """
        Load watchlist configuration from app config.

        Supports:
        - New unified YAML-based watchlist files
        - Legacy built-in categories (from pathogens.yaml)
        - Legacy species_of_interest format

        Args:
            config: Application configuration dictionary
        """
        # Preserve watchlists that were already enabled via enable_watchlist()
        # before load_config was called (race condition with Dash callbacks).
        pre_enabled = set(self._enabled_watchlists)

        self._entries = {}
        self._name_index = {}
        self._enabled_watchlists = set()

        # Set project directory for custom watchlist discovery
        project_dir = config.get("results_output_directory") or config.get("main_dir")
        if project_dir:
            self._project_dir = Path(project_dir)
            loader = _get_watchlist_loader()
            loader.set_project_dir(self._project_dir)

        # Get or create pathogen database (for legacy support)
        self._pathogen_db = get_pathogen_database()

        # Load watchlist config (new format)
        watchlist_config = config.get("watchlist", {})

        # Set taxonomy mode
        self._taxonomy_mode = watchlist_config.get("taxonomy_mode", "auto")

        if watchlist_config.get("enabled", True):
            # Load YAML-based watchlists first (new system)
            builtin_watchlists = watchlist_config.get("builtin", [])
            if builtin_watchlists:
                self._load_yaml_watchlists(builtin_watchlists)

            # Load custom YAML files from config
            custom_files = watchlist_config.get("custom_files", [])
            for file_path in custom_files:
                self._load_custom_yaml_file(file_path)

            # Do NOT load any watchlists by default - user must enable via Quick Enable or toggles
            # This ensures a clean slate at startup per user request

            # Load custom entries from inline config
            custom_entries = watchlist_config.get("custom", [])
            for entry_data in custom_entries:
                self._add_entry_from_dict(entry_data, WatchlistSource.USER)

            # Apply overrides
            overrides = watchlist_config.get("overrides", [])
            for override in overrides:
                self._apply_override(override)

        # Handle legacy species_of_interest (backward compatibility)
        species_of_interest = config.get("species_of_interest", [])
        if species_of_interest and not watchlist_config.get("custom"):
            logger.info(f"Migrating {len(species_of_interest)} legacy species_of_interest entries")
            for species in species_of_interest:
                self._add_entry_from_dict(species, WatchlistSource.MIGRATED)

        # Re-enable watchlists that were activated before load_config ran.
        # This handles the race condition where enable_watchlist() is called
        # by a Dash callback before load_config() runs in another callback.
        if pre_enabled:
            for wl_id in pre_enabled:
                if wl_id not in self._enabled_watchlists:
                    self.enable_watchlist(wl_id)
            logger.info(f"Re-enabled {len(pre_enabled)} pre-existing watchlists: {pre_enabled}")

        self._loaded = True
        logger.info(f"WatchlistManager loaded {len(self._entries)} entries "
                   f"(taxonomy mode: {self._taxonomy_mode})")

    def _load_yaml_watchlists(self, watchlist_ids: List[str]) -> None:
        """Load entries from YAML watchlist files."""
        loader = _get_watchlist_loader()

        for watchlist_id in watchlist_ids:
            try:
                pathogens = loader.load_watchlist(watchlist_id)
                count = 0
                for p in pathogens:
                    entry_data = {
                        "name": p.name,
                        "names_alt": p.names_alt,
                        "taxid_ncbi": p.taxid_ncbi,
                        "common_name": p.common_name,
                        "threat_level": p.threat_level,
                        "bsl_level": p.bsl_level,
                        "category": p.category,
                        "alert_threshold": p.alert_threshold,
                        "action_required": p.action_required,
                        "notes": p.notes,
                        "enabled": True,
                    }
                    self._add_entry_from_dict(
                        entry_data,
                        WatchlistSource.BUILTIN,
                        watchlist_id=watchlist_id
                    )
                    count += 1

                self._enabled_watchlists.add(watchlist_id)
                logger.info(f"Loaded {count} entries from watchlist: {watchlist_id}")

            except Exception as e:
                logger.warning(f"Failed to load watchlist {watchlist_id}: {e}")

    def _load_custom_yaml_file(self, file_path: str) -> None:
        """Load a custom YAML watchlist file by path."""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Custom watchlist file not found: {file_path}")
            return

        loader = _get_watchlist_loader()
        is_valid, errors = loader.validate_file(path)

        if not is_valid:
            logger.warning(f"Invalid watchlist file {file_path}: {errors}")
            raise ValueError(f"Invalid watchlist: {'; '.join(errors)}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            pathogens = data.get("pathogens", [])
            watchlist_id = path.stem

            for p_data in pathogens:
                self._add_entry_from_dict(
                    p_data,
                    WatchlistSource.IMPORTED,
                    watchlist_id=watchlist_id
                )

            self._enabled_watchlists.add(watchlist_id)
            logger.info(f"Loaded {len(pathogens)} entries from custom file: {file_path}")

        except Exception as e:
            logger.error(f"Error loading custom watchlist {file_path}: {e}")

    def _load_builtin_categories(self, categories: List[str]) -> None:
        """Load entries from built-in pathogen database by category."""
        if not self._pathogen_db:
            return

        all_pathogens = self._pathogen_db.get_all_pathogens()

        for cat_key in categories:
            if cat_key not in BUILTIN_CATEGORIES:
                logger.warning(f"Unknown builtin category: {cat_key}")
                continue

            self._enabled_categories.add(cat_key)
            cat_filter = BUILTIN_CATEGORIES[cat_key]["filter"]

            for taxid, pathogen in all_pathogens.items():
                if cat_filter(pathogen):
                    if taxid not in self._entries:
                        entry = WatchlistEntry.from_pathogen_entry(pathogen)
                        entry.watchlist_id = cat_key  # Set watchlist_id for filtering
                        entry.watchlist_ids = {cat_key}  # Initialize watchlist_ids set
                        self._entries[taxid] = entry
                        self._name_index[pathogen.name.lower()] = taxid
                    else:
                        # Entry already exists - add this category as a source
                        self._entries[taxid].watchlist_ids.add(cat_key)

    def _add_entry_from_dict(
        self,
        data: Dict[str, Any],
        source: WatchlistSource,
        watchlist_id: Optional[str] = None
    ) -> None:
        """Add an entry from dictionary data."""
        if "taxid" not in data and "taxid_ncbi" not in data and "name" not in data:
            logger.warning("Watchlist entry missing both taxid and name, skipping")
            return

        entry = WatchlistEntry.from_dict(data, source, watchlist_id=watchlist_id)

        # Initialize watchlist_ids from watchlist_id
        if watchlist_id:
            entry.watchlist_ids = {watchlist_id}

        # If taxid exists, use it as key
        if entry.taxid:
            if entry.taxid in self._entries:
                # MERGE: Entry already exists from another watchlist
                existing = self._entries[entry.taxid]

                # Add new watchlist_id to the set
                if watchlist_id:
                    existing.watchlist_ids.add(watchlist_id)

                # Keep higher threat level (more severe)
                if entry.threat_level.value > existing.threat_level.value:
                    existing.threat_level = entry.threat_level

                # Keep lower threshold (more sensitive alerting)
                existing.alert_threshold = min(existing.alert_threshold, entry.alert_threshold)

                # Merge alternative names
                for alt_name in entry.names_alt:
                    if alt_name not in existing.names_alt:
                        existing.names_alt.append(alt_name)
                        self._name_index[alt_name.lower()] = entry.taxid

                # If incoming entry is enabled (e.g. from enable_watchlist),
                # also enable existing entry for consistent UX
                if entry.enabled:
                    existing.enabled = True

                # Check if this is a user override of a builtin
                if existing.source == WatchlistSource.BUILTIN and source != WatchlistSource.BUILTIN:
                    existing.user_override = True
                    if existing.original_threshold is None:
                        existing.original_threshold = existing.alert_threshold
                    if existing.original_threat_level is None:
                        existing.original_threat_level = existing.threat_level

                # Don't overwrite - we merged into existing
                return

            # New entry - add it
            self._entries[entry.taxid] = entry
            if entry.name:
                self._name_index[entry.name.lower()] = entry.taxid
                # Also index alternative names
                for alt_name in entry.names_alt:
                    self._name_index[alt_name.lower()] = entry.taxid
        elif entry.name:
            # Name-only entry (no taxid) - use hash of name as pseudo-taxid
            pseudo_taxid = hash(entry.name.lower()) % (10**9)

            if pseudo_taxid in self._entries:
                # MERGE: Entry already exists
                existing = self._entries[pseudo_taxid]
                if watchlist_id:
                    existing.watchlist_ids.add(watchlist_id)
                if entry.threat_level.value > existing.threat_level.value:
                    existing.threat_level = entry.threat_level
                existing.alert_threshold = min(existing.alert_threshold, entry.alert_threshold)
                # Preserve existing enabled state (don't force enable on merge)
                return

            entry.taxid = pseudo_taxid
            self._entries[pseudo_taxid] = entry
            self._name_index[entry.name.lower()] = pseudo_taxid
            # Also index alternative names
            for alt_name in entry.names_alt:
                self._name_index[alt_name.lower()] = pseudo_taxid

    def _apply_override(self, override: Dict[str, Any]) -> None:
        """Apply an override to an existing entry."""
        taxid = override.get("taxid")
        if not taxid or taxid not in self._entries:
            return

        entry = self._entries[taxid]

        # Store original values if not already overridden
        if not entry.user_override:
            entry.original_threshold = entry.alert_threshold
            entry.original_threat_level = entry.threat_level
            entry.user_override = True

        # Apply overrides
        if "alert_threshold" in override:
            entry.alert_threshold = int(override["alert_threshold"])
        if "threat_level" in override:
            threat_str = override["threat_level"]
            threat_map = {
                "critical": ThreatLevel.CRITICAL,
                "high": ThreatLevel.HIGH,
                "moderate": ThreatLevel.MODERATE,
                "low": ThreatLevel.LOW,
            }
            entry.threat_level = threat_map.get(threat_str.lower(), entry.threat_level)
        if "enabled" in override:
            entry.enabled = override["enabled"]

    def get_all_entries(self) -> Dict[int, WatchlistEntry]:
        """Get all watchlist entries (including disabled)."""
        return self._entries.copy()

    def get_active_entries(self) -> Dict[int, WatchlistEntry]:
        """Get only enabled watchlist entries."""
        return {k: v for k, v in self._entries.items() if v.enabled}

    def get_entry_by_taxid(self, taxid: int) -> Optional[WatchlistEntry]:
        """Get a specific entry by taxonomy ID."""
        return self._entries.get(taxid)

    def get_entry_by_name(self, name: str) -> Optional[WatchlistEntry]:
        """Get a specific entry by name (case-insensitive)."""
        taxid = self._name_index.get(name.lower())
        if taxid:
            return self._entries.get(taxid)

        # Try partial match
        name_lower = name.lower()
        for entry_name, entry_taxid in self._name_index.items():
            if name_lower in entry_name:
                return self._entries.get(entry_taxid)

        return None

    def get_entries_by_threat_level(self, level: ThreatLevel) -> List[WatchlistEntry]:
        """Get all entries of a specific threat level."""
        return [e for e in self._entries.values() if e.threat_level == level and e.enabled]

    def get_critical_entries(self) -> List[WatchlistEntry]:
        """Get all critical threat level entries."""
        return self.get_entries_by_threat_level(ThreatLevel.CRITICAL)

    def check_organisms(
        self,
        detected_organisms: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Check detected organisms against the watchlist.

        Uses TaxonomyMatcher for multi-taxonomy support (NCBI and GTDB).

        Args:
            detected_organisms: List of dicts with 'taxid', 'name', 'reads', 'abundance'

        Returns:
            List of alert dictionaries for matched organisms exceeding thresholds
        """
        alerts = []
        active_entries = self.get_active_entries()
        matcher = _get_taxonomy_matcher()

        for organism in detected_organisms:
            taxid = organism.get("taxid")
            name = organism.get("name", "").strip()
            reads = organism.get("reads", 0)

            # Try to find matching entry using multi-taxonomy matching
            entry = None
            best_score = 0.0

            # First try exact taxid match (NCBI only)
            if taxid and taxid in active_entries:
                entry = active_entries[taxid]
                best_score = 1.0
            else:
                # Use TaxonomyMatcher for name-based matching
                for e in active_entries.values():
                    score = matcher.match_organism(
                        detected=organism,
                        entry_name=e.name,
                        entry_alt_names=e.names_alt,
                        entry_taxid=e.taxid if e.taxid else None
                    )
                    if score > best_score:
                        best_score = score
                        entry = e

            # Only consider matches above threshold (0.7)
            if entry and best_score >= 0.7 and reads >= entry.alert_threshold:
                alerts.append({
                    "taxid": entry.taxid,
                    "name": entry.name,
                    "common_name": entry.common_name,
                    "reads": reads,
                    "abundance": organism.get("abundance", 0.0),
                    "threat_level": entry.threat_level.value,
                    "bsl": entry.bsl_level.value if entry.bsl_level else None,
                    "category": entry.category,
                    "notes": entry.notes,
                    "action_required": entry.action_required,
                    "source": entry.source.value,
                    "threshold": entry.alert_threshold,
                    "match_score": best_score,
                    "detected_name": name,
                })

        # Sort by threat level (critical first)
        threat_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
        alerts.sort(key=lambda x: threat_order.get(x.get("threat_level", "low"), 4))

        return alerts

    def add_custom_entry(self, entry_data: Dict[str, Any]) -> WatchlistEntry:
        """Add a custom entry to the watchlist."""
        self._add_entry_from_dict(entry_data, WatchlistSource.USER)
        taxid = entry_data.get("taxid") or hash(entry_data.get("name", "").lower()) % (10**9)
        return self._entries.get(taxid)

    def remove_entry(self, taxid: int) -> bool:
        """Remove an entry from the watchlist."""
        if taxid in self._entries:
            entry = self._entries[taxid]
            # Don't allow removing builtin entries, just disable them
            if entry.source == WatchlistSource.BUILTIN:
                entry.enabled = False
                return True
            else:
                del self._entries[taxid]
                # Remove from name index
                self._name_index = {k: v for k, v in self._name_index.items() if v != taxid}
                return True
        return False

    def toggle_entry(self, taxid: int, enabled: bool) -> bool:
        """Enable or disable an entry."""
        if taxid in self._entries:
            self._entries[taxid].enabled = enabled
            return True
        return False

    def toggle_category(self, category: str, enabled: bool) -> int:
        """Enable or disable all entries in a category."""
        if category not in BUILTIN_CATEGORIES:
            return 0

        count = 0
        cat_filter = BUILTIN_CATEGORIES[category]["filter"]

        for entry in self._entries.values():
            # Convert to pathogen entry for filter check
            if entry.source == WatchlistSource.BUILTIN:
                pathogen = entry.to_pathogen_entry()
                if cat_filter(pathogen):
                    entry.enabled = enabled
                    count += 1

        if enabled:
            self._enabled_categories.add(category)
        else:
            self._enabled_categories.discard(category)

        return count

    def get_enabled_categories(self) -> Set[str]:
        """Get the set of enabled builtin categories."""
        return self._enabled_categories.copy()

    # -------------------------------------------------------------------------
    # New methods for YAML-based watchlists and multi-taxonomy support
    # -------------------------------------------------------------------------

    def set_taxonomy_mode(self, mode: str) -> None:
        """
        Set the taxonomy matching mode.

        Args:
            mode: "auto" (detect from data), "ncbi", or "gtdb"
        """
        if mode in ("auto", "ncbi", "gtdb"):
            self._taxonomy_mode = mode
            matcher = _get_taxonomy_matcher()
            if mode == "ncbi":
                from .taxonomy_matcher import TaxonomyType
                matcher.taxonomy_type = TaxonomyType.NCBI
            elif mode == "gtdb":
                from .taxonomy_matcher import TaxonomyType
                matcher.taxonomy_type = TaxonomyType.GTDB
            else:
                from .taxonomy_matcher import TaxonomyType
                matcher.taxonomy_type = TaxonomyType.UNKNOWN

    def get_taxonomy_mode(self) -> str:
        """Get the current taxonomy matching mode."""
        return self._taxonomy_mode

    def get_taxonomy_indicator(self) -> str:
        """Get human-readable taxonomy indicator for UI display."""
        matcher = _get_taxonomy_matcher()
        return matcher.get_taxonomy_indicator()

    def detect_taxonomy_from_report(self, report_path: str) -> str:
        """
        Auto-detect taxonomy from a Kraken2 report file.

        Args:
            report_path: Path to a Kraken2 report file

        Returns:
            Detected taxonomy type ("ncbi", "gtdb", "mixed", or "unknown")
        """
        matcher = _get_taxonomy_matcher()
        taxonomy_type = matcher.detect_taxonomy_from_report(report_path)
        return taxonomy_type.value

    def get_available_watchlists(self) -> List[Dict[str, Any]]:
        """
        Get all available watchlist files (builtin, user, project).

        Returns:
            List of watchlist metadata dicts with:
            - id: Watchlist identifier
            - name: Display name
            - description: Description
            - source: "builtin", "user", or "project"
            - pathogen_count: Number of pathogens
            - enabled: Whether this watchlist is currently enabled
        """
        loader = _get_watchlist_loader()
        if self._project_dir:
            loader.set_project_dir(self._project_dir)

        watchlists = loader.discover_watchlists()

        result = []
        for wl in watchlists:
            result.append({
                "id": wl.id,
                "name": wl.name,
                "description": wl.description,
                "source": wl.source,
                "pathogen_count": wl.pathogen_count,
                "categories": wl.categories,
                "enabled": wl.id in self._enabled_watchlists,
            })

        return result

    def enable_watchlist(self, watchlist_id: str) -> int:
        """
        Enable a watchlist by loading all its entries.

        Args:
            watchlist_id: ID of the watchlist to enable

        Returns:
            Number of entries added
        """
        if watchlist_id in self._enabled_watchlists:
            return 0  # Already enabled

        loader = _get_watchlist_loader()
        pathogens = loader.load_watchlist(watchlist_id)

        count = 0
        for p in pathogens:
            entry_data = {
                "name": p.name,
                "names_alt": p.names_alt,
                "taxid": p.taxid_ncbi,
                "taxid_ncbi": p.taxid_ncbi,
                "common_name": p.common_name,
                "threat_level": p.threat_level,
                "bsl_level": p.bsl_level,
                "category": p.category,
                "alert_threshold": p.alert_threshold,
                "action_required": p.action_required,
                "notes": p.notes,
                "enabled": True,
            }
            self._add_entry_from_dict(
                entry_data,
                WatchlistSource.BUILTIN,
                watchlist_id=watchlist_id
            )
            count += 1

        self._enabled_watchlists.add(watchlist_id)
        logger.info(f"Enabled watchlist {watchlist_id}: {count} entries")
        return count

    def disable_watchlist(self, watchlist_id: str) -> int:
        """
        Disable a watchlist by removing its contribution from entries.

        If an entry has multiple watchlist sources, only this watchlist's
        contribution is removed. The entry remains active if other sources exist.

        Args:
            watchlist_id: ID of the watchlist to disable

        Returns:
            Number of entries affected
        """
        if watchlist_id not in self._enabled_watchlists:
            return 0  # Already disabled

        count = 0
        entries_to_remove = []

        for taxid, entry in list(self._entries.items()):
            # Check both legacy watchlist_id and new watchlist_ids set
            has_this_watchlist = (
                watchlist_id in entry.watchlist_ids or
                entry.watchlist_id == watchlist_id
            )

            if has_this_watchlist:
                # Remove this watchlist from the entry's sources
                entry.watchlist_ids.discard(watchlist_id)
                if entry.watchlist_id == watchlist_id:
                    entry.watchlist_id = None

                count += 1

                # Check if entry still has other sources
                if not entry.watchlist_ids:
                    # No remaining sources - remove entry from table
                    # Entry will be re-added when watchlist is enabled again
                    entries_to_remove.append(taxid)
                # else: Entry still active from other watchlists

        # Remove entries with no remaining sources
        for taxid in entries_to_remove:
            del self._entries[taxid]
            self._name_index = {k: v for k, v in self._name_index.items() if v != taxid}

        self._enabled_watchlists.discard(watchlist_id)
        logger.info(f"Disabled watchlist {watchlist_id}: {count} entries affected")
        return count

    def get_enabled_watchlists(self) -> Set[str]:
        """Get the set of enabled watchlist IDs."""
        return self._enabled_watchlists.copy()

    def get_entries_by_watchlist(self, watchlist_id: str) -> List[WatchlistEntry]:
        """Get all entries that include this watchlist as a source."""
        return [
            e for e in self._entries.values()
            if watchlist_id in e.watchlist_ids or e.watchlist_id == watchlist_id
        ]

    def get_watchlist_pathogens_preview(self, watchlist_id: str) -> List[Dict[str, Any]]:
        """
        Load pathogens directly from YAML for display (without enabling).

        Unlike get_entries_by_watchlist(), this loads directly from the YAML file
        without requiring the watchlist to be enabled. Used for showing watchlist
        contents in the expandable UI sections.

        Args:
            watchlist_id: ID of the watchlist to preview

        Returns:
            List of pathogen dicts with display-relevant fields
        """
        loader = _get_watchlist_loader()
        try:
            pathogens = loader.load_watchlist(watchlist_id)
        except Exception as e:
            logger.warning(f"Failed to load watchlist preview for {watchlist_id}: {e}")
            return []

        result = []
        for p in pathogens:
            # Check if entry exists in active _entries for enabled status
            existing = None
            if p.taxid_ncbi:
                existing = self._entries.get(p.taxid_ncbi)
            if not existing:
                # Try by name hash for name-only entries
                pseudo_taxid = hash(p.name.lower()) % (10**9)
                existing = self._entries.get(pseudo_taxid)

            result.append({
                "taxid": p.taxid_ncbi or 0,
                "name": p.name,
                "common_name": p.common_name,
                "threat_level": p.threat_level,
                "alert_threshold": p.alert_threshold,
                "enabled": existing.enabled if existing else False,
                "watchlist_id": watchlist_id,
            })

        return result

    def get_entries_with_toggle_state(self) -> List[Dict[str, Any]]:
        """
        Get all entries with their toggle (enabled/disabled) state.

        Returns:
            List of entry dicts with toggle information for UI display
        """
        result = []
        for entry in self._entries.values():
            entry_dict = entry.to_dict()
            entry_dict["can_remove"] = entry.source != WatchlistSource.BUILTIN
            entry_dict["can_toggle"] = True
            entry_dict["threat_level_display"] = entry.threat_level.value.title()
            entry_dict["bsl_display"] = f"BSL-{entry.bsl_level.value}" if entry.bsl_level else "N/A"
            result.append(entry_dict)

        # Sort by threat level, then name
        threat_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
        result.sort(key=lambda x: (
            threat_order.get(x.get("threat_level", "low"), 4),
            x.get("name", "")
        ))

        return result

    def update_entry_threshold(self, taxid: int, threshold: int) -> bool:
        """
        Update the alert threshold for an entry.

        Args:
            taxid: Taxonomy ID of the entry
            threshold: New alert threshold

        Returns:
            True if updated successfully
        """
        if taxid not in self._entries:
            return False

        entry = self._entries[taxid]

        # Store original if not already overridden
        if not entry.user_override:
            entry.original_threshold = entry.alert_threshold
            entry.user_override = True

        entry.alert_threshold = threshold
        return True

    def export_config(self) -> Dict[str, Any]:
        """Export the current watchlist configuration."""
        custom_entries = []
        overrides = []

        for entry in self._entries.values():
            if entry.source in [WatchlistSource.USER, WatchlistSource.MIGRATED, WatchlistSource.IMPORTED]:
                custom_entries.append(entry.to_dict())
            elif entry.user_override:
                overrides.append({
                    "taxid": entry.taxid,
                    "alert_threshold": entry.alert_threshold,
                    "threat_level": entry.threat_level.value,
                    "enabled": entry.enabled,
                })

        return {
            "enabled": True,
            "taxonomy_mode": self._taxonomy_mode,
            "builtin": list(self._enabled_watchlists),  # New YAML-based watchlists
            "include_builtin": list(self._enabled_categories),  # Legacy categories
            "custom": custom_entries,
            "overrides": overrides,
        }

    # -------------------------------------------------------------------------
    # API Validation Methods
    # -------------------------------------------------------------------------

    def validate_entry_via_api(
        self,
        taxid: int,
        use_ncbi: bool = True,
        use_gtdb: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate a watchlist entry by querying NCBI and/or GTDB APIs.

        Args:
            taxid: Taxonomy ID of the entry to validate
            use_ncbi: Whether to query NCBI API
            use_gtdb: Whether to query GTDB API

        Returns:
            Dict with validation results:
            - success: True if at least one API returned results
            - ncbi_found: True if found in NCBI
            - gtdb_found: True if found in GTDB
            - entry: Updated WatchlistEntry (or None if not found)
        """
        from datetime import datetime

        # Lazy import to avoid circular dependency
        try:
            from nanometa_live.core.taxonomy.taxonomy_api import (
                get_ncbi_client,
                get_gtdb_client,
            )
        except ImportError:
            logger.warning("Taxonomy API module not available")
            return {"success": False, "error": "Taxonomy API not available"}

        if taxid not in self._entries:
            return {"success": False, "error": f"Entry with taxid {taxid} not found"}

        entry = self._entries[taxid]
        result = {
            "success": False,
            "ncbi_found": False,
            "gtdb_found": False,
            "entry": None,
        }

        # Query NCBI
        if use_ncbi:
            ncbi = get_ncbi_client()
            # Try by taxid first, then by name
            ncbi_result = None
            if entry.taxid and entry.taxid > 0:
                ncbi_result = ncbi.get_by_taxid(entry.taxid)
            if not ncbi_result and entry.name:
                ncbi_result = ncbi.search_by_name(entry.name)

            if ncbi_result:
                result["ncbi_found"] = True
                entry.ncbi_link = ncbi_result.ncbi_link
                entry.api_sciname = ncbi_result.sciname
                entry.api_commonname = ncbi_result.commonname
                entry.api_rank = ncbi_result.rank
                entry.lineage = ncbi_result.lineage
                # Update taxid if we found by name
                if not entry.taxid or entry.taxid == 0:
                    entry.taxid = ncbi_result.taxid

        # Query GTDB
        if use_gtdb:
            gtdb = get_gtdb_client()
            # Search by name (GTDB doesn't use NCBI taxids)
            search_name = entry.api_sciname or entry.name
            gtdb_result = gtdb.search_by_name(search_name)

            if gtdb_result:
                result["gtdb_found"] = True
                entry.gtdb_link = gtdb_result.gtdb_link
                entry.gtdb_taxonomy = gtdb_result.gtdb_taxonomy

        # Update validation status
        if result["ncbi_found"] or result["gtdb_found"]:
            entry.validated = True
            entry.validation_date = datetime.utcnow().isoformat() + "Z"
            result["success"] = True
            result["entry"] = entry

        return result

    def bulk_validate_entries(
        self,
        taxids: Optional[List[int]] = None,
        use_ncbi: bool = True,
        use_gtdb: bool = True,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Validate multiple entries via API.

        Args:
            taxids: List of taxids to validate (None = all unvalidated)
            use_ncbi: Whether to query NCBI API
            use_gtdb: Whether to query GTDB API
            progress_callback: Optional callback(current, total) for progress

        Returns:
            Dict with:
            - validated: Number of entries validated
            - failed: Number of entries that failed
            - results: List of per-entry results
        """
        if taxids is None:
            # Validate all unvalidated entries
            taxids = [
                taxid for taxid, entry in self._entries.items()
                if not entry.validated
            ]

        results = {
            "validated": 0,
            "failed": 0,
            "results": [],
        }

        total = len(taxids)
        for i, taxid in enumerate(taxids):
            if progress_callback:
                progress_callback(i + 1, total)

            entry_result = self.validate_entry_via_api(
                taxid,
                use_ncbi=use_ncbi,
                use_gtdb=use_gtdb,
            )

            results["results"].append({
                "taxid": taxid,
                **entry_result
            })

            if entry_result.get("success"):
                results["validated"] += 1
            else:
                results["failed"] += 1

        logger.info(f"Bulk validation: {results['validated']} validated, "
                   f"{results['failed']} failed out of {total}")
        return results

    def get_validation_status(self) -> Dict[str, Any]:
        """
        Get summary statistics about validation status.

        Returns:
            Dict with:
            - total: Total entries
            - validated: Number of validated entries
            - unvalidated: Number of unvalidated entries
            - ncbi_validated: Number with NCBI links
            - gtdb_validated: Number with GTDB links
            - last_validation: Most recent validation date
        """
        validated = []
        unvalidated = []
        ncbi_validated = 0
        gtdb_validated = 0
        last_validation = None

        for entry in self._entries.values():
            if entry.validated:
                validated.append(entry)
                if entry.ncbi_link:
                    ncbi_validated += 1
                if entry.gtdb_link:
                    gtdb_validated += 1
                if entry.validation_date:
                    if last_validation is None or entry.validation_date > last_validation:
                        last_validation = entry.validation_date
            else:
                unvalidated.append(entry)

        return {
            "total": len(self._entries),
            "validated": len(validated),
            "unvalidated": len(unvalidated),
            "ncbi_validated": ncbi_validated,
            "gtdb_validated": gtdb_validated,
            "last_validation": last_validation,
        }

    def get_unvalidated_entries(self) -> List[WatchlistEntry]:
        """Get list of entries that haven't been validated via API."""
        return [e for e in self._entries.values() if not e.validated]

    def clear_validation(self, taxid: Optional[int] = None) -> int:
        """
        Clear validation data from entries.

        Args:
            taxid: Specific entry to clear (None = all entries)

        Returns:
            Number of entries cleared
        """
        count = 0
        entries = [self._entries[taxid]] if taxid and taxid in self._entries else self._entries.values()

        for entry in entries:
            if entry.validated:
                entry.validated = False
                entry.validation_date = None
                entry.ncbi_link = None
                entry.gtdb_link = None
                entry.lineage = None
                entry.api_sciname = None
                entry.api_commonname = None
                entry.api_rank = None
                entry.gtdb_taxonomy = None
                count += 1

        return count

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the current watchlist."""
        active = self.get_active_entries()

        # Count by watchlist (entries may be counted in multiple watchlists if shared)
        by_watchlist = {}
        for entry in active.values():
            watchlist_sources = entry.watchlist_ids or ({entry.watchlist_id} if entry.watchlist_id else {"legacy"})
            for wl_id in watchlist_sources:
                by_watchlist[wl_id] = by_watchlist.get(wl_id, 0) + 1

        stats = {
            "total_entries": len(self._entries),
            "active_entries": len(active),
            "disabled_entries": len(self._entries) - len(active),
            "taxonomy_mode": self._taxonomy_mode,
            "taxonomy_indicator": self.get_taxonomy_indicator(),
            "by_threat_level": {
                "critical": len([e for e in active.values() if e.threat_level == ThreatLevel.CRITICAL]),
                "high": len([e for e in active.values() if e.threat_level == ThreatLevel.HIGH]),
                "moderate": len([e for e in active.values() if e.threat_level == ThreatLevel.MODERATE]),
                "low": len([e for e in active.values() if e.threat_level == ThreatLevel.LOW]),
            },
            "by_source": {
                "builtin": len([e for e in active.values() if e.source == WatchlistSource.BUILTIN]),
                "user": len([e for e in active.values() if e.source == WatchlistSource.USER]),
                "migrated": len([e for e in active.values() if e.source == WatchlistSource.MIGRATED]),
                "imported": len([e for e in active.values() if e.source == WatchlistSource.IMPORTED]),
            },
            "by_watchlist": by_watchlist,
            "enabled_categories": list(self._enabled_categories),
            "enabled_watchlists": list(self._enabled_watchlists),
        }

        return stats

    def check_organisms_with_mapping(
        self,
        detected_organisms: List[Dict[str, Any]],
        mapping_collection: Optional["TaxidMappingCollection"] = None,
    ) -> List[Dict[str, Any]]:
        """
        Check detected organisms against the watchlist using taxid mappings.

        This method provides improved matching for GTDB and mixed databases
        by using pre-computed taxid mappings between NCBI taxids and
        database-specific taxids.

        Args:
            detected_organisms: List of dicts with 'taxid', 'name', 'reads', 'abundance'
            mapping_collection: Optional pre-computed TaxidMappingCollection.
                               If None, falls back to standard check_organisms().

        Returns:
            List of alert dictionaries for matched organisms exceeding thresholds
        """
        # If no mapping collection, fall back to standard method
        if not mapping_collection:
            return self.check_organisms(detected_organisms)

        alerts = []
        active_entries = self.get_active_entries()

        # Build reverse mapping: db_taxid -> ncbi_taxid
        db_to_ncbi = {}
        mappings = mapping_collection.mappings
        for ncbi_taxid, mapping in mappings.items():
            if mapping.db_taxid:
                db_to_ncbi[mapping.db_taxid] = ncbi_taxid

        for organism in detected_organisms:
            detected_taxid = organism.get("taxid")
            name = organism.get("name", "").strip()
            reads = organism.get("reads", 0)

            entry = None
            best_score = 0.0
            match_method = "none"

            # Try to find matching entry
            # 1. First, try direct NCBI taxid match
            if detected_taxid and detected_taxid in active_entries:
                entry = active_entries[detected_taxid]
                best_score = 1.0
                match_method = "direct_ncbi"

            # 2. Try reverse mapping from database taxid to NCBI taxid
            if not entry and detected_taxid and detected_taxid in db_to_ncbi:
                ncbi_taxid = db_to_ncbi[detected_taxid]
                if ncbi_taxid in active_entries:
                    entry = active_entries[ncbi_taxid]
                    # Get the mapping score
                    mapping = mappings.get(ncbi_taxid)
                    if mapping:
                        best_score = mapping.match_score or 0.9
                    else:
                        best_score = 0.9
                    match_method = "taxid_mapping"

            # 3. Fall back to name-based matching using TaxonomyMatcher
            if not entry:
                matcher = _get_taxonomy_matcher()
                for e in active_entries.values():
                    score = matcher.match_organism(
                        detected=organism,
                        entry_name=e.name,
                        entry_alt_names=e.names_alt,
                        entry_taxid=e.taxid if e.taxid else None
                    )
                    if score > best_score:
                        best_score = score
                        entry = e
                        match_method = "name_matching"

            # Only consider matches above threshold
            if entry and best_score >= 0.7 and reads >= entry.alert_threshold:
                alerts.append({
                    "taxid": entry.taxid,
                    "detected_taxid": detected_taxid,
                    "name": entry.name,
                    "common_name": entry.common_name,
                    "reads": reads,
                    "abundance": organism.get("abundance", 0.0),
                    "threat_level": entry.threat_level.value,
                    "bsl": entry.bsl_level.value if entry.bsl_level else None,
                    "category": entry.category,
                    "notes": entry.notes,
                    "action_required": entry.action_required,
                    "source": entry.source.value,
                    "threshold": entry.alert_threshold,
                    "match_score": best_score,
                    "match_method": match_method,
                    "detected_name": name,
                })

        # Sort by threat level (critical first)
        threat_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
        alerts.sort(key=lambda x: threat_order.get(x.get("threat_level", "low"), 4))

        return alerts


# Module-level singleton instance
_watchlist_manager: Optional[WatchlistManager] = None


def get_watchlist_manager() -> WatchlistManager:
    """Get the global watchlist manager instance."""
    global _watchlist_manager
    if _watchlist_manager is None:
        _watchlist_manager = WatchlistManager()
    return _watchlist_manager


def reset_watchlist_manager() -> None:
    """Reset the global watchlist manager instance."""
    global _watchlist_manager
    _watchlist_manager = None
