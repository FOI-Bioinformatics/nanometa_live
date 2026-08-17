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


# Results subdirectories whose contents drive GUI refreshes. This is the
# single watch list shared by check_data_freshness (the results-fingerprint
# store) and first-batch detection (app/utils/first_batch.py); the two had
# drifted apart, and neither watched canonical/ although the loaders read it
# before any cache (2026-08-17 audit, finding C6).
RESULTS_WATCHED_SUBDIRS = (
    "kraken2",
    "fastp",
    "seqkit",
    "validation",
    "taxpasta",
    "canonical",
    "on_demand_validation",
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

# File mtime/size cache: maps cache_key -> (path_fingerprint, epoch, result).
# Used for O(stat) freshness checks instead of O(parse).
_file_mtimes: Dict[str, Tuple[Tuple[float, int, int], int, Any]] = {}
# Last freshness fingerprint for change detection
_last_freshness_fingerprint: str = ""

# Monotonic counter bumped by check_data_freshness whenever the results tree
# changes. It is the authority for "has anything at all changed since the
# last poll", and lets _check_mtime_cache answer a repeat lookup within the
# same poll without touching the filesystem.
#
# A single poll issues roughly 3N + 8 load_kraken_data calls (the dashboard
# per-sample loop, the pathogen attribution loop, and the QC summary loop
# each walk every sample). Before the epoch check, each of those calls paid
# its own directory fingerprint walk even on a cache hit, which is what made
# a quiet 24-sample poll cost ~74k stat() calls.
#
# Epoch 0 means check_data_freshness has never run in this process. Callers
# that never poll -- tests, the CLI, one-shot report generation -- stay on
# the unconditional path-fingerprint check, so the shortcut cannot serve
# them stale data.
_freshness_epoch: int = 0

# Per-key parse locks. Concurrent callbacks that all miss the mtime cache
# at the same instant (because kraken2/ mtime advanced since their last
# read) would otherwise each start a full re-parse, despite a shared
# in-process cache existing. The per-key lock makes the parse path
# single-writer for any given (main_dir, sample) so the second-through-
# Nth caller waits ~ms then takes the cached result rather than redoing
# the work in parallel. Closes the P0-G01 thundering-herd race flagged
# in audit-2026-04-28-throughput-gui.md.
_parse_locks: Dict[str, threading.Lock] = {}
_parse_locks_lock = threading.Lock()


def _get_parse_lock(cache_key: str) -> threading.Lock:
    """Return (creating if needed) a Lock dedicated to one cache key.

    Thread-safe: the registry is itself protected by a guard lock, but
    the returned per-key lock is the one held during the actual parse
    so concurrent keys do not serialize against each other.
    """
    with _parse_locks_lock:
        lock = _parse_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _parse_locks[cache_key] = lock
        return lock


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

    # Clean mtime cache (enforce max size)
    if len(_file_mtimes) > CACHE_MAX_ENTRIES:
        # Remove entries with oldest cached results (no TTL, just cap size)
        sorted_entries = sorted(_file_mtimes.items(), key=lambda x: x[1][0])
        entries_to_remove = len(_file_mtimes) - CACHE_MAX_ENTRIES
        for key, _ in sorted_entries[:entries_to_remove]:
            del _file_mtimes[key]
        removed_mtime = entries_to_remove
    else:
        removed_mtime = 0

    total_removed = len(stale_keys) + removed_mtime
    if total_removed:
        logging.debug(f"Cache cleanup: removed {total_removed} stale entries")


def clear_data_cache():
    """Clear all cached data. Call when data is expected to have changed."""
    with _cache_lock:
        _kraken_cache.clear()
        _fastp_cache.clear()
        _file_mtimes.clear()


def clear_all_loader_caches():
    """Reset every cache layer that could carry one run's data into the next.

    Called when the boundary between two runs is crossed: on Archive (the
    prior results just left the output directory) and on pipeline start.
    Without this, the TTL cache, the per-key mtime cache, the parsed-frame
    cache, the sample-detector cache and the alert history all survive into
    the next run inside the same process -- the loaders are module-global
    state, so "new run" is invisible to them unless someone says so.

    Imports are local to avoid cycles: classification_loaders and
    sample_detector both import from this module.
    """
    from nanometa_live.core.utils.alert_engine import get_alert_engine
    from nanometa_live.core.utils.classification_loaders import (
        clear_report_frame_cache,
    )
    from nanometa_live.core.utils.sample_detector import invalidate_sample_cache

    clear_data_cache()
    clear_report_frame_cache()
    invalidate_sample_cache()
    get_alert_engine().clear_alerts()


def _get_dir_latest_mtime(directory: str) -> Tuple[float, int]:
    """Return (latest mtime, file count) among files in a directory (recursive).

    Walks the entire tree, stat'ing the first ``_MAX_FINGERPRINT_FILES`` files
    for their mtime. The recursive walk is required so the freshness
    fingerprint advances when files land in nested subdirectories such as the
    real-time Kraken2 layout (``kraken2/<sample>/batch_reports/*``); a
    non-recursive scandir of ``kraken2/`` finds no direct files there and the
    fingerprint would otherwise lock in a constant value, leaving fingerprint-
    gated callbacks permanently stale.

    Files past the stat cap are still COUNTED (no stat, so it stays cheap) --
    genuinely mirroring ``_get_path_fingerprint``. The earlier hard return at
    the cap abandoned the walk entirely, so on a tree exceeding the cap in one
    watched subdir a new file could fail to bump the freshness epoch, and
    every per-key mtime-cache entry then took the epoch fast-path forever:
    indefinite staleness, not a one-poll delay.
    """
    latest = 0.0
    files_seen = 0
    try:
        for root, _dirs, files in os.walk(directory):
            for name in files:
                files_seen += 1
                if files_seen > _MAX_FINGERPRINT_FILES:
                    continue
                try:
                    mt = os.stat(os.path.join(root, name)).st_mtime
                except OSError:
                    continue
                if mt > latest:
                    latest = mt
    except OSError:
        pass
    return latest, files_seen


def _get_path_fingerprint(paths: List[str]) -> Tuple[float, int, int]:
    """
    Compute a (max_mtime, total_size, file_count) fingerprint for a list of paths.

    For directories, walks the entire tree and records the latest file mtime
    plus the running total size. ``stat`` is called on the first
    ``_MAX_FINGERPRINT_FILES`` files to bound I/O on large outdirs; files past
    that cap still increment ``file_count`` so newly-added files past the cap
    advance the fingerprint and invalidate the loader cache. Without the count
    component the fingerprint would silently plateau on million-file outdirs
    and the GUI would render stale data.

    The recursive walk is required so the fingerprint advances when files land
    in nested subdirectories such as the v1.5 incremental Kraken2 layout
    (``kraken2/<sample>/batch_reports/*``); a non-recursive scandir of
    ``kraken2/`` finds no direct files there and the cache would otherwise
    lock in an empty result.

    For regular files, uses their individual stat values.
    """
    combined_mtime = 0.0
    combined_size = 0
    file_count = 0
    files_stat = 0
    for fp in paths:
        try:
            st = os.stat(fp)
        except OSError:
            continue
        if os.path.isdir(fp):
            # Walk the tree so files in nested subdirectories advance the
            # fingerprint. stat() is bounded by _MAX_FINGERPRINT_FILES for
            # latency; the bare count walk continues past the cap so newly
            # added files still bump the fingerprint via file_count.
            try:
                for root, _dirs, files in os.walk(fp):
                    for name in files:
                        file_count += 1
                        if files_stat >= _MAX_FINGERPRINT_FILES:
                            continue
                        try:
                            est = os.stat(os.path.join(root, name))
                        except OSError:
                            continue
                        if est.st_mtime > combined_mtime:
                            combined_mtime = est.st_mtime
                        combined_size += est.st_size
                        files_stat += 1
            except OSError:
                pass
        else:
            file_count += 1
            if st.st_mtime > combined_mtime:
                combined_mtime = st.st_mtime
            combined_size += st.st_size
    return (combined_mtime, combined_size, file_count)


# Cap the number of files stat()-ed per fingerprint computation. The walk
# itself continues past the cap so newly-added files still advance the
# fingerprint via file_count, but the per-file stat() cost is bounded.
# Override at runtime by exporting NANOMETA_MAX_FINGERPRINT_FILES (integer).
# Default sized for a typical PromethION run (24 barcodes x ~100 batches x
# a handful of intermediate files each); raise for outdirs that warehouse
# multiple historical runs in the same tree.
_MAX_FINGERPRINT_FILES = int(
    os.environ.get("NANOMETA_MAX_FINGERPRINT_FILES", "50000")
)


def _check_mtime_cache(
    cache_key: str,
    paths: List[str],
) -> Optional[Any]:
    """
    Check if any of the given paths have changed since the last cached result.

    Compares current mtime and size against stored values. If unchanged,
    returns the cached result without reparsing. Returns None on cache miss
    or when data has changed.

    Two levels of validation, cheapest first:

    1. If the entry was stored during the current freshness epoch, nothing in
       the results tree has changed since, so the entry is still valid and no
       filesystem call is needed. This is the common case: the same cache key
       is looked up several times within one poll.
    2. Otherwise fall back to fingerprinting ``paths``. On a match the entry
       is re-stamped with the current epoch, so the remaining lookups in this
       poll take path 1.

    Thread-safe: acquires _cache_lock for the dict lookup.
    """
    state, result = _mtime_cache_state(cache_key, paths)
    return result if state == "hit" else None


def _mtime_cache_state(
    cache_key: str,
    paths: List[str],
) -> Tuple[str, Any]:
    """Classify an mtime-cache lookup as ``hit``, ``stale`` or ``absent``.

    ``_check_mtime_cache`` collapses "no entry yet" and "the files changed"
    into a single ``None``, which loses the distinction callers need. A caller
    that falls back to a time-to-live cache after a ``stale`` result would
    return data it has just proven to be out of date; after an ``absent``
    result the TTL cache is a legitimate fallback.

    Returns ``(state, result)`` where ``result`` is meaningful only for
    ``hit``.
    """
    with _cache_lock:
        if cache_key not in _file_mtimes:
            return ("absent", None)
        stored_fp, stored_epoch, cached_result = _file_mtimes[cache_key]
        epoch = _freshness_epoch

    if epoch and stored_epoch == epoch:
        return ("hit", cached_result)

    current_fp = _get_path_fingerprint(paths)
    if current_fp == stored_fp:
        with _cache_lock:
            _file_mtimes[cache_key] = (stored_fp, epoch, cached_result)
        return ("hit", cached_result)

    return ("stale", None)


def _store_mtime_cache(
    cache_key: str,
    paths: List[str],
    result: Any,
) -> None:
    """Store a result keyed by the (mtime, size, count) fingerprint of paths.

    The current freshness epoch is recorded alongside so that repeat lookups
    within the same poll can skip the fingerprint walk entirely.
    """
    fp = _get_path_fingerprint(paths)
    with _cache_lock:
        _file_mtimes[cache_key] = (fp, _freshness_epoch, result)


def check_data_freshness(main_dir: str) -> str:
    """
    Return a fingerprint string representing the freshness of result data.

    Scans the subdirectories in ``RESULTS_WATCHED_SUBDIRS`` and hashes the
    latest file mtimes. A changed fingerprint means new data is available.

    seqkit/ is the QC output directory for the chopper and filtlong
    pipelines (fastp/ is the alternative when qc_tool=fastp). Including
    it here means the fingerprint advances on every QC update regardless
    of which tool the run used. canonical/ is included because the loaders
    consult it before their caches, so a rewritten manifest or
    classification JSON must advance the fingerprint; on_demand_validation/
    because operator-triggered validation results land there mid-session.

    This function is intended to be called once per polling interval by a
    single centralized callback, rather than having each tab poll independently.

    When data has changed, stale cache entries are cleaned up as a side effect.
    """
    global _last_freshness_fingerprint, _freshness_epoch

    main_dir = resolve_analysis_directory(main_dir)

    # The directory itself is part of the payload: the epoch bump below
    # compares against the LAST fingerprint regardless of which directory
    # produced it, so two directories that hash identically (two empty
    # outdirs, or one emptied by Archive) would otherwise fail to bump the
    # epoch on a switch -- and every mtime-cache entry stamped with the
    # current epoch keeps answering without a filesystem check.
    parts = [main_dir]
    for subdir in RESULTS_WATCHED_SUBDIRS:
        dirpath = os.path.join(main_dir, subdir)
        mt, n_files = _get_dir_latest_mtime(dirpath)
        parts.append(f"{subdir}:{mt}:{n_files}")

    raw = "|".join(parts)
    fingerprint = hashlib.md5(raw.encode()).hexdigest()

    # Update fingerprint and run periodic cache cleanup (including mtime cache)
    with _cache_lock:
        if fingerprint != _last_freshness_fingerprint:
            _last_freshness_fingerprint = fingerprint
            # Something in the tree moved. Bump the epoch so every mtime-cache
            # entry re-validates against its own paths on next lookup.
            _freshness_epoch += 1
        elif _freshness_epoch == 0:
            # First call of the process on an unchanged tree: start the epoch
            # so downstream lookups can use the shortcut.
            _freshness_epoch = 1
        _cleanup_stale_cache_entries()

    return fingerprint


def get_last_freshness_fingerprint() -> str:
    """
    Return the last computed freshness fingerprint without triggering a rescan.

    Tabs can call this to check whether data has changed since they last
    rendered, and skip a full rescan when the fingerprint is unchanged.
    """
    with _cache_lock:
        return _last_freshness_fingerprint
