"""
Auto-detection utilities for Nanometa Live.

This module provides automatic detection of configuration settings based on
file structure and database characteristics, reducing manual configuration.

Features:
- Sample handling mode detection (by_barcode, single_sample, per_file)
- Kraken2 database taxonomy detection (GTDB vs NCBI)
- Optimal update interval estimation
"""

import re
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

logger = logging.getLogger(__name__)


# Conventional Oxford Nanopore demultiplexer naming. The historic
# "barcode01", "barcode02", ... pattern that ONT software emits.
# Subdirectories matching this regex are always treated as sample
# folders even if (transiently) empty. Other layouts (Turex/, Zymo/,
# operator-named pools) qualify as sample folders only when they
# directly contain FASTQ files.
_BARCODE_NAME_RE = re.compile(r"^barcode\d{2,}$", re.IGNORECASE)


def is_barcode_named(name: str) -> bool:
    """True iff *name* matches the conventional 'barcode<NN>' pattern."""
    return bool(_BARCODE_NAME_RE.match(name))


def find_sample_subdirs(input_directory: str) -> List[Path]:
    """Return FASTQ-bearing per-sample subdirectories of *input_directory*.

    "by_barcode" sample handling is really "subdirectory-per-sample".
    Conventional ONT output uses ``barcode01``, ``barcode02``, ... but
    operators routinely point Nanometa Live at custom layouts (e.g.
    ``Turex/``, ``Zymo/``, mock-community pools) where each subdirectory
    is one sample under a non-conventional name. This helper returns
    every direct subdirectory that qualifies as a sample folder:

    - Any subdir whose basename matches ``barcode<NN>`` (always
      included so an empty barcode directory awaiting reads still
      shows up).
    - Plus any other direct subdirectory containing at least one
      ``*.fastq*`` or ``*.fq*`` file.

    The special ``unclassified/`` directory is included whenever it
    contains FASTQ files. Hidden directories (``.``-prefixed) are
    excluded.

    Single source of truth used by:
    - the Configuration tab "Apply Settings" validation
    - parameter_mapping samplesheet generation for ``by_barcode``
    - parameter_mapping launch validation
    - readiness_checker input-directory check
    - backend_manager file-count display

    Returns the matching paths sorted by basename. Returns ``[]`` when
    *input_directory* is missing, not a directory, or unreadable.
    """
    p = Path(input_directory).expanduser()
    if not p.is_dir():
        return []
    try:
        candidates = [d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]
    except OSError:
        return []

    selected: List[Path] = []
    for d in candidates:
        if is_barcode_named(d.name):
            selected.append(d)
            continue
        try:
            has_fastq = any(
                True for pattern in ("*.fastq*", "*.fq*") for _ in d.glob(pattern)
            )
        except OSError:
            has_fastq = False
        if has_fastq:
            selected.append(d)

    return sorted(selected, key=lambda d: d.name)


def detect_sample_handling(input_directory: str) -> Tuple[str, str]:
    """
    Auto-detect the appropriate sample handling mode based on directory structure.

    Detection logic:
    - If barcode subdirectories exist (barcode01, barcode02, etc.) -> by_barcode
    - If files are in flat directory with varied names -> per_file
    - If files are in flat directory with similar names -> single_sample

    Args:
        input_directory: Path to the nanopore output directory

    Returns:
        Tuple of (sample_handling_mode, explanation)
    """
    input_path = Path(input_directory).expanduser()

    if not input_path.exists():
        return "by_barcode", "Directory not found, using default"

    if not input_path.is_dir():
        return "by_barcode", "Path is not a directory, using default"

    # Check for per-sample subdirectories (conventional barcode<NN>
    # AND custom-named subdirs that directly hold FASTQ files).
    # Filter to only those that actually contain FASTQs so empty
    # placeholder barcode dirs do not override flat root FASTQs.
    sample_subdirs = [
        d for d in find_sample_subdirs(str(input_path))
        if any(d.glob("*.fastq*")) or any(d.glob("*.fq*"))
    ]
    if sample_subdirs:
        # Distinguish the conventional case for nicer messaging.
        conventional = [d for d in sample_subdirs if is_barcode_named(d.name)]
        if conventional and len(conventional) == len(sample_subdirs):
            return (
                "by_barcode",
                f"Found {len(conventional)} barcode directories with FASTQ files",
            )
        return (
            "by_barcode",
            f"Found {len(sample_subdirs)} per-sample subdirectories with "
            f"FASTQ files ({', '.join(d.name for d in sample_subdirs[:3])}"
            + (", ..." if len(sample_subdirs) > 3 else "")
            + ")",
        )

    # Check for FASTQ files in the root directory
    root_fastq_files = list(input_path.glob("*.fastq*")) + list(input_path.glob("*.fq*"))

    if not root_fastq_files:
        # No root-level FASTQs and no qualifying per-sample subdirs
        # (find_sample_subdirs already returned empty above). Fall
        # back to the default with an explanation.
        return "by_barcode", "No FASTQ files found, using default"

    # Analyze filename patterns to distinguish single_sample vs per_file
    file_basenames = []
    for f in root_fastq_files:
        # Remove common suffixes
        basename = f.name
        for suffix in [".fastq.gz", ".fastq", ".fq.gz", ".fq"]:
            if basename.endswith(suffix):
                basename = basename[:-len(suffix)]
                break
        file_basenames.append(basename)

    # Check for common patterns indicating per_file mode
    # Look for distinct sample identifiers in filenames
    unique_prefixes = set()
    for name in file_basenames:
        # Extract potential sample ID (first part before underscore or number sequence)
        match = re.match(r'^([A-Za-z]+\d*)', name)
        if match:
            unique_prefixes.add(match.group(1).lower())

    if len(unique_prefixes) >= 2 and len(unique_prefixes) <= len(file_basenames) * 0.5:
        return "per_file", f"Found {len(root_fastq_files)} files with {len(unique_prefixes)} distinct sample identifiers"

    # Check if filenames follow a sequential pattern (like pass_0001.fastq, pass_0002.fastq)
    sequential_pattern = re.compile(r'(pass|fail|batch|reads?)_?\d+', re.IGNORECASE)
    sequential_count = sum(1 for name in file_basenames if sequential_pattern.search(name))

    if sequential_count > len(file_basenames) * 0.5:
        return "single_sample", f"Found {len(root_fastq_files)} files with sequential naming pattern"

    # Default based on file count
    if len(root_fastq_files) > 5:
        return "single_sample", f"Found {len(root_fastq_files)} FASTQ files, treating as single sample"
    else:
        return "per_file", f"Found {len(root_fastq_files)} FASTQ files, treating each as separate sample"


def detect_kraken_taxonomy(kraken_db_path: str) -> Tuple[str, str]:
    """
    Auto-detect whether a Kraken2 database uses GTDB or NCBI taxonomy.

    Detection methods:
    1. Check database name for hints (gtdb, ncbi)
    2. Examine taxo.k2d file header if accessible
    3. Sample species names from inspect output

    Args:
        kraken_db_path: Path to Kraken2 database directory

    Returns:
        Tuple of (taxonomy_type, explanation)
    """
    db_path = Path(kraken_db_path).expanduser()

    if not db_path.exists():
        return "gtdb", "Database not found, using default (GTDB)"

    # Check database name for hints
    db_name = db_path.name.lower()
    parent_name = db_path.parent.name.lower() if db_path.parent != db_path else ""

    if "gtdb" in db_name or "gtdb" in parent_name:
        return "gtdb", f"Database name contains 'gtdb': {db_path.name}"

    if "ncbi" in db_name or "refseq" in db_name or "ncbi" in parent_name:
        return "ncbi", f"Database name contains 'ncbi' or 'refseq': {db_path.name}"

    # Check for GTDB-specific markers
    # GTDB taxonomy uses prefixes like "d__", "p__", "c__", etc.
    # NCBI taxonomy uses different formatting

    # Try to read library/library_report.tsv if it exists
    library_report = db_path / "library" / "library_report.tsv"
    if library_report.exists():
        try:
            with open(library_report, 'r') as f:
                content = f.read(2000)  # Read first 2KB
                if "d__Bacteria" in content or "s__" in content:
                    return "gtdb", "GTDB taxonomy markers found in library report"
                elif "cellular organisms" in content or "Bacteria" in content:
                    return "ncbi", "NCBI taxonomy markers found in library report"
        except IOError:
            pass

    # Check for seqid2taxid.map
    seqid_map = db_path / "seqid2taxid.map"
    if seqid_map.exists():
        try:
            with open(seqid_map, 'r') as f:
                # Read first few lines
                lines = [f.readline() for _ in range(100)]
                # Check for GTDB accession patterns (GB_/RS_ prefixes)
                gtdb_count = sum(1 for line in lines if "GB_" in line or "RS_" in line)
                if gtdb_count > 50:
                    return "gtdb", f"GTDB accession patterns found in seqid2taxid.map"
        except IOError:
            pass

    # Check for inspect file that may have been generated
    inspect_files = list(db_path.parent.glob("*inspect*.txt"))
    for inspect_file in inspect_files:
        try:
            with open(inspect_file, 'r') as f:
                content = f.read(5000)
                # GTDB species names have underscore format: Escherichia_coli
                # and often have suffixes like _A, _B for reclassified species
                if re.search(r's__[A-Z][a-z]+_[a-z]+(_[A-Z])?', content):
                    return "gtdb", "GTDB species naming pattern found in inspect file"
                # Check for genus/species without underscore
                if re.search(r'Escherichia coli|Staphylococcus aureus', content):
                    return "ncbi", "NCBI species naming pattern found in inspect file"
        except IOError:
            pass

    # Default to GTDB (more common for modern databases)
    return "gtdb", "Could not determine taxonomy type, defaulting to GTDB"


def estimate_update_interval(
    input_directory: str,
    sample_interval_seconds: int = 60,
    min_interval: int = 10,
    max_interval: int = 300
) -> Tuple[int, str]:
    """
    Estimate optimal update interval based on file change frequency.

    Monitors the input directory for a short period to detect file change rate,
    then recommends an interval that balances responsiveness with CPU usage.

    Args:
        input_directory: Path to monitor
        sample_interval_seconds: How long to monitor for file changes
        min_interval: Minimum recommended interval
        max_interval: Maximum recommended interval

    Returns:
        Tuple of (recommended_interval, explanation)
    """
    input_path = Path(input_directory).expanduser()

    if not input_path.exists():
        return 30, "Directory not found, using default interval"

    # Count initial files
    def count_fastq_files() -> int:
        count = 0
        try:
            # Count in root
            count += len(list(input_path.glob("*.fastq*")))
            count += len(list(input_path.glob("*.fq*")))

            # Count in subdirectories
            for subdir in input_path.iterdir():
                if subdir.is_dir():
                    count += len(list(subdir.glob("*.fastq*")))
                    count += len(list(subdir.glob("*.fq*")))
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.exception(f"Error counting files: {e}")
        return count

    initial_count = count_fastq_files()

    # For batch mode (no active sequencing), use longer interval
    if initial_count == 0:
        return 60, "No files found, recommending longer interval"

    # Get modification times of existing files
    mod_times = []
    try:
        for f in input_path.rglob("*.fastq*"):
            mod_times.append(f.stat().st_mtime)
        for f in input_path.rglob("*.fq*"):
            mod_times.append(f.stat().st_mtime)
    except (FileNotFoundError, PermissionError, OSError):
        pass

    if not mod_times:
        return 30, "Could not analyze file modification times, using default"

    # Check if files were recently modified (active sequencing)
    now = time.time()
    recent_threshold = 5 * 60  # 5 minutes
    recent_files = sum(1 for t in mod_times if now - t < recent_threshold)

    if recent_files == 0:
        # Batch mode - files not recently modified
        return 60, f"Files not recently modified, batch mode recommended with 60s interval"

    # Real-time mode - calculate based on file frequency
    if len(mod_times) >= 2:
        mod_times.sort()
        # Calculate average interval between files
        intervals = [mod_times[i+1] - mod_times[i] for i in range(len(mod_times)-1)]
        avg_interval = sum(intervals) / len(intervals) if intervals else 30

        # Recommend update interval as 2-3x the file generation interval
        recommended = int(avg_interval * 2.5)
        recommended = max(min_interval, min(recommended, max_interval))

        return recommended, f"Based on file generation rate (~{avg_interval:.0f}s between files)"

    # Default for real-time mode
    return 30, f"Active sequencing detected ({recent_files} recent files), recommending 30s interval"


def get_barcode_list(input_directory: str) -> List[str]:
    """
    Get list of detected barcode directories.

    Args:
        input_directory: Path to nanopore output directory

    Returns:
        List of barcode directory names found
    """
    input_path = Path(input_directory).expanduser()

    if not input_path.exists():
        return []

    barcode_pattern = re.compile(r'^barcode\d{2,}$', re.IGNORECASE)
    barcodes = []

    for item in input_path.iterdir():
        if item.is_dir() and barcode_pattern.match(item.name):
            # Check if it contains FASTQ files
            fastq_files = list(item.glob("*.fastq*")) + list(item.glob("*.fq*"))
            if fastq_files:
                barcodes.append(item.name)

    return sorted(barcodes)


def detect_file_format(input_directory: str) -> Dict[str, Any]:
    """
    Detect the format of input files (FASTQ variants).

    Args:
        input_directory: Path to input directory

    Returns:
        Dictionary with format information
    """
    input_path = Path(input_directory).expanduser()

    result = {
        "primary_format": None,
        "formats_found": {},
        "total_files": 0,
        "compressed": False
    }

    if not input_path.exists():
        return result

    # Count files by extension
    extensions = {}
    try:
        for f in input_path.rglob("*"):
            if f.is_file():
                suffix = f.suffix.lower()
                if suffix == ".gz":
                    # Get the full extension for compressed files
                    stem = f.stem
                    if "." in stem:
                        inner_ext = Path(stem).suffix.lower()
                        suffix = inner_ext + suffix
                        result["compressed"] = True

                extensions[suffix] = extensions.get(suffix, 0) + 1
                result["total_files"] += 1
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.exception(f"Error scanning files: {e}")

    result["formats_found"] = extensions

    fastq_count = sum(extensions.get(ext, 0) for ext in [".fastq", ".fq", ".fastq.gz", ".fq.gz"])

    if fastq_count > 0:
        result["primary_format"] = "fastq"

    return result
