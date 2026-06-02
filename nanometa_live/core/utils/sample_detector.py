"""
Sample detection utilities for Nanometa Live v2.0.

This module provides functions to automatically detect available samples
from nanometanf output files, supporting both barcoded and non-barcoded runs.

Includes mtime-based caching for get_available_samples() to reduce filesystem
overhead from repeated glob scans on each polling interval.
"""

import os
import glob
import logging
import threading
from typing import List, Dict, Optional, Set, Tuple

from nanometa_live.core.utils.canonical_loaders import load_manifest

# Module-level cache for sample detection.
# Stores (dir_mtimes_fingerprint, cached_sample_list) keyed by main_dir.
_sample_cache_lock = threading.Lock()
_sample_cache: Dict[str, Tuple[Tuple[Tuple[str, float], ...], List[str]]] = {}

# Output subdirectories whose mtime we monitor for cache invalidation.
_WATCHED_SUBDIRS = ("kraken2", "fastp", "seqkit", "nanoplot", "validation")


def _get_dir_mtimes(main_dir: str) -> Tuple[Tuple[str, float], ...]:
    """Return a hashable fingerprint of top-level output directory mtimes."""
    mtimes = []
    for subdir in _WATCHED_SUBDIRS:
        path = os.path.join(main_dir, subdir)
        try:
            st = os.stat(path)
            mtimes.append((subdir, st.st_mtime))
        except OSError:
            mtimes.append((subdir, 0.0))
    return tuple(mtimes)


def invalidate_sample_cache():
    """Clear the sample detection cache (e.g. after data changes)."""
    with _sample_cache_lock:
        _sample_cache.clear()


def resolve_analysis_directory(main_dir: str) -> str:
    """
    Resolve the actual analysis directory from a base directory.

    If main_dir contains analysis output directly (e.g., kraken2/ folder),
    return it as-is. If main_dir is a base directory containing analysis
    subdirectories (e.g., analysis_20251210_164228/), return the most recent one.

    Args:
        main_dir: Path to main directory (may be base or analysis directory)

    Returns:
        Path to directory containing actual analysis output
    """
    if not main_dir or not os.path.exists(main_dir):
        return main_dir

    # Check if this directory already has analysis output
    kraken_dir = os.path.join(main_dir, "kraken2")
    if os.path.exists(kraken_dir):
        return main_dir

    # Check for analysis subdirectories (named analysis_YYYYMMDD_HHMMSS)
    analysis_pattern = os.path.join(main_dir, "analysis_*")
    analysis_dirs = glob.glob(analysis_pattern)

    if not analysis_dirs:
        return main_dir

    # Sort by modification time to get the most recent
    analysis_dirs_sorted = sorted(
        analysis_dirs,
        key=lambda x: os.path.getmtime(x),
        reverse=True
    )

    # Check if the most recent has actual output with report files
    for analysis_dir in analysis_dirs_sorted:
        if os.path.isdir(analysis_dir):
            kraken_check = os.path.join(analysis_dir, "kraken2")
            if os.path.exists(kraken_check):
                # Verify there are actual report files, not just an empty directory
                report_patterns = [
                    os.path.join(kraken_check, "*.kraken2.report.txt"),
                ]
                has_reports = any(
                    glob.glob(pattern) for pattern in report_patterns
                )
                if has_reports:
                    logging.info(f"Resolved analysis directory: {analysis_dir}")
                    return analysis_dir
                else:
                    logging.debug(f"Skipping {analysis_dir} - kraken2 dir exists but no report files")

    # Return most recent even if no kraken2 output yet
    if analysis_dirs_sorted:
        most_recent = analysis_dirs_sorted[0]
        if os.path.isdir(most_recent):
            logging.info(f"Using most recent analysis directory: {most_recent}")
            return most_recent

    return main_dir


def extract_sample_name(filename: str) -> str:
    """
    Extract sample name from nanometanf output filename.

    Strips file extensions and batch suffixes to group multiple batches
    of the same sample together for visualization.

    Args:
        filename: Name of the file (e.g., "barcode01_batch0.kraken2.report.txt")

    Returns:
        Sample name without extensions and batch suffix (e.g., "barcode01")

    Examples:
        >>> extract_sample_name("barcode01.kraken2.report.txt")
        'barcode01'
        >>> extract_sample_name("barcode01_batch0.kraken2.report.txt")
        'barcode01'
        >>> extract_sample_name("sample_A.fastp.json")
        'sample_A'
        >>> extract_sample_name("unclassified_batch2.kraken2.txt")
        'unclassified'
    """
    import re

    # Get basename without directory
    base = os.path.basename(filename)

    # Remove common nanometanf file extensions
    # Order matters - longer extensions must come first
    extensions_to_remove = [
        '.cumulative.kraken2.report.txt',  # Incremental mode cumulative reports (must be first)
        '.kraken2.report.txt',  # nanometanf v1.2+
        '.kraken2.txt',
        '.fastp.json',
        '.txt',
        '.json'
    ]

    for ext in extensions_to_remove:
        if base.endswith(ext):
            base = base[:-len(ext)]
            break

    # Strip batch suffix (e.g., _batch0, _batch1, _batch2, etc.)
    # This groups multiple batches of the same sample together
    base = re.sub(r'[._]batch_?\d+$', '', base)

    return base


def detect_samples_from_kraken(kraken_dir: str) -> Set[str]:
    """
    Detect available samples from Kraken2 output directory.

    Supports both flat (v1.2+) and nested per-sample subdirectory (v1.5)
    output structures:
    - Flat: ``kraken2/{sample_id}.cumulative.kraken2.report.txt``
    - Nested: ``kraken2/{sample_id}/batch_reports/{sample_id}_batch0.kraken2.report.txt``

    Args:
        kraken_dir: Path to kraken2 output directory

    Returns:
        Set of sample names found
    """
    samples = set()

    if not os.path.exists(kraken_dir):
        logging.debug(f"Kraken2 directory not found: {kraken_dir}")
        return samples

    # Find Kraken2 report files at the TOP level only.
    # Files inside per-sample subdirectories (v1.5 nested structure) are
    # handled separately below -- we use the directory name as the sample,
    # not the batch filename (which would produce spurious "batch_0" etc.).
    kreport_patterns = [
        os.path.join(kraken_dir, "*.cumulative.kraken2.report.txt"),  # Incremental mode cumulative
        os.path.join(kraken_dir, "*.kraken2.report.txt"),  # nanometanf v1.2+
    ]
    kreport_files = []
    for pattern in kreport_patterns:
        kreport_files.extend(glob.glob(pattern))

    for file_path in kreport_files:
        sample_name = extract_sample_name(file_path)
        samples.add(sample_name)
        logging.debug(f"Detected sample from Kraken2: {sample_name}")

    # v1.5 nested structure: detect sample subdirectories that contain a
    # batch_reports/ or batches/ folder, in case no top-level cumulative
    # report has been written yet (early in a run).
    try:
        kraken_entries = os.listdir(kraken_dir)
    except OSError:
        logging.debug("Cannot list kraken2 directory (may have been removed): %s", kraken_dir)
        return samples
    for item in kraken_entries:
        item_path = os.path.join(kraken_dir, item)
        if not os.path.isdir(item_path):
            continue
        has_batch_subdir = (
            os.path.isdir(os.path.join(item_path, "batch_reports"))
            or os.path.isdir(os.path.join(item_path, "batches"))
        )
        if has_batch_subdir and item not in samples:
            samples.add(item)
            logging.debug(f"Detected sample from Kraken2 v1.5 subdirectory: {item}")

    return samples


def detect_samples_from_fastp(fastp_dir: str) -> Set[str]:
    """
    Detect available samples from FASTP output directory.

    Args:
        fastp_dir: Path to fastp output directory

    Returns:
        Set of sample names found
    """
    samples = set()

    if not os.path.exists(fastp_dir):
        logging.debug(f"FASTP directory not found: {fastp_dir}")
        return samples

    # Find all fastp JSON files
    fastp_files = glob.glob(os.path.join(fastp_dir, "*.fastp.json"))

    for file_path in fastp_files:
        sample_name = extract_sample_name(file_path)
        samples.add(sample_name)
        logging.debug(f"Detected sample from FASTP: {sample_name}")

    return samples


def detect_samples_from_blast(blast_dir: str) -> Set[str]:
    """
    Detect available samples from BLAST output directory.

    Args:
        blast_dir: Path to blast output directory

    Returns:
        Set of sample names found
    """
    samples = set()

    if not os.path.exists(blast_dir):
        logging.debug(f"BLAST directory not found: {blast_dir}")
        return samples

    # BLAST files may have format: sample_taxid.txt or sample.txt
    blast_files = glob.glob(os.path.join(blast_dir, "*.txt"))

    for file_path in blast_files:
        filename = os.path.basename(file_path)
        # Remove .txt extension
        base = filename.replace('.txt', '')

        # If format is sample_taxid, extract just sample part
        if '_' in base:
            sample_name = base.rsplit('_', 1)[0]
        else:
            sample_name = base

        samples.add(sample_name)
        logging.debug(f"Detected sample from BLAST: {sample_name}")

    return samples


def detect_samples_from_seqkit(seqkit_dir: str) -> Set[str]:
    """
    Detect available samples from seqkit output directory.

    Used when QC tool is chopper (nanometanf default).

    Args:
        seqkit_dir: Path to seqkit output directory

    Returns:
        Set of sample names found
    """
    samples = set()

    if not os.path.exists(seqkit_dir):
        logging.debug(f"Seqkit directory not found: {seqkit_dir}")
        return samples

    # Find all seqkit TSV files
    tsv_files = glob.glob(os.path.join(seqkit_dir, "*.tsv"))

    for file_path in tsv_files:
        filename = os.path.basename(file_path)
        # Remove .tsv extension
        sample_name = filename.replace('.tsv', '')
        # Strip any batch suffixes
        import re
        sample_name = re.sub(r'_batch\d+$', '', sample_name)
        samples.add(sample_name)
        logging.debug(f"Detected sample from seqkit: {sample_name}")

    return samples


def detect_samples_from_nanoplot(nanoplot_dir: str) -> Set[str]:
    """
    Detect available samples from NanoPlot output directory.

    NanoPlot typically organizes output in sample subdirectories.

    Args:
        nanoplot_dir: Path to nanoplot output directory

    Returns:
        Set of sample names found
    """
    samples = set()

    if not os.path.exists(nanoplot_dir):
        logging.debug(f"NanoPlot directory not found: {nanoplot_dir}")
        return samples

    # NanoPlot usually creates subdirectories per sample
    try:
        nanoplot_entries = os.listdir(nanoplot_dir)
    except OSError:
        logging.debug("Cannot list NanoPlot directory (may have been removed): %s", nanoplot_dir)
        return samples
    for item in nanoplot_entries:
        item_path = os.path.join(nanoplot_dir, item)
        if os.path.isdir(item_path):
            # Check if it contains NanoStats.txt
            nanostats_path = os.path.join(item_path, "NanoStats.txt")
            if os.path.exists(nanostats_path):
                samples.add(item)
                logging.debug(f"Detected sample from NanoPlot: {item}")

    return samples


def get_available_samples(main_dir: str) -> List[str]:
    """
    Get unified list of available samples from nanometanf output.

    Scans multiple output directories (kraken2, fastp, blast) and returns
    a sorted list of all detected samples, with "All Samples" as the first option.

    Args:
        main_dir: Main nanometanf output directory

    Returns:
        Sorted list of sample names, starting with "All Samples"

    Example:
        >>> samples = get_available_samples("/path/to/results")
        >>> print(samples)
        ['All Samples', 'barcode01', 'barcode02', 'unclassified']
    """
    # Auto-resolve to analysis directory if needed
    main_dir = resolve_analysis_directory(main_dir)

    # Try manifest-based detection first (canonical format)
    manifest = load_manifest(main_dir)
    if manifest is not None:
        manifest_samples = manifest.get("samples", [])
        if manifest_samples:
            logging.debug(
                "Using manifest-based sample detection: %d samples",
                len(manifest_samples),
            )
            return ["All Samples"] + sorted(manifest_samples)

    # Mtime-based cache: check whether any watched output directory has
    # changed since the last scan.  This reduces ~384 globs to ~5
    # os.stat() calls on cache hits.
    current_mtimes = _get_dir_mtimes(main_dir)
    with _sample_cache_lock:
        cached = _sample_cache.get(main_dir)
        if cached is not None:
            stored_mtimes, stored_result = cached
            if stored_mtimes == current_mtimes:
                logging.debug("Sample detection cache hit for %s", main_dir)
                return stored_result

    all_samples: Set[str] = set()

    # Detect from Kraken2 output
    kraken_dir = os.path.join(main_dir, "kraken2")
    all_samples.update(detect_samples_from_kraken(kraken_dir))

    # Detect from FASTP output
    fastp_dir = os.path.join(main_dir, "fastp")
    all_samples.update(detect_samples_from_fastp(fastp_dir))

    # Detect from seqkit output (used with chopper QC tool)
    seqkit_dir = os.path.join(main_dir, "seqkit")
    all_samples.update(detect_samples_from_seqkit(seqkit_dir))

    # Detect from NanoPlot output
    nanoplot_dir = os.path.join(main_dir, "nanoplot")
    all_samples.update(detect_samples_from_nanoplot(nanoplot_dir))

    # Detect from BLAST output (nanometanf v1.1+ publishes to validation/blast/)
    blast_dir = os.path.join(main_dir, "validation", "blast")
    if not os.path.exists(blast_dir):
        blast_dir = os.path.join(main_dir, "blast")
    all_samples.update(detect_samples_from_blast(blast_dir))

    # Sort samples alphabetically
    sorted_samples = sorted(list(all_samples))

    # Always add "All Samples" as the first option
    result = ["All Samples"] + sorted_samples

    # Store in mtime cache
    with _sample_cache_lock:
        _sample_cache[main_dir] = (current_mtimes, result)

    return result


def get_sample_file_mapping(main_dir: str) -> Dict[str, Dict[str, List[str]]]:
    """
    Create a mapping of samples to their output file paths.

    Finds all batch files for each sample and returns them as lists,
    allowing data loaders to combine multiple batches.

    Args:
        main_dir: Main nanometanf output directory

    Returns:
        Dictionary mapping sample names to lists of file paths:
        {
            'barcode01': {
                'kraken2': ['/path/kraken2/barcode01_batch0.kraken2.report.txt',
                           '/path/kraken2/barcode01_batch1.kraken2.report.txt'],
                'fastp': ['/path/fastp/barcode01_batch0.fastp.json',
                         '/path/fastp/barcode01_batch1.fastp.json'],
                'blast': ['/path/blast/barcode01_*.blast.tsv']
            },
            ...
        }
    """
    mapping = {}

    # Get all samples
    samples = get_available_samples(main_dir)

    # Skip "All Samples" virtual sample
    for sample in samples:
        if sample == "All Samples":
            continue

        sample_files = {}

        # Kraken2 files (may be multiple batches)
        kraken_dir = os.path.join(main_dir, "kraken2")
        # Match nanometanf report naming, with and without batch suffix
        kraken_patterns = [
            os.path.join(kraken_dir, f"{sample}.kraken2.report.txt"),    # nanometanf v1.2+
            os.path.join(kraken_dir, f"{sample}_*.kraken2.report.txt"),  # nanometanf batches
        ]
        kraken_files = []
        for pattern in kraken_patterns:
            kraken_files.extend(glob.glob(pattern))
        if kraken_files:
            sample_files['kraken2'] = sorted(kraken_files)

        # FASTP files (may be multiple batches)
        fastp_dir = os.path.join(main_dir, "fastp")
        # Match both with and without batch suffix
        fastp_patterns = [
            os.path.join(fastp_dir, f"{sample}.fastp.json"),
            os.path.join(fastp_dir, f"{sample}_*.fastp.json")
        ]
        fastp_files = []
        for pattern in fastp_patterns:
            fastp_files.extend(glob.glob(pattern))
        if fastp_files:
            sample_files['fastp'] = sorted(fastp_files)

        # BLAST files (nanometanf v1.1+ publishes to validation/blast/)
        blast_dir = os.path.join(main_dir, "validation", "blast")
        if not os.path.exists(blast_dir):
            blast_dir = os.path.join(main_dir, "blast")
        blast_files = glob.glob(os.path.join(blast_dir, f"{sample}_*.txt"))
        if blast_files:
            sample_files['blast'] = sorted(blast_files)

        if sample_files:
            mapping[sample] = sample_files

    return mapping


def is_barcoded_run(main_dir: str) -> bool:
    """
    Determine if the run is barcoded based on sample names.

    A run is considered barcoded if any sample name starts with "barcode".

    Args:
        main_dir: Main nanometanf output directory

    Returns:
        True if barcoded run detected, False otherwise
    """
    samples = get_available_samples(main_dir)

    # Check if any sample starts with "barcode"
    for sample in samples:
        if sample.lower().startswith("barcode"):
            logging.info(f"Barcoded run detected (found sample: {sample})")
            return True

    return False


def get_sample_count(main_dir: str) -> int:
    """
    Get the number of samples detected (excluding "All Samples").

    Args:
        main_dir: Main nanometanf output directory

    Returns:
        Number of samples
    """
    samples = get_available_samples(main_dir)
    # Subtract 1 to exclude "All Samples"
    return len(samples) - 1 if len(samples) > 0 else 0
