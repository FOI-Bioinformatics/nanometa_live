"""
First-batch detection helper (U4, 2026-05-09 UX spec).

Returns ``True`` once any tracked nanometanf output subdirectory contains
a non-empty file. The waiting-for-first-batch banner is hidden as soon
as this flag flips, so the check has to be cheap (one os.scandir per
tracked subdir, early exit on first match).
"""

from __future__ import annotations

import os
from typing import Iterable

# Subdirectories that nanometanf may write into during normal operation.
# A non-empty file in any of these counts as "first batch arrived".
TRACKED_SUBDIRS = ("kraken2", "fastp", "seqkit", "validation", "taxpasta")


def _dir_has_nonempty_file(path: str) -> bool:
    """Return True if path is a directory containing at least one non-empty file.

    Walks recursively but exits at the first match to keep the cost
    bounded on large outdirs.
    """
    if not path or not os.path.isdir(path):
        return False
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                full = os.path.join(root, name)
                try:
                    if os.path.getsize(full) > 0:
                        return True
                except OSError:
                    continue
    except OSError:
        return False
    return False


def first_batch_seen(
    main_dir: str, subdirs: Iterable[str] = TRACKED_SUBDIRS
) -> bool:
    """Return True if any tracked subdir under main_dir holds a non-empty file."""
    if not main_dir or not os.path.isdir(main_dir):
        return False
    for sub in subdirs:
        if _dir_has_nonempty_file(os.path.join(main_dir, sub)):
            return True
    return False
