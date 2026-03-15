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
)


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
    # NOTE: .copy() on cache hits is intentional. Multiple Dash callbacks may
    # receive the same DataFrame concurrently; without copy, any callback that
    # modifies the frame (e.g. filtering, adding columns) would corrupt the
    # shared cached object. The copy cost is modest relative to the I/O saved.
    mtime_key = f"kraken:{cache_key}"
    if os.path.isdir(kraken_dir):
        mtime_cached = _check_mtime_cache(mtime_key, [kraken_dir])
        if mtime_cached is not None:
            logging.debug(f"Mtime cache hit for Kraken data: {cache_key}")
            return mtime_cached.copy()

    # Fall back to TTL-based cache
    with _cache_lock:
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

        # Deduplicate by sample name: if multiple files resolve to the same
        # sample (e.g. top-level and subdir copies), keep only the first to
        # prevent double-counting reads across duplicate report files.
        seen_samples = set()
        deduplicated_files = []
        for kreport_file in kreport_files:
            basename = os.path.basename(kreport_file)
            sample_name = re.sub(
                r'\.(cumulative\.kraken2\.report|kraken2\.report|kreport2)\.txt$',
                '', basename
            )
            if sample_name in seen_samples:
                logging.debug(
                    f"Skipping duplicate report for sample {sample_name}: {kreport_file}"
                )
                continue
            seen_samples.add(sample_name)
            deduplicated_files.append(kreport_file)
        kreport_files = deduplicated_files

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
        with _cache_lock:
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
        with _cache_lock:
            _kraken_cache[cache_key] = (time.time(), result_df.copy())
        _store_mtime_cache(mtime_key, [kraken_dir], result_df.copy())
        return result_df
