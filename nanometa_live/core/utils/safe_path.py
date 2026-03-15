"""
Safe filesystem path utilities for Nanometa Live.

Provides guarded directory listing and existence checks that return
sensible defaults (empty lists, False) when paths are missing or
inaccessible, preventing tracebacks in interval-driven callbacks.
"""

import os
import glob
import logging
from typing import List

logger = logging.getLogger(__name__)


def safe_listdir(path: str, pattern: str = "*") -> List[str]:
    """
    Return glob results for *path/pattern*, or an empty list if the
    directory is missing or inaccessible.

    Args:
        path: Directory to search.
        pattern: Glob pattern (e.g. "*.json", "**/*.fastq.gz").

    Returns:
        Sorted list of matching file paths, or [] on any error.
    """
    if not path or not os.path.isdir(path):
        return []
    try:
        return sorted(glob.glob(os.path.join(path, pattern)))
    except OSError as exc:
        logger.debug("safe_listdir failed for %s/%s: %s", path, pattern, exc)
        return []


def results_dir_exists(main_dir: str, subdir: str) -> bool:
    """
    Check whether *main_dir/subdir* exists and is a directory.

    Args:
        main_dir: Pipeline results root directory.
        subdir: Subdirectory name (e.g. "kraken2", "fastp").

    Returns:
        True if the combined path is an existing directory; False otherwise.
    """
    if not main_dir:
        return False
    target = os.path.join(main_dir, subdir)
    return os.path.isdir(target)
