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
`canonical_loaders`, `loader_utils`). The previous re-export hub was
collapsed in the 2026-05-07 audit pass; symbol-to-source is now visible at
every import site.

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
3. `*.kreport2.txt` (nanometanf output)
4. `*.kreport2` (legacy)

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
└── logs/                              # trace.txt
```

Notes:
- `fastp/` and `seqkit/` are mutually exclusive; QC loaders try fastp first, fall back to seqkit.
- `seqkit/<sample>.tsv` is the current flat layout. The older nested `seqkit/<sample>/stats/*.tsv` is still supported.
- Trace lives in `logs/`, not `pipeline_info/`.

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

## Validation System

Two validation sub-tabs:
- **BLAST** — read-centric: identity scores, distribution plot, stats table
- **Minimap2/Coverage** — genome-centric: depth chart, cumulative curve, histogram, mapq filter

### On-demand validation

`OnDemandValidator.validate_organism()` invokes `nextflow run -resume --validation_only`
against the existing pipeline outdir. Previously-validated `(sample, taxid)` pairs hit
the Nextflow work cache; only newly-added taxids run end-to-end.

Genome list `<outdir>/validation/pathogen_genomes.json` is cumulative across calls
(atomic `.replace()`). Aggregator re-runs each invocation to rebuild
`validation_results.json` over the union.

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
   before any `git ls-remote` fires.

3. **Offline-mode propagation** to NCBI/GTDB callers. `GenomeManager` methods and watchlist
   Validate / Add-custom-species callbacks read `offline_mode` and short-circuit network calls.
   Caches (`TaxonomyCache` / `OfflineTaxonomyCache`) are consulted first either way.

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

### macOS bind-mount gotcha

macOS writes AppleDouble (`._*`) sidecar files when writing to non-HFS+ filesystems,
including Docker bind-mounts. These break Nextflow when `NXF_HOME` lands on such a volume
(e.g. `Operation not permitted` on `._.gitattributes`). Fix: set `NXF_HOME` to a
Linux-native path (Docker volume or `/root/.nextflow`); short-term workaround is
`COPYFILE_DISABLE=1` and removing existing `._*` files.

## Testing

```bash
pytest tests/ -v
```

861 tests as of 2026-05-07. Synthetic datasets are auto-generated under
`/tmp/nanometa_test_datasets/` by `conftest.py` via `scripts/generate_test_datasets.py`.
Mock Kraken2/FASTP generators live in `core/testing/mock_data_generator.py`.

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
