"""Shared per-tick memo for the per-sample organism attribution dict.

``_load_per_sample_organisms`` derives, for every real sample, the
species-level organism dicts used for attribution. Three dashboard
callbacks need it in the same tick (pathogen alert panel, dashboard
alerts, verdict banner on detection); before this memo each ran its own
full pass — ~3S+3 sweeps over the species table per tick at S barcodes
(round-2 audit, 2026-08-22).

Key design: the loader ``_freshness_epoch`` is the invalidation
authority — ``check_data_freshness`` bumps it whenever the results tree
changes, once per poll. Epoch 0 means that function never ran in this
process (CLI, tests, one-shot report generation); those callers bypass
the memo entirely so they can never be served stale data. The negative-
control declaration is part of the key because it changes the
``is_negative_control`` flags inside the result.

All consumers are synchronous main-process callbacks (verified in the
round-2 audit), so module-level state is shared correctly. If a consumer
is ever converted to ``background=True`` its worker process starts with
an empty memo — correct results, just uncached; never share this memo
via diskcache.

The returned dict is shared between callers within a tick and MUST be
treated as read-only; attribution consumers build their own structures
from it (``build_pathogen_attribution``, ``samples_for_detection``).
"""

import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional

_memo: "OrderedDict[tuple, Dict[int, List[Dict[str, Any]]]]" = OrderedDict()
_MEMO_MAX = 4
_lock = threading.Lock()


def _load_impl(main_dir: str, available_samples: List[str],
               config: Optional[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Deferred import seam: dashboard_helpers imports this module."""
    from nanometa_live.app.tabs.dashboard_helpers import (
        _load_per_sample_organisms,
    )
    return _load_per_sample_organisms(main_dir, available_samples, config)


def get_per_sample_organisms_cached(
    main_dir: str,
    available_samples: List[str],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[int, List[Dict[str, Any]]]:
    """One attribution build per tick, shared across all dashboard callers.

    Treat the returned dict as read-only (it is shared within the tick).
    """
    from nanometa_live.core.utils import loader_utils

    epoch = loader_utils._freshness_epoch
    if epoch == 0:
        return _load_impl(main_dir, available_samples, config)

    nc_signature = tuple(sorted(
        (config or {}).get("negative_control_samples") or ()))
    samples_key = tuple(
        s for s in available_samples if s != "All Samples")
    key = (main_dir, samples_key, epoch, nc_signature)

    with _lock:
        cached = _memo.get(key)
    if cached is not None:
        return cached

    result = _load_impl(main_dir, available_samples, config)
    with _lock:
        _memo[key] = result
        # Round 3: the epoch is in the key and bumps every batch, so the
        # 4-slot LRU held four dead epochs' worth of 50-120 MB payloads.
        # Keep the current and previous epoch only (the previous covers
        # callbacks still in flight across a bump).
        _evict_stale_epochs(current_epoch=key[2])
        while len(_memo) > _MEMO_MAX:
            _memo.popitem(last=False)
    return result

def _evict_stale_epochs(current_epoch) -> None:
    """Drop memo entries more than one epoch behind. Caller holds the lock
    or is the single writer path."""
    if not isinstance(current_epoch, int):
        return
    for key in [k for k in _memo
                if isinstance(k[2], int) and k[2] < current_epoch - 1]:
        _memo.pop(key, None)
