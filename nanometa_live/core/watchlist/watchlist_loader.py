"""
Watchlist Loader for Nanometa Live.

This module handles loading watchlist files from multiple locations:
1. Project directory: <project_dir>/watchlists/
2. User directory: NanometaPaths.watchlists (``<data_dir>/watchlists``, or
   ``<project_dir>/.nanometa/watchlists`` when a project is set)
3. Built-in: core/config/data/watchlists/

Project watchlists take precedence over user defaults, which take
precedence over built-in watchlists.
"""

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from nanometa_live.core.config.pathogen_loader import default_alert_threshold

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
    PROJECT_SUBDIR = Path("watchlists")

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        app_root: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ):
        """
        Initialize the watchlist loader.

        Args:
            project_dir: Project directory to search for custom watchlists
            app_root: Application root directory (for built-in watchlists)
            user_dir: Operator watchlist directory. Defaults to the one
                :func:`get_watchlists_dir_from_env` resolves, so the loader,
                the GUI upload callback, and the bundle exporter agree on a
                single location under ``--data-dir`` / ``--project-dir``.
        """
        self._project_dir = project_dir
        self._app_root = app_root or self._find_app_root()
        self._user_dir = Path(user_dir) if user_dir else None
        self._cached_watchlists: Dict[str, WatchlistMetadata] = {}
        self._loaded_pathogens: Dict[str, List[WatchlistPathogenEntry]] = {}

    @property
    def user_watchlist_dir(self) -> Path:
        """Directory holding operator-uploaded watchlists.

        Resolved lazily rather than at construction so a loader built before
        the CLI set ``NANOMETA_DATA_DIR`` still lands in the right place.
        """
        if self._user_dir is not None:
            return self._user_dir
        from nanometa_live.core.utils.paths import get_watchlists_dir_from_env
        return Path(get_watchlists_dir_from_env())

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

        # 2. Operator watchlist directory (uploads land here)
        user_watchlists = self.user_watchlist_dir
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
                except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError) as e:
                    logger.exception(f"Error reading watchlist {file_path}: {e}")

            # Also check for .yml files
            for file_path in search_path.glob("*.yml"):
                if file_path.name.startswith("."):
                    continue

                try:
                    metadata = self._read_metadata(file_path, source)
                    if metadata:
                        discovered[metadata.id] = metadata
                except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError) as e:
                    logger.exception(f"Error reading watchlist {file_path}: {e}")

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

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            logger.exception(f"Error reading metadata from {file_path}: {e}")
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
                        db_taxid=(p_data.get("db_taxid") or p_data.get("kraken_taxid")
                                  or p_data.get("taxid_custom") or p_data.get("taxid_gtdb")),
                        common_name=p_data.get("common_name"),
                        threat_level=p_data.get("threat_level", "moderate"),
                        bsl_level=p_data.get("bsl_level"),
                        category=p_data.get("category"),
                        alert_threshold=p_data.get("alert_threshold"),
                        action_required=p_data.get("action_required", "Follow laboratory biosafety protocols"),
                        notes=p_data.get("notes", ""),
                        organism_type=p_data.get("organism_type"),
                        annotation=p_data.get("annotation", "")
                    )
                    pathogens.append(entry)
                except (TypeError, ValueError, AttributeError) as e:
                    logger.exception(f"Error parsing pathogen entry: {e}")

            return pathogens

        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            logger.exception(f"Error loading pathogens from {file_path}: {e}")
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

    @staticmethod
    def find_entries_without_taxid(file_path: Path) -> List[str]:
        """Return the names of pathogen entries that carry no taxonomy ID.

        A taxid is not required for a file to be structurally valid, and an
        entry without one is loaded, displayed, and counted like any other.
        It can never match a Kraken2 report, though: matching keys on
        ``taxid_ncbi`` / ``db_taxid``, and an entry lacking both is assigned a
        synthetic key by ``_stable_pseudo_taxid`` that no classifier will ever
        emit. Such an entry is therefore a permanently silent watch item --
        worth telling the operator about at upload time.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return []

        if not isinstance(data, dict):
            return []

        missing = []
        for i, p in enumerate(data.get("pathogens") or []):
            if not isinstance(p, dict):
                continue
            if p.get("taxid_ncbi") is None and p.get("db_taxid") is None:
                missing.append(str(p.get("name") or f"entry {i + 1}"))
        return missing

    @staticmethod
    def sanitize_upload_name(file_name: str) -> Optional[str]:
        """Reduce an untrusted upload name to a bare, usable filename.

        ``file_name`` carries the browser-supplied dcc.Upload name, so
        "../evil.yaml" would otherwise write outside the watchlists
        directory, and an absolute path would ignore the destination
        entirely. Reducing rather than refusing keeps a well-meaning upload
        working -- the file is still imported, just not where the string
        asked. Returns None when nothing usable remains.

        This is the single sanitizer for upload names: ``import_watchlist``
        and the GUI upload callback must both use it, or they disagree
        about where the file landed (2026-08-17 audit, finding W1: the
        callback re-derived the destination from the raw name, so a
        sanitizer-changed upload was imported but never activated in the
        session, with a success alert either way).
        """
        name = Path(file_name).name if file_name else ""
        if not name or name in (".", ".."):
            return None
        return name

    def import_watchlist(
        self,
        source_path: Path,
        destination: str = "user",
        overwrite: bool = False,
        file_name: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Import a watchlist file to user or project directory.

        Args:
            source_path: Path to the source YAML file
            destination: "user" or "project"
            overwrite: Replace an existing file of the same name. Without
                this an existing destination file, or a name that shadows a
                built-in watchlist, is refused rather than silently replaced.
            file_name: Destination file name. Defaults to the source file
                name; pass the operator's original upload name when the
                source is a temporary file.

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
            dest_dir = self.user_watchlist_dir

        # Create directory if needed
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_name = self.sanitize_upload_name(file_name or source_path.name)
        if dest_name is None:
            return False, (
                f"'{file_name}' is not a usable watchlist file name."
            )
        dest_path = dest_dir / dest_name
        watchlist_id = Path(dest_name).stem

        if not overwrite:
            refusal = self._import_collision(dest_dir, dest_name, watchlist_id)
            if refusal:
                return False, refusal
        try:
            shutil.copy2(source_path, dest_path)

            # Clear cache to pick up new file
            self._cached_watchlists.clear()
            self._loaded_pathogens.clear()

            return True, f"Imported watchlist to {dest_path}"
        except (FileNotFoundError, PermissionError, OSError, shutil.SameFileError) as e:
            logger.exception(f"Failed to import watchlist: {e}")
            return False, f"Failed to import: {e}"

    def _import_collision(
        self, dest_dir: Path, dest_name: str, watchlist_id: str
    ) -> Optional[str]:
        """Why this import must be refused, or None if it is safe.

        A watchlist is keyed by its file stem, so two different files with the
        same stem are the same watchlist as far as discovery is concerned: the
        copy would replace the operator's earlier upload, or shadow a built-in
        list, with no indication that anything was lost.
        """
        if (dest_dir / dest_name).exists():
            return (
                f"A watchlist file named '{dest_name}' already exists in "
                f"{dest_dir}. Rename the file, or confirm the replacement."
            )

        # Same stem, different extension. This check used to apply only to
        # built-in names, so 'pathogens.yml' landing beside an existing
        # 'pathogens.yaml' passed -- and since discovery keys by stem, one of
        # them then vanished from every list, count and toggle while both
        # imports reported success.
        existing = next(
            (
                p for p in dest_dir.iterdir()
                if p.suffix in (".yaml", ".yml")
                and p.stem == watchlist_id
                and p.name != dest_name
            ),
            None,
        )
        if existing is not None:
            return (
                f"'{existing.name}' already provides the watchlist "
                f"'{watchlist_id}' in {dest_dir}. A watchlist is identified by "
                f"its file name without the extension, so importing "
                f"'{dest_name}' would hide it. Rename the file, or confirm the "
                f"replacement."
            )

        builtin_dir = self._app_root / self.BUILTIN_SUBDIR
        if builtin_dir.is_dir():
            builtin_stems = {
                p.stem for p in builtin_dir.iterdir()
                if p.suffix in (".yaml", ".yml")
            }
            if watchlist_id in builtin_stems:
                return (
                    f"'{watchlist_id}' is the name of a built-in watchlist. An "
                    "imported file with this name would take precedence over "
                    "it everywhere without saying so. Rename the file before "
                    "importing."
                )
        return None

    def create_user_watchlist_dir(self) -> Path:
        """Create the user watchlist directory if it does not exist."""
        user_dir = self.user_watchlist_dir
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir


# A synthetic key must never be written to an exported file as if it were an
# NCBI taxid. See core.taxonomy.pseudo_taxid.
from nanometa_live.core.taxonomy.pseudo_taxid import (  # noqa: E402
    PSEUDO_TAXID_BASE,
)


def build_watchlist_yaml(
    entries: List[Dict[str, object]],
    name: str = "Exported watchlist",
    description: str = "",
) -> Dict[str, object]:
    """Assemble a v2.0 watchlist document from serialised watchlist entries.

    Takes the dicts ``WatchlistEntry.to_dict()`` produces and emits the same
    schema the built-in YAML files use, so an exported file can be re-imported
    through the upload control unchanged. Session-only fields (validation
    results, source, watchlist membership) are dropped; they are recomputed on
    load and would otherwise go stale in the file.

    Synthetic keys assigned to name-only entries are not written as
    ``taxid_ncbi`` -- they are internal identifiers, and a downstream reader
    would treat them as real taxonomy IDs.
    """
    pathogens: List[Dict[str, object]] = []
    for e in entries:
        taxid = e.get("taxid")
        entry: Dict[str, object] = {"name": e.get("name", "")}
        if e.get("names_alt"):
            entry["names_alt"] = list(e["names_alt"])
        if isinstance(taxid, int) and taxid < PSEUDO_TAXID_BASE:
            entry["taxid_ncbi"] = taxid
        if e.get("db_taxid"):
            entry["db_taxid"] = e["db_taxid"]
        if e.get("common_name"):
            entry["common_name"] = e["common_name"]
        entry["threat_level"] = e.get("threat_level", "moderate")
        if e.get("bsl_level"):
            entry["bsl_level"] = e["bsl_level"]
        if e.get("category"):
            entry["category"] = e["category"]
        entry["alert_threshold"] = e.get(
            "alert_threshold",
            default_alert_threshold(e.get("threat_level", "moderate")),
        )
        if e.get("action_required"):
            entry["action_required"] = e["action_required"]
        if e.get("organism_type"):
            entry["organism_type"] = e["organism_type"]
        if e.get("annotation"):
            entry["annotation"] = e["annotation"]
        if e.get("notes"):
            entry["notes"] = e["notes"]
        pathogens.append(entry)

    return {
        "version": "2.0",
        "taxonomy_support": ["ncbi", "gtdb"],
        "metadata": {
            "name": name,
            "description": description or (
                "Exported from the Nanometa Live watchlist tab."
            ),
        },
        "pathogens": pathogens,
    }


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
