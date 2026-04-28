# Implementation Plan -- Throughput Fixes for 12-24 Barcode Runs

Source: `docs/audit-2026-04-28-throughput-{gui,ux,synthesis}.md`.
4 P0s, 16 P1s. This plan groups them by the smallest set of code
changes that closes the most P0/P1s, ordered by clinical-safety risk
first, then throughput risk.

The audit predicted 5-15s GUI freezes per tick at 24 barcodes plus a
clinical-misleading "+N more" pill that hides which of 24 barcodes
triggered a critical pathogen alert. Wave 1 closes both classes in two
focused PRs.

## Wave 1 -- P0 closure (high priority, ~1 day total)

### W1-A. Centralize "All Samples" Kraken2 loading via shared store

**Closes:** P0-G01 (5 redundant `load_kraken_data(..., "All Samples")`
calls per tick), P0-G02 (24-iteration serial per-sample loop in dashboard
pathogen alert), and P1-T07 (re-load on sample switch).

**Files to modify:**
- `nanometa_live/app/app.py` -- add new `dcc.Store(id="aggregate-kraken-cache")`
  and `dcc.Store(id="per-sample-kraken-cache")` next to existing stores
- `nanometa_live/app/tabs/dashboard_tab.py:410, 777, 1566, 2006, 2027` --
  replace direct `load_kraken_data(main_dir, "All Samples")` calls with
  reads of `aggregate-kraken-cache` Store
- `nanometa_live/app/tabs/dashboard_tab.py` `_load_per_sample_organisms` --
  replace `for sample in samples: load_kraken_data(main_dir, sample)` with
  a single read of `per-sample-kraken-cache`
- New callback in `dashboard_tab.py` (single-writer): triggered by
  `update-interval`, populates both stores in one pass, with a guard
  that skips when `backend-status.running == False` and main_dir mtime
  has not advanced

**Approach:**
1. Single feeder callback: `Input("update-interval", "n_intervals"),
   State("app-config"), State("backend-status")` -> writes both stores
2. Feeder honours `mtime(kraken2_dir)` -- if unchanged since last tick,
   `raise PreventUpdate` (no store overwrite, no downstream re-render)
3. Feeder loads "All Samples" once and per-sample once, reusing the
   parsed DataFrame from "All Samples" filtered by sample column rather
   than re-parsing files
4. All consumer callbacks become readers of the stores

**Acceptance:** with 24 barcodes simulated by 24 mock kraken2 reports,
verify via `app.callback_map` inspection that no callback contains a
`load_kraken_data` call (except the new feeder). New test in
`tests/test_dashboard_aggregate_cache.py` confirming the feeder
short-circuits when mtime is stable.

**Estimate:** 4-6 hours including tests.

### W1-B. Make alert "+N more" pill expandable and add verdict-banner attribution

**Closes:** P0-T01 (non-interactive "+N more" pill), P0-T02 (verdict
banner does not name triggering samples).

**Files to modify:**
- `nanometa_live/app/components/pathogen_alert.py:69-112` -- replace the
  non-interactive `+N more` `Span` with a `dbc.Button` (or Popover) that
  opens a modal listing every triggering sample with reads + abundance
- `nanometa_live/app/components/pathogen_alert.py` -- new helper
  `_render_sample_attribution_modal(samples)` rendering the full list
- `nanometa_live/app/tabs/dashboard_tab.py:425-443` -- when verdict is
  ACTION REQUIRED, append a subhead "Triggered by: barcode13 (+2 more)"
  with the same expandable affordance as the chip pill (top-3 names + a
  click-to-see-all link)
- `nanometa_live/app/components/dashboard_*` -- ensure the verdict
  banner has slot for the subhead at small viewports too

**Approach:**
1. Extend the existing `_render_sample_attribution()` return shape with
   an Attached `dcc.Modal` containing every sample's chip
2. The "+N more" Button's `id` becomes a pattern-matching `{"type":
   "alert-attribution-show-all", "alert_id": <pathogen_taxid>}`; modal
   open/close callback wires to it
3. For the verdict banner subhead: extend the alert-engine output
   shape to surface a `triggering_samples` list at the verdict level,
   not just per-pathogen. Wire it into the Zone 1 right-column slot.

**Acceptance:** Snapshot test rendering a 24-barcode pathogen-alert
case asserting modal opens with all 18 triggering samples enumerated.
Snapshot of verdict banner asserting "Triggered by:" subhead present.

**Estimate:** 3-5 hours.

## Wave 2 -- High-impact P1 throughput fixes (~1 day)

### W2-A. Replace direct `glob`/`open` callsites with `_fastp_cache` / loader cache

**Closes:** P1-T01 (`update_qc_plots` bypasses cache), P1-T04
(`_collect_samples_data` redundant per-barcode loads), P1-T06
(validation parser triple-rescan).

**Files:**
- `nanometa_live/app/tabs/qc_tab.py` (callsites identified in P1-T01)
- `nanometa_live/app/tabs/dashboard_tab.py` (`_collect_samples_data`)
- `nanometa_live/core/parsers/blast_validation_parser.py` (rescan)

**Approach:** route all reads through `core/utils/loader_utils.py`'s
existing cached helpers. Where the cache key is too coarse, add a
mtime-fingerprint key.

**Estimate:** 3-4 hours.

### W2-B. Add LRU bound to `_debounce_timestamps` and one-tick guards

**Closes:** P1-T08 (unbounded debounce dict), P1-T03 (samples store
overwrite churn), P1-T09 (BackendManager `os.listdir` per tick).

**Files:**
- `nanometa_live/app/utils/debounce.py` -- add `functools.lru_cache` or
  a manual `OrderedDict` with `max_entries=512`
- `nanometa_live/app/callbacks.py` -- `update_available_samples` should
  short-circuit when sample list has not changed (compare hash of
  sorted list to State)
- `nanometa_live/core/workflow/backend_manager.py` -- cache file count
  with 5s TTL instead of recomputing each call

**Estimate:** 2-3 hours.

### W2-C. DiskcacheManager worker pool bump

**Closes:** P1-T05 (single-worker serializes prep + DB download).

**Files:**
- `nanometa_live/app/app.py` -- pass `workers=4` to `DiskcacheManager`
  constructor (one for prep, one for DB download, one for genome
  download, one slack)

**Approach:** trivial config change. Ensure tests for background
callback semantics still pass.

**Estimate:** 30 min.

## Wave 3 -- UI scaling P1s (~half day)

### W3-A. Sample selector + AgGrid pagination at scale

**Closes:** P1-U01 (sample selector not searchable), P1-U02 (Dashboard
table page size 8), P1-U03 (QC table page size 10).

**Files:**
- `nanometa_live/app/components/sample_selector.py` -- enable Dash
  `dcc.Dropdown(searchable=True)` plus a virtualized variant for >12
  entries; show "12 samples (search to filter)" placeholder
- `nanometa_live/app/layouts/dashboard_layout.py` -- AgGrid
  `paginationPageSize` from 8 -> dynamic based on sample count (12/24/48)
- `nanometa_live/app/layouts/qc_layout.py` -- same; also remove the fixed
  420px container height that clips 24-row tables

**Estimate:** 2-3 hours.

### W3-B. Classification filter defaults at 24-barcode scale

**Closes:** P1-U04 (`min_reads=10` and `max_taxa=10` are too narrow
for aggregated 24-barcode views).

**Files:**
- `nanometa_live/app/layouts/classification_layout.py` -- defaults
  scale by `len(available_samples)`: at >12 samples, raise
  `min_reads` to 50 and `max_taxa` to 25 to keep the figure readable

**Estimate:** 1 hour.

### W3-C. Coverage species selector grouping + result-card virtualization

**Closes:** P1-U06 (coverage species selector mixes species/sample
names), P1-U07 (BLAST/coverage card lists non-virtualized at ~120 cards).

**Files:**
- `nanometa_live/app/components/coverage_plots.py` -- group dropdown
  options by sample under `optgroup` headers
- `nanometa_live/app/tabs/validation_tab.py` -- replace the flat
  `html.Div([Card, Card, ...])` with `dash_ag_grid.AgGrid` virtualized
  list, or `dash_extensions.Pagination`. AgGrid is already a project
  dependency.

**Estimate:** 3-4 hours.

## Wave 4 -- Pipeline tuning + operator docs (~half day)

### W4-A. nanometanf executor + queue tuning

**Closes:** synthesis observation that `executor.queueSize` defaults
to 100 while 24 barcodes x `max_concurrent_batches=4` = 96 batches
in-flight (too tight).

**Files:**
- `/Users/andreassjodin/Code/nanometanf/nextflow.config` -- add explicit
  `executor { queueSize = 200 }` block
- `/Users/andreassjodin/Code/nanometanf/conf/modules.config:181` --
  parameterise the KRAKEN2 memory request on `params.kraken2_db_size_gb`
  (currently hardcoded 12.GB sized for MiniKraken2 dev DB; PlusPFP needs
  64+ GB)

**Estimate:** 1-2 hours including a small test confirming the param
flows through.

### W4-B. Operator-facing 24-barcode tuning guide

**Closes:** the "operators must know" gap from the synthesis (defaults
are conservative; operators with 16+ cores need to raise
`max_classification_forks` to 8 for memory-mapped DBs).

**Files:**
- `nanometa_live/docs/OPERATOR_GUIDE.md` -- new section "Tuning for
  high-throughput runs" with a table mapping host class to recommended
  `max_classification_forks`, `max_concurrent_batches`,
  `update_interval_seconds`, `pipeline_cores` settings
- `nanometa_live/docs/configuration.md` -- cross-link

**Estimate:** 1-2 hours.

## Wave 5 -- Empirical 12 / 24-barcode validation (operator-driven)

Reproduction script lives in `audit-2026-04-28-throughput-synthesis.md`.
Run after Waves 1-2 land. Report:
- Tick latency on cold and warm cache
- JVM and Python memory peaks
- Time from file arrival to dashboard pathogen alert
- Whether the verdict-banner attribution actually answers "which barcode?"

This wave is not coding work; it is acceptance testing. Drive it on the
target hardware where the pipeline will actually run.

## Out of scope for this cycle

- The fabricated nextflow-expert audit's claims that turned out to be
  wrong (Channel.watchPath missing, `--memory-mapping` not wired,
  KRAKEN2_KRAKEN2 unlabelled). All three are present and correct.
- conda-lock / pixi alternative to per-module `environment.yml` for
  cross-platform deployment -- separate concern, deferred from the
  earlier offline-deployment cycle.
- nf-core lint upstream tooling regression (master->main rename in
  nf-core/modules.git) -- needs nf-core CLI update, not our code.

## Sequencing recommendation

Do the waves in order:
1. **Wave 1** ships the two clinical-safety P0s in one PR per item.
   These are the closest to "user could make a wrong decision".
2. **Wave 2** ships the throughput P1s in one consolidated PR; tests
   should show a measurable per-tick latency drop.
3. **Wave 3** ships the UI P1s; ideally paired with Wave 5 acceptance
   testing on a real 24-barcode dataset to validate visual choices.
4. **Wave 4** ships the small pipeline tuning + operator docs.
5. **Wave 5** is the empirical validation -- after 1-4 land.

Total estimated effort: 2-3 working days for waves 1-4. Wave 5 is
operator time only.

## Acceptance for the whole cycle

Re-run the throughput audit (or at least re-verify the audit's P0/P1
checklist against the post-fix code) and confirm:
- All 4 P0s closed (covered by tests)
- At least 12 of 16 P1s closed
- Synthesis rubric score moves from 67/100 to >= 82/100
- Empirical 24-barcode run shows tick latency < 2s warm, < 5s cold
