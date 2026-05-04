# Production-Readiness Audit: Nanometa Live Frontend

Date: 2026-05-02
Scope: Dash GUI (`nanometa_live/app/`) + supporting core
(`nanometa_live/core/`).
Auditor: Phase B Auditor 1 (multi-agent audit).
Method: static cross-reference of layouts vs callbacks; pytest run
on dev2; targeted reads of suspect call sites. Three random claims
re-verified by direct file read before submission (see end of file).

Codebase scale: 100 Python source files (excluding `__pycache__`),
57,119 LOC; 47 test files (776 tests, 775 passed, 1 skipped, 0
failed; pytest run completed in 56.15s on the audit machine).

---

## 1. Dead Stores

The repo declares 56 `dcc.Store` widgets across 11 layout/component
files. Six of them are written or read by **zero** callbacks
(verified by grepping every `Input(...)`, `Output(...)`, `State(...)`
form, including `set_props`):

| Store ID | Declared at | Status |
|----------|-------------|--------|
| `aggregate-kraken-cache` | `nanometa_live/app/app.py:249` | Dead. Documented in CLAUDE.md as expected; the feeder callback that was supposed to populate it never landed. |
| `per-sample-kraken-cache` | `nanometa_live/app/app.py:250` | Dead. Same lineage as `aggregate-kraken-cache`; a 14-line comment block (`app.py:236-248`) describes a schema that no code implements. |
| `prep-job-state` | `nanometa_live/app/layouts/preparation_layout.py:124` | Dead. Stub for a job-tracking feature; no callback writes or reads it. |
| `download-cancel-flag` | `nanometa_live/app/layouts/preparation_layout.py:125` | Dead. The cancel button never wires to it. |
| `blast-cancel-flag` | `nanometa_live/app/layouts/preparation_layout.py:126` | Dead. Same as above. |
| `taxmap-selected-entry` | `nanometa_live/app/layouts/watchlist_layout.py:42` | Dead. No taxmap callback uses it. |

Two cancel flags (`download-cancel-flag`, `blast-cancel-flag`) imply
a cancellable long-running job UI that was started but not finished;
this is the one that actually matters for operators who need to
abort a 30-minute genome download. The other four are pure
accumulated-cruft that should be deleted.

## 2. Dead Callbacks

One outright dead clientside callback found:

**`nanometa_live/app/app.py:655-669`** -- `app.clientside_callback`
toggling watchlist collapse. Outputs target
`dashboard-watchlist-collapse` and `dashboard-watchlist-expand-btn`
(both `is_open` and `children`); Input is `dashboard-watchlist-expand-btn.n_clicks`.
A repo-wide grep finds **zero** definitions of either ID outside this
callback. The callback is registered but its trigger button does not
exist in any layout. Probably orphaned during the Dashboard
4-zone refactor noted in `CLAUDE.md`.

This is the same class of finding as the `aggregate-kraken-cache`
example called out in the audit brief: a remnant from a deleted
component that the registration site was never updated to drop.

## 3. Catch-all Exception Swallowers

100 `except Exception` blocks across the codebase. Most are well-
behaved (logged via `logger.exception()` with full stack trace, then
the function returns a safe default and the dashboard shows degraded
state). A small set silently swallow:

| File | Line | What it does | Severity |
|------|------|--------------|----------|
| `nanometa_live/app/tabs/validation_tab.py:505` | `except Exception: pass` after a `sorted(...)` call. If the sort key blows up on a malformed result dict, the validation cards render in arbitrary order with no indication anything went wrong. | Medium |
| `nanometa_live/app/tabs/main_tab.py:693` | `except Exception: return []` in `sync_watchlist`. If the WatchlistManager fails to load (e.g., corrupt YAML on user's `~/.nanometa/watchlists/`), the UI silently renders an empty watchlist with no alert. The operator believes their watchlist is empty. | High |
| `nanometa_live/app/tabs/main_tab.py:1022-1023` | `except Exception: continue` while looping over `*_validation.json` files. A single corrupt result file silently disappears from the dashboard. | Medium |
| `nanometa_live/app/tabs/dashboard_helpers.py:708-709` | Falls back to `_estimate_classified_rate(...)` with no logging. The dashboard shows an estimate as if it were real; operator has no way to know the actual computation failed. | Medium |
| `nanometa_live/app/tabs/watchlist_tab.py:44-45` | `except Exception: logger.debug("Could not save last-session.yaml", exc_info=True)`. Logged at DEBUG level (off by default), so config persistence failures are invisible in production. | Low |
| `nanometa_live/app/tabs/watchlist_tab.py:532-533` | `except Exception: genome_mgr = None`. The downstream code branches on `if genome_mgr` but the operator gets no warning that genome status will be unavailable. | Medium |
| `nanometa_live/app/callbacks.py:124-129` | `except Exception` on a network probe; this one *does* surface a friendly toast ("No Internet Detected"). Healthy pattern, included for contrast. | OK |

**Bare `except:` blocks: zero** (good).
**TODO / FIXME / XXX / HACK markers: zero** (verified by
case-sensitive grep across all 100 source files).

## 4. UX Gaps (Silent Failure on Happy-Path Callbacks)

The exception-swallower findings above flow directly into UX gaps.
Three additional issues independent of exception handling:

1. **`nanometa_live/app/tabs/main_tab.py:683-694`** -- when the
   watchlist load fails, `sync_watchlist` returns `[]`. The UI
   downstream assumes "empty watchlist" and renders nothing. There
   is no `dbc.Toast` or alert pathway in this callback, and the
   `notification-trigger` store (which exists for exactly this
   purpose, see `nanometa_live/app/app.py:221`) is not written.

2. **`nanometa_live/app/tabs/main_tab.py:1022-1023`** -- when a
   single `*_validation.json` parse fails, the loop silently
   `continue`s. The on-demand validation list quietly omits one
   entry. An operator who hit the Validate button and expects a
   result is told nothing.

3. **`nanometa_live/app/tabs/dashboard_helpers.py:701-709`** -- the
   dashboard "classified rate" stat falls back from a real
   computation to an estimator with **identical visual presentation**.
   No "(estimated)" suffix, no muted styling. This is a Dashboard
   Zone 3 stat (per the 4-zone clinical layout in CLAUDE.md), so an
   operator scanning the verdict banner thinks the number is
   measured when it might be a guess.

## 5. Module-Level Mutable State / Race Conditions

Caches and singletons in `core/`:

| File | Line | State | Lock? |
|------|------|-------|-------|
| `nanometa_live/core/utils/loader_utils.py:35-55` | `_kraken_cache`, `_fastp_cache`, `_file_mtimes`, `_parse_locks` | `_cache_lock`, `_parse_locks_lock` -- correct |
| `nanometa_live/core/utils/sample_detector.py:21-22` | `_sample_cache` | `_sample_cache_lock` -- correct |
| `nanometa_live/core/utils/offline_cache.py:514` | `_cache_instance_lock` -- correct |
| `nanometa_live/core/utils/alert_engine.py:522-523` | `_alert_engine` | `_alert_engine_lock` -- correct |
| `nanometa_live/core/utils/pathogen_database.py:60` | `_database_lock` -- correct |
| `nanometa_live/core/watchlist/watchlist_manager.py:1568-1579` | `_watchlist_manager` | Double-checked locking with `_wm_lock` -- correct |
| `nanometa_live/core/watchlist/validation/name_normalizer.py:459` | `_normalizer_lock` -- correct |
| `nanometa_live/core/watchlist/validation/confidence_scorer.py:317` | `_scorer_lock` -- correct |
| **`nanometa_live/core/utils/genome_manager.py:1950-1998`** | `_genome_manager` global. `get_genome_manager()` mutates the global with `if _genome_manager is None: _genome_manager = ...`, including the reinit-on-cache-dir-change branch at 1986-1991 and the offline_mode mutation at 1994-1996. **No lock.** | **Missing** |

The `genome_manager` singleton is the only violation. Under Dash's
multi-thread Flask worker model, two simultaneous tab loads each
hitting `get_genome_manager(cache_dir=...)` for the first time can
race: both check `_genome_manager is None`, both construct, the
second overwrites the first, and any in-flight downloads on the
first instance are now orphaned. The pattern in
`watchlist_manager.py:1568-1579` (double-checked locking) is exactly
what should be applied here.

## 6. Test Coverage

```
Pytest result: 775 passed, 1 skipped, 0 failed (776 collected)
Wall time: 56.15s
```

Source vs test ratio:

| Top-level package | Source files | Source files referenced by any test | Untested |
|-------------------|-------------:|-------:|---------:|
| `app/components/` | 10 | 6 | 4 |
| `app/layouts/` | 8 | 1 | 7 |
| `app/tabs/` | 11 | 8 | 3 |
| `app/utils/` | 5 | 4 | 1 |
| `core/utils/` | 19 | 8 | 11 |
| `core/workflow/` | 8 | 6 | 2 |
| `core/parsers/` | 2 | 2 | 0 |
| `core/taxonomy/` | 3 | 1 | 2 |
| `core/watchlist/` | 3 | 3 | 0 |
| `core/config/` | 5 | 4 | 1 |

Concrete coverage gaps that matter most:

- **`nanometa_live/core/utils/genome_manager.py`** -- 2,000+ LOC,
  network-dependent, runs subprocesses, wrote the singleton race
  bug at line 1950, has zero tests.
- **`nanometa_live/core/utils/blast_utils.py`**, **`kraken_utils.py`**,
  **`read_extractor.py`** -- subprocess invokers, all untested.
- **`nanometa_live/core/utils/alert_engine.py`** -- generates the
  Zone 1 verdict banner content (see CLAUDE.md "Dashboard
  Architecture"); behaviour drives operator action; untested.
- **`nanometa_live/core/utils/auto_detect.py`** -- selects sample
  layout (`by_barcode` vs `single_sample` vs `per_file`); a
  misclassification produces empty dashboards; untested.
- **`nanometa_live/app/tabs/dashboard_tab.py`**, **`watchlist_tab.py`**
  -- the two largest user-facing tabs (1,123 + 1,341 LOC); covered
  only obliquely through frontend integration tests.
- **`nanometa_live/core/taxonomy/taxonomy_api.py`**, **`database_indexer.py`**
  -- the entry points for NCBI/GTDB lookups; untested directly.
- **`nanometa_live/core/watchlist/validation/name_normalizer.py`**,
  **`confidence_scorer.py`** -- name-matching logic that drives
  watchlist taxid resolution; zero direct tests.

Smaller layout modules (`config_layout.py`, `dashboard_layout.py`,
etc.) being untested is fine -- they are pure component constructors
with no logic. Only `nanometa_live/app/layouts/main_layout.py` is
a meaningful gap because it owns the `on-demand-validation-target`
and `on-demand-validation-results` stores.

## 7. Security Posture

- **Subprocess invocation:** every subprocess call site reviewed
  uses **list-form** arguments (`subprocess.run([...])`,
  `subprocess.Popen([...])`); no `shell=True` anywhere in the
  source tree. The Nextflow launcher
  (`nanometa_live/core/workflow/nextflow_manager.py:684-691`)
  passes `cmd` as a list; the cmd list itself is built from the
  config dict (validated paths) at lines 477-495, so injection via
  `pipeline_path` would require an attacker to write the config
  YAML, in which case they already have arbitrary code execution.
- **Filesystem path validation:** `qc_tab.py:763-764` resolves both
  base and export path with `os.path.realpath` -- correct guard
  against path-traversal via symlinks.
  `classification_loaders.py:433,451,652` deduplicates kreport file
  lists by realpath -- correct.
- **Filesystem browser:** `nanometa_live/app/tabs/config_tab.py:1112-1199`
  exposes the host filesystem to anyone who can reach the dashboard
  port (callback `toggle_folder_browser` and `update_directory_tree`
  list arbitrary directories the server process can read; hidden
  files filtered, but no chroot, no allowlist). This is the
  intended UX for an operator-controlled local tool, but the
  dashboard binds to an HTTP port; if it is ever exposed to a LAN,
  this becomes a passive disclosure bug. No explicit warning in
  `docs/OPERATOR_GUIDE.md` to bind to localhost only.
- **File upload:** `nanometa_live/app/tabs/watchlist_tab.py:1195-1233`
  decodes the uploaded YAML to `tempfile.NamedTemporaryFile`,
  validates via `loader.validate_file()` before persisting, and
  uses only `Path(filename).suffix` to derive the temp suffix.
  `Path(filename).stem` flows into the destination dir at line 1243
  -- if `filename` were `../../etc/passwd.yaml`, `stem` would be
  `passwd` so the traversal does not land. The validation gate
  catches malformed input. Acceptable.
- **`open()` writes from app code:** only `app.py:102` (default CSS),
  `app.py:144-152` (default empty pixel logo); no user-data writes
  through string-interpolated paths.

Net: no command injection, no obvious arbitrary file write. The
filesystem browser is the only realistic concern and only matters
under a non-default deployment. Documenting "bind to 127.0.0.1
only" in the Operator Guide closes it.

## 8. TODO / FIXME / XXX

Zero TODO, FIXME, XXX, or HACK markers found anywhere in
`nanometa_live/`. This is unusual and probably good --
`docs/audit-2026-04-28-production-readiness.md` and prior cycles
have been keeping the repo cleaner than is normal for a project of
this age.

## 9. Cosmetic / Lower-Priority

- Two `DeprecationWarning` from
  `nanometa_live/core/watchlist/watchlist_manager.py:1278`
  (`datetime.utcnow()`); fix is one line, replace with
  `datetime.now(datetime.UTC)`.
- `nanometa_live/app/app.py:236-248` is a 14-line comment block
  describing the schema of two stores (`aggregate-kraken-cache`,
  `per-sample-kraken-cache`) that no code reads; delete with the
  stores.

---

## Scoring

Weighted average of five sub-scores. Each sub-score is justified
with at least one file:line citation.

| Sub-score | Weight | Score | Justification |
|-----------|-------:|------:|---------------|
| code_quality | 20% | 7.5 | No TODO/FIXME (verified zero), no `except: pass` bare blocks, dead code is bounded to ~6 stores + 1 clientside callback (`nanometa_live/app/app.py:655-669`). The dashboard tab files are large (`preparation_tab.py` 1,832 lines, `config_tab.py` 1,767 lines) but well-organized. Comment block at `app.py:236-248` documents stores that don't function. |
| error_handling | 25% | 6.5 | Most `except Exception` paths log via `logger.exception()` (e.g., `classification_loaders.py:177-183`), but several silently degrade UX -- particularly `main_tab.py:693-694` (empty watchlist on failure), `main_tab.py:1022-1023` (silent `continue` over corrupt validation results), and `dashboard_helpers.py:708-709` (estimator falls back without visible flag). |
| test_coverage | 25% | 6.5 | 775 tests pass with high stability, but key files are untested: `core/utils/genome_manager.py` (2,000 LOC, network + subprocess, race bug at line 1950), `core/utils/alert_engine.py` (drives Dashboard Zone 1 verdict), `core/utils/auto_detect.py`, and `core/utils/blast_utils.py`/`kraken_utils.py`/`read_extractor.py` (subprocess invokers). |
| ux_completeness | 15% | 6.0 | Verdict banner and Stage Strip happy paths are covered, but failure paths in `sync_watchlist` (`main_tab.py:693-694`) and on-demand validation result loading (`main_tab.py:1022-1023`) silently produce empty UI with no toast. The `notification-trigger` store at `app.py:221` exists but is not used by these callbacks. |
| security | 15% | 8.0 | Zero `shell=True`, all subprocess calls use list-form (e.g., `nextflow_manager.py:684-691`, `on_demand_validator.py:249-255`); `qc_tab.py:763-764` validates export paths via `os.path.realpath`. The directory browser at `config_tab.py:1184-1199` exposes the host filesystem to anyone reaching the dashboard port -- intended for local operator use, but no documented bind-to-localhost warning. |

**Production-readiness score: 0.20*7.5 + 0.25*6.5 + 0.25*6.5 +
0.15*6.0 + 0.15*8.0 = 1.50 + 1.625 + 1.625 + 0.90 + 1.20 = 6.85 / 10.**

The codebase is operable in a controlled lab. It is not yet
production-grade for unattended deployment.

---

## Recommended Next-Cycle Fix List

Ordered by ratio of risk reduction to effort:

1. **Add a lock to the `genome_manager` singleton.**
   `nanometa_live/core/utils/genome_manager.py:1950-1998` -- copy
   the double-checked locking pattern from
   `core/watchlist/watchlist_manager.py:1568-1579`. Risk: race
   condition that orphans in-flight downloads. Effort: 10 minutes.

2. **Surface failures in `sync_watchlist` and validation-result
   loading.** `nanometa_live/app/tabs/main_tab.py:683-694` and
   `1015-1023` -- on `Exception`, write to the existing
   `notification-trigger` store at `app.py:221` so the operator
   sees a toast instead of an empty list. Effort: 30 minutes.

3. **Mark estimated stats as estimates.**
   `nanometa_live/app/tabs/dashboard_helpers.py:701-709` -- when
   the kraken-data load fails and the estimator fires, append
   `(estimated)` to the Zone 3 stat label and log at WARNING.
   Effort: 15 minutes.

4. **Delete the six dead stores and the dead clientside callback.**
   `app.py:249-250`, `preparation_layout.py:124-126`,
   `watchlist_layout.py:42`, `app.py:655-669`. Drop the obsolete
   schema comment at `app.py:236-248`. Effort: 20 minutes.

5. **Wire the `download-cancel-flag` and `blast-cancel-flag`
   stores** (or document them as out-of-scope and remove with the
   above). The presence of these stores plus an absent cancel
   button is a UX promise the GUI doesn't keep for a 30-minute
   genome download. Effort: half a day if implemented; 5 minutes
   if removed.

6. **Add a smoke test for `genome_manager.py`** -- at minimum,
   exercise `get_genome_manager()` re-init paths and
   `get_kingdom`/`fetch_*` short-circuit in `offline_mode=True`.
   Effort: 1-2 hours.

7. **Add a smoke test for `alert_engine.py`** -- assert that the
   Zone 1 verdict transitions correctly across the five states
   (ALL CLEAR, ACTION REQUIRED, MONITORING, SCREENING IN
   PROGRESS, STANDBY) given known input dicts. Effort: 1-2 hours.

8. **Document operator-deployment binding.** Add a note in
   `docs/OPERATOR_GUIDE.md` that the dashboard exposes a
   filesystem browser by design and must be bound to `127.0.0.1`
   on shared networks. Effort: 5 minutes.

9. **Replace `datetime.utcnow()`** at
   `core/watchlist/watchlist_manager.py:1278`. Effort: 1 minute.

Items 1-4 are blocking for a high-confidence v2.0 release; items
5-8 are second-order and can flow into the next throughput cycle.

---

## Anti-Fabrication Verification

Three claims selected at random and re-verified before submission
by direct file read (no `cat`; the `Read` tool was used):

1. **Claim:** `aggregate-kraken-cache` declared at
   `nanometa_live/app/app.py:249` and never read.
   **Verification:** Read of `app.py:200-250` confirmed the
   declaration at line 249. A repo-wide
   `grep -rn "aggregate-kraken-cache" nanometa_live/ --include="*.py"`
   returned exactly four hits, all in `app.py:241-250`, none in any
   callback. **Verified.**

2. **Claim:** `nanometa_live/app/tabs/validation_tab.py:505` is a
   bare `except Exception: pass` after a `sorted()` call.
   **Verification:** Read of `validation_tab.py:498-507` confirmed
   the literal text `except Exception:` at line 505 followed by
   `pass` at line 506, immediately after a `sorted(results, ...)`
   call at lines 500-504. **Verified.**

3. **Claim:** Dead clientside callback at
   `nanometa_live/app/app.py:655-669` references IDs
   `dashboard-watchlist-collapse` and `dashboard-watchlist-expand-btn`
   that exist nowhere else.
   **Verification:** Read of `app.py:650-669` confirmed the
   `app.clientside_callback` block with `Output("dashboard-watchlist-collapse", "is_open")`
   at line 664 and `Output("dashboard-watchlist-expand-btn", "children")`
   at line 665. A repo-wide
   `grep -rn "dashboard-watchlist" nanometa_live/ --include="*.py"`
   returned only those four lines (664, 665, 667, 668). **Verified.**

All three stand. No claim was dropped or marked unverified.
