"""
Shared caching and file-stability utilities for data loaders.

This module provides thread-safe caching infrastructure and file-stability
checks used by the category-specific loader modules (classification, QC,
validation).
"""

import hashlib
import logging
import os
import threading
import time
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

from nanometa_live.core.utils.sample_detector import (
    get_available_samples,
    resolve_analysis_directory
)


# Cache configuration
CACHE_TTL_SECONDS = 30  # Time-to-live for cached data
CACHE_MAX_ENTRIES = 100  # Maximum cache entries to prevent unbounded growth
CACHE_CLEANUP_INTERVAL_SECONDS = 60  # Run cleanup every 60 seconds

# File stability configuration (for real-time mode)
FILE_STABILITY_CHECK_INTERVAL_MS = 200  # Wait time between size checks
FILE_STABILITY_MIN_SIZE_BYTES = 10  # Minimum file size to consider valid

# Module-level cache storage -- protected by _cache_lock for thread safety.
# Dash/Flask runs callbacks concurrently in multiple threads, so all reads
# and writes to these shared dicts must be serialized.
_cache_lock = threading.Lock()
_kraken_cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
_fastp_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_last_cache_cleanup: float = 0.0  # Track last cleanup time

# File mtime/size cache: maps (dir, sample) -> (mtime, size, cached_result)
# Used for O(stat) freshness checks instead of O(parse)
_file_mtimes: Dict[str, Tuple[float, int, Any]] = {}
# Last freshness fingerprint for change detection
_last_freshness_fingerprint: str = ""


def _is_file_stable(filepath: str, wait_ms: int = FILE_STABILITY_CHECK_INTERVAL_MS) -> bool:
    """
    Check if a file is stable (not currently being written to).

    In real-time mode, Nextflow may still be writing to files when the dashboard
    polls for updates. This function checks whether the file's modification time
    is older than a threshold, indicating the write operation has completed.
    This avoids blocking the callback thread with sleep calls.

    Args:
        filepath: Path to the file to check
        wait_ms: Age threshold in milliseconds; the file's mtime must be at
            least this old to be considered stable (default: 200ms)

    Returns:
        True if file exists, has content, and mtime is sufficiently old; False otherwise
    """
    try:
        stat_result = os.stat(filepath)

        # File must have minimum content
        if stat_result.st_size < FILE_STABILITY_MIN_SIZE_BYTES:
            logging.debug(f"File too small ({stat_result.st_size} bytes), may be incomplete: {filepath}")
            return False

        # File is stable if its mtime is older than the threshold
        age_seconds = time.time() - stat_result.st_mtime
        threshold_seconds = max(wait_ms / 1000.0, 1.0)

        if age_seconds < threshold_seconds:
            logging.debug(f"File modified {age_seconds:.2f}s ago, may still be written: {filepath}")
            return False

        return True

    except OSError as e:
        logging.warning(f"Error checking file stability for {filepath}: {e}")
        return False


def _get_cache_key(main_dir: str, sample: Optional[str]) -> str:
    """Generate a cache key from main_dir and sample."""
    sample_key = sample if sample else "All Samples"
    return f"{main_dir}:{sample_key}"


def _is_cache_valid(cache_time: float) -> bool:
    """Check if cached data is still valid based on TTL."""
    return (time.time() - cache_time) < CACHE_TTL_SECONDS


def _cleanup_stale_cache_entries():
    """
    Remove stale entries from caches to prevent memory leaks.

    This function is called periodically to remove expired entries.
    It also enforces a maximum cache size by removing oldest entries.

    Caller must hold _cache_lock.
    """
    global _last_cache_cleanup

    current_time = time.time()

    # Only run cleanup if enough time has passed
    if (current_time - _last_cache_cleanup) < CACHE_CLEANUP_INTERVAL_SECONDS:
        return

    _last_cache_cleanup = current_time

    # Clean Kraken cache
    stale_keys = [
        key for key, (cache_time, _) in _kraken_cache.items()
        if not _is_cache_valid(cache_time)
    ]
    for key in stale_keys:
        del _kraken_cache[key]

    # If still too many entries, remove oldest
    if len(_kraken_cache) > CACHE_MAX_ENTRIES:
        sorted_entries = sorted(_kraken_cache.items(), key=lambda x: x[1][0])
        entries_to_remove = len(_kraken_cache) - CACHE_MAX_ENTRIES
        for key, _ in sorted_entries[:entries_to_remove]:
            del _kraken_cache[key]

    # Clean FASTP cache
    stale_keys = [
        key for key, (cache_time, _) in _fastp_cache.items()
        if not _is_cache_valid(cache_time)
    ]
    for key in stale_keys:
        del _fastp_cache[key]

    # If still too many entries, remove oldest
    if len(_fastp_cache) > CACHE_MAX_ENTRIES:
        sorted_entries = sorted(_fastp_cache.items(), key=lambda x: x[1][0])
        entries_to_remove = len(_fastp_cache) - CACHE_MAX_ENTRIES
        for key, _ in sorted_entries[:entries_to_remove]:
            del _fastp_cache[key]

    if stale_keys:
        logging.debug(f"Cache cleanup: removed {len(stale_keys)} stale entries")


def clear_data_cache():
    """Clear all cached data. Call when data is expected to have changed."""
    with _cache_lock:
        _kraken_cache.clear()
        _fastp_cache.clear()
        _file_mtimes.clear()


def _get_dir_latest_mtime(directory: str) -> float:
    """Return the most recent mtime among files in a directory (non-recursive)."""
    latest = 0.0
    try:
        for entry in os.scandir(directory):
            if entry.is_file():
                try:
                    mt = entry.stat().st_mtime
                    if mt > latest:
                        latest = mt
                except OSError:
                    pass
    except OSError:
        pass
    return latest


def _get_path_fingerprint(paths: List[str]) -> Tuple[float, int]:
    """
    Compute a (max_mtime, total_size) fingerprint for a list of paths.

    For directories, scans contained files for the latest mtime and total size.
    For regular files, uses their individual stat values.
    """
    combined_mtime = 0.0
    combined_size = 0
    for fp in paths:
        try:
            st = os.stat(fp)
        except OSError:
            continue
        if os.path.isdir(fp):
            # Scan directory entries for latest mtime and accumulated size
            try:
                for entry in os.scandir(fp):
                    if entry.is_file():
                        try:
                            est = entry.stat()
                            if est.st_mtime > combined_mtime:
                                combined_mtime = est.st_mtime
                            combined_size += est.st_size
                        except OSError:
                            pass
            except OSError:
                pass
        else:
            if st.st_mtime > combined_mtime:
                combined_mtime = st.st_mtime
            combined_size += st.st_size
    return (combined_mtime, combined_size)


def _check_mtime_cache(
    cache_key: str,
    paths: List[str],
) -> Optional[Any]:
    """
    Check if any of the given paths have changed since the last cached result.

    Compares current mtime and size against stored values. If unchanged,
    returns the cached result without reparsing. Returns None on cache miss
    or when data has changed.

    Thread-safe: acquires _cache_lock for the dict lookup.
    """
    with _cache_lock:
        if cache_key not in _file_mtimes:
            return None
        stored_mtime, stored_size, cached_result = _file_mtimes[cache_key]

    # Filesystem stat is done outside the lock (I/O should not block other threads)
    current_mtime, current_size = _get_path_fingerprint(paths)

    if current_mtime == stored_mtime and current_size == stored_size:
        return cached_result

    return None


def _store_mtime_cache(
    cache_key: str,
    paths: List[str],
    result: Any,
) -> None:
    """Store a result keyed by the combined mtime/size fingerprint of paths."""
    mtime, size = _get_path_fingerprint(paths)
    with _cache_lock:
        _file_mtimes[cache_key] = (mtime, size, result)


def check_data_freshness(main_dir: str) -> str:
    """
    Return a fingerprint string representing the freshness of result data.

    Scans the kraken2/, fastp/, and validation/ subdirectories and hashes
    the latest file mtimes. A changed fingerprint means new data is available.

    This function is intended to be called once per polling interval by a
    single centralized callback, rather than having each tab poll independently.

    When data has changed, stale cache entries are cleaned up as a side effect.
    """
    global _last_freshness_fingerprint

    main_dir = resolve_analysis_directory(main_dir)

    parts = []
    for subdir in ("kraken2", "fastp", "validation"):
        dirpath = os.path.join(main_dir, subdir)
        mt = _get_dir_latest_mtime(dirpath)
        parts.append(f"{subdir}:{mt}")

    raw = "|".join(parts)
    fingerprint = hashlib.md5(raw.encode()).hexdigest()

    # Run cache cleanup only when data has actually changed
    with _cache_lock:
        if fingerprint != _last_freshness_fingerprint:
            _last_freshness_fingerprint = fingerprint
            _cleanup_stale_cache_entries()

    return fingerprint
