# Configuration Reference

Complete reference for all Nanometa Live configuration options.

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
| `analysis_name` | string | "Nanometa Analysis" | Display name for this analysis |
| `nanopore_output_directory` | path | required | Directory containing FASTQ files |
| `results_output_directory` | path | auto | Where to write pipeline output |
| `main_dir` | path | same as results | Directory for visualization (usually same as results) |

### Processing

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `processing_mode` | string | "batch" | `batch` or `realtime` |
| `sample_handling` | string | "by_barcode" | `by_barcode`, `single_sample`, or `per_file` |
| `sample_name` | string | "sample" | Name when using single_sample mode |

### Kraken2 Classification

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `kraken_db` | path | required | Path to Kraken2 database |
| `kraken_taxonomy` | string | "ncbi" | `ncbi` or `gtdb` |
| `kraken_memory_mapping` | bool | true | Memory-map database for speed |
| `kraken2_enable_incremental` | bool | true (realtime) | Incremental classification |

### Pipeline Execution

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pipeline_profile` | string | "docker" | `docker`, `singularity`, or `conda` |
| `pipeline_source` | string | "remote:main" | Pipeline location (see below) |
| `pipeline_cores` | int | 4 | CPU cores for pipeline |

### GUI Settings

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `update_interval_seconds` | int | 30 | Dashboard refresh interval |
| `gui_port` | string | "8050" | Web server port |
| `danger_lower_limit` | int | 100 | Alert threshold for species of interest |

### Visualization

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `default_hierarchy_letters` | list | ["D","C","G","S"] | Default taxonomy levels |
| `taxonomic_hierarchy_letters` | list | ["D","P","C","O","F","G","S"] | Available levels |
| `default_reads_per_level` | int | 10 | Minimum reads to display |

### Optional Features

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `blast_validation` | bool | false | Enable BLAST validation |
| `blast_db` | path | null | BLAST database path |
| `remove_temp_files` | bool | true | Clean up intermediate files |

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

## Pipeline Source Options

### Remote (GitHub)

```yaml
# Main branch (stable)
pipeline_source: "remote:main"

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

## Real-time Mode Settings

Additional options for real-time monitoring:

```yaml
processing_mode: "realtime"

# Batching
batch_size: 10                    # Files per batch
batch_interval: "5min"            # Time between batches

# Monitoring
realtime_timeout_minutes: 180     # Inactivity timeout
file_pattern: "**/*.fastq.gz"     # File matching pattern
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
pipeline_profile: "docker"
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
realtime_timeout_minutes: 480
pipeline_profile: "docker"
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
pipeline_profile: "docker"
```

### With Species Tracking

```yaml
analysis_name: "Pathogen Screening"
nanopore_output_directory: "/data/clinical/sample_001"
results_output_directory: "/data/results/clinical_001"
kraken_db: "/databases/kraken2_plusPF"
processing_mode: "batch"
sample_handling: "by_barcode"
pipeline_profile: "docker"

species_of_interest:
  - name: "Yersinia pestis"
    taxid: "632"
  - name: "Bacillus anthracis"
    taxid: "1392"
  - name: "Francisella tularensis"
    taxid: "263"

danger_lower_limit: 50
blast_validation: true
blast_db: "/databases/nt"
```

## Environment Variables

Override settings via environment:

```bash
# Debug mode
DASH_DEBUG=true python -m nanometa_live.app --config config.yaml

# Custom port
python -m nanometa_live.app --port 8080
```

## Command Line Options

```bash
python -m nanometa_live.app [OPTIONS]

Options:
  --main_dir PATH    Results directory (visualization only)
  --config FILE      Configuration file path
  --port INT         Server port (default: 8050)
  --debug            Enable debug mode
  --data-dir PATH    Application data directory
  --version          Show version
```

## Validation

The GUI validates configuration before starting:

- **Directories**: Checks paths exist and are accessible
- **Database**: Verifies Kraken2 database files present
- **Sample handling**: Warns if directory structure doesn't match mode
- **Required fields**: Ensures essential parameters are set

Error messages appear in the Configuration tab when validation fails.
