"""
QC data loaders for Nanometa Live.

Functions for loading quality control statistics from fastp, NanoPlot,
and seqkit outputs, with support for sample filtering and aggregation.
"""

import glob
import json
import logging
import os
import re
import pandas as pd
from typing import Any, Dict, List, Optional

from nanometa_live.core.utils.canonical_loaders import load_canonical_qc_stats
from nanometa_live.core.utils.sample_detector import (
    get_available_samples,
    resolve_analysis_directory
)
from nanometa_live.core.utils.loader_utils import (
    _fastp_cache,
    _cache_lock,
    _get_cache_key,
    _check_mtime_cache,
    _store_mtime_cache,
    _is_file_stable,
)


def _validate_fastp_json(fastp_data: Dict, filepath: str) -> bool:
    """Check that a parsed FASTP JSON contains the expected structure.

    Returns True if the required keys are present, False otherwise.
    Logs a warning when the file appears truncated or malformed.
    """
    summary = fastp_data.get("summary")
    if not isinstance(summary, dict):
        logging.warning("FASTP file missing 'summary' key (truncated?): %s", filepath)
        return False
    if "before_filtering" not in summary:
        logging.warning("FASTP file missing 'summary.before_filtering' (truncated?): %s", filepath)
        return False
    if "after_filtering" not in summary:
        logging.warning("FASTP file missing 'summary.after_filtering' (truncated?): %s", filepath)
        return False
    return True


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

    # Try canonical format first (waterfall pattern)
    if sample is not None and sample != "All Samples":
        canonical = load_canonical_qc_stats(main_dir, sample)
        if canonical is not None:
            logging.debug("Using canonical QC stats for %s", sample)
            return canonical

    fastp_dir = os.path.join(main_dir, "fastp")

    if not os.path.exists(fastp_dir):
        logging.debug(f"FASTP directory not found: {fastp_dir}")
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
                if not _is_file_stable(fastp_file):
                    logging.debug(f"Skipping unstable file: {fastp_file}")
                    continue

                with open(fastp_file, 'r') as f:
                    fastp_data = json.load(f)

                if not _validate_fastp_json(fastp_data, fastp_file):
                    continue

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

            except json.JSONDecodeError as e:
                logging.warning(f"Malformed JSON in {fastp_file}: {e}")
                continue
            except OSError as e:
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
                if not _is_file_stable(sample_file):
                    logging.debug(f"Skipping unstable file: {sample_file}")
                    continue

                with open(sample_file, 'r') as f:
                    fastp_data = json.load(f)

                if not _validate_fastp_json(fastp_data, sample_file):
                    continue

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

            except json.JSONDecodeError as e:
                logging.warning(f"Malformed JSON in {sample_file}: {e}")
                continue
            except OSError as e:
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
            if not _is_file_stable(batch_file):
                logging.debug(f"Skipping unstable batch file: {batch_file}")
                continue

            with open(batch_file, 'r') as f:
                batch_data = json.load(f)

            all_batches.append(batch_data)

        except json.JSONDecodeError as e:
            logging.warning(f"Malformed JSON in {batch_file}: {e}")
            continue
        except OSError as e:
            logging.error(f"Error reading {batch_file}: {e}")
            continue

    return all_batches


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
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.warning(f"Cannot read NanoStats file {stats_file}: {e}")
            continue
        except (ValueError, KeyError, TypeError) as e:
            logging.warning(f"Malformed NanoStats file {stats_file}: {e}")
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

    except (FileNotFoundError, PermissionError, OSError) as e:
        logging.warning(f"Cannot read NanoStats file {filepath}: {e}")
        return _empty_nanoplot_stats()
    except (ValueError, TypeError) as e:
        logging.warning(f"Malformed NanoStats file {filepath}: {e}")
        return _empty_nanoplot_stats()


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


def _is_incremental_seqkit_layout(
    seqkit_dir: str, sample: Optional[str] = None
) -> bool:
    """
    Detect whether seqkit output uses the v1.5 incremental streaming layout.

    In incremental mode each batch is published as a separate TSV under
    ``seqkit/<sample>/batch_stats/`` and the merged cumulative file
    (``seqkit/<sample>.tsv``) is only written by ``SEQKIT_MERGE_STATS`` at
    end-of-stream. Under realtime + timeout shutdown the merge step does
    not run, so the GUI sees only the per-batch TSVs and must aggregate
    them itself. The presence of ``<sample>/batch_stats/*.tsv`` together
    with the absence of the flat ``<sample>.tsv`` is the canonical marker
    of this state.

    Args:
        seqkit_dir: Path to the ``seqkit/`` output directory.
        sample: Optional sample name. When provided, only that sample's
            subdirectory is inspected; otherwise any sample with a
            ``batch_stats/`` directory is sufficient evidence.

    Returns:
        True when at least one sample has ``<sample>/batch_stats/*.tsv``
        but no flat ``<sample>.tsv`` companion.
    """
    if not os.path.isdir(seqkit_dir):
        return False

    samples_to_check: List[str]
    if sample is not None and sample != "All Samples":
        samples_to_check = [sample]
    else:
        try:
            samples_to_check = [
                entry for entry in os.listdir(seqkit_dir)
                if os.path.isdir(os.path.join(seqkit_dir, entry))
            ]
        except OSError:
            return False

    for sample_name in samples_to_check:
        batch_stats_dir = os.path.join(seqkit_dir, sample_name, "batch_stats")
        if not os.path.isdir(batch_stats_dir):
            continue
        try:
            has_batch_tsv = any(
                entry.endswith(".tsv")
                for entry in os.listdir(batch_stats_dir)
            )
        except OSError:
            continue
        if not has_batch_tsv:
            continue
        flat_tsv = os.path.join(seqkit_dir, f"{sample_name}.tsv")
        if not os.path.exists(flat_tsv):
            return True
    return False


def load_seqkit_stats(main_dir: str, sample: Optional[str] = None) -> pd.DataFrame:
    """
    Load seqkit sequence statistics (used when QC tool is chopper).

    The loader supports three upstream layouts:

    1. Flat ``seqkit/<sample>.tsv`` (nanometanf v1.4 and earlier; also the
       end-of-stream output of ``SEQKIT_MERGE_STATS`` in v1.5).
    2. Nested ``seqkit/<sample>/stats/*.tsv`` (older nanometanf nested
       layout, retained for backwards compatibility).
    3. Incremental ``seqkit/<sample>/batch_stats/*.tsv`` (nanometanf v1.5
       streaming mode). Each TSV is a single-batch snapshot; the merged
       cumulative file is only published at end-of-stream, so a realtime
       run that hits the configured timeout exposes only the per-batch
       files. In that state the loader sums ``num_seqs`` and ``sum_len``
       across batches and recomputes the quality metrics as a per-base
       weighted average, mirroring the SEQKIT_MERGE_STATS Python script
       in the nanometanf pipeline.

    Layouts (1) and (2) are read directly. Layout (3) is detected via
    ``_is_incremental_seqkit_layout`` and aggregated per sample.

    Args:
        main_dir: Main nanometanf output directory
        sample: Sample name, or None/"All Samples" for aggregated data

    Returns:
        DataFrame with seqkit statistics. One row per sample in the
        incremental case; one row per source TSV otherwise.
    """
    seqkit_dir = os.path.join(main_dir, "seqkit")

    if not os.path.exists(seqkit_dir):
        logging.debug(f"Seqkit directory not found: {seqkit_dir}")
        return pd.DataFrame()

    incremental = _is_incremental_seqkit_layout(seqkit_dir, sample)

    if sample is None or sample == "All Samples":
        # Load all TSV files (flat and nanometanf v1.5 nested layout)
        tsv_files = glob.glob(os.path.join(seqkit_dir, "*.tsv"))
        tsv_files.extend(glob.glob(os.path.join(seqkit_dir, "*/stats/*.tsv")))
    else:
        # Load specific sample (flat and nested layouts)
        sample_patterns = [
            os.path.join(seqkit_dir, f"{sample}.tsv"),
            os.path.join(seqkit_dir, f"{sample}_*.tsv"),
            os.path.join(seqkit_dir, f"{sample}/stats/*.tsv"),
        ]
        tsv_files = []
        for pattern in sample_patterns:
            tsv_files.extend(glob.glob(pattern))

    if incremental:
        incremental_df = _load_seqkit_incremental(seqkit_dir, sample)
        if not incremental_df.empty:
            if tsv_files:
                # A flat or nested TSV exists for some samples but not the
                # incremental one; combine the legacy rows with the
                # aggregated row(s) so all samples are represented.
                legacy_df = _read_seqkit_tsvs(tsv_files)
                if not legacy_df.empty:
                    return pd.concat(
                        [legacy_df, incremental_df], ignore_index=True
                    )
            return incremental_df

    if not tsv_files:
        logging.debug("No seqkit TSV files found")
        return pd.DataFrame()

    return _read_seqkit_tsvs(tsv_files)


def _read_seqkit_tsvs(tsv_files: List[str]) -> pd.DataFrame:
    """Read and concatenate flat seqkit TSV files."""
    all_stats = []
    for tsv_file in tsv_files:
        try:
            df = pd.read_csv(tsv_file, sep='\t')
            # Add sample column from filename
            sample_name = os.path.basename(tsv_file).replace('.tsv', '')
            df['sample'] = sample_name
            all_stats.append(df)
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.warning(f"Cannot read seqkit file {tsv_file}: {e}")
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
            logging.warning(f"Malformed seqkit file {tsv_file}: {e}")
            continue

    if not all_stats:
        return pd.DataFrame()

    return pd.concat(all_stats, ignore_index=True)


def _load_seqkit_incremental(
    seqkit_dir: str, sample: Optional[str] = None
) -> pd.DataFrame:
    """
    Aggregate per-batch seqkit TSVs into a single cumulative row per sample.

    The aggregation logic mirrors the SEQKIT_MERGE_STATS module in the
    nanometanf pipeline (modules/local/seqkit_merge_stats/main.nf):

    * ``num_seqs``, ``sum_len``, ``sum_gap``, ``sum_n`` are summed.
    * ``min_len`` is the minimum across batches that actually contributed
      reads (empty batches reporting ``min_len = 0`` are ignored).
    * ``max_len`` is the maximum across batches.
    * ``avg_len`` is recomputed as ``sum_len / num_seqs``.
    * ``Q20(%)``, ``Q30(%)``, ``AvgQual`` and ``GC(%)`` are recomputed as
      per-base weighted averages (weighted by ``sum_len``).
    * ``Q1``, ``Q2``, ``Q3``, ``N50`` and ``N50_num`` are approximated
      from the cumulative average length, since the raw read-length
      distribution is not preserved in cumulative stats.

    Args:
        seqkit_dir: Path to the ``seqkit/`` output directory.
        sample: Optional sample to restrict aggregation to.

    Returns:
        DataFrame with one row per sample. Empty when no batch files
        could be read.
    """
    if sample is not None and sample != "All Samples":
        sample_dirs = [sample]
    else:
        try:
            sample_dirs = [
                entry for entry in os.listdir(seqkit_dir)
                if os.path.isdir(os.path.join(seqkit_dir, entry))
            ]
        except OSError:
            return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for sample_name in sample_dirs:
        batch_stats_dir = os.path.join(
            seqkit_dir, sample_name, "batch_stats"
        )
        if not os.path.isdir(batch_stats_dir):
            continue
        batch_files = sorted(glob.glob(os.path.join(batch_stats_dir, "*.tsv")))
        if not batch_files:
            continue

        per_batch: List[pd.DataFrame] = []
        for batch_file in batch_files:
            try:
                if not _is_file_stable(batch_file):
                    logging.debug(f"Skipping unstable seqkit batch: {batch_file}")
                    continue
                df = pd.read_csv(batch_file, sep='\t')
            except (FileNotFoundError, PermissionError, OSError) as exc:
                logging.warning(
                    f"Cannot read seqkit batch file {batch_file}: {exc}"
                )
                continue
            except (
                pd.errors.ParserError,
                pd.errors.EmptyDataError,
                UnicodeDecodeError,
            ) as exc:
                logging.warning(
                    f"Malformed seqkit batch file {batch_file}: {exc}"
                )
                continue
            if df.empty:
                continue
            per_batch.append(df)

        if not per_batch:
            continue

        aggregated = _aggregate_seqkit_batches(per_batch, sample_name)
        if aggregated is not None:
            rows.append(aggregated)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def _aggregate_seqkit_batches(
    per_batch: List[pd.DataFrame], sample_name: str
) -> Optional[Dict[str, Any]]:
    """Sum a list of single-row seqkit batch frames into a cumulative row.

    Mirrors the per-base weighted aggregation used by the upstream
    SEQKIT_MERGE_STATS module so the GUI's view of an interrupted
    realtime run matches a completed one.
    """
    total_num_seqs = 0
    total_sum_len = 0
    total_sum_gap = 0
    total_sum_n = 0
    contributing_min_lens: List[int] = []
    max_len = 0
    weighted_q20 = 0.0
    weighted_q30 = 0.0
    weighted_avgqual = 0.0
    weighted_gc = 0.0

    file_label = ""
    fmt_label = ""
    type_label = ""

    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0

    def _safe_float(value: Any) -> float:
        try:
            return float(str(value).replace('%', ''))
        except (ValueError, TypeError):
            return 0.0

    for df in per_batch:
        row = df.iloc[0]
        num_seqs = _safe_int(row.get('num_seqs', 0))
        sum_len = _safe_int(row.get('sum_len', 0))
        sum_gap = _safe_int(row.get('sum_gap', 0))
        sum_n = _safe_int(row.get('sum_n', 0))
        this_min = _safe_int(row.get('min_len', 0))
        this_max = _safe_int(row.get('max_len', 0))

        total_num_seqs += num_seqs
        total_sum_len += sum_len
        total_sum_gap += sum_gap
        total_sum_n += sum_n

        # Empty batches (num_seqs == 0) report min_len = 0; skip them so
        # the cumulative min_len reflects only batches that contributed
        # reads, matching the upstream merge module.
        if num_seqs > 0:
            contributing_min_lens.append(this_min)
            max_len = max(max_len, this_max)

        weighted_q20 += _safe_float(row.get('Q20(%)', 0)) * sum_len
        weighted_q30 += _safe_float(row.get('Q30(%)', 0)) * sum_len
        weighted_avgqual += _safe_float(row.get('AvgQual', 0)) * sum_len
        weighted_gc += _safe_float(row.get('GC(%)', 0)) * sum_len

        if not file_label:
            file_label = str(row.get('file', f"{sample_name}.fastq.gz"))
            fmt_label = str(row.get('format', 'FASTQ'))
            type_label = str(row.get('type', 'DNA'))

    if total_num_seqs == 0:
        return None

    avg_len = total_sum_len / total_num_seqs if total_num_seqs > 0 else 0.0
    final_q20 = weighted_q20 / total_sum_len if total_sum_len > 0 else 0.0
    final_q30 = weighted_q30 / total_sum_len if total_sum_len > 0 else 0.0
    final_avgqual = (
        weighted_avgqual / total_sum_len if total_sum_len > 0 else 0.0
    )
    final_gc = weighted_gc / total_sum_len if total_sum_len > 0 else 0.0

    min_len = min(contributing_min_lens) if contributing_min_lens else 0

    return {
        'file': file_label,
        'format': fmt_label,
        'type': type_label,
        'num_seqs': total_num_seqs,
        'sum_len': total_sum_len,
        'min_len': min_len,
        'avg_len': round(avg_len, 1),
        'max_len': max_len,
        'Q1': round(avg_len * 0.75, 1),
        'Q2': round(avg_len, 1),
        'Q3': round(avg_len * 1.5, 1),
        'sum_gap': total_sum_gap,
        'N50': int(avg_len),
        'N50_num': total_num_seqs // 2,
        'Q20(%)': round(final_q20, 2),
        'Q30(%)': round(final_q30, 2),
        'AvgQual': round(final_avgqual, 2),
        'GC(%)': round(final_gc, 2),
        'sum_n': total_sum_n,
        'sample': sample_name,
    }


def _kraken_classification_counts(kraken_df: pd.DataFrame) -> tuple:
    """Return (classified, unclassified, total) derived from a Kraken2 report.

    Uses the root and unclassified rows' ``cumul_reads`` values, matching the
    Stage Strip's ``get_classification_stats`` logic so every QC surface
    reports the same read total for the same report.
    """
    if kraken_df is None or kraken_df.empty or 'name' not in kraken_df.columns:
        return 0, 0, 0

    names = kraken_df['name'].astype(str).str.strip()
    root_mask = names == 'root'
    unclass_mask = names == 'unclassified'

    classified = (
        int(kraken_df.loc[root_mask, 'cumul_reads'].iloc[0])
        if root_mask.any() else 0
    )
    unclassified = (
        int(kraken_df.loc[unclass_mask, 'cumul_reads'].iloc[0])
        if unclass_mask.any() else 0
    )
    return classified, unclassified, classified + unclassified


def get_sample_statistics_summary(main_dir: str) -> pd.DataFrame:
    """
    Get summary statistics for all samples (for per-barcode breakdown table).

    Supports both FASTP (when using fastp QC tool) and NanoPlot/Kraken2
    fallback (when using chopper QC tool).

    Every Kraken2-derived count is reported on two time horizons:

    - ``*_cumul``  : cumulative since run start (matches Stage Strip, Dashboard,
      Organism tab). Sourced from the cumulative report when present, else
      the standard per-sample report, else the highest-numbered batch.
    - ``*_latest`` : latest batch only. Sourced from the highest-numbered
      ``*_batch*`` report; falls back to the cumulative value when no batch
      files exist (e.g. completed batch-mode runs).

    Returns:
        DataFrame with columns:
            sample, base_pairs, pass_rate, mean_quality, n50, status,
            reads_cumul, classified_cumul, unclassified_cumul,
            classified_rate_cumul, classified_rate_cumul_num,
            reads_latest, classified_latest, unclassified_latest,
            classified_rate_latest, classified_rate_latest_num,
            reads_delta,
            reads, classified, unclassified, classified_rate,
            classified_rate_num, unclassified_rate   # legacy aliases (cumulative)
    """
    # Import here to avoid circular imports (classification_loaders uses loader_utils too)
    from nanometa_live.core.utils.classification_loaders import (
        load_kraken_data,
        load_kraken_latest_batch,
    )

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
            nanoplot_stats = load_nanoplot_stats(main_dir, sample)
            if nanoplot_stats.get('number_of_reads', 0) == 0:
                nanoplot_stats = load_nanoplot_stats(main_dir, None)

            if nanoplot_stats.get('number_of_reads', 0) > 0:
                total_reads = nanoplot_stats['number_of_reads']
                total_bases = nanoplot_stats.get('total_bases', 0)
                mean_quality = nanoplot_stats.get('mean_read_quality', 0)
                n50 = nanoplot_stats.get('read_length_n50', 0)

        # --- Cumulative horizon (matches Stage Strip / Dashboard / Organism) ---
        cumul_df = load_kraken_data(main_dir, sample)
        classified_cumul, unclassified_cumul, kraken_total_cumul = (
            _kraken_classification_counts(cumul_df)
        )

        classified_rate_cumul = (
            round((classified_cumul / kraken_total_cumul * 100), 1)
            if kraken_total_cumul > 0 else 0
        )
        unclassified_rate_cumul = (
            round((unclassified_cumul / kraken_total_cumul * 100), 1)
            if kraken_total_cumul > 0 else 0
        )

        # If FASTP/NanoPlot did not supply a filtered count, use the Kraken2
        # cumulative total (= reads that passed the quality filter, since the
        # filter feeds Kraken2 in the pipeline order).
        if total_reads == 0:
            total_reads = kraken_total_cumul

        # --- Latest-batch horizon ---
        latest_df = load_kraken_latest_batch(main_dir, sample)
        classified_latest, unclassified_latest, kraken_total_latest = (
            _kraken_classification_counts(latest_df)
        )

        # If no batch files exist, latest collapses to cumulative (batch-mode
        # runs, or runs that have only emitted a single consolidated report).
        if kraken_total_latest == 0 and kraken_total_cumul > 0:
            classified_latest = classified_cumul
            unclassified_latest = unclassified_cumul
            kraken_total_latest = kraken_total_cumul

        classified_rate_latest = (
            round((classified_latest / kraken_total_latest * 100), 1)
            if kraken_total_latest > 0 else 0
        )

        # Delta = reads added since the previous batch. When latest == cumulative
        # (no batch files, or only one batch exists) the delta equals the
        # latest-batch total — operators see the full run as a single batch.
        reads_delta = kraken_total_latest

        # Status follows the cumulative classification rate.
        if total_reads == 0:
            status = "\u25cb No Data"
        elif classified_rate_cumul >= 70:
            status = "\u2713 Complete"
        elif classified_rate_cumul >= 50:
            status = "\u26a0 Review"
        else:
            status = "\u2717 Issue"

        pass_rate_display = pass_rate if pass_rate is not None else "N/A"

        summary_data.append({
            'sample': sample,
            'base_pairs': total_bases,
            'pass_rate': pass_rate_display,
            'mean_quality': round(mean_quality, 1) if mean_quality > 0 else "N/A",
            'n50': n50 if n50 > 0 else "N/A",
            'status': status,

            # Cumulative horizon (since run start)
            'reads_cumul': kraken_total_cumul if kraken_total_cumul > 0 else total_reads,
            'classified_cumul': classified_cumul,
            'unclassified_cumul': unclassified_cumul,
            'classified_rate_cumul': f"{classified_rate_cumul}%",
            'classified_rate_cumul_num': classified_rate_cumul,

            # Latest batch horizon
            'reads_latest': kraken_total_latest,
            'classified_latest': classified_latest,
            'unclassified_latest': unclassified_latest,
            'classified_rate_latest': (
                f"{classified_rate_latest}%" if kraken_total_latest > 0 else "N/A"
            ),
            'classified_rate_latest_num': classified_rate_latest,
            'reads_delta': reads_delta,

            # Legacy aliases (cumulative) — kept so downstream consumers that
            # still reference the flat schema (CSV exports, older tests) keep
            # working without a breaking change.
            'reads': kraken_total_cumul if kraken_total_cumul > 0 else total_reads,
            'classified': classified_cumul,
            'unclassified': unclassified_cumul,
            'classified_rate': f"{classified_rate_cumul}%",
            'classified_rate_num': classified_rate_cumul,
            'unclassified_rate': unclassified_rate_cumul,
        })

    return pd.DataFrame(summary_data)


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
    # Try canonical format first (waterfall pattern)
    if sample is not None and sample != "All Samples":
        canonical = load_canonical_qc_stats(main_dir, sample)
        if canonical is not None:
            logging.debug("Using canonical QC stats via get_qc_stats for %s", sample)
            return {
                'source': 'canonical',
                'total_reads': canonical.get('total_reads_after', 0),
                'total_bases': canonical.get('total_bases_after', 0),
                'reads_before_filter': canonical.get('total_reads_before', 0),
                'pass_rate': (canonical['total_reads_after'] /
                             canonical['total_reads_before'] * 100
                             if canonical.get('total_reads_before', 0) > 0 else 0),
                'low_quality': canonical.get('low_quality', 0),
                'too_short': canonical.get('too_short', 0),
                **canonical,
            }

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
