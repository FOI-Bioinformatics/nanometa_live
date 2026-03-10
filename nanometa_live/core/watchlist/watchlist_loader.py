"""
Watchlist Loader for Nanometa Live.

This module handles loading watchlist files from multiple locations:
1. Project directory: <project_dir>/watchlists/
2. User directory: ~/.nanometa/watchlists/
3. Built-in: core/config/data/watchlists/

Project watchlists take precedence over user defaults, which take
precedence over built-in watchlists.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


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
    common_name: Optional[str] = None
    threat_level: str = "moderate"
    bsl_level: Optional[int] = None
    category: Optional[str] = None
    alert_threshold: int = 10
    action_required: str = "Follow laboratory biosafety protocols"
    notes: str = ""


class WatchlistLoader:
    """
    Loader for watchlist files from multiple locations.

    Searches directories in order of precedence:
    1. Project directory watchlists (highest priority)
    2. User home directory watchlists
    3. Built-in watchlists (lowest priority)
    """

    # Default search paths
    BUILTIN_SUBDIR = Path("core/config/data/watchlists")
    USER_SUBDIR = Path(".nanometa/watchlists")
    PROJECT_SUBDIR = Path("watchlists")

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        app_root: Optional[Path] = None
    ):
        """
        Initialize the watchlist loader.

        Args:
            project_dir: Project directory to search for custom watchlists
            app_root: Application root directory (for built-in watchlists)
        """
        self._project_dir = project_dir
        self._app_root = app_root or self._find_app_root()
        self._cached_watchlists: Dict[str, WatchlistMetadata] = {}
        self._loaded_pathogens: Dict[str, List[WatchlistPathogenEntry]] = {}

    def _find_app_root(self) -> Path:
        """Find the application root directory."""
        # Start from this file's location
        current = Path(__file__).resolve()
        # Go up to nanometa_live package root
        while current.name != "nanometa_live" and current.parent != current:
            current = current.parent
        return current

    def set_project_dir(self, project_dir: Path) -> None:
        """Set the project directory."""
        self._project_dir = Path(project_dir) if project_dir else None
        # Clear cache when project changes
        self._cached_watchlists.clear()
        self._loaded_pathogens.clear()

    def get_search_paths(self) -> List[Tuple[Path, str]]:
        """
        Get ordered list of paths to search for watchlist files.

        Returns:
            List of (path, source_type) tuples
        """
        paths = []

        # 1. Project directory (highest priority)
        if self._project_dir:
            project_watchlists = self._project_dir / self.PROJECT_SUBDIR
            if project_watchlists.exists():
                paths.append((project_watchlists, "project"))

        # 2. User home directory
        home = Path.home()
        user_watchlists = home / self.USER_SUBDIR
        if user_watchlists.exists():
            paths.append((user_watchlists, "user"))

        # 3. Built-in watchlists
        builtin_watchlists = self._app_root / self.BUILTIN_SUBDIR
        if builtin_watchlists.exists():
            paths.append((builtin_watchlists, "builtin"))

        return paths

    def discover_watchlists(self) -> List[WatchlistMetadata]:
        """
        Discover all available watchlist files.

        Returns:
            List of WatchlistMetadata for each discovered watchlist,
            sorted by source priority (project > user > builtin)
        """
        discovered = {}  # id -> WatchlistMetadata (later sources override)
        search_paths = self.get_search_paths()

        # Process in reverse order so higher priority overwrites
        for search_path, source in reversed(search_paths):
            if not search_path.exists():
                continue

            for file_path in search_path.glob("*.yaml"):
                if file_path.name.startswith("."):
                    continue

                try:
                    metadata = self._read_metadata(file_path, source)
                    if metadata:
                        discovered[metadata.id] = metadata
                except Exception as e:
                    logger.warning(f"Error reading watchlist {file_path}: {e}")

            # Also check for .yml files
            for file_path in search_path.glob("*.yml"):
                if file_path.name.startswith("."):
                    continue

                try:
                    metadata = self._read_metadata(file_path, source)
                    if metadata:
                        discovered[metadata.id] = metadata
                except Exception as e:
                    logger.warning(f"Error reading watchlist {file_path}: {e}")

        self._cached_watchlists = discovered
        return list(discovered.values())

    def _read_metadata(self, file_path: Path, source: str) -> Optional[WatchlistMetadata]:
        """Read metadata from a watchlist file without loading all pathogens."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                return None

            # Extract metadata
            metadata_section = data.get("metadata", {})
            pathogens = data.get("pathogens", [])

            watchlist_id = file_path.stem  # filename without extension

            # Gather categories from pathogens
            categories = set()
            for p in pathogens:
                if cat := p.get("category"):
                    categories.add(cat)

            return WatchlistMetadata(
                id=watchlist_id,
                name=metadata_section.get("name", watchlist_id.replace("_", " ").title()),
                description=metadata_section.get("description", ""),
                source=source,
                file_path=file_path,
                pathogen_count=len(pathogens),
                version=str(data.get("version", "1.0")),
                taxonomy_support=data.get("taxonomy_support", ["ncbi", "gtdb"]),
                categories=sorted(categories)
            )

        except Exception as e:
            logger.error(f"Error reading metadata from {file_path}: {e}")
            return None

    def load_watchlist(self, watchlist_id: str) -> List[WatchlistPathogenEntry]:
        """
        Load pathogens from a specific watchlist.

        Args:
            watchlist_id: Watchlist ID (filename without extension)

        Returns:
            List of WatchlistPathogenEntry objects
        """
        # Check cache
        if watchlist_id in self._loaded_pathogens:
            return self._loaded_pathogens[watchlist_id]

        # Find the watchlist file
        if watchlist_id not in self._cached_watchlists:
            self.discover_watchlists()

        if watchlist_id not in self._cached_watchlists:
            logger.warning(f"Watchlist not found: {watchlist_id}")
            return []

        metadata = self._cached_watchlists[watchlist_id]
        pathogens = self._load_pathogens_from_file(metadata.file_path)

        self._loaded_pathogens[watchlist_id] = pathogens
        return pathogens

    def _load_pathogens_from_file(self, file_path: Path) -> List[WatchlistPathogenEntry]:
        """Load pathogen entries from a YAML file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                return []

            pathogens_data = data.get("pathogens", [])
            pathogens = []

            for p_data in pathogens_data:
                try:
                    entry = WatchlistPathogenEntry(
                        name=p_data.get("name", "Unknown"),
                        names_alt=p_data.get("names_alt", []),
                        taxid_ncbi=p_data.get("taxid_ncbi") or p_data.get("taxid"),
                        common_name=p_data.get("common_name"),
                        threat_level=p_data.get("threat_level", "moderate"),
                        bsl_level=p_data.get("bsl_level"),
                        category=p_data.get("category"),
                        alert_threshold=p_data.get("alert_threshold", 10),
                        action_required=p_data.get("action_required", "Follow laboratory biosafety protocols"),
                        notes=p_data.get("notes", "")
                    )
                    pathogens.append(entry)
                except Exception as e:
                    logger.warning(f"Error parsing pathogen entry: {e}")

            return pathogens

        except Exception as e:
            logger.error(f"Error loading pathogens from {file_path}: {e}")
            return []

    def get_builtin_watchlists(self) -> List[WatchlistMetadata]:
        """Get only built-in watchlists."""
        if not self._cached_watchlists:
            self.discover_watchlists()
        return [m for m in self._cached_watchlists.values() if m.source == "builtin"]

    def get_user_watchlists(self) -> List[WatchlistMetadata]:
        """Get only user-defined watchlists."""
        if not self._cached_watchlists:
            self.discover_watchlists()
        return [m for m in self._cached_watchlists.values() if m.source == "user"]

    def get_project_watchlists(self) -> List[WatchlistMetadata]:
        """Get only project-specific watchlists."""
        if not self._cached_watchlists:
            self.discover_watchlists()
        return [m for m in self._cached_watchlists.values() if m.source == "project"]

    def validate_file(self, file_path: Path) -> Tuple[bool, List[str]]:
        """
        Validate a watchlist YAML file.

        Args:
            file_path: Path to the YAML file

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if not file_path.exists():
            return False, [f"File not found: {file_path}"]

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return False, [f"Invalid YAML syntax: {e}"]

        if not data:
            return False, ["Empty file"]

        # Check for required sections
        if "pathogens" not in data:
            errors.append("Missing 'pathogens' section")

        pathogens = data.get("pathogens", [])
        if not isinstance(pathogens, list):
            errors.append("'pathogens' must be a list")
        elif not pathogens:
            errors.append("No pathogens defined")
        else:
            # Validate pathogen entries
            for i, p in enumerate(pathogens):
                if not isinstance(p, dict):
                    errors.append(f"Pathogen {i+1}: must be a dictionary")
                    continue

                if "name" not in p:
                    errors.append(f"Pathogen {i+1}: missing 'name' field")

                if "threat_level" in p:
                    valid_levels = ["critical", "high", "moderate", "low"]
                    if p["threat_level"] not in valid_levels:
                        errors.append(f"Pathogen {i+1}: invalid threat_level '{p['threat_level']}'")

                if "bsl_level" in p:
                    if not isinstance(p["bsl_level"], int) or p["bsl_level"] not in [1, 2, 3, 4]:
                        errors.append(f"Pathogen {i+1}: bsl_level must be 1, 2, 3, or 4")

        return len(errors) == 0, errors

    def import_watchlist(
        self,
        source_path: Path,
        destination: str = "user"
    ) -> Tuple[bool, str]:
        """
        Import a watchlist file to user or project directory.

        Args:
            source_path: Path to the source YAML file
            destination: "user" or "project"

        Returns:
            Tuple of (success, message)
        """
        # Validate first
        is_valid, errors = self.validate_file(source_path)
        if not is_valid:
            return False, f"Invalid watchlist file: {'; '.join(errors)}"

        # Determine destination directory
        if destination == "project" and self._project_dir:
            dest_dir = self._project_dir / self.PROJECT_SUBDIR
        else:
            dest_dir = Path.home() / self.USER_SUBDIR

        # Create directory if needed
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy file
        dest_path = dest_dir / source_path.name
        try:
            import shutil
            shutil.copy2(source_path, dest_path)

            # Clear cache to pick up new file
            self._cached_watchlists.clear()
            self._loaded_pathogens.clear()

            return True, f"Imported watchlist to {dest_path}"
        except Exception as e:
            return False, f"Failed to import: {e}"

    def create_user_watchlist_dir(self) -> Path:
        """Create the user watchlist directory if it does not exist."""
        user_dir = Path.home() / self.USER_SUBDIR
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir


# Module-level singleton
_watchlist_loader: Optional[WatchlistLoader] = None


def get_watchlist_loader(project_dir: Optional[Path] = None) -> WatchlistLoader:
    """Get the global WatchlistLoader instance."""
    global _watchlist_loader
    if _watchlist_loader is None:
        _watchlist_loader = WatchlistLoader(project_dir=project_dir)
    elif project_dir:
        _watchlist_loader.set_project_dir(project_dir)
    return _watchlist_loader


def reset_watchlist_loader() -> None:
    """Reset the global WatchlistLoader instance."""
    global _watchlist_loader
    _watchlist_loader = None
