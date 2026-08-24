"""Syscall counting and cache reset helpers for the scaling harness.

Counting is done by monkeypatching rather than by :mod:`cProfile`. Two
reasons:

* The workload under study is call-dominated. cProfile's per-call overhead
  inflates wall time several-fold, so a single run cannot yield both a
  trustworthy duration and trustworthy counts.
* cProfile aggregates every ``posix.stat`` into one entry regardless of
  caller, which discards exactly the attribution the study needs.

Patching ``os.stat`` transitively covers ``os.path.exists``, ``os.path.isdir``,
``os.path.isfile``, ``os.path.getmtime`` and ``os.path.getsize``: the
``genericpath`` and ``posixpath`` implementations resolve ``os.stat`` as a
module attribute at call time rather than binding it at import.

Counts are a function of the directory tree and the code path only, so they
are reproducible across machines. Wall time is not, which is why the CI gate
in :mod:`scripts.perf.scaling_bench` asserts on counts alone.
"""

from __future__ import annotations

import builtins
import glob as glob_mod
import json as json_mod
import os
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Tuple

# (module, attribute) pairs wrapped by the counter. Keep the reported label
# stable -- it is a key in the committed baseline.
_TARGETS: Tuple[Tuple[Any, str, str], ...] = (
    (os, "stat", "os.stat"),
    (os, "lstat", "os.lstat"),
    (os, "scandir", "os.scandir"),
    (os, "listdir", "os.listdir"),
    (os, "walk", "os.walk"),
    (glob_mod, "glob", "glob.glob"),
    (glob_mod, "iglob", "glob.iglob"),
    (builtins, "open", "builtins.open"),
    (json_mod, "load", "json.load"),
)

# Metrics the CI gate is allowed to assert on. builtins.open is excluded
# deliberately: pandas rearranges its own file handling between releases, so
# the count moves for reasons unrelated to this codebase.
GATED_METRICS: Tuple[str, ...] = (
    "os.stat",
    "os.scandir",
    "os.listdir",
    "glob.glob",
    "pandas.read_csv",
)

ALL_METRICS: Tuple[str, ...] = tuple(
    [label for _, _, label in _TARGETS] + ["pandas.read_csv"]
)


@dataclass
class CountResult:
    """Syscall counts plus loader-cache occupancy for one measured region."""

    counts: Counter = field(default_factory=Counter)
    frame_cache_len: int = 0
    frame_cache_evictions: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {label: int(self.counts.get(label, 0)) for label in ALL_METRICS}


@contextmanager
def count_syscalls() -> Iterator[CountResult]:
    """Count filesystem and parse calls made inside the block.

    Not reentrant and not thread-safe -- the patches are process-global. The
    harness is single-threaded by construction.
    """
    result = CountResult()
    counts = result.counts
    originals: List[Tuple[Any, str, Callable]] = []

    def make_wrapper(fn: Callable, label: str) -> Callable:
        def wrapper(*args, **kwargs):
            counts[label] += 1
            return fn(*args, **kwargs)

        return wrapper

    for module, attr, label in _TARGETS:
        original = getattr(module, attr)
        originals.append((module, attr, original))
        setattr(module, attr, make_wrapper(original, label))

    # pandas.read_csv is patched separately: the loaders import it as
    # ``pd.read_csv``, so patching the pandas module attribute is what
    # actually intercepts them.
    import pandas as pd

    pd_original = pd.read_csv
    pd.read_csv = make_wrapper(pd_original, "pandas.read_csv")

    try:
        yield result
    finally:
        pd.read_csv = pd_original
        for module, attr, original in reversed(originals):
            setattr(module, attr, original)
        result.frame_cache_len = report_frame_cache_len()


@contextmanager
def timed() -> Iterator[List[float]]:
    """Measure wall time of the block in milliseconds.

    Yields a one-element list that is filled on exit, so the caller can read
    the duration after the ``with`` block closes.
    """
    holder: List[float] = []
    start = time.perf_counter()
    try:
        yield holder
    finally:
        holder.append((time.perf_counter() - start) * 1000.0)


def report_frame_cache_len() -> int:
    """Current occupancy of the per-file parsed-frame LRU.

    Recorded per measurement cell so an N=24 slowdown caused by LRU eviction
    (``_REPORT_FRAME_CACHE_MAX`` is 512) can be told apart from one caused by
    the loaders themselves.
    """
    from nanometa_live.core.utils import classification_loaders as cl

    try:
        with cl._report_frame_cache_lock:
            return len(cl._report_frame_cache)
    except Exception:
        return -1


def reset_caches() -> None:
    """Drop every module-level loader cache, restoring a cold-start state.

    Maintenance hazard: a new module-level cache added anywhere in the loader
    stack and not cleared here silently invalidates every "cold" measurement,
    because the second and later cells would start warm. When adding a cache,
    add it here.
    """
    from nanometa_live.core.utils import classification_loaders as cl
    from nanometa_live.core.utils import loader_utils as lu
    from nanometa_live.core.utils import sample_detector as sd

    lu.clear_data_cache()
    lu._last_freshness_fingerprint = ""
    cl.clear_report_frame_cache()

    with sd._sample_cache_lock:
        sd._sample_cache.clear()

    # Optional caches -- present in some versions of the loader stack.
    for module, name in ((lu, "_poll_fingerprint_cache"),
                         (sd, "_manifest_cache")):
        cache = getattr(module, name, None)
        if isinstance(cache, dict):
            cache.clear()

    # Round-3 additions: the caches the first version missed, which made
    # every "cold" cell measure warm for the paths that touch them
    # (taxonomy map, PAF breadth, validation parser singletons, the
    # organisms/pathogen memos, per-key parse locks, staleness flags).
    # Pinned by tests/test_perf_fixtures_validation.py.
    from nanometa_live.app.tabs import kraken2_helpers as kh
    from nanometa_live.app.tabs import dashboard_helpers as dh
    from nanometa_live.app.utils import organisms_memo as om
    from nanometa_live.core.parsers import paf_coverage_parser as pcp
    from nanometa_live.core.parsers import blast_validation_parser as bvp
    from nanometa_live.core.utils import pathogen_database as pdb
    from nanometa_live.core.utils import staleness

    kh._TAXONOMY_CACHE.clear()
    pcp._breadth_cache.clear()
    om._memo.clear()
    dh._pathogen_check_memo.clear()
    pdb._dangerous_check_memo.clear()
    bvp.reset_validation_parsers()
    staleness.clear()
    with lu._parse_locks_lock:
        lu._parse_locks.clear()


def report_frame_cache_bytes() -> int:
    """Deep byte size of the parsed-frame caches (round 3).

    The count-based LRU is size-blind; this is the number the memory gate
    watches so a 50k-row report population cannot silently multiply the
    resident set by 20x behind an unchanged entry count.
    """
    from nanometa_live.core.utils import classification_loaders as cl

    try:
        with cl._report_frame_cache_lock:
            frames = list(cl._report_frame_cache.values()) + list(
                cl._last_good_frame.values())
        return int(sum(df.memory_usage(deep=True).sum() for df in frames))
    except Exception:
        return -1


def cache_ttl_seconds() -> int:
    """Current loader TTL, recorded in the baseline for interpretation."""
    from nanometa_live.core.utils import loader_utils as lu

    return int(lu.CACHE_TTL_SECONDS)
