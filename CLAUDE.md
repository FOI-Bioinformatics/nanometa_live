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
│   │   ├── sample_selector.py      # Multi-sample/barcode selection
│   │   ├── taxid_mapping_ui.py     # Kraken2 taxid mapping modal
│   │   ├── tooltip_components.py   # Help icons and contextual guidance
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
│       ├── chart_builders.py       # Plotly chart construction helpers
│       ├── config_manager.py       # Config state management
│       ├── debounce.py             # Callback debouncing
│       ├── export_utils.py         # Report export (CSV, PDF)
│       └── plotly_theme.py         # Consistent Plotly theming
├── core/
│   ├── config/             # Configuration loading and parameter mapping
│   │   ├── config_loader.py
│   │   ├── config_validator.py
│   │   ├── parameter_mapping.py
│   │   ├── pathogen_loader.py
│   │   └── data/               # Built-in watchlist YAML files
│   │       └── watchlists/     # clinical_pathogens, foodborne, respiratory, etc.
│   ├── parsers/            # Output file parsers
│   │   ├── blast_validation_parser.py  # BLAST validation JSON parser
│   │   ├── nanometanf_parser.py        # Pipeline output parser
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
| Genome Manager | `core/utils/genome_manager.py` | Reference genome downloads and BLAST DBs |
| On-Demand Validator | `core/workflow/on_demand_validator.py` | On-demand BLAST/minimap2 validation |

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
├── kraken2/
│   ├── barcode01.kraken2.report.txt
│   └── barcode01.cumulative.kraken2.report.txt  # Real-time mode
├── fastp/
│   └── barcode01.fastp.json
├── taxpasta/
│   └── *.tsv
├── validation/
│   ├── blast/
│   │   └── barcode01.blast.tsv                 # BLAST results
│   └── minimap2/
│       └── barcode01_taxid562.paf              # Coverage data
├── on_demand_validation/
│   └── barcode01_562_ondemand.paf              # On-demand results
└── pipeline_info/
    └── trace.txt  # For process monitoring
```

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
pipeline_profile: "docker"      # or "singularity", "conda"
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

Allows validating unexpected organisms found during sequencing without re-running Kraken2.

```
User sees unexpected organism in Organisms tab
        |
        v
Clicks "Validate" button on organism card
        |
        v
OnDemandValidator (core/workflow/on_demand_validator.py)
  1. Download reference genome (if missing)
  2. Build BLAST database (if missing)
  3. Extract reads from Kraken2 per-read output
  4. Run BLAST validation
  5. Parse and display results
```

**Requirements**:
- Kraken2 per-read output saved (`save_reads_assignment: true`)
- Original FASTQ files accessible
- BLAST+ toolkit installed

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

## Testing

### Running Tests

```bash
# Full test suite (274 tests)
pytest tests/ -v

# Individual test modules
pytest tests/test_frontend_integration.py -v    # Frontend integration (mock data)
pytest tests/test_visualization_integration.py -v  # Visualization with synthetic datasets
pytest tests/test_sunburst_tax_levels.py -v     # Sunburst taxonomy level filtering
pytest tests/test_classification_tab.py -v      # Classification tab functions
pytest tests/test_qc_tab.py -v                  # QC tab functions
pytest tests/test_main_tab.py -v                # Main tab functions
pytest tests/test_data_loaders.py -v            # Data loader functions
pytest tests/test_nanometanf_parser.py -v       # Pipeline output parser
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
├── single_fastq/      # Flat directory
└── multiple_pod5/     # POD5 files (requires Dorado)

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
| Parser Guide | `docs/nanometanf_parser_guide.md` | Pipeline output parser details |

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

**Last Updated:** 2026-04-04

**Production hardening phase 4 (2026-04-04) -- cross-application audit:**

- Parameter mapping: replaced `barcode_dirs` (not in nanometanf schema) with `input_dir` for auto-detection
- BLAST loader: added `.blast.tsv` glob pattern (nanometanf produces `.blast.tsv`, not `.txt`)
- SeqKit loader: added nested directory scan for `seqkit/{sample}/stats/*.tsv` (nanometanf v1.5 layout)
- Fixed `minimap2_min_mapq` default from 30 to 10 (matching nanometanf schema)
- Removed legacy `min_perc_identity` and `e_val_cutoff` params (silently ignored, duplicated by new names)
- Removed orphaned `taxmap-export-download` dcc.Download and `create_mapping_section` unused import
- Removed orphaned stores: `api-validation-progress`, `genome-download-progress`
- Nextflow log error extraction now captures multiline "Caused by:" context
- Test coverage: 403 tests passing, 100+ new tests from phases 3-4

**Production hardening phase 3 (2026-04-03):**

- Taxonomy mapping: `names_alt` support for multi-name matching, strategy priority fix, DB type guards
- GTDB API SSL fallback for environments with restricted certificate chains
- Parser hardening: PAF bounds checking, classification race-condition guards, FASTP JSON validation
- Readiness checker: minimap2 detection, network connectivity test, Nextflow version checks
- FASTA validation after genome download (detects truncated or corrupt files)
- Timeouts on all subprocess and network calls to prevent indefinite hangs
- Test coverage: 20+ new tests for parsers, loaders, and mapping strategies
- Icons: `bi-exclamation-octagon-fill` for critical alerts, `bi-exclamation-triangle-fill` for high-risk alerts
- Accessibility: `title` attributes on icon-only buttons (watchlist info, alert dismiss)

**Production hardening phase 1-2 (2026-03-01):**

- Test suite expanded from 233 to 274 tests (all passing)
- Fixed BLAST validation path: parsers now look in `validation/blast/` (matching nanometanf output)
- Fixed memory leak in BackendManager (error list deduplication)
- Fixed `pipeline_cores` config key being ignored in parameter_mapping
- Added `qc_tool` parameter mapping for FASTP/Chopper selection
- Downgraded verbose VALIDATION DEBUG messages from INFO to DEBUG
- Replaced `iterrows()` with vectorized pandas operations in main_tab
- Added `tests/validation/conftest.py` for proper sys.path setup
