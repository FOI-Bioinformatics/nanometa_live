"""
Sample-aware data loading utilities for Nanometa Live v2.0.

This module provides functions to load nanometanf output data with
optional sample filtering, supporting both per-sample and aggregated views.
"""

import os
import glob
import hashlib
import json
import logging
import re
import time
import pandas as pd
from typing import Optional, List, Dict, Any, Tuple, Union

from nanometa_live.core.utils.sample_detector import (
    get_sample_file_mapping,
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

# Module-level cache storage
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
    polls for updates. This function checks if the file size is stable over a
    short interval, indicating the write operation has completed.

    Args:
        filepath: Path to the file to check
        wait_ms: Milliseconds to wait between size checks (default: 200ms)

    Returns:
        True if file exists, has content, and size is stable; False otherwise
    """
    try:
        if not os.path.exists(filepath):
            return False

        # Get initial size
        size1 = os.path.getsize(filepath)

        # File must have minimum content
        if size1 < FILE_STABILITY_MIN_SIZE_BYTES:
            logging.debug(f"File too small ({size1} bytes), may be incomplete: {filepath}")
            return False

        # Wait and check again
        time.sleep(wait_ms / 1000.0)

        # Get size after wait
        size2 = os.path.getsize(filepath)

        # File is stable if size hasn't changed
        if size1 != size2:
            logging.debug(f"File size changed ({size1} -> {size2}), still being written: {filepath}")
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
    """
    global _kraken_cache, _fastp_cache, _last_cache_cleanup

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
    global _kraken_cache, _fastp_cache, _file_mtimes
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
    """
    if cache_key not in _file_mtimes:
        return None

    stored_mtime, stored_size, cached_result = _file_mtimes[cache_key]
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
    if fingerprint != _last_freshness_fingerprint:
        _last_freshness_fingerprint = fingerprint
        _cleanup_stale_cache_entries()

    return fingerprint


# Expected columns for Kraken2 report format
KRAKEN2_EXPECTED_COLUMNS = ["%", "cumul_reads", "reads", "rank", "taxid", "name"]
KRAKEN2_EXPECTED_COLUMN_COUNT = 6



def _parse_kraken2_report(filepath: str, check_stability: bool = True) -> Optional[pd.DataFrame]:
    """
    Parse and validate a Kraken2 report file.

    Args:
        filepath: Path to Kraken2 report file
        check_stability: If True, verify file is not being written to (default: True)

    Returns:
        DataFrame with validated columns, or None if parsing fails or file unstable
    """
    # Check file stability before reading (prevents reading partial files in real-time mode)
    if check_stability and not _is_file_stable(filepath):
        logging.debug(f"Skipping unstable file (may still be writing): {filepath}")
        return None

    try:
        # Read file without header - Kraken2 reports don't have headers
        df = pd.read_csv(
            filepath,
            sep="\t",
            header=None,
        )

        # Validate column count
        if len(df.columns) != KRAKEN2_EXPECTED_COLUMN_COUNT:
            logging.warning(
                f"Kraken2 report {filepath} has {len(df.columns)} columns, "
                f"expected {KRAKEN2_EXPECTED_COLUMN_COUNT}. Skipping file."
            )
            return None

        # Assign column names
        df.columns = KRAKEN2_EXPECTED_COLUMNS

        # Validate numeric columns can be converted
        numeric_cols = ["%", "cumul_reads", "reads", "taxid"]
        for col in numeric_cols:
            try:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            except Exception as e:
                logging.warning(
                    f"Column '{col}' in {filepath} contains non-numeric values: {e}"
                )

        # Drop rows where essential columns are NaN (from coercion errors)
        initial_len = len(df)
        df = df.dropna(subset=["reads", "taxid"])
        if len(df) < initial_len:
            dropped = initial_len - len(df)
            logging.debug(f"Dropped {dropped} rows with invalid data from {filepath}")

        # Ensure taxid is integer
        df["taxid"] = df["taxid"].astype(int)

        # Strip whitespace from name column (Kraken2 uses indentation for hierarchy)
        # but preserve leading spaces for hierarchy visualization
        df["name"] = df["name"].fillna("unknown")

        # Build parent_taxid from indentation-based hierarchy
        # Uses a stack to track the parent at each indentation depth
        parent_taxids = []
        indent_stack = []  # list of (indent_level, taxid) tuples
        for idx in range(len(df)):
            name_val = df.iloc[idx]["name"]
            indent = len(name_val) - len(str(name_val).lstrip())
            taxid = int(df.iloc[idx]["taxid"])

            # Pop stack entries with indent >= current (siblings or deeper)
            while indent_stack and indent_stack[-1][0] >= indent:
                indent_stack.pop()

            if indent_stack:
                parent_taxids.append(indent_stack[-1][1])
            else:
                parent_taxids.append(0)  # root has no parent

            indent_stack.append((indent, taxid))

        df["parent_taxid"] = parent_taxids

        return df

    except Exception as e:
        logging.error(f"Error parsing Kraken2 report {filepath}: {e}")
        return None


def _deduplicate_batch_files(filepaths: List[str]) -> List[str]:
    """
    Deduplicate batch report files that exist in multiple directories.

    The nanometanf pipeline may publish the same batch report to both
    ``reports/`` and ``batch_reports/`` directories, and ``batch_reports/``
    may contain two naming conventions (e.g. ``barcode01_batch0`` and
    ``batch_0``). This function keeps one file per (sample, batch_number)
    combination, preferring ``batch_reports/`` over ``reports/``.

    Args:
        filepaths: List of batch report file paths

    Returns:
        Deduplicated list of file paths
    """
    if not filepaths:
        return filepaths

    # Extract (sample, batch_num) from each path
    # Patterns: {sample}_batch{N}.kraken2.report.txt or batch_{N}.kraken2.report.txt
    batch_id_pattern = re.compile(r'(?:(.+?)_batch|batch_)(\d+)\.')

    seen_batches: Dict[Tuple[str, str], str] = {}  # (sample, batch) -> filepath

    for fp in filepaths:
        basename = os.path.basename(fp)
        match = batch_id_pattern.search(basename)
        if not match:
            # Not a batch file pattern - keep it
            seen_batches[('_nonbatch_', fp)] = fp
            continue

        sample_from_name = match.group(1) or ''
        batch_num = match.group(2)

        # Determine sample from directory structure if not in filename
        # e.g. kraken2/barcode01/batch_reports/batch_0.kraken2.report.txt
        if not sample_from_name:
            parts = fp.replace('\\', '/').split('/')
            for i, part in enumerate(parts):
                if part in ('batch_reports', 'reports', 'batches'):
                    if i > 0:
                        sample_from_name = parts[i - 1]
                    break

        batch_key = (sample_from_name, batch_num)

        if batch_key not in seen_batches:
            seen_batches[batch_key] = fp
        else:
            # Prefer batch_reports/ over reports/
            existing = seen_batches[batch_key]
            if 'batch_reports' in fp and 'batch_reports' not in existing:
                seen_batches[batch_key] = fp
            # Prefer sample-prefixed naming over generic batch_ naming
            elif (sample_from_name and match.group(1)
                  and 'batch_reports' in fp == 'batch_reports' in existing):
                existing_match = batch_id_pattern.search(os.path.basename(existing))
                if existing_match and not existing_match.group(1):
                    seen_batches[batch_key] = fp

    result = list(seen_batches.values())
    if len(result) < len(filepaths):
        logging.debug(
            f"Deduplicated batch files: {len(filepaths)} -> {len(result)}"
        )
    return result


def load_kraken_data(main_dir: str, sample: Optional[str] = None) -> pd.DataFrame:
    """
    Load Kraken2 classification data for specific sample or all samples.

    Uses time-based caching to reduce file system operations.
    Auto-resolves base directory to most recent analysis directory if needed.

    Args:
        main_dir: Main nanometanf output directory (or base directory)
        sample: Sample name, or None/"All Samples" for combined data

    Returns:
        DataFrame with columns: %, cumul_reads, reads, rank, taxid, name

    Examples:
        >>> # Load combined data from all samples
        >>> df = load_kraken_data("/path/to/results")
        >>>
        >>> # Load specific sample
        >>> df = load_kraken_data("/path/to/results", "barcode01")
    """
    global _kraken_cache

    # Auto-resolve to analysis directory if main_dir is base directory
    main_dir = resolve_analysis_directory(main_dir)

    # Check cache first
    cache_key = _get_cache_key(main_dir, sample)

    kraken_dir = os.path.join(main_dir, "kraken2")

    # Fast mtime-based check: if the kraken2 directory has not changed,
    # return the previously cached result without any parsing or TTL lookup
    mtime_key = f"kraken:{cache_key}"
    if os.path.isdir(kraken_dir):
        mtime_cached = _check_mtime_cache(mtime_key, [kraken_dir])
        if mtime_cached is not None:
            logging.debug(f"Mtime cache hit for Kraken data: {cache_key}")
            return mtime_cached.copy()

    # Fall back to TTL-based cache
    if cache_key in _kraken_cache:
        cache_time, cached_df = _kraken_cache[cache_key]
        if _is_cache_valid(cache_time):
            logging.debug(f"Using cached Kraken data for {cache_key}")
            return cached_df.copy()

    if not os.path.exists(kraken_dir):
        logging.warning(f"Kraken2 directory not found: {kraken_dir}")
        return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

    if sample is None or sample == "All Samples":
        # Load and aggregate all samples
        # Prioritize cumulative reports (generated by incremental Kraken2 in realtime mode)
        # then fall back to individual reports
        # Support both nanometanf v1.2+ and legacy file naming
        # Search both top-level and subdirectories for flexibility
        cumulative_patterns = [
            os.path.join(kraken_dir, "*.cumulative.kraken2.report.txt"),  # Incremental mode cumulative
            os.path.join(kraken_dir, "**", "*.cumulative.kraken2.report.txt"),  # In subdirs
        ]
        standard_patterns = [
            os.path.join(kraken_dir, "*.kraken2.report.txt"),  # nanometanf v1.2+
            os.path.join(kraken_dir, "*.kreport2.txt"),         # Legacy
            os.path.join(kraken_dir, "**", "*.kraken2.report.txt"),  # In subdirs
            os.path.join(kraken_dir, "**", "*.kreport2.txt"),         # Legacy in subdirs
        ]

        kreport_files = []

        # First check for cumulative reports (preferred for realtime mode)
        for pattern in cumulative_patterns:
            kreport_files.extend(glob.glob(pattern, recursive=True))
        # Deduplicate (direct and ** patterns can match the same files)
        kreport_files = list(dict.fromkeys(os.path.realpath(f) for f in kreport_files))

        if kreport_files:
            logging.debug(f"Found {len(kreport_files)} cumulative Kraken2 reports")
        else:
            # Fall back to standard reports (non-batch, non-cumulative)
            for pattern in standard_patterns:
                found_files = glob.glob(pattern, recursive=True)
                # Exclude cumulative files and batch files when loading standard reports
                for f in found_files:
                    basename = os.path.basename(f)
                    if '.cumulative.' not in basename and '_batch' not in basename and '.batch_' not in basename and not basename.startswith('batch_'):
                        kreport_files.append(f)
            # Deduplicate (direct and ** patterns can match the same files)
            kreport_files = list(dict.fromkeys(os.path.realpath(f) for f in kreport_files))

            # If no standard reports, fall back to batch files (will be aggregated)
            if not kreport_files:
                logging.debug("No standard reports found, looking for batch files to aggregate")
                batch_patterns = [
                    os.path.join(kraken_dir, "*_batch*.kraken2.report.txt"),
                    os.path.join(kraken_dir, "*_batch*.kreport2.txt"),
                    os.path.join(kraken_dir, "**", "*_batch*.kraken2.report.txt"),
                    os.path.join(kraken_dir, "**", "*_batch*.kreport2.txt"),
                    # v1.5 scalable streaming: batch_reports/ inside per-sample subdirs
                    os.path.join(kraken_dir, "**", "batch_reports", "*.kraken2.report.txt"),
                ]
                for pattern in batch_patterns:
                    kreport_files.extend(glob.glob(pattern, recursive=True))
                # Deduplicate: same batch may appear in reports/ and batch_reports/
                kreport_files = _deduplicate_batch_files(kreport_files)

                if kreport_files:
                    logging.debug(f"Found {len(kreport_files)} batch Kraken2 reports to aggregate")

        if not kreport_files:
            logging.warning("No Kraken2 report files found")
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        all_reports = []
        for kreport_file in kreport_files:
            df = _parse_kraken2_report(kreport_file)
            if df is not None and not df.empty:
                all_reports.append(df)

        if not all_reports:
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        # Aggregate reports by taxid - sum reads (direct assignments are additive)
        combined_df = pd.concat(all_reports, ignore_index=True)
        aggregated = combined_df.groupby(["taxid", "rank", "name"], as_index=False).agg({
            "reads": "sum",
            "cumul_reads": "sum"  # Note: cumul_reads sum is approximate for aggregated view
        })

        # Recalculate percentages from total reads (not sum of percentages)
        total_reads = aggregated['reads'].sum()
        if total_reads > 0:
            aggregated['%'] = (aggregated['reads'] / total_reads) * 100
        else:
            aggregated['%'] = 0.0

        # Merge hierarchy from all samples to avoid losing taxa present only in some samples
        # Build a complete ordered list of taxa preserving hierarchy from all samples
        # Using vectorized operations instead of iterrows() for O(n) vs O(n*m) performance
        if all_reports:
            taxa_df = pd.concat([
                report[['taxid', 'rank', 'name', 'parent_taxid']] for report in all_reports
            ], ignore_index=True)
            # Keep first occurrence of each taxid (preserves original hierarchy order
            # and parent_taxid from the first report that contains this taxon)
            ordered_taxa_df = taxa_df.drop_duplicates(subset='taxid', keep='first')
            ordered_taxa = ordered_taxa_df.to_dict('records')
        else:
            ordered_taxa = []

        # Create result dataframe with proper ordering
        agg_dict = aggregated.set_index('taxid')[['%', 'cumul_reads', 'reads']].to_dict('index')

        result_rows = []
        for taxon in ordered_taxa:
            taxid = taxon['taxid']
            if taxid in agg_dict:
                result_rows.append({
                    '%': round(agg_dict[taxid]['%'], 2),
                    'cumul_reads': agg_dict[taxid]['cumul_reads'],
                    'reads': agg_dict[taxid]['reads'],
                    'rank': taxon['rank'],
                    'taxid': taxid,
                    'name': taxon['name'],
                    'parent_taxid': taxon['parent_taxid'],
                })

        result_df = pd.DataFrame(result_rows)
        # Cache the result
        _kraken_cache[cache_key] = (time.time(), result_df.copy())
        _store_mtime_cache(mtime_key, [kraken_dir], result_df.copy())
        return result_df

    else:
        # Load specific sample - may have multiple batch files to combine
        # Prioritize cumulative reports (generated by incremental Kraken2 in realtime mode)
        # Support both nanometanf v1.2+ and legacy file naming
        # Search both top-level and subdirectories for flexibility
        cumulative_patterns = [
            os.path.join(kraken_dir, f"{sample}.cumulative.kraken2.report.txt"),  # Incremental mode
            os.path.join(kraken_dir, "**", f"{sample}.cumulative.kraken2.report.txt"),  # In subdirs
        ]
        standard_patterns = [
            os.path.join(kraken_dir, f"{sample}.kraken2.report.txt"),    # nanometanf v1.2+
            os.path.join(kraken_dir, f"{sample}.kreport2.txt"),          # Legacy
            os.path.join(kraken_dir, "**", f"{sample}.kraken2.report.txt"),  # In subdirs
            os.path.join(kraken_dir, "**", f"{sample}.kreport2.txt"),         # Legacy in subdirs
        ]
        batch_patterns = [
            os.path.join(kraken_dir, f"{sample}_batch*.kraken2.report.txt"),  # nanometanf batches
            os.path.join(kraken_dir, f"{sample}_batch*.kreport2.txt"),        # Legacy batches
            os.path.join(kraken_dir, "**", f"{sample}_batch*.kraken2.report.txt"),  # In subdirs
            os.path.join(kraken_dir, "**", f"{sample}_batch*.kreport2.txt"),        # Legacy in subdirs
            # v1.5 scalable streaming: batch_reports/ subdirectory inside per-sample folder
            os.path.join(kraken_dir, sample, "batch_reports", "*.kraken2.report.txt"),
        ]

        sample_files = []

        # First check for cumulative reports (preferred - already aggregated)
        for pattern in cumulative_patterns:
            sample_files.extend(glob.glob(pattern, recursive=True))
        # Deduplicate (direct and ** patterns can match the same files)
        sample_files = list(dict.fromkeys(os.path.realpath(f) for f in sample_files))

        if sample_files:
            logging.debug(f"Found cumulative Kraken2 report for {sample}")
        else:
            # Check for standard (non-batch) reports
            for pattern in standard_patterns:
                sample_files.extend(glob.glob(pattern, recursive=True))
            sample_files = list(dict.fromkeys(os.path.realpath(f) for f in sample_files))

            # If no standard report, check for batch files to aggregate
            if not sample_files:
                for pattern in batch_patterns:
                    sample_files.extend(glob.glob(pattern, recursive=True))
                # Deduplicate: same batch may appear in reports/ and batch_reports/
                sample_files = _deduplicate_batch_files(sample_files)

        if not sample_files:
            logging.warning(f"No Kraken2 files found for sample {sample}")
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        all_reports = []
        for sample_file in sample_files:
            df = _parse_kraken2_report(sample_file)
            if df is not None and not df.empty:
                all_reports.append(df)

        if not all_reports:
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        # If only one batch file, cache and return it directly
        if len(all_reports) == 1:
            result_df = all_reports[0]
            _kraken_cache[cache_key] = (time.time(), result_df.copy())
            _store_mtime_cache(mtime_key, [kraken_dir], result_df.copy())
            return result_df

        # Otherwise, aggregate multiple batches by taxid - sum reads (direct assignments)
        combined_df = pd.concat(all_reports, ignore_index=True)
        aggregated = combined_df.groupby(["taxid", "rank", "name"], as_index=False).agg({
            "reads": "sum",
            "cumul_reads": "sum"  # Note: cumul_reads sum is approximate for aggregated view
        })

        # Recalculate percentages from total reads (not sum of percentages)
        total_reads = aggregated['reads'].sum()
        if total_reads > 0:
            aggregated['%'] = (aggregated['reads'] / total_reads) * 100
        else:
            aggregated['%'] = 0.0

        # Merge hierarchy from all batches to avoid losing taxa present only in some batches
        # Using vectorized operations instead of iterrows() for O(n) vs O(n*m) performance
        if all_reports:
            taxa_df = pd.concat([
                report[['taxid', 'rank', 'name', 'parent_taxid']] for report in all_reports
            ], ignore_index=True)
            # Keep first occurrence of each taxid (preserves original hierarchy order
            # and parent_taxid from the earliest batch that contains this taxon)
            ordered_taxa_df = taxa_df.drop_duplicates(subset='taxid', keep='first')
            ordered_taxa = ordered_taxa_df.to_dict('records')
        else:
            ordered_taxa = []

        # Create result dataframe with proper ordering
        agg_dict = aggregated.set_index('taxid')[['%', 'cumul_reads', 'reads']].to_dict('index')

        result_rows = []
        for taxon in ordered_taxa:
            taxid = taxon['taxid']
            if taxid in agg_dict:
                result_rows.append({
                    '%': round(agg_dict[taxid]['%'], 2),
                    'cumul_reads': agg_dict[taxid]['cumul_reads'],
                    'reads': agg_dict[taxid]['reads'],
                    'rank': taxon['rank'],
                    'taxid': taxid,
                    'name': taxon['name'],
                    'parent_taxid': taxon['parent_taxid'],
                })

        result_df = pd.DataFrame(result_rows)
        # Cache the result
        _kraken_cache[cache_key] = (time.time(), result_df.copy())
        _store_mtime_cache(mtime_key, [kraken_dir], result_df.copy())
        return result_df


def load_fastp_data(main_dir: str, sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Load FASTP statistics for specific sample or all samples.

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name, or None/"All Samples" for aggregated data

    Returns:
        Dictionary with aggregated FASTP statistics:
        {
            'total_reads_before': int,
            'total_reads_after': int,
            'total_bases_before': int,
            'total_bases_after': int,
            'passed_filter': int,
            'low_quality': int,
            'too_short': int,
            'too_many_N': int
        }
    """
    # Auto-resolve to analysis directory if needed
    main_dir = resolve_analysis_directory(main_dir)

    fastp_dir = os.path.join(main_dir, "fastp")

    if not os.path.exists(fastp_dir):
        logging.warning(f"FASTP directory not found: {fastp_dir}")
        return _empty_fastp_stats()

    # Fast mtime-based check: skip parsing if fastp directory is unchanged
    fastp_cache_key = _get_cache_key(main_dir, sample)
    mtime_key = f"fastp:{fastp_cache_key}"
    mtime_cached = _check_mtime_cache(mtime_key, [fastp_dir])
    if mtime_cached is not None:
        logging.debug(f"Mtime cache hit for FASTP data: {fastp_cache_key}")
        return mtime_cached.copy() if isinstance(mtime_cached, dict) else mtime_cached

    if sample is None or sample == "All Samples":
        # Aggregate all samples
        fastp_files = glob.glob(os.path.join(fastp_dir, "*.fastp.json"))

        if not fastp_files:
            logging.warning("No FASTP files found")
            return _empty_fastp_stats()

        aggregated_stats = _empty_fastp_stats()
        _acc_q30_bases = 0

        for fastp_file in fastp_files:
            try:
                with open(fastp_file, 'r') as f:
                    fastp_data = json.load(f)

                summary = fastp_data.get("summary", {})
                before = summary.get("before_filtering", {})
                after = summary.get("after_filtering", {})
                filtering = fastp_data.get("filtering_result", {})

                aggregated_stats['total_reads_before'] += before.get("total_reads", 0)
                aggregated_stats['total_reads_after'] += after.get("total_reads", 0)
                aggregated_stats['total_bases_before'] += before.get("total_bases", 0)
                aggregated_stats['total_bases_after'] += after.get("total_bases", 0)
                aggregated_stats['passed_filter'] += filtering.get("passed_filter_reads", 0)
                aggregated_stats['low_quality'] += filtering.get("low_quality_reads", 0)
                aggregated_stats['too_short'] += filtering.get("too_short_reads", 0)
                aggregated_stats['too_many_N'] += filtering.get("too_many_N_reads", 0)
                _acc_q30_bases += after.get("q30_bases", 0)

            except Exception as e:
                logging.error(f"Error reading {fastp_file}: {e}")
                continue

        total_bases_after = aggregated_stats['total_bases_after']
        if total_bases_after > 0:
            aggregated_stats['q30_rate_after'] = _acc_q30_bases / total_bases_after
        _store_mtime_cache(mtime_key, [fastp_dir], aggregated_stats.copy())
        return aggregated_stats

    else:
        # Load specific sample - may have multiple batch files to combine
        sample_patterns = [
            os.path.join(fastp_dir, f"{sample}.fastp.json"),
            os.path.join(fastp_dir, f"{sample}_*.fastp.json")
        ]

        sample_files = []
        for pattern in sample_patterns:
            sample_files.extend(glob.glob(pattern))

        if not sample_files:
            logging.warning(f"No FASTP files found for sample {sample}")
            return _empty_fastp_stats()

        # Aggregate stats from all batch files
        aggregated_stats = _empty_fastp_stats()
        _acc_q30_bases = 0

        for sample_file in sample_files:
            try:
                with open(sample_file, 'r') as f:
                    fastp_data = json.load(f)

                summary = fastp_data.get("summary", {})
                before = summary.get("before_filtering", {})
                after = summary.get("after_filtering", {})
                filtering = fastp_data.get("filtering_result", {})

                aggregated_stats['total_reads_before'] += before.get("total_reads", 0)
                aggregated_stats['total_reads_after'] += after.get("total_reads", 0)
                aggregated_stats['total_bases_before'] += before.get("total_bases", 0)
                aggregated_stats['total_bases_after'] += after.get("total_bases", 0)
                aggregated_stats['passed_filter'] += filtering.get("passed_filter_reads", 0)
                aggregated_stats['low_quality'] += filtering.get("low_quality_reads", 0)
                aggregated_stats['too_short'] += filtering.get("too_short_reads", 0)
                aggregated_stats['too_many_N'] += filtering.get("too_many_N_reads", 0)
                _acc_q30_bases += after.get("q30_bases", 0)

            except Exception as e:
                logging.error(f"Error reading {sample_file}: {e}")
                continue

        total_bases_after = aggregated_stats['total_bases_after']
        if total_bases_after > 0:
            aggregated_stats['q30_rate_after'] = _acc_q30_bases / total_bases_after
        _store_mtime_cache(mtime_key, [fastp_dir], aggregated_stats.copy())
        return aggregated_stats


def load_batch_stats(main_dir: str, sample: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load real-time batch statistics, optionally filtered by sample.

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name to filter by, or None/"All Samples" for all batches

    Returns:
        List of batch statistics dictionaries
    """
    batch_stats_dir = os.path.join(main_dir, "realtime_batch_stats")

    if not os.path.exists(batch_stats_dir):
        logging.warning(f"Batch statistics directory not found: {batch_stats_dir}")
        return []

    batch_files = sorted(glob.glob(os.path.join(batch_stats_dir, "batch_*.json")))

    if not batch_files:
        logging.warning("No batch statistics files found")
        return []

    all_batches = []

    for batch_file in batch_files:
        try:
            with open(batch_file, 'r') as f:
                batch_data = json.load(f)

            # If sample filtering is requested, check if this batch contains the sample
            # Note: Batch files may not have sample-level detail, so we include all for now
            # This can be enhanced if batch files include per-sample breakdown
            all_batches.append(batch_data)

        except Exception as e:
            logging.error(f"Error reading {batch_file}: {e}")
            continue

    return all_batches


def get_sample_statistics_summary(main_dir: str) -> pd.DataFrame:
    """
    Get summary statistics for all samples (for per-barcode breakdown table).

    Supports both FASTP (when using fastp QC tool) and NanoPlot/Kraken2
    fallback (when using chopper QC tool).

    Returns:
        DataFrame with columns: sample, reads, base_pairs, pass_rate,
                               classified, unclassified, classified_rate, unclassified_rate,
                               mean_quality, n50
    """
    # Auto-resolve to analysis directory if needed
    main_dir = resolve_analysis_directory(main_dir)

    samples = get_available_samples(main_dir)
    summary_data = []

    for sample in samples:
        if sample == "All Samples":
            continue

        # Initialize variables
        total_reads = 0
        total_bases = 0
        pass_rate = None  # N/A when using chopper
        mean_quality = 0
        n50 = 0
        classified = 0
        unclassified = 0
        classified_rate = 0
        unclassified_rate = 0

        # Try FASTP stats first
        fastp_stats = load_fastp_data(main_dir, sample)
        reads_before = fastp_stats.get('total_reads_before', 0)
        reads_after = fastp_stats.get('total_reads_after', 0)
        bases_after = fastp_stats.get('total_bases_after', 0)

        if reads_after > 0:
            # FASTP data is available
            total_reads = reads_after
            total_bases = bases_after
            pass_rate = round((reads_after / reads_before * 100), 1) if reads_before > 0 else 0
            # Estimate mean quality from q30 rate
            q30_rate = fastp_stats.get('q30_rate_after', 0)
            if q30_rate > 0:
                mean_quality = round(10 + 25 * q30_rate, 1)
        else:
            # Fall back to NanoPlot stats (used when chopper is the QC tool)
            # First try sample-specific NanoPlot stats
            nanoplot_stats = load_nanoplot_stats(main_dir, sample)
            if nanoplot_stats.get('number_of_reads', 0) == 0:
                # If no per-sample stats, try root NanoStats.txt
                # This handles cases where nanometanf produces aggregated stats
                nanoplot_stats = load_nanoplot_stats(main_dir, None)

            if nanoplot_stats.get('number_of_reads', 0) > 0:
                total_reads = nanoplot_stats['number_of_reads']
                total_bases = nanoplot_stats.get('total_bases', 0)
                mean_quality = nanoplot_stats.get('mean_read_quality', 0)
                n50 = nanoplot_stats.get('read_length_n50', 0)

        # Get Kraken2 stats for this sample
        kraken_df = load_kraken_data(main_dir, sample)

        if not kraken_df.empty:
            total_kraken_reads = int(kraken_df['reads'].sum())
            unclassified_row = kraken_df[kraken_df['taxid'] == 0]
            unclassified = int(unclassified_row.iloc[0]['reads']) if not unclassified_row.empty else 0
            classified = total_kraken_reads - unclassified

            # If we still don't have total_reads, use Kraken2 total
            if total_reads == 0:
                total_reads = total_kraken_reads

            classified_rate = round((classified / total_kraken_reads * 100), 1) if total_kraken_reads > 0 else 0
            unclassified_rate = round((unclassified / total_kraken_reads * 100), 1) if total_kraken_reads > 0 else 0

        # Format pass_rate for display
        pass_rate_display = pass_rate if pass_rate is not None else "N/A"

        # Determine sample status based on quality metrics
        # Status logic: Good classification (>70%) + reasonable quality = OK
        # Using Unicode icons for WCAG 1.4.1 compliance (not relying on color alone)
        if total_reads == 0:
            status = "○ No Data"
        elif classified_rate >= 70:
            status = "✓ Complete"
        elif classified_rate >= 50:
            status = "⚠ Review"
        else:
            status = "✗ Issue"

        # Format classified_rate for display
        classified_rate_display = f"{classified_rate}%"

        summary_data.append({
            'sample': sample,
            'reads': total_reads,
            'base_pairs': total_bases,
            'pass_rate': pass_rate_display,
            'mean_quality': round(mean_quality, 1) if mean_quality > 0 else "N/A",
            'n50': n50 if n50 > 0 else "N/A",
            'classified': classified,
            'unclassified': unclassified,
            'classified_rate': classified_rate_display,
            'classified_rate_num': classified_rate,  # Numeric value for filtering
            'unclassified_rate': unclassified_rate,
            'status': status
        })

    return pd.DataFrame(summary_data)


def _empty_fastp_stats() -> Dict[str, int]:
    """Return empty FASTP statistics dictionary."""
    return {
        'total_reads_before': 0,
        'total_reads_after': 0,
        'total_bases_before': 0,
        'total_bases_after': 0,
        'passed_filter': 0,
        'low_quality': 0,
        'too_short': 0,
        'too_many_N': 0,
        'q30_rate_after': 0.0,
    }


def load_nanoplot_stats(main_dir: str, sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Load NanoPlot statistics for quality metrics, with seqkit fallback.

    nanometanf produces: nanoplot/<sample>/NanoStats.txt or nanoplot/NanoStats.txt
    Falls back to seqkit stats when NanoPlot data is unavailable.

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name, or None/"All Samples" for aggregated data

    Returns:
        Dictionary with quality statistics:
        {
            'mean_read_length': float,
            'mean_read_quality': float,
            'median_read_length': float,
            'median_read_quality': float,
            'number_of_reads': int,
            'read_length_n50': int,
            'total_bases': int,
            'source': str  # 'nanoplot' or 'seqkit'
        }
    """
    nanoplot_dir = os.path.join(main_dir, "nanoplot")
    nanostats_files = []

    if os.path.exists(nanoplot_dir):
        # Find NanoStats.txt files
        if sample is None or sample == "All Samples":
            # Look for NanoStats.txt in subdirectories or root
            for pattern in [
                os.path.join(nanoplot_dir, "*/NanoStats.txt"),
                os.path.join(nanoplot_dir, "NanoStats.txt")
            ]:
                nanostats_files.extend(glob.glob(pattern))
        else:
            # Look for sample-specific NanoStats
            sample_patterns = [
                os.path.join(nanoplot_dir, sample, "NanoStats.txt"),
                os.path.join(nanoplot_dir, f"{sample}_NanoStats.txt"),
                os.path.join(nanoplot_dir, f"{sample}/NanoStats.txt")
            ]
            for pattern in sample_patterns:
                if os.path.exists(pattern):
                    nanostats_files.append(pattern)

    if not nanostats_files:
        # Fall back to seqkit stats when NanoPlot data unavailable
        logging.debug("No NanoStats.txt files found, falling back to seqkit")
        return _load_seqkit_as_nanoplot_stats(main_dir, sample)

    # Parse and aggregate stats
    aggregated = _empty_nanoplot_stats()
    file_count = 0

    for stats_file in nanostats_files:
        try:
            stats = _parse_nanostats_file(stats_file)
            if stats:
                file_count += 1
                aggregated['number_of_reads'] += stats.get('number_of_reads', 0)
                aggregated['total_bases'] += stats.get('total_bases', 0)
                # For averages, we'll recalculate after summing
                aggregated['mean_read_length'] += stats.get('mean_read_length', 0)
                aggregated['mean_read_quality'] += stats.get('mean_read_quality', 0)
                aggregated['read_length_n50'] = max(
                    aggregated['read_length_n50'],
                    stats.get('read_length_n50', 0)
                )
        except Exception as e:
            logging.error(f"Error parsing {stats_file}: {e}")
            continue

    # Average the mean values
    if file_count > 0:
        aggregated['mean_read_length'] /= file_count
        aggregated['mean_read_quality'] /= file_count
        aggregated['source'] = 'nanoplot'

    return aggregated


def _parse_nanostats_file(filepath: str) -> Dict[str, Any]:
    """
    Parse a NanoStats.txt file.

    Args:
        filepath: Path to NanoStats.txt file

    Returns:
        Dictionary with parsed statistics
    """
    stats = _empty_nanoplot_stats()

    try:
        with open(filepath, 'r') as f:
            content = f.read()

        # Parse key metrics from NanoStats format
        # Note: Numbers may have comma separators (e.g., "3,911.7")
        patterns = {
            'mean_read_length': r'Mean read length:\s*([\d,]+\.?\d*)',
            'mean_read_quality': r'Mean read quality:\s*([\d,]+\.?\d*)',
            'median_read_length': r'Median read length:\s*([\d,]+\.?\d*)',
            'median_read_quality': r'Median read quality:\s*([\d,]+\.?\d*)',
            'number_of_reads': r'Number of reads:\s*([\d,]+\.?\d*)',
            'read_length_n50': r'Read length N50:\s*([\d,]+\.?\d*)',
            'total_bases': r'Total bases:\s*([\d,]+\.?\d*)'
        }

        import re
        for key, pattern in patterns.items():
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                value = match.group(1).replace(',', '')
                if key in ['mean_read_length', 'mean_read_quality',
                           'median_read_length', 'median_read_quality']:
                    stats[key] = float(value)
                else:
                    stats[key] = int(float(value))

        return stats

    except Exception as e:
        logging.error(f"Error parsing NanoStats file {filepath}: {e}")
        return _empty_nanoplot_stats()


def _empty_nanoplot_stats() -> Dict[str, Any]:
    """Return empty NanoPlot statistics dictionary."""
    return {
        'mean_read_length': 0.0,
        'mean_read_quality': 0.0,
        'median_read_length': 0.0,
        'median_read_quality': 0.0,
        'number_of_reads': 0,
        'read_length_n50': 0,
        'total_bases': 0,
        'source': 'none'
    }


def _load_seqkit_as_nanoplot_stats(main_dir: str, sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Load seqkit statistics and convert to NanoPlot-compatible format.

    This is a fallback when NanoPlot data is unavailable (e.g., nanopore pipelines
    using chopper for QC instead of NanoPlot).

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name, or None/"All Samples" for aggregated data

    Returns:
        Dictionary with quality statistics in NanoPlot format
    """
    seqkit_df = load_seqkit_stats(main_dir, sample)

    if seqkit_df.empty:
        logging.debug("No seqkit data available for fallback")
        return _empty_nanoplot_stats()

    # Aggregate seqkit stats
    total_reads = int(seqkit_df['num_seqs'].sum()) if 'num_seqs' in seqkit_df.columns else 0
    total_bases = int(seqkit_df['sum_len'].sum()) if 'sum_len' in seqkit_df.columns else 0
    mean_length = float(seqkit_df['avg_len'].mean()) if 'avg_len' in seqkit_df.columns else 0.0
    n50 = int(seqkit_df['N50'].max()) if 'N50' in seqkit_df.columns else 0

    # Use AvgQual from seqkit as mean_read_quality (Phred scale)
    mean_quality = float(seqkit_df['AvgQual'].mean()) if 'AvgQual' in seqkit_df.columns else 0.0

    # Estimate median from Q2 (second quartile = median)
    median_length = float(seqkit_df['Q2'].mean()) if 'Q2' in seqkit_df.columns else mean_length

    logging.debug(f"Seqkit fallback: {total_reads} reads, {total_bases} bases, Q={mean_quality:.1f}")

    return {
        'mean_read_length': mean_length,
        'mean_read_quality': mean_quality,
        'median_read_length': median_length,
        'median_read_quality': mean_quality,  # Seqkit doesn't provide median quality
        'number_of_reads': total_reads,
        'read_length_n50': n50,
        'total_bases': total_bases,
        'source': 'seqkit',
        # Additional seqkit-specific metrics
        'q20_percent': float(seqkit_df['Q20(%)'].mean()) if 'Q20(%)' in seqkit_df.columns else 0.0,
        'q30_percent': float(seqkit_df['Q30(%)'].mean()) if 'Q30(%)' in seqkit_df.columns else 0.0,
        'gc_percent': float(seqkit_df['GC(%)'].mean()) if 'GC(%)' in seqkit_df.columns else 0.0
    }


def load_validation_data(
    main_dir: str,
    sample: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Load unified validation data (BLAST and/or minimap2) from nanometanf output.

    Checks for results in priority order:
    1. validation/validation_results.json (nanometanf aggregate output)
    2. blast_validation/validation_summary.json (legacy format)
    3. Legacy BLAST tabular files (fallback)

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name to filter by, or None/"All Samples" for all

    Returns:
        List of ValidationResult.to_dict() entries with both BLAST and
        minimap2 results (each as a separate entry with validation_method field)
    """
    from nanometa_live.core.parsers.blast_validation_parser import ValidationParser

    main_dir = resolve_analysis_directory(main_dir)
    parser = ValidationParser(main_dir)

    filter_sample = None if (sample is None or sample == "All Samples") else sample
    results = parser.get_validation_results(sample=filter_sample)

    return [r.to_dict() for r in results]


def load_blast_validation_data(
    main_dir: str,
    watchlist: List[Dict[str, Any]],
    sample: Optional[str] = None
) -> Dict[int, Dict[str, Any]]:
    """
    Load BLAST validation data for watched species.

    BLAST validation files are generated by nanometanf when blast_validation is
    enabled. Files are named {sample}_{taxid}.txt or {taxid}.txt in BLAST
    tabular format (outfmt 6).

    Args:
        main_dir: Main nanometanf output directory
        watchlist: List of watched species dicts with 'name' and 'taxid' keys
        sample: Sample name to filter by, or None/"All Samples" for aggregated

    Returns:
        Dictionary mapping taxid to validation stats:
        {
            562: {
                'taxid': 562,
                'name': 'Escherichia coli',
                'total_reads': 1452,
                'validated_reads': 1234,
                'validation_rate': 85.0,
                'status': 'validated'  # 'validated', 'partial', 'failed', 'no_data'
            },
            ...
        }
    """
    # Auto-resolve to analysis directory if needed
    main_dir = resolve_analysis_directory(main_dir)

    # First check for nanometanf aggregate validation JSON (includes both BLAST and minimap2)
    aggregate_paths = [
        os.path.join(main_dir, "validation", "validation_results.json"),
        os.path.join(main_dir, "blast_validation", "validation_results.json"),
    ]

    for agg_path in aggregate_paths:
        if os.path.exists(agg_path):
            try:
                with open(agg_path, 'r') as f:
                    agg_data = json.load(f)

                results = {}
                filter_sample = None if (sample is None or sample == "All Samples") else sample

                for sample_id, taxid_entries in agg_data.get('results', {}).items():
                    if filter_sample and sample_id != filter_sample:
                        continue
                    for tid_str, entry in taxid_entries.items():
                        tid = int(tid_str)
                        # Check if this taxid is in the watchlist
                        watchlist_match = None
                        for s in watchlist:
                            if s.get('taxid') and int(s['taxid']) == tid:
                                watchlist_match = s
                                break
                        if not watchlist_match:
                            continue

                        # BLAST data
                        blast_hits = entry.get('blast_hits', 0)
                        hit_rate = entry.get('hit_rate', 0.0)
                        kraken_reads = entry.get('kraken_reads', 0)

                        result_entry = {
                            'taxid': tid,
                            'name': watchlist_match.get('name', f'Species {tid}'),
                            'total_reads': kraken_reads,
                            'validated_reads': blast_hits,
                            'validation_rate': round(hit_rate * 100 if hit_rate <= 1.0 else hit_rate, 1),
                            'status': entry.get('validation_status', 'no_data'),
                            'avg_identity': entry.get('avg_identity', 0.0),
                        }

                        # Map status values
                        if result_entry['status'] == 'confirmed':
                            result_entry['status'] = 'validated'
                        elif result_entry['status'] == 'uncertain':
                            result_entry['status'] = 'partial'
                        elif result_entry['status'] == 'rejected':
                            result_entry['status'] = 'failed'

                        # Add minimap2 fields if present
                        if entry.get('minimap2_mapped') is not None:
                            result_entry['minimap2_validated_reads'] = int(entry.get('minimap2_mapped', 0))
                            mm2_rate = entry.get('minimap2_hit_rate', 0.0)
                            result_entry['minimap2_validation_rate'] = round(
                                mm2_rate * 100 if mm2_rate <= 1.0 else mm2_rate, 1
                            )
                            result_entry['minimap2_identity'] = float(entry.get('minimap2_identity', 0.0))
                            result_entry['minimap2_avg_mapq'] = float(entry.get('avg_mapq', 0.0))
                            result_entry['minimap2_status'] = entry.get('minimap2_status', 'no_data')

                        results[tid] = result_entry

                if results:
                    logging.info(f"Loaded validation data from aggregate JSON: {len(results)} entries")
                    return results
            except Exception as e:
                logging.warning(f"Error reading aggregate validation JSON {agg_path}: {e}")

    # nanometanf v1.1+ publishes BLAST results to validation/blast/
    blast_dir = os.path.join(main_dir, "validation", "blast")

    # Fallback to legacy directory names
    if not os.path.exists(blast_dir):
        blast_dir = os.path.join(main_dir, "blast_validation")
    if not os.path.exists(blast_dir):
        blast_dir = os.path.join(main_dir, "blast")
    if not os.path.exists(blast_dir):
        logging.debug("BLAST validation directory not found")
        return {}

    # OPTIMIZATION: Load Kraken data ONCE outside the loop (was loading per-species)
    # This provides ~50x speedup for typical watchlists with 50+ species
    kraken_df = load_kraken_data(main_dir, sample)

    results = {}

    for species in watchlist:
        taxid = species.get('taxid')
        name = species.get('name', f'Species {taxid}')

        if taxid is None:
            continue

        # Convert taxid to int if string
        try:
            taxid = int(taxid)
        except (ValueError, TypeError):
            logging.warning(f"Invalid taxid: {taxid}")
            continue

        # Find BLAST result files for this taxid
        blast_files = []

        if sample is None or sample == "All Samples":
            # Look for all files matching this taxid
            patterns = [
                os.path.join(blast_dir, f"*_{taxid}.txt"),
                os.path.join(blast_dir, f"{taxid}.txt"),
                os.path.join(blast_dir, f"*_{taxid}_blast.txt"),
            ]
            for pattern in patterns:
                blast_files.extend(glob.glob(pattern))
        else:
            # Look for sample-specific file
            patterns = [
                os.path.join(blast_dir, f"{sample}_{taxid}.txt"),
                os.path.join(blast_dir, f"{sample}_{taxid}_blast.txt"),
            ]
            for pattern in patterns:
                if os.path.exists(pattern):
                    blast_files.append(pattern)

        # Count validated reads from all matching files
        total_validated = 0
        unique_reads = set()

        for blast_file in blast_files:
            try:
                if os.path.exists(blast_file) and os.path.getsize(blast_file) > 0:
                    with open(blast_file, 'r') as f:
                        for line in f:
                            if line.strip():
                                parts = line.strip().split('\t')
                                if parts:
                                    unique_reads.add(parts[0])
            except Exception as e:
                logging.warning(f"Error reading BLAST file {blast_file}: {e}")
                continue

        validated_count = len(unique_reads)

        # Get total reads for this species from pre-loaded Kraken data
        total_reads = 0

        if not kraken_df.empty:
            species_row = kraken_df[kraken_df['taxid'] == taxid]
            if not species_row.empty:
                total_reads = int(species_row.iloc[0]['reads'])

        # Calculate validation rate
        if total_reads > 0:
            validation_rate = (validated_count / total_reads) * 100
        else:
            validation_rate = 0.0

        # Determine validation status
        if validated_count == 0 and not blast_files:
            status = 'no_data'
        elif validation_rate >= 80:
            status = 'validated'
        elif validation_rate >= 50:
            status = 'partial'
        else:
            status = 'failed'

        results[taxid] = {
            'taxid': taxid,
            'name': name,
            'total_reads': total_reads,
            'validated_reads': validated_count,
            'validation_rate': round(validation_rate, 1),
            'status': status
        }

    return results


def load_seqkit_stats(main_dir: str, sample: Optional[str] = None) -> pd.DataFrame:
    """
    Load seqkit sequence statistics (used when QC tool is chopper).

    nanometanf produces: seqkit/<sample>.tsv
    Columns: file, format, type, num_seqs, sum_len, min_len, avg_len, max_len

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name, or None/"All Samples" for aggregated data

    Returns:
        DataFrame with seqkit statistics
    """
    seqkit_dir = os.path.join(main_dir, "seqkit")

    if not os.path.exists(seqkit_dir):
        logging.debug(f"Seqkit directory not found: {seqkit_dir}")
        return pd.DataFrame()

    if sample is None or sample == "All Samples":
        # Load all TSV files
        tsv_files = glob.glob(os.path.join(seqkit_dir, "*.tsv"))
    else:
        # Load specific sample
        sample_patterns = [
            os.path.join(seqkit_dir, f"{sample}.tsv"),
            os.path.join(seqkit_dir, f"{sample}_*.tsv")
        ]
        tsv_files = []
        for pattern in sample_patterns:
            tsv_files.extend(glob.glob(pattern))

    if not tsv_files:
        logging.debug("No seqkit TSV files found")
        return pd.DataFrame()

    all_stats = []
    for tsv_file in tsv_files:
        try:
            df = pd.read_csv(tsv_file, sep='\t')
            # Add sample column from filename
            sample_name = os.path.basename(tsv_file).replace('.tsv', '')
            df['sample'] = sample_name
            all_stats.append(df)
        except Exception as e:
            logging.error(f"Error reading seqkit file {tsv_file}: {e}")
            continue

    if not all_stats:
        return pd.DataFrame()

    combined = pd.concat(all_stats, ignore_index=True)
    return combined


def get_qc_stats(main_dir: str, sample: Optional[str] = None) -> Dict[str, Any]:
    """
    Get QC statistics from available sources (fastp, seqkit, or nanoplot).

    This is a unified interface that tries multiple sources and returns
    the best available data.

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name, or None/"All Samples" for aggregated data

    Returns:
        Dictionary with unified QC statistics
    """
    # Try fastp first
    fastp_stats = load_fastp_data(main_dir, sample)
    if fastp_stats.get('total_reads_before', 0) > 0:
        return {
            'source': 'fastp',
            'total_reads': fastp_stats['total_reads_after'],
            'total_bases': fastp_stats['total_bases_after'],
            'reads_before_filter': fastp_stats['total_reads_before'],
            'pass_rate': (fastp_stats['total_reads_after'] /
                         fastp_stats['total_reads_before'] * 100
                         if fastp_stats['total_reads_before'] > 0 else 0),
            'low_quality': fastp_stats['low_quality'],
            'too_short': fastp_stats['too_short'],
            **fastp_stats
        }

    # Try seqkit (used with chopper)
    seqkit_df = load_seqkit_stats(main_dir, sample)
    if not seqkit_df.empty:
        total_reads = seqkit_df['num_seqs'].sum() if 'num_seqs' in seqkit_df.columns else 0
        total_bases = seqkit_df['sum_len'].sum() if 'sum_len' in seqkit_df.columns else 0
        avg_len = seqkit_df['avg_len'].mean() if 'avg_len' in seqkit_df.columns else 0

        # Extract Q20% and Q30% from seqkit stats (very useful quality metrics)
        q20_pct = seqkit_df['Q20(%)'].mean() if 'Q20(%)' in seqkit_df.columns else 0
        q30_pct = seqkit_df['Q30(%)'].mean() if 'Q30(%)' in seqkit_df.columns else 0
        avg_qual = seqkit_df['AvgQual'].mean() if 'AvgQual' in seqkit_df.columns else 0
        n50 = seqkit_df['N50'].mean() if 'N50' in seqkit_df.columns else 0

        return {
            'source': 'seqkit',
            'total_reads': int(total_reads),
            'total_bases': int(total_bases),
            'avg_read_length': float(avg_len),
            'min_read_length': int(seqkit_df['min_len'].min()) if 'min_len' in seqkit_df.columns else 0,
            'max_read_length': int(seqkit_df['max_len'].max()) if 'max_len' in seqkit_df.columns else 0,
            'q20_percent': float(q20_pct),
            'q30_percent': float(q30_pct),
            'avg_quality': float(avg_qual),
            'n50': int(n50)
        }

    # Try nanoplot
    nanoplot_stats = load_nanoplot_stats(main_dir, sample)
    if nanoplot_stats.get('number_of_reads', 0) > 0:
        return {
            'source': 'nanoplot',
            'total_reads': nanoplot_stats['number_of_reads'],
            'total_bases': nanoplot_stats['total_bases'],
            'avg_read_length': nanoplot_stats['mean_read_length'],
            'mean_quality': nanoplot_stats['mean_read_quality'],
            'read_length_n50': nanoplot_stats['read_length_n50'],
            **nanoplot_stats
        }

    # No data available
    return {'source': 'none', 'total_reads': 0, 'total_bases': 0}
