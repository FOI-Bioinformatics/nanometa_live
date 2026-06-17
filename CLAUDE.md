# CLAUDE.md

Developer guidance for **Nanometa Live v2.0**, a real-time visualization dashboard for Oxford Nanopore sequencing analysis.

## Architecture

```
Input FASTQ -> nanometanf Pipeline -> Output Files -> Data Loaders -> Dash Callbacks -> Visualizations
                     ^                    |
              BackendManager <-- Status Polling (5s)
                     |
              NextflowManager
```

Top-level layout:

```
nanometa_live/
├── app/         # Dash app: app.py, callbacks.py, components/, layouts/, tabs/, utils/
├── core/
│   ├── config/      # Config loading, parameter mapping, built-in watchlist YAMLs
│   ├── parsers/     # PAF coverage parser, BLAST validation parser
│   ├── taxonomy/    # Kraken2 DB indexer, NCBI/GTDB API, taxid mapping
│   ├── utils/       # Data loaders, sample detector, genome manager, alert engine
│   ├── watchlist/   # Watchlist loader, manager (singleton), taxonomy matcher
│   └── workflow/    # Backend, Nextflow, bundle, on-demand validator, readiness
└── docs/        # Active docs at top; archive/ for historical
```

Loader package: import directly from the leaf module that owns the symbol
(`classification_loaders`, `qc_loaders`, `validation_loaders`,
`canonical_loaders`, `loader_utils`).

### Processing Modes

| Mode | Use Case |
|------|----------|
| Batch | One-time processing of existing FASTQ; samplesheet generated, runs to completion |
| Real-time | Continuous monitoring via Nextflow `watchPath`; incremental Kraken2, cumulative reports refreshed on interval |

### Sample Handling

| Mode | Input Structure |
|------|-----------------|
| `by_barcode` | `barcode01/`, `barcode02/` subdirs (multiplexed) |
| `single_sample` | Flat directory, all files = one sample |
| `per_file` | Flat directory, each file = one sample |

## Development

### Running locally

```bash
# Visualization only (no pipeline)
python -m nanometa_live.app --main_dir /path/to/results --port 8050

# Full mode with config
python -m nanometa_live.app --config config.yaml

# Debug
DASH_DEBUG=true python -m nanometa_live.app --main_dir /path/to/results
```

### Adding a new tab

Layout in `app/layouts/`, callbacks in `app/tabs/`, wire both in `app/app.py`.
Full walkthrough: [`docs/developer-guide.md`](docs/developer-guide.md).

### Key Stores

| Store ID | Purpose |
|----------|---------|
| `app-config` | Current configuration dict |
| `backend-status` | Pipeline status (running, stage, processes) |
| `selected-sample` | Currently selected sample name |
| `available-samples` | List of detected samples |
| `validation-data-store` | Validation results (BLAST/minimap2) |
| `taxmap-collection` | Kraken2 taxid mapping data |
| `watchlist-tab-state` | Watchlist UI state trigger |
| `watchlist-entries-snapshot` | Watchlist entries hydrated from main process for background workers |

**Background callback isolation:** Dash `DiskcacheManager` runs background callbacks
in a separate OS process, so Python singletons (e.g. `WatchlistManager`) are empty there.
Share state via a `dcc.Store` populated in a main-process callback and read via `State`.
Concretely: any background callback that needs the watchlist MUST take
`State("watchlist-entries-snapshot", "data")` and use it instead of
`get_watchlist_manager()`. The readiness checker is one such case —
`update_readiness_state` (`app/callbacks/readiness.py`) passes the snapshot into
`ReadinessChecker.check_readiness(..., watchlist_entries=...)`; without it the
worker's empty singleton makes every watchlist check report "not enabled". The
snapshot carries `enabled` per entry (set in `hydrate_watchlist_entries_snapshot`)
so the checks can filter to the active set.

**Update cadence and session writes.** A single global
`dcc.Interval(id='update-interval')` drives all polling, default 30 s
(configurable via `update_interval_seconds`; the value is re-applied
at runtime by `callbacks.py:75`). Heavy I/O (kraken2/fastp/seqkit/
blast scans) is gated on the `results-fingerprint` store rather than
on raw interval ticks; ~13 callbacks share a uniform 2 s
`should_skip_update()` debounce so an interval tick that finds
nothing new is a microsecond-cost short-circuit. Session-state
writes to `~/.nanometa/configs/last-session.yaml` happen only on
Apply Settings (`config_tab.py:876`) and watchlist edits
(`watchlist_tab.py:38`); pipeline Start, Stop, and finish do NOT
auto-persist. Boot is fresh by design (the Resume/Discard banner
makes session restore an explicit choice, see commit `8bb4290`).
The Start callback writes an optimistic
`{running: True, starting: True}` to the `backend-status` store on
click so the verdict banner flips within ~30 ms instead of waiting
for the next poll; the next real status poll overwrites with the
authoritative value.

**Run metadata on disk:** every successful pipeline start writes
`<results_output_directory>/.nanometa.run.json` (see
`BackendManager.write_run_metadata`). It carries a sha256 fingerprint over the
input-identifying config keys (`nanopore_output_directory`, `sample_handling`,
`processing_mode`, `kraken_db`) so the next launch can detect when the
operator is about to point a different input at a populated outdir. The
collision modal renders a red mismatch banner in that case. Companion helpers:
`compute_input_fingerprint`, `read_run_metadata`, `fingerprint_matches`.

## Output File Formats

### Kraken2 Reports

Loader priority order (cumulative beats per-batch):

1. `*.cumulative.kraken2.report.txt` (real-time cumulative)
2. `*.kraken2.report.txt`

The pre-current `*.kreport2.txt` / `*.kreport2` naming was retired in the
2026-06-02 sunset pass; only the current nanometanf `*.kraken2.report.txt`
naming is recognised.

Per-batch reports `*_batch*.kraken2.report.txt` are excluded — `load_kraken_latest_batch()`
selects the highest-numbered batch and never sums across them.

**Authoritative taxonomy:** `apply_authoritative_taxonomy()` in `app/tabs/kraken2_helpers.py`
parses `inspect.txt` from the Kraken2 DB to correct parent_taxid for Sankey/Sunburst.

**Sequences-analyzed metric:** the dashboard tile uses
`get_classification_stats(kraken_df)` from `app/utils/callback_helpers.py` —
which returns `(classified_reads, unclassified_reads, rate)` from
`root.cumul_reads + unclassified.cumul_reads`. Do not use `kraken_df['reads'].sum()`;
the per-rank assignment column collapses to 0 when every read is parked at
root level (the degenerate single-read input case caught by the audit).

**Loader hot-path invariants (do not regress).** The Kraken2 loaders run on
every poll, so per-element pandas access is the dominant cost on a large
report. The 2026-06-05 perf pass (cProfile, 6 samples × ~3100 taxa) took the
per-poll loader work from ~2 s to <0.1 s; keep these contracts:

- **No per-row `df.iloc[idx][col]` in a parse loop.** `_parse_kraken2_report`
  builds `parent_taxid` by iterating `df["name"].tolist()` / `df["taxid"].tolist()`,
  not `df.iloc`. Each `df.iloc[idx]` materialises a cross-section Series
  (`fast_xs`); on 3000 rows that alone was ~98% of loader time.
- **Use `.tolist()`, not `.values`, for string columns in row loops.** Under
  pandas 3.0 `.values` on the arrow-backed `name`/`rank` columns returns an
  ExtensionArray whose per-element `[i]` goes through arrow `__getitem__`.
  `_accumulate_kraken_df` extracts every column with `.tolist()` for this
  reason. Numeric columns are unaffected but use `.tolist()` there too for
  consistency.
- **Single-report path skips accumulation.** `_parse_kraken_data_uncached`
  (per-sample branch) parses into `parsed_frames` and returns the lone frame
  directly when only one report contributes; `_accumulate_kraken_df` /
  `_aggregate_to_result_df` run only for genuine multi-file aggregation.
- **`get_sample_statistics_summary` parses each sample once when it safely can.**
  `latest_batch_equals_cumulative(main_dir, sample)` (glob/stat only, no parse)
  returns True only when the sample has neither a cumulative report nor any
  per-batch report — the case where `load_kraken_data` and
  `load_kraken_latest_batch` resolve to the same standard
  `<sample>.kraken2.report.txt`. The summary reuses `cumul_df` then; otherwise
  it loads the latest-batch horizon independently (the horizons legitimately
  differ once a cumulative or batch report exists). Regression-covered in
  `tests/test_qc_loaders_horizon.py`.

- **Per-file parsed-frame cache (`_report_frame_cache`).** `_parse_kraken2_report`
  is a thin wrapper over `_parse_kraken2_report_uncached` that memoises the parsed
  frame on `(realpath, st_mtime_ns, st_size)`. Within one poll the same physical
  report is otherwise parsed 2-3x — the aggregated "All Samples" load, the
  per-sample load, and `get_sample_statistics_summary` each go through this choke
  point under different higher-level cache keys (cProfile, 6 samples × ~3100 taxa:
  12 parses for 6 files in one fresh-data poll). The cache collapses that to one
  parse per changed file and, in realtime mode, makes an *incremental* poll
  re-parse only the sample whose report advanced. Measured on the per-poll
  harness: full-refresh poll 137 → 89 ms, incremental poll → 63 ms. Safe because
  parsed frames are read-only for every consumer (`apply_authoritative_taxonomy` /
  `recalculate_cumulative_reads` copy before mutating, `_accumulate_kraken_df`
  only reads). Only successful (non-None) parses are cached; an unstable/empty
  file returns None and is retried next poll (its mtime is unchanged once it
  stabilises, so the key alone cannot distinguish "unstable then" from "stable
  now"). `check_stability=False` (test-only) bypasses the cache so the two
  stability modes never share an entry. Regression-covered in
  `tests/test_classification_loaders.py::TestPerFileParseCache`.

All five were behaviour-preserving (loader output is byte-identical, verified
by sha256 over the full frame incl. `parent_taxid`).

**Sunburst node cap (visualization invariant).** `create_sunburst_data`
(`app/tabs/classification_helpers.py`) takes `max_taxa_per_level` and keeps the
top-N taxa by recalculated cumulative reads at each rank, mirroring
`create_sankey_data`. The classification callback passes the same `max_taxa`
value to both views, so they stay consistent. The default is `0` (= no cap) so
existing callers and tests are unchanged; the callback's own default is the
shared `max_taxa` (10, with 0 mapped to "no limit"). The cap is not only a
readability control: ~60% of an uncapped sunburst build is plotly's
per-element trace validation, which scales with node count (~3100 species nodes
on a GTDB run took ~57 ms; capped ~15 ms). A node whose direct parent is capped
out reparents to its nearest still-present ancestor (or `root`) via
`_resolve_sunburst_parent`, so capping never orphans a node. Regression-covered
in `tests/test_sunburst_tax_levels.py`.

### PAF Files (minimap2 validation)

```
{outdir}/validation/minimap2/{sample}_taxid{taxid}.paf       # pipeline
{outdir}/on_demand_validation/{sample}_{taxid}_ondemand.paf  # on-demand
```

Coverage uses cols 5/6 (tname/tlen), 7/8 (tstart/tend), 11 (mapq).

### nanometanf Output Layout

```
results/
├── kraken2/                           # *.kraken2.report.txt, *.cumulative.kraken2.report.txt
├── fastp/         OR   seqkit/        # mutually exclusive, depends on qc_tool
├── taxpasta/
├── validation/
│   ├── blast/                         # *.blast.tsv
│   └── minimap2/                      # *_taxid*.paf
├── on_demand_validation/
└── pipeline_info/                     # execution_trace_*.txt, report.html, timeline.html
```

Notes:
- `fastp/` and `seqkit/` are mutually exclusive; QC loaders try fastp first, fall back to seqkit.
- `seqkit/<sample>.tsv` is the current flat layout (plus the incremental `seqkit/<sample>/batch_stats/*.tsv`). The older nested `seqkit/<sample>/stats/*.tsv` layout was retired in the 2026-06-02 sunset pass.
- Nextflow trace lives at `pipeline_info/execution_trace_*.txt` (per `nextflow.config:407` in nanometanf). The GUI's NextflowManager redirects its own copy to `~/.nanometa/logs/trace.txt` for status polling, but the canonical pipeline emit is under `pipeline_info/`.

## Configuration

```yaml
# Input/Output
nanopore_output_directory: "/path/to/fastq"
results_output_directory: "/path/to/output"
kraken_db: "/path/to/kraken2/db"

# Processing
processing_mode: "batch"        # or "realtime"
sample_handling: "by_barcode"   # or "single_sample", "per_file"

# Pipeline
pipeline_profile: "conda"       # always conda for nanometanf
# Upstream nanometanf has no `main` branch -- use `remote:dev` (active
# development), `remote:master` (legacy default), or a local checkout path.
pipeline_source: "remote:dev"   # or "/Users/.../nanometanf"

# Validation
blast_validation: true
min_reads_for_validation: 50
min_perc_identity: 90
e_val_cutoff: 0.01

update_interval_seconds: 30
```

### Parameter mapping (non-obvious renames)

`core/config/parameter_mapping.py` translates config keys to Nextflow params:

- `nanopore_output_directory` -> `--input` (samplesheet) or `--nanopore_output_dir`
- `kraken_db` -> `--kraken2_db`
- `processing_mode: realtime` -> `--realtime_mode`

### Path lifecycle

Every path-bearing config key is canonicalised at write time
(Configuration tab save) and at load time (`ConfigLoader.load_config`)
via `core/utils/path_utils.normalise_path`. Stripping, `~` expansion,
and `os.path.abspath` apply uniformly. Sentinel values are
deliberately preserved: `remote:...`, `http(s)://`, `git@`, and the
bundle-relative `./pipeline_source` / `./nextflow_plugins` strings
are returned unchanged so the bundle import-rebase logic continues to
work. The full set of normalised keys is `PATH_CONFIG_KEYS` in the
same module; consumers should call `normalise_config_paths(config)`
rather than reimplementing the loop.

`report_missing_paths(config)` returns `{key: path}` for every
path-bearing key whose value is set but does not exist on disk. A
startup callback (`warn_about_missing_paths_on_startup` in
`app/callbacks.py`) emits a single combined toast on app load so the
operator sees the stale path without having to read the terminal log.

`core/utils/kraken_utils.py` is the single source of truth for "is
this a valid Kraken2 database?". `KRAKEN_REQUIRED_FILES` lists the
canonical filenames; `check_kraken_db(db_path) -> (bool, list[str])`
returns a missing-file list for the caller to format. Configuration
tab save validation, `parameter_mapping.validate_nextflow_params`
(the launch-time gate), and `readiness_checker._check_kraken_db` all
delegate. Adding a new required file (e.g. `accmap.k2d`) is a
single-edit change.

### Config form: save / load / dirty-state symmetry

The Configuration tab has three field lists that must stay in lock-step,
or the form silently mis-reports: `apply_config_changes` (States that build
the saved config), `initialize_form_from_config` (Outputs that repopulate the
form), and `detect_form_changes` (Inputs that drive the "Modified" badge).
When you add a form field, wire it into all three. The dirty check delegates
to the pure `config_form_dirty(snapshot, form=...)` helper in
`config_tab_helpers.py`, fed the full saved field set keyed exactly as
`build_config_from_form` writes it (with `pipeline_source` reconstructed from
the three source widgets via `_pipeline_source_from_form`); a field missing
there means edits to it never flag the form modified, so the operator can
forget to Apply and launch with stale config. Form-loader `.get(key, default)`
fallbacks must match `create_default_config` — a divergent default (e.g.
`validation_method`, `sample_handling`) only surfaces when a key is absent, a
latent trap since `load_config` merges defaults on read.

**Form-draft autosave.** Switching tabs re-fires `refresh-form-trigger`
(`trigger_initial_form_load` on `tabs.active_tab` change), so
`initialize_form_from_config` re-runs and would discard unsaved edits. To keep
edits across a tab switch, `detect_form_changes` also writes the in-progress
`form` dict to the session Store `config-form-draft` (the dict it already
builds for the dirty check — same `build_config_from_form` keys), and
`initialize_form_from_config` overlays that draft on top of the saved config
(`config = {**config, **draft}`). The draft is the *fourth* writer of the form
state and must stay key-compatible with the other three lists above. It is
cleared (`None`) on Load and Reset so those authoritative actions win; Apply
needs no clear because the draft already equals the applied config. Edits are
still only persisted to `last-session.yaml` on Apply — the draft is a
session-scoped convenience, not a saved config.

## Watchlist System

Sources searched in priority order:

1. Project: `{project_dir}/watchlists/*.yaml`
2. User: `~/.nanometa/watchlists/*.yaml` (custom uploads persist here)
3. Built-in: `core/config/data/watchlists/*.yaml`

Format examples live in `core/config/data/watchlists/` — see any built-in YAML
for the v2.0 schema (pathogens with `taxid_ncbi`, `threat_level`, `bsl_level`,
`alert_threshold`, etc.).

### Taxonomy resolution

`TaxidMapper.generate_mappings()` (`core/taxonomy/taxid_mapping.py`) tries strategies
in order: ExactTaxid -> ExactName -> Variant -> Reclassification -> Fuzzy -> ParentTaxon.
Includes GTDB suffix variants (`_A`...`_Z`) and prefers species-level matches.

Genome download by kingdom: Bacteria/Archaea use GTDB representative genomes
(`isGtdbSpeciesRep`); other kingdoms use NCBI RefSeq. Downloads via NCBI Datasets CLI,
output to `~/.nanometa/genomes/{taxid}.fasta`.

### API circuit breaker and taxonomy auto-selection

GTDB and NCBI taxonomy clients in `core/taxonomy/taxonomy_api.py`
share a class-level per-host circuit breaker. After
`_CIRCUIT_FAILURE_THRESHOLD` (default 3) consecutive failures, the
host is short-circuited for the remainder of the process and
subsequent calls return `None` immediately. Default HTTP timeout is
5 s. The breaker is in-memory only — a transient outage does not
persist a disabled flag. The Verify Taxonomy IDs callback in
`watchlist_tab.py` reads `config["kraken_taxonomy"]` and skips the
API that does not match the active database, so an NCBI run does not
stall on a degraded GTDB endpoint. Operators can still tick both
checkboxes for explicit cross-validation.

### Database registry: bundled + operator-managed

The Kraken2 download manifest is loaded from two sources on startup
and merged into the picker store:

1. `nanometa_live/kraken2_databases.yaml` (bundled defaults; public
   `genome-idx` URLs).
2. `~/.nanometa/kraken2_databases.local.yaml` (operator-managed;
   same schema).

Local entries win on key collision. A missing local file is silently
skipped; a malformed one logs and continues with the bundled
defaults. Use the local file to register private mirrors or in-house
custom builds without forking the package.

## Validation System

Two validation sub-tabs:
- **BLAST** — read-centric: identity scores, distribution plot, stats table
- **Minimap2/Coverage** — genome-centric: depth chart, cumulative curve, histogram, mapq filter

**Result-loading priority** (`ValidationParser.get_validation_results`): the
aggregate `validation/validation_results.json` wins when present. Without it,
the parser falls back to individual per-(sample, taxid) files — `blast/*.blast.tsv`
*and* `minimap2/*.minimap2_stats.json`. The minimap2 individual-file path
(`core/parsers/minimap2_stats.py`) is what keeps the Coverage sub-tab populated
during a realtime run, where the aggregate JSON is not written until late; BLAST
and minimap2 are distinct methods for the same pair, so minimap2 stats supplement
the blast.tsv results rather than dedup against them. Added in the 2026-06-02
validation audit after a live run showed the Coverage tab blank mid-run despite
high-quality `.minimap2_stats.json` already on disk.

### Realtime cumulative validation + per-batch drill-down

In realtime mode the pipeline keeps a run-so-far cumulative view per
`(sample, taxid)` instead of overwriting each batch (the prior behaviour, where a
later empty batch reset a confirmed organism to 0). Layout:

- **Cumulative (canonical flat):** `validation/{minimap2,blast}/<sample>_taxid<tid>.{paf,blast.tsv,*_stats.json}`
  — kept current each batch by nanometanf's `validation_cumulative_aggregator`
  module (merges the prior cumulative + the new batch, recomputes stats; coverage
  breadth is recomputed since it is not additive, `total_reads` is accumulated
  since it is not in the alignment files). The GUI reads these by default.
- **Per-batch (preserved):** `validation/{minimap2,blast}/batch/<sample>_taxid<tid>_<batch_id>.*`
  — every batch retained for drill-down. `batch_id` is the realtime batch index.

GUI side: a "View: Cumulative / Single batch" toggle (hidden unless a `batch/`
dir exists) drives `get_validation_results(batch_id=…)` and
`_load_real_coverage(batch_id=…)`; batch results come from
`core/parsers/validation_batch.py`. In batch processing mode (no `meta.batch_id`)
nothing changes — the flat file is the result and the aggregator is skipped.
Added 2026-06-02 (nanometanf + nanometa_live `validation-cumulative-realtime`).

### On-demand validation

`OnDemandValidator.validate_organism()` invokes `nextflow run -resume --validation_only`
against the existing pipeline outdir. Previously-validated `(sample, taxid)` pairs hit
the Nextflow work cache; only newly-added taxids run end-to-end.

Genome list `<outdir>/validation/pathogen_genomes.json` is cumulative across calls
(atomic `.replace()`). Aggregator re-runs each invocation to rebuild
`validation_results.json` over the union.

On load, an on-demand result *supersedes* the pipeline result for the same
`(sample, taxid, method)` in `ValidationParser.get_validation_results` (it is an
explicit operator re-check, so it wins in place); a method the on-demand run did
not cover is left untouched. `OnDemandValidator._save_results` derives its
`validation_status` from `ValidationResult.determine_status` rather than a private
threshold copy, so the two paths cannot drift. Both changed in the 2026-06-02
validation audit.

Requirements: `pipeline_source` configured, `save_reads_assignment: true`,
original FASTQ accessible. `pipeline_source` is now mandatory: missing config
or a `None` return from `validate_via_nanometanf` produces a failed
`ValidationResult` with a descriptive `error_message` instead of silently
running a parallel subprocess path. The legacy local-subprocess fallback was
removed in the 2026-05-07 audit pass (commit `4c7c284`).

### Durable invariants in the validation pipeline

- `subworkflows/local/validation/main.nf` coerces `taxids_to_validate` to string before `.split()`. Nextflow's CLI parser silently promotes all-digit single values to `Integer` regardless of schema; coercion is required for single-taxid GUI calls.
- `modules/local/minimap2_validation/main.nf` double-escapes `\\n` in the awk JSON writer because bare `\n` in a Groovy triple-quoted string expands at parse time.
- `modules/local/blastn_validation/main.nf` deduplicates BLAST hits by `qseqid` so `hit_rate` stays bounded to `[0, 1]`. Counting raw HSPs produces hit rates above 1.

## Offline Deployment

Three concerns:

1. **Bundle export/import** (`BundleManager`). Ships pipeline source, plugins,
   watchlists, genomes/BLAST DBs, conda cache, and `manifest.json` with `build_platform`.
   Kraken2 DB excluded by size — transferred separately. `import_bundle` rewrites
   relative paths to absolute and warns on platform mismatch.

2. **Subprocess env injection** (`NextflowManager._build_nextflow_env`). When
   `config['offline_mode']` is true:
   ```
   NXF_OFFLINE=true             # literal "true", not "1"
   NXF_DISABLE_CHECK_LATEST=true
   NXF_PLUGINS_PATH=<dir>       # suppresses registry probe
   NXF_PLUGINS_DIR=<dir>        # legacy install-target alias
   NXF_CONDA_CACHEDIR=<dir>
   ```
   `validate_pipeline_source` rejects `remote:` / `https://` / `git@` sources when offline,
   before any `git ls-remote` fires. `_build_nextflow_env` starts from
   `os.environ.copy()`, so any `NXF_*` variable exported by the shell that
   launched `python -m nanometa_live.app` propagates to GUI-spawned pipeline
   runs without code changes.

3. **Offline-mode propagation** to NCBI/GTDB callers. `GenomeManager` methods and watchlist
   Validate / Add-custom-species callbacks read `offline_mode` and short-circuit network calls.
   Caches (`TaxonomyCache` / `OfflineTaxonomyCache`) are consulted first either way.

### Toolchain floor (Nextflow 26.04.0)

`nanometanf` floors at `nextflowVersion = '>=26.04.0'` (manifest in
`nanometanf/nextflow.config`). The matching `nf-core` conda env ships
Nextflow 26.04.0 / nf-core/tools 4.0.2 / nf-test 0.9.5. The pipeline
parses cleanly under the strict v2 grammar (default in 26+) — no
`NXF_SYNTAX_PARSER` opt-in needed. Verification is in
`docs/audit/realtime-2026-05-09.md` sections 13 and 14.

One known upstream wrinkle: **`nf-core/tools 4.0.2 pipelines lint`
crashes** with `LiveError` from `rocrate.parse_manifest_contributors`.
Pin `nf-core==3.5.2` for local lint runs until the rich progress-bar
nesting is fixed upstream. This is unrelated to the runtime path —
pipelines run normally under 4.0.2.

The 25.10.x watchPath JVM cleanup hang (the historical reason for the
`NXF_VER=25.04.7` workaround) was resolved upstream in 26.04.0.

### Cross-platform restriction

Conda envs built by Nextflow embed absolute build-machine paths and per-arch binaries.
**Build and field machine must share OS and CPU architecture.** Cross-platform deployment
requires either shipping without pre-warmed envs or a separate `conda-pack` workflow
(not currently automated).

### Backend hardening

Three guards run on every pipeline launch and shape what an operator sees when
something goes wrong:

- **Half-built conda env purge** (`NextflowManager._purge_broken_conda_envs`).
  Sweeps `<work_dir>/conda/env-*/` before each conda-profile run, removing any
  env directory missing `conda-meta/history` (the marker conda writes last on
  successful build). Without this, a SIGTERM-killed env build leaves a stub
  directory that Nextflow's cache treats as ready -- the next run activates an
  empty env and the first process needing it exits 127 (`command not found`).
- **Loader nested-mtime walk** (`_get_path_fingerprint` in
  `core/utils/loader_utils.py`). Bounded recursive walk (5000 files) so the
  kraken2 cache fingerprint advances when realtime-mode files land under
  `kraken2/<sample>/batch_reports/`. The non-recursive predecessor saw zero
  direct files in `kraken2/`, locked in an empty result on the first poll,
  and the dashboard sat at 0 sequences for the entire run.
- **Output-collision modal** (`detect_existing_results` +
  `archive_existing_results` in `BackendManager`). Pre-run scan of
  `RESULT_SUBDIRS`; modal offers Archive (`_archive_<ts>/`), Continue (with
  `-resume`), or Cancel. The fingerprint above tags the modal red when the
  new input differs from what the prior run wrote.

**Polling-tick backstop on results-driven callbacks.** Lead callbacks
in `dashboard_tab.py` (verdict banner + status cache),
`main_tab.py` (Organisms), `qc_tab.py` (QC plots),
`classification_tab.py` (Sankey/Sunburst), and `validation_tab.py`
(Validation data store) take `update-interval` as an Input alongside
`results-fingerprint`. Without the backstop, a tab visited after the
first fingerprint tick on a quiet outdir leaves the operator looking
at the empty initial layout because the fingerprint never advances
again. The 2-second `should_skip_update("...")` debouncer or the
`get_trigger_type(ctx) == "interval"` guard keeps the new Input from
multiplying work — the backstop fires at most once per tick.

**Verdict-banner decision logic is a pure function.** The safety-critical
clinical verdict (ACTION REQUIRED / MONITORING / ALL CLEAR / SCREENING /
STANDBY) is decided by `select_verdict()` in
`app/tabs/dashboard_helpers.py`, which returns a `VerdictDescriptor` from the
input booleans and the watchlist hit list — no file I/O, no component build.
The `update_verdict_banner` callback only gathers inputs (Kraken load,
`_check_pathogens_with_mapping`), delegates the state choice, runs per-sample
attribution when `descriptor.needs_attribution` is set (ACTION REQUIRED only),
and renders via `_make_banner_content` / `_verdict_banner_style`. The precedence
is fixed: no-config → starting → data-driven → running-no-data → standby; note
a missing results dir yields STANDBY even while the pipeline runs. Every branch
is unit-tested in `tests/test_verdict_selector.py`; keep new states in the pure
function so they stay testable without a running app. This mirrors the broader
`*_tab.py` → `*_helpers.py` split (pure logic in helpers, thin callback wiring
in the tab module) used across the dashboard, main, qc, and validation tabs.

**Pathogen Report modal references are built dynamically.** The report's
external links come from `build_reference_links()` in `dashboard_helpers.py`,
which never emits a link to a wrong or nonexistent record: NCBI Taxonomy only
for a real NCBI taxid (`_is_real_ncbi_taxid`) or a resolved `ncbi_link`; GTDB
only when a resolved `gtdb_link` exists (never reconstructed from a name);
Federal Select Agent Program (`SELECT_AGENTS_URL`,
`https://www.selectagents.gov/sat/list.htm`) always. The old CDC
`niosh/topics/emres/chemagent.html` link was dead (404) and topically wrong
(chemical agents) — do not reintroduce a CDC bioterrorism-category URL; CDC
retired that tree in 2024. Confidence in the report is `compute_detection_confidence`
(read-support bands, not a statistical CI), and `build_detection_meta` labels
the watchlist `validated` flag as "Taxonomy ID" validation so it is not
confused with the confirmatory BLAST/minimap2 results on the Validation tab.

**Export Results report generator** (`core/export/report_generator.py`). The
report's decision banner and Watched Organisms table are driven entirely by
`watched_results`, so `_screen_watchlist` must iterate
`get_active_entries()` — a `Dict[int, WatchlistEntry]`, NOT a list of dicts —
via `.values()` with attribute access, matching by `db_taxid` → NCBI `taxid` →
name. Iterating it wrong silently empties the threat screen (a false negative
in the archived artifact); regression-covered in `tests/test_report_generator.py`.
Classification counts delegate to `get_classification_stats`; organism abundance
uses species (`S`) rank only with Kraken2's `%` column (never `reads.sum()` —
double-counts genus and over-states). Raw files copied are `_RAW_SUBDIRS`
(kraken2/fastp/seqkit/taxpasta/validation/on_demand_validation/pipeline_info),
AppleDouble-filtered, skipped above `export_max_raw_bytes` (default 5 GiB).
Plotly is inlined for offline self-containment; `offline_mode` suppresses the
CDN fallback so an offline report never emits a dead `<script src>`. The export
runs synchronously in the callback ON PURPOSE — a background callback would
empty the `WatchlistManager` singleton and re-break the screen.

### macOS bind-mount gotcha

macOS writes AppleDouble (`._*`) sidecar files when writing to non-HFS+ filesystems,
including Docker bind-mounts. These break Nextflow when `NXF_HOME` lands on such a volume
(e.g. `Operation not permitted` on `._.gitattributes`). Fix: set `NXF_HOME` to a
Linux-native path (Docker volume or `/root/.nextflow`); short-term workaround is
`COPYFILE_DISABLE=1` and removing existing `._*` files.

## Testing

```bash
pytest                                              # full suite, parallel (pytest-xdist)
pytest -n 0                                         # serial, for pdb/print debugging
pytest --cov=nanometa_live --cov-report=term-missing   # with the coverage gate
```

2321 tests as of 2026-06-07, ~63% line coverage. `pytest.ini` enforces a
`fail_under = 62` floor on coverage runs only (the default `pytest` dev loop
does not load coverage); the floor ratchets up as coverage rises — keep it ~1
point below the measured total, never lower it. Also
`filterwarnings = error::DeprecationWarning:nanometa_live` (our own deprecations
fail the build), and the `unit` / `callback` / `integration` markers. CI runs the
suite and the gate on Python 3.11 and 3.12 for every push and PR to `main` /
`dev` (`.github/workflows/tests.yml`). Tests marked `slow` need Nextflow/conda
and are skipped by default.

Synthetic datasets are auto-generated under `/tmp/nanometa_test_datasets/` by
`conftest.py` via `scripts/generate_test_datasets.py`. Mock Kraken2/FASTP
generators live in `core/testing/mock_data_generator.py`;
`generate_test_dataset(dir, scenario=MockDataScenario.PATHOGEN_DETECTED,
num_samples=N)` writes a realistic results tree (`kraken2/`, `fastp/`, `qc/`,
`multiqc/`) that drives populated-data callback/loader tests — back-date the
files (`os.utime` to ~30s ago) so the loaders' file-stability checks pass.

**Callback tests.** Dash callbacks are tested by registering on a throwaway
`Dash` app and extracting the unwrapped function with
`tests/dash_test_utils.get_callback_fn(app, output_id, input_contains=...)`
(walks `app.callback_map`, unwraps `spec["callback"].__wrapped__`); pass
`input_contains` to disambiguate when several callbacks share an output (e.g. the
many `toast-message`/`tabs.active_tab` writers). Invoke the extracted function
directly with realistic store values and assert the returned component structure
+ content, not just `is not None`. **`ctx` gotcha:** `dash_test_utils.ctx_with`
patches `dash.ctx`, which only reaches callbacks that reference `dash.ctx` at call
time; modules that did `from dash import ctx` (main_tab, qc_tab, classification_tab,
dashboard_tab) bind a module-local name, so patch `<module>.ctx` instead. Pure
helpers and module-level guards inside `register_*` are closures — re-register the
app (function-scoped fixture) to reset a once-per-session guard. Background
(`background=True`) callbacks and subprocess managers (`nextflow_manager`,
`on_demand_validator`) are intentionally light on unit coverage — testing them
needs DiskcacheManager/`set_progress`/subprocess harnessing that yields brittle
wiring-only tests; prefer covering the pure helpers they delegate to.

Real test data:
```
/Users/andreassjodin/Desktop/ONT/demodata_ONT/data/nanometa_testdata/
├── multiple_fastq/    # Barcoded
└── single_fastq/      # Flat
Kraken2 DB: /Users/andreassjodin/Desktop/ONT/demodata_ONT/database/kraken2.gtdb_bac120_4Gb
```

## Documentation

| Document | Content |
|----------|---------|
| `docs/quickstart-with-nanorunner.md` | End-to-end demo using simulated input |
| `docs/user-guide.md` | Operator usage |
| `docs/OPERATOR_GUIDE.md` | Field deployment |
| `docs/configuration.md` | All config options |
| `docs/developer-guide.md` | Architecture details |
| `docs/api-reference.md` | Parser and loader APIs |
| `docs/MIGRATION_GUIDE_V2.md` | v1 to v2 migration |
| `docs/archive/` | Audits, plans, migration notes (not maintained) |

## Links

- [nanometanf Pipeline](https://github.com/FOI-Bioinformatics/nanometanf)
- [Dash Documentation](https://dash.plotly.com/)
- [Original Nanometa Live](https://github.com/FOI-Bioinformatics/nanometa_live) — legacy reference
