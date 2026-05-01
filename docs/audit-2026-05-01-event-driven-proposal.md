# Event-Driven Dashboard Refresh: Audit and Migration Proposal

**Date:** 2026-05-01
**Status:** Proposal — not yet implemented
**Scope:** `nanometa_live/app/` polling model; `nanometa_live/core/utils/loader_utils.py` and related caches

---

## 1. Existing Event-Driven Primitives

The codebase already contains several mechanisms for "data has changed" detection. These are documented below with verified file:line references before any new work is proposed.

### 1.1 `check_data_freshness` / `_last_freshness_fingerprint`

**File:** `nanometa_live/core/utils/loader_utils.py`, lines 287–318

`check_data_freshness(main_dir)` scans `kraken2/`, `fastp/`, and `validation/` subdirectories, takes the latest file mtime from each, and returns an MD5 hex digest of the combined string. If the fingerprint is unchanged from the previous call, the data on disk is unchanged. The module also stores the last fingerprint in `_last_freshness_fingerprint` (line 44), accessible without a rescan via `get_last_freshness_fingerprint()` (lines 321–329).

This function is **defined and exported** but, as of the current codebase, is **not called by any callback**. It is re-exported through `nanometa_live/core/utils/data_loaders.py` (line 24) but no tab calls it. It was built for exactly the use case described in this proposal — a centralized gate — and is ready to use.

### 1.2 Per-loader mtime/size cache (`_file_mtimes`, `_check_mtime_cache`, `_store_mtime_cache`)

**File:** `nanometa_live/core/utils/loader_utils.py`, lines 42–43, 249–284

Every call to `load_kraken_data` first checks `_check_mtime_cache(mtime_key, [kraken_dir])` (classification_loaders.py lines 360–363, 382–385). If the kraken2 directory's mtime and total size are identical to the stored values, the cached DataFrame is returned without any file parsing. The same pattern is used for per-sample loads at lines 741, 765. The mtime/size pair is computed by `_get_path_fingerprint` (lines 214–246), which scans directory entries.

### 1.3 `ValidationParser` per-instance mtime cache

**File:** `nanometa_live/core/parsers/blast_validation_parser.py`, lines 206–208, 495–550

`ValidationParser._validation_dir_fingerprint()` computes the latest mtime under `validation_dir`. `get_validation_results()` compares this fingerprint against `_results_cache_mtime` and returns the cached list when unchanged. This eliminates the triple file-walk (has_validation_data + get_validation_results + get_validation_summary) per tick.

### 1.4 `should_skip_update` debounce

**File:** `nanometa_live/app/utils/debounce.py`, lines 30–84

A thread-safe, bounded (512-key) dict of last-call timestamps. Callbacks call `should_skip_update(id, debounce_ms=2000)` at the top and raise `PreventUpdate` if called again within the threshold. This is already deployed in: `compute_overall_status_cache`, `update_verdict_banner`, `update_quality_card`, `update_pathogen_alert_panel`, `update_data_freshness`. The 2000 ms threshold means, in the worst case, a 30-second interval callback still executes once at the beginning of each tick.

### 1.5 `aggregate-kraken-cache` and `per-sample-kraken-cache` stores

**File:** `nanometa_live/app/app.py`, lines 248–249

Two `dcc.Store` components carry `{"fingerprint": str, ...data...}`. The comment at lines 237–249 explicitly names `fingerprint` as "mtime hash; used for change detection." The dashboard feeder callback (`compute_overall_status_cache`, dashboard_tab.py lines 107–138) populates `dashboard-overall-status-cache`, and downstream callbacks (`update_dashboard_metrics`, `update_dashboard_sample_table`, `update_dashboard_alerts`) input that store rather than `update-interval` directly. This is a partial implementation of the fingerprint-gate pattern: the dashboard zone-2/3/4 callbacks do not fire on the interval tick at all; they fire only when the cache store changes value.

### 1.6 `update_available_samples` short-circuit

**File:** `nanometa_live/app/callbacks.py`, lines 596–598

After detecting samples, the callback compares `new_samples == prev_samples and new_mapping == prev_mapping` and raises `PreventUpdate` when equal. This prevents cascading store-overwrite re-renders at every tick when samples do not change.

### Summary of existing primitives

| Mechanism | Location | What it detects | Currently wired to callbacks? |
|-----------|----------|-----------------|-------------------------------|
| `check_data_freshness` | loader_utils.py:287 | kraken2/fastp/validation dir mtime change | No — exported but unused in callbacks |
| Per-loader mtime cache | loader_utils.py:249 | Individual dir mtime+size | Yes — inside every `load_kraken_data` call |
| `ValidationParser` instance cache | blast_validation_parser.py:495 | validation dir mtime | Yes — inside each `get_validation_results` call |
| `should_skip_update` debounce | debounce.py:30 | Wall-clock time since last execution | Yes — several dashboard callbacks |
| Fingerprint stores (aggregate-kraken-cache) | app.py:248 | Populated per tick; downstream callbacks react | Partial — dashboard zone 3/4 only |
| Sample list equality check | callbacks.py:596 | Structural equality of sample list | Yes — prevents downstream cascade |

---

## 2. Identified Callback Count

From `grep` across all tab files and `callbacks.py`, the following direct subscriptions to `Input("update-interval", "n_intervals")` are present:

**callbacks.py (8 subscriptions):**
- `initialize_taxid_mappings` (line 98)
- `update_backend_status` (line 177)
- `update_readiness_indicator` (line 435)
- `update_available_samples` (line 555)
- `update_live_indicator` (line 657)
- `update_stale_data_warning` (line 706)
- `track_last_update_time` (line 743)
- (one other at line 657)

**dashboard_tab.py (5 subscriptions):**
- `compute_overall_status_cache` (line 110)
- `update_verdict_banner` (line 153)
- `update_quality_card` (line 374)
- `update_pathogen_alert_panel` (line 596)
- `update_data_freshness` (line 967)

**Other tabs (9 subscriptions):**
- main_tab.py: 2 (lines 310, 994)
- qc_tab.py: 7 (lines 236, 472, 809, 850, 960, 1081, 1253)
- classification_tab.py: 1 (line 129)
- validation_tab.py: 1 (line 318)
- config_tab.py: 1 (line 104)

**Total: approximately 24 direct interval subscribers.** All fire on every 30-second tick regardless of whether any output file on disk has changed.

---

## 3. Smallest Change with Highest Impact: `results-fingerprint` Store

### Design

Add a single new `dcc.Store` to `app.py`:

```python
dcc.Store(id='results-fingerprint', data={"fp": "", "ts": 0})
```

Register one new callback in `callbacks.py` (not in any tab) that is the **only** direct consumer of `update-interval`:

```python
@app.callback(
    Output("results-fingerprint", "data"),
    Input("update-interval", "n_intervals"),
    State("app-config", "data"),
    State("results-fingerprint", "data"),
)
def compute_results_fingerprint(n_intervals, config, prev):
    from nanometa_live.core.utils.loader_utils import check_data_freshness
    main_dir = (config or {}).get("results_output_directory") or (config or {}).get("main_dir", "")
    if not main_dir:
        raise PreventUpdate
    fp = check_data_freshness(main_dir)
    if fp == (prev or {}).get("fp"):
        raise PreventUpdate      # data unchanged -- downstream callbacks do not fire
    import time
    return {"fp": fp, "ts": time.time()}
```

Data-bound callbacks then switch their `Input` from `update-interval` to `results-fingerprint`:

```python
# Before:
Input("update-interval", "n_intervals"),
# After:
Input("results-fingerprint", "data"),
```

When no file has changed, `compute_results_fingerprint` raises `PreventUpdate`, and the store value does not change, so Dash does not invoke any downstream callback. The downstream callbacks execute zero Python on unchanged ticks.

`check_data_freshness` costs approximately 3 `os.scandir` calls (one each for `kraken2/`, `fastp/`, `validation/`) plus one MD5 hash. At 24 barcodes with ~5 files per directory this is on the order of microseconds — negligible compared to the parsing it replaces.

### Correctness note on `seqkit/`

`check_data_freshness` currently scans `kraken2/`, `fastp/`, and `validation/` (loader_utils.py line 305). For runs where `qc_tool: chopper` is configured, QC output lands in `seqkit/`, not `fastp/`. The function should be extended to also scan `seqkit/` so that QC-only changes are not missed:

```python
for subdir in ("kraken2", "fastp", "seqkit", "validation"):
```

This is a one-line change inside `loader_utils.py` and does not affect any caller's interface.

---

## 4. Risk Assessment

### 4.1 False negatives (missed updates)

**Risk:** A file write that does not advance the directory mtime would be invisible to `check_data_freshness`.

**Conditions where this can occur:**
- An atomic rename (e.g. Nextflow's `.command.out` swap) that lands at an mtime already equal to the stored value. In practice this requires two separate writes within the same filesystem timestamp resolution (1 second on most Linux/macOS), which is rare for Nextflow's batch-writing pattern.
- New subdirectories appearing (e.g. `on_demand_validation/`) whose parent is not scanned. Mitigation: extend the scanned subdirectory list or scan one level deeper.

**Rollback:** If a false negative is observed in production, raise the interval from 30 s to 10 s and add `os.utime` instrumentation to identify the write pattern before reverting the fingerprint gate.

**Severity:** Low for the primary use case. The loader-level mtime cache (`_check_mtime_cache`) already assumes the same invariant; the fingerprint store merely moves the detection one level up.

### 4.2 False positives (unnecessary re-render)

**Risk:** A file in `validation/` is touched (e.g. a lock file, `.nextflow/` trace entry) without new classification data, causing all data callbacks to re-run.

**Mitigation:** The downstream callbacks still hit the loader-level mtime cache on re-entry. If the kraken2 directory itself has not changed, `load_kraken_data` returns the cached DataFrame in O(stat) time, and the callback completes in microseconds before building any Plotly figure. False positives at the fingerprint gate result in fast no-op executions, not full re-parses.

**Severity:** Very low due to the inner mtime cache.

### 4.3 Callbacks that do not use `results-fingerprint`

Several callbacks should **not** migrate to `results-fingerprint` because they need wall-clock firing regardless of data changes (see Section 6). They continue to subscribe to `update-interval` directly.

### 4.4 Incremental rollout risk

Each callback migration is independent: switching one callback's Input from `update-interval` to `results-fingerprint` does not affect any other callback. Rollback is a one-line Input change. No coordinated deployment is required.

---

## 5. Implementation Order (Phased Rollout)

### Phase 1 — Core fingerprint store (1 person, ~2 hours)

1. Extend `check_data_freshness` to include `seqkit/` in its scan list (`loader_utils.py` line 305). Write a unit test.
2. Add `dcc.Store(id='results-fingerprint', ...)` to `app.py` layout.
3. Add `compute_results_fingerprint` callback in `callbacks.py`. This callback is the only new interval subscriber; it raises `PreventUpdate` when the fingerprint is unchanged.
4. Verify the store changes value when a test Kraken2 report is touched.

**Risk:** None — the callback is additive. No existing callback is modified.

### Phase 2 — Migrate highest-cost data callbacks (~4 hours)

Migrate the following callbacks to `Input("results-fingerprint", "data")` in order of measured cost (file I/O volume):

1. `compute_overall_status_cache` (dashboard_tab.py:107) — calls `_calculate_overall_status` which calls `load_kraken_data` for all samples.
2. `update_pathogen_alert_panel` (dashboard_tab.py:596) — calls `load_kraken_data` + `_load_per_sample_organisms` (per-sample loop).
3. `update_verdict_banner` (dashboard_tab.py:153) — calls `load_kraken_data`.
4. Main tab organism callbacks (main_tab.py:310, 994) — call `load_kraken_data`.
5. QC tab callbacks (qc_tab.py:236, 472, 809, 850, 960, 1081, 1253) — call `load_nanoplot_stats`, `get_qc_stats`.
6. Classification tab sunburst/sankey callback (classification_tab.py:129) — calls `load_kraken_data`.
7. Validation tab callback (validation_tab.py:318) — calls `ValidationParser.get_validation_results`.

For each migration: change `Input("update-interval", "n_intervals")` to `Input("results-fingerprint", "data")` and rename the parameter from `n_intervals` to `fingerprint_data` (or keep as `_` if unused). Remove any `should_skip_update` debounce guard that was compensating for the always-firing interval, unless the callback also has legitimate user-action inputs that need debounce.

**Effort estimate:** 30–60 minutes per callback group; 7 groups. Total: 4–6 hours, easily split across two sessions.

**Testing:** Run the test suite (`pytest tests/ -v`) after each group. The synthetic dataset tests in `test_frontend_integration.py` and `test_visualization_integration.py` exercise the callback pipeline end-to-end.

### Phase 3 — Optional clientside fingerprint pre-check (~2 hours)

Once Phase 2 is complete, a clientside callback can be added to suppress server round-trips for the cheapest callbacks (live indicator, stale-data warning) when the fingerprint has not changed. This is pure upside — the server callbacks already do minimal work — and can be deferred indefinitely if Phase 2 delivers sufficient gain.

---

## 6. Callbacks That Must NOT Migrate

The following callbacks should continue to subscribe to `update-interval` directly because they provide time-dependent UI feedback that must update on every tick regardless of whether any pipeline output file has changed.

| Callback | File:line | Reason |
|----------|-----------|--------|
| `update_elapsed_time` | callbacks.py:879 | Ticks from `countdown-tick` (1 s interval), not `update-interval`; already correct |
| `update_live_indicator` | callbacks.py:649 | Displays "Updated: HH:MM:SS" wall clock; must advance on every tick |
| `track_last_update_time` / `update_stale_data_warning` | callbacks.py:741, 703 | Stale-data detection requires wall-clock comparison; must fire even when data is unchanged to detect staleness |
| `update_data_freshness` badge | dashboard_tab.py:967 | Displays "Last updated HH:MM:SS" in Stage Strip; must advance every tick |
| `update_backend_status` | callbacks.py:176 | Polls `BackendManager.get_status()` which monitors the Nextflow process; must fire even when no files have changed |
| `update_available_samples` | callbacks.py:550 | Detects new barcodes appearing mid-run; already short-circuits on equality |
| `update_readiness_indicator` | callbacks.py:428 | Monitors tool/DB availability which can change independently of result files |
| `initialize_taxid_mappings` | callbacks.py:93 | Runs once on first tick; already gated by `config.get("_taxid_mapping_initialized")` |
| `update_countdown` | app.py (clientside) | Pure JS time display; already on `countdown-tick` |
| `config_tab` config-file watcher | config_tab.py:104 | Monitors external config file changes, not pipeline output |

---

## 7. Architecture After Phase 2

```
dcc.Interval (30 s)
       |
       v
compute_results_fingerprint
  check_data_freshness()        <-- 3-4 os.scandir calls, 1 MD5
       |
       | fingerprint unchanged?  --> PreventUpdate (store value not written)
       |                              --> NO downstream callback fires
       |
       | fingerprint changed?    --> write "results-fingerprint" store
                                      --> all data callbacks fire once
                                           |
                                           v
                                  load_kraken_data()
                                    _check_mtime_cache()   <-- O(stat)
                                    _parse_kraken_data_uncached()  <-- only when files changed
```

The two-level cache structure means: on a tick where the directory mtime did not advance at the filesystem level, `compute_results_fingerprint` raises `PreventUpdate` before any callback body runs. On a tick where files changed, all data callbacks run but the inner mtime cache still short-circuits individual file parses that have not changed since the previous successful parse.

---

## 8. Implementation Checklist

- [ ] Phase 1a: extend `check_data_freshness` to scan `seqkit/` (`loader_utils.py`:305)
- [ ] Phase 1b: add `dcc.Store(id='results-fingerprint', ...)` (`app.py` layout)
- [ ] Phase 1c: add `compute_results_fingerprint` callback (`callbacks.py`)
- [ ] Phase 1d: unit test for fingerprint change detection with mock directory
- [ ] Phase 2a: migrate `compute_overall_status_cache` (`dashboard_tab.py`:107)
- [ ] Phase 2b: migrate `update_pathogen_alert_panel` (`dashboard_tab.py`:596)
- [ ] Phase 2c: migrate `update_verdict_banner` (`dashboard_tab.py`:153)
- [ ] Phase 2d: migrate main tab organism callbacks (`main_tab.py`:310, 994)
- [ ] Phase 2e: migrate QC tab callbacks (7 callbacks in `qc_tab.py`)
- [ ] Phase 2f: migrate classification tab callback (`classification_tab.py`:129)
- [ ] Phase 2g: migrate validation tab callback (`validation_tab.py`:318)
- [ ] Phase 2h: run full test suite after each migration
- [ ] Phase 3 (optional): clientside pre-check for cheapest callbacks

---

## 9. Files Changed

| File | Change |
|------|--------|
| `nanometa_live/core/utils/loader_utils.py` | Add `seqkit` to `check_data_freshness` scan list |
| `nanometa_live/app/app.py` | Add `results-fingerprint` store to layout |
| `nanometa_live/app/callbacks.py` | Add `compute_results_fingerprint` callback |
| `nanometa_live/app/tabs/dashboard_tab.py` | Migrate 3 callbacks |
| `nanometa_live/app/tabs/main_tab.py` | Migrate 2 callbacks |
| `nanometa_live/app/tabs/qc_tab.py` | Migrate 7 callbacks |
| `nanometa_live/app/tabs/classification_tab.py` | Migrate 1 callback |
| `nanometa_live/app/tabs/validation_tab.py` | Migrate 1 callback |

Total: approximately 16 targeted one-line Input changes plus 1 new callback function (~20 lines) and 1 store declaration (~3 lines). No architectural changes to any loader, parser, or layout component.
