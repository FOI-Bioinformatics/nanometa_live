"""
Pathogen Database Loader for Nanometa Live.

Loads pathogen watchlists from YAML configuration files with support for:
- Built-in default pathogen database
- User-configurable custom watchlists
- Validation of YAML structure
- Caching for performance optimization

The loader implements a layered configuration approach:
1. Built-in defaults (pathogens.yaml in package)
2. User overrides via analysis config (species_of_interest)
3. External watchlist files (optional)
"""

import logging
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


class ThreatLevel(Enum):
    """Threat level classification for pathogens."""

    CRITICAL = "critical"  # BSL-3/4, immediate action required
    HIGH = "high"  # BSL-2+, significant concern
    MODERATE = "moderate"  # Monitor closely
    LOW = "low"  # Common, generally not dangerous
    UNKNOWN = "unknown"  # Not characterized


class BiosaftyLevel(Enum):
    """Biosafety level classification."""

    BSL1 = 1
    BSL2 = 2
    BSL3 = 3
    BSL4 = 4


@dataclass
class PathogenEntry:
    """Information about a pathogen for alert purposes."""

    taxid: int
    name: str
    common_name: Optional[str] = None
    threat_level: ThreatLevel = ThreatLevel.UNKNOWN
    bsl: Optional[BiosaftyLevel] = None
    category: Optional[str] = None  # CDC Category A/B/C, WHO-Critical, etc.
    notes: str = ""
    alert_threshold: int = 10  # Minimum reads to trigger alert
    action_required: str = "Follow laboratory biosafety protocols"
    organism_type: Optional[str] = None  # virus / bacteria / fungi / ...
    annotation: str = ""  # Free-text note shown next to the species name

    def to_dict(self) -> Dict[str, Any]:
        """Convert PathogenEntry to dictionary representation."""
        return {
            "taxid": self.taxid,
            "name": self.name,
            "common_name": self.common_name,
            "threat_level": self.threat_level.value,
            "bsl_level": self.bsl.value if self.bsl else None,
            "category": self.category,
            "notes": self.notes,
            "alert_threshold": self.alert_threshold,
            "action_required": self.action_required,
            "organism_type": self.organism_type,
            "annotation": self.annotation,
        }


class PathogenLoaderError(Exception):
    """Exception raised for pathogen loader errors."""

    pass


class PathogenValidationError(PathogenLoaderError):
    """Exception raised for pathogen data validation errors."""

    pass


def _get_default_database_path() -> Path:
    """
    Get the path to the built-in pathogen database.

    Returns:
        Path to the default pathogens.yaml file.
    """
    module_dir = Path(__file__).parent
    return module_dir / "data" / "pathogens.yaml"


def _parse_threat_level(value: str) -> ThreatLevel:
    """
    Parse threat level string to enum.

    Args:
        value: String representation of threat level.

    Returns:
        ThreatLevel enum value.
    """
    value_lower = value.lower().strip()
    mapping = {
        "critical": ThreatLevel.CRITICAL,
        "high": ThreatLevel.HIGH,
        "high_risk": ThreatLevel.HIGH,
        "moderate": ThreatLevel.MODERATE,
        "medium": ThreatLevel.MODERATE,
        "low": ThreatLevel.LOW,
        "info": ThreatLevel.LOW,
        "unknown": ThreatLevel.UNKNOWN,
    }
    return mapping.get(value_lower, ThreatLevel.UNKNOWN)


def _parse_bsl_level(value: Optional[Union[int, str]]) -> Optional[BiosaftyLevel]:
    """
    Parse biosafety level to enum.

    Args:
        value: Integer or string representation of BSL level.

    Returns:
        BiosaftyLevel enum value or None.
    """
    if value is None:
        return None

    try:
        level = int(value)
        mapping = {
            1: BiosaftyLevel.BSL1,
            2: BiosaftyLevel.BSL2,
            3: BiosaftyLevel.BSL3,
            4: BiosaftyLevel.BSL4,
        }
        return mapping.get(level)
    except (ValueError, TypeError):
        return None


def _validate_pathogen_entry(entry: Dict[str, Any], index: int) -> List[str]:
    """
    Validate a single pathogen entry from YAML.

    Args:
        entry: Dictionary containing pathogen data.
        index: Index of entry in the list (for error messages).

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    # Required fields
    if "taxid" not in entry:
        errors.append(f"Entry {index}: missing required field 'taxid'")
    elif not isinstance(entry["taxid"], int):
        errors.append(f"Entry {index}: 'taxid' must be an integer")

    if "name" not in entry:
        errors.append(f"Entry {index}: missing required field 'name'")
    elif not isinstance(entry["name"], str) or not entry["name"].strip():
        errors.append(f"Entry {index}: 'name' must be a non-empty string")

    # Optional fields with type validation
    if "threat_level" in entry:
        valid_levels = ["critical", "high", "high_risk", "moderate", "medium", "low", "info", "unknown"]
        if entry["threat_level"].lower() not in valid_levels:
            errors.append(
                f"Entry {index}: 'threat_level' must be one of {valid_levels}"
            )

    if "bsl_level" in entry:
        try:
            bsl = int(entry["bsl_level"])
            if bsl not in [1, 2, 3, 4]:
                errors.append(f"Entry {index}: 'bsl_level' must be 1, 2, 3, or 4")
        except (ValueError, TypeError):
            errors.append(f"Entry {index}: 'bsl_level' must be an integer")

    if "alert_threshold" in entry:
        try:
            threshold = int(entry["alert_threshold"])
            if threshold < 0:
                errors.append(f"Entry {index}: 'alert_threshold' must be non-negative")
        except (ValueError, TypeError):
            errors.append(f"Entry {index}: 'alert_threshold' must be an integer")

    return errors


def _dict_to_pathogen_entry(
    data: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None
) -> PathogenEntry:
    """
    Convert a dictionary to a PathogenEntry object.

    Args:
        data: Dictionary containing pathogen data.
        defaults: Optional default values to apply.

    Returns:
        PathogenEntry object.
    """
    defaults = defaults or {}

    return PathogenEntry(
        taxid=int(data["taxid"]),
        name=data["name"],
        common_name=data.get("common_name"),
        threat_level=_parse_threat_level(
            data.get("threat_level", defaults.get("threat_level", "moderate"))
        ),
        bsl=_parse_bsl_level(data.get("bsl_level", defaults.get("bsl_level"))),
        category=data.get("category"),
        notes=data.get("notes", ""),
        alert_threshold=int(
            data.get("alert_threshold", defaults.get("alert_threshold", 10))
        ),
        action_required=data.get(
            "action_required",
            defaults.get("action_required", "Follow laboratory biosafety protocols"),
        ),
        organism_type=data.get("organism_type", defaults.get("organism_type")),
        annotation=data.get("annotation", defaults.get("annotation", "")),
    )


class PathogenDatabase:
    """
    Manages pathogen database loading, caching, and lookups.

    This class provides a unified interface for accessing pathogen information
    from the built-in database and user-defined watchlists.
    """

    def __init__(
        self,
        database_path: Optional[Union[str, Path]] = None,
        user_watchlist: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Initialize the pathogen database.

        Args:
            database_path: Path to custom pathogen database YAML file.
                          If None, uses built-in default database.
            user_watchlist: Optional list of user-defined species to watch.
                           These are merged with the database entries.
        """
        self._database_path = Path(database_path) if database_path else None
        self._user_watchlist = user_watchlist or []
        self._pathogens: Dict[int, PathogenEntry] = {}
        self._loaded = False
        self._load_errors: List[str] = []

    def load(self, force_reload: bool = False) -> bool:
        """
        Load the pathogen database.

        Args:
            force_reload: If True, reload even if already loaded.

        Returns:
            True if loading succeeded, False otherwise.
        """
        if self._loaded and not force_reload:
            return True

        self._pathogens = {}
        self._load_errors = []

        try:
            # Load built-in database
            default_path = _get_default_database_path()
            if default_path.exists():
                self._load_yaml_database(default_path)
            else:
                logger.warning(
                    f"Built-in pathogen database not found at {default_path}"
                )

            # Load custom database if specified
            if self._database_path and self._database_path.exists():
                self._load_yaml_database(self._database_path, override=True)
            elif self._database_path:
                logger.warning(
                    f"Custom pathogen database not found at {self._database_path}"
                )

            # Add user watchlist entries
            self._load_user_watchlist()

            self._loaded = True
            # DEBUG, not INFO: dashboard polling instantiates a fresh
            # PathogenDatabase per check_for_dangerous_pathogens call
            # (see pathogen_database.py), so this fires every ~30s
            # during a run. The count is recoverable from the log file
            # if needed.
            logger.debug(f"Loaded {len(self._pathogens)} pathogens into database")
            return True

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, KeyError, ValueError, TypeError, AttributeError) as e:
            logger.exception(f"Failed to load pathogen database: {e}")
            self._load_errors.append(str(e))
            return False

    def _load_yaml_database(
        self, path: Path, override: bool = False
    ) -> None:
        """
        Load pathogens from a YAML database file.

        Args:
            path: Path to the YAML file.
            override: If True, override existing entries with same taxid.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                logger.warning(f"Empty pathogen database at {path}")
                return

            # Get defaults
            defaults = data.get("defaults", {})

            # Load pathogens from each threat level category
            pathogens_section = data.get("pathogens", {})

            for threat_level, entries in pathogens_section.items():
                if not isinstance(entries, list):
                    continue

                for idx, entry in enumerate(entries):
                    # Validate entry
                    errors = _validate_pathogen_entry(entry, idx)
                    if errors:
                        for error in errors:
                            logger.warning(f"Validation error in {path}: {error}")
                            self._load_errors.append(error)
                        continue

                    # Convert to PathogenEntry
                    pathogen = _dict_to_pathogen_entry(entry, defaults)
                    taxid = pathogen.taxid

                    # Add or override
                    if taxid not in self._pathogens or override:
                        self._pathogens[taxid] = pathogen

            logger.debug(f"Loaded pathogens from {path}")

        except yaml.YAMLError as e:
            error_msg = f"YAML parsing error in {path}: {e}"
            logger.error(error_msg)
            self._load_errors.append(error_msg)
            raise PathogenLoaderError(error_msg) from e

    def _load_user_watchlist(self) -> None:
        """Load user-defined watchlist entries."""
        if not self._user_watchlist:
            return

        defaults = {
            "threat_level": "moderate",
            "alert_threshold": 10,
            "action_required": "Review and follow laboratory protocols",
        }

        for idx, entry in enumerate(self._user_watchlist):
            # Skip entries without taxid
            if "taxid" not in entry:
                # Try to match by name
                name = entry.get("name", "").strip()
                if name:
                    # Add as name-based entry (will be matched during lookup)
                    logger.debug(f"User watchlist entry without taxid: {name}")
                continue

            errors = _validate_pathogen_entry(entry, idx)
            if errors:
                for error in errors:
                    logger.warning(f"User watchlist validation error: {error}")
                continue

            pathogen = _dict_to_pathogen_entry(entry, defaults)
            pathogen.category = entry.get("category", "Custom Watchlist")

            # User entries always override
            self._pathogens[pathogen.taxid] = pathogen

        logger.debug(f"Loaded {len(self._user_watchlist)} user watchlist entries")

    def get_all_pathogens(self) -> Dict[int, PathogenEntry]:
        """
        Get all pathogens in the database.

        Returns:
            Dictionary mapping taxid to PathogenEntry.
        """
        if not self._loaded:
            self.load()
        return self._pathogens.copy()

    def get_pathogen_by_taxid(self, taxid: int) -> Optional[PathogenEntry]:
        """
        Look up a pathogen by taxonomy ID.

        Args:
            taxid: NCBI taxonomy ID.

        Returns:
            PathogenEntry if found, None otherwise.
        """
        if not self._loaded:
            self.load()
        return self._pathogens.get(taxid)

    def get_pathogen_by_name(self, name: str) -> Optional[PathogenEntry]:
        """
        Look up a pathogen by scientific name (case-insensitive partial match).

        Args:
            name: Scientific name or partial name.

        Returns:
            PathogenEntry if found, None otherwise.
        """
        if not self._loaded:
            self.load()

        name_lower = name.lower().strip()

        for pathogen in self._pathogens.values():
            if name_lower in pathogen.name.lower():
                return pathogen
            if pathogen.common_name and name_lower in pathogen.common_name.lower():
                return pathogen

        return None

    def get_pathogens_by_threat_level(
        self, level: ThreatLevel
    ) -> List[PathogenEntry]:
        """
        Get all pathogens of a specific threat level.

        Args:
            level: ThreatLevel enum value.

        Returns:
            List of PathogenEntry objects matching the threat level.
        """
        if not self._loaded:
            self.load()
        return [p for p in self._pathogens.values() if p.threat_level == level]

    def get_critical_pathogens(self) -> List[PathogenEntry]:
        """Get all critical threat level pathogens (BSL-3/4)."""
        return self.get_pathogens_by_threat_level(ThreatLevel.CRITICAL)

    def get_high_risk_pathogens(self) -> List[PathogenEntry]:
        """Get all high risk pathogens."""
        return self.get_pathogens_by_threat_level(ThreatLevel.HIGH)

    def get_load_errors(self) -> List[str]:
        """Get list of errors encountered during loading."""
        return self._load_errors.copy()

    def is_loaded(self) -> bool:
        """Check if database is loaded."""
        return self._loaded

    def reload(self) -> bool:
        """Force reload the database."""
        self._loaded = False
        return self.load(force_reload=True)


# Module-level cached database instance
_cached_database: Optional[PathogenDatabase] = None


def get_pathogen_database(
    user_watchlist: Optional[List[Dict[str, Any]]] = None,
    force_reload: bool = False,
) -> PathogenDatabase:
    """
    Get the global pathogen database instance.

    This function provides a cached singleton instance of the pathogen database
    for efficient repeated access.

    Args:
        user_watchlist: Optional list of user-defined species to watch.
        force_reload: If True, create a new database instance.

    Returns:
        PathogenDatabase instance.
    """
    global _cached_database

    if _cached_database is None or force_reload:
        _cached_database = PathogenDatabase(user_watchlist=user_watchlist)
        _cached_database.load()

    return _cached_database


def clear_cache() -> None:
    """Clear the cached database instance."""
    global _cached_database
    _cached_database = None


@lru_cache(maxsize=1)
def load_builtin_pathogens() -> Dict[int, PathogenEntry]:
    """
    Load and cache the built-in pathogen database.

    This is a convenience function for quick access to the default database
    without user customization.

    Returns:
        Dictionary mapping taxid to PathogenEntry.
    """
    db = PathogenDatabase()
    db.load()
    return db.get_all_pathogens()


def validate_watchlist_yaml(path: Union[str, Path]) -> Tuple[bool, List[str]]:
    """
    Validate a pathogen watchlist YAML file.

    Args:
        path: Path to the YAML file to validate.

    Returns:
        Tuple of (is_valid, list_of_errors).
    """
    path = Path(path)
    errors = []

    if not path.exists():
        return False, [f"File not found: {path}"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, [f"YAML parsing error: {e}"]

    if not data:
        return False, ["Empty YAML file"]

    if not isinstance(data, dict):
        return False, ["Root element must be a dictionary"]

    # Validate pathogens section
    pathogens = data.get("pathogens", {})
    if not isinstance(pathogens, dict):
        errors.append("'pathogens' must be a dictionary with threat level keys")

    for threat_level, entries in pathogens.items():
        if not isinstance(entries, list):
            errors.append(f"Pathogens under '{threat_level}' must be a list")
            continue

        for idx, entry in enumerate(entries):
            entry_errors = _validate_pathogen_entry(entry, idx)
            errors.extend(
                [f"{threat_level}[{idx}]: {e}" for e in entry_errors]
            )

    return len(errors) == 0, errors


def export_watchlist_template(
    output_path: Optional[Union[str, Path]] = None,
) -> str:
    """
    Export a template YAML file for custom watchlists.

    Args:
        output_path: Optional path to write the template. If None, returns as string.

    Returns:
        YAML template as string.
    """
    template = """# Custom Pathogen Watchlist Template
# Add your own species of interest to this file
#
# Each entry requires:
#   - taxid: NCBI taxonomy ID (integer)
#   - name: Scientific name (string)
#
# Optional fields:
#   - common_name: Common/disease name
#   - threat_level: critical, high, moderate, low
#   - bsl_level: 1, 2, 3, or 4
#   - category: Classification category
#   - notes: Additional information
#   - alert_threshold: Minimum reads to trigger alert (default: 10)
#   - action_required: Recommended action when detected

version: "1.0"

pathogens:
  # Add your critical pathogens here
  critical:
    - taxid: 0  # Replace with actual NCBI taxonomy ID
      name: "Example critical pathogen"
      common_name: "Example disease"
      threat_level: "critical"
      bsl_level: 3
      notes: "Add your notes here"
      alert_threshold: 5
      action_required: "Contact biosafety officer immediately"

  # Add high-risk pathogens here
  high:
    - taxid: 0
      name: "Example high-risk pathogen"
      threat_level: "high"
      bsl_level: 2
      alert_threshold: 10

  # Add moderate-risk pathogens here
  moderate:
    - taxid: 0
      name: "Example monitored species"
      threat_level: "moderate"
      alert_threshold: 50
"""

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(template)
        logger.info(f"Watchlist template exported to {path}")

    return template
