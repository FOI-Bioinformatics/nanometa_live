"""
Classification data loaders for Nanometa Live.

Functions for loading and parsing Kraken2 taxonomic classification reports,
with support for batch aggregation, cumulative reports, and caching.
"""

import glob
import logging
import os
import re
import time
import pandas as pd
from typing import Dict, List, Optional, Tuple

from nanometa_live.core.utils.canonical_loaders import load_canonical_classification
from nanometa_live.core.utils.sample_detector import (
    get_available_samples,
    resolve_analysis_directory
)
from nanometa_live.core.utils.loader_utils import (
    _cache_lock,
    _kraken_cache,
    _is_file_stable,
    _get_cache_key,
    _is_cache_valid,
    _check_mtime_cache,
    _store_mtime_cache,
    _get_parse_lock,
)


# Expected columns for Kraken2 report format
KRAKEN2_EXPECTED_COLUMNS = ["%", "cumul_reads", "reads", "rank", "taxid", "name"]
KRAKEN2_EXPECTED_COLUMN_COUNT = 6


def _diagnose_empty_kraken_dir(kraken_dir: str, sample: Optional[str] = None) -> str:
    """
    Build a single-line diagnostic for the case where the loader returns no
    Kraken2 reports. Lists the directory's actual contents (capped) and the
    glob patterns the loader tried, so an operator can triage from the log
    without re-running the pipeline.
    """
    try:
        entries = sorted(os.listdir(kraken_dir))
    except OSError as exc:
        return f"kraken_dir={kraken_dir!r} unreadable: {exc}"
    files = [e for e in entries if os.path.isfile(os.path.join(kraken_dir, e))]
    subdirs = [e for e in entries if os.path.isdir(os.path.join(kraken_dir, e))]
    sample_hint = f" for sample={sample!r}" if sample else ""
    patterns = [
        "*.cumulative.kraken2.report.txt",
        "*.kraken2.report.txt",
        "*.kreport2.txt",
        "*_batch*.kraken2.report.txt",
    ]
    return (
        f"No Kraken2 reports{sample_hint} in {kraken_dir}. "
        f"Patterns tried: {patterns}. "
        f"Filename filters dropped any name containing '_batch', '.batch_', "
        f"'.cumulative.' (when looking for non-cumulative reports). "
        f"Files present ({len(files)}): {files[:10]}{'...' if len(files) > 10 else ''}. "
        f"Subdirs ({len(subdirs)}): {subdirs[:10]}{'...' if len(subdirs) > 10 else ''}."
    )


def _is_standard_report(basename: str) -> bool:
    """True for a plain (non-cumulative, non-batch) Kraken2 report filename.

    Standard reports are the per-sample end-of-run reports; cumulative
    snapshots and per-batch deltas are selected by dedicated code paths and
    must be excluded here. Centralised so the four-clause exclusion rule
    cannot drift between the call sites that filter glob results.
    """
    return (
        '.cumulative.' not in basename
        and '_batch' not in basename
        and '.batch_' not in basename
        and not basename.startswith('batch_')
    )


def _scan_subdirs_for_pattern(
    parent_dir: str,
    file_pattern: str,
    subdir: Optional[str] = None,
) -> List[str]:
    """
    Non-recursive scan of immediate subdirectories for a file glob pattern.

    This replaces ``glob.glob(parent/**/<pattern>, recursive=True)`` with a
    targeted two-level scan, avoiding the full recursive directory walk.

    Args:
        parent_dir: Top-level directory whose children are sample directories
        file_pattern: Glob pattern for filenames (e.g. ``*.kraken2.report.txt``)
        subdir: Optional subdirectory name within each sample dir (e.g. ``batch_reports``)

    Returns:
        List of matching file paths
    """
    results: List[str] = []
    try:
        entries = os.listdir(parent_dir)
    except OSError:
        return results
    for entry in entries:
        entry_path = os.path.join(parent_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        scan_path = os.path.join(entry_path, subdir) if subdir else entry_path
        if not os.path.isdir(scan_path):
            continue
        results.extend(glob.glob(os.path.join(scan_path, file_pattern)))
    return results


def _parse_kraken2_report(filepath: str, check_stability: bool = True) -> Optional[pd.DataFrame]:
    """
    Parse and validate a Kraken2 report file.

    Args:
        filepath: Path to Kraken2 report file
        check_stability: If True, verify file is not being written to (default: True)

    Returns:
        DataFrame with validated columns, or None if parsing fails or file unstable
    """
    # Guard against files that vanish or are empty (expected in real-time mode)
    try:
        if not os.path.exists(filepath):
            logging.debug("Kreport file no longer exists (may have been rotated): %s", filepath)
            return None
        if os.path.getsize(filepath) == 0:
            logging.debug("Skipping empty kreport file: %s", filepath)
            return None
    except OSError:
        logging.debug("Cannot stat kreport file (may have been removed): %s", filepath)
        return None

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
            except (ValueError, TypeError) as e:
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

    except FileNotFoundError:
        logging.debug("Kreport file disappeared during parsing (expected in real-time mode): %s", filepath)
        return None
    except OSError as e:
        logging.warning("OS error reading kreport file %s: %s", filepath, e)
        return None
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as e:
        logging.warning("Malformed Kraken2 report %s: %s", filepath, e)
        return None
    except Exception:
        # Unexpected failure in the parsing logic above. Keep a single
        # catch-all so a single corrupt file cannot bring the whole
        # dashboard down, but log with exception() so the stack trace
        # reaches the debug log.
        logging.exception("Unexpected error parsing Kraken2 report %s", filepath)
        return None


def _is_incremental_layout(kraken_dir: str, sample: Optional[str] = None) -> bool:
    """
    Detect whether the kraken2 output uses the v1.5 incremental streaming layout.

    In incremental mode (``kraken2_enable_incremental: true``) each batch
    report under ``<sample>/batch_reports/`` contains only that batch's
    reads (a delta), not a running cumulative snapshot. The presence of
    ``<sample>/stats/batch_N_report_stats.json`` is the canonical marker
    of this layout, since the older non-incremental flow does not emit
    those per-batch stats files.

    Args:
        kraken_dir: Path to the ``kraken2/`` output directory
        sample: Optional sample name. When provided, only that sample's
            subdirectory is inspected; otherwise any sample's stats
            directory is sufficient evidence.

    Returns:
        True if a per-sample ``stats/batch_*_report_stats.json`` is found.
    """
    if not os.path.isdir(kraken_dir):
        return False

    samples_to_check: List[str]
    if sample is not None:
        samples_to_check = [sample]
    else:
        try:
            samples_to_check = [
                entry for entry in os.listdir(kraken_dir)
                if os.path.isdir(os.path.join(kraken_dir, entry))
            ]
        except OSError:
            return False

    for sample_name in samples_to_check:
        stats_dir = os.path.join(kraken_dir, sample_name, "stats")
        if not os.path.isdir(stats_dir):
            continue
        try:
            for entry in os.listdir(stats_dir):
                if entry.startswith("batch_") and entry.endswith("_report_stats.json"):
                    return True
        except OSError:
            continue
    return False


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
    Load Kraken2 classification data for a specific sample or all samples.

    The loader resolves the cumulative read counts using a layered fallback:

    1. Flat ``*.cumulative.kraken2.report.txt`` (preferred, already aggregated).
    2. Standard non-batch report (``{sample}.kraken2.report.txt``).
    3. Batch reports. Their semantics depend on the upstream layout:
       legacy ``{sample}_batch{N}`` files are cumulative snapshots, so only
       the highest-numbered batch is read; v1.5 incremental
       ``<sample>/batch_reports/batch_N`` files are deltas, so all batches
       are summed per taxid. The two cases are distinguished by
       ``_is_incremental_layout``.

    Uses time-based caching to reduce file system operations and
    auto-resolves the base directory to the most recent analysis run when
    the supplied path points to a parent directory.

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
    # Auto-resolve to analysis directory if main_dir is base directory
    main_dir = resolve_analysis_directory(main_dir)

    # Try canonical format first (waterfall pattern)
    if sample is not None and sample != "All Samples":
        canonical_df = load_canonical_classification(main_dir, sample)
        if canonical_df is not None:
            logging.debug("Using canonical classification for %s", sample)
            return canonical_df

    # Check cache first
    cache_key = _get_cache_key(main_dir, sample)

    kraken_dir = os.path.join(main_dir, "kraken2")

    # Fast mtime-based check: if the kraken2 directory has not changed,
    # return the previously cached result without any parsing or TTL lookup.
    # NOTE: .copy() on cache returns has been removed. All callback callers
    # that mutate the DataFrame already copy() before modification (verified
    # in main_tab.py, classification_tab.py). The cache stores its own copy
    # at write time, so the cached object is safe.
    mtime_key = f"kraken:{cache_key}"
    if os.path.isdir(kraken_dir):
        mtime_cached = _check_mtime_cache(mtime_key, [kraken_dir])
        if mtime_cached is not None:
            logging.debug(f"Mtime cache hit for Kraken data: {cache_key}")
            return mtime_cached

    # Fall back to TTL-based cache
    with _cache_lock:
        if cache_key in _kraken_cache:
            cache_time, cached_df = _kraken_cache[cache_key]
            if _is_cache_valid(cache_time):
                logging.debug(f"Using cached Kraken data for {cache_key}")
                return cached_df

    # Serialize the parse path: concurrent callbacks that all miss above
    # would otherwise each start their own full re-parse. Holding a
    # per-key lock makes second-through-Nth callers wait ~ms then take
    # the cached result the first caller just stored.
    parse_lock = _get_parse_lock(cache_key)
    with parse_lock:
        # Re-check mtime and TTL cache after acquiring the lock. The first
        # waiter to win the lock parses; subsequent waiters find the
        # result already cached and return without re-parsing.
        if os.path.isdir(kraken_dir):
            mtime_cached = _check_mtime_cache(mtime_key, [kraken_dir])
            if mtime_cached is not None:
                return mtime_cached
        with _cache_lock:
            if cache_key in _kraken_cache:
                cache_time, cached_df = _kraken_cache[cache_key]
                if _is_cache_valid(cache_time):
                    return cached_df

        return _parse_kraken_data_uncached(
            main_dir, sample, cache_key, kraken_dir, mtime_key
        )


def _accumulate_kraken_df(
    df: pd.DataFrame,
    agg: Dict[int, List],
    ordered_taxids: List[int],
    seen_taxids: set,
) -> None:
    """Accumulate one parsed kraken report into the aggregation state.

    Reads and cumulative reads are summed per taxid; the remaining
    columns (rank, name, parent_taxid) are taken from the first
    occurrence. New taxids are appended to ``ordered_taxids`` in
    first-seen order. Vectorized extraction avoids per-row overhead.
    """
    taxids = df['taxid'].astype(int).values
    reads_arr = df['reads'].values
    cumul_arr = df['cumul_reads'].values
    ranks = df['rank'].values
    names = df['name'].values
    parent_taxids_arr = df['parent_taxid'].values if 'parent_taxid' in df.columns else [0] * len(df)
    for i in range(len(df)):
        taxid = int(taxids[i])
        if taxid in agg:
            agg[taxid][0] += reads_arr[i]
            agg[taxid][1] += cumul_arr[i]
        else:
            agg[taxid] = [reads_arr[i], cumul_arr[i], ranks[i], names[i], parent_taxids_arr[i]]
            if taxid not in seen_taxids:
                ordered_taxids.append(taxid)
                seen_taxids.add(taxid)


def _parse_kraken_data_uncached(
    main_dir: str,
    sample: Optional[str],
    cache_key: str,
    kraken_dir: str,
    mtime_key: str,
) -> pd.DataFrame:
    """Parse Kraken2 reports without consulting any cache.

    Caller must hold the parse lock for ``cache_key`` and have already
    re-checked the mtime and TTL caches. The function is internal; outside
    callers should use ``load_kraken_data``.
    """
    if not os.path.exists(kraken_dir):
        # DEBUG, not WARNING: a missing kraken2/ subdir is the normal
        # state for a freshly-configured results folder before the
        # pipeline has run. Logging it at WARNING produced terminal
        # noise on every callback that touched the loader during
        # Configuration-tab interactions on a fresh outdir. The
        # equivalent miss in sample_detector already logs at DEBUG.
        logging.debug(f"Kraken2 directory not found: {kraken_dir}")
        return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

    if sample is None or sample == "All Samples":
        # Load and aggregate all samples.
        # Strategy: use targeted non-recursive globs at the top-level first
        # (the common case), falling back to recursive scans only when the
        # v1.5 nested directory layout is in use.
        kreport_files: List[str] = []

        # 1. Cumulative reports (preferred for realtime mode) -- top-level only
        kreport_files = glob.glob(
            os.path.join(kraken_dir, "*.cumulative.kraken2.report.txt")
        )

        # 1b. Fallback: check v1.5 nested subdirs for cumulative reports
        if not kreport_files:
            kreport_files = _scan_subdirs_for_pattern(
                kraken_dir, "*.cumulative.kraken2.report.txt"
            )

        if kreport_files:
            kreport_files = list(dict.fromkeys(os.path.realpath(f) for f in kreport_files))
            logging.debug(f"Found {len(kreport_files)} cumulative Kraken2 reports")
        else:
            # 2. Standard (non-batch, non-cumulative) reports -- top-level
            for ext_pattern in ("*.kraken2.report.txt", "*.kreport2.txt"):
                for f in glob.glob(os.path.join(kraken_dir, ext_pattern)):
                    basename = os.path.basename(f)
                    if _is_standard_report(basename):
                        kreport_files.append(f)

            # 2b. Fallback: v1.5 nested subdirs
            if not kreport_files:
                for ext_pattern in ("*.kraken2.report.txt", "*.kreport2.txt"):
                    for f in _scan_subdirs_for_pattern(kraken_dir, ext_pattern):
                        basename = os.path.basename(f)
                        if _is_standard_report(basename):
                            kreport_files.append(f)

            # 2c. Final flat-root re-scan as a defensive fallback for
            # ``per_file`` and ``single_sample`` layouts emitted by
            # nanometanf, where reports sit directly under ``kraken2/``
            # without a per-sample subdirectory. Step 2a already covers
            # this case in normal operation; the duplicate scan guards
            # against future filter changes that might drop reports out
            # of 2a while no nested layout is present.
            if not kreport_files:
                for ext_pattern in ("*.kraken2.report.txt", "*.kreport2.txt"):
                    for f in glob.glob(os.path.join(kraken_dir, ext_pattern)):
                        basename = os.path.basename(f)
                        if _is_standard_report(basename):
                            kreport_files.append(f)

            kreport_files = list(dict.fromkeys(os.path.realpath(f) for f in kreport_files))

            # 3. Batch files as last resort. The semantics depend on the
            # upstream layout, so we dispatch via ``_is_incremental_layout``:
            #
            #   * Legacy (non-incremental): flat ``{sample}_batch{N}`` files
            #     are CUMULATIVE snapshots. We keep only the highest-numbered
            #     batch per sample (matches the 2026-04-15 audit fix).
            #   * v1.5 incremental: ``<sample>/batch_reports/batch_N`` files
            #     are DELTAS. All batches are kept; the per-taxid aggregation
            #     below sums them. The all-samples aggregation happens to
            #     work for both modes because it accumulates by taxid across
            #     every retained file.
            if not kreport_files:
                logging.debug("No standard reports found, looking for batch files")
                candidate_batches: List[str] = []
                # Top-level batch files
                for ext_pattern in ("*_batch*.kraken2.report.txt", "*_batch*.kreport2.txt"):
                    candidate_batches.extend(glob.glob(os.path.join(kraken_dir, ext_pattern)))
                # v1.5: batch_reports/ inside per-sample subdirs
                candidate_batches.extend(
                    _scan_subdirs_for_pattern(kraken_dir, "*.kraken2.report.txt", subdir="batch_reports")
                )
                # Deduplicate: same batch may appear in reports/ and batch_reports/
                candidate_batches = _deduplicate_batch_files(candidate_batches)

                if candidate_batches:
                    if _is_incremental_layout(kraken_dir):
                        # Incremental deltas - keep every batch so the
                        # aggregation loop sums per taxid across batches.
                        kreport_files = candidate_batches
                        logging.debug(
                            "Incremental Kraken2 layout detected: summing "
                            "%d batch reports across all samples",
                            len(candidate_batches),
                        )
                    else:
                        # Legacy snapshots: keep one (highest-numbered) per sample.
                        _batch_num_re = re.compile(r'batch[_\-]?(\d+)', re.IGNORECASE)
                        _batch_suffix_re = re.compile(r'[._]batch[_\-]?\d+$', re.IGNORECASE)

                        def _batch_sample(fp: str) -> str:
                            basename = os.path.basename(fp)
                            stem = re.sub(
                                r'\.(cumulative\.kraken2\.report|kraken2\.report|kreport2)\.txt$',
                                '', basename,
                            )
                            # Strip batch_N suffix if it is embedded in the filename.
                            stripped = _batch_suffix_re.sub('', stem)
                            if stripped and stripped != stem:
                                return stripped
                            # Fall back to the containing directory (v1.5 nested
                            # layout publishes batch_N.kraken2.report.txt inside
                            # the per-sample batch_reports/ folder).
                            parts = fp.replace('\\', '/').split('/')
                            for i, part in enumerate(parts):
                                if part in ('batch_reports', 'reports', 'batches') and i > 0:
                                    return parts[i - 1]
                            return stem

                        def _batch_num(fp: str) -> int:
                            m = _batch_num_re.search(os.path.basename(fp))
                            return int(m.group(1)) if m else -1

                        by_sample: Dict[str, str] = {}
                        for fp in candidate_batches:
                            sample_key = _batch_sample(fp)
                            current = by_sample.get(sample_key)
                            if current is None or _batch_num(fp) > _batch_num(current):
                                by_sample[sample_key] = fp
                        kreport_files = list(by_sample.values())
                        logging.debug(
                            f"Selected {len(kreport_files)} latest-per-sample batch "
                            f"Kraken2 reports from {len(candidate_batches)} candidates"
                        )

        if not kreport_files:
            logging.warning(_diagnose_empty_kraken_dir(kraken_dir))
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        # Deduplicate by (sample, batch) so that copies of the same report
        # in different directories (e.g. top-level + subdir, or
        # ``reports/`` + ``batch_reports/``) do not multi-count reads.
        # Files from per-sample subdirectories carry their containing folder
        # in the key so that files with identical basenames but different
        # samples (e.g. ``barcode01/batch_reports/batch_0`` and
        # ``barcode02/batch_reports/batch_0``) are kept distinct.
        seen_keys: set = set()
        deduplicated_files = []
        for kreport_file in kreport_files:
            basename = os.path.basename(kreport_file)
            stem = re.sub(
                r'\.(cumulative\.kraken2\.report|kraken2\.report|kreport2)\.txt$',
                '', basename
            )
            parent_dir = os.path.basename(os.path.dirname(kreport_file))
            grandparent = os.path.basename(os.path.dirname(os.path.dirname(kreport_file)))
            # Use the per-sample directory as namespace when present so that
            # incremental batches under ``<sample>/batch_reports/`` are
            # disambiguated by sample.
            if parent_dir in ("batch_reports", "reports", "batches"):
                dedup_key = (grandparent, stem)
            else:
                dedup_key = (parent_dir, stem)
            if dedup_key in seen_keys:
                logging.debug(
                    f"Skipping duplicate report for {dedup_key}: {kreport_file}"
                )
                continue
            seen_keys.add(dedup_key)
            deduplicated_files.append(kreport_file)
        kreport_files = deduplicated_files

        # Incremental aggregation: accumulate reads/cumul_reads per taxid in
        # a running dict, avoiding pd.concat of all raw reports (O(unique_taxa)
        # memory instead of O(all_rows_across_files)).
        agg: Dict[int, List] = {}  # taxid -> [reads, cumul_reads, rank, name, parent_taxid]
        ordered_taxids: List[int] = []  # insertion-order for hierarchy
        seen_taxids: set = set()
        has_data = False

        for kreport_file in kreport_files:
            df = _parse_kraken2_report(kreport_file)
            if df is None or df.empty:
                continue
            has_data = True
            _accumulate_kraken_df(df, agg, ordered_taxids, seen_taxids)

        if not has_data:
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        # Compute percentages from total reads
        total_reads = sum(v[0] for v in agg.values())

        result_rows = []
        for taxid in ordered_taxids:
            reads, cumul, rank, name, parent_taxid = agg[taxid]
            pct = round((reads / total_reads) * 100, 2) if total_reads > 0 else 0.0
            result_rows.append({
                '%': pct,
                'cumul_reads': cumul,
                'reads': reads,
                'rank': rank,
                'taxid': taxid,
                'name': name,
                'parent_taxid': parent_taxid,
            })

        result_df = pd.DataFrame(result_rows)
        # Cache the aggregated all-samples result
        with _cache_lock:
            _kraken_cache[cache_key] = (time.time(), result_df.copy())
        _store_mtime_cache(mtime_key, [kraken_dir], result_df.copy())
        return result_df

    else:
        # Load specific sample - may have multiple batch files to combine.
        # Use direct path construction + os.path.exists() first (O(1) stat),
        # falling back to glob only for v1.5 nested layouts.
        sample_files: List[str] = []

        # 1. Cumulative report (preferred - already aggregated)
        cumul_path = os.path.join(kraken_dir, f"{sample}.cumulative.kraken2.report.txt")
        if os.path.exists(cumul_path):
            sample_files = [cumul_path]
        else:
            # v1.5 fallback: check sample subdir
            nested_cumul = os.path.join(kraken_dir, sample, f"{sample}.cumulative.kraken2.report.txt")
            if os.path.exists(nested_cumul):
                sample_files = [nested_cumul]

        if sample_files:
            logging.debug(f"Found cumulative Kraken2 report for {sample}")
        else:
            # 2. Standard (non-batch) reports via direct path
            for ext in (f"{sample}.kraken2.report.txt", f"{sample}.kreport2.txt"):
                p = os.path.join(kraken_dir, ext)
                if os.path.exists(p):
                    sample_files.append(p)
            # v1.5 nested fallback
            if not sample_files:
                for ext in (f"{sample}.kraken2.report.txt", f"{sample}.kreport2.txt"):
                    p = os.path.join(kraken_dir, sample, ext)
                    if os.path.exists(p):
                        sample_files.append(p)
            # Final flat-root re-check. Mirrors the all-samples branch
            # above; defensive against the nested fallback claiming a
            # path that disappeared between checks, and makes the flat
            # ``per_file``/``single_sample`` layout explicit at the
            # per-sample call site.
            if not sample_files:
                for ext in (f"{sample}.kraken2.report.txt", f"{sample}.kreport2.txt"):
                    p = os.path.join(kraken_dir, ext)
                    if os.path.exists(p):
                        sample_files.append(p)
            sample_files = list(dict.fromkeys(os.path.realpath(f) for f in sample_files))

            # 3. Batch files. The semantics depend on the upstream layout:
            #
            #   * Legacy (non-incremental) flow publishes flat
            #     ``{sample}_batch{N}.kraken2.report.txt`` files where each
            #     report is a CUMULATIVE snapshot containing all reads since
            #     run start. The correct choice is the highest-numbered batch.
            #   * v1.5+ incremental flow (``kraken2_enable_incremental: true``)
            #     publishes ``<sample>/batch_reports/batch_N.kraken2.report.txt``
            #     where each report is a DELTA covering only that batch. The
            #     correct choice is the sum of all batches.
            #
            # We dispatch on the layout via ``_is_incremental_layout`` (which
            # checks for the ``<sample>/stats/batch_N_report_stats.json``
            # files emitted only by the incremental writer).
            if not sample_files:
                candidate_batches: List[str] = []
                for ext_pattern in (f"{sample}_batch*.kraken2.report.txt", f"{sample}_batch*.kreport2.txt"):
                    candidate_batches.extend(glob.glob(os.path.join(kraken_dir, ext_pattern)))
                # v1.5: batch_reports/ subdirectory inside per-sample folder
                batch_dir = os.path.join(kraken_dir, sample, "batch_reports")
                if os.path.isdir(batch_dir):
                    candidate_batches.extend(
                        glob.glob(os.path.join(batch_dir, "*.kraken2.report.txt"))
                    )
                # Deduplicate: same batch may appear in reports/ and batch_reports/
                candidate_batches = _deduplicate_batch_files(candidate_batches)
                if candidate_batches:
                    if _is_incremental_layout(kraken_dir, sample):
                        # Incremental deltas - use every batch and let the
                        # aggregation logic below sum them per taxid.
                        sample_files = candidate_batches
                        logging.debug(
                            "Incremental Kraken2 layout detected for %s: "
                            "summing %d batch reports",
                            sample, len(candidate_batches),
                        )
                    else:
                        _batch_num_re = re.compile(r'batch[_\-]?(\d+)', re.IGNORECASE)
                        def _extract_batch_num(fp: str) -> int:
                            m = _batch_num_re.search(os.path.basename(fp))
                            return int(m.group(1)) if m else -1
                        sample_files = [max(candidate_batches, key=_extract_batch_num)]

        if not sample_files:
            # Per-sample miss is DEBUG when the directory already
            # contains kraken reports for *other* samples (the
            # requested sample's file simply has not landed yet during
            # a live run). The full diagnostic stays WARNING when the
            # directory is genuinely empty / unreadable, since that is
            # the operator-facing failure mode the helper was added
            # for. The whole-dir scan path below keeps WARNING
            # unconditionally.
            try:
                has_any_kreports = any(
                    f.endswith(".kraken2.report.txt") or f.endswith(".kreport2.txt")
                    for f in os.listdir(kraken_dir)
                )
            except OSError:
                has_any_kreports = False
            level = logging.DEBUG if has_any_kreports else logging.WARNING
            logging.log(level, _diagnose_empty_kraken_dir(kraken_dir, sample=sample))
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        # Parse files, using single-file fast path when possible
        first_df = None
        file_count = 0
        # Incremental aggregation dict for multi-batch case
        agg: Dict[int, List] = {}
        ordered_taxids: List[int] = []
        seen_taxids: set = set()

        for sample_file in sample_files:
            df = _parse_kraken2_report(sample_file)
            if df is None or df.empty:
                continue
            file_count += 1
            if file_count == 1:
                first_df = df
            _accumulate_kraken_df(df, agg, ordered_taxids, seen_taxids)

        if file_count == 0:
            return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)

        # If only one file, return its DataFrame directly (no aggregation needed)
        if file_count == 1:
            result_df = first_df
            _kraken_cache[cache_key] = (time.time(), result_df.copy())
            _store_mtime_cache(mtime_key, [kraken_dir], result_df.copy())
            return result_df

        # Build aggregated result from running dict
        total_reads = sum(v[0] for v in agg.values())

        result_rows = []
        for taxid in ordered_taxids:
            reads, cumul, rank, name, parent_taxid = agg[taxid]
            pct = round((reads / total_reads) * 100, 2) if total_reads > 0 else 0.0
            result_rows.append({
                '%': pct,
                'cumul_reads': cumul,
                'reads': reads,
                'rank': rank,
                'taxid': taxid,
                'name': name,
                'parent_taxid': parent_taxid,
            })

        result_df = pd.DataFrame(result_rows)
        # Cache the per-sample result
        with _cache_lock:
            _kraken_cache[cache_key] = (time.time(), result_df.copy())
        _store_mtime_cache(mtime_key, [kraken_dir], result_df.copy())
        return result_df


def load_kraken_latest_batch(main_dir: str, sample_name: str) -> pd.DataFrame:
    """Return the latest batch report for a single sample.

    Returns the highest-numbered batch file found under
    ``<sample>/batch_reports/`` or the top-level kraken2 directory, falling
    back to a standard per-sample report when no batch files exist.

    The same selection (highest-numbered batch) yields the intended
    "latest batch" semantics in both upstream layouts:

    * Legacy non-incremental: each batch is a cumulative snapshot, so the
      highest batch is the most recent total — equivalent to SeqKit's
      latest-batch view.
    * v1.5 incremental: each batch is a delta covering only that batch, so
      the highest batch is exactly the reads added since the previous batch.

    Cumulative reports are deliberately not consulted because they span
    all batches and would inflate counts relative to the latest-batch
    horizon used by SeqKit.

    Args:
        main_dir: Main nanometanf output directory
        sample_name: Sample barcode/name (not "All Samples")

    Returns:
        DataFrame with columns: %, cumul_reads, reads, rank, taxid, name.
        Empty DataFrame if no suitable file is found.
    """
    main_dir = resolve_analysis_directory(main_dir)
    kraken_dir = os.path.join(main_dir, "kraken2")

    # 1. Collect candidate batch files and pick the highest-numbered one.
    candidate_batches: List[str] = []
    for ext_pattern in (
        f"{sample_name}_batch*.kraken2.report.txt",
        f"{sample_name}_batch*.kreport2.txt",
    ):
        candidate_batches.extend(glob.glob(os.path.join(kraken_dir, ext_pattern)))

    # v1.5 layout: batch_reports/ inside per-sample subdirectory
    batch_dir = os.path.join(kraken_dir, sample_name, "batch_reports")
    if os.path.isdir(batch_dir):
        candidate_batches.extend(
            glob.glob(os.path.join(batch_dir, "*.kraken2.report.txt"))
        )

    if candidate_batches:
        candidate_batches = _deduplicate_batch_files(candidate_batches)
        _batch_num_re = re.compile(r"batch[_\-]?(\d+)", re.IGNORECASE)

        def _extract_num(fp: str) -> int:
            m = _batch_num_re.search(os.path.basename(fp))
            return int(m.group(1)) if m else -1

        latest = max(candidate_batches, key=_extract_num)
        logging.debug("Latest batch file for %s: %s", sample_name, latest)
        df = _parse_kraken2_report(latest)
        if df is not None:
            return df

    # 2. Fall back to standard (non-cumulative) report when no batch files exist.
    for ext in (
        f"{sample_name}.kraken2.report.txt",
        f"{sample_name}.kreport2.txt",
    ):
        for candidate in (
            os.path.join(kraken_dir, ext),
            os.path.join(kraken_dir, sample_name, ext),
        ):
            if os.path.exists(candidate):
                df = _parse_kraken2_report(candidate)
                if df is not None:
                    logging.debug(
                        "Using standard report as latest-batch for %s: %s",
                        sample_name,
                        candidate,
                    )
                    return df

    logging.debug(
        "No latest-batch report found for sample %s in %s", sample_name, kraken_dir
    )
    return pd.DataFrame(columns=KRAKEN2_EXPECTED_COLUMNS)


def describe_kraken_scan_locations(main_dir: str) -> Dict[str, object]:
    """Return a structured description of where the Kraken2 loader looks.

    Used by the Analyze-error toast to tell the operator the absolute
    path the loader scanned and the glob patterns it tried, so a
    'Kraken2 reports not found' message can be diagnosed without
    reading the source. The patterns mirror the priority order in
    ``_parse_kraken_data_uncached``.

    Returns a dict with keys:
      - ``kraken_dir``: absolute path scanned (or expected, if absent).
      - ``exists``: True iff ``kraken_dir`` is a directory on disk.
      - ``patterns``: ordered list of glob patterns the loader tries.
    """
    resolved = resolve_analysis_directory(main_dir) if main_dir else ""
    kraken_dir = (
        os.path.abspath(os.path.join(resolved, "kraken2")) if resolved else ""
    )
    return {
        "kraken_dir": kraken_dir,
        "exists": bool(kraken_dir) and os.path.isdir(kraken_dir),
        "patterns": [
            "*.cumulative.kraken2.report.txt",
            "*.kraken2.report.txt",
            "*.kreport2.txt",
            "*.kreport2",
        ],
    }
