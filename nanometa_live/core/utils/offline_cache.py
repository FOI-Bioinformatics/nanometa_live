"""
Offline taxonomy cache for Nanometa Live.

This module provides caching functionality for GTDB and NCBI API responses,
enabling offline operation when network access is unavailable.

Features:
- Persistent cache storage in ~/.nanometa/cache/
- TTL-based cache expiration
- Offline mode flag for air-gapped environments
- Pre-bundled taxonomy snapshot support
"""

import json
import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from functools import wraps

logger = logging.getLogger(__name__)

# Default cache directory
DEFAULT_CACHE_DIR = os.path.expanduser("~/.nanometa/cache")

# Cache TTL (time-to-live) in seconds
DEFAULT_TTL = 7 * 24 * 60 * 60  # 7 days


@dataclass
class CacheEntry:
    """A cached item with metadata."""
    key: str
    data: Any
    created_at: float
    ttl: int
    source: str  # 'api', 'snapshot', 'user'

    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return time.time() > (self.created_at + self.ttl)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'CacheEntry':
        """Create from dictionary."""
        return cls(**data)


class OfflineTaxonomyCache:
    """
    Cache for offline taxonomy lookups.

    Provides caching for GTDB and NCBI API responses to enable
    offline operation in air-gapped environments.
    """

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE_DIR,
        ttl: int = DEFAULT_TTL,
        offline_mode: bool = False
    ):
        """
        Initialize the offline cache.

        Args:
            cache_dir: Directory to store cache files
            ttl: Time-to-live for cache entries in seconds
            offline_mode: If True, only use cached data (no API calls)
        """
        self.cache_dir = Path(cache_dir).expanduser()
        self.ttl = ttl
        self.offline_mode = offline_mode

        # Create subdirectories for different cache types
        self.gtdb_cache_dir = self.cache_dir / "gtdb"
        self.ncbi_cache_dir = self.cache_dir / "ncbi"
        self.species_cache_dir = self.cache_dir / "species"
        self.metadata_file = self.cache_dir / "cache_metadata.json"

        # Create directories
        self._init_directories()

        # Load metadata
        self._metadata = self._load_metadata()

    def _init_directories(self) -> None:
        """Create cache directories if they don't exist."""
        for directory in [
            self.cache_dir,
            self.gtdb_cache_dir,
            self.ncbi_cache_dir,
            self.species_cache_dir
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def _load_metadata(self) -> Dict:
        """Load cache metadata from disk."""
        if self.metadata_file.exists():
            try:
                return json.loads(self.metadata_file.read_text())
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error loading cache metadata: {e}")
        return {
            "created_at": time.time(),
            "version": "1.0",
            "entry_count": 0,
            "last_cleanup": None
        }

    def _save_metadata(self) -> None:
        """Save cache metadata to disk."""
        try:
            self.metadata_file.write_text(json.dumps(self._metadata, indent=2))
        except IOError as e:
            logger.warning(f"Error saving cache metadata: {e}")

    def _get_cache_key(self, identifier: str, cache_type: str = "species") -> str:
        """
        Generate a cache key from an identifier.

        Args:
            identifier: The identifier to cache (e.g., species name, taxid)
            cache_type: Type of cache ('gtdb', 'ncbi', 'species')

        Returns:
            A safe filename-compatible cache key
        """
        # Create a hash for long identifiers
        if len(identifier) > 50:
            hash_suffix = hashlib.md5(identifier.encode()).hexdigest()[:8]
            safe_id = identifier[:40] + "_" + hash_suffix
        else:
            safe_id = identifier

        # Make filename safe
        safe_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in safe_id)
        return f"{cache_type}_{safe_id}.json"

    def _get_cache_path(self, key: str, cache_type: str = "species") -> Path:
        """Get the file path for a cache key."""
        if cache_type == "gtdb":
            return self.gtdb_cache_dir / key
        elif cache_type == "ncbi":
            return self.ncbi_cache_dir / key
        else:
            return self.species_cache_dir / key

    def get(
        self,
        identifier: str,
        cache_type: str = "species"
    ) -> Optional[Any]:
        """
        Get a cached value.

        Args:
            identifier: The identifier to look up
            cache_type: Type of cache to search

        Returns:
            Cached data if found and not expired, None otherwise
        """
        key = self._get_cache_key(identifier, cache_type)
        cache_path = self._get_cache_path(key, cache_type)

        if not cache_path.exists():
            logger.debug(f"Cache miss for {identifier}")
            return None

        try:
            entry_data = json.loads(cache_path.read_text())
            entry = CacheEntry.from_dict(entry_data)

            # Check expiration (unless in offline mode, then always use cached)
            if entry.is_expired() and not self.offline_mode:
                logger.debug(f"Cache expired for {identifier}")
                return None

            logger.debug(f"Cache hit for {identifier}")
            return entry.data

        except (json.JSONDecodeError, IOError, KeyError) as e:
            logger.warning(f"Error reading cache for {identifier}: {e}")
            return None

    def set(
        self,
        identifier: str,
        data: Any,
        cache_type: str = "species",
        source: str = "api",
        ttl: Optional[int] = None
    ) -> bool:
        """
        Store a value in the cache.

        Args:
            identifier: The identifier to cache
            data: The data to cache
            cache_type: Type of cache to store in
            source: Source of the data ('api', 'snapshot', 'user')
            ttl: Custom TTL (uses default if not specified)

        Returns:
            True if successfully cached
        """
        key = self._get_cache_key(identifier, cache_type)
        cache_path = self._get_cache_path(key, cache_type)

        entry = CacheEntry(
            key=key,
            data=data,
            created_at=time.time(),
            ttl=ttl or self.ttl,
            source=source
        )

        try:
            cache_path.write_text(json.dumps(entry.to_dict(), indent=2))
            self._metadata["entry_count"] = self._metadata.get("entry_count", 0) + 1
            self._save_metadata()
            logger.debug(f"Cached {identifier}")
            return True
        except IOError as e:
            logger.warning(f"Error caching {identifier}: {e}")
            return False

    def get_species_info(self, taxid: int) -> Optional[Dict]:
        """
        Get cached species information by taxid.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Species info dict if cached, None otherwise
        """
        return self.get(str(taxid), cache_type="species")

    def cache_species_info(self, taxid: int, info: Dict) -> bool:
        """
        Cache species information.

        Args:
            taxid: NCBI taxonomy ID
            info: Species information dictionary

        Returns:
            True if successfully cached
        """
        return self.set(str(taxid), info, cache_type="species", source="api")

    def get_gtdb_taxonomy(self, species_name: str) -> Optional[Dict]:
        """
        Get cached GTDB taxonomy data.

        Args:
            species_name: Species name to look up

        Returns:
            GTDB taxonomy data if cached, None otherwise
        """
        return self.get(species_name, cache_type="gtdb")

    def cache_gtdb_taxonomy(self, species_name: str, data: Dict) -> bool:
        """
        Cache GTDB taxonomy data.

        Args:
            species_name: Species name
            data: GTDB taxonomy data

        Returns:
            True if successfully cached
        """
        return self.set(species_name, data, cache_type="gtdb", source="api")

    def get_ncbi_taxonomy(self, taxid: int) -> Optional[Dict]:
        """
        Get cached NCBI taxonomy data.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            NCBI taxonomy data if cached, None otherwise
        """
        return self.get(str(taxid), cache_type="ncbi")

    def cache_ncbi_taxonomy(self, taxid: int, data: Dict) -> bool:
        """
        Cache NCBI taxonomy data.

        Args:
            taxid: NCBI taxonomy ID
            data: NCBI taxonomy data

        Returns:
            True if successfully cached
        """
        return self.set(str(taxid), data, cache_type="ncbi", source="api")

    def load_snapshot(self, snapshot_path: str) -> int:
        """
        Load a pre-bundled taxonomy snapshot into the cache.

        Snapshots are JSON files containing bulk taxonomy data for offline use.

        Args:
            snapshot_path: Path to snapshot file

        Returns:
            Number of entries loaded
        """
        snapshot_path = Path(snapshot_path).expanduser()

        if not snapshot_path.exists():
            logger.error(f"Snapshot not found: {snapshot_path}")
            return 0

        try:
            snapshot_data = json.loads(snapshot_path.read_text())
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading snapshot: {e}")
            return 0

        loaded_count = 0

        # Load GTDB entries
        for species_name, data in snapshot_data.get("gtdb", {}).items():
            if self.set(species_name, data, cache_type="gtdb", source="snapshot"):
                loaded_count += 1

        # Load NCBI entries
        for taxid, data in snapshot_data.get("ncbi", {}).items():
            if self.set(taxid, data, cache_type="ncbi", source="snapshot"):
                loaded_count += 1

        # Load species entries
        for taxid, data in snapshot_data.get("species", {}).items():
            if self.set(taxid, data, cache_type="species", source="snapshot"):
                loaded_count += 1

        logger.info(f"Loaded {loaded_count} entries from snapshot")
        return loaded_count

    def export_snapshot(self, output_path: str) -> int:
        """
        Export current cache to a snapshot file.

        Args:
            output_path: Path to save snapshot

        Returns:
            Number of entries exported
        """
        output_path = Path(output_path).expanduser()

        snapshot = {
            "gtdb": {},
            "ncbi": {},
            "species": {},
            "metadata": {
                "created_at": time.time(),
                "source": "nanometa_live_cache_export"
            }
        }

        export_count = 0

        # Export each cache type
        for cache_type, cache_dir in [
            ("gtdb", self.gtdb_cache_dir),
            ("ncbi", self.ncbi_cache_dir),
            ("species", self.species_cache_dir)
        ]:
            for cache_file in cache_dir.glob("*.json"):
                try:
                    entry_data = json.loads(cache_file.read_text())
                    entry = CacheEntry.from_dict(entry_data)
                    # Use the original identifier from the key
                    identifier = cache_file.stem.replace(f"{cache_type}_", "", 1)
                    snapshot[cache_type][identifier] = entry.data
                    export_count += 1
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Error reading {cache_file}: {e}")

        try:
            output_path.write_text(json.dumps(snapshot, indent=2))
            logger.info(f"Exported {export_count} entries to {output_path}")
            return export_count
        except IOError as e:
            logger.error(f"Error writing snapshot: {e}")
            return 0

    def clear_expired(self) -> int:
        """
        Remove expired cache entries.

        Returns:
            Number of entries removed
        """
        removed_count = 0

        for cache_dir in [
            self.gtdb_cache_dir,
            self.ncbi_cache_dir,
            self.species_cache_dir
        ]:
            for cache_file in cache_dir.glob("*.json"):
                try:
                    entry_data = json.loads(cache_file.read_text())
                    entry = CacheEntry.from_dict(entry_data)

                    if entry.is_expired():
                        cache_file.unlink()
                        removed_count += 1

                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Error processing {cache_file}: {e}")

        self._metadata["last_cleanup"] = time.time()
        self._metadata["entry_count"] = max(
            0, self._metadata.get("entry_count", 0) - removed_count
        )
        self._save_metadata()

        logger.info(f"Removed {removed_count} expired cache entries")
        return removed_count

    def clear_all(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries removed
        """
        removed_count = 0

        for cache_dir in [
            self.gtdb_cache_dir,
            self.ncbi_cache_dir,
            self.species_cache_dir
        ]:
            for cache_file in cache_dir.glob("*.json"):
                try:
                    cache_file.unlink()
                    removed_count += 1
                except IOError as e:
                    logger.warning(f"Error removing {cache_file}: {e}")

        self._metadata["entry_count"] = 0
        self._metadata["last_cleanup"] = time.time()
        self._save_metadata()

        logger.info(f"Cleared {removed_count} cache entries")
        return removed_count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        stats = {
            "cache_dir": str(self.cache_dir),
            "offline_mode": self.offline_mode,
            "ttl_seconds": self.ttl,
            "ttl_days": self.ttl / (24 * 60 * 60),
            "gtdb_entries": len(list(self.gtdb_cache_dir.glob("*.json"))),
            "ncbi_entries": len(list(self.ncbi_cache_dir.glob("*.json"))),
            "species_entries": len(list(self.species_cache_dir.glob("*.json"))),
            "total_entries": 0,
            "expired_entries": 0,
            "cache_size_bytes": 0,
            "last_cleanup": self._metadata.get("last_cleanup")
        }

        # Calculate totals
        for cache_dir in [
            self.gtdb_cache_dir,
            self.ncbi_cache_dir,
            self.species_cache_dir
        ]:
            for cache_file in cache_dir.glob("*.json"):
                stats["total_entries"] += 1
                stats["cache_size_bytes"] += cache_file.stat().st_size

                try:
                    entry_data = json.loads(cache_file.read_text())
                    entry = CacheEntry.from_dict(entry_data)
                    if entry.is_expired():
                        stats["expired_entries"] += 1
                except Exception:
                    pass

        stats["cache_size_mb"] = round(stats["cache_size_bytes"] / (1024 * 1024), 2)

        return stats


# Global cache instance
_cache_instance: Optional[OfflineTaxonomyCache] = None


def get_cache(offline_mode: bool = False) -> OfflineTaxonomyCache:
    """
    Get the global cache instance.

    Args:
        offline_mode: Whether to enable offline mode

    Returns:
        The global cache instance
    """
    global _cache_instance

    if _cache_instance is None:
        _cache_instance = OfflineTaxonomyCache(offline_mode=offline_mode)
    elif offline_mode != _cache_instance.offline_mode:
        # Update offline mode if changed
        _cache_instance.offline_mode = offline_mode

    return _cache_instance


def cached_api_call(cache_type: str = "species", ttl: Optional[int] = None):
    """
    Decorator for caching API call results.

    Usage:
        @cached_api_call(cache_type="gtdb")
        def fetch_gtdb_species(species_name: str) -> Dict:
            # API call here
            return api_response

    Args:
        cache_type: Type of cache to use
        ttl: Custom TTL for cached entries
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache()

            # Generate cache key from function args
            cache_key = f"{func.__name__}:{':'.join(str(a) for a in args)}"
            if kwargs:
                cache_key += f":{':'.join(f'{k}={v}' for k, v in sorted(kwargs.items()))}"

            # Check cache first
            cached_result = cache.get(cache_key, cache_type)
            if cached_result is not None:
                return cached_result

            # If in offline mode and no cache, return None
            if cache.offline_mode:
                logger.warning(f"Offline mode: no cache for {cache_key}")
                return None

            # Make the API call
            result = func(*args, **kwargs)

            # Cache the result
            if result is not None:
                cache.set(cache_key, result, cache_type, source="api", ttl=ttl)

            return result

        return wrapper
    return decorator
