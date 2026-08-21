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

import hashlib
import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from nanometa_live.core.taxonomy.taxid_mapping import TaxidMappingCollection

import yaml

from nanometa_live.core.config.pathogen_loader import (
    PathogenDatabase,
    PathogenEntry,
    ThreatLevel,
    BiosaftyLevel,
    default_alert_threshold,
    get_pathogen_database,
)

logger = logging.getLogger(__name__)

# See core.taxonomy.pseudo_taxid for why these keys exist and why they must
# be deterministic across process restarts.
from nanometa_live.core.taxonomy.pseudo_taxid import (  # noqa: E402
    PSEUDO_TAXID_BASE as _PSEUDO_TAXID_BASE,  # noqa: F401  re-export
    stable_pseudo_taxid as _stable_pseudo_taxid,
)


# Import taxonomy and loader (with lazy initialization to avoid circular imports)
# Protected by lock for thread-safe lazy initialization.
_taxonomy_matcher = None
_watchlist_loader = None
_lazy_init_lock = threading.Lock()


def _get_taxonomy_matcher():
    """Lazy import of TaxonomyMatcher (thread-safe)."""
    global _taxonomy_matcher
    if _taxonomy_matcher is not None:
        return _taxonomy_matcher
    with _lazy_init_lock:
        if _taxonomy_matcher is None:
            from .taxonomy_matcher import get_taxonomy_matcher
            _taxonomy_matcher = get_taxonomy_matcher()
        return _taxonomy_matcher


def _get_watchlist_loader():
    """Lazy import of WatchlistLoader (thread-safe)."""
    global _watchlist_loader
    if _watchlist_loader is not None:
        return _watchlist_loader
    with _lazy_init_lock:
        if _watchlist_loader is None:
            from .watchlist_loader import get_watchlist_loader
            _watchlist_loader = get_watchlist_loader()
        return _watchlist_loader


# Severity ordering for threat levels. ThreatLevel.value is a STRING
# ("critical", "high", ...), so comparing .value directly is a lexicographic
# compare ("critical" < "high" < "low" < "moderate"), which is NOT severity
# order. Merging entries by that comparison silently under-escalates a
# CRITICAL organism onto a LOW one (and downgrades CRITICAL when a HIGH entry
# merges in). Rank explicitly so "more severe wins" actually holds.
_THREAT_SEVERITY = {
    ThreatLevel.CRITICAL: 4,
    ThreatLevel.HIGH: 3,
    ThreatLevel.MODERATE: 2,
    ThreatLevel.LOW: 1,
    ThreatLevel.UNKNOWN: 0,
}


def _threat_severity(level: ThreatLevel) -> int:
    """Return the severity rank of a threat level (higher == more severe)."""
    return _THREAT_SEVERITY.get(level, 0)


def _same_db_node(a: "WatchlistEntry", b: "WatchlistEntry") -> bool:
    """Do these two entries name the same node in the loaded Kraken2 database?

    Only a genuine disagreement counts as "different": when both entries state
    a ``db_taxid`` and the values differ. If either is silent the entries are
    treated as the same organism, which keeps an NCBI-only watchlist merging
    with a database-aware one rather than forking it.
    """
    return a.db_taxid is None or b.db_taxid is None or a.db_taxid == b.db_taxid


# Allowed values for ``WatchlistEntry.organism_type``. Single source of truth so
# the Add/Edit form options, ``from_dict`` normalisation, and the tests cannot
# drift apart. An unrecognised or empty value normalises to ``None``.
ORGANISM_TYPES = ("bacteria", "virus", "fungi", "archaea", "parasite", "other")


def normalize_organism_type(value: Optional[str]) -> Optional[str]:
    """Lowercase + validate an organism_type, returning None when unrecognised."""
    if not value:
        return None
    candidate = str(value).strip().lower()
    return candidate if candidate in ORGANISM_TYPES else None


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
    organism_type: Optional[str] = None  # virus / bacteria / fungi / ...
    annotation: str = ""  # Free-text note shown next to the species name
    source: WatchlistSource = WatchlistSource.USER
    enabled: bool = False
    # Multi-taxonomy support
    names_alt: List[str] = field(default_factory=list)  # Alternative names for matching
    # The organism's taxid in the Kraken2 *database* (GTDB / custom DBs assign
    # their own integers, unrelated to NCBI). When set, it is used directly for
    # detection matching and pipeline filtering, so the operator does not have
    # to rely on "Scan Database" auto-mapping. ``taxid`` above stays the NCBI
    # taxid (used for reference-genome download).
    db_taxid: Optional[int] = None
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
            organism_type=normalize_organism_type(
                getattr(pathogen, "organism_type", None)
            ),
            annotation=getattr(pathogen, "annotation", "") or "",
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

        # Default alert threshold based on threat level. The table lives in
        # pathogen_loader so the loader's entry type derives the same value;
        # they used to disagree, and an entry's threshold then depended on
        # which path happened to load it.
        alert_threshold = data.get(
            "alert_threshold", default_alert_threshold(threat_level)
        )
        # A hand-edited YAML can carry ``alert_threshold: null`` or a
        # non-numeric string; an unguarded int() raised out of the per-entry
        # loading loop and silently truncated the rest of the file. Fall back
        # to the threat-level default rather than dropping the entry.
        try:
            alert_threshold = int(alert_threshold)
        except (ValueError, TypeError):
            alert_threshold = default_alert_threshold(threat_level)

        # Handle taxid - support both 'taxid' and 'taxid_ncbi' keys
        taxid = data.get("taxid") or data.get("taxid_ncbi") or 0
        try:
            taxid = int(taxid)
        except (ValueError, TypeError):
            taxid = 0

        # Custom/GTDB database taxid (accept several aliases). Distinct from the
        # NCBI taxid above; used for matching + pipeline filtering when set.
        db_taxid_raw = (data.get("db_taxid") or data.get("kraken_taxid")
                        or data.get("taxid_custom") or data.get("taxid_gtdb"))
        try:
            db_taxid = int(db_taxid_raw) if db_taxid_raw else None
        except (ValueError, TypeError):
            db_taxid = None

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
            alert_threshold=alert_threshold,
            bsl_level=bsl_level,
            category=data.get("category", "Custom"),
            notes=data.get("notes", ""),
            action_required=data.get("action_required", "Follow laboratory biosafety protocols"),
            organism_type=normalize_organism_type(data.get("organism_type")),
            annotation=data.get("annotation", "") or "",
            source=source,
            enabled=data.get("enabled", False),
            names_alt=names_alt,
            db_taxid=db_taxid,
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
            "organism_type": self.organism_type,
            "annotation": self.annotation,
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
        # Custom/GTDB database taxid (round-trips to the UI store + workers).
        if self.db_taxid:
            result["db_taxid"] = self.db_taxid
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
            action_required=self.action_required,
            organism_type=self.organism_type,
            annotation=self.annotation
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


def _reset_taxonomy_circuit_breaker() -> None:
    """Reset the per-host circuit breaker before a bulk validation run.

    A transient host failure from an earlier run must not silently
    short-circuit this whole run. The in-run breaker still trips after the
    threshold for a genuinely-down host, so the batch never stalls.
    """
    try:
        from nanometa_live.core.taxonomy.taxonomy_api import TaxonomyAPIClient
        TaxonomyAPIClient.reset_circuit_breaker()
    except ImportError:
        pass


def _collect_api_failures() -> Dict[str, Any]:
    """Return {host: human-readable reason} for hosts whose breaker tripped.

    Empty dict when nothing failed or the taxonomy module is unavailable.
    """
    try:
        from nanometa_live.core.taxonomy.taxonomy_api import (
            TaxonomyAPIClient, describe_failure_reason,
        )
        summary = TaxonomyAPIClient.circuit_failure_summary()
        if summary:
            return {
                host: describe_failure_reason(reason)
                for host, reason in summary.items()
            }
    except ImportError:
        pass
    return {}


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
        # Reentrant: readers now snapshot under the lock, and a mutator that
        # calls a locked reader must not deadlock.
        self._lock = threading.RLock()
        self._entries: Dict[int, WatchlistEntry] = {}
        self._name_index: Dict[str, int] = {}  # name.lower() -> taxid
        self._enabled_categories: Set[str] = set()
        self._enabled_watchlists: Set[str] = set()  # YAML watchlist IDs
        self._pathogen_db: Optional[PathogenDatabase] = None
        self._project_dir: Optional[Path] = None
        # Further watchlist dirs (the run's results dir), kept so every
        # loader hand-off restates them rather than resetting the search path.
        self._additional_watchlist_dirs: List[Path] = []
        # data_dir/project_dir captured at load_config time so the toggle
        # state file resolves to the project-local location via NanometaPaths.
        self._paths_config: Dict[str, Any] = {}
        self._loaded = False
        # (watchlist_signature, EntryMatchIndex) built lazily by
        # _entry_match_index. Content-keyed, so every mutation invalidates
        # by construction -- there is no bump hook to forget.
        self._match_index_cache: Optional[Tuple[str, Any]] = None

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
        with self._lock:
            self._load_config_locked(config)

    def _load_config_locked(self, config: Dict[str, Any]) -> None:
        """Internal load_config implementation (caller must hold self._lock)."""
        # Preserve watchlists that were already enabled via enable_watchlist()
        # before load_config was called (race condition with Dash callbacks).
        pre_enabled = set(self._enabled_watchlists)

        self._entries = {}
        self._name_index = {}
        self._enabled_watchlists = set()

        # Capture the path-relevant keys so the project-local toggle-state
        # file resolves via NanometaPaths (project_dir/.nanometa/...).
        self._paths_config = {
            "data_dir": config.get("data_dir"),
            "project_dir": config.get("project_dir"),
        }

        self._resolve_watchlist_dirs(config)

        # Get or create pathogen database (for legacy support)
        self._pathogen_db = get_pathogen_database()

        # Load watchlist config (new format)
        watchlist_config = config.get("watchlist", {})

        # Set taxonomy mode

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
                    self._enable_watchlist_locked(wl_id)
            logger.info(f"Re-enabled {len(pre_enabled)} pre-existing watchlists: {pre_enabled}")

        # Restore per-entry enabled/disabled state from previous session
        self._restore_toggle_state()

        self._loaded = True
        logger.info(f"WatchlistManager loaded {len(self._entries)} entries")

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
                        "db_taxid": getattr(p, "db_taxid", None),
                        "common_name": p.common_name,
                        "threat_level": p.threat_level,
                        "bsl_level": p.bsl_level,
                        "category": p.category,
                        "alert_threshold": p.alert_threshold,
                        "action_required": p.action_required,
                        "notes": p.notes,
                        "organism_type": getattr(p, "organism_type", None),
                        "annotation": getattr(p, "annotation", ""),
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

            except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError, KeyError, ValueError, TypeError, AttributeError) as e:
                logger.exception(f"Failed to load watchlist {watchlist_id}: {e}")

    def _load_custom_yaml_file(self, file_path: str) -> None:
        """Load a custom YAML watchlist file by path."""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Custom watchlist file not found: {file_path}")
            return

        loader = _get_watchlist_loader()
        # One parse: validation returns the parsed data, so the file is not
        # read a second time for the entry load below.
        is_valid, errors, data = loader.validate_and_parse(path)

        if not is_valid:
            logger.warning(f"Invalid watchlist file {file_path}: {errors}")
            raise ValueError(f"Invalid watchlist: {'; '.join(errors)}")

        try:
            pathogens = (data or {}).get("pathogens", [])
            watchlist_id = path.stem

            for p_data in pathogens:
                # An operator's YAML carries no ``enabled`` key, and
                # ``WatchlistEntry.from_dict`` defaults it to False. Loading the
                # raw dict therefore produced disabled entries while the line
                # below marked the watchlist itself enabled -- so the toggle
                # rendered ON, ``enable_watchlist`` short-circuited on
                # "already enabled", and the uploaded list screened nothing.
                # The two must agree: this method activates the watchlist, so
                # it activates its entries. An explicit ``enabled: false`` in
                # the file is still honoured.
                entry_data = dict(p_data)
                entry_data["enabled"] = entry_data.get("enabled", True)
                # Per-entry isolation: one malformed entry must cost that
                # entry alone. Raising out of this loop dropped every entry
                # after the bad one AND skipped the enabled-marking below --
                # the UI then reported the watchlist off while the entries
                # loaded before the failure were live.
                try:
                    self._add_entry_from_dict(
                        entry_data,
                        WatchlistSource.IMPORTED,
                        watchlist_id=watchlist_id
                    )
                except Exception:
                    logger.exception(
                        "Skipping malformed watchlist entry %r in %s; the "
                        "remaining entries are still loaded",
                        p_data.get("name", p_data), file_path,
                    )

            self._enabled_watchlists.add(watchlist_id)
            logger.info(f"Loaded {len(pathogens)} entries from custom file: {file_path}")

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError, KeyError, ValueError, TypeError, AttributeError) as e:
            logger.exception(f"Error loading custom watchlist {file_path}: {e}")

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

    def _identity_key(self, entry: WatchlistEntry) -> int:
        """Return the key ``entry`` should be stored under.

        Normally the NCBI taxid. But an NCBI taxid does not identify an
        organism in the loaded Kraken2 database: NCBI has no separate id for
        many subspecies, and GTDB splits polyphyletic species into several
        nodes. So *Burkholderia mallei* subsp. *mallei* (db 4003795, glanders)
        and *Burkholderia mallei* (db 4003703) both carry NCBI 13373, and all
        three *Escherichia coli* variants carry 562.

        Keying those on the NCBI taxid alone merged them, and the merge kept
        one ``db_taxid`` and discarded the other -- so a database node that the
        operator explicitly listed stopped being watched. Measured on the
        Bioshield list: 129 entries loaded as 125, two of the four lost being
        Critical.

        ``db_taxid`` is therefore the identity here: entries whose db_taxid
        genuinely differs get their own key. Entries that agree, or where
        either side is silent, still share a key and merge as before -- that
        is the same organism arriving from two watchlist files.
        """
        key = entry.taxid
        existing = self._entries.get(key)
        if existing is None or _same_db_node(existing, entry):
            return key

        # A different node that happens to share an NCBI taxid. Prefer its own
        # database taxid as the key; fall back to a name-derived key if that
        # is somehow taken by yet another organism.
        fork = entry.db_taxid
        if fork:
            other = self._entries.get(fork)
            if other is None or _same_db_node(other, entry):
                return fork
        return _stable_pseudo_taxid(f"{entry.name}|{entry.db_taxid}")

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
            key = self._identity_key(entry)
            if key in self._entries:
                # MERGE: Entry already exists from another watchlist
                existing = self._entries[key]

                # Snapshot the pre-merge state so a later user-override can
                # record the TRUE originals, not the already-merged values.
                pre_merge_threshold = existing.alert_threshold
                pre_merge_threat_level = existing.threat_level

                # Add new watchlist_id to the set
                if watchlist_id:
                    existing.watchlist_ids.add(watchlist_id)

                # Keep higher threat level (more severe), ranked by severity.
                if _threat_severity(entry.threat_level) > _threat_severity(existing.threat_level):
                    existing.threat_level = entry.threat_level

                # Keep lower threshold (more sensitive alerting)
                existing.alert_threshold = min(existing.alert_threshold, entry.alert_threshold)

                # Merge alternative names
                for alt_name in entry.names_alt:
                    if alt_name not in existing.names_alt:
                        existing.names_alt.append(alt_name)
                        self._name_index[alt_name.lower()] = key

                # If incoming entry is enabled (e.g. from enable_watchlist),
                # also enable existing entry for consistent UX
                if entry.enabled:
                    existing.enabled = True

                # Check if this is a user override of a builtin
                if existing.source == WatchlistSource.BUILTIN and source != WatchlistSource.BUILTIN:
                    existing.user_override = True
                    if existing.original_threshold is None:
                        existing.original_threshold = pre_merge_threshold
                    if existing.original_threat_level is None:
                        existing.original_threat_level = pre_merge_threat_level

                # Don't overwrite - we merged into existing
                return

            # New entry - add it
            self._entries[key] = entry
            if entry.name:
                self._name_index[entry.name.lower()] = key
                # Also index alternative names
                for alt_name in entry.names_alt:
                    self._name_index[alt_name.lower()] = key
        elif entry.name:
            # Name-only entry (no taxid) - use hash of name as pseudo-taxid
            pseudo_taxid = _stable_pseudo_taxid(entry.name)

            if pseudo_taxid in self._entries:
                # MERGE: Entry already exists. Mirror the taxid-keyed merge
                # branch above -- this branch used to drop the incoming
                # entry's names_alt, db_taxid and enabled state, so a
                # name-only organism behaved differently from the same
                # organism with a taxid (2026-08-17 audit, finding W8).
                existing = self._entries[pseudo_taxid]
                if watchlist_id:
                    existing.watchlist_ids.add(watchlist_id)
                if _threat_severity(entry.threat_level) > _threat_severity(existing.threat_level):
                    existing.threat_level = entry.threat_level
                existing.alert_threshold = min(existing.alert_threshold, entry.alert_threshold)

                for alt_name in entry.names_alt:
                    if alt_name not in existing.names_alt:
                        existing.names_alt.append(alt_name)
                        self._name_index[alt_name.lower()] = pseudo_taxid

                if entry.db_taxid and not existing.db_taxid:
                    existing.db_taxid = entry.db_taxid

                # If incoming entry is enabled (e.g. from enable_watchlist),
                # also enable existing entry for consistent UX
                if entry.enabled:
                    existing.enabled = True
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
        """Get only enabled watchlist entries.

        Snapshotted under the lock: mutators (load_config rebuilds
        ``_entries`` key by key) hold ``self._lock``, and iterating the live
        dict without it can raise "dictionary changed size during iteration"
        mid-poll or -- worse -- miss an entry not yet re-added, a transient
        false negative on that screening pass. The returned dict is a copy,
        so callers can iterate it freely.
        """
        with self._lock:
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
        with self._lock:
            return [
                e for e in self._entries.values()
                if e.threat_level == level and e.enabled
            ]

    def get_critical_entries(self) -> List[WatchlistEntry]:
        """Get all critical threat level entries."""
        return self.get_entries_by_threat_level(ThreatLevel.CRITICAL)

    @staticmethod
    def _database_taxids_are_ncbi() -> bool:
        """Whether a raw taxid comparison against this database means anything.

        False whenever it cannot be established -- including before any
        database has been indexed. Trusting an unverified taxid names the
        wrong organism on a pathogen dashboard; distrusting a good one only
        costs the shortcut, since name matching still runs.
        """
        try:
            from nanometa_live.core.taxonomy.taxid_mapping import (
                get_mapping_collection,
            )
            collection = get_mapping_collection()
            return bool(collection and collection.profile.taxids_are_ncbi)
        except (ImportError, AttributeError):
            return False

    @staticmethod
    def _other_entries_on_node(
        detected_taxid: Optional[int],
        db_to_ncbi: Dict[int, List[int]],
        active_entries: Dict[int, "WatchlistEntry"],
        matched: "WatchlistEntry",
    ) -> List[str]:
        """Names of the other watchlist entries sharing this database node."""
        if not detected_taxid:
            return []
        others = []
        for key in db_to_ncbi.get(int(detected_taxid), []):
            other = active_entries.get(key)
            if other is not None and other.name != matched.name:
                others.append(other.name)
        return others

    @staticmethod
    def _build_db_taxid_index(
        active_entries: Dict[int, "WatchlistEntry"],
        mapping_collection: Optional[Any],
    ) -> Dict[int, List[int]]:
        """Map database taxid -> the watchlist keys that resolve to it.

        A list, not a single key, because several watchlist entries can
        legitimately share one database node. On a GTDB-derived database
        every *Shigella* species sits under *Escherichia coli*, and
        *Burkholderia mallei* and *pseudomallei* share a node because GTDB
        treats mallei as a lineage within pseudomallei. A detection landing
        there genuinely cannot say which entry it is, so the caller reports
        the ambiguity rather than picking one and sounding certain.

        An operator-set ``db_taxid`` on an entry takes precedence over a
        generated mapping for the same node -- the precedence
        ``parameter_mapping.build_species_list`` already applies when
        building the pipeline's taxid filter.
        """
        db_to_ncbi: Dict[int, List[int]] = {}
        if mapping_collection is not None:
            for ncbi_taxid, mapping in sorted(mapping_collection.mappings.items()):
                if not mapping.db_taxid:
                    continue
                keys = db_to_ncbi.setdefault(int(mapping.db_taxid), [])
                if ncbi_taxid not in keys:
                    keys.append(ncbi_taxid)
        for key, entry in active_entries.items():
            db_taxid = getattr(entry, "db_taxid", None)
            if db_taxid:
                # Explicit operator statement: it leads, others still listed.
                keys = db_to_ncbi.setdefault(int(db_taxid), [])
                if key in keys:
                    keys.remove(key)
                keys.insert(0, key)
        return db_to_ncbi


    @staticmethod
    def _dedupe_alerts_by_entry(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """One detection per watchlist entry, keeping the dominant node.

        A species report row and its subspecies/strain rows all resolve to
        the same watchlist entry, and the species row's cumulative count
        already CONTAINS its descendants -- so emitting one alert per
        matched row both multiplied the "N of M watched pathogens" count
        (a real LVS run announced 12 pathogens for one organism) and
        double-counted reads anywhere the alerts are summed (2026-08-17
        reaudit). The kept row is the one with the most reads: for
        ancestor/descendant matches that is the ancestor, whose count
        contains the others. Distinct entries are never merged.
        """
        best: Dict[Any, Dict[str, Any]] = {}
        order: List[Any] = []
        for alert in alerts:
            key = alert.get("taxid") or alert.get("name")
            if key not in best:
                best[key] = alert
                order.append(key)
            elif alert.get("reads", 0) > best[key].get("reads", 0):
                best[key] = alert
        return [best[k] for k in order]

    def check_organisms(
        self,
        detected_organisms: List[Dict[str, Any]],
        below_threshold: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Check detected organisms against the watchlist.

        Uses TaxonomyMatcher for multi-taxonomy support (NCBI and GTDB).

        Args:
            detected_organisms: List of dicts with 'taxid', 'name', 'reads', 'abundance'

        Args (continued):
            below_threshold: return the matches that were filtered OUT for
                sitting under their entry's ``alert_threshold`` instead of the
                ones above it. Those are still evidence -- the threshold
                decides whether a hit alarms, not whether it exists -- and the
                Dashboard renders them so a sub-threshold detection cannot hide
                behind a green ALL CLEAR (2026-08-19 operator decision).

        Returns:
            List of alert dictionaries for matched organisms exceeding
            thresholds -- or, with ``below_threshold``, those under them
        """
        above, below = self.check_organisms_split(detected_organisms)
        return below if below_threshold else above

    def _finalise_alerts(
        self, alerts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """One alert per watchlist entry (dominant node wins), then sort by
        threat level (critical first)."""
        alerts = self._dedupe_alerts_by_entry(alerts)
        threat_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
        alerts.sort(
            key=lambda x: threat_order.get(x.get("threat_level", "low"), 4))
        return alerts

    def watchlist_signature(
        self, active_entries: Optional[Dict[int, WatchlistEntry]] = None
    ) -> str:
        """Content signature of the active watchlist.

        Covers every entry field (dataclass repr), so any edit -- toggle,
        threshold, alt names, threat level, db_taxid -- yields a new value.
        Keys the entry-match index and the dashboard's pathogen-check memo;
        being content-derived, a missed invalidation hook cannot serve
        stale results.
        """
        if active_entries is None:
            active_entries = self.get_active_entries()
        parts = "|".join(repr(e) for e in active_entries.values())
        return hashlib.md5(parts.encode("utf-8", "replace")).hexdigest()

    def _entry_match_index(self, active_entries: Dict[int, WatchlistEntry]):
        """Entry-match index for the given active set, cached on content.

        Rebuilding costs O(entries); the win is per report row, where the
        former inner loop recomputed name variants for every
        (row x entry) pair.
        """
        signature = self.watchlist_signature(active_entries)
        cached = self._match_index_cache
        if cached is not None and cached[0] == signature:
            return cached[1]
        index = _get_taxonomy_matcher().build_entry_index(
            list(active_entries.values()))
        self._match_index_cache = (signature, index)
        return index

    def check_organisms_split(
        self,
        detected_organisms: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Single matching pass, partitioned by alert threshold.

        Returns ``(above, below)``: the alerts at or above their entry's
        ``alert_threshold``, and the sub-threshold matches. The dashboard
        needs both sides every tick, and matching is the expensive part --
        one pass instead of two halves the dominant per-poll cost.
        """
        above: List[Dict[str, Any]] = []
        below: List[Dict[str, Any]] = []
        active_entries = self.get_active_entries()
        matcher = _get_taxonomy_matcher()
        match_index = self._entry_match_index(active_entries)
        # A raw taxid comparison is only meaningful when the database's taxids
        # are NCBI's. False is the safe default: trusting an unverified taxid
        # names the WRONG organism, while distrusting a good one only falls
        # through to name matching. Resolved once, not once per organism.
        db_is_ncbi = self._database_taxids_are_ncbi()

        # Operator-set db_taxid values, so an entry that names its taxid in the
        # loaded database matches by that id even when its name does not
        # normalise to the report's name. Without this the field was honoured
        # when building pipeline parameters and when writing the export report,
        # but ignored by live detection -- the three disagreed.
        db_to_ncbi = self._build_db_taxid_index(active_entries, None)

        for organism in detected_organisms:
            taxid = organism.get("taxid")
            name = organism.get("name", "").strip()
            reads = organism.get("reads", 0)

            # Try to find matching entry using multi-taxonomy matching
            entry = None
            best_score = 0.0

            if taxid and taxid in db_to_ncbi:
                entry = active_entries.get(db_to_ncbi[taxid][0])
                best_score = 1.0 if entry else 0.0
            if entry is None and db_is_ncbi and taxid and taxid in active_entries:
                entry = active_entries[taxid]
                best_score = 1.0
            if entry is None:
                # Name-based matching against the prebuilt index; equivalent
                # to looping match_organism over every entry (max score wins,
                # first entry wins ties) at O(1) instead of O(entries).
                entry, best_score = matcher.match_row_indexed(
                    organism.get("name", ""), match_index)

            # 0.7 is the NAME-match floor; alert_threshold then decides which
            # side of the fence the hit lands on. Both sides are real matches
            # -- see check_organisms_with_mapping for why sub-threshold hits
            # are returned rather than dropped.
            if entry and best_score >= 0.7:
                (above if reads >= entry.alert_threshold else below).append(
                    self._alert_dict(entry, organism, taxid, best_score,
                                     db_to_ncbi, active_entries))

        return self._finalise_alerts(above), self._finalise_alerts(below)

    def _alert_dict(
        self,
        entry: WatchlistEntry,
        organism: Dict[str, Any],
        detected_taxid: Optional[int],
        best_score: float,
        db_to_ncbi: Dict[int, List[int]],
        active_entries: Dict[int, WatchlistEntry],
        match_method: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build one alert from a matched entry and its detected organism.

        ``detected_taxid`` is the taxid as it appeared in the Kraken2 report.
        Callers attribute detections to samples by this key; without it
        attribution is unrecoverable on a GTDB or custom database, where the
        report taxid differs from the watchlist entry's NCBI taxid.

        ``ambiguous_with`` discloses the other watchlist entries sharing this
        database node. A detection there genuinely cannot say which organism
        it is (GTDB folds B. mallei into pseudomallei), and announcing one
        name at full confidence would be a false identification on a
        biothreat panel.
        """
        alert = {
            "taxid": entry.taxid,
            "detected_taxid": detected_taxid,
            "name": entry.name,
            "common_name": entry.common_name,
            "reads": organism.get("reads", 0),
            "abundance": organism.get("abundance", 0.0),
            "threat_level": entry.threat_level.value,
            "bsl": entry.bsl_level.value if entry.bsl_level else None,
            "category": entry.category,
            "notes": entry.notes,
            "action_required": entry.action_required,
            "organism_type": entry.organism_type,
            "annotation": entry.annotation,
            "source": entry.source.value,
            "threshold": entry.alert_threshold,
            "match_score": best_score,
            "detected_name": organism.get("name", "").strip(),
            "ambiguous_with": self._other_entries_on_node(
                detected_taxid, db_to_ncbi, active_entries, entry
            ),
        }
        if match_method is not None:
            alert["match_method"] = match_method
        return alert

    def add_custom_entry(self, entry_data: Dict[str, Any]) -> WatchlistEntry:
        """Add a custom entry to the watchlist."""
        with self._lock:
            self._add_entry_from_dict(entry_data, WatchlistSource.USER)
            taxid = entry_data.get("taxid") or _stable_pseudo_taxid(entry_data.get("name", ""))
            return self._entries.get(taxid)

    def remove_entry(self, taxid: int) -> bool:
        """Remove an entry from the watchlist."""
        with self._lock:
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
        """Enable or disable an entry and persist state to disk."""
        with self._lock:
            if taxid in self._entries:
                self._entries[taxid].enabled = enabled
                self._save_toggle_state()
                return True
            return False

    def toggle_category(self, category: str, enabled: bool) -> int:
        """Enable or disable all entries in a category and persist state."""
        with self._lock:
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

            if count > 0:
                self._save_toggle_state()

            return count

    def get_enabled_categories(self) -> Set[str]:
        """Get the set of enabled builtin categories."""
        return self._enabled_categories.copy()

    def _toggle_state_path(self) -> Path:
        """Path to the toggle-state persistence file.

        The toggle state (which entries are enabled/disabled) is the
        operator's per-analysis *selection*, so it is project-local:
        ``<project_dir>/.nanometa/watchlist_toggle_state.yaml`` via
        NanometaPaths. When no project_dir was supplied at load_config
        time, NanometaPaths falls back to the global data_dir (honouring
        NANOMETA_DATA_DIR), preserving the pre-split location.
        """
        from nanometa_live.core.utils.paths import (
            NanometaPaths, get_data_dir_from_env,
        )
        if self._paths_config:
            return NanometaPaths.from_config(self._paths_config).watchlist_toggle_state
        return Path(get_data_dir_from_env()) / "watchlist_toggle_state.yaml"

    def _toggle_state_read_candidates(self) -> List[Path]:
        """Paths to try when RESTORING toggle state, most specific first.

        Writes always go to the project-scoped path, but reads fall back to
        the data-dir one. That fallback is what makes a transferred bundle
        work: ``import_bundle`` writes the operator's selection to
        ``<data_dir>/watchlist_toggle_state.yaml`` because a bundle is
        machine-portable and cannot know the field machine's project
        directory. Without the fallback, a project dir -- which the GUI
        always sets -- shadowed the imported file, and every entry the
        operator had deliberately disabled came back enabled on the field
        machine with no indication anything had been lost.

        A project that has its own state still wins, so this seeds a fresh
        project rather than overriding an existing selection.
        """
        from nanometa_live.core.utils.paths import get_data_dir_from_env

        primary = self._toggle_state_path()
        fallback = Path(get_data_dir_from_env()) / "watchlist_toggle_state.yaml"
        candidates = [primary]
        if fallback != primary:
            candidates.append(fallback)
        return candidates

    def _save_toggle_state(self) -> None:
        """Save disabled taxid set to disk for persistence across restarts.

        Atomic write-then-rename so a concurrent reader never observes
        a half-written file. The fcntl lock serialises concurrent
        writers; we deliberately do not merge state, because a toggle
        is an explicit per-instance operator action and the most
        recent click should reflect on disk. Two operators working in
        parallel against the same data_dir share the toggle state by
        design (both load the same file at startup).
        """
        from nanometa_live.core.utils.atomic_write import (
            atomic_write_text, file_lock,
        )
        try:
            disabled = sorted(
                taxid for taxid, entry in self._entries.items() if not entry.enabled
            )
            state_path = self._toggle_state_path()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with file_lock(state_path):
                atomic_write_text(
                    state_path,
                    yaml.dump(
                        {"disabled_taxids": disabled},
                        default_flow_style=False,
                    ),
                )
        except (FileNotFoundError, PermissionError, OSError, yaml.YAMLError) as e:
            logger.debug(f"Could not save toggle state: {e}")

    def _restore_toggle_state(self) -> None:
        """Restore disabled taxid set from disk after loading entries."""
        try:
            state_path = next(
                (p for p in self._toggle_state_read_candidates() if p.exists()),
                None,
            )
            if state_path is None:
                return
            with open(state_path) as f:
                data = yaml.safe_load(f) or {}
            disabled = set(data.get("disabled_taxids", []))
            if not disabled:
                return
            count = 0
            for taxid in disabled:
                if taxid in self._entries:
                    self._entries[taxid].enabled = False
                    count += 1
            if count:
                logger.info(f"Restored toggle state: {count} entries disabled from previous session")
        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError, AttributeError) as e:
            logger.debug(f"Could not restore toggle state: {e}")

    # -------------------------------------------------------------------------
    # New methods for YAML-based watchlists and multi-taxonomy support
    # -------------------------------------------------------------------------

    def _resolve_watchlist_dirs(self, config: Dict[str, Any]) -> None:
        """Decide which directories hold this project's watchlists.

        The project dir is the documented home of the project tier. The
        results dir is searched as well, because
        `import_watchlist(destination="project")` has been saving operator
        uploads there and the two directories stop coinciding once the project
        dir defaults outside the working directory.
        """
        results_dir = (config.get("results_output_directory")
                       or config.get("main_dir"))
        project_dir = config.get("project_dir") or results_dir
        if not project_dir:
            return
        self._project_dir = Path(project_dir)
        self._additional_watchlist_dirs = (
            [Path(results_dir)]
            if results_dir and results_dir != project_dir else []
        )
        self._apply_watchlist_search_path()

    def _apply_watchlist_search_path(self) -> None:
        """Restate the loader's project tier from what this manager holds.

        The loader is a process-wide singleton whose search path any caller can
        overwrite, so both hand-offs go through here: setting the project dir
        without the additional dirs silently narrows the search.
        """
        if not self._project_dir:
            return
        _get_watchlist_loader().set_project_dir(
            self._project_dir,
            additional_dirs=list(self._additional_watchlist_dirs),
        )

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
        self._apply_watchlist_search_path()

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
                # The tier badge alone cannot identify a file: the user tier
                # moves with the project/data dir, so several copies of one
                # watchlist can exist and the panel showed them identically.
                "file_path": str(getattr(wl, "file_path", "") or ""),
            })

        return result

    def enabled_watchlist_ids(self) -> List[str]:
        """Sorted ids of the currently enabled watchlists.

        Recorded into the run metadata at pipeline start so a post-hoc
        ``nanometa-report`` can reproduce the run's pathogen screen without
        the operator having to remember which lists were active.
        """
        with self._lock:
            return sorted(self._enabled_watchlists)

    def enable_watchlist(self, watchlist_id: str) -> int:
        """
        Enable a watchlist by loading all its entries.

        Args:
            watchlist_id: ID of the watchlist to enable

        Returns:
            Number of entries added
        """
        with self._lock:
            return self._enable_watchlist_locked(watchlist_id)

    def _enable_watchlist_locked(self, watchlist_id: str) -> int:
        """Internal enable_watchlist (caller must hold self._lock)."""
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
                # Carried explicitly: this dict is rebuilt field by field, and
                # omitting db_taxid dropped the operator's database-specific
                # taxid on the way in. On a flextaxd/GTDB build the NCBI taxid
                # does not identify the node -- that is why db_taxid was set --
                # so losing it silently reduced the entry to name matching,
                # which GTDB's renaming is exactly what breaks.
                "db_taxid": getattr(p, "db_taxid", None),
                "common_name": p.common_name,
                "threat_level": p.threat_level,
                "bsl_level": p.bsl_level,
                "category": p.category,
                "alert_threshold": p.alert_threshold,
                "action_required": p.action_required,
                "notes": p.notes,
                "organism_type": getattr(p, "organism_type", None),
                "annotation": getattr(p, "annotation", ""),
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
        with self._lock:
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
        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError, KeyError, ValueError) as e:
            logger.exception(f"Failed to load watchlist preview for {watchlist_id}: {e}")
            return []

        result = []
        for p in pathogens:
            # Check if entry exists in active _entries for enabled status
            existing = None
            if p.taxid_ncbi:
                existing = self._entries.get(p.taxid_ncbi)
            if not existing:
                # Try by name hash for name-only entries
                pseudo_taxid = _stable_pseudo_taxid(p.name)
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
        with self._lock:
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
        offline_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate a watchlist entry by querying NCBI and/or GTDB APIs.

        Args:
            taxid: Taxonomy ID of the entry to validate
            use_ncbi: Whether to query NCBI API
            use_gtdb: Whether to query GTDB API
            offline_mode: If True, skip live API calls and use cached data only

        Returns:
            Dict with validation results:
            - success: True if at least one API returned results
            - ncbi_found: True if found in NCBI
            - gtdb_found: True if found in GTDB
            - entry: Updated WatchlistEntry (or None if not found)
        """
        from datetime import datetime, timezone

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

        if offline_mode:
            logger.debug(
                "validate_entry_via_api: offline_mode=True, skipping live API calls for taxid %s",
                taxid,
            )

        # Query NCBI
        if use_ncbi:
            ncbi = get_ncbi_client(offline_mode=offline_mode)
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
            gtdb = get_gtdb_client(offline_mode=offline_mode)
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
            # Timezone-aware UTC instead of the deprecated datetime.utcnow().
            # The trailing "Z" is preserved by stripping the +00:00 offset
            # that isoformat() would otherwise emit.
            entry.validation_date = (
                datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
            )
            result["success"] = True
            result["entry"] = entry

        return result

    def bulk_validate_entries(
        self,
        taxids: Optional[List[int]] = None,
        use_ncbi: bool = True,
        use_gtdb: bool = True,
        progress_callback: Optional[callable] = None,
        offline_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate multiple entries via API.

        Args:
            taxids: List of taxids to validate (None = all unvalidated)
            use_ncbi: Whether to query NCBI API
            use_gtdb: Whether to query GTDB API
            progress_callback: Optional callback(current, total) for progress
            offline_mode: If True, skip live API calls and use cached data only

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

        _reset_taxonomy_circuit_breaker()

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
                offline_mode=offline_mode,
            )

            results["results"].append({
                "taxid": taxid,
                **entry_result
            })

            if entry_result.get("success"):
                results["validated"] += 1
            else:
                results["failed"] += 1

        # Surface which API host(s) failed and why, so the UI can report a
        # cause instead of a silent partial count.
        api_failures = _collect_api_failures()
        if api_failures:
            results["api_failures"] = api_failures

        logger.info(f"Bulk validation: {results['validated']} validated, "
                   f"{results['failed']} failed out of {total}")
        return results

    def apply_validation_results(self, results: List[Dict[str, Any]]) -> int:
        """Copy validation outcomes (WatchlistEntry.to_dict() payloads) onto
        the in-memory entries, matching by taxid.

        Validation runs in a DiskcacheManager background worker so the
        NCBI/GTDB probes never freeze the UI. The worker mutates its own
        process-local WatchlistManager, so its results must be applied back
        onto the main-process singleton that the table reads from. This is
        that apply step.

        Returns the number of entries updated.
        """
        applied = 0
        for payload in results or []:
            try:
                taxid = int(payload.get("taxid"))
            except (TypeError, ValueError):
                continue
            entry = self._entries.get(taxid)
            if entry is None:
                continue
            entry.validated = bool(payload.get("validated", False))
            entry.validation_date = payload.get("validation_date")
            entry.ncbi_link = payload.get("ncbi_link")
            entry.gtdb_link = payload.get("gtdb_link")
            entry.gtdb_taxonomy = payload.get("gtdb_taxonomy")
            entry.api_sciname = payload.get("api_sciname")
            entry.api_commonname = payload.get("api_commonname")
            entry.api_rank = payload.get("api_rank")
            if payload.get("lineage") is not None:
                entry.lineage = payload.get("lineage")
            applied += 1
        if applied:
            logger.info("Applied %d background validation result(s)", applied)
        return applied

    def get_validation_status(self, enabled_only: bool = False) -> Dict[str, Any]:
        """
        Get summary statistics about validation status.

        Args:
            enabled_only: When True, count only entries the operator currently
                has enabled. The "validated X/Y" badge must use this so the
                denominator reflects the active set -- un-ticking a watchlist
                must lower Y, not leave a stale total from previously-ticked
                lists.

        Returns:
            Dict with:
            - total: Total entries (enabled-only when requested)
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

        entries = [
            e for e in self._entries.values()
            if not enabled_only or getattr(e, "enabled", True)
        ]
        for entry in entries:
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
            "total": len(entries),
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
        below_threshold: bool = False,
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
        above, below = self.check_organisms_with_mapping_split(
            detected_organisms, mapping_collection)
        return below if below_threshold else above

    @staticmethod
    def _reverse_mapping_hit(
        detected_taxid: int,
        db_to_ncbi: Dict[int, List[int]],
        active_entries: Dict[int, WatchlistEntry],
        mapping_collection: "TaxidMappingCollection",
    ) -> Optional[Tuple[WatchlistEntry, float]]:
        """Resolve a database taxid to a watchlist entry via the reverse map.

        Carries the generated mapping's own confidence when there is one. An
        operator-set db_taxid has no mapping record, and scores 1.0: it is an
        explicit statement, not a guess. ``or`` would promote a genuine 0.0
        mapping score to 0.9, turning a no-confidence mapping into a strong
        match; only an ABSENT score takes the default.
        """
        ncbi_taxid = db_to_ncbi[detected_taxid][0]
        entry = active_entries.get(ncbi_taxid)
        if entry is None:
            return None
        mapping = mapping_collection.mappings.get(ncbi_taxid)
        if mapping:
            score = (mapping.match_score
                     if mapping.match_score is not None else 0.9)
        elif getattr(entry, "db_taxid", None) == detected_taxid:
            score = 1.0
        else:
            score = 0.9
        return entry, score

    def check_organisms_with_mapping_split(
        self,
        detected_organisms: List[Dict[str, Any]],
        mapping_collection: Optional["TaxidMappingCollection"] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Single mapping-aware matching pass, partitioned by threshold.

        Returns ``(above, below)`` like :meth:`check_organisms_split`, using
        the taxid mapping steps first and the indexed name matcher as the
        fallback.
        """
        # If no mapping collection, fall back to standard method
        if not mapping_collection:
            return self.check_organisms_split(detected_organisms)

        above: List[Dict[str, Any]] = []
        below: List[Dict[str, Any]] = []
        active_entries = self.get_active_entries()

        db_to_ncbi = self._build_db_taxid_index(active_entries, mapping_collection)
        matcher = _get_taxonomy_matcher()
        match_index = self._entry_match_index(active_entries)
        # See the note on the equivalent gate in check_organisms for why
        # False is the safe default rather than True. Loop-invariant.
        db_is_ncbi = bool(mapping_collection.profile.taxids_are_ncbi)

        for organism in detected_organisms:
            detected_taxid = organism.get("taxid")
            name = organism.get("name", "").strip()
            reads = organism.get("reads", 0)

            entry = None
            best_score = 0.0
            match_method = "none"

            # 1. First, try direct NCBI taxid match.
            if db_is_ncbi and detected_taxid and detected_taxid in active_entries:
                entry = active_entries[detected_taxid]
                best_score = 1.0
                match_method = "direct_ncbi"

            # 2. Try reverse mapping from database taxid to NCBI taxid
            if not entry and detected_taxid and detected_taxid in db_to_ncbi:
                hit = self._reverse_mapping_hit(
                    detected_taxid, db_to_ncbi, active_entries,
                    mapping_collection)
                if hit is not None:
                    entry, best_score = hit
                    match_method = "taxid_mapping"

            # 3. Fall back to name-based matching against the prebuilt
            #    index; equivalent to looping match_organism over every
            #    entry (max score wins, first entry wins ties).
            if not entry:
                m_entry, m_score = matcher.match_row_indexed(
                    organism.get("name", ""), match_index)
                if m_entry is not None:
                    entry, best_score = m_entry, m_score
                    match_method = "name_matching"

            # Threshold decides which side of the fence a match lands on;
            # both sides are real matches.
            if entry and best_score >= 0.7:
                (above if reads >= entry.alert_threshold else below).append(
                    self._alert_dict(entry, organism, detected_taxid,
                                     best_score, db_to_ncbi, active_entries,
                                     match_method=match_method))

        return self._finalise_alerts(above), self._finalise_alerts(below)


# Module-level singleton instance with thread-safe initialization.
_watchlist_manager: Optional[WatchlistManager] = None
_wm_lock = threading.Lock()


def get_watchlist_manager() -> WatchlistManager:
    """Get the global watchlist manager instance (thread-safe)."""
    global _watchlist_manager
    if _watchlist_manager is None:
        with _wm_lock:
            if _watchlist_manager is None:
                _watchlist_manager = WatchlistManager()
    return _watchlist_manager


def reset_watchlist_manager() -> None:
    """Reset the global watchlist manager instance."""
    global _watchlist_manager
    _watchlist_manager = None
