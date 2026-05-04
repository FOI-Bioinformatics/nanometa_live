# Audit: Update Frequency and Dash 4 Idiom Compliance

**Date:** 2026-05-01
**Scope:** `nanometa_live/app/` -- all tab callbacks, layouts, core callbacks, and supporting utilities
**Auditor:** Systematic code review (Claude Sonnet 4.6)

---

## 1. Interval Component Inventory

Two `dcc.Interval` components are declared in `nanometa_live/app/app.py` lines 260-273.
Neither is ever disabled by a callback; both fire unconditionally from page load.

### 1.1 `update-interval`

| Property | Value |
|---|---|
| id | `update-interval` |
| default interval | `config.get('update_interval_seconds', 30) * 1000` ms (default 30 000 ms) |
| disabled? | Never -- no callback writes to its `disabled` prop |
| declared at | `app/app.py:260` |
| subscriber count | **24 callbacks** |

**Subscribers (all files verified by grep):**

| File | Function | What it updates |
|---|---|---|
| `app/callbacks.py:177` | `update_backend_status` | `backend-status` store |
| `app/callbacks.py:438` | `update_readiness_indicator` | Readiness badge, popover, `readiness-state` store |
| `app/callbacks.py:560` | `update_available_samples` | `available-samples`, `sample-file-mapping` stores |
| `app/callbacks.py:661` | `update_live_indicator` | Live dot class, text, `last-update-display` |
| `app/callbacks.py:711` | `update_stale_data_warning` | `stale-data-warning` style |
| `app/callbacks.py:746` | `track_last_update_time` | `last-update-time` store |
| `app/callbacks.py:98` | `initialize_taxid_mappings` | `app-config`, `taxmap-*` stores (once only via guard) |
| `app/tabs/config_tab.py:107` | `update_available_configs` | `available-configs` children |
| `app/tabs/dashboard_tab.py:118` | `compute_overall_status_cache` | `dashboard-overall-status-cache` store |
| `app/tabs/dashboard_tab.py:163` | `update_verdict_banner` | Verdict banner children + style, elapsed time, run-state badge |
| `app/tabs/dashboard_tab.py:378` | `update_quality_card` | Dashboard quality card children |
| `app/tabs/dashboard_tab.py:605` | `update_pathogen_alert_panel` | Pathogen alert container |
| `app/tabs/dashboard_tab.py:973` | `update_data_freshness` | `dashboard-last-updated` store, badge |
| `app/tabs/main_tab.py:297` | `update_main_results` | Organism cards, summary, table rowData, watched-species section (9 outputs) |
| `app/tabs/main_tab.py:992` | `reload_on_demand_results` | `on-demand-validation-results` store (once-only guard) |
| `app/tabs/qc_tab.py:228` | `update_qc_plots` | 4 QC figures |
| `app/tabs/qc_tab.py:458` | `update_qc_stats` | 7 QC stat text outputs |
| `app/tabs/qc_tab.py:806` | `update_per_sample_table` | `per-sample-table` rowData |
| `app/tabs/qc_tab.py:847` | `update_base_quality_card` | Base-quality card children |
| `app/tabs/qc_tab.py:960` | `update_read_statistics_card` | Read statistics card children |
| `app/tabs/qc_tab.py:1078` | `update_stage_strip` | QC stage strip children |
| `app/tabs/qc_tab.py:1252` | `update_qc_action_guidance` | QC action guidance children |
| `app/tabs/classification_tab.py:122` | `update_classification_plot` | Sankey/Sunburst figure, info message, style |
| `app/tabs/validation_tab.py:314` | `load_validation_data` | `validation-data-store` store |

### 1.2 `countdown-tick`

| Property | Value |
|---|---|
| id | `countdown-tick` |
| interval | 1 000 ms (fixed) |
| disabled? | Never |
| declared at | `app/app.py:268` |
| subscriber count | **2 callbacks** |

**Subscribers:**

| File | Function | What it updates |
|---|---|---|
| `app/callbacks.py:884` | `update_elapsed_time` | `elapsed-time-display` children, `elapsed-time-container` style |
| `app/app.py:653` (clientside) | countdown clientside callback | `update-countdown` children (next-tick display) |

The elapsed-time server callback fires every second unconditionally. It reads `backend-status` from a Store (no disk I/O) and formats a timedelta string, so the per-call cost is low. However it fires even when no run is active, wasting one round-trip per second. The clientside sibling is appropriately free of server cost.

---

## 2. Polling Load Catalogue

### 2.1 Caching status per loader

| Loader / function | Cache type | Cache location |
|---|---|---|
| `load_kraken_data` | mtime+size fingerprint (`_check_mtime_cache`) | `loader_utils._file_mtimes` (process-level dict, thread-safe) |
| `load_fastp_per_sample` | mtime cache | `loader_utils._file_mtimes` |
| `load_nanoplot_stats` | mtime cache | `loader_utils._file_mtimes` |
| `get_qc_stats` | mtime cache | `loader_utils._file_mtimes` |
| `check_data_freshness` | scans kraken2/, fastp/, validation/ dirs | returns MD5 of mtimes; side-effect: cleans `_file_mtimes` if stale |
| `ReadinessChecker.check_readiness` | **no cache** | runs `shutil.which` / `os.stat` on every call |
| `ConfigLoader.get_available_configs` | **no cache** | scans `~/.nanometa/configs/` on every call |
| `get_available_samples` / `get_sample_file_mapping` | PreventUpdate short-circuit in `update_available_samples` if list unchanged | process-level comparison in `app/callbacks.py:596` |

Key observation: `loader_utils.CACHE_TTL_SECONDS = 30` (line 24). With the default 30 s polling interval the TTL equals the interval, so the cache has minimal value at default settings. The mtime/size fingerprint path (`_check_mtime_cache`) provides genuine savings because it short-circuits the full re-parse when files have not changed.

### 2.2 Store-based result caching

`dcc.Store` caching is used in three places:

1. `aggregate-kraken-cache` and `per-sample-kraken-cache` (`app.py:248-249`): declared as shared Kraken2 result caches, but inspection of `dashboard_tab.py` shows `update_verdict_banner` calls `load_kraken_data` directly (line 237) rather than reading from these stores. The stores are therefore written but not consumed by the verdict-banner callback.

2. `dashboard-overall-status-cache`: written by `compute_overall_status_cache` and consumed by `update_dashboard_metrics`, `update_dashboard_sample_table`, and `update_dashboard_alerts`. This is the correct pattern and works well.

3. `validation-data-store`: written by `load_validation_data` (validation_tab.py:314) and consumed as State by `update_verdict_banner` (dashboard_tab.py:159). Correct pattern.

### 2.3 `should_skip_update` debounce gate usage

| Callback | Guard present? | debounce_ms |
|---|---|---|
| `compute_overall_status_cache` | Yes | 2000 |
| `update_verdict_banner` | Yes (interval-trigger path only) | 2000 |
| `update_quality_card` | Yes | 2000 |
| `update_pathogen_alert_panel` | Yes | 2000 |
| `update_data_freshness` | Yes | 2000 |
| `update_qc_plots` | Yes (interval-trigger path only) | 2000 |
| `update_qc_stats` | Yes (interval-trigger path only) | 2000 |
| `update_per_sample_table` | Yes (interval-trigger path only) | 2000 |
| `update_base_quality_card` | Yes (interval-trigger path only) | 2000 |
| `update_read_statistics_card` | Yes (interval-trigger path only) | 2000 |
| `update_stage_strip` | Yes (interval-trigger path only) | 2000 |
| `update_qc_action_guidance` | Yes (interval-trigger path only) | 2000 |
| `update_classification_plot` | Yes (interval-trigger path only) | 2000 |
| **`update_main_results`** | **No** | -- |
| **`update_backend_status`** | **No** | -- |
| **`update_readiness_indicator`** | **No** | -- |
| **`update_available_samples`** | No (uses PreventUpdate on equal result) | -- |
| **`update_live_indicator`** | **No** | -- |
| **`update_stale_data_warning`** | **No** | -- |
| **`track_last_update_time`** | **No** | -- |
| **`update_available_configs`** | **No** | -- |

---

## 3. Dash 4 Idiom Compliance

### 3.1 AgGrid `rowData` full-replacement vs `Patch()`

All four AgGrid tables with `getRowId` configured still write full `rowData` replacements on every poll tick. No `Patch()` usage exists anywhere in the application (confirmed: `grep -rn "Patch()" app/` returns zero results).

| Table id | getRowId | Callback writing rowData | Can use Patch()? |
|---|---|---|---|
| `detailed-organism-table` | `params.data.taxid` (`main_layout.py:286`) | `update_main_results` (`main_tab.py:301`) | Yes -- rows keyed by taxid; append/update semantics are safe |
| `per-sample-table` | `params.data.sample` (`qc_layout.py:315`) | `update_per_sample_table` (`qc_tab.py:807`) | Yes -- rows keyed by sample name |
| `dashboard-sample-table` | `params.data.sample` (`dashboard_layout.py:334`) | `update_dashboard_sample_table` (`dashboard_tab.py:507`) | Yes -- rows keyed by sample name |
| `blast-stats-table` | `params.data.species + '||' + params.data.sample_id` (`validation_layout.py:279`) | `update_blast_table` (`validation_tab.py:637`) | Yes -- composite key is stable per species+sample pair |

Because all four tables have stable `getRowId` expressions, `Patch()` row-level updates would preserve sort order, filter state, and scroll position across interval ticks. The transition is especially impactful for `detailed-organism-table` (driven by `update_main_results` which has no debounce gate and re-renders 9 outputs every tick).

### 3.2 Callbacks that should be `background=True`

Preparation tab callbacks confirmed as `background=True` (lines 150, 965, 1267, 1756 of `preparation_tab.py`):
- `run_preparation` -- correct
- `download_missing_genomes` -- correct
- `build_missing_blast_dbs` -- correct
- Bundle export callback at line 1756 -- correct

**Not background, but potentially slow:**

| Callback | File:line | Why it may block |
|---|---|---|
| `run_rescan` | `preparation_tab.py:699` | Calls `mapper.load_database(kraken_db)` (reads Kraken2 DB index, can take several seconds on cold cache) then `mapper.generate_mappings()` (iterates all watchlist entries with fuzzy matching). Not marked `background=True`. |
| `import_bundle` | `preparation_tab.py:471` | Calls `BundleManager.import_bundle` which copies potentially many files synchronously. No background flag or progress reporting. |
| `import_genomes_from_archive` | `preparation_tab.py:578` | Extracts and copies genome files from an archive. Synchronous. |
| `update_readiness_indicator` | `callbacks.py:438` | Executes `shutil.which` for up to 7 tools and `os.stat` / glob for DB paths on **every interval tick** with no caching. At 30 s frequency this is manageable, but it is the single most disk-touching callback that fires on every tick without a debounce gate. |

### 3.3 Clientside callback opportunities

Existing clientside callbacks (confirmed in `app/app.py:635`, `app/app.py:653`, `app/callbacks.py:511`, `app/callbacks.py:839`):
- Watchlist collapse toggle -- correct
- Countdown timer display -- correct
- Readiness badge navigation to preparation tab -- correct
- Theme toggle -- correct

**Candidates for conversion to clientside callbacks:**

| Current server callback | File:line | Why it qualifies |
|---|---|---|
| `update_elapsed_time` (`callbacks.py:887`) | Fires every 1 s via `countdown-tick`. Reads `backend-status` Store and formats a timedelta. No disk I/O. The clientside countdown callback at `app.py:653` already has access to `backend-status` as an Input and could compute elapsed time from `backend_status.start_time` using `Date.now()`. Merging these two into one clientside callback would eliminate one server round-trip per second entirely. | Pure arithmetic on two timestamps. |
| `update_live_indicator` (`callbacks.py:661`) | Reads `backend-status` and `app-config` from Stores. Returns CSS class names and a time string. No disk I/O. Fires on every `update-interval` tick. | Pure Store read + string formatting. |
| `update_stale_data_warning` (`callbacks.py:711`) | Reads `last-update-time` and `app-config` from Stores. Computes age in seconds. Returns one CSS style dict. | Pure arithmetic on timestamps. |

### 3.4 List-wrapped Output/Input/State (legacy form)

Dash 4 accepts bare `Output(...)` / `Input(...)` / `State(...)` without enclosing lists when there is a single item, and recommends bare multi-output tuples over bracketed lists. The following callbacks still use the `[Output(...), ...]` list syntax:

**`app/callbacks.py`** (verified lines 184, 232, 331, 375, 429, 530, 551, 602, 650, 705, 880, 913, 966, 1024):
- `update_status_display` -- `[Output, Output, Output]`
- `update_control_button` -- `[Output, Output, Output]`
- `handle_stop_confirmation` -- `[Output, Output]`
- `update_readiness_indicator` -- `[Output, Output, Output, Output]`
- `update_available_samples` -- `[Output, Output]` + `[Input, ...]`
- `update_sample_selector_options` -- `[Output, Output]`
- `update_live_indicator` -- `[Output, Output, Output]` + `[Input, Input]`
- `update_stale_data_warning` -- `[Input, Input]` (single Output, Input list)
- `update_elapsed_time` -- `[Output, Output]`
- `auto_navigate_on_completion` -- `[Output, Output, Output]` + `[State, State, State, State]`
- `manage_welcome_modal` -- `[Output, Output]` + `[Input, Input]`
- `theme-preference` clientside -- `[Output, Output]`

**`app/tabs/qc_tab.py`** (verified lines 229, 459, 808, 849, 959, 1080, 1252): all interval-driven QC callbacks use bracketed Input/Output lists.

**`app/tabs/main_tab.py`** (line 297): `update_main_results` wraps both its 9 Outputs and 4 Inputs in lists.

**`app/tabs/dashboard_tab.py`** (lines 109, 145, 444, 506, 530, 592, 963, 1106): all multi-output dashboard callbacks use lists.

**`app/tabs/classification_tab.py`** (lines 122, 128): `update_classification_plot` wraps 3 Outputs and 9 Inputs in lists.

This is a cosmetic/forward-compat issue. Dash 4 parses both forms identically, but the list form is explicitly listed as legacy in the Dash 4 migration guide. Any future move to `dash.page_container` or decorator-only registration will require the non-list form.

### 3.5 `prevent_initial_call` gaps on interval-driven callbacks

The following callbacks receive `update-interval` as an Input with no `prevent_initial_call=True`, meaning they execute on page load with `n_intervals=0`:

| Callback | File:line | Cost of spurious first-tick call |
|---|---|---|
| `update_backend_status` | `callbacks.py:176` | Calls `backend_manager.get_status()` -- cheap dict read; acceptable, this is the intended startup bootstrap |
| `update_readiness_indicator` | `callbacks.py:428` | Calls `ReadinessChecker.check_readiness()` -- spawns `shutil.which` for up to 7 tools on first load. Medium cost. |
| `update_available_samples` | `callbacks.py:550` | Scans output directory; will PreventUpdate if result matches default. Low cost. |
| `update_live_indicator` | `callbacks.py:649` | String formatting only. Acceptable. |
| `update_stale_data_warning` | `callbacks.py:703` | Datetime arithmetic. Negligible. |
| `track_last_update_time` | `callbacks.py:741` | `os.path.exists`. Negligible. |
| **`update_main_results`** | `main_tab.py:297` | **Full Kraken2 parse, organism card rendering, table population, watched-species scan. High cost. No debounce gate.** |
| `update_qc_plots` | `qc_tab.py:228` | FASTP/seqkit directory scan + 4 figure renders. Has internal debounce gate. Debounce prevents repeat but first call still fires. |
| `update_qc_stats` | `qc_tab.py:458` | Has internal debounce gate. |
| `update_per_sample_table` | `qc_tab.py:806` | Has internal debounce gate. |
| `update_base_quality_card` | `qc_tab.py:847` | Has internal debounce gate. |
| `update_read_statistics_card` | `qc_tab.py:960` | Has internal debounce gate. |
| `update_stage_strip` | `qc_tab.py:1078` | Has internal debounce gate. |
| `update_qc_action_guidance` | `qc_tab.py:1252` | Has internal debounce gate. |
| `update_classification_plot` | `classification_tab.py:122` | Has internal debounce gate (`prevent_initial_call=False` explicitly set at line 99). |
| **`update_available_configs`** | `config_tab.py:102` | Scans `~/.nanometa/configs/` on first load. Low cost but no guard. |

`update_main_results` is the primary concern: it has no `prevent_initial_call=True`, no `should_skip_update` guard, and performs the most expensive computation of any single interval-driven callback (Kraken2 parse, organism card construction, watched-species lookup, table rowData construction -- 9 outputs).

### 3.6 `allow_duplicate=True` usage

118 occurrences of `allow_duplicate=True` across the app (verified by grep). All reviewed usages follow the correct pattern: multiple callbacks write to the same Output but only one is expected to fire at a time (e.g., `notification-trigger`, `tabs.active_tab`, `taxmap-collection`, `app-config`). No band-aid misuse was detected, but the high count (118) indicates that some of this could be restructured around fewer shared outputs once the legacy list syntax is cleared up in a future pass.

---

## 4. "Always Firing" Hotspot Analysis

Cost-frequency ranking at default 30 s interval, 24-barcode scale:

| Rank | Callback | Interval | Debounce gate | Per-call operations | Cost x Frequency score |
|---|---|---|---|---|---|
| 1 | `update_main_results` (`main_tab.py:297`) | 30 s | None | Kraken2 parse (mtime-gated but cold-start every 30 s), organism card construction (up to N cards), watchlist scan, 9 outputs written | **HIGH** |
| 2 | `update_readiness_indicator` (`callbacks.py:428`) | 30 s | None | `shutil.which` x 7 tools + `os.stat` + glob per DB path -- 10+ syscalls per tick unconditionally | **HIGH** |
| 3 | `update_verdict_banner` (`dashboard_tab.py:163`) | 30 s | 2 s debounce | `load_kraken_data` (mtime-gated) + watchlist check + per-sample loop for attribution | MEDIUM-HIGH |
| 4 | `update_pathogen_alert_panel` (`dashboard_tab.py:605`) | 30 s | 2 s debounce | `load_kraken_data` + per-sample organism load + alert component construction | MEDIUM-HIGH |
| 5 | `compute_overall_status_cache` (`dashboard_tab.py:118`) | 30 s | 2 s debounce | `load_kraken_data` + `_collect_samples_data` across all samples | MEDIUM |
| 6 | `update_classification_plot` (`classification_tab.py:122`) | 30 s | 2 s debounce | Sankey/Sunburst figure generation (potentially large DataFrame) | MEDIUM |
| 7 | QC callbacks x 7 (`qc_tab.py`) | 30 s | 2 s debounce each | FASTP/seqkit parse + figure render | MEDIUM (per callback, x7) |
| 8 | `update_elapsed_time` (`callbacks.py:884`) | **1 s** | None | Store read + timedelta arithmetic | LOW per call, **HIGH frequency** |
| 9 | `update_available_samples` (`callbacks.py:560`) | 30 s | PreventUpdate on equal | `get_available_samples` + `get_sample_file_mapping` directory scan | LOW-MEDIUM |
| 10 | `update_available_configs` (`config_tab.py:107`) | 30 s | None | Config directory scan | LOW |

**Notable finding:** `update_verdict_banner` calls `load_kraken_data(main_dir, "All Samples")` directly (line 237) without checking `aggregate-kraken-cache` store, even though that store exists precisely to prevent redundant loads. On the same tick, `compute_overall_status_cache` (ranked 5) also calls `load_kraken_data`. With the mtime cache, the second call hits the cache if files have not changed, but the cache is process-level and thread-sensitive; under concurrent callback execution in Flask's threaded mode both calls may each enter the parse path simultaneously before either stores the result, mitigated only by the `_get_parse_lock` mechanism in `loader_utils.py:65`.

---

## 5. Operator-Impact Severity Rankings

### P0 -- Causes visible flicker, lost interaction state, or visible lag

**P0-F01: `update_main_results` fires on page load with no guard and overwrites `detailed-organism-table` rowData wholesale**
- File: `app/tabs/main_tab.py:297`
- Impact: On every 30 s tick the organism table is fully replaced with a new list, which in AgGrid scrolls the table back to row 1 and resets sort/filter state. Despite `getRowId` being declared, full `rowData` replacement bypasses the AgGrid diffing engine and causes a full re-render with visible flicker.
- Fix: Add `prevent_initial_call=True` to the decorator. Add a `should_skip_update("main_results", debounce_ms=2000)` guard for interval-triggered calls. Transition to `Patch()` for incremental row updates.

**P0-F02: `update_verdict_banner` does not consume `aggregate-kraken-cache` store**
- File: `app/tabs/dashboard_tab.py:237`
- Impact: On every tick the verdict banner independently calls `load_kraken_data(main_dir, "All Samples")`, duplicating work already done by `compute_overall_status_cache` on the same tick. The mtime cache usually prevents a double-parse, but the duplicate `load_kraken_data` call still enters the parse lock path and contends with other concurrent callbacks. At 24-barcode scale this creates measurable lock-wait latency on the Dashboard tab.
- Fix: Change `update_verdict_banner` to read `overall_status` from `dashboard-overall-status-cache` (State, already present at line 159) and extract the pre-computed Kraken2 results from `overall_status["all_samples"]` instead of re-calling `load_kraken_data`.

### P1 -- Wastes resources, invisible to operator

**P1-F01: `update_readiness_indicator` runs `ReadinessChecker.check_readiness` on every 30 s tick without any caching or debounce gate**
- File: `app/callbacks.py:428`
- Impact: `check_readiness` calls `shutil.which` for up to 7 command-line tools and performs multiple `os.stat` / glob operations per tick. With the default 30 s interval this runs 120 times per hour. The results change only when the operator installs a tool or the database path changes.
- Fix: Cache the `ReadinessReport` against an `(app-config._version, mtime_of_nanometa_home)` fingerprint with a 60 s minimum TTL, and add `should_skip_update("readiness_indicator", debounce_ms=30000)` (matching the update interval). Alternatively, remove `n_intervals` as an Input and keep only `app-config` as the trigger.

**P1-F02: `update_elapsed_time` fires every second even when no run is active**
- File: `app/callbacks.py:884`
- Impact: One server round-trip per second. When `status.running` is False the callback returns immediately with default values, but the round-trip still occupies a Flask worker thread, Dash serialization, and WebSocket bandwidth.
- Fix: Convert to a clientside callback. The countdown clientside callback (`app.py:653`) already receives `backend-status` as an Input. Extend it to also compute elapsed time from `backend_status.start_time` using `Date.now()`, output to `update-countdown` and `elapsed-time-display`, and remove the server callback entirely.

**P1-F03: `update_available_configs` scans `~/.nanometa/configs/` on every 30 s tick without a debounce gate**
- File: `app/tabs/config_tab.py:107`
- Impact: The config list changes only when the operator saves or loads a configuration. Scanning the directory 120 times per hour is unnecessary.
- Fix: Add `should_skip_update("available_configs", debounce_ms=30000)` and raise `PreventUpdate` if the scan result is identical to the last known value, or add `prevent_initial_call=True` and trigger only from `app-config` data changes.

**P1-F04: Neither `update-interval` nor `countdown-tick` is ever disabled**
- File: `app/app.py:260-273`
- Impact: Both intervals fire from page load through page close regardless of pipeline state, occupying 24 + 2 callback executions per 30 s cycle continuously. When the operator is on the Configuration tab with no run active, approximately 20 of those 24 callbacks perform no meaningful work (return early or hit debounce), but they still consume Flask threads and Dash overhead.
- Fix: Disable `countdown-tick` when `backend-status.running` is False via a clientside callback writing to its `disabled` prop. Consider disabling `update-interval` when no `main_dir` is configured.

**P1-F05: `aggregate-kraken-cache` and `per-sample-kraken-cache` stores are written but not consumed by the verdict-banner callback**
- File: `app/app.py:248-249`, `app/tabs/dashboard_tab.py:237`
- Impact: These stores were introduced as a caching layer but the Dashboard's most expensive consumer (`update_verdict_banner`) does not read from them, making them partially dead code.
- Fix: See P0-F02.

### P2 -- Code quality / Dash 5 forward-compat

**P2-F01: List-wrapped `[Output(...), ...]` syntax in ~90% of multi-output callbacks**
- Affects: `app/callbacks.py` (14 locations), `app/tabs/main_tab.py`, `app/tabs/qc_tab.py` (8 locations), `app/tabs/dashboard_tab.py` (9 locations), `app/tabs/classification_tab.py`
- Impact: Dash 5 will require the bare tuple form. The list form is parsed identically in Dash 4.
- Fix: Mechanical conversion -- remove the outer `[...]` brackets from `Output`, `Input`, and `State` argument groups in `@app.callback` decorators. Can be done per-file as part of any routine edit.

**P2-F02: `run_rescan` (Kraken2 DB taxid mapping scan) is synchronous, not `background=True`**
- File: `app/tabs/preparation_tab.py:685`
- Impact: `mapper.load_database(kraken_db)` reads the Kraken2 database index (can be several hundred MB) and `mapper.generate_mappings()` performs fuzzy name matching across all watchlist entries. On a large database with many watchlist entries this may block the Flask worker for 5-30 seconds, freezing the operator's browser tab.
- Fix: Convert to `background=True` with progress reporting, following the same pattern used by `download_missing_genomes` at line 954.

**P2-F03: `update_elapsed_time` server callback is redundant with the existing clientside countdown**
- File: `app/callbacks.py:879` (see also P1-F02)
- Impact: Both update the elapsed-time display. The server callback fires once per second. Forward-compat: Dash 5 will enforce stricter limits on high-frequency server callbacks.

---

## 6. Callsites That Can Now Move to `Patch()`

All four AgGrid tables with `getRowId` write full `rowData` replacements. After the phase 6 work that added `getRowId` to each table, the following callsites are now candidates for `Patch()` row-level updates:

| Callsite | File:line | Current behaviour | `Patch()` benefit |
|---|---|---|---|
| `update_main_results` | `main_tab.py:301` | Returns full `rowData` list every tick | `Patch()` with `append` / `__setitem__[taxid]` would preserve sort, filter, scroll; eliminates full-table re-render flicker |
| `update_per_sample_table` | `qc_tab.py:807` | Returns full `rowData` list every tick | Rows keyed by `sample`; `Patch()` would preserve column sort state between ticks |
| `update_dashboard_sample_table` | `dashboard_tab.py:507` | Returns full `rowData` list every tick | Rows keyed by `sample`; same benefit |
| `update_blast_table` | `validation_tab.py:637` | Returns full `rowData` list every tick | Composite key `species||sample_id`; validation results are write-once so `Patch().__add__` of new rows is appropriate |

For `update_blast_table` the full-replace pattern is less harmful because validation results load infrequently (only when the operator triggers validation). For the other three tables the 30 s interval makes the flicker visible.

A minimal `Patch()` implementation for `update_per_sample_table` as a reference:
```python
from dash import Patch

def update_per_sample_table(n_intervals, selected_sample, config, status):
    ...
    summary_df = get_sample_statistics_summary(main_dir)
    if summary_df.empty:
        return []
    patch = Patch()
    for record in summary_df.to_dict('records'):
        patch[record["sample"]] = record  # keyed by getRowId field
    return patch
```
Note: `Patch()` dict-style assignment requires that the key matches the `getRowId` expression value. For full replacement on first load (when existing rows are unknown) the current `return []` guard should remain as the initial path; `Patch()` should be used only when `prev_cache` indicates data was previously loaded.

---

## 7. Component Coverage Table

| Component | Location | Status |
|---|---|---|
| `dcc.Interval` `update-interval` | `app.py:260` | Audited -- never disabled, 24 subscribers |
| `dcc.Interval` `countdown-tick` | `app.py:268` | Audited -- never disabled, 2 subscribers |
| `dcc.Store` `aggregate-kraken-cache` | `app.py:248` | Written, not consumed by primary intended consumer |
| `dcc.Store` `per-sample-kraken-cache` | `app.py:249` | Written, not consumed by primary intended consumer |
| `dcc.Store` `dashboard-overall-status-cache` | `dashboard_layout.py` | Correct producer-consumer pattern |
| `dcc.Store` `validation-data-store` | `validation_tab.py` | Correct |
| AgGrid `detailed-organism-table` | `main_layout.py:241` | `getRowId` present; `rowData` still full-replace |
| AgGrid `per-sample-table` | `qc_layout.py:134` | `getRowId` present; `rowData` still full-replace |
| AgGrid `dashboard-sample-table` | `dashboard_layout.py:229` | `getRowId` present; `rowData` still full-replace |
| AgGrid `blast-stats-table` | `validation_layout.py:230` | `getRowId` present; `rowData` still full-replace |
| `background=True` callbacks | `preparation_tab.py:150,965,1267,1756` | Correct |
| Clientside callbacks (4 existing) | `app.py`, `callbacks.py` | Correct; 3 candidates for addition identified |

---

## 8. Recommended Action Items (Priority Order)

1. **P0-F01**: Add `prevent_initial_call=True` to `update_main_results` (`main_tab.py:297`) and add a `should_skip_update` guard. This single change eliminates the most expensive spurious first-load call.

2. **P0-F02**: Redirect `update_verdict_banner` to consume Kraken2 results from `dashboard-overall-status-cache` State instead of calling `load_kraken_data` directly (`dashboard_tab.py:237`). Retire the `aggregate-kraken-cache` store or wire it correctly.

3. **P1-F01**: Cache `ReadinessChecker` results in `update_readiness_indicator` (`callbacks.py:428`) with a debounce gate or config-change-only trigger.

4. **P1-F02 + P2-F03**: Convert `update_elapsed_time` (`callbacks.py:884`) to a clientside callback and merge with the existing countdown clientside callback.

5. **P1-F04**: Add a clientside callback to disable `countdown-tick` when `backend-status.running` is False.

6. **P2-F02**: Convert `run_rescan` (`preparation_tab.py:685`) to `background=True`.

7. **AgGrid Patch()**: Migrate `update_per_sample_table` and `update_dashboard_sample_table` to `Patch()` row updates (lowest risk, highest visual benefit for operators using the sample tables during active runs).

8. **P2-F01**: Mechanically remove list-wrapping from `Output/Input/State` arguments across all tab files as a batch refactor.
