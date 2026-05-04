# nanometa_live GUI Throughput Audit -- 2026-04-28

## Scope

GUI behavior at 12-24 barcodes streaming continuously for hours. Focus on
callback fanout, loader caching, store churn, parser cost, and memory growth.
Findings already covered by `docs/audit-2026-04-28-nanometa-live-code.md`
(offline-mode regressions, dead modules, dead stores, missing tests) are
**not** repeated here.

## Summary

- Total findings: 17 (P0: 2, P1: 9, P2: 6)
- Highest-impact bottleneck: **P0-T01** -- one tick of `update-interval`
  fires roughly two dozen server callbacks, several of which call
  `load_kraken_data(main_dir, "All Samples")` independently. Every such call
  re-aggregates *every* per-sample report serially in Python (no shared
  in-process aggregate cache below the 2s mtime fingerprint key). At 24
  barcodes producing fresh batch reports every interval, the kraken2
  directory's mtime advances on most ticks, all "All Samples" mtime caches
  invalidate at once, and 5-10 separate callbacks each redo the full
  aggregation. With cumulative reports in the multi-MB range this is the
  dominant per-tick cost.
- Bundled secondary risk: **P0-T02** -- `_load_per_sample_organisms`
  (dashboard pathogen alert callback) calls `load_kraken_data(main_dir, sample)`
  in a Python `for` loop over every barcode. At 24 barcodes this is 24
  serial loads (each potentially parsing a multi-MB cumulative report on a
  cache miss), all on the Dash request thread, blocking the response.
- Predicted GUI responsiveness at 24 barcodes streaming hourly: **fair to
  poor**. The 30s interval and 2s debounce mask single-tick cost, but in
  the worst case (kraken2 mtime advanced + cold cache) the dashboard
  pathogen-alert callback alone serially parses 24 cumulative reports
  totaling 100-200MB of pandas IO. Operator-perceived freezes of 5-15s on
  fresh data ticks are likely.

## P0 (GUI hangs or memory-leaks under load)

### [P0-T01] Five "All Samples" Kraken2 loads per tick, all invalidate together

**Files:**
- `nanometa_live/app/tabs/dashboard_tab.py:777` (pathogen alert)
- `nanometa_live/app/tabs/dashboard_tab.py:2006` (alerts panel
  `_generate_alerts`)
- `nanometa_live/app/tabs/dashboard_tab.py:2027` (pathogen check inside
  `_generate_alerts`)
- `nanometa_live/app/tabs/dashboard_tab.py:1566` (overall status cache:
  `safe_load_kraken_data(..., "All Samples")`)
- `nanometa_live/app/tabs/dashboard_tab.py:410` (active watchlist panel
  loader; not registered as callback per the comment, but the function
  still pays the cost when invoked elsewhere)

**Issue:** Each call goes through `classification_loaders.py:303
load_kraken_data(main_dir, "All Samples")`. The function has two cache
layers: a mtime-cache keyed on the kraken2 directory's `(max_mtime,
total_size)` fingerprint (`loader_utils.py:188 _get_path_fingerprint`) and
a 30s TTL cache (`loader_utils.py:24 CACHE_TTL_SECONDS`). On every tick
where any of 24 barcodes wrote a new batch file, the directory's mtime
advances and *all* "All Samples" mtime keys invalidate. The TTL cache is
also invalidated because `_kraken_cache` is keyed by `f"{main_dir}:{sample}"`
(`loader_utils.py:90`), so the SAME key is contended -- all five callbacks
re-aggregate from scratch. At 24 barcodes with cumulative reports of ~5-10MB
each, that is 120-240MB of pandas IO replayed five times per tick.

There is no shared "current-tick aggregate" reference held by Dash, so two
callbacks firing in parallel (Flask runs callbacks on a thread pool) both
hit the cache miss and both rebuild.

**Impact:** Worst-case 5-15s freeze per tick at 24 barcodes when the
pipeline is actively writing. Best case (no new data): cache hit, near-zero
cost. The amplification factor is the killer: 5 callbacks x 24 reports =
120 cumulative-report parses per tick.

**Recommendation outline (don't fix, just for the parent agent):** A
single "kraken-aggregate-cache" `dcc.Store` updated by one core callback
on the freshness fingerprint, read as State by all five places.
Alternatively, the existing `dashboard-overall-status-cache` already
fans the result out to three downstream callbacks; extend it to carry the
all-samples DataFrame's pre-computed organism list rather than just
totals.

### [P0-T02] Per-sample organism load serializes 24 cumulative-report parses

**File:** `nanometa_live/app/tabs/dashboard_tab.py:81-134
(_load_per_sample_organisms)`

**Issue:** Inside the `update_pathogen_alert_panel` callback (line
736-803), `_load_per_sample_organisms(main_dir, resolved_samples)` runs
once per tick (line 791). Its body is a Python for-loop over every real
sample (line 106): `kraken_df = load_kraken_data(main_dir, sample)`. At
24 barcodes that is 24 sequential `load_kraken_data` calls on the
callback thread. Each call:

1. Hits the mtime cache (cheap on warm hit, but 24 separate stat calls)
2. On miss: parses the cumulative report for that sample with
   `_parse_kraken2_report` (`classification_loaders.py:72`), which calls
   `_is_file_stable` (`loader_utils.py:47`) -- one extra `os.stat`, then
   `pd.read_csv` of the multi-MB cumulative report.

There is **no parallelism** -- not `concurrent.futures`, not even
`ThreadPoolExecutor`. The dashboard pathogen-alert callback blocks for
the full sum of all 24 parse times.

**Impact:** This is the single hottest spot for >5s freezes. At a
realistic 100k-1M reads per barcode and ~50k taxa in the Kraken2 PlusPFP
DB, a single parse can be 200-500ms. 24 of them serially is 5-12s. The
debounce at line 759 (`debounce_ms=2000`) does not help -- it just makes
this happen on every other tick instead of every tick.

**Recommendation outline:** Either (a) skip per-sample attribution when
`len(real_samples) > N` and only attribute taxids that *actually* matched
a watchlist entry (most of the 24 parses' results are discarded); or (b)
parallelize via `concurrent.futures.ThreadPoolExecutor` -- pandas releases
the GIL during `read_csv`. Order (a) is the correct architectural fix.

## P1 (sluggish or wasted CPU)

### [P1-T01] `update_qc_plots` rescans `fastp/` and `kraken2/` directly, ignoring loader cache

**File:** `nanometa_live/app/tabs/qc_tab.py:203-417`

**Issue:** Instead of calling `load_fastp_data` (which has mtime caching at
`qc_loaders.py:119`), the callback opens every JSON in `fastp/` directly
(`qc_tab.py:229`) and falls through to opening every kraken2 report
directly (`qc_tab.py:282`). For 24 barcodes producing 5-10 batch files
each, that is 120-240 fresh `open()` + `json.load` (or `pd.read_csv` for
kreports) calls every tick, with no caching. Same pattern in
`update_qc_stats` (line 499) for `realtime_batch_stats/batch_*.json` and
in `update_base_quality_card` (line 865), `update_read_statistics_card`
(line 972).

**Impact:** ~5-10x redundant filesystem IO per tick. The unused but
existing `_fastp_cache` (`loader_utils.py:37`) was supposed to cover
exactly this case. Per the prior audit P1-08, `check_data_freshness`
(the cleanup hook for `_fastp_cache`) is never invoked, so the cache
never fills *or* clears.

### [P1-T02] `update_pathogen_alert_panel` and `compute_overall_status_cache` both run every tick on the same data

**Files:**
- `nanometa_live/app/tabs/dashboard_tab.py:280` (`compute_overall_status_cache`)
- `nanometa_live/app/tabs/dashboard_tab.py:723` (`update_pathogen_alert_panel`)

**Issue:** Both callbacks listen to `Input("update-interval", "n_intervals")`
and both call `load_kraken_data(main_dir, "All Samples")` (lines 1566 and
777). The 4-zone redesign explicitly introduced
`dashboard-overall-status-cache` to share work between Zone 1/2/3, yet
the pathogen alert in Zone 2 reads from `update-interval` directly
instead of subscribing to the cache store. Same code, computed twice per
tick. Verdict banner (line 317), quality card (line 505), data freshness
(line 1240), watchlist panel (line 1093 -- noqa noted but still imported)
all also fire on `update-interval` directly.

**Impact:** Zone 2 alert duplicates Zone 1's expensive load. Same TTL
cache is hit, but each callback still pays the lookup + Python overhead,
and on cache miss (P0-T01) both pay the full parse cost.

### [P1-T03] `update_available_samples` runs every tick and over-writes the store every time

**File:** `nanometa_live/app/callbacks.py:543-579`

**Issue:** This callback fires on every `update-interval` tick (line 548)
and unconditionally returns `(samples, mapping)` even when the values
haven't changed. The `available-samples` store update then re-triggers
every callback that has it as Input or State. The
`get_sample_file_mapping` call (line 571,
`sample_detector.py:440`) in particular does **not** use the mtime cache
that `get_available_samples` does -- it always loops every sample and
runs four `glob.glob` calls per sample (lines 484-507). At 24 barcodes
that is 96 `glob.glob` invocations every 30s.

**Impact:** Cache-bypass for `get_sample_file_mapping`. The
`sample-file-mapping` store is then a no-op write (same data) that may
still trigger downstream renders depending on Dash's prop-diff. Returning
`no_update` when the fingerprint matches would cut store traffic.

### [P1-T04] `_collect_samples_data` calls `load_kraken_data` AND `load_seqkit_stats` for every barcode

**File:** `nanometa_live/app/tabs/dashboard_tab.py:1816-1942`

**Issue:** `_collect_samples_data` is invoked by
`compute_overall_status_cache` (line 306) every tick. It loops every
real_sample (line 1834) and per iteration calls:

- `load_kraken_data(main_dir, sample)` (line 1837)
- `load_seqkit_stats(main_dir, sample)` (line 1878)
- `load_nanoplot_stats(main_dir, sample)` if seqkit empty (line 1887)

At 24 barcodes that's 24 + 24 + (up to 24) = 48-72 loader calls every
tick, all serial. Each `load_kraken_data` is itself the per-sample fast
path described in `classification_loaders.py:584-728`, which on cache
miss parses a single (highest-numbered or cumulative) report. Cumulative
reports for late-run samples will be 1-5MB each.

**Impact:** Same serial-fan-out problem as P0-T02 but for a different
callback. Worst case 1-2s per tick. Mitigated by mtime caching when no
new data arrived, but on every tick where new data arrived, the cache
invalidates for *all* samples at once because they share the kraken2
directory mtime.

### [P1-T05] DiskcacheManager runs single-worker; long-running prep + DB downloads serialize

**File:** `nanometa_live/app/app.py:13-27`

**Issue:** `DiskcacheManager(_cache)` is constructed without any worker
configuration (line 27). Dash's default behaviour with diskcache is a
*single* worker process per manager instance. There are four background
callbacks: `run_preparation` (preparation_tab.py:147),
`build_blast_databases` (preparation_tab.py:969 area), genome download
(preparation_tab.py:1271), and Kraken2 DB download
(preparation_tab.py:1906). If a clinician kicks off genome downloads while
preparation is running, the second click queues behind the first --
silently. There is no queueing UI.

For 24-barcode field deployments this matters most when a user runs
"Prepare" while the live dashboard is also doing things; the worker pool
size is the bottleneck.

**Impact:** Latent UX issue. Operator clicks Download, sees nothing
happen for tens of minutes while another background job finishes.
Specify `DiskcacheManager(_cache, expire=3600, threads=N)` or use the
`celery` manager for true concurrency.

### [P1-T06] Validation parser reloads aggregate JSON twice per call

**File:** `nanometa_live/core/parsers/blast_validation_parser.py:599-606`

**Issue:** `get_validation_summary()` calls `self.get_validation_results()`
(line 606) which re-runs the entire glob + JSON parse pipeline. Both
`update_blast_summary` callback (validation_tab.py:131) reads
`data["summary"]` AND `data["results"]` from the same store, but the
store is populated by `load_validation_data` (validation_tab.py:80-125)
which calls `parser.has_validation_data()`, then
`parser.get_validation_results()`, then `parser.get_validation_summary()`
-- three independent passes over the validation directory per tick. At
24 barcodes with 5-10 validated species each, that is 100-200 file
opens every 30s.

There is no caching anywhere in `BlastValidationParser`. Every callback
fires builds a new parser and walks the directory.

**Impact:** Redundant. With minimap2 PAF parsing also happening on
demand (`paf_coverage_parser.py`), the validation tab is the second
costliest tab after the dashboard.

### [P1-T07] `update_dashboard_metrics` re-loads kraken data when sample changes from "All Samples"

**File:** `nanometa_live/app/tabs/dashboard_tab.py:591-632`

**Issue:** The "smart" path at line 604 says "if user picked a specific
sample, do `load_kraken_data(main_dir, metric_sample)`". Otherwise it
uses cached `overall_status['total_reads']`. The branch is fine, but the
issue is the callback fires both on `dashboard-overall-status-cache`
data change AND on `sample-selector` value change (lines 582-583), and
the per-sample load (line 605) does not coalesce with the load done by
`_collect_samples_data` (line 1837) when "All Samples" is the selection.
Two separate callbacks load the same sample's data within the same tick.

**Impact:** Mild. Both calls hit the same TTL cache, so only the first
pays the cost. But the `should_skip_update` debounce that protects most
other callbacks is missing here, so a rapid-fire sample-selector change
during ingest triggers full re-renders unbounded.

### [P1-T08] No bound on `_debounce_timestamps` dict

**File:** `nanometa_live/app/utils/debounce.py:17, 64`

**Issue:** `_debounce_timestamps: Dict[str, float] = {}` is a module-level
dict that grows by one entry per unique `callback_id` ever passed.
`should_skip_update` (line 65) writes but never trims. There are ~14
distinct `callback_id`s in the codebase, so the dict tops out at 14
entries -- not a memory leak. **However**, the same is not true if
pattern-matching callbacks ever pass dynamic ids, and `reset_debounce`
is documented but called nowhere (`grep -RIn "reset_debounce"
nanometa_live/` returns only its definition).

**Impact:** Negligible today (14-entry max). Worth a comment to prevent
future regression. Also `CallbackThrottler._last_calls` (line 114-116)
has the same pattern with no eviction.

### [P1-T09] `BackendManager._update_file_counts` os.listdir's nanopore directory each tick

**File:** `nanometa_live/core/workflow/backend_manager.py:527-552`

**Issue:** Called from `get_status` (line 522), which is called by
`update_backend_status` (callbacks.py:178) on every tick. The function
does `os.listdir(nanopore_dir)` then a second `os.listdir` per barcode
subdir (lines 540-545). For 24 barcodes with hundreds of FASTQ files
each, that's 25 `listdir` calls + linear filename matching on every
tick. As the run progresses past 10k input files (long real-time runs),
this becomes the slowest part of `get_status`.

**Impact:** Mild but compounds with run length. After 12 hours of
sequencing the nanopore_dir can have 50k+ FASTQ files per barcode and
the listdir + extension matching grows linearly. Use the manifest count
instead, or cache by mtime.

## P2 (cleanup)

### [P2-T01] Two `from nanometa_live.core.utils.data_loaders import load_kraken_data` redundant imports

**Files:**
- `nanometa_live/app/tabs/dashboard_tab.py:21` (top-level)
- `nanometa_live/app/tabs/dashboard_tab.py:878` (re-imported inside
  `handle_view_report`)

**Issue:** `load_kraken_data` is already imported at module level (line
21) but re-imported inside the `handle_view_report` callback (line 878).
Same in main_tab.py callbacks. Cosmetic.

### [P2-T02] `_kraken_cache` size cap is 100 entries; per-tick cardinality at 24 barcodes is 25

**File:** `nanometa_live/core/utils/loader_utils.py:25, 36-37`

**Issue:** `CACHE_MAX_ENTRIES = 100`. At 24 barcodes the cardinality is
25 keys (`{main_dir}:{barcode01}` ... `{main_dir}:{barcode24}` plus
`{main_dir}:All Samples`). Plenty of headroom now. But if a user runs
multiple analyses in one session (`main_dir` changes), the cache fills
up quickly: 25 entries per main_dir x several main_dirs = >100 fast.
The eviction is "remove oldest by cache_time" (line 127) which is fine
but there's no eviction by main_dir. A long-running operator session
that opens five different `main_dir` paths burns the cache.

**Impact:** Latent. Document the pathology or scope keys by main_dir.

### [P2-T03] `_count_processed_samples` glob per sample, runs every tick via overall status

**File:** `nanometa_live/app/tabs/dashboard_tab.py:1694-1707`

**Issue:** Loop over real_samples (line 1701) running
`glob.glob(os.path.join(kraken_dir, f"*{sample}*.txt"))`. At 24 barcodes,
24 `glob.glob` calls per tick. Could be one `os.listdir` and a
substring match.

### [P2-T04] `iterrows()` still present in `qc_tab.py:259` and `report_generator.py:167`

**File:** `nanometa_live/app/tabs/qc_tab.py:259` (already noted in prior
audit P2-11)

Already filed. Including here for completeness in the "callbacks fanout"
context: this is inside `update_qc_plots` so it does fire per tick.

### [P2-T05] `parent_taxid` derivation per row in `_parse_kraken2_report` is O(N) Python loop

**File:** `nanometa_live/core/utils/classification_loaders.py:144-163`

**Issue:** The indentation-stack traversal (lines 144-161) iterates row
by row in Python with `df.iloc[idx]["name"]`. For a Kraken2 PlusPFP
report with 50k taxa, that's 50k iloc lookups -- pandas `iloc[]` is
slow. Should be vectorizable with `df["name"].str.lstrip().str.len()`
for indent calculation, then a single forward-pass over a numpy array.

CLAUDE.md notes this column is then often *overridden* by
`apply_authoritative_taxonomy` (kraken2_helpers.py) anyway, so the slow
in-parser computation can be skipped entirely when the inspect.txt
taxonomy is available.

**Impact:** ~50-200ms per cumulative report parse, multiplied by 24 in
the worst-case fan-out paths above.

### [P2-T06] `track_last_update_time` writes to store every tick unconditionally

**File:** `nanometa_live/app/callbacks.py:721-741`

**Issue:** Returns `datetime.now().isoformat()` on every tick (line 737)
even when nothing has changed. Every callback with
`Input("last-update-time", "data")` (the stale-data warning) fires
every tick because the value advances every tick. The
`update_stale_data_warning` callback (line 691) doesn't actually need
this: it could compare against `backend-status.last_update` which
already advances when real activity happens.

**Impact:** One extra store write + one extra callback fire per tick.
~0% CPU; mostly a callback-graph cleanup item.

## Callback inventory

Counted via grep on `@app.callback` and `Input("update-interval"`:

| Tab / module | Total callbacks | Fire on update-interval | Has per-sample loop |
|---|---:|---:|---|
| `app/callbacks.py` | ~25 | 9 | Yes (`update_available_samples` -> `get_sample_file_mapping`) |
| `app/tabs/dashboard_tab.py` | 16 | 8 | Yes (`_load_per_sample_organisms`, `_collect_samples_data`, `_count_processed_samples`) |
| `app/tabs/qc_tab.py` | 11 | 7 | No (uses "All Samples" or selected_sample) |
| `app/tabs/main_tab.py` | 10 | 2 | No (relies on selected-sample) |
| `app/tabs/classification_tab.py` | 5 | 1 | No |
| `app/tabs/validation_tab.py` | 17 | 1 | No (loads via parser, not per-sample) |
| `app/tabs/preparation_tab.py` | many | 0 (mostly background) | N/A |
| `app/tabs/watchlist_tab.py` | many | 0 | N/A |
| `app/tabs/config_tab.py` | many | 1 | No |

**Per interval tick fanout ceiling:** ~30 server callbacks + 2 clientside.
Of those, **5 independently load `load_kraken_data(main_dir, "All Samples")`**
and **3 helpers loop over every barcode calling `load_kraken_data(...,
sample)`** (one of which fires per tick from `update_pathogen_alert_panel`).

## Recommended optimizations for 24-barcode runs (don't fix; leave as suggestions for the parent agent)

1. **Centralize all-samples kraken load** behind a single dcc.Store
   updated once per tick by a core callback; have all dashboard /
   pathogen / verdict / quality callbacks read it as State, not as Input
   on update-interval. Cuts P0-T01 fanout from 5 to 1.

2. **Cap or parallelize per-sample fan-out** in
   `_load_per_sample_organisms`. Either skip when N > 12 and lazily
   attribute only on click, or use `ThreadPoolExecutor(max_workers=8)`
   to parallelize the parses.

3. **Wire `_fastp_cache`** (currently a dead variable) into
   `update_qc_plots` / `update_qc_stats` / `update_base_quality_card` /
   `update_read_statistics_card`, removing the direct `glob` + `open`
   loops. Same caching strategy as the Kraken2 mtime cache, scoped to
   `fastp/`.

4. **Wire `check_data_freshness`** (already exists at
   `loader_utils.py:261`, has zero callers) into a single core callback
   so the TTL cache cleanup actually runs.

5. **Reduce store-update churn** by returning `no_update` from
   `update_available_samples`, `update_dashboard_metrics`, and
   `track_last_update_time` when the value would be unchanged.

6. **Make `BlastValidationParser` cache its scan result** within a single
   `load_validation_data` callback invocation, rather than
   `has_validation_data` + `get_validation_results` +
   `get_validation_summary` each independently re-scanning.

7. **Specify DiskcacheManager workers** explicitly so concurrent
   background jobs don't silently queue.

---

End of throughput audit.
