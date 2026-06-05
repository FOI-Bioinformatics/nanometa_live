# Configuration Reference

Reference for Nanometa Live configuration options.

## Configuration File Format

Configuration files use YAML format:

```yaml
analysis_name: "My Analysis"
nanopore_output_directory: "/path/to/input"
# ... more options
```

## Core Settings

### Input/Output

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `analysis_name` | string | "Nanometa Live Analysis" | Display name for this analysis |
| `nanopore_output_directory` | path | required | Directory containing FASTQ files |
| `results_output_directory` | path | ~/nanometa_results | Where to write pipeline output |
| `main_dir` | path | same as results | Directory for visualization (usually same as results) |
| `genome_cache_dir` | path | ~/.nanometa | Directory for downloaded reference genomes |

### Processing

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `processing_mode` | string | "batch" | `batch` or `realtime` |
| `sample_handling` | string | "by_barcode" | `by_barcode`, `single_sample`, or `per_file` |
| `sample_name` | string | "sample" | Name when using single_sample mode |
| `offline_mode` | bool | false | Skip network calls and use cached data only |

### Kraken2 Classification

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `kraken_db` | path | required | Path to Kraken2 database |
| `kraken_taxonomy` | string | "gtdb" | `ncbi` or `gtdb` |
| `kraken_memory_mapping` | bool | true | Memory-map database for speed |
| `kraken2_enable_incremental` | bool | true | Incremental classification in realtime mode |

### Pipeline Execution

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pipeline_profile` | string | "conda"  | `conda` is the canonical and supported profile for nanometanf. `docker` and `singularity` exist but are not used by Nanometa Live. |
| `pipeline_source` | string | "remote:master" | Pipeline location (see below) |
| `pipeline_cores` | int | 1 | CPU cores for pipeline |
| `kraken_cores` | int | 1 | CPU cores for Kraken2 classification |
| `validation_cores` | int | 1 | CPU cores for validation tasks |
| `blast_cores` | int | 1 | CPU cores for BLAST searches |
| `conda_frontend` | string | "mamba" | Conda package manager (`mamba` or `conda`) |

### Validation

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `blast_validation` | bool | false | Enable validation of detected organisms |
| `validation_method` | string | "blast" | `blast`, `minimap2`, or `both` |
| `blast_db` | path | null | BLAST database path |
| `min_perc_identity` | float | 90 | Minimum percent identity for BLAST hits |
| `e_val_cutoff` | float | 0.01 | E-value cutoff for BLAST |
| `validation_hit_rate_threshold` | float | 0.5 | Minimum fraction of reads that must validate |
| `validation_identity_threshold` | float | 90.0 | Minimum identity score for validation |
| `minimap2_preset` | string | "map-ont" | Minimap2 alignment preset |
| `minimap2_min_mapq` | int | 30 | Minimum mapping quality for minimap2 |

### GUI Settings

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `update_interval_seconds` | int | 10 | Dashboard refresh interval in seconds. Lowered from 30 in 2026-05; downstream callbacks are gated on a results fingerprint so unchanged ticks are near-zero cost. |
| `check_intervals_seconds` | int | 15 | Backend file-check interval in seconds |
| `gui_port` | int | 8050 | Web server port |
| `danger_lower_limit` | int | 100 | Read count threshold for species-of-interest alerts |

### Visualization

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `default_hierarchy_letters` | list | ["D","C","G","S"] | Default taxonomy levels shown |
| `taxonomic_hierarchy_letters` | list | ["D","P","C","O","F","G","S"] | All available taxonomy levels |
| `default_reads_per_level` | int | 10 | Minimum reads to display at each level |
| `enable_krona_plots` | bool | false | Generate Krona interactive HTML plots |
| `enable_nanopore_stats_mqc` | bool | false | Include NanoPlot stats in MultiQC |

### QC and Analysis Tools

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `qc_tool` | string | "chopper" | QC tool for read filtering |
| `skip_nanoplot` | bool | false | Skip NanoPlot quality reporting |
| `remove_temp_files` | bool | true | Clean up intermediate files after processing |

### Real-time Mode

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `batch_size` | int | 1 | Files per processing batch (1 = immediate) |
| `min_batch_size` | int | 1 | Minimum files before triggering a batch |
| `max_file_age_minutes` | int | 1000000 | Maximum age of files to process |

### High-Throughput Tuning (12-24 barcodes)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `kraken2_memory_gb` | int | 12 | RAM headroom (GB) per Kraken2 fork. Set to on-disk DB size + 4 GB. |
| `kraken2_memory_mapping` | bool | true | Share the Kraken2 DB across forks via OS page cache. |
| `max_classification_forks` | int | 4 | Max parallel Kraken2 jobs. Raise for high-RAM hosts; lower if OOM. |
| `max_concurrent_batches` | int | 4 | Per-sample backpressure cap. Total in-flight = N_samples * this. |
| `report_write_interval` | int | 5 | Write progressive cumulative report every N batches (0 = every batch). |

See the [Operator Guide section "Tuning for High-Throughput Runs"](OPERATOR_GUIDE.md#-tuning-for-high-throughput-runs-12-24-barcodes)
for the host-class recommendation table and per-database memory sizing
(`kraken2_memory_gb` rule of thumb: on-disk DB size + 4 GB).

## Species of Interest

Define organisms to track with alerts:

```yaml
species_of_interest:
  - name: "Escherichia coli"
    taxid: "562"
  - name: "Salmonella enterica"
    taxid: "28901"
  - name: "Bacillus anthracis"
    taxid: "1392"
```

## Watchlist Format (v2.0)

Nanometa Live uses structured YAML watchlists for pathogen screening. The application ships with 9 built-in watchlists and supports importing custom lists.

### Built-in Watchlists

| Watchlist | Pathogens | Focus |
|-----------|-----------|-------|
| Clinical Pathogens | 17 | Common healthcare-associated organisms |
| CDC Bioterrorism | 34 | CDC Category A/B agents and select-agent overlap |
| WHO Priority | 19 | WHO 2024 Bacterial Priority Pathogens |
| Foodborne | 20 | Food safety and outbreak pathogens |
| Respiratory | 20 | Respiratory tract pathogens |
| Water Safety | 28 | WHO drinking water quality indicators |
| Nosocomial/ESKAPE | 14 | Hospital-acquired infection organisms |
| Wastewater Surveillance | 13 | Environmental monitoring targets |
| Zoonotic One Health | 15 | Animal-to-human transmission pathogens |

### Watchlist YAML Structure

```yaml
# Metadata header
version: "2.0"
taxonomy_support: ["ncbi", "gtdb"]

metadata:
  name: "My Custom Watchlist"
  description: "Short description of the watchlist purpose"
  source: "Organization or reference"
  reference: "URL or citation"

# Pathogen entries
pathogens:
  - name: "Genus species"           # Scientific name (required)
    names_alt: ["Genus_species"]     # Alternative names for matching (GTDB uses underscores)
    taxid_ncbi: 12345                # NCBI taxonomy ID (required)
    common_name: "Common name"       # Display name in the UI
    threat_level: "high"             # critical, high, moderate, or low
    bsl_level: 2                     # Biosafety level (1-4)
    category: "BACTERIA"             # Grouping category (free text)
    alert_threshold: 10              # Minimum reads before alerting
    action_required: "Steps to take" # Guidance text shown on detection
    notes: "Additional context"      # Background information
```

### Field Reference

| Field | Required | Values | Description |
|-------|----------|--------|-------------|
| `name` | yes | string | Binomial scientific name |
| `names_alt` | no | list | Alternative names (underscore variants, synonyms) |
| `taxid_ncbi` | yes | int | NCBI taxonomy identifier |
| `common_name` | no | string | Short display name for the UI |
| `threat_level` | yes | critical/high/moderate/low | Determines alert severity and color |
| `bsl_level` | no | 1-4 | Biosafety level for handling guidance |
| `category` | no | string | Grouping label (e.g., BACTERIA, VIRUSES, FUNGI) |
| `alert_threshold` | no | int | Minimum read count to trigger an alert (default: 10) |
| `action_required` | no | string | Operator guidance shown when organism is detected |
| `notes` | no | string | Background information for the organism |

### Threat Level Behavior

| Level | UI Color | Alert Type | Typical Use |
|-------|----------|------------|-------------|
| `critical` | Red | Immediate notification | BSL-3+, select agents, WHO critical priority |
| `high` | Orange | Warning notification | BSL-2 with AMR concerns, invasive pathogens |
| `moderate` | Yellow | Informational | Common clinical pathogens, environmental indicators |
| `low` | Blue | Log only | Commensal organisms, low-virulence species |

### Creating Custom Watchlists

Save a YAML file following the v2.0 format and import it through the Watchlist & Preparation tab in the GUI. Example files are provided in `nanometa_live/core/config/data/watchlists/examples/`:

- `sti_pathogens.yaml` - Sexually transmitted infection organisms
- `neglected_tropical_diseases.yaml` - NTD surveillance targets
- `agricultural_plant.yaml` - Plant pathogen monitoring

### Taxid Mapping

When a watchlist is loaded, Nanometa Live maps each `taxid_ncbi` to the active Kraken2 database. Organisms not present in the database (e.g., eukaryotic parasites in a bacteria-only database) are reported as unmapped in the Watchlist & Preparation tab. Use a PlusPF or PlusPFP Kraken2 database for broader organism coverage.

## Pipeline Source Options

### Remote (GitHub)

```yaml
# Main branch (stable)
pipeline_source: "remote:master"

# Development branch
pipeline_source: "remote:dev"

# Specific release
pipeline_source: "remote:v1.2.0"
```

### Local Path

```yaml
# Local development copy
pipeline_source: "/path/to/nanometanf"
```

## Example Configurations

### Basic Batch Analysis

```yaml
analysis_name: "Batch Analysis"
nanopore_output_directory: "/data/sequencing/run_001"
results_output_directory: "/data/results/run_001"
kraken_db: "/databases/kraken2_standard"
processing_mode: "batch"
sample_handling: "by_barcode"
pipeline_profile: "conda"
```

### Real-time Monitoring

```yaml
analysis_name: "Live Monitoring"
nanopore_output_directory: "/sequencer/output/fastq_pass"
results_output_directory: "/data/live_results"
kraken_db: "/databases/kraken2_standard"
processing_mode: "realtime"
sample_handling: "by_barcode"
update_interval_seconds: 15
batch_size: 5
pipeline_profile: "conda"
```

### Single Sample Analysis

```yaml
analysis_name: "Single Sample"
nanopore_output_directory: "/data/sample_001"
results_output_directory: "/data/results/sample_001"
kraken_db: "/databases/kraken2_standard"
processing_mode: "batch"
sample_handling: "single_sample"
sample_name: "PATIENT_001"
pipeline_profile: "conda"
```

### With Validation

```yaml
analysis_name: "Pathogen Screening"
nanopore_output_directory: "/data/clinical/sample_001"
results_output_directory: "/data/results/clinical_001"
kraken_db: "/databases/kraken2_plusPF"
processing_mode: "batch"
sample_handling: "by_barcode"
pipeline_profile: "conda"

blast_validation: true
validation_method: "minimap2"
minimap2_preset: "map-ont"
minimap2_min_mapq: 30

danger_lower_limit: 50
```

## Command Line Options

```
nanometa-live [OPTIONS]

Options:
  --host TEXT      Host to bind (default: 127.0.0.1, use 0.0.0.0 for network access)
  --port INT       Server port (default: 8050)
  --config FILE    Configuration file path
  --debug          Enable debug mode
  --data-dir PATH  Application data directory (default: ~/.nanometa)
  --version        Show version
```

## Validation

The GUI validates configuration before starting:

- **Directories**: Checks paths exist and are accessible
- **Database**: Verifies Kraken2 database files present
- **Sample handling**: Warns if directory structure doesn't match mode
- **Required fields**: Ensures essential parameters are set

Error messages appear in the Configuration tab when validation fails.
