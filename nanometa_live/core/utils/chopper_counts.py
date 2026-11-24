"""Chopper's own read counts: the reads before and after the filter.

chopper writes ``Kept K reads out of N reads`` to standard error and keeps no
other record of the reads it received. nanometanf (from the release after
1.12.0) publishes that text per task to
``chopper/<sample>/counts/<sample>.<stamp>.chopper_counts.txt``, one file per
batch. Summing N over a sample's files gives the reads that entered the
filter, which is the only count of the reads before filtering a chopper run
has; SeqKit and Kraken2 both see the filtered reads.

Each file is written once, so a parsed file is cached on its realpath and
``(st_mtime_ns, st_size)``. A file that does not yet carry the summary line
(chopper writes it last) is not cached and is read again on the next poll.
"""

from __future__ import annotations

import glob
import os
import re
from typing import Dict, NamedTuple, Optional, Tuple

_KEPT_RE = re.compile(r"Kept (\d+) reads out of (\d+) reads")


class ChopperCounts(NamedTuple):
    reads_in: int
    reads_kept: int
    files: int


# realpath -> ((st_mtime_ns, st_size), (reads_in, reads_kept))
_counts_cache: Dict[str, Tuple[Tuple[int, int], Tuple[int, int]]] = {}


def clear_chopper_counts_cache() -> None:
    _counts_cache.clear()


def _read_counts(path: str) -> Optional[Tuple[int, int]]:
    """(reads_in, reads_kept) from one file, or None when not yet complete."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = os.path.realpath(path)
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _counts_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            matches = _KEPT_RE.findall(fh.read())
    except OSError:
        return None
    if not matches:
        return None
    kept, total = (int(v) for v in matches[-1])
    _counts_cache[key] = (stamp, (total, kept))
    return total, kept


def load_chopper_counts(main_dir: str, sample: Optional[str]) -> Optional[ChopperCounts]:
    """Summed chopper counts for one sample, or for all samples.

    ``sample`` None or ``"All Samples"`` sums every sample. Returns None when
    no file carries a summary line, so a run without the files (fastp,
    filtlong, an older nanometanf) is told apart from a measured zero.
    """
    if not main_dir:
        return None
    scope = "*" if sample in (None, "All Samples") else glob.escape(sample)
    pattern = os.path.join(main_dir, "chopper", scope, "counts", "*.chopper_counts.txt")
    reads_in = reads_kept = files = 0
    for path in sorted(glob.glob(pattern)):
        counts = _read_counts(path)
        if counts is None:
            continue
        reads_in += counts[0]
        reads_kept += counts[1]
        files += 1
    if files == 0:
        return None
    return ChopperCounts(reads_in, reads_kept, files)
