# Three-part audit -- 2026-04-29 (master index)

Trigger: operator request for an audit + score of nanorunner, nanometanf, and
nanometa_live, focused on orphan code, simplification opportunities, Dash 4
compliance, conda-profile health for the Nextflow backend, and nf-core best
practices.

Method: four parallel agents, each reporting with file:line citations
verified by Read or grep. Per-repo full reports are linked below; this
file is the cross-repo synthesis and recommended fix order.

## Per-repo full reports

| Repo | Report path |
|------|-------------|
| nanorunner | `/Users/andreassjodin/Code/nanorunner/docs/audit-2026-04-29-orphans-simplification.md` |
| nanometanf | `/Users/andreassjodin/Code/nanometanf/docs/audit-2026-04-29-orphans-simplification.md` |
| nanometa_live (code) | `docs/audit-2026-04-29-orphans-simplification.md` |
| nanometa_live (UX) | `docs/audit-2026-04-29-ux-ui.md` |

## Aggregate scores

| Part | Score | Headline |
|------|-------|----------|
| nanorunner | **42/60 (70%)** | Sound architecture, transitional-refactor cruft, broken `bin/` shim |
| nanometanf | **47/70 (67%)** | Conda profile resolves but 12 modules miss directive; 200 lint warnings; orphan realtime/optimization stack |
| nanometa_live (code) | **51/80 (64%)** | Dash 4 migrated; ~2,300 LoC orphan; zero `Patch()` adoption |
| nanometa_live (UX) | **35/70 (50%)** | Tier/token/layer drift; **WCAG AA failures** in two widely-used color tokens |

Combined nanometa_live: **86/150 (57%)** -- the front-end is the lowest-scoring
part by margin, with the UX dimension as the floor.

## Highest-impact findings (cross-repo)

### P0 -- correctness + accessibility

1. **WCAG AA failures (nanometa_live UX).** `text-warning` (`#ffc107` on
   white, ~1.6:1) and `text-danger` (`#dc3545` on `#f8d7da`, ~3.6:1)
   fail the contrast floor on widely-used surfaces:
   - `app/layouts/validation_layout.py:52,587` (validation status text)
   - `app/components/pathogen_alert.py:514` (HighRiskPathogenAlert body)
   One audit-and-replace pass closes most failures.

2. **`bin/nanopore-simulator` is broken (nanorunner).**
   `bin/nanopore-simulator:5` imports `from nanopore_simulator.cli.main
   import main`; `cli` is a module not a package. `MANIFEST.in:5` ships
   the script in sdists, so anyone installing from PyPI gets a
   `ModuleNotFoundError`. The actual entry point is `pyproject.toml:41`.

3. **12 nanometanf local modules lack a `conda` directive.** The user
   explicitly asked for conda-profile completeness. Modules:
   `MERGE_BARCODE_FASTQ`, `STREAMING_REALTIME_OPTIMIZER`,
   `DYNAMIC_RESOURCE_SCALER`, `MEMORY_EFFICIENT_PROCESSOR`, the
   `apptainer/` family, and others. Most are pure-bash glue so adding
   the directive is mechanical -- but until they have one, `nf-core
   lint` flags `process_no_conda` and offline pre-warming via
   `BundleManager` may skip them.

### P1 -- orphan code (verified deletions)

| Repo | Orphan | Lines | Notes |
|------|--------|-------|-------|
| nanometa_live | `app/utils/chart_builders.py` | 1356 | 17 functions, 0 production callers |
| nanometa_live | `core/parsers/nanometanf_parser.py` | 1122 | tests-only consumer |
| nanometa_live | `app/components/tooltip_components.py` | 433 | 8 fns, 0 callers |
| nanometa_live | `app/utils/export_utils.py` | 336 | re-exported, 0 callers |
| nanometa_live | `core/utils/database_utils.py` | 342 | 0 importers |
| nanometa_live | `app/components/sample_selector.py` | 141 | inline replacement at `app/app.py:292-301` |
| nanometa_live | `core/utils/safe_path.py` | 52 | 0 importers |
| nanometa_live | retired `FilteringBreakdownVisual` / `KeyMetricsSummaryCard` / `QualityScoreIndicator` | ~600 | already documented as "removed" in CLAUDE.md but still resident |
| nanometanf | `subworkflows/local/realtime_optimization/` | -- | not imported by active workflow |
| nanometanf | `workflows/nanometanf.nf` | 1500+ | superseded by `realtime_nanopore.nf` |
| nanometanf | `subworkflows/local/realtime_kraken2_processing/main.nf` | -- | inlined into realtime_nanopore.nf |
| nanorunner | `_WORKER_GENOME_CACHE` / `_init_worker_genomes` (`generators.py:41-55`) | ~15 | claims ProcessPoolExecutor; runner uses ThreadPoolExecutor |
| nanorunner | `ProgressMonitor.pause/resume/is_paused/wait_if_paused` (`monitoring.py:265-281`) | ~17 | advertised in README, not wired into runner |
| nanorunner | `cli.py:138-147` re-export shim | ~10 | only test callers |
| nanorunner | `BuiltinGenerator._write_fastq` (`generators.py:600-623`) | ~24 | tests only |

Cross-repo orphan total: roughly **5,500 lines** of code that can be deleted
or relocated to test fixtures without behaviour change.

### P1 -- Dash 4 modernization (nanometa_live)

1. **Adopt `Patch()` for AgGrid row updates** at four call-sites
   (`app/tabs/main_tab.py:301`, `app/tabs/dashboard_tab.py:679`,
   `app/tabs/qc_tab.py:806`, `app/tabs/validation_tab.py:493`).
   Current code resends full `rowData` every 30-second interval tick,
   blowing sort/filter/selection state and adding flicker. Highest
   single-fix UX win available.

2. **Convert 14 callbacks from legacy list-wrapped `[Input(...)]`
   form** to comma-separated args. Cosmetic today, Dash 5 risk later.

3. **Route 24 `update-interval` consumer callbacks through the cache
   stores** `aggregate-kraken-cache` / `per-sample-kraken-cache` that
   already exist at `app/app.py:248-249`. Today most consumer callbacks
   re-parse Kraken reports per tick; routing through the fingerprinted
   stores means downstream work fires only on real change.

### P1 -- nf-core compliance (nanometanf)

1. **Schema/param drift**: 11 `params.X` declarations in `nextflow.config`
   missing from `nextflow_schema.json` -- `wf`, `realtime`, `qc`,
   `taxpasta`, `assembly`, `validation`, `igenomes_base`,
   `igenomes_ignore`, etc. `--validate_params` may pass while runtime
   misuses these.
2. **152 TODO markers** flagged by `pipeline_todos`. Mid-template-migration
   evidence; some hide real gaps.
3. **`actions_ci`**: `.github/workflows/ci.yml` references `dev` /
   `master` branches that do not match this repo's main branch.
4. **`nfcore_yml` template drift**: declared `nf_core_version 3.4.0`,
   lint runs with 3.5.0.

### P2 -- UX polish (nanometa_live)

1. **Tier drift on alert cards**: 3px / 4px / 6px left-border thickness
   across `pathogen_alert.py:551,620`, `validation_layout.py:644`,
   `organism_components.py:1432`, Stage Strip slots in `assets/styles.css:3673`.
2. **Border-radius spread**: 3px / 4px / 6px / 8px / 12px on cards in
   the same flow.
3. **Amber token split**: CLAUDE.md locks `#664d03`; some tables use
   `#856404` (`dashboard_layout.py:254`, `validation_layout.py:211`).
4. **Verdict banner full border** (`dashboard_tab.py:1591`,
   `dashboard_layout.py:87`) instead of left-border accent that
   CLAUDE.md specifies.
5. **British/American mix**: "Analyse" (`modern_components.py:34`) vs
   "Analyzed" (`dashboard_layout.py:56,123,136,279`).
6. **Same metric, two names**: "Match Quality" on BLAST result card
   (`validation_layout.py:599`) vs "Match %" in BLAST stats table
   (`validation_layout.py:196`).

### P2 -- documentation drift

- nanorunner test counts in `docs/README.md:42` and `CLAUDE.md:277`
  state 722/92%; reality is 730/88% (`pytest --collect-only`).
  `pytest.ini:14` has `--cov-fail-under=90` -- a clean CI run today
  would fail on coverage.

## Recommended fix order

1. **nanometa_live UX accessibility** (text-warning / text-danger
   replacements; full-border verdict banner -> left-border).
   Single audit-and-replace pass per token. Zero risk to logic.
2. **nanorunner `bin/nanopore-simulator` fix** (one-line import
   correction). Unblocks any sdist install.
3. **nanometanf 12 missing conda directives.** Mechanical add to
   modules.config or to each module's main.nf. Mandatory before the
   conda-profile is offline-bundle-ready.
4. **Schema/param drift fix** in nanometanf. Add the 11 missing entries
   to `nextflow_schema.json` or remove the orphan params.
5. **Orphan-code deletion sweep** across all three repos. Group into
   per-repo branches. Start with the high-confidence deletions
   (nanorunner `_WORKER_GENOME_CACHE`, nanometa_live retired card
   classes, nanometanf `realtime_optimization` subworkflow). Run full
   test suites between each branch.
6. **Dash 4 `Patch()` adoption** at the four AgGrid call-sites.
   Single coordinated PR; needs interaction-state regression testing.
7. **Tab-file split** of `dashboard_tab.py` and `preparation_tab.py`.
   Higher-touch refactor; bundle with the orphan deletion to amortise
   test-suite churn.
8. **UX polish pass** (tier / token / radius standardisation, copy
   normalisation). Lowest priority because it is cosmetic, but highest
   visibility once the rest is done.

## Risks (do not simplify these)

- **nanometanf `realtime_optimization` subworkflow** is technically
  orphan today, but the user has flagged real-time mode at amplicon
  scale as an open concern (`docs/audit-2026-04-29-short-amplicons.md`).
  Confirm there is no plan to revive it before deleting.
- **nanometa_live `core/parsers/nanometanf_parser.py`** is tests-only
  but the tests do exercise the public canonical-output contract;
  deletion would lose that coverage. Migrate the tests to the actual
  loaders before deletion.
- **nanometa_live re-exports** in `app/utils/__init__.py` and
  `core/parsers/__init__.py` may be consumed by external scripts not
  visible in this repo. Search the operator's deployment scripts
  before pruning the public API.
