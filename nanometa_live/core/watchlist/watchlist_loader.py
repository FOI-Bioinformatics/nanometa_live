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
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from nanometa_live.core.config.pathogen_loader import default_alert_threshold
from nanometa_live.core.watchlist.validation.entry_schema import (
    entries_without_taxid as _entries_without_taxid_impl,
    validate_pathogen_entry as _validate_pathogen_entry_impl,
)

logger = logging.getLogger(__name__)


from nanometa_live.core.watchlist.watchlist_models import (  # noqa: F401
    WatchlistMetadata,
    WatchlistPathogenEntry,
)


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
        self._additional_project_dirs: List[Path] = []
        self._app_root = app_root or self._find_app_root()
        self._user_dir = Path(user_dir) if user_dir else None
        self._cached_watchlists: Dict[str, WatchlistMetadata] = {}
        self._loaded_pathogens: Dict[str, List[WatchlistPathogenEntry]] = {}
        # Corpus fingerprint the discovery cache was built against, and the
        # invalid-file sweep cached on the same fingerprint. Discovery used
        # to write _cached_watchlists and never consult it, so every
        # tab-state change re-parsed the whole corpus three times
        # (round-2 audit, 2026-08-22).
        self._cache_fingerprint: Optional[tuple] = None
        self._invalid_files_cache: Optional[
            Tuple[tuple, List[Tuple[str, str]]]] = None

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

    def set_project_dir(
        self,
        project_dir: Path,
        additional_dirs: Optional[List[Path]] = None,
    ) -> None:
        """Set the project directory, plus any further dirs to search.

        ``additional_dirs`` exists for the run's results directory, which
        `import_watchlist` has been treating as "the project" when saving
        operator uploads. It is searched after the project directory, so a
        stem present in both resolves to the project copy. Passing no
        ``additional_dirs`` clears any previously set ones.
        """
        self._project_dir = Path(project_dir) if project_dir else None
        self._additional_project_dirs = [
            Path(d) for d in (additional_dirs or []) if d
        ]
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

        # 1. Project directory (highest priority), then any additional dirs
        #    such as the run's results directory.
        seen = set()
        for candidate in [self._project_dir, *self._additional_project_dirs]:
            if not candidate:
                continue
            project_watchlists = candidate / self.PROJECT_SUBDIR
            resolved = str(project_watchlists)
            if resolved in seen or not project_watchlists.exists():
                continue
            seen.add(resolved)
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

    def _corpus_fingerprint(self) -> tuple:
        """(path, mtime_ns, size) of every watchlist YAML across the tiers.

        One scandir per tier -- cheap enough to run per call, and content-
        derived so nothing can serve a stale discovery.
        """
        entries = []
        for search_path, _source in self.get_search_paths():
            try:
                with os.scandir(search_path) as it:
                    for entry in it:
                        name = entry.name
                        if name.startswith(".") or not (
                            name.endswith(".yaml") or name.endswith(".yml")
                        ):
                            continue
                        try:
                            st = entry.stat()
                            entries.append(
                                (entry.path, st.st_mtime_ns, st.st_size))
                        except OSError:
                            continue
            except OSError:
                continue
        return tuple(sorted(entries))

    def discover_watchlists(self) -> List[WatchlistMetadata]:
        """
        Discover all available watchlist files.

        Serves from the instance cache while the corpus fingerprint is
        unchanged; any file added, removed, or edited in any tier forces a
        rescan.

        Returns:
            List of WatchlistMetadata for each discovered watchlist,
            sorted by source priority (project > user > builtin)
        """
        fingerprint = self._corpus_fingerprint()
        if (self._cached_watchlists
                and fingerprint == self._cache_fingerprint):
            return list(self._cached_watchlists.values())

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
        self._cache_fingerprint = fingerprint
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
        is_valid, errors, _parsed = self.validate_and_parse(file_path)
        return is_valid, errors

    def validate_and_parse(
        self,
        file_path: Path,
        progress_cb=None,
    ) -> Tuple[bool, List[str], Optional[dict]]:
        """Validate a watchlist YAML file and hand back the parsed data.

        One upload used to be parsed 5-6 times because every step
        (validation, taxid audit, import, session load) re-read the file;
        callers that need the content should take it from here and pass it
        on. ``progress_cb(done, total)`` is called every 25 entries so a
        background import can report per-entry validation progress.

        Returns:
            (is_valid, errors, parsed_dict). ``parsed_dict`` is None when
            the file could not be read or parsed at all; on validation
            errors the parsed data is still returned for error reporting.
        """
        errors = []

        if not file_path.exists():
            return False, [f"File not found: {file_path}"], None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return False, [f"Invalid YAML syntax: {e}"], None

        if not data:
            return False, ["Empty file"], None

        # Version gate: absent is fine (minimal custom files), but a value
        # that is present and not the v2.0 schema is refused rather than
        # imported on faith (2026-08-17 audit, finding W3 -- the field was
        # parsed and never checked, so any version imported identically).
        version = data.get("version")
        if version is not None and str(version) != "2.0":
            errors.append(
                f"Unsupported watchlist version '{version}' (this build "
                f"reads version 2.0)"
            )

        # Check for required sections
        if "pathogens" not in data:
            errors.append("Missing 'pathogens' section")

        pathogens = data.get("pathogens", [])
        if not isinstance(pathogens, list):
            errors.append("'pathogens' must be a list")
        elif not pathogens:
            errors.append("No pathogens defined")
        else:
            total = len(pathogens)
            for i, p in enumerate(pathogens):
                errors.extend(self._validate_pathogen_entry(i, p))
                if progress_cb is not None and (i + 1) % 25 == 0:
                    progress_cb(i + 1, total)
            if progress_cb is not None:
                progress_cb(total, total)

        return len(errors) == 0, errors, data

    # Per-entry schema checks live in validation/entry_schema.py; these
    # delegating names keep the loader's public surface stable.
    _validate_pathogen_entry = staticmethod(_validate_pathogen_entry_impl)
    entries_without_taxid = staticmethod(_entries_without_taxid_impl)

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

        return _entries_without_taxid_impl(data)

    def find_invalid_watchlist_files(self) -> List[Tuple[str, str]]:
        """(filename, first problem) for every watchlist file that fails to load.

        ``discover_watchlists`` silently drops a malformed or unreadable
        YAML with only a log line, so a corrupted upload simply vanished
        from every list and count with no operator-visible signal
        (2026-08-17 audit, finding W4). This scans the same tiers with the
        same validation and returns what was dropped, for the GUI to show.
        """
        # Cached on the same corpus fingerprint as discovery: the sweep
        # re-validated every YAML in every tier on every tab-state change.
        fingerprint = self._corpus_fingerprint()
        if (self._invalid_files_cache is not None
                and self._invalid_files_cache[0] == fingerprint):
            return list(self._invalid_files_cache[1])

        invalid: List[Tuple[str, str]] = []
        seen: set = set()
        for tier_dir, _source in self.get_search_paths():
            if not tier_dir.is_dir():
                continue
            for path in sorted(tier_dir.iterdir()):
                if path.suffix not in (".yaml", ".yml") or path.name in seen:
                    continue
                seen.add(path.name)
                try:
                    ok, errors = self.validate_file(path)
                except (OSError, UnicodeDecodeError) as e:
                    ok, errors = False, [str(e)]
                if not ok:
                    invalid.append((path.name, errors[0] if errors else "invalid"))
        self._invalid_files_cache = (fingerprint, list(invalid))
        return invalid

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
        parsed: Optional[dict] = None,
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
            parsed: The source file's parsed data from a prior
                ``validate_and_parse`` of the SAME file. Skips the internal
                re-validation; the caller vouches that the file validated.

        Returns:
            Tuple of (success, message)
        """
        # Validate first, unless the caller already did on this same file.
        if parsed is None:
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

            # Clear cache to pick up new file. NOTE: this clears the caches
            # of THIS loader instance. When the import runs in a background
            # worker process, the live app's loader is a different object --
            # the finalize callback must call invalidate_cache() on the
            # main-process singleton.
            self.invalidate_cache()

            return True, f"Imported watchlist to {dest_path}"
        except (FileNotFoundError, PermissionError, OSError, shutil.SameFileError) as e:
            logger.exception(f"Failed to import watchlist: {e}")
            return False, f"Failed to import: {e}"

    def invalidate_cache(self) -> None:
        """Drop the discovery and pathogen caches so the next read re-scans
        the watchlist directories. Call on the main-process singleton after
        any out-of-process change to the files (background import)."""
        self._cached_watchlists.clear()
        self._loaded_pathogens.clear()
        self._cache_fingerprint = None
        self._invalid_files_cache = None

    def _import_collision(
        self, dest_dir: Path, dest_name: str, watchlist_id: str
    ) -> Optional[str]:
        """Why this import must be refused, or None if it is safe."""
        classified = self._classify_collision(dest_dir, dest_name, watchlist_id)
        return classified[1] if classified else None

    def classify_upload_collision(
        self, file_name: str, destination: str = "user"
    ) -> Optional[Tuple[str, str]]:
        """(kind, message) for the collision this upload would cause, or None.

        ``kind`` is ``"exists"`` (same filename), ``"stem"`` (same watchlist
        id under a different extension) or ``"builtin"`` (shadows a shipped
        list). The GUI uses the kind to decide whether a confirmed
        replacement is offered: the first two are the operator overwriting
        their own file and are replaceable with confirmation; shadowing a
        built-in stays refused outright (2026-08-17 audit, finding W2 --
        the refusal message promised "confirm the replacement" while no
        confirm control existed anywhere).
        """
        dest_name = self.sanitize_upload_name(file_name)
        if dest_name is None:
            return None
        if destination == "project" and self._project_dir:
            dest_dir = self._project_dir / self.PROJECT_SUBDIR
        else:
            dest_dir = self.user_watchlist_dir
        if not dest_dir.is_dir():
            dest_dir = None
        return self._classify_collision(
            dest_dir, dest_name, Path(dest_name).stem
        )

    def _classify_collision(
        self, dest_dir: Optional[Path], dest_name: str, watchlist_id: str
    ) -> Optional[Tuple[str, str]]:
        """(kind, refusal message) or None when the import is safe.

        A watchlist is keyed by its file stem, so two different files with the
        same stem are the same watchlist as far as discovery is concerned: the
        copy would replace the operator's earlier upload, or shadow a built-in
        list, with no indication that anything was lost.
        """
        if dest_dir is not None and (dest_dir / dest_name).exists():
            return "exists", (
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
        ) if dest_dir is not None else None
        if existing is not None:
            return "stem", (
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
                return "builtin", (
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
