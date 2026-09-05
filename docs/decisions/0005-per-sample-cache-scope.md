# 0005. A per-sample cache entry is fingerprinted against that sample's own files

**Status:** accepted (2026-07-25, extended 2026-08-25)

## Context

A quiet 24-sample real-time poll cost 74,462 `stat` calls and 772 ms, with
a scaling exponent of O(N^1.65): every per-sample lookup walked the whole
results tree, so one sample's new batch invalidated every other sample.

## Decision

`_sample_fingerprint_paths` and `_seqkit_fingerprint_paths` return the
sample-scoped path list; only the aggregate load may pass the directory.
`check_data_freshness` bumps a per-poll epoch, and an entry stored in the
current epoch is returned without a filesystem call. A `stale` mtime
verdict never falls through to the TTL cache. Write-once batch files are
cached on immutability; caches are byte-budgeted
(`NANOMETA_FRAME_CACHE_MB`) and every module-level cache is wired into
both `clear_all_loader_caches` and `instrument.reset_caches`.

## Consequences

The same poll now costs 2,119 calls and 59 ms at O(N^0.91). A frame served
from a last-good fallback or a tier fallback is transient and must not be
cached under the new fingerprint. Consumers copy a cached frame before
mutating it.

## Evidence

`tests/test_loader_cache_transparency.py`, `tests/test_cache_inventory.py`,
`tests/test_tick_call_counts.py`, `tests/test_cache_capacity_scaling.py`.
