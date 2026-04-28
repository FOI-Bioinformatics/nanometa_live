# Nanometa Live + nanometanf Throughput Synthesis -- 2026-04-28

This audit asked: can the stack reliably handle 12 or 24 barcodes streaming
reads in real time, and how efficiently does it use the host hardware?

The headline answer is **conditionally yes** -- the architectural building
blocks are in place (v1.5+ pipeline backpressure, Kraken2 memory-mapping,
watchPath with the F6 fix for atomic-rename producers), but the GUI fans
out per-tick work O(N_samples) in places where it should aggregate, and
several UX components hard-cap at 3-10 entries with no overflow path.
At 24 barcodes the predicted symptom is 5-15 second freezes every time a
batch lands, plus an operator who literally cannot tell which of 24
barcodes triggered a critical pathogen alert.

## Source audits

| Audit | File | Findings |
|---|---|---|
| Pipeline (nanometanf) | direct verification of source -- `subworkflows/local/realtime_monitoring/main.nf`, `conf/modules.config`, `nextflow.config` | Real audit below; the delegated nextflow-expert agent fabricated its output (zero tool calls, invented file paths). |
| GUI throughput (nanometa_live) | `audit-2026-04-28-throughput-gui.md` | 17 findings (P0: 2, P1: 9, P2: 6) -- verified credible (P0-T01 confirmed: 5 separate `load_kraken_data(main_dir, "All Samples")` call sites in `app/tabs/dashboard_tab.py`). |
| UI scaling (nanometa_live) | `audit-2026-04-28-throughput-ux.md` | 14 findings (P0: 2, P1: 7, P2: 5) -- 30-second-scan goal at 24 barcodes flagged DEGRADED. |

## Hardware-efficiency rubric (per-area)

| Dimension | Score | Notes |
|---|---|---|
| Pipeline backpressure | 9/10 | `max_classification_forks` (default 4) + `max_concurrent_batches` (default 4) prevent queue saturation. Defaults are conservative -- on a 16-core / 64 GB host with `kraken2_memory_mapping=true`, 8 forks would be fine. |
| Pipeline resource declarations | 8/10 | KRAKEN2_KRAKEN2 has `cpus=8`, `memory={12.GB * task.attempt}`, label `process_high`. Good. The 12 GB memory request is sized for an 8 GB MiniKraken2 DB; needs review for the 64 GB GTDB Bac120 the field uses. |
| watchPath under file-arrival storms | 8/10 | F6 settle-window fix ships; nanorunner atomic rename is supported. macOS Java NIO WatchService is documented as not always re-emitting stable events. |
| Kraken2 memory-mapping | 9/10 | Wired through `params.kraken2_memory_mapping` (default true) -> `--memory-mapping` ext.args in `conf/modules.config:183`. Auto-disabled on ARM (Apple Silicon) at `taxonomic_classification/main.nf:104` because mmap segfaults under emulation. |
| Cumulative report aggregation | 7/10 | Live in `subworkflows/local/taxonomic_classification/main.nf` via `KRAKEN2_INCREMENTAL_CLASSIFIER` with batch caching. `report_write_interval = 5` (default 5 batches) keeps I/O bounded. |
| GUI per-tick callback fanout | 5/10 | Five separate "All Samples" loads in `dashboard_tab.py` alone (verified). Per-sample loops in `_load_per_sample_organisms`. P0 in the GUI audit. |
| GUI loader cache scaling | 6/10 | mtime fingerprint key works, but at 24 barcodes a single barcode's batch report invalidates the shared "All Samples" cache for everyone. |
| UI 30-second-scan at 24 barcodes | 4/10 | "+N more" chip pill is non-interactive (you cannot enumerate which of 24 barcodes carry a critical pathogen). Verdict banner subhead never names the triggering sample. |
| 24-barcode dashboard ergonomics | 5/10 | AgGrid table paginates at 8 rows by default; 24-row sample selector dropdown not searchable; classification filter defaults tuned for one sample. |

**Aggregate: 67/100 for 24-barcode runs.** Robust enough to complete a run, but the operator UX falls below the 30-second-scan promise and the GUI burns CPU it does not need to.

## Findings rolled up by severity

### P0 -- run-blocking or clinically misleading (4 total)

**P0-G01** (GUI) Five separate `load_kraken_data(main_dir, "All Samples")`
callbacks fire per tick, all with the same 2s mtime cache key. When any
barcode writes a fresh batch the cache invalidates for everyone, and 5-10
callbacks each redo the full aggregation in serial Python. Predicted 5-15s
freezes per tick on 24-barcode runs. **Files:** `app/tabs/dashboard_tab.py:410,777,1566,2006,2027`.

**P0-G02** (GUI) `_load_per_sample_organisms` (dashboard pathogen-alert
callback) iterates over every barcode in a Python `for` loop and calls
`load_kraken_data(main_dir, sample)` per iteration. At 24 barcodes that is
24 serial loads, each potentially parsing a multi-MB cumulative report on
a cache miss, all on the Dash request thread. **File:** `audit-2026-04-28-throughput-gui.md` for line numbers.

**P0-T01** (UX) Pathogen alert "+N more" chip pill is non-interactive --
hard-capped at 3 inline chips with no expandable list, no tooltip, no
underlying data. On a 24-barcode run with one critical pathogen detected
in 18 samples the operator sees three barcode chips and "+15 more" with
no way to enumerate. The clinical question "which sample is contaminated?"
is unanswerable from the dashboard. **Files:** `app/components/pathogen_alert.py:69-112`.

**P0-T02** (UX) Zone 1 verdict banner subhead never names the triggering
sample(s). One contaminated barcode in 24 reads to the operator the same
as 24-of-24 contaminated. **Files:** `app/tabs/dashboard_tab.py:425-443`.

### P1 -- degrades throughput or 30-second scan (16 total)

Highlights:
- Direct `glob`/`open` calls bypass `_fastp_cache`
- Dashboard callbacks read `update-interval` directly instead of subscribing to `dashboard-overall-status-cache`
- `update_available_samples` cache-bypasses `get_sample_file_mapping`
- `_collect_samples_data` runs 48-72 loader calls per tick
- Single-worker DiskcacheManager
- Validation parser triple-rescanning
- Sample selector dropdown not searchable at 12-24 entries
- AgGrid paginates at 8 dashboard / 10 QC rows -- 24-row tables paginate by default
- BLAST/coverage card list non-virtualized at ~120 cards
- Coverage species selector flat (120-entry) with no grouping
- Classification filter defaults tuned for one sample

### P2 -- polish (11 total)

See per-audit reports.

## Pipeline-side additional notes (from direct verification)

The previously fabricated audit got several facts backwards. Real state:

- `subworkflows/local/realtime_monitoring/main.nf:93` has
  `Channel.watchPath(full_pattern, 'create,modify')` mixing existing files
  in first via `Channel.fromList` round-robin-interleaved by parent
  directory (so a `.take(N)` cap is fair across 24 barcodes, not biased
  toward one).
- `conf/modules.config:183`:
  `ext.args = { params.kraken2_memory_mapping ? "--memory-mapping" : "" }`
  -- the flag is wired through. Default true (`nextflow.config:53`).
- `conf/modules.config:178-188`: KRAKEN2_KRAKEN2 has `cpus = 8`,
  `memory = { 12.GB * task.attempt }`, label `process_high`. The 12 GB
  comment says "for 8GB database + overhead" -- this is sized for a
  MiniKraken2 dev DB, **not** the production GTDB Bac120 8 GB or
  PlusPFP 80 GB databases. Operators using PlusPFP need to bump memory.
- `nextflow.config:62-63`: defaults `max_concurrent_batches = 4`,
  `max_classification_forks = 4`. Both are conservative but correct;
  with `kraken2_memory_mapping=true` and 16+ cores you can raise
  `max_classification_forks = 8`.
- `conf/modules.config:214,232,265`: KRAKEN2_INCREMENTAL_CLASSIFIER
  honours `params.max_classification_forks` via `maxForks =
  params.max_classification_forks ?: 4`. Clean.
- `subworkflows/local/realtime_monitoring/main.nf:38`:
  `def max_concurrent = params.max_concurrent_batches ?: 4` -- backpressure
  is per-sample, not global. At 24 barcodes total in-flight = 24 x 4 = 96.
  This may saturate with `executor.queueSize` defaulting to 100; consider
  raising `executor.queueSize` to 200 for 24-barcode runs or capping
  `max_concurrent_batches = 2` at high sample count.

The remaining concern -- not flagged by the GUI/UX audits -- is that
`max_concurrent_batches` is per-sample. With 24 barcodes the total
in-flight work fan-out is 24 x 4 = 96 batches simultaneously schedulable.
This is plausibly fine on a workstation with `max_classification_forks=4`
serializing the heaviest stage, but operators should be told.

## Recommended changes (deferred to a separate fix wave)

### Pipeline (`nanometanf`)

```groovy
// nextflow.config -- add these to params block for 24-barcode tuning guidance
params {
    // For 16-core / 64 GB workstation with kraken2_memory_mapping=true and PlusPFP DB:
    //   max_classification_forks = 8  (forks share mmap'd DB)
    //   max_concurrent_batches = 2     (cap per-sample fan-out at high sample count)
    // For 32-core / 128 GB server:
    //   max_classification_forks = 12
    //   max_concurrent_batches = 4
}
```

`KRAKEN2_KRAKEN2` memory bound (`conf/modules.config:181`) is sized for
the 8 GB MiniKraken2 dev database. For PlusPFP_8GB use `12.GB`, for full
PlusPFP use `64.GB`. Either parameterise on `params.kraken2_db_size_gb`
or document in the operator guide.

`executor.queueSize` is not explicitly set. Current default (100) is fine
at 12 barcodes but tight at 24 (`24 * max_concurrent_batches=4 = 96`).
Add `executor { queueSize = 200 }` to `nextflow.config` for headroom.

### GUI (`nanometa_live`)

Three high-impact changes that close the P0s:

1. **Centralize "All Samples" loading.** The five `load_kraken_data(...,
   "All Samples")` call sites in `dashboard_tab.py` should be one shared
   `dcc.Store` (e.g. `dashboard-aggregate-cache`) with a single callback
   feeding it. Other dashboard callbacks become readers of the store.
   Also resolves the per-sample loop in `_load_per_sample_organisms`.

2. **Make alert chip pill expandable.** `_render_sample_attribution()` in
   `app/components/pathogen_alert.py:69-112` should return a `dcc.Tooltip`
   on the "+N more" pill containing the full sample list, or open a
   modal listing all triggering samples. Either is acceptable; the
   current dead-end pill is not.

3. **Add triggering-sample subhead to verdict banner.** `dashboard_tab.py:425-443`
   should append "Triggered by: barcode13, barcode17 (2 of 24 samples)"
   when ACTION REQUIRED state fires from a subset.

## Empirical 12 / 24-barcode reproduction script

Run on the actual target hardware to ground-truth the audit predictions.
Not run in this session.

```bash
# Conda envs (pre-existing)
#   nf-core    -- nanometa_live, nanometanf
#   nanorunner -- the simulator

# Build a 12-barcode dataset (24 barcodes by duplicating the 12-source set)
RAW=/Users/andreassjodin/Desktop/snabbsekvensering/rawdata_organized
TGT=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/_test_data_2026-04-28/multiplex_12
mkdir -p "$TGT"
# 12-barcode is already organized in rawdata_organized/barcode01..12

# Drive nanorunner replay at a steady file-arrival rate
conda run -n nanorunner nanorunner replay \
  --source "$RAW" \
  --target /Users/andreassjodin/Desktop/snabbsekvensering/output-live/realtime_input_12 \
  --interval 10 \
  --batch-size 12 \
  --reads-per-file 200 \
  --force-structure multiplex \
  --operation copy \
  --monitor enhanced &
NANORUNNER_PID=$!

# Launch nanometa_live in another terminal pointing at the watch dir
conda run -n nf-core python -m nanometa_live.app \
  --config /Users/andreassjodin/Desktop/snabbsekvensering/output-live/_test_data_2026-04-28/realtime_12bc_config.yaml \
  --port 8050

# Monitor host resources during the run
top -o cpu -stats pid,command,cpu,mem,th  # or `htop` if installed
du -sh /Users/andreassjodin/Desktop/snabbsekvensering/output-live/realtime_run_12bc/work
```

Expected pass criteria for 12 barcodes:
- Nextflow `trace.txt` shows no task takes >2x its declared `time`
- GUI Dashboard tick latency (browser network tab, "Reload data" XHR) <2s on cold cache, <500ms warm
- Memory of the `nextflow main` JVM stays under 2 GB
- Memory of the dash app stays under 4 GB after 1 hour
- `~/.nanometa/work/conda` populates exactly the env set listed in `_PRE_WARM_SCENARIOS`

For 24 barcodes (duplicate the 12-source dataset by running nanorunner
twice with different `--target` paths and merging into a single watch
directory) raise tolerances 2x and watch for the P0-T01 / P0-T02
clinical-misleading symptoms in real use.

## Caveats

- Empirical run not performed in this session; predictions based on
  source review.
- The pipeline-side delegated audit fabricated its findings; my own
  verification covered the highest-risk areas (watchPath, memory-mapping,
  Kraken2 labels, queue caps, error strategy) but is not exhaustive.
- I did not run `nf-core lint` -- it is currently broken on an upstream
  tooling regression unrelated to this audit (master-to-main branch
  rename in nf-core/modules.git).
