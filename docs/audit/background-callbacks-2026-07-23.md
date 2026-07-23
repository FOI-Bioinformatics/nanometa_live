# Background-callback audit — nanometa_live Dash app

**Date:** 2026-07-23
**Lens:** the `dash-background-callback-split` skill
**Deliverable:** assessment only — no code changes.

## Scope & method

This audit applies one quality lens to the app's callback layer: a Dash callback
that does heavy or blocking I/O ties up a request thread and freezes the UI, and
should move to a background callback (`background=True`, `DiskcacheManager`). The
skill also says when *not* to split — fast callbacks and pure plot-renders stay
synchronous.

**nanometanf is out of scope.** It is a pure Nextflow DSL2 pipeline with no
Dash/Flask/web-UI code; its Python is stateless `bin/*.py` CLI helpers invoked
by Nextflow processes. The pattern applies only to nanometa_live.

**The distinction the whole audit turns on.** Not every side effect is a
problem in a background worker. A DiskcacheManager worker runs in a **separate
OS process**, so:

- Writing a **`dcc.Store` Output** from a worker is **fine** — the store is
  client-side state, returned to the browser via the callback response and
  applied in the main process. (This is why `download_kraken_database` can write
  `app-config` from its worker.)
- Mutating **Python in-process state** in a worker — a module-level singleton
  (`get_genome_manager`, `WatchlistManager`, the offline clients),
  `_init_offline_mode`, an lru_cache — is the **silent-failure trap**: the
  change happens in the worker's process and the live app never sees it. Such a
  side effect must run in a **main-process finalize** callback keyed on the
  worker's Store.

Reading a singleton the worker would find empty (the `WatchlistManager`) has the
mirror problem: the worker must receive that state via `State` from a store the
main process populates (`watchlist-entries-snapshot`, hydrated by
`hydrate_watchlist_entries_snapshot`, `preparation_tab.py:1044`).

Every claim below was verified against the decorator on disk.

---

## 1. Already background — correct (15)

Infrastructure: `app.py:30` declares the module-level `background_callback_manager`
(`DiskcacheManager`), passed to the `Dash(...)` constructor; every background
callback imports it.

### Full worker → dcc.Store → main-process finalize split — the precedents

These correctly isolate a Python-state side effect to the main process. Copy
these when converting a finding below.

| Worker | Finalize (main process) | Main-process side effect |
|---|---|---|
| `preparation_tab.py:739 import_bundle_worker` | `finalize_import:811` | `_init_offline_mode(True)` — re-inits the offline singletons; textbook case |
| `watchlist_tab.py:886 validate_entries` | `apply_background_validation_results:1028` | `manager.apply_validation_results` onto the main-process `WatchlistManager` |
| `startup.py:91 check_internet_on_startup` | `relay_internet_check_toast:136` | relay only (no singleton) — split done to avoid a duplicate-`toast-message` renderer crash |

### Plain background — self-sufficient (disk or Store output, no Python-state side effect)

`run_preparation` (`preparation_tab.py:403`), `export_bundle` (`:555`),
`force_export_bundle` (`:700`), `regenerate_mappings` (`:833`), `run_rescan`
(`:1089`), `download_missing_genomes` (`:1366`), `download_single_genome`
(`:1630`), `build_missing_blast_dbs` (`:1708`), `run_all_wizard_steps` (`:2153`),
`download_kraken_database` (`:2265`), `update_main_results` (`main_tab.py:151`),
`update_readiness_state` (`readiness.py:139`).

These reach the live app via the on-disk cache plus a refresh Store
(`genome-download-complete`, `blast-build-complete`), or via a Store Output — not
via in-process state — so no finalize is needed. Those that read the watchlist
already take the `watchlist-entries-snapshot` State (`run_preparation`,
`export_bundle`, `regenerate_mappings`, `run_rescan`, `download_single_genome`,
`update_readiness_state`); `validate_entries` and `run_all_wizard_steps` instead
reload `WatchlistManager` from config inside the worker.

---

## 2. Findings — should convert (ranked)

### P1 — clearly blocking subprocess/network, real operator pain

**`main_tab.py:978 run_on_demand_validation`** — *synchronous.* The Organisms-tab
"Validate" button shells out to BLAST/minimap2 or `nextflow run
--validation_only` (minutes), and also scans `<main_dir>/kraken2`. The code's own
comment says it should be a background callback. This is the biggest
un-converted blocker. Side effect: it writes the validation-results Store, which
belongs in a main-process finalize. Needs the split; watchlist not required.

**`preparation_tab.py:1925 test_genome_download`** — *synchronous.* Runs an NCBI
`datasets` download (E. coli, taxid 562) — network + subprocess on the request
thread. Plain background is enough (disk output; no Python-state side effect).

### P2 — network-on-load, and the sharp singleton cases

**`config_tab.py:304 populate_pipeline_branch_options`** — *synchronous* GitHub
API call (`fetch_nanometanf_branches`) on initial load and on every Remote/Local
toggle. A 10-minute cache and an offline short-circuit soften it, but a cold
load blocks the Configuration tab. Convert, or defer the fetch off the initial
render. No Python-state side effect.

**`preparation_tab.py:878 import_genomes_from_dir` / `:931
import_genomes_from_archive` / `:984 import_mapped_genomes`** — *synchronous*
directory scan / tar extraction / FASTA copy, and each **mutates the
`get_genome_manager` singleton**. These are the sharp side-effect cases: if the
import runs in a worker, the on-disk genomes land but the live app's in-memory
genome metadata never updates. The conversion must reload the singleton
(`reload_metadata()`) in the **main-process finalize** — the skill's core lesson.
(They currently run synchronously in the main process, so the singleton is
correct today; the cost is only the UI freeze.)

---

## 3. Keep synchronous — per "when NOT to split"

- **`classification_tab.py:137 update_classification_plot`** — CPU-heavy kraken
  parse + taxonomy-index read, but a multi-input **plot-render** callback that
  re-fires on input changes (not a one-shot action) with no Python-state side
  effect, and already memoized. Backgrounding plot renders is awkward and
  unwarranted; optimize via caching instead.
- **`startup.py:159 initialize_taxid_mappings`** — `update-interval`-driven cache
  load writing Stores. Interval-driven work fits background callbacks poorly, and
  it is fast after the first load. Keep; ensure it stays gated.
- **`reports_tab.py:58 render_reports_content`** — interval-driven, already
  debounced (`interval_tick_is_redundant`). Keep synchronous; only revisit if the
  taxpasta-long TSV parse is *proven* slow, and then via caching — do not
  background an interval callback.
- **`preparation_tab.py:1550 delete_genome` / `:1609 handle_remove_all`** — disk
  delete + singleton mutation, but fast. Keep synchronous (cheap callbacks stay
  sync).
- **`start_stop.py:44 start_or_prompt_stop` / `:201 handle_collision_choice`** —
  `backend_manager.start()` is a non-blocking `Popen`; the inline
  `detect_existing_results` scan is light. Keep synchronous.
- **`preparation_tab.py:2084 run_wizard_step`** — runs one heavy `_execute_wizard_step`,
  but it is a `MATCH` pattern-matching callback (awkward to background) and the
  batch path (`run_all_wizard_steps`) is already background. Prefer documenting
  the single-step synchronous limitation over a fragile conversion.

---

## 4. Correctness note (not a conversion)

**`download_kraken_database` (already background) calls `autosave_session_config`
at `preparation_tab.py:2329` inside the worker**, where the `WatchlistManager`
singleton is empty. Writing the `app-config` Store from the worker is fine
(client-side state), but the in-worker autosave runs against an empty watchlist
singleton, so the persisted `last-session.yaml` may omit watchlist state. This is
a latent singleton-in-worker smell — worth a follow-up ticket, independent of any
conversion above.

---

## 5. Priority summary

| Callback | Status | Verdict | Key risk on conversion |
|---|---|---|---|
| `main_tab.py:978 run_on_demand_validation` | sync | **P1 convert** | writes results Store → finalize |
| `preparation_tab.py:1925 test_genome_download` | sync | **P1 convert** | none (plain background) |
| `config_tab.py:304 populate_pipeline_branch_options` | sync | **P2 convert/defer** | none (network only) |
| `preparation_tab.py:878/931/984 import_genomes_*` | sync | **P2 convert** | genome-manager singleton → reload in finalize |
| `classification_tab.py:137 update_classification_plot` | sync | keep (cache) | plot-render, no side effect |
| `startup.py:159 initialize_taxid_mappings` | sync | keep | interval-driven |
| `reports_tab.py:58 render_reports_content` | sync | keep | interval-driven, debounced |
| `preparation_tab.py:1550/1609 delete_*` | sync | keep | fast |
| `start_stop.py:44/201` | sync | keep | non-blocking Popen |
| `preparation_tab.py:2084 run_wizard_step` | sync | keep/document | MATCH callback; batch path already bg |
| `download_kraken_database` autosave-in-worker | bg | **fix (correctness)** | empty watchlist singleton in worker |

**Headline:** the app's background-callback discipline is already strong — 15
callbacks converted, including 3 correct main-process-finalize splits. The one
true blocker is P1 `run_on_demand_validation`. The `import_genomes_*` trio (P2)
is the case that most needs the skill's core lesson: reload the genome-manager
singleton in a main-process finalize, not the worker. One correctness smell
(`download_kraken_database` autosave) is unrelated to blocking and worth its own
fix.
