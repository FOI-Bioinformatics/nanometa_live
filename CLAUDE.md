# CLAUDE.md

Developer guidance for **Nanometa Live v2.0**, a real-time visualization dashboard for Oxford Nanopore sequencing analysis.

## Quick Reference

```
nanometa_live/
├── app/                    # Dash web application
│   ├── app.py              # Main app setup, intervals, clientside callbacks
│   ├── callbacks.py        # Core callbacks (status, samples, timer)
│   ├── components/         # Reusable UI components
│   │   ├── config_form.py          # Configuration form
│   │   ├── coverage_plots.py       # Coverage depth/cumulative/histogram figures
│   │   ├── header.py               # App header with status
│   │   ├── modern_components.py    # Operator-friendly cards, badges, meters
│   │   ├── organism_components.py  # Organism display cards
│   │   ├── pathogen_alert.py       # Critical pathogen alert banners
│   │   ├── taxid_mapping_ui.py     # Kraken2 taxid mapping modal
│   │   ├── watchlist_manager_ui.py # Watchlist management components
│   │   └── watchlist_modal.py      # Watchlist detail modals
│   ├── layouts/            # Tab layout definitions
│   │   ├── classification_layout.py
│   │   ├── config_layout.py
│   │   ├── dashboard_layout.py
│   │   ├── main_layout.py
│   │   ├── preparation_layout.py
│   │   ├── qc_layout.py
│   │   ├── validation_layout.py
│   │   └── watchlist_layout.py
│   ├── tabs/               # Tab-specific callbacks
│   │   ├── classification_tab.py
│   │   ├── config_tab.py
│   │   ├── dashboard_tab.py
│   │   ├── kraken2_helpers.py     # Kraken2-specific logic (extracted from classification_tab)
│   │   ├── main_tab.py
│   │   ├── preparation_tab.py
│   │   ├── qc_tab.py
│   │   ├── validation_tab.py
│   │   └── watchlist_tab.py
│   └── utils/              # Callback helpers
│       ├── callback_helpers.py     # Shared callback utilities
│       ├── config_manager.py       # Config state management
│       ├── debounce.py             # Callback debouncing
│       └── plotly_theme.py         # Consistent Plotly theming
├── core/
│   ├── config/             # Configuration loading and parameter mapping
│   │   ├── config_loader.py
│   │   ├── config_manager.py
│   │   ├── config_validator.py
│   │   ├── parameter_mapping.py
│   │   ├── pathogen_loader.py
│   │   └── data/               # Built-in watchlist YAML files
│   │       └── watchlists/     # clinical_pathogens, foodborne, respiratory, etc.
│   ├── parsers/            # Output file parsers
│   │   ├── blast_validation_parser.py  # BLAST + minimap2 validation_results.json
│   │   └── paf_coverage_parser.py      # PAF per-position coverage parser
│   ├── taxonomy/           # Taxonomy resolution
│   │   ├── database_indexer.py     # Kraken2 database index reader
│   │   ├── taxid_mapping.py        # NCBI-to-Kraken2 taxid mapping
│   │   └── taxonomy_api.py         # NCBI/GTDB API lookup
│   ├── utils/              # Data loaders, sample detection, genome management
│   │   ├── data_loaders.py         # Re-export hub (imports from sub-modules below)
│   │   ├── classification_loaders.py  # Kraken2 report parsing and loading
│   │   ├── qc_loaders.py           # FASTP/SeqKit/NanoPlot QC loading
│   │   ├── validation_loaders.py   # BLAST/minimap2 validation loading
│   │   ├── loader_utils.py         # Shared cache and file stability utilities
│   │   ├── canonical_loaders.py    # Waterfall loading (canonical JSON first, raw fallback)
│   │   ├── sample_detector.py      # Manifest-based sample detection with glob fallback
│   │   ├── genome_manager.py       # Genome download and BLAST DB management
│   │   ├── read_extractor.py       # Extract reads by taxid
│   │   ├── alert_engine.py         # Pathogen alert thresholds
│   │   └── ...                     # auto_detect, language_utils, offline_cache, etc.
│   ├── testing/            # Test infrastructure
│   │   └── mock_data_generator.py  # Synthetic Kraken2/FASTP data for tests
│   ├── watchlist/          # Watchlist management
│   │   ├── watchlist_loader.py     # Discover and load YAML watchlists
│   │   ├── watchlist_manager.py    # Singleton manager, entry toggling, API validation
│   │   └── taxonomy_matcher.py     # Name matching utilities
│   └── workflow/           # Backend/Nextflow management
│       ├── backend_manager.py      # Pipeline lifecycle management
│       ├── nextflow_manager.py     # Nextflow execution and monitoring
│       ├── on_demand_validator.py  # On-demand BLAST/minimap2 validation
│       ├── pipeline_runner.py      # Pipeline execution
│       ├── bundle_manager.py       # Offline deployment bundle export/import
│       ├── mobile_lab_preparer.py  # Field lab preparation
│       └── readiness_checker.py    # Pre-flight readiness checks
└── docs/                   # Documentation
```

## Architecture

### Data Flow

```
Input FASTQ -> nanometanf Pipeline -> Output Files -> Data Loaders -> Dash Callbacks -> Visualizations
                     ^                    |
              BackendManager <-- Status Polling (5s)
                     |
              NextflowManager
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| App Setup | `app/app.py` | Dash app, intervals, stores, clientside callbacks |
| Core Callbacks | `app/callbacks.py` | Sample detection, status updates, timer/elapsed time |
| Backend Manager | `core/workflow/backend_manager.py` | Pipeline lifecycle management |
| Nextflow Manager | `core/workflow/nextflow_manager.py` | Nextflow execution and monitoring |
| Parameter Mapping | `core/config/parameter_mapping.py` | Config to Nextflow params conversion |
| Sample Detector | `core/utils/sample_detector.py` | Manifest-based sample detection with glob fallback |
| Data Loaders | `core/utils/data_loaders.py` | Re-export hub for classification, QC, and validation loaders |
| PAF Coverage Parser | `core/parsers/paf_coverage_parser.py` | Per-position coverage from minimap2 PAF |
| Coverage Plots | `app/components/coverage_plots.py` | Depth, cumulative, histogram figures |
| Watchlist Manager | `core/watchlist/watchlist_manager.py` | Watchlist entry management |
| Taxid Mapper | `core/taxonomy/taxid_mapping.py` | NCBI-to-Kraken2 taxid resolution |
| Authoritative Taxonomy | `app/tabs/kraken2_helpers.py` | `load_kraken2_taxonomy()` / `apply_authoritative_taxonomy()` — parses `inspect.txt` from Kraken2 DB to correct parent_taxid for Sankey/Sunburst |
| Latest-Batch Loader | `core/utils/classification_loaders.py` | `load_kraken_latest_batch()` — selects highest-numbered batch report, never sums across cumulative batches |
| Genome Manager | `core/utils/genome_manager.py` | Reference genome downloads and BLAST DBs (offline-mode-aware) |
| On-Demand Validator | `core/workflow/on_demand_validator.py` | On-demand BLAST/minimap2 validation |
| Bundle Manager | `core/workflow/bundle_manager.py` | Mobile-lab bundle export/import: pipeline source, plugins, watchlists, genomes, BLAST DBs, conda cache; build-platform manifest |
| Mobile Lab Preparer | `core/workflow/mobile_lab_preparer.py` | Field-deployment preparation orchestration |
| Readiness Checker | `core/workflow/readiness_checker.py` | Pre-flight checks: tools, DBs, indices, optional network probe |

### Processing Modes

**Batch Mode**: One-time processing of existing FASTQ files
- Generates samplesheet from input directory
- Runs pipeline once to completion
- Results displayed after processing

**Real-time Mode**: Continuous monitoring during active sequencing
- Uses Nextflow `watchPath` for file monitoring
- Incremental Kraken2 classification (batch-by-batch)
- Cumulative reports updated after each batch
- Dashboard refreshes on configurable interval

### Sample Handling Options

| Mode | Use Case | Input Structure |
|------|----------|-----------------|
| `by_barcode` | Multiplexed runs | `barcode01/`, `barcode02/` subdirectories |
| `single_sample` | All files = one sample | Flat directory with FASTQ files |
| `per_file` | Each file = one sample | Flat directory, samples from filenames |

## Development

### Running Locally

```bash
# Visualization mode (no pipeline)
python -m nanometa_live.app --main_dir /path/to/results --port 8050

# Full mode with config
python -m nanometa_live.app --config config.yaml

# Debug mode
DASH_DEBUG=true python -m nanometa_live.app --main_dir /path/to/results
```

### Adding a New Tab

1. Create layout in `app/layouts/my_layout.py`
2. Create callbacks in `app/tabs/my_tab.py`
3. Register in `app/app.py`:
   ```python
   from nanometa_live.app.layouts.my_layout import create_my_layout
   from nanometa_live.app.tabs.my_tab import register_my_callbacks

   # In create_app():
   dbc.Tab(label="My Tab", children=create_my_layout())
   register_my_callbacks(app)
   ```

### Callback Patterns

```python
# Standard callback with sample filtering
@app.callback(
    Output("my-plot", "figure"),
    Input("update-interval", "n_intervals"),
    [State("selected-sample", "data"), State("app-config", "data")]
)
def update_plot(n_intervals, selected_sample, config):
    main_dir = config.get("main_dir", "")
    data = load_kraken_data(main_dir, selected_sample)
    return create_figure(data)
```

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

## Output File Formats

### Kraken2 Reports

```
# Priority order for loading:
1. *.cumulative.kraken2.report.txt  (real-time cumulative)
2. *.kraken2.report.txt             (standard)
3. *.kreport2.txt                   (nanometanf output)
4. *.kreport2                       (legacy)

# Batch files excluded: *_batch*.kraken2.report.txt
```

### PAF Files (minimap2 validation)

```
# Pipeline output:
{results_dir}/validation/minimap2/{sample}_taxid{taxid}.paf

# On-demand output:
{results_dir}/on_demand_validation/{sample}_{taxid}_ondemand.paf

# PAF columns used for coverage:
tname (col 5) = reference name
tlen  (col 6) = reference length
tstart (col 7), tend (col 8) = alignment coordinates
mapq  (col 11) = mapping quality
```

### Directory Structure (nanometanf output)

```
results/
|-- kraken2/
|   |-- barcode01.kraken2.report.txt
|   `-- barcode01.cumulative.kraken2.report.txt  # Real-time mode
|-- fastp/                                       # only when qc_tool: fastp
|   `-- barcode01.fastp.json
|-- seqkit/                                      # only when qc_tool: chopper
|   `-- barcode01.tsv                            # flat layout (current)
|-- taxpasta/
|   `-- *.tsv
|-- validation/
|   |-- blast/
|   |   `-- barcode01.blast.tsv                 # BLAST results
|   `-- minimap2/
|       `-- barcode01_taxid562.paf              # Coverage data
|-- on_demand_validation/
|   `-- barcode01_562_ondemand.paf              # On-demand results
`-- logs/
    `-- trace.txt                                # Nextflow process trace
```

Notes on QC output layout (2026-04-21 audit clarifications):

- `fastp/` and `seqkit/` are mutually exclusive -- exactly one is produced
  per run, depending on `qc_tool`. The QC loaders (`qc_loaders.py`) try
  fastp first and fall back to seqkit.
- `seqkit/<sample>.tsv` is the current nanometanf layout. An older nested
  layout (`seqkit/<sample>/stats/*.tsv`) is also supported by the loader
  for backwards compatibility.
- Nextflow's trace report lives under `logs/`, not `pipeline_info/`.

## Configuration

### Essential Parameters

```yaml
# Input/Output
nanopore_output_directory: "/path/to/fastq"
results_output_directory: "/path/to/output"
kraken_db: "/path/to/kraken2/db"

# Processing
processing_mode: "batch"        # or "realtime"
sample_handling: "by_barcode"   # or "single_sample", "per_file"

# Pipeline
pipeline_profile: "conda"       # always conda for nanometanf; docker/singularity exist but aren't used
pipeline_source: "remote:main"  # or "/local/path"

# Validation
blast_validation: true           # Enables validation features
min_reads_for_validation: 50     # Minimum reads to show Validate button
min_perc_identity: 90            # BLAST identity threshold
e_val_cutoff: 0.01               # BLAST E-value cutoff

# GUI
update_interval_seconds: 30
```

### Parameter Mapping

Config values are converted to Nextflow params in `parameter_mapping.py`:
- `nanopore_output_directory` -> `--input` (samplesheet) or `--nanopore_output_dir`
- `kraken_db` -> `--kraken2_db`
- `processing_mode: realtime` -> `--realtime_mode`

## Watchlist System

### Architecture

The watchlist system manages which pathogens to monitor, with support for built-in, user, and project watchlists.

**Watchlist sources** (searched in priority order):
1. **Project**: `{project_dir}/watchlists/*.yaml`
2. **User**: `~/.nanometa/watchlists/*.yaml` (custom uploads persist here)
3. **Built-in**: `core/config/data/watchlists/*.yaml` (6 predefined lists)

**Built-in watchlists** (ordered to match quick-start buttons):
1. `clinical_pathogens` - Clinical diagnostics
2. `foodborne` - Food safety monitoring
3. `who_drinking_water` - Water quality
4. `respiratory` - Respiratory pathogens
5. `cdc_bioterrorism` - CDC Category A/B agents
6. `who_priority` - WHO priority pathogens

### Custom Watchlist YAML Format

```yaml
version: "2.0"
taxonomy_support: ["ncbi", "gtdb"]
metadata:
  name: "My Watchlist"
  description: "Custom pathogens for specific monitoring"
  source: "Internal"
pathogens:
  - name: "Listeria monocytogenes"
    names_alt: ["Listeria_monocytogenes"]
    taxid_ncbi: 1639
    common_name: "Listeria"
    threat_level: "critical"    # critical, high, moderate, low
    bsl_level: 2                # 1-4
    category: "Foodborne"
    alert_threshold: 5
    action_required: "Product recall assessment."
    notes: "Zero tolerance in ready-to-eat foods."
```

### Multi-Taxonomy Architecture

```
User Input (Pathogen Name)
        |
        v
+-----------------------------------------------------------+
|               WatchlistEntry                              |
|  - taxid (NCBI canonical)                                 |
|  - kraken_taxid (mapped to database)                      |
|  - names_alt (alternative names for multi-taxonomy)       |
|  - gtdb_taxonomy (if validated via API)                   |
+-----------------------------------------------------------+
        |
        v
+-----------------------------------------------------------+
|            TaxidMapper.generate_mappings()                |
|  - Loads Kraken2 database index                           |
|  - Tries strategies: ExactTaxid -> ExactName -> Variant ->|
|    Reclassification -> Fuzzy -> ParentTaxon               |
|  - GTDB suffix variants: _A, _B, ... _Z                  |
|  - Prefers species-level over genus-level matches         |
+-----------------------------------------------------------+
        |
        v
+-----------------------------------------------------------+
|         Genome Download (by taxonomy type)                |
|  - Bacteria/Archaea: GTDB representative genomes          |
|  - Other kingdoms: NCBI RefSeq representative genomes     |
|  - Uses NCBI Datasets CLI for actual downloads            |
+-----------------------------------------------------------+
```

### Kingdom-Specific Taxonomy Handling

| Kingdom | Taxonomy Source | Representative Selection |
|---------|-----------------|-------------------------|
| Bacteria | GTDB | `isGtdbSpeciesRep = True` |
| Archaea | GTDB | `isGtdbSpeciesRep = True` |
| Fungi | NCBI | RefSeq representative genome |
| Viruses | NCBI | RefSeq reference genome |
| Parasites | NCBI | RefSeq representative genome |

## Dashboard Architecture (4-zone clinical layout)

The Dashboard is targeted at first responders and clinicians with a 30-second scan. Four zones, top-to-bottom:

**Zone 1 — Clinical Verdict Banner** (full-width, ~120px minimum, 8px radius, 6px left border)
Single unified banner whose background color is the answer. Replaces three older fragmented elements (traffic-light status, decision banner, threat indicator card).

| State | Background | Left border | Icon | Trigger |
|-------|-----------|-------------|------|---------|
| ALL CLEAR | `#d4edda` | `#28a745` | `bi-shield-check` | 0 watched pathogens detected, run active or complete |
| ACTION REQUIRED | `#f8d7da` | `#8b0000` | `bi-exclamation-octagon-fill` | Any critical or high-risk watched pathogen found |
| MONITORING | `#fff3cd` | `#fd7e14` | `bi-eye-fill` | Only moderate/watch-level pathogens found |
| SCREENING IN PROGRESS | `#cfe2ff` | `#0d6efd` | `bi-arrow-repeat` (with `.spin`) | Run active, first batch pending |
| STANDBY | `#f8f9fa` | muted | — | No run active |

WCAG AA-compliant text colors forced per state. Verdict H3 32px / 700 / letter-spacing −0.01em. Right column shows run state badge, elapsed time, last-updated timestamp, and a "— pending confirmatory validation" qualifier appended to ACTION REQUIRED when BLAST/minimap2 validation has not yet run.

**Zone 2 — Pathogen Alert Cards** (conditional)
Hidden when no alerts. Uses existing `CriticalPathogenAlert` (~120px), `HighRiskPathogenAlert` (~80px), `WatchedSpeciesAlert` (~60px) from `app/components/pathogen_alert.py`.

Each alert card carries a **per-sample attribution row** ("DETECTED IN:" label + chips). Alert dict schema extended with:
```python
"samples": [
    {"sample": "barcode03", "reads": 4521, "abundance": 3.62, "is_negative_control": False},
    ...
]
```
Sorted descending by reads. Chip treatment: 10px / 500, border-radius 3px, colored per severity tier. Negative-control chips render flat gray with `(NC)` suffix. Top 3 chips inline + `+X more` pill for 5+ samples. Non-clickable (read surface).

**Zone 3 — Supporting Data Strip** (4 cards, md=3 each)
- **Sequences Analyzed** — total reads (cumulative)
- **Sample Quality** — headline = plain level (Excellent / Good / Fair / Poor); subtitle = Q-score
- **Species Detected** — distinct organism count
- **Run Time** — elapsed + state badge

StatCard value 28px / 700, label 13px / 500 uppercase letter-spacing +0.04em. 8px radius.

**Zone 4 — Sample Details** (collapsed accordion)
Per-sample AgGrid table + secondary technical details. Column names in plain language: "Sequences Analyzed", "Sample Quality", "Read Length" (formerly N50), "Match Rate" (formerly ID Rate).

**Responsive:**
- <768px: Zone 1 icon hidden except for ACTION REQUIRED; Zone 3 stacks to 2×2
- <480px: Zone 3 stacks 1×4

## Quality Control Stage Strip

The QC tab's primary element is a horizontal three-slot **Stage Strip**: Raw → Quality-filtered → Classified. Each slot: 13px uppercase muted label, 28px bold count, 12px muted subtitle naming the tool, 8px radius, left-border accent (`#084298` for quality-filtered, `#155724` for classified, dashed `#dee2e6` when N/A).

**Chopper pipelines**: Raw slot is dashed border + `—` at 28px `#adb5bd` + inline text "Not available (Chopper pipeline)". Chopper has no pre-filter stage, and nanometanf does not emit pre-chopper seqkit stats.

**Delta row** beneath arrows shows the classification rate colored per threshold:

| Rate | Color | Range |
|------|-------|-------|
| Green | `#155724` / `#d4edda` | ≥ 80% |
| Amber | `#664d03` / `#fff3cd` | 50–79% |
| Red | `#721c24` / `#f8d7da` | < 50% |

**Q30 thresholds**: green ≥45%, amber 25–44%, red <25%.

A "Last updated HH:MM:SS" timestamp sits in the Stage Strip's top-right corner.

Earlier layouts shipped three cards that are now deleted entirely:
`KeyMetricsSummaryCard` (triple-count bug source), `FilteringBreakdownVisual`
(dead code for Chopper), and `QualityScoreIndicator` (replaced by the
verdict banner + Stage Strip combination). They are not in the
component module, not re-exported, and not referenced from any
layout. Phase-5 cleanup, 2026-04-29.

## Validation System

### Overview

The validation tab uses two sub-tabs to separate BLAST and minimap2 results:

1. **BLAST Sub-tab** — Read-centric validation: result cards with identity scores, filtering, sorting, identity distribution plot, and statistics table.
2. **Minimap2/Coverage Sub-tab** — Genome-centric validation: species selector, mapping quality filter, per-position coverage plots (depth, cumulative, histogram), and coverage statistics.

### Architecture

| Component | File | Purpose |
|-----------|------|---------|
| PAF Parser | `core/parsers/paf_coverage_parser.py` | Parse PAF into depth arrays, compute stats |
| BLAST Parser | `core/parsers/blast_validation_parser.py` | Parse BLAST JSON results |
| Coverage Plots | `app/components/coverage_plots.py` | 3 Plotly figures (depth, cumulative, histogram) |
| Validation Layout | `app/layouts/validation_layout.py` | Two sub-tabs (BLAST + Coverage) |
| Validation Tab | `app/tabs/validation_tab.py` | Separate callbacks per sub-tab |

**CoverageData** fields: `ref_name`, `ref_length`, `depth_array` (numpy uint32), `breadth`, `mean_depth`, `median_depth`, `max_depth`, `positions_above_threshold`.

**Coverage plots**:
- Depth chart: area fill with range slider, threshold line, red low-coverage regions
- Cumulative curve: fraction of genome at >= N depth
- Depth histogram: distribution of per-position depth values

### On-Demand Validation (IMPLEMENTED)

Allows validating unexpected organisms found during sequencing without
re-running Kraken2. As of the 2026-04-30 refactor, validation
processing is delegated to nanometanf -- the GUI invokes ``nextflow
run -resume --validation_only`` against the main pipeline outdir, so
previously-validated (sample, taxid) pairs hit the Nextflow work
cache and only the newly-added taxid actually runs.

```
User sees unexpected organism in Organisms tab
        |
        v
Clicks "Validate" button on organism card
        |
        v
OnDemandValidator.validate_organism(config=...)
        |
        v  (when pipeline_source is configured)
validate_via_nanometanf
  1. Download reference genome via NCBI Datasets if missing
  2. Append taxid -> genome path to <outdir>/validation/pathogen_genomes.json
     (cumulative across calls; atomic .replace())
  3. Build nextflow command:
       nextflow run <pipeline> -profile conda -resume \
           --validation_only \
           --kraken2_output_dir <outdir>/kraken2 \
           --reads_dir <outdir>/<reads_dir> \
           --validation_method blast|minimap2|both \
           --pathogen_genomes <outdir>/validation/pathogen_genomes.json \
           --taxids_to_validate <comma-list of all enabled taxids> \
           --outdir <outdir>
  4. Subprocess run; nanometanf VALIDATION_ONLY workflow consumes the
     existing kraken2 + reads dirs and runs only the new (sample, taxid)
     pairs (others hit the work cache).
  5. Parse <outdir>/validation/validation_results.json + per-sample
     stats JSONs into ValidationResult.
```

The legacy local-subprocess path (``run_blast``, ``_run_minimap2``,
``build_blast_db``, ``download_genome``, ``parse_blast_results``)
remains in ``on_demand_validator.py`` as a fallback when no
pipeline_source is configured. Removing it forces every deployment
through nanometanf; left as a follow-up so operators on no-Nextflow
setups still have a path.

**Requirements**:
- ``pipeline_source`` configured (the canonical setup)
- Kraken2 per-read output saved (``save_reads_assignment: true``)
- Original FASTQ files accessible

**Resume cache behaviour (verified 2026-04-30 e2e):** with the same
``--outdir`` and a cumulative ``pathogen_genomes.json``, a second
invocation that adds taxid B after taxid A reports ``cached: 2`` per
per-(sample, taxid) process for A's pairs and only B's pairs run end
to end. The aggregator (AGGREGATE_VALIDATION_RESULTS) re-runs to
rebuild ``validation_results.json`` over the union.

**Bug-fixes shipped during the 2026-04-30 e2e audit:**
- ``subworkflows/local/validation/main.nf:82`` -- coerce
  ``taxids_to_validate`` to string before ``.split()``; Nextflow's
  CLI parser auto-promotes single all-digit values to Integer despite
  the schema declaring string, so ``--taxids_to_validate 9606`` was
  failing every single-taxid GUI call.
- ``modules/local/minimap2_validation/main.nf:136-153`` -- double-
  escape ``\\n`` in the awk JSON writer; bare ``\n`` in the Groovy
  triple-quoted string was expanding to a literal newline at parse
  time, producing unterminated awk string literals. 100% of minimap2
  invocations were exiting code 2 before this fix.
- ``modules/local/blastn_validation/main.nf:113-128`` -- dedupe by
  qseqid so ``hit_rate`` is bounded to [0, 1]; previously every HSP
  row counted, so a 654-HSP/499-read result rendered as "1.3%
  Confirmed" in the GUI.

**UX fixes shipped at the same time:**
- Coverage depth threshold is now operator-controllable via a numeric
  input next to the MAPQ filter (was hardcoded at 10x).
- BLAST stats-table column "Query Coverage (%)" -> "Read Alignment %"
  (clearer + method-agnostic).
- Result-card 4th metric: minimap2 "Alignment Score" -> "Mapping
  Confidence: X / 60" with a "30+ reliable" caption. BLAST: "Query
  Coverage" -> "Read Alignment %" (consistent with stats-table).

### Validation Result Card "View Coverage" Button

Minimap2 result cards include a "View Coverage" button (pattern-matching callback `{"type": "view-coverage-btn", "index": "{sample}_{taxid}"}`). Clicking sets the coverage species selector, which triggers PAF parsing and plot rendering.

## Genome Management

```
Watchlist Entries (enabled pathogens)
        |
        v
GenomeDownloadManager (core/utils/genome_manager.py)
  1. Check existing genomes: ~/.nanometa/genomes/
  2. Determine taxonomy source per species
  3. Fetch genome accessions (GTDB API or NCBI)
  4. Download via NCBI Datasets CLI
  5. Rename to {taxid}.fasta format
  6. Build BLAST database (optional)
        |
        v
Output: ~/.nanometa/genomes/{taxid}.fasta
        ~/.nanometa/blast/{taxid}.fasta.{nhr,nin,nsq}
```

## Offline Deployment

Field labs without internet access are a primary deployment target. The
codebase splits "build online, run offline" into three concerns:

1. **Bundle export / import** (`BundleManager.export_bundle` /
   `import_bundle`). Bundle ships:
   - `pipeline_source/` (the resolved nanometanf checkout, ignoring
     `.git/`, `work/`, `.nextflow*`, `tests/`, `.nf-test/`, `__pycache__`,
     `*.pyc`)
   - `nextflow_plugins/` (plugins matched in `nextflow.config` plus
     known prefixes `nf-schema`, `nf-validation`, `nf-wave`, `nf-console`)
   - `genomes/`, `blast/`, `mappings/`, `cache/`, `watchlists/`
   - `config.yaml` with relative `pipeline_source: ./pipeline_source`
     and `nxf_plugins_dir: ./nextflow_plugins`. `import_bundle` rewrites
     these to absolute paths on the field machine.
   - `manifest.json` records `build_platform` (`{system, machine,
     python}`); `import_bundle` warns on platform mismatch.
   The Kraken2 database is excluded by size and transferred separately.

2. **Subprocess env injection** (`NextflowManager._build_nextflow_env`).
   When `config['offline_mode']` is true, the Nextflow subprocess
   receives:
   ```
   NXF_OFFLINE=true              # literal string "true" (not "1")
   NXF_DISABLE_CHECK_LATEST=true
   NXF_PLUGINS_PATH=<dir>        # suppresses registry probe
   NXF_PLUGINS_DIR=<dir>         # legacy install-target alias
   NXF_CONDA_CACHEDIR=<dir>      # bundled conda envs
   ```
   `validate_pipeline_source` and `BackendManager.setup_project` reject
   `pipeline_source` starting with `remote:` / `https://` / `git@` when
   offline, before any `git ls-remote` fires.

3. **Offline-mode propagation** to NCBI / GTDB callers. `GenomeManager`
   methods (`get_kingdom`, `fetch_gtdb_accession`, `fetch_ncbi_accession`,
   `get_kingdoms_batch`, `fetch_ncbi_accessions_batch`) and the watchlist
   Validate / Add-custom-species callbacks read `offline_mode` and
   short-circuit network calls. Caches (`TaxonomyCache` /
   `OfflineTaxonomyCache`) are consulted first either way.

### Pre-warm conda envs

`BundleManager.export_bundle(..., pre_warm_conda_envs=True)` runs
nine stub scenarios (`_PRE_WARM_SCENARIOS`) under `-profile conda`
to populate `~/.nanometa/work/conda/`:

```
batch_samplesheet      Default chopper QC path
realtime_multiplex     Watchpath barcode mode
realtime_per_file      Per-file fan-out
realtime_single_sample Single-sample aggregation
validation_blast       BLASTN_VALIDATION + EXTRACT_READS_BY_TAXID envs
validation_minimap2    MINIMAP2_ALIGNMENT_VALIDATION + samtools envs
fastp_qc               FASTP / FASTP_STREAMING (alternate QC tool)
assembly_flye          Assembly subworkflow (flye, miniasm)
untar_kraken2_db       UNTAR module for tar.gz Kraken2 DB
```

Adds roughly 30 minutes and ~5 GB to the build. Default off so the
existing flow is unaffected.

### Cross-platform restriction

Conda environments built by Nextflow embed absolute build-machine paths
and per-architecture binaries. **Build machine and field machine must
share OS and CPU architecture** (e.g., both Linux x86_64, or both macOS
arm64). Cross-platform deployment requires either shipping the bundle
without pre-warmed envs (and resolving on first run with brief network
access) or a separate `conda-pack` workflow not currently automated.

## Testing

### Running Tests

```bash
# Full test suite (549 tests, 1 skipped)
pytest tests/ -v

# Individual test modules
pytest tests/test_frontend_integration.py -v    # Frontend integration (mock data)
pytest tests/test_visualization_integration.py -v  # Visualization with synthetic datasets
pytest tests/test_sunburst_tax_levels.py -v     # Sunburst taxonomy level filtering
pytest tests/test_classification_tab.py -v      # Classification tab functions
pytest tests/test_qc_tab.py -v                  # QC tab functions
pytest tests/test_main_tab.py -v                # Main tab functions
pytest tests/test_data_loaders.py -v            # Data loader functions
pytest tests/test_validation_system.py -v       # Validation parser + on-demand validator
pytest tests/test_coverage_threshold_control.py -v  # Coverage depth threshold UI control
```

### Test Data

**Auto-generated synthetic datasets** (`/tmp/nanometa_test_datasets/`):
- Created automatically by `conftest.py` via `scripts/generate_test_datasets.py`
- 8 scenarios: single species, low/medium/high/very high diversity, pathogen detected, low/mixed quality

**Mock data** (`core/testing/mock_data_generator.py`):
- Generates realistic Kraken2 reports and FASTP JSON with full taxonomic hierarchy
- Used by `test_frontend_integration.py` for testing without external data

**Real test data location**:
```
/Users/andreassjodin/Desktop/ONT/demodata_ONT/data/nanometa_testdata/
├── multiple_fastq/    # Barcoded samples
└── single_fastq/      # Flat directory

Kraken2 DB: /Users/andreassjodin/Desktop/ONT/demodata_ONT/database/kraken2.gtdb_bac120_4Gb
```

## Documentation

| Document | Location | Content |
|----------|----------|---------|
| User Guide | `docs/user-guide.md` | Usage instructions for operators |
| Operator Guide | `docs/OPERATOR_GUIDE.md` | Field deployment guide |
| Configuration | `docs/configuration.md` | All config options |
| Developer Guide | `docs/developer-guide.md` | Architecture details |
| API Reference | `docs/api-reference.md` | Parser and loader APIs |
| Migration Guide | `docs/MIGRATION_GUIDE_V2.md` | v1 to v2 migration |

## Links

- [nanometanf Pipeline](https://github.com/FOI-Bioinformatics/nanometanf)
- [Dash Documentation](https://dash.plotly.com/)
- [Plotly Python](https://plotly.com/python/)
- [Original Nanometa Live](https://github.com/FOI-Bioinformatics/nanometa_live) - Legacy implementation reference

---

## Roadmap

### Minimap2 Pipeline Integration (Available)

nanometanf now includes the minimap2 validation subworkflow with PAF output at `results/validation/minimap2/`. On-demand validation is implemented via `OnDemandValidator`.

### Future Features

- Automatic genome updates
- Multi-reference validation
- Regulatory report generation
- Combined BLAST + minimap2 results display

---

See `git log` for change history. Non-obvious patterns and quirks that
survive across cycles are captured inline above (offline mode, authoritative
taxonomy, Kraken2 batch-cumulative aggregation, QC Stage Strip rules,
build-platform restriction, etc.).
