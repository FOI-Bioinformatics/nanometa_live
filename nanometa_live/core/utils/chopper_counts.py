"""Chopper's own read counts: the reads before and after the filter.

chopper writes ``Kept K reads out of N reads`` to standard error and keeps no
other record of the reads it received. nanometanf (from the release after
1.12.0) publishes that text per task to
``chopper/<sample>/counts/<sample>.<stamp>.chopper_counts.txt``, one file per
batch. Summing N over a sample's files gives the reads that entered the
filter, which is the only count of the reads before filtering a chopper run
has; SeqKit and Kraken2 both see the filtered reads.

Two cache layers keep a quiet poll at one ``stat`` per sample, however many
batch files a long run accumulates (barcodes x batches):

- ``_sample_memo`` holds each sample's sum keyed on its ``counts/``
  directory's mtime; publishing a new file changes that mtime. It is stored
  only when every file in the directory carried the summary line, so a file
  completed in place (its own mtime changes, the directory's does not) is
  still read on the next poll.
- ``_counts_cache`` holds each parsed file on its realpath and
  ``(st_mtime_ns, st_size)``, so a directory that did change re-reads only
  its new files.
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


# realpath of a sample's counts/ directory -> (dir st_mtime_ns, (in, kept, files))
_sample_memo: Dict[str, Tuple[int, Tuple[int, int, int]]] = {}


def clear_chopper_counts_cache() -> None:
    _counts_cache.clear()
    _sample_memo.clear()


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


def _sample_counts(counts_dir: str) -> Optional[Tuple[int, int, int]]:
    """(in, kept, files) for one sample's ``counts/`` directory, or None."""
    try:
        dir_mtime = os.stat(counts_dir).st_mtime_ns
    except OSError:
        return None
    key = os.path.realpath(counts_dir)
    memo = _sample_memo.get(key)
    if memo is not None and memo[0] == dir_mtime:
        return memo[1]
    paths = sorted(glob.glob(os.path.join(glob.escape(counts_dir), "*.chopper_counts.txt")))
    reads_in = reads_kept = files = 0
    for path in paths:
        counts = _read_counts(path)
        if counts is None:
            continue
        reads_in += counts[0]
        reads_kept += counts[1]
        files += 1
    if files and files == len(paths):
        _sample_memo[key] = (dir_mtime, (reads_in, reads_kept, files))
    return (reads_in, reads_kept, files) if files else None


def load_chopper_counts(main_dir: str, sample: Optional[str]) -> Optional[ChopperCounts]:
    """Summed chopper counts for one sample, or for all samples.

    ``sample`` None or ``"All Samples"`` sums every sample. Returns None when
    no file carries a summary line, so a run without the files (fastp,
    filtlong, an older nanometanf) is told apart from a measured zero.
    """
    if not main_dir:
        return None
    scope = "*" if sample in (None, "All Samples") else glob.escape(sample)
    reads_in = reads_kept = files = 0
    for counts_dir in sorted(glob.glob(os.path.join(glob.escape(main_dir), "chopper", scope, "counts"))):
        counts = _sample_counts(counts_dir)
        if counts is None:
            continue
        reads_in += counts[0]
        reads_kept += counts[1]
        files += counts[2]
    if files == 0:
        return None
    return ChopperCounts(reads_in, reads_kept, files)
