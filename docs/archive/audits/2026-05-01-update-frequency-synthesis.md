# Synthesis: Update Frequency, Real-Time Triggering, and Event-Driven Refresh

**Date:** 2026-05-01
**Scope:** End-to-end audit of how nanometanf is triggered, how the
Dash dashboard schedules redraws, and where the two halves can be
reconciled around a single "data has actually changed" signal.
**Sources:** Two reliable worker reports plus a redone backend audit
performed for this synthesis.[^worker2]

[^worker2]: An earlier worker (`nextflow-expert`) returned a backend
audit with two material errors -- it claimed `Channel.watchPath` was
not used in nanometanf, and that `subworkflows/local/process_batches/main.nf`
is a zero-byte stub. Both are false.
`Channel.watchPath(full_pattern, 'create,modify')` is invoked at
`subworkflows/local/realtime_monitoring/main.nf:93`, and there is no
`process_batches/` subworkflow in the tree at all. The findings in
Section 1 below come from a redone audit, not that worker's output.

The user's four questions are answered in order. Concrete claims cite
`file:line` where verifiable. Where a claim could not be verified from
the visible source the text says so explicitly.

---

## 1. How is nanometanf triggered in real time -- files, or time?

**Answer: predominantly files, with a wall-clock idle-timeout safety
net and a per-batch wall-clock flush bound that is currently
non-functional.**

### 1.1 The watchPath entry point

The real-time entry is a single `Channel.watchPath` call:

- `subworkflows/local/realtime_monitoring/main.nf:93` --
  `Channel.watchPath(full_pattern, 'create,modify')`. The pattern is
  built from `${watch_dir}/${file_pattern}` (line 45). `watch_dir`
  comes from `params.nanopore_output_dir` and `file_pattern` defaults
  to `"**.fastq{,.gz}"`
  (`nextflow.config:17-18`).

- The subworkflow first enumerates already-existing matches via
  `file(full_pattern)` (line 46), groups them by parent directory,
  interleaves round-robin so `take(max_files)` is fair across
  barcodes (lines 56-76), then `mix(ch_existing, ch_new)`
  (line 96) so existing files are processed first and new files
  stream in after.

- The settling filter that earlier dropped emissions younger than 1 s
  was removed; the F6 fix comment (lines 98-109) explains that atomic
  rename writers (nanorunner, MinKNOW, rsync) always land inside that
  window and that the macOS Java NIO `WatchService` does not
  reliably re-emit a stable file. Files are therefore consumed as
  soon as `watchPath` reports them.

- Wiring into the main workflow:
  `workflows/nanometanf.nf:166-174` instantiates
  `REALTIME_MONITORING(...)` only when `params.realtime_mode` is true
  and `params.nanopore_output_dir` is set; otherwise the static
  samplesheet path is used (line 198).

This is the only `Channel.watchPath` invocation in nanometanf
(`grep -rn watchPath subworkflows/ workflows/ main.nf` returns
exactly four hits, all referring to that one call site).

### 1.2 Where wall-clock time enters the pipeline

Three time-based bounds wrap the file-driven stream. They are
independent and any one of them can terminate the channel:

**(a) Idle / total-budget timeout.**
`realtime_monitoring/main.nf:141-181` schedules a one-shot daemon
`Timer` that binds a `__REALTIME_TIMEOUT_SENTINEL__` value plus
`PoisonPill.instance` into a `DataflowQueue` after
`(realtime_timeout_minutes + realtime_processing_grace_period) * 60_000` ms.
The sentinel is `mix`ed into the file stream (line 179) and
`.until { it == TIMEOUT_SENTINEL }` (line 180) terminates downstream
consumption when it arrives. Defaults:
`realtime_timeout_minutes = 60`, `realtime_processing_grace_period = 5`
(`nextflow.config:23-24`).

**(b) Hard file count cap.**
`.take(params.max_files.toInteger())` at line 185. Default is
`null` (`nextflow.config:22`).

**(c) Per-batch flush bound.**
This is the one with a problem.
`realtime_monitoring/main.nf:243-247` and `253-258` call
`BatchUtils.batchWithTimeout(ch, effective_batch_size, batch_timeout_val)`
with `batch_timeout_val = params.batch_timeout ?: 60`
(`nextflow.config:41`). The intent, per the schema help text at
`nextflow_schema.json:323`, is "if no new files arrive within this
many seconds, the current partial batch is emitted." Looking at the
implementation:

`lib/BatchUtils.groovy:28-32` --
```
static def batchWithTimeout(ch_input, int batchSize, int timeoutSeconds) {
    return ch_input.buffer(size: batchSize, remainder: true)
}
```
The `timeoutSeconds` argument is **discarded**. The class doc at
lines 10-13 acknowledges that `Channel.create()` is gone in modern
Nextflow and recommends `watchPath`'s polling interval for timeout
behaviour, but the production code falls back to plain
`buffer(size: N, remainder: true)`. The consequence: a batch is
emitted **only** when `batch_size` files have accumulated, or when
the upstream channel closes (one of the two bounds in (a)/(b)
fires). On a low-throughput run (single barcode, slow MinION
release cadence) the dashboard can wait the full
`realtime_timeout_minutes` before any batch ever reaches Kraken2.
This is worth fixing.

**Default cadence summary:**

| Bound | Default | Effect |
|---|---|---|
| File events (`watchPath`) | n/a | Files trigger immediately on `create,modify` |
| Per-batch size | `batch_size = 10` (line 20) | Emit a batch every 10 files per sample |
| Per-batch timeout | `batch_timeout = 60` s (line 41) | **Documented but not implemented** |
| Idle timeout | `realtime_timeout_minutes = 60` (line 23) | Hard stop after 60 min idle (+ 5 min grace) |
| Cumulative-report write | `report_write_interval = 5` (line 71) | Cumulative kreport rewritten every 5 batches per sample |
| File hard cap | `max_files = null` | Off by default |

### 1.3 What the dashboard polls vs what nanometanf produces

The relevant disk-level heartbeats are:

- `kraken2/{sample}.cumulative.kraken2.report.txt` -- written
  atomically (temp + rename) by the progressive cumulative reporter
  inside the Nextflow head process at
  `taxonomic_classification/main.nf:298-307`. Touched once per
  `report_write_interval` batches, plus on the final batch
  (`is_final_batch == true`).
- `kraken2/{sample}_batch{n}.kraken2.report.txt` -- per-batch reports
  written by `KRAKEN2_REPORT_GENERATOR`. The Nanometa loader
  explicitly excludes this pattern when picking up cumulative
  reports (per the `Output File Formats` section of the project
  CLAUDE.md).
- `seqkit/{sample}.tsv` (Chopper / Filtlong) or `fastp/{sample}.fastp.json`
  (Fastp) -- written per batch, but with `qc_enable_incremental` on
  (auto-promoted to true when `realtime_mode + kraken2_enable_incremental`
  -- see `qc_analysis/main.nf:236-241`) the seqkit stats are merged
  per-sample so the published `seqkit/{sample}.tsv` is cumulative.
- `validation/blast/{sample}.blast.tsv`,
  `validation/minimap2/{sample}_taxid{tid}.paf` -- written by the
  validation subworkflow either during the run (when validation is
  enabled) or by the on-demand `nextflow run --validation_only`
  invocation (`main.nf:147-151`).

In other words: **the dashboard's true "new data is available"
signal is the mtime of `kraken2/*.cumulative.kraken2.report.txt`,
plus the QC and validation outputs.** Nothing in the GUI today is
actually subscribing to those mtimes.

### 1.4 NanoPlot and MultiQC are explicitly throttled

Per `qc_analysis/main.nf:289-337`:

- `params.nanoplot_realtime_skip_intermediate = true` (default,
  `nextflow.config:131`) plus `params.nanoplot_batch_interval = 10`
  means NanoPlot runs only every 10th batch and on the final batch
  in real-time mode.
- `multiqc_realtime_final_only = true` (default,
  `nextflow.config:133`) defers MultiQC to end-of-session.

These are fine and not part of the figure-update problem the user
is asking about.

---

## 2. How often are figures updated, and what does that cost?

Synthesised from the frontend audit at
`docs/audit-2026-05-01-update-frequency-frontend.md`.

### 2.1 Two clocks, never disabled

- `update-interval` -- `app/app.py:260`, period
  `config.get('update_interval_seconds', 30) * 1000` ms, default
  30 000 ms. **24 callbacks subscribe**.
- `countdown-tick` -- `app/app.py:268`, period 1 000 ms fixed. Two
  callbacks subscribe.

Neither interval is ever disabled by any callback (no writes to
their `disabled` prop). Both fire from page load to page close
regardless of pipeline state.

### 2.2 Worst offenders at default cadence

These are the callbacks that run every 30 s, with their cost and
gating status. Source: frontend audit Section 4.

| Rank | Callback | File:line | Debounce | Per-tick work |
|---|---|---|---|---|
| 1 | `update_main_results` | `main_tab.py:297` | none | Full Kraken2 parse (mtime-cached but contended), organism cards, watchlist scan, 9 outputs, AgGrid full `rowData` replace |
| 2 | `update_readiness_indicator` | `callbacks.py:438` | none | `shutil.which` x 7 tools + `os.stat`/glob per DB path, 10+ syscalls per tick |
| 3 | `update_verdict_banner` | `dashboard_tab.py:163` | 2 s | Calls `load_kraken_data` directly instead of consuming `dashboard-overall-status-cache` (the bug at line 237) |
| 4 | `update_pathogen_alert_panel` | `dashboard_tab.py:605` | 2 s | `load_kraken_data` + per-sample organism load |
| 5 | `compute_overall_status_cache` | `dashboard_tab.py:118` | 2 s | `load_kraken_data` + `_collect_samples_data` across all samples |
| 6 | `update_classification_plot` | `classification_tab.py:122` | 2 s | Sankey/Sunburst figure regeneration |
| 7-13 | Seven QC callbacks | `qc_tab.py:228..1252` | 2 s each | FASTP/seqkit parse + figure render |
| 14 | `update_elapsed_time` | `callbacks.py:884` | none | **Fires every 1 s**; cheap arithmetic, but one server round-trip per second even when no run is active |

Three structural problems in the current model:

1. **The dashboard polls regardless of file changes.** Even when no
   file under `kraken2/`, `seqkit/`, `fastp/`, or `validation/` has
   changed, the 24 subscribers still run. The only thing keeping
   cost down is the inner `_check_mtime_cache` short-circuit inside
   `load_kraken_data` (loader_utils.py:249-284); the callback bodies,
   the figure-construction code, and the AgGrid full-replace still
   fire.

2. **AgGrid tables flicker.** All four AgGrid tables already have
   `getRowId` declared (verified at `main_layout.py:286`,
   `qc_layout.py:315`, `dashboard_layout.py:334`,
   `validation_layout.py:279`) but every interval-driven callback
   returns a full `rowData` list, defeating row-level diffing. No
   `Patch()` usage exists anywhere
   (`grep -rn 'Patch()' app/` returns zero hits).

3. **`aggregate-kraken-cache` is dead weight.** The store is declared
   at `app/app.py:248` but `update_verdict_banner`
   (`dashboard_tab.py:237`) ignores it and re-calls `load_kraken_data`
   on its own, racing `compute_overall_status_cache` for the
   `_get_parse_lock` mutex.

### 2.3 The 1-second clock fires when nothing is running

`update_elapsed_time` (`callbacks.py:884`) wakes up every second
even when `backend-status.running` is false. It returns immediately
in that case, but the round-trip still occupies a Flask worker
thread. The clientside countdown at `app/app.py:653` already has
the `backend-status` Store as Input; merging the two into one
clientside callback eliminates the per-second server hit entirely.

---

## 3. Could we update only when new data is available?

Yes, with a small, well-bounded change. Synthesised from
`docs/audit-2026-05-01-event-driven-proposal.md`.

### 3.1 The primitive already exists and is unused

`core/utils/loader_utils.py:287-318` defines
`check_data_freshness(main_dir)`. It scans `kraken2/`, `fastp/`, and
`validation/`, takes the latest mtime per directory, and returns an
MD5 hash of the combined string. Module-level state at line 44
caches the last result; `get_last_freshness_fingerprint()` at
lines 321-329 reads it without rescanning.

The function is exported through `core/utils/data_loaders.py:24`
**but is never called by any callback**. It was added as the seed
for a centralised gate and has been sitting in the tree waiting
for a consumer. (Worker 3 verified the gap; I confirmed by `grep
-rn check_data_freshness app/` returning zero hits in the app
package.)

### 3.2 Proposed: a single `results-fingerprint` store

Worker 3's design (Section 3 of the event-driven proposal):

```python
# app.py layout
dcc.Store(id='results-fingerprint', data={"fp": "", "ts": 0})

# callbacks.py
@app.callback(
    Output("results-fingerprint", "data"),
    Input("update-interval", "n_intervals"),
    State("app-config", "data"),
    State("results-fingerprint", "data"),
)
def compute_results_fingerprint(n_intervals, config, prev):
    fp = check_data_freshness(main_dir)
    if fp == (prev or {}).get("fp"):
        raise PreventUpdate    # downstream callbacks do not fire
    return {"fp": fp, "ts": time.time()}
```

Data-bound callbacks then change their `Input` from
`update-interval` to `results-fingerprint`. When no file under the
scanned directories has changed, the store value never updates and
Dash skips every downstream callback's body.

The cost of the gate itself is roughly four `os.scandir` calls plus
one MD5 -- microseconds at the scale of one nanometanf run.

### 3.3 Two real correctness issues with the as-shipped freshness check

**(a) `seqkit/` is missing from the scan list.**
`loader_utils.py:304` iterates over `("kraken2", "fastp",
"validation")`. Chopper and Filtlong runs publish QC stats to
`seqkit/` (per the project CLAUDE.md QC layout note and confirmed
by `qc_analysis/main.nf:202-212`). With Chopper as the default QC
tool (`nextflow.config:120`), QC-only changes will not bump the
fingerprint. One-line fix: add `"seqkit"` to the tuple.

**(b) `on_demand_validation/` is a separate directory.**
The CLAUDE.md output-format section documents
`{outdir}/on_demand_validation/{sample}_{taxid}_ondemand.paf` as a
distinct location. After the 2026-04-30 refactor that delegates
on-demand validation to nanometanf with `--validation_only` (per
the CLAUDE.md "On-Demand Validation" section), results may also
land under `validation/validation_results.json` for the same run,
so coverage of `validation/` is enough for the canonical path. But
operators on the legacy local-subprocess fallback still get output
in `on_demand_validation/`, and that path is invisible to the
freshness check. Either include the directory in the scan or make
sure all on-demand callers route through the nanometanf path.

### 3.4 Callbacks that legitimately must keep wall-clock firing

Worker 3 lists these and the synthesis agrees (event-driven
proposal Section 6):

- `update_elapsed_time` -- ticks from `countdown-tick`, by design.
- `update_live_indicator` -- displays "Updated: HH:MM:SS"; advances
  on every tick.
- `update_stale_data_warning` / `track_last_update_time` -- staleness
  detection requires firing when data is **not** changing.
- `update_data_freshness` Stage Strip badge -- "Last updated
  HH:MM:SS"; same reason.
- `update_backend_status` -- polls `BackendManager.get_status()`,
  which is independent of result files (it monitors the Nextflow
  process).
- `update_available_samples` -- detects new barcodes appearing
  mid-run; already short-circuits via the equality check at
  `callbacks.py:596-598`.
- `update_readiness_indicator` -- monitors tool/DB availability,
  which is independent of result files. Should still be cached
  separately (see Section 4 P1 below) but not gated on the data
  fingerprint.

These keep `Input("update-interval", ...)`. Everything else in the
data-bound list moves to `Input("results-fingerprint", "data")`.

---

## 4. Recommendations, risk-ranked and sequenced

The thing the frontend audit and the event-driven proposal both
gesture at -- but neither finishes -- is the fact that the
file-mtime fingerprint **is** nanometanf's output cadence. The
backend writes `kraken2/{sample}.cumulative.kraken2.report.txt`
roughly once per 5 batches per sample
(`taxonomic_classification/main.nf:248`,
`report_write_interval = 5`). When that file's mtime advances the
dashboard genuinely has new data; when it does not, it does not.
Hashing those mtimes is therefore a faithful proxy for nanometanf's
"a new batch landed" event, and the gate proposed in Section 3 is
the correct shape.

The sequenced plan below runs from highest-impact and
lowest-risk to lower-impact and higher-risk.

### Phase A -- Wire the fingerprint gate (do this first)

**A1. Extend `check_data_freshness` to scan `seqkit/`.**
File: `core/utils/loader_utils.py:304`. One-line change. Risk: nil
(adds a directory to a glob; does not remove any existing
behaviour). Time: 15 min including a unit test.

**A2. Add the `results-fingerprint` Store and `compute_results_fingerprint`
callback.** Files: `app/app.py` (one Store declaration in the
layout), `app/callbacks.py` (one new callback). Additive only.
Risk: nil -- no existing callback is touched. Time: 1 hour.

**A3. Migrate the highest-cost data callbacks to consume the Store.**
Switch `Input("update-interval", "n_intervals")` to
`Input("results-fingerprint", "data")` in:

1. `compute_overall_status_cache` (`dashboard_tab.py:118`)
2. `update_pathogen_alert_panel` (`dashboard_tab.py:605`)
3. `update_verdict_banner` (`dashboard_tab.py:163`) -- and at the
   same edit, fix the bug at `dashboard_tab.py:237` that re-calls
   `load_kraken_data` instead of reading
   `dashboard-overall-status-cache` State.
4. `update_main_results` (`main_tab.py:297`) -- also add
   `prevent_initial_call=True` here while you are touching it.
5. The seven QC callbacks
   (`qc_tab.py:228, 458, 806, 847, 960, 1078, 1252`).
6. `update_classification_plot` (`classification_tab.py:122`).
7. `load_validation_data` (`validation_tab.py:314`).

That is 15 callbacks. Each migration is a one-line `Input` change
and is independently revertible. Run `pytest tests/` after each
group. The synthetic dataset tests in
`test_frontend_integration.py` and
`test_visualization_integration.py` exercise the end-to-end render
pipeline and will catch the obvious regressions. Time: 4-6 hours
across two sessions.

After Phase A: when no kraken2/seqkit/fastp/validation file has
changed since the last tick, **zero data callbacks fire**. The
worst-offender ranking in Section 2.2 collapses to the wall-clock
group only.

### Phase B -- Eliminate the 1 Hz server clock

**B1. Convert `update_elapsed_time` to clientside.** File:
`app/callbacks.py:879-913` (server callback removed),
`app/app.py:653` (existing clientside countdown extended). The
clientside callback already has `backend-status` as Input; add
`elapsed-time-display` to its Outputs and compute the elapsed
string from `backend_status.start_time` using `Date.now()`. Time:
1 hour. Risk: low (purely a code move; there is one fewer server
round-trip per second).

**B2. Disable `countdown-tick` when no run is active.** Add a
clientside callback that writes
`{"disabled": !backend_status.running}` to the interval's
`disabled` prop. Time: 30 minutes. Risk: low.

### Phase C -- AgGrid `Patch()` for the visible-flicker tables

**C1.** `update_per_sample_table` (`qc_tab.py:807`) and
`update_dashboard_sample_table` (`dashboard_tab.py:507`) -- both
keyed by `sample` -- are the lowest-risk transitions because the
key is unique and stable, and these tables are the most visible
ones to operators during active runs. Pattern in worker 1 audit
Section 6.

**C2.** `update_main_results` writes to `detailed-organism-table`
keyed by `taxid` (`main_layout.py:286`). After Phase A this
callback no longer fires on unchanged ticks, so `Patch()` is more
about preserving sort/filter/scroll state when new data **does**
arrive. Higher value once an operator is actively interacting with
the table mid-run. Convert in a second pass, with manual UI
verification.

**C3.** `update_blast_table` is lowest priority -- validation
results load on operator demand, not on every tick.

### Phase D -- Clean up the always-on syscall sources

**D1. Cache `ReadinessChecker.check_readiness`.**
`callbacks.py:438`. Cache the `ReadinessReport` against an
`(app-config._version, mtime_of_nanometa_home)` fingerprint with a
60 s minimum TTL, or remove `update-interval` from the Inputs and
trigger only from `app-config` data changes. The result changes
only when an operator installs a tool or edits a path. Time: 1
hour. Risk: low.

**D2. Cache or gate `update_available_configs`.**
`config_tab.py:107`. Same shape as D1; the config list changes only
when the operator saves or loads a configuration. Time: 30 min.

**D3. Convert `run_rescan` to `background=True`.**
`preparation_tab.py:699`. Loads the Kraken2 DB index and runs
fuzzy mapping against the watchlist; can block the Flask worker
for 5-30 s. Pattern matches `download_missing_genomes` already at
line 954. Time: 1 hour. Risk: medium (background callbacks have
slightly different semantics; test on the staging dataset).

### Phase E -- Backend cadence fix

**E1. Implement `BatchUtils.batchWithTimeout` for real.**
File: `lib/BatchUtils.groovy:28`. The schema documents a
`batch_timeout` parameter (`nextflow_schema.json:317-323`) and the
default of 60 s implies "a partial batch will be flushed if no new
files arrive within 60 s." Today this argument is silently ignored
(line 28 ignores `timeoutSeconds` and just returns
`buffer(size: batchSize, remainder: true)`). Two consequences:

- Low-throughput single-barcode runs sit at 0/10 forever and never
  produce a Kraken2 report until the idle timeout fires.
- The dashboard's "monitoring is happening" feel is bound entirely
  to whatever time it takes to fill `batch_size` files, not to
  `batch_timeout`.

A correct implementation needs a Nextflow-idiomatic flushing
operator. Worker 3's proposal does not address this; it is purely
a backend issue. Possible approaches:

  - Use `groupTuple(remainder: true)` keyed by a
    time-window-derived bucket (file mtime rounded down to
    `batch_timeout`). Coarser, but no extra dependencies.
  - Use the GPars `DataflowReadChannel.timer(...)` operator from
    inside a custom operator wrapper that emits a flush sentinel
    every `batch_timeout` seconds, similar to the existing
    `realtime_timeout_minutes` daemon-`Timer` pattern at
    `realtime_monitoring/main.nf:167-176`. That pattern is already
    in the codebase and proven to work with `DataflowQueue.bind`
    plus `mix`.

This is more involved than Phase A-D and should be sequenced
last. Risk: medium-high (touches the streaming hot path; all
existing real-time tests need to pass). Time: 1-2 days including
new nf-tests.

### What I would do tomorrow

If Andreas has a single afternoon: **do Phase A1 + A2 + A3 only.**
That is one new file scan in the freshness check, one new
`dcc.Store`, one new callback in `callbacks.py`, and 15
one-line `Input` swaps. After it ships, on every 30 s tick where
no Nextflow output file has been touched, zero data callbacks
execute. That is the change with the highest ratio of
operator-visible-improvement to risk-and-effort. Phase B (the 1 Hz
clientside conversion) is a natural follow-up the next day.
Phases C-E can be sequenced over the next sprint.

---

## 5. What this synthesis did NOT verify

- Per-callback runtime cost numbers. Worker 1's frontend audit
  ranked callbacks by file I/O volume and syscall count, which is
  a reasonable proxy, but no profiler run was performed.
- The exact mtime-update behaviour of
  `*.cumulative.kraken2.report.txt` under a real production run
  with multiple barcodes and `report_write_interval = 5`. The
  source at `taxonomic_classification/main.nf:298-307` does an
  atomic temp-then-rename, which on POSIX should advance the
  parent directory's mtime (good for `check_data_freshness`); on
  some networked filesystems this is not guaranteed. Not verified
  on Andreas's deployment targets.
- The macOS Java NIO `WatchService` reliability concern noted at
  `realtime_monitoring/main.nf:106-109` is documented in code but
  the impact on dashboard cadence specifically (as opposed to
  pipeline cadence) is not measured here.
- Whether the on-demand `nextflow run --validation_only` path
  writes its outputs with mtimes that bump the `validation/`
  directory mtime in a way `check_data_freshness` will pick up.
  Likely yes (the aggregator rewrites
  `validation/validation_results.json`) but not directly verified.

---

## 6. File index for the recommended changes

| Phase | File | Change |
|---|---|---|
| A1 | `core/utils/loader_utils.py:304` | Add `"seqkit"` to subdir tuple |
| A2 | `app/app.py` (layout) | Add `dcc.Store(id='results-fingerprint', ...)` |
| A2 | `app/callbacks.py` | Add `compute_results_fingerprint` callback |
| A3 | `app/tabs/dashboard_tab.py:118, 163, 605` | Switch to fingerprint Input |
| A3 | `app/tabs/dashboard_tab.py:237` | Remove direct `load_kraken_data`; use cache State |
| A3 | `app/tabs/main_tab.py:297` | Switch + add `prevent_initial_call=True` |
| A3 | `app/tabs/qc_tab.py:228..1252` | Switch 7 callbacks |
| A3 | `app/tabs/classification_tab.py:122` | Switch |
| A3 | `app/tabs/validation_tab.py:314` | Switch |
| B1 | `app/callbacks.py:879-913` | Delete server callback |
| B1 | `app/app.py:653` | Extend clientside countdown |
| B2 | `app/app.py` | Add `disabled` clientside writer for `countdown-tick` |
| C1 | `app/tabs/qc_tab.py:807` | `Patch()` row update |
| C1 | `app/tabs/dashboard_tab.py:507` | `Patch()` row update |
| C2 | `app/tabs/main_tab.py:301` | `Patch()` row update |
| D1 | `app/callbacks.py:438` | Cache `ReadinessReport` |
| D2 | `app/tabs/config_tab.py:107` | Cache config list |
| D3 | `app/tabs/preparation_tab.py:699` | `background=True` |
| E1 | `lib/BatchUtils.groovy:28` (nanometanf) | Implement real timeout flush |
