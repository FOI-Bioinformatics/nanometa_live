# Nanometa Live User Guide

## Overview

Nanometa Live is a real-time visualization dashboard for Oxford Nanopore metagenomic sequencing. It displays taxonomic classification results, quality metrics, and provides interactive visualizations as your sequencing run progresses.

## Installation

### Prerequisites

- Python 3.9 or higher
- Docker (recommended) or Conda/Mamba
- Nextflow 23.04+ (for running analysis pipelines)
- A Kraken2 database

### Install with pip

```bash
# Create virtual environment
python -m venv nanometa_env
source nanometa_env/bin/activate

# Install
pip install nanometa-live
```

### Install with Conda

```bash
conda create -n nanometa python=3.10
conda activate nanometa
pip install nanometa-live
```

### Install from source

```bash
git clone https://github.com/FOI-Bioinformatics/nanometa_live.git
cd nanometa_live
pip install -e .
```

## Quick Start

### View Existing Results

If you already have nanometanf pipeline output:

```bash
python -m nanometa_live.app --main_dir /path/to/results
```

Open http://localhost:8050 in your browser.

### Run New Analysis

To analyze new sequencing data:

```bash
python -m nanometa_live.app --config my_config.yaml
```

## Input Data

### Supported Input Formats

| Format | Description | Example |
|--------|-------------|---------|
| Barcoded directories | Each barcode in subdirectory | `barcode01/`, `barcode02/` |
| Flat FASTQ | All files in one directory | `*.fastq.gz` |
| nanometanf output | Pre-analyzed results | `kraken2/`, `fastp/` subdirs |

### Barcoded Data Structure

```
input_directory/
├── barcode01/
│   ├── reads_001.fastq.gz
│   └── reads_002.fastq.gz
├── barcode02/
│   └── reads_001.fastq.gz
└── unclassified/
    └── reads.fastq.gz
```

### Flat Directory Structure

```
input_directory/
├── sample_001.fastq.gz
├── sample_002.fastq.gz
└── sample_003.fastq.gz
```

## Dashboard Tabs

### Dashboard Tab

Overview of your analysis:
- Current status and elapsed time
- Sample summary
- Alerts for species of interest

### Organisms Tab

Detected organisms and classification results:
- **Organism Cards**: Each detected organism with abundance bars and confidence badges
- **Summary Card**: Total organisms, DNA sequences, classification rate
- **Watchlist Matches**: Organisms matching active watchlist entries highlighted
- **On-Demand Validation**: Validate unexpected organisms with BLAST

### Quality Control Tab

Quality control metrics:
- Quality score indicator with plain-language rating
- Filtering breakdown visualization
- Read counts before/after filtering
- Per-sample statistics table with color-coded quality
- Time-series plots of cumulative and per-batch data

### Taxonomy Tab

Interactive taxonomic visualizations:
- **Sankey Diagram**: Flow visualization of taxonomic hierarchy
- **Sunburst Chart**: Radial hierarchical view
- Filters for minimum reads, domains, and taxonomy levels

### Validation Tab

Organism identity verification:
- **BLAST Sub-tab**: Read-centric validation with identity scores, filtering, and statistics
- **Coverage Sub-tab**: Genome-centric minimap2 coverage plots (depth, cumulative, histogram)
- Species selector and mapping quality filters

### Watchlist Tab

Pathogen monitoring management:
- Browse and activate built-in watchlists (clinical, foodborne, respiratory, etc.)
- Upload custom watchlist YAML files
- Toggle individual pathogen entries on/off
- Kraken2 taxid mapping for database compatibility

### Configuration Tab

Analysis settings:
- Input/output directories
- Kraken2 database selection
- Processing mode (batch/real-time)
- Start/stop analysis controls

### Preparation Tab

Pre-run setup:
- Reference genome downloads for watchlist pathogens
- BLAST database preparation
- Genome management status

## Processing Modes

### Batch Mode

Processes all existing FASTQ files once:

1. Set Processing Mode to "Batch"
2. Select your input directory
3. Click "Start Analysis"
4. Results appear after pipeline completes

Best for: Completed sequencing runs, re-analysis

### Real-time Mode

Continuously monitors for new files:

1. Set Processing Mode to "Real-time"
2. Point to your sequencing output directory
3. Click "Start Analysis"
4. Results update as new data arrives

Best for: Active sequencing runs, live monitoring

## Sample Handling

### By Barcode

Use when your data is in barcode subdirectories:
- Automatically detects `barcode01/`, `barcode02/`, etc.
- Each subdirectory becomes a separate sample
- Use sample selector to view individual barcodes

### Single Sample

Use when all files belong to one sample:
- All FASTQ files merged for analysis
- Enter a sample name in the configuration
- Good for non-multiplexed runs

### Per File

Use when each file is a separate sample:
- Sample names derived from filenames
- Each file processed independently
- Useful for plate-based experiments

## Status Indicators

### Header Status

- **Status Light**: Green (running), Gray (idle), Red (error)
- **Timer**: Countdown to next data refresh
- **Elapsed Time**: Time since analysis started
- **Current Stage**: Active pipeline process

### Pipeline Progress

When analysis is running:
- Stage name (FASTP, KRAKEN2, etc.)
- Process counts (completed/total)
- Batch number (in real-time mode)

## Configuration File

Save your settings for reuse:

```yaml
analysis_name: "My Analysis"
nanopore_output_directory: "/data/sequencing/run_001"
results_output_directory: "/data/results/run_001"
kraken_db: "/databases/kraken2_standard"

processing_mode: "realtime"
sample_handling: "by_barcode"
update_interval_seconds: 30

pipeline_profile: "docker"
blast_validation: false

# Watchlists are managed via the Watchlist tab in the GUI
# Built-in watchlists: clinical_pathogens, foodborne, respiratory, etc.
```

## Tips

### Performance

- Use a fast SSD for the Kraken2 database
- Enable `kraken_memory_mapping` for large databases
- Adjust `update_interval_seconds` based on your needs (30-60s typical)

### Troubleshooting

**No samples detected:**
- Check that your directory structure matches the selected sample handling mode
- Verify FASTQ files have `.fastq` or `.fastq.gz` extension

**Visualizations not updating:**
- Ensure the backend is running (check status indicator)
- Verify the results directory contains expected output files

**Pipeline errors:**
- Check Docker/Singularity is running
- Verify Kraken2 database path is correct
- Review Nextflow logs in the results directory

## Next Steps

- [Configuration Reference](configuration.md) - All available options
- [Operator Guide](OPERATOR_GUIDE.md) - Quick reference card
- [Developer Guide](developer-guide.md) - Extending Nanometa Live
