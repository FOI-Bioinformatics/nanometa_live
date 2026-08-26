"""Per-sample accumulation cache for the "All Samples" aggregate (round 3).

The incremental-layout aggregate rebuild used to parse and accumulate ALL
batch files of ALL samples every time any one sample gained a batch --
O(total files) work per rebuild, ~14 minutes at the 96x300 envelope. Per-
taxid sums are associative, so each sample's accumulation can be cached
against that sample's exact file set and the rebuild becomes: recompute
the changed sample, merge per-sample sums.

Byte-identical output is the contract (the aggregate's row order is
first-occurrence over the globally sorted file list, pinned by
tests/test_report_accumulation.py and the round-1 ordering test):

- Samples are merged as CONTIGUOUS SEGMENTS of the sorted list, in list
  order, so the global first-occurrence order is unchanged.
- If any sample's files interleave with another's in sort order (possible
  with prefix names such as barcode01 / barcode010 across layouts), the
  caller is told to fall back to the plain loop. Correctness beats the
  cache.
- A changed sample is recomputed whole, from its own files, in its own
  sorted order -- never appended to, because a new file can sort into the
  middle and change first-occurrence order within the sample.

The cache is registered with ``clear_all_loader_caches`` via
``classification_loaders.clear_report_frame_cache`` (run boundaries) and
with the perf harness reset.
"""

import logging
import os
import threading
from typing import Callable, Dict, List, Optional, Tuple

from nanometa_live.core.utils.loader_utils import _is_file_stable

_lock = threading.Lock()
# (kraken_dir, sample_key) -> (files_state, agg fragment, ordered taxids)
_sample_accum: Dict[Tuple[str, str], Tuple[tuple, Dict[int, list], List[int]]] = {}

# The accumulate function is injected by the caller (classification_loaders)
# to avoid an import cycle; module-level so tests can wrap it.
_accumulate: Optional[Callable] = None


def _segments(files: List[str], sample_key_fn: Callable[[str], str]):
    """Split the sorted file list into runs of consecutive same-sample files.

    Returns None when a sample owns more than one run -- the interleaved
    case where segment merging would reorder first occurrences.
    """
    segments: List[Tuple[str, List[str]]] = []
    seen: set = set()
    for fp in files:
        key = sample_key_fn(fp)
        if segments and segments[-1][0] == key:
            segments[-1][1].append(fp)
            continue
        if key in seen:
            return None
        seen.add(key)
        segments.append((key, [fp]))
    return segments


def _files_state(files: List[str]) -> Optional[tuple]:
    state = []
    for fp in files:
        try:
            st = os.stat(fp)
        except OSError:
            return None
        state.append((fp, st.st_mtime_ns, st.st_size))
    return tuple(state)


def aggregate_with_sample_cache(
    kraken_dir: str,
    files: List[str],
    sample_key_fn: Callable[[str], str],
    parse_fn: Callable,
    accumulate_fn: Callable,
) -> Optional[Tuple[Dict[int, list], List[int]]]:
    """Aggregate ``files`` into (agg, ordered_taxids), sample-cached.

    Returns None when the segment precondition fails or a file vanished
    mid-scan; the caller then runs its plain loop, which is always
    correct. The returned structures are fresh copies -- cached fragments
    are never exposed to mutation.
    """
    global _accumulate
    _accumulate = accumulate_fn

    segments = _segments(files, sample_key_fn)
    if segments is None:
        logging.debug(
            "Sample groups interleave in sort order under %s; using the "
            "uncached aggregate loop.", kraken_dir)
        return None

    g_agg: Dict[int, list] = {}
    g_ordered: List[int] = []
    live_keys = set()
    for sample_key, sample_files in segments:
        cache_key = (kraken_dir, sample_key)
        live_keys.add(cache_key)
        state = _files_state(sample_files)
        if state is None:
            return None
        with _lock:
            hit = _sample_accum.get(cache_key)
        if hit is None or hit[0] != state:
            s_agg: Dict[int, list] = {}
            s_ordered: List[int] = []
            s_seen: set = set()
            for fp in sample_files:
                df = parse_fn(fp)
                if df is None or df.empty:
                    if df is None and not _is_file_stable(fp):
                        # Skipped by the file-stability gate: transient by
                        # definition (the file only has to AGE past the
                        # window, which changes no mtime and therefore not
                        # this cache's key). Caching the reduced
                        # accumulation would freeze the sample out until an
                        # unrelated write -- on a completed run, forever.
                        # Bail to the caller's plain loop for this tick.
                        logging.debug(
                            "Report %s inside the stability window; "
                            "aggregate not cacheable this tick.", fp)
                        return None
                    continue
                _accumulate(df, s_agg, s_ordered, s_seen)
            with _lock:
                _sample_accum[cache_key] = (state, s_agg, s_ordered)
        else:
            s_agg, s_ordered = hit[1], hit[2]

        for taxid in s_ordered:
            fragment = s_agg[taxid]
            slot = g_agg.get(taxid)
            if slot is None:
                # Copy: the global sums mutate, the cached fragment must not.
                g_agg[taxid] = list(fragment)
                g_ordered.append(taxid)
            else:
                slot[0] += fragment[0]
                slot[1] += fragment[1]

    # Drop cache entries for samples that no longer exist under this dir,
    # so a deleted barcode does not pin its sums in memory forever.
    with _lock:
        for key in [k for k in _sample_accum if k[0] == kraken_dir
                    and k not in live_keys]:
            del _sample_accum[key]

    return g_agg, g_ordered


def cache_len() -> int:
    with _lock:
        return len(_sample_accum)


def clear_sample_accum_cache() -> None:
    with _lock:
        _sample_accum.clear()
