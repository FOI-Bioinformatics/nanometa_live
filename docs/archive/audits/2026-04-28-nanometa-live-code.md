# Nanometa Live Python Audit -- 2026-04-28

## Summary

- Total findings: 22 (P0: 2, P1: 8, P2: 12)
- Highest-impact issue: **P0-01** -- the `download_kraken_database` callback in `preparation_tab.py` issues an unguarded HTTPS request when the operator clicks "Download" while in `offline_mode`. The dashboard is targeted at field labs that lose network mid-run; this can hang the background callback for the full request timeout and emit an outbound request that may be blocked by lab firewalls. Every other operator-facing action is offline-mode-aware; this one path was missed in cycle 17.
- Bundled secondary risk: **P0-02** -- `ReadinessChecker._check_network_connectivity` always probes NCBI/GTDB even when the user has set `offline_mode: true`. On an air-gapped field machine the probe blocks the readiness panel for ~10s per endpoint while it times out, and surfaces a `WARNING` that operators are trained to treat as actionable.
- ~2,000 lines of dead code remain from the v1 -> v2 refactor (eight modules with no live callers). Most are listed in CLAUDE.md's "Quick Reference" but were never deleted.

## P0 (blocking)

### [P0-01] Kraken2 DB download callback bypasses offline_mode

**File:** `nanometa_live/app/tabs/preparation_tab.py:1899-1937`

**Issue:** The background callback `download_kraken_database` reads `app-config` State at line 1904 but never checks `config.get("offline_mode")` before invoking `kraken_utils.download_kraken_database(db_info, dest_dir)`. The downstream function (`core/utils/kraken_utils.py:50`) opens an HTTPS stream to `db_info["database_url"]` with `requests.get(..., timeout=60)`. On an air-gapped machine the request blocks the background-callback worker for the full 60s before raising, and the operator sees a generic "Download failed" alert with no clear remediation.

**Impact:** Run-blocking. Field operators who hit "Download Kraken2 Database" while offline get a 60s UI freeze in the Preparation tab, the diskcache background worker holds the slot, and any concurrent background callback (genome download, blast build) queues behind it. Worse, on a partially-connected lab network the request can succeed *partially*, leaving a corrupt tar.gz that the verify step then has to detect.

**Fix:** Mirror the pattern used by `validate_entries` (watchlist_tab.py:841) and `lookup_species` (watchlist_tab.py:989) -- read `offline_mode = bool((config or {}).get("offline_mode", False))`, return an `Alert(color="warning")` early when offline. Apply the same guard at the top of `kraken_utils.download_kraken_database` itself so any other caller is also protected.

### [P0-02] Readiness network probe ignores offline_mode

**File:** `nanometa_live/core/workflow/readiness_checker.py:171, 621-647`

**Issue:** `check_readiness` unconditionally calls `self._check_network_connectivity()`, which opens `urllib.request.urlopen` against `https://eutils.ncbi.nlm.nih.gov/...` and `https://api.gtdb.ecogenomic.org/` with a 5s timeout each. The `config` dict is in scope at line 171 but is never inspected. In offline mode this fires twice on every readiness panel refresh, blocks for up to 10s per panel render, and emits a `Severity.WARNING` "NCBI API unreachable. Genome downloads may fail." that operators reading the report treat as a real fault.

**Impact:** Operator-blocking. Readiness is the first screen field staff hit after import_bundle. CLAUDE.md cycle 17 calls out that offline_mode hardening must reach NCBI/GTDB callers; this one was missed because it predates the GenomeManager work.

**Fix:** Add `if config.get("offline_mode"): return [CheckResult("Network", True, Severity.INFO, "Offline mode -- network probe skipped")]` at the top of `_check_network_connectivity()`. Or skip the call entirely in `check_readiness` when offline. Either way, the probe must not run with `offline_mode: true`.

## P1 (affecting)

### [P1-01] `validate_taxid_source` does not propagate offline_mode

**File:** `nanometa_live/core/taxonomy/taxonomy_api.py:749-785`

**Issue:** Module-level helper `validate_taxid_source(taxid)` calls `get_ncbi_client()` and `get_gtdb_client()` with no `offline_mode` argument (lines 762-763), so it always uses whatever offline state the singletons happen to be in. Singletons are normally configured at app start via `_init_offline_mode`, so it is *probably* fine in practice, but if any caller is invoked before `_init_offline_mode` (or in a test fixture), the lookup hits the live API.

**Impact:** Latent risk. Currently the function has zero call sites in the codebase. If reintroduced without an audit it will silently bypass offline mode.

**Fix:** Either add an `offline_mode: bool = False` parameter and forward it to the two `get_*_client()` calls, or remove the function and its tests entirely.

### [P1-02] `update_qc_plots` proceeds without a config guard, returning empty plots silently

**File:** `nanometa_live/app/tabs/qc_tab.py:200-218`

**Issue:** When `config` is `None` the callback uses the ternary `(config.get(...) if config else "")` to produce an empty string, then short-circuits at line 216. That works -- but it returns `_get_empty_qc_figures()` (three blank Plotly figures) on every interval tick when the user has not yet loaded a config, instead of `raise PreventUpdate`. This trips Dash's prop diff and re-renders three plots per tick. The same pattern repeats in `update_qc_stats` (line 458), `update_per_sample_table` (line 791), `update_base_quality_card` (line 832), and `update_read_statistics_card` (line 939).

**Impact:** Performance. ~5 unnecessary re-renders per tab per interval tick on a fresh app start. Also masks misconfiguration: a missing `main_dir` looks identical to "no data yet".

**Fix:** Add `if not config or not config.get("results_output_directory") and not config.get("main_dir"): raise PreventUpdate` at the top of each interval-driven QC callback. Use the same pattern dashboard_tab.py:258-267 already uses (`_should_load_data`).

### [P1-03] `_init_offline_mode` runs before config is loaded -- only fires once

**File:** `nanometa_live/app/app.py:48-62, 561-564`

**Issue:** `_init_offline_mode(offline)` runs once during `create_app()` from the static `config['offline_mode']` value baked into the Dash store at startup. If the user later toggles offline_mode in the Configuration tab and clicks Save (config_tab.py:1626), the singletons (`_ncbi_client`, `_gtdb_client`, `_genome_manager`) are *not* re-initialised. They stay on the original mode. Subsequent API lookups go to the network even though the user thinks they are offline.

**Impact:** Operator-confusing. The offline_mode toggle in the UI is effectively cosmetic until the user restarts the app.

**Fix:** Add a callback on `Output("app-config", "data")` change that calls `_init_offline_mode(new_config.get("offline_mode", False))`. Or have `get_ncbi_client/get_gtdb_client/get_genome_manager` re-read the live mode each call (the existing if-mode-changed path at line 733-734 of `taxonomy_api.py` already supports this; just ensure the watchlist Validate / Add-custom-species callbacks pass the *current* `config["offline_mode"]`, not a cached one). watchlist_tab.py already does this correctly; the GenomeManager calls inside preparation_tab.py do not.

### [P1-04] `core.config.config_manager.ConfigManager` exists but is never instantiated

**File:** `nanometa_live/core/config/config_manager.py` (181 lines), exported at `nanometa_live/core/config/__init__.py:8`

**Issue:** Top-level `ConfigManager` class with `__init__`, `validate`, `update`, `get_config` methods is wired up in the package init and `__all__` but has zero instantiations or imports anywhere. Live config-state management is done entirely by `app/utils/config_manager.py::ConfigUpdateManager`. The two classes have very similar shapes and confusingly-similar names; new contributors will land on the wrong one.

**Impact:** Dead code, plus a discoverability trap.

**Fix:** Delete `nanometa_live/core/config/config_manager.py`, drop the import at `core/config/__init__.py:8`, and trim the entry from `__all__`.

### [P1-05] `data_utils.py` is fully orphaned legacy v1 code

**File:** `nanometa_live/core/utils/data_utils.py` (292 lines)

**Issue:** Functions `parse_kraken_report`, `parse_kraken_output`, `parse_fastq_file`, `parse_fastp_report`, `parse_blast_results`, `extract_classified_reads` have zero call sites anywhere in `nanometa_live/` or `tests/`. The same names exist as method-functions on `NanometaParser` (parsers/nanometanf_parser.py) and the new modular loaders, with different signatures. The module is only reachable via `from nanometa_live.core.utils import *` at `core/utils/__init__.py:9`.

**Impact:** Dead code (~290 lines). Maintenance burden because the duplicate name `parse_kraken_report` collides with `kraken_utils.parse_kraken_report` (a different function with different return type) when both are star-imported.

**Fix:** Delete `data_utils.py` and remove the `from nanometa_live.core.utils.data_utils import *` line at `core/utils/__init__.py:9`.

### [P1-06] `database_utils.py`, `safe_path.py`, `watchlist_manager_ui.py`, `tooltip_components.py` have no callers

**Files:**
- `nanometa_live/core/utils/database_utils.py` (342 lines)
- `nanometa_live/core/utils/safe_path.py` (52 lines)
- `nanometa_live/app/components/watchlist_manager_ui.py` (22 lines, just a docstring stub)
- `nanometa_live/app/components/tooltip_components.py` (433 lines, eight component functions)

**Issue:** None of the public symbols in these four modules are imported anywhere in `nanometa_live/` or `tests/`. CLAUDE.md still references `tooltip_components.py` and `watchlist_manager_ui.py` as live components (lines 24-25 of CLAUDE.md), so the documentation also lies.

**Impact:** ~850 lines of dead code; misleading docs.

**Fix:** Delete the four files. Update CLAUDE.md "Quick Reference" tree.

### [P1-07] Dead component re-exports in `app/components/__init__.py`

**File:** `nanometa_live/app/components/__init__.py:39-94`

**Issue:** Six component symbols are re-exported by `__init__.py` but only used inside the package (i.e., only the `__init__.py` itself or the components' own files reference them):
- `FilteringBreakdownVisual` (organism_components.py:545) -- CLAUDE.md cycle 4 explicitly notes this was a "bug vector in earlier layouts" and was supposed to be removed.
- `KeyMetricsSummaryCard` (organism_components.py:914) -- same, "triple-count source" per CLAUDE.md.
- `QualityScoreIndicator` (organism_components.py:728)
- `ThreatSummaryIndicator` (pathogen_alert.py:668)
- `N50Badge` (modern_components.py:570) -- replaced by plain-language "Read Length" per cycle 4 rename.
- `TrendIndicator` (modern_components.py:823)
- `DecisionBanner` (modern_components.py:848) -- replaced by Zone 1 verdict banner per cycle 5.

**Impact:** ~700 lines of dead UI code, plus import-time cost on every app startup.

**Fix:** Delete each function and its corresponding `__init__.py` entry. The seven names listed above can be removed without breaking any layout.

### [P1-08] Loader re-exports in `data_loaders.py` are partly dead

**File:** `nanometa_live/core/utils/data_loaders.py:13-72`

**Issue:** Three re-exports have no caller outside the re-export hub itself:
- `check_data_freshness` (loader_utils.py:261)
- `get_last_freshness_fingerprint` (loader_utils.py:295)
- `_fastp_cache` is imported in `qc_loaders.py:22` but never used (no read or write anywhere in that module; only `_kraken_cache` is touched, and only in `classification_loaders.py`).

The freshness functions are described in their docstrings as "intended to be called once per polling interval by a single centralized callback" -- that callback was never written. CLAUDE.md cycle 1-2 mentions the cache infrastructure but no tab uses the freshness fingerprint to short-circuit loads.

**Impact:** Latent bug -- the cleanup path inside `check_data_freshness` (line 290) is the only place `_cleanup_stale_cache_entries` gets called from outside `_cleanup_stale_cache_entries`'s own module. Since the function never runs, the kraken/fastp cache only cleans up via the size cap at `CACHE_MAX_ENTRIES=100`, never via TTL.

**Fix:** Either wire `check_data_freshness` into a single core callback (e.g. `app/callbacks.py` on the `update-interval` Input) and have it tick `_cleanup_stale_cache_entries`, or move the cleanup call into the per-loader hot paths so TTL eviction actually happens. Drop `_fastp_cache` from the `qc_loaders.py` import list.

## P2 (polish)

### [P2-01] `core/utils/__init__.py` does `from X import *` for legacy modules

**File:** `nanometa_live/core/utils/__init__.py:8-11`

**Issue:** `data_utils.py`, `file_utils.py`, `blast_utils.py`, `kraken_utils.py` are all star-imported into the package namespace. Most of those modules' contents are unused (see P1-05, P1-06 for `data_utils` and the file_utils orphan check). The star imports also pull in `pd`, `subprocess`, `tarfile`, etc. as module-level names on `core.utils`, which silently masks any caller that meant to import them directly.

**Fix:** Replace each `from X import *` with explicit imports of the small set of functions that *are* used (`verify_kraken_db`, `inspect_kraken_db`, `download_kraken_database` from `kraken_utils`; nothing else from `data_utils`/`file_utils`/`blast_utils`).

### [P2-02] `blast_utils.py` and `database_utils.py` are mostly unused

**Files:**
- `nanometa_live/core/utils/blast_utils.py` (318 lines)
- `nanometa_live/core/utils/database_utils.py` (342 lines)

**Issue:** Of the five public functions in `blast_utils.py` (`build_blast_databases`, `check_blast_dbs_exist`, `run_blast_validation`, `count_validated_reads`, `get_blast_validation_summary`), only `count_validated_reads` is referenced internally (line 308). All BLAST validation now happens via `OnDemandValidator` (`core/workflow/on_demand_validator.py`). Similarly, `database_utils.py`'s four public functions are all unreachable. Both modules predate the v2 refactor.

**Fix:** Delete both files. Update `core/utils/__init__.py` accordingly.

### [P2-03] `large block` of `file_utils.py` functions are unused

**File:** `nanometa_live/core/utils/file_utils.py` (425 lines)

**Issue:** Of `ensure_directory`, `clean_path`, `copy_file`, `extract_archive`, `download_file`, `calculate_file_hash`, `get_file_list`, `read_file_lines`, `write_file_lines`, `remove_temp_files`, `create_temp_directory`, `get_most_recent_file`, `check_command_exists` -- none have call sites outside the module itself. The hits on `remove_temp_files` in `parameter_mapping.py` are a config-key string, not a function call.

**Fix:** Audit which (if any) functions in `file_utils.py` are actually used and delete the rest. Best guess: zero callers, full delete.

### [P2-04] Dead store `kraken-databases` propagation

**File:** `nanometa_live/app/app.py:196` and `nanometa_live/app/tabs/preparation_tab.py:670, 1898`

**Issue:** The `kraken-databases` dcc.Store is populated from a YAML at app-start (app.py:78-83) but only ever read once: by `download_kraken_database` (preparation_tab.py:1898) which itself bypasses offline_mode (see P0-01). The other Input at preparation_tab.py:670 just feeds a dropdown options builder. There is no callback that updates the store; it is read-only after page load.

**Fix:** Convert `kraken-databases` from a dcc.Store to a module-level constant or pass it directly into the layout function. Saves one round-trip serialization.

### [P2-05] Dead `dcc.Store` ID `pathogen-report-data`

**File:** `nanometa_live/app/app.py:366`

**Issue:** Verified via grep that no callback reads or writes `pathogen-report-data`. It is initialised to `{}` and never touched after.

**Fix:** Remove the store. If the pathogen modal needs persistent state, wire it up; otherwise drop the empty store.

### [P2-06] Unhelpful `except Exception:` swallows in tab callbacks

**Files:**
- `nanometa_live/app/tabs/main_tab.py:692`, `1021`
- `nanometa_live/app/tabs/watchlist_tab.py:44`, `532`
- `nanometa_live/app/tabs/dashboard_tab.py:2012`
- `nanometa_live/app/tabs/validation_tab.py:238`
- `nanometa_live/app/tabs/config_tab.py:1386`

**Issue:** Each of these is a bare `except Exception:` (no logging, no traceback) followed by `return []` / `continue` / `return no_update`. Operators staring at a blank Organisms tab cannot tell whether the watchlist failed to load (main_tab.py:692) or whether the data is empty. The dashboard fallback at line 2012 silently substitutes an *estimated* classification rate, which is wrong-by-default behaviour for a clinical dashboard.

**Fix:** Replace each with `except Exception:\n    logger.exception("...")` and pick a typed exception list when the failure modes are known. main_tab.py:1021 is reading `os.path.join(od_dir, f)` JSON files; a `(json.JSONDecodeError, OSError)` typed catch would be correct.

### [P2-07] `nextflow_manager._check_singularity_available` swallows errors silently

**File:** `nanometa_live/core/workflow/nextflow_manager.py:130-154`

**Issue:** When `singularity --version` fails with `subprocess.TimeoutExpired`, the function returns immediately with a "timed out" message (line 145-146), but when it fails with `subprocess.CalledProcessError` it logs and `continue`s to try `apptainer` (line 147-149). The asymmetry means a slow Singularity install hides Apptainer.

**Fix:** Make the timeout case also `continue`. Consistent semantics: any failure of `<tool> --version` -> try the next tool; only return failure when *both* options exhausted.

### [P2-08] No tests for `BundleManager`, `MobileLabPreparer`, or `OnDemandValidator` offline guards

**Files:** `tests/test_bundle_manager.py`, `tests/test_e2e_scenarios.py`

**Issue:** Existing bundle tests (9 tests per CLAUDE.md cycle 17) cover bundle round-tripping but do not assert that the bundle's `import_bundle` rewrites `pipeline_source` to the absolute path of `pipeline_source/`. The tests also do not cover the platform-mismatch warning path (`build_platform != current_platform`). For `OnDemandValidator`, the offline_mode check is missing entirely (it accepts a `config` dict but does not consult `offline_mode`).

**Fix:** Add tests:
- `test_import_bundle_rewrites_pipeline_source_to_absolute_path`
- `test_import_bundle_warns_on_platform_mismatch`
- `test_on_demand_validator_refuses_offline_when_genome_missing`

### [P2-09] No test files for several production modules

**Files (in production but no `tests/test_<module>.py`):**
- `nanometa_live/core/workflow/mobile_lab_preparer.py` (181 lines, lifecycle orchestration)
- `nanometa_live/core/workflow/on_demand_validator.py` (~700 lines including read-extract + BLAST + minimap2 paths)
- `nanometa_live/core/workflow/pipeline_runner.py`
- `nanometa_live/core/workflow/backend_manager.py` (lock acquisition / release, stale-lock detection)
- `nanometa_live/core/utils/genome_manager.py` (1998 lines, kingdom routing, GTDB/NCBI fallbacks)
- `nanometa_live/core/utils/alert_engine.py` (per-sample attribution)
- `nanometa_live/core/utils/read_extractor.py`
- `nanometa_live/core/parsers/nanometanf_parser.py` (has tests, but the validation summary and FASTP edge cases are not covered)

**Fix:** Add at minimum a smoke test per module (instantiation + happy-path call). `genome_manager` and `alert_engine` are highest-priority because they have the most behavioural complexity and the most direct operator impact.

### [P2-10] `pre-warm` scenario references a remote tar.gz at build time

**File:** `nanometa_live/core/workflow/bundle_manager.py:195-209` (scenario `untar_kraken2_db`)

**Issue:** The pre-warm scenario hard-codes `https://raw.githubusercontent.com/nf-core/test-datasets/...kraken2.tar.gz`. This is a build-time URL on the technician's machine, so it's expected to have network -- but if GitHub is unreachable during the bundle build, this scenario fails silently and the field machine ends up missing the UNTAR conda env. A failed pre-warm scenario currently writes a warning to manifest.json but does not abort the build.

**Fix:** Either ship a tiny stub tar.gz inside the package (`nanometa_live/core/data/test_kraken2.tar.gz`) and reference it via `file://`, or fail the build hard when `pre_warm_conda_envs=True` is requested and any scenario fails.

### [P2-11] `qc_tab.py` keeps one `iterrows()` call

**File:** `nanometa_live/app/tabs/qc_tab.py:259`

**Issue:** `for _, row in seqkit_df.iterrows()` in the seqkit fallback path. CLAUDE.md cycle 1-2 says all `iterrows()` were vectorized; this one slipped through. Same loop is open in `core/export/report_generator.py:167`.

**Fix:** Replace with `seqkit_df.assign(...).to_dict(orient="records")` or vectorized column access. Negligible perf impact for 6-12 rows but consistent style.

### [P2-12] `parameter_mapping.py` `_get_command_version` regex doesn't anchor

**File:** `nanometa_live/core/workflow/bundle_manager.py:1413-1438`

**Issue:** `_get_command_version(command, args)` returns the first non-empty line of stdout+stderr -- but for some tools (`makeblastdb -version` prints two-line output: `makeblastdb: 2.14.0+\n  Package: blast 2.14.0...`), this picks up `makeblastdb: 2.14.0+` which is fine, but `blastn` does the same and the line gets truncated to 100 chars (line 1430). Manifest readability suffers.

**Fix:** Add a tool-specific regex pass like `_get_nextflow_version` does. Low priority -- manifest is informational only.

## Coverage map

| Module | Test file | Status |
|---|---|---|
| `core.config.config_loader` | `test_parameter_mapping.py`, `test_e2e_scenarios.py` | covered |
| `core.config.config_manager` (ConfigManager) | -- | dead module (P1-04) |
| `core.config.config_validator` | `test_parameter_mapping.py` | covered |
| `core.config.parameter_mapping` | `test_parameter_mapping.py` | covered |
| `core.config.pathogen_loader` | `test_e2e_scenarios.py` (indirect) | thin |
| `core.parsers.blast_validation_parser` | `test_validation_system.py` | covered |
| `core.parsers.nanometanf_parser` | `test_nanometanf_parser.py` | covered |
| `core.parsers.paf_coverage_parser` | `test_paf_parser.py` | covered |
| `core.taxonomy.database_indexer` | `test_strategy_priorities.py` (indirect) | thin |
| `core.taxonomy.taxid_mapping` | `test_strategy_priorities.py` | covered |
| `core.taxonomy.taxonomy_api` | -- | gap |
| `core.utils.alert_engine` | -- | gap (P2-09) |
| `core.utils.auto_detect` | -- | gap |
| `core.utils.blast_utils` | -- | dead module (P2-02) |
| `core.utils.canonical_loaders` | `test_canonical_loaders.py` | covered |
| `core.utils.classification_loaders` | `test_classification_loaders.py` | covered |
| `core.utils.data_loaders` (re-export) | `test_data_loaders.py` | covered |
| `core.utils.data_utils` | -- | dead module (P1-05) |
| `core.utils.database_utils` | -- | dead module (P2-02) |
| `core.utils.file_utils` | -- | dead module (P2-03) |
| `core.utils.genome_manager` | -- | gap (P2-09) |
| `core.utils.kraken_utils` | -- | gap |
| `core.utils.language_utils` | -- | gap |
| `core.utils.loader_utils` | `test_data_loaders.py` (indirect) | thin |
| `core.utils.offline_cache` | -- | gap |
| `core.utils.qc_loaders` | `test_qc_loaders.py`, `test_qc_loaders_horizon.py`, `test_seqkit_loader_layouts.py` | covered |
| `core.utils.read_extractor` | -- | gap |
| `core.utils.safe_path` | -- | dead module (P1-06) |
| `core.utils.sample_detector` | `test_sample_detector.py` | covered |
| `core.utils.validation_loaders` | `test_validation_system.py`, `test_integration_data_flow.py` | covered |
| `core.watchlist.watchlist_loader` | `test_watchlist_loader.py` | covered |
| `core.watchlist.watchlist_manager` | `test_watchlist_validation.py` | covered |
| `core.watchlist.taxonomy_matcher` | -- | gap |
| `core.watchlist.validation.match_strategies` | `test_strategy_priorities.py` | covered |
| `core.watchlist.validation.confidence_scorer` | -- | gap |
| `core.watchlist.validation.name_normalizer` | -- | gap |
| `core.workflow.backend_manager` | `test_realtime_timeout_config.py` | thin (P2-09) |
| `core.workflow.bundle_manager` | `test_bundle_manager.py` | thin (P2-08) |
| `core.workflow.mobile_lab_preparer` | -- | gap (P2-09) |
| `core.workflow.nextflow_manager` | `test_realtime_timeout_config.py` | thin |
| `core.workflow.on_demand_validator` | -- | gap (P2-09) |
| `core.workflow.pipeline_runner` | -- | gap |
| `core.workflow.readiness_checker` | `test_readiness_checker.py` | covered |
| `app.callbacks` | -- | gap |
| `app.tabs.classification_tab` | `test_classification_tab.py`, `test_sunburst_tax_levels.py` | covered |
| `app.tabs.dashboard_tab` | -- | gap |
| `app.tabs.kraken2_helpers` | `test_classification_tab.py` (indirect) | thin |
| `app.tabs.main_tab` | `test_main_tab.py` | covered |
| `app.tabs.preparation_tab` | -- | gap |
| `app.tabs.qc_tab` | `test_qc_tab.py` | covered |
| `app.tabs.validation_tab` | `test_validation_system.py` (indirect) | thin |
| `app.tabs.watchlist_tab` | `test_watchlist_validation.py` (indirect) | thin |
| `app.components.tooltip_components` | -- | dead module (P1-06) |
| `app.components.watchlist_manager_ui` | -- | dead module (P1-06) |
| `app.components.coverage_plots` | `test_visualization_integration.py` (indirect) | thin |
| `app.components.modern_components` | `test_ux_components.py` | covered (with dead exports flagged P1-07) |
| `app.components.organism_components` | -- | gap |
| `app.components.pathogen_alert` | -- | gap |
| `app.utils.callback_helpers` | -- | gap |
| `app.utils.export_utils` | -- | gap |

---

End of audit.
