"""Sample read lengths from input FASTQ files.

Pre-flight support for the readiness checker: the QC length filter
(``chopper_minlength`` / ``filtlong_min_length``, default 1000 bp) silently
discards ALL reads of a short-amplicon run -- chopper exits 0 on total loss,
the pipeline completes green, and every dashboard panel is blank. Sampling a
few hundred reads from the input directory before launch is enough to tell
the operator that the filter is set above the data.

Sampling is bounded (a few files, a few hundred reads each) and cached on
``(path, mtime, size)`` so the readiness poll does not repeatedly re-read
the same gzip.
"""

import gzip
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MAX_FILES = 3
_MAX_READS_PER_FILE = 200

_FASTQ_PATTERNS = ("*.fastq", "*.fastq.gz", "*.fq", "*.fq.gz")

# (realpath, mtime_ns, size, max_reads) -> sampled lengths
_length_cache: Dict[tuple, List[int]] = {}


def _open_text(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", errors="replace")
    return open(path, "rt", errors="replace")


def sample_read_lengths(fastq_path, max_reads: int = _MAX_READS_PER_FILE) -> List[int]:
    """Return the lengths of up to ``max_reads`` reads from one FASTQ file.

    Failed or partially-read files return what was read without caching, so
    a file still being written is re-sampled on the next call.
    """
    p = Path(fastq_path)
    try:
        st = p.stat()
    except OSError:
        return []
    key = (str(p.resolve()), st.st_mtime_ns, st.st_size, max_reads)
    cached = _length_cache.get(key)
    if cached is not None:
        return cached

    lengths: List[int] = []
    try:
        with _open_text(p) as fh:
            for i, line in enumerate(fh):
                if i % 4 == 1:
                    lengths.append(len(line.rstrip("\r\n")))
                    if len(lengths) >= max_reads:
                        break
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        logger.debug("Read-length sampling failed for %s: %s", p, exc)
        return lengths

    _length_cache[key] = lengths
    return lengths


def find_input_fastqs(input_dir, max_files: int = _MAX_FILES) -> List[Path]:
    """Locate up to ``max_files`` FASTQ files under the input directory.

    Covers both layouts: flat files (single_sample / per_file) and one level
    of sample subdirectories (by_barcode). Hidden files (AppleDouble ``._*``
    sidecars above all) are skipped, mirroring the pipeline's own discovery.
    """
    root = Path(input_dir)
    if not root.is_dir():
        return []

    def _visible(paths):
        return [f for f in paths if not f.name.startswith(".")]

    files: List[Path] = []
    for pattern in _FASTQ_PATTERNS:
        files.extend(_visible(root.glob(pattern)))
    if not files:
        subdirs = sorted(
            d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")
        )
        for sub in subdirs:
            for pattern in _FASTQ_PATTERNS:
                files.extend(_visible(sub.glob(pattern)))
            if len(files) >= max_files:
                break
    return sorted(files)[:max_files]


def median_input_read_length(
    input_dir,
    max_files: int = _MAX_FILES,
    max_reads: int = _MAX_READS_PER_FILE,
) -> Tuple[Optional[int], int, Optional[str]]:
    """Return ``(median_bp, reads_sampled, example_filename)``.

    ``(None, 0, None)`` when no readable FASTQ is found.
    """
    lengths: List[int] = []
    example: Optional[str] = None
    for fastq in find_input_fastqs(input_dir, max_files=max_files):
        sampled = sample_read_lengths(fastq, max_reads=max_reads)
        if sampled and example is None:
            example = fastq.name
        lengths.extend(sampled)
    if not lengths:
        return None, 0, None
    lengths.sort()
    return lengths[len(lengths) // 2], len(lengths), example
