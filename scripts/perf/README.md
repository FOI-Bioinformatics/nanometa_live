# Per-poll scaling harness

Measures what one dashboard polling tick costs as the barcode count grows,
for 1, 2, 6, 12 and 24 samples. It runs without a browser and without
Nextflow: the loaders and figure builders are called directly against
generated result trees.

## Running it

```bash
python -m scripts.perf.scaling_bench                      # full matrix
python -m scripts.perf.scaling_bench --n 1,6,24 --no-figures
python -m scripts.perf.scaling_bench --compare scripts/perf/baseline.json
python -m scripts.perf.scaling_bench --update-baseline    # re-record
python -m scripts.perf.scaling_bench --check              # CI gate
```

Use an environment that has the app's dependencies (`dash`, `pandas`); the
`nf-core` conda env used for the smoke tests works.

## What is measured

Each cell is one `(layout, scenario, N)` point, measured twice:

- a **timing pass** (`--repeat`, default 5) with counting off, reporting the
  minimum, since measurement noise is one-sided;
- a **counting pass**, run once, since syscall counts are deterministic.

| Scenario | State | What it isolates |
|---|---|---|
| `cold` | caches cleared | first-render upper bound |
| `full_refresh` | every sample advanced | worst case for cache invalidation |
| `incremental` | one sample advanced | realtime steady state |
| `quiet` | nothing changed | the gate cost most polls actually pay |

`quiet` is the headline: in a real run most ticks find no new data, so its
cost is what the operator pays continuously.

Layouts: `batch` (flat reports), `realtime_incremental` (per-batch reports
plus the incremental markers), and `realtime_cumulative` (opt-in; the
cumulative report short-circuits the batch files).

## Why counts, not wall time, are the gate

Syscall counts over a deterministically generated tree are a function of the
tree shape and the code path only, so they reproduce exactly across machines.
Wall time on a shared CI runner varies by several times between runs, so any
threshold tight enough to catch a real regression would flake. Wall time is
recorded and printed, and gated on nothing.

Counting is done by monkeypatching rather than `cProfile`: `cProfile` inflates
wall time several-fold on this call-dominated workload, and it aggregates all
`posix.stat` calls into one entry, discarding the caller attribution that is
the point of the exercise.

## Reading the output

The per-metric tables end with a log-log slope over the N series:

```
  scaling exponent:  base O(N^1.65)   head O(N^0.91)
```

An exponent near 1 is linear in the sample count and is expected — the
freshness gate genuinely has to look at every sample's files. An exponent
above 1 means work is being repeated per sample and is the thing to hunt.

## Things that will silently corrupt results

- **A new module-level cache** in the loader stack that `instrument.reset_caches()`
  does not clear. Every "cold" cell would start warm. When you add a cache,
  add it there.
- **`CACHE_TTL_SECONDS`** (currently 30). If one cell's repeat loop runs
  longer than the TTL, its "warm" polls go cold and `quiet` silently measures
  `cold`. The value in effect is recorded in `baseline.json` under `poll`.
- **`_REPORT_FRAME_CACHE_MAX`** (currently 512). At 24 samples x 20 batches
  the parsed-frame LRU sits near capacity, so an N=24 cliff may be eviction
  rather than the loaders. Each cell records `frame_cache_len` so the two can
  be told apart.
- **Un-backdated files.** `loader_utils._is_file_stable` rejects anything
  younger than about a second, so a freshly written tree makes every loader
  return empty. `build_fixture` backdates and then asserts a non-empty load,
  which is what turns this from a silent zero into a clear failure.

## Deliberately not measured

`load_kraken2_taxonomy` / `apply_authoritative_taxonomy` (needs a real
Kraken2 `inspect.txt`, and does not scale with sample count), Dash JSON
serialisation, and the browser. The harness measures server-side per-poll
cost, not end-to-end page latency.

## Guard tests

`tests/test_perf_harness.py` keeps the harness honest, including a
determinism check and a fidelity check that the real dashboard helper sweeps
every sample the way `simulate_poll` assumes. It is skipped unless
`NANOMETA_PERF=1` is set, and must be run with `-n 0`: the counters patch
`os.stat` process-globally, which is not safe under `pytest-xdist`.
