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

Re-export hub: `core/utils/data_loaders.py` re-exports from `classification_loaders.py`,
`qc_loaders.py`, `validation_loaders.py`, `canonical_loaders.py`, `loader_utils.py`.

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
pipeline_source: "remote:main"  # or "/local/path"

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

Requirements: `pipeline_source` configured, `save_reads_assignment: true`, original FASTQ accessible.
Legacy local-subprocess path remains as fallback when no `pipeline_source`.

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

821 tests as of 2026-05-04. Synthetic datasets are auto-generated under
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
