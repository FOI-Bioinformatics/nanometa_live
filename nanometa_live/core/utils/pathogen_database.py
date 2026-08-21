"""
Pathogen Database for Nanometa Live.

Pre-configured lists of dangerous pathogens based on CDC Bioterrorism Categories
and WHO Priority Pathogens. These lists help operators identify potentially
dangerous organisms in sequencing results.

This module provides backward-compatible access to the pathogen database.
The actual pathogen data is now externalized to a YAML configuration file
located at: nanometa_live/core/config/data/pathogens.yaml

Users can override or extend the built-in database by:
1. Creating a custom pathogens.yaml file
2. Adding entries to species_of_interest in their analysis config

References:
- Federal Select Agent Program (select agents and toxins): https://www.selectagents.gov/sat/list.htm
- WHO Priority Pathogens: https://www.who.int/publications/i/item/9789240093461
"""

import logging
import threading
from typing import Any, Dict, List, Optional

# Import classes and functions from the new loader module for backward compatibility
from nanometa_live.core.config.pathogen_loader import (
    BiosaftyLevel,
    PathogenDatabase,
    PathogenEntry,
    ThreatLevel,
    clear_cache,
    export_watchlist_template as _export_template,
    get_pathogen_database,
    validate_watchlist_yaml,
)

logger = logging.getLogger(__name__)

# Re-export enums and dataclass for backward compatibility
__all__ = [
    "ThreatLevel",
    "BiosaftyLevel",
    "PathogenEntry",
    "get_all_dangerous_pathogens",
    "get_pathogens_by_threat_level",
    "get_critical_pathogens",
    "get_pathogen_by_taxid",
    "get_pathogen_by_name",
    "check_for_dangerous_pathogens",
    "export_watchlist_template",
    "PathogenDatabase",
    "get_pathogen_database",
    "validate_watchlist_yaml",
    "clear_cache",
]


# Module-level database instance (lazy-loaded, thread-safe)
_database: Optional[PathogenDatabase] = None
_database_lock = threading.Lock()

# (custom-watchlist digest, merged pathogen dict). check_for_dangerous_
# pathogens runs on dashboard alert ticks with the full active watchlist as
# custom_watchlist, and constructing a fresh PathogenDatabase re-parsed
# pathogens.yaml from disk on every call (~11 ms plus the merge). The
# digest is content-derived, so an edited watchlist reloads by construction.
_merged_db_cache: Optional[tuple] = None


def _merged_pathogen_db(
    custom_watchlist: List[Dict[str, Any]],
) -> Dict[Any, PathogenEntry]:
    global _merged_db_cache
    import json

    digest = json.dumps(custom_watchlist, sort_keys=True, default=str)
    cached = _merged_db_cache
    if cached is not None and cached[0] == digest:
        return cached[1]
    db = PathogenDatabase(user_watchlist=custom_watchlist)
    db.load()
    merged = db.get_all_pathogens()
    _merged_db_cache = (digest, merged)
    return merged


def _get_database() -> PathogenDatabase:
    """Get the module-level database instance, initializing if needed (thread-safe)."""
    global _database
    if _database is not None:
        return _database
    with _database_lock:
        if _database is None:
            _database = get_pathogen_database()
        return _database


def get_all_dangerous_pathogens(
    custom_watchlist: Optional[List[Dict[str, Any]]] = None,
) -> Dict[int, PathogenEntry]:
    """
    Return a dictionary of all dangerous pathogens keyed by taxonomy ID.

    This function loads pathogens from the YAML database file and optionally
    merges user-defined watchlist entries.

    Args:
        custom_watchlist: Optional list of additional pathogens to include.

    Returns:
        Dict mapping taxid to PathogenEntry.
    """
    if custom_watchlist:
        # Create a new database instance with custom watchlist
        db = PathogenDatabase(user_watchlist=custom_watchlist)
        db.load()
        return db.get_all_pathogens()
    else:
        return _get_database().get_all_pathogens()


def get_pathogens_by_threat_level(level: ThreatLevel) -> List[PathogenEntry]:
    """
    Get all pathogens of a specific threat level.

    Args:
        level: ThreatLevel enum value.

    Returns:
        List of PathogenEntry objects matching the threat level.
    """
    return _get_database().get_pathogens_by_threat_level(level)


def get_critical_pathogens() -> List[PathogenEntry]:
    """Get all critical threat level pathogens (BSL-3/4)."""
    return _get_database().get_critical_pathogens()


def get_pathogen_by_taxid(taxid: int) -> Optional[PathogenEntry]:
    """
    Look up a pathogen by taxonomy ID.

    Args:
        taxid: NCBI taxonomy ID.

    Returns:
        PathogenEntry if found, None otherwise.
    """
    return _get_database().get_pathogen_by_taxid(taxid)


def get_pathogen_by_name(name: str) -> Optional[PathogenEntry]:
    """
    Look up a pathogen by scientific name (case-insensitive partial match).

    Args:
        name: Scientific name or partial name.

    Returns:
        PathogenEntry if found, None otherwise.
    """
    return _get_database().get_pathogen_by_name(name)


def _database_taxids_are_ncbi() -> bool:
    """Whether a raw NCBI-taxid comparison against this database means anything.

    Mirrors WatchlistManager._database_taxids_are_ncbi: False whenever it
    cannot be established. This path (the Alerts panel and the dashboard's
    exception fallback) previously compared report taxids straight against
    the NCBI-keyed pathogen database with no profile consult, so on a
    remapped-taxid database a colliding taxid raised an alert for the wrong
    organism (2026-08-17 reaudit, G3).
    """
    try:
        from nanometa_live.core.taxonomy.taxid_mapping import (
            get_mapping_collection,
        )
        collection = get_mapping_collection()
        return bool(collection and collection.profile.taxids_are_ncbi)
    except (ImportError, AttributeError):
        return False


def check_for_dangerous_pathogens(
    detected_organisms: List[Dict[str, Any]],
    custom_watchlist: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Check a list of detected organisms against the dangerous pathogen database.

    This function compares detected organisms against both the built-in pathogen
    database and any user-defined custom watchlist. It returns detailed alert
    information for any matches that exceed their alert threshold.

    Args:
        detected_organisms: List of dicts with 'taxid', 'name', 'reads' keys.
        custom_watchlist: Optional additional watchlist from user config.

    Returns:
        List of detected dangerous pathogens with full information including:
        - taxid: NCBI taxonomy ID
        - name: Scientific name
        - common_name: Common/disease name
        - reads: Number of reads detected
        - abundance: Relative abundance percentage
        - threat_level: critical, high, moderate, low
        - bsl: Biosafety level (1-4)
        - category: CDC/WHO category
        - notes: Additional information
        - action_required: Recommended action
        - source: 'database' or 'custom_watchlist'
    """
    # Get database with custom watchlist merged
    # Note: Use 'is not None' to distinguish between None (no watchlist)
    # and [] (empty watchlist means no alerts wanted)
    if custom_watchlist is not None:
        dangerous_db = _merged_pathogen_db(custom_watchlist)
    else:
        dangerous_db = _get_database().get_all_pathogens()

    alerts = []

    # Build custom watchlist lookup for entries not in database
    custom_lookup: Dict[Any, Dict[str, Any]] = {}
    if custom_watchlist is not None:
        for item in custom_watchlist:
            taxid = item.get("taxid")
            name = item.get("name", "").lower().strip()
            if taxid:
                custom_lookup[taxid] = item
            if name:
                custom_lookup[name] = item

    db_is_ncbi = _database_taxids_are_ncbi()

    for organism in detected_organisms:
        taxid = organism.get("taxid")
        name = organism.get("name", "").lower().strip()
        reads = organism.get("reads", 0)

        # Check against dangerous pathogen database. The direct taxid
        # shortcut is only meaningful when the database's taxid space is
        # NCBI; otherwise name matching decides (G3).
        pathogen_entry: Optional[PathogenEntry] = None
        if db_is_ncbi and taxid and taxid in dangerous_db:
            pathogen_entry = dangerous_db[taxid]
        elif name:
            # Name-based lookup. Match when the detected name EQUALS the pathogen
            # name or is MORE specific than it (e.g. "Francisella tularensis
            # subsp. novicida" -> "Francisella tularensis"). Do NOT match when the
            # detected name is a less-specific prefix of the pathogen name: a bare
            # genus read "Bacillus" must not be attributed to "Bacillus anthracis"
            # and raise a false CRITICAL alert.
            for p in dangerous_db.values():
                pname = p.name.lower()
                cname = (p.common_name or "").lower()
                if name == pname or pname in name:
                    pathogen_entry = p
                    break
                if cname and (name == cname or cname in name):
                    pathogen_entry = p
                    break

        # Check against custom watchlist - this takes priority over built-in database
        # because user can enable/disable specific pathogens
        custom_entry = (
            (custom_lookup.get(taxid) if db_is_ncbi else None)
            or custom_lookup.get(name)
        )

        # If pathogen is in custom watchlist, respect its enabled status
        # If custom watchlist exists but pathogen is disabled, skip alerting
        if custom_entry is not None:
            if not custom_entry.get("enabled", True):
                continue  # User explicitly disabled this pathogen

        if pathogen_entry:
            # Check if user has this in their watchlist and it's enabled
            # If watchlist exists but entry is not in it, don't alert (user hasn't enabled it)
            # Use 'is not None' to handle empty list [] as "watchlist enabled but empty"
            if custom_watchlist is not None and custom_entry is None:
                # Watchlist exists but this pathogen is not in it - skip
                continue

            if reads >= pathogen_entry.alert_threshold:
                alerts.append({
                    "taxid": pathogen_entry.taxid,
                    "detected_taxid": taxid,
                    "name": pathogen_entry.name,
                    "common_name": pathogen_entry.common_name,
                    "reads": reads,
                    "abundance": organism.get("abundance", 0.0),
                    "threat_level": pathogen_entry.threat_level.value,
                    "bsl": pathogen_entry.bsl.value if pathogen_entry.bsl else None,
                    "category": pathogen_entry.category,
                    "notes": pathogen_entry.notes,
                    "action_required": pathogen_entry.action_required,
                    "source": "database",
                })
        elif custom_entry:
            # Only alert for enabled entries (default to enabled if not specified)
            if not custom_entry.get("enabled", True):
                continue
            alert_threshold = custom_entry.get("alert_threshold", 10)
            if reads >= alert_threshold:
                alerts.append({
                    "taxid": custom_entry.get("taxid") or taxid,
                    "detected_taxid": taxid,
                    "name": organism.get("name", "Unknown"),
                    "common_name": custom_entry.get("common_name"),
                    "reads": reads,
                    "abundance": organism.get("abundance", 0.0),
                    "threat_level": custom_entry.get("threat_level", "moderate"),
                    "bsl": custom_entry.get("bsl_level") or custom_entry.get("bsl"),
                    "category": "Custom Watchlist",
                    "notes": custom_entry.get("notes", ""),
                    "action_required": custom_entry.get(
                        "action_required",
                        "Review and follow laboratory protocols",
                    ),
                    "source": "custom_watchlist",
                })

    # Sort by threat level (critical first)
    threat_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "unknown": 4}
    alerts.sort(key=lambda x: threat_order.get(x.get("threat_level", "unknown"), 5))

    return alerts


def export_watchlist_template() -> List[Dict[str, Any]]:
    """
    Export a template for custom watchlist configuration.

    Returns a list of example pathogen entries that can be used as a template
    for the species_of_interest section in config.yaml.

    Returns:
        List of dicts suitable for config.yaml species_of_interest.
    """
    critical = get_critical_pathogens()

    template = []
    for pathogen in critical[:5]:  # Top 5 critical pathogens as example
        template.append({
            "taxid": pathogen.taxid,
            "name": pathogen.name,
            "common_name": pathogen.common_name,
            "threat_level": pathogen.threat_level.value,
            "bsl_level": pathogen.bsl.value if pathogen.bsl else None,
            "alert_threshold": pathogen.alert_threshold,
            "notes": pathogen.notes,
        })

    return template


def reload_database() -> bool:
    """
    Reload the pathogen database from YAML files.

    Useful after modifying the pathogens.yaml file or when testing.

    Returns:
        True if reload succeeded, False otherwise.
    """
    global _database
    clear_cache()
    _database = None
    try:
        _database = get_pathogen_database(force_reload=True)
        return True
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.exception(f"Failed to reload pathogen database: {e}")
        return False

