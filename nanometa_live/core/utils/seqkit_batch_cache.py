"""Per-file cache for seqkit batch TSVs (round 3).

`_load_seqkit_incremental` re-read every batch TSV of every sample on any
cache miss -- and its outer fingerprint spans the whole ``seqkit/`` dir,
so ANY sample's new batch was a miss for all of them. Measured on the
perf harness at 24 barcodes x 100 batches: 2,414 ``pandas.read_csv``
calls and 19.6 s for one incremental tick. Batch TSVs are immutable once
stable (nanometanf writes each once), so a per-file
``(realpath, mtime_ns, size)`` cache -- the ``_report_frame_cache``
idiom -- collapses that to one read per genuinely new file.

Values are single-row frames (~2 KB); the cap is entry-count based and
generous because even the 96x300 envelope (28,800 files) fits in tens of
MB. Cleared on run boundaries via ``clear_all_loader_caches``.
"""

import logging
import os
import threading
from collections import OrderedDict
from typing import Optional

import pandas as pd

from nanometa_live.core.utils.loader_utils import _is_file_stable

_CACHE_MAX = int(os.environ.get("NANOMETA_SEQKIT_CACHE_MAX", "40000"))

_lock = threading.Lock()
_cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()


def load_batch_frame(filepath: str) -> Optional[pd.DataFrame]:
    """Parse one seqkit batch TSV through the cache.

    Returns None for unstable, unreadable or malformed files -- exactly
    the outcomes the uncached loop skipped -- and never caches a None, so
    an unstable file is retried until it settles (its mtime changes when
    the write completes, which also keys the retry correctly).
    """
    try:
        st = os.stat(filepath)
        key = (os.path.realpath(filepath), st.st_mtime_ns, st.st_size)
    except OSError:
        return None

    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached

    if not _is_file_stable(filepath):
        logging.debug("Skipping unstable seqkit batch: %s", filepath)
        return None
    try:
        df = pd.read_csv(filepath, sep="\t")
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logging.warning("Cannot read seqkit batch file %s: %s", filepath, exc)
        return None
    except (pd.errors.ParserError, pd.errors.EmptyDataError,
            UnicodeDecodeError) as exc:
        logging.warning("Malformed seqkit batch file %s: %s", filepath, exc)
        return None
    if df.empty:
        return None

    with _lock:
        _cache[key] = df
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return df


def cache_len() -> int:
    with _lock:
        return len(_cache)


def clear_seqkit_batch_cache() -> None:
    with _lock:
        _cache.clear()
