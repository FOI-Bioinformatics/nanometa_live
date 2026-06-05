# Nanometa Live user guide

## Overview

Nanometa Live is a real-time visualisation dashboard for Oxford Nanopore metagenomic sequencing. It displays taxonomic classification results, quality metrics, and interactive visualisations as a sequencing run progresses.

## Installation

### Prerequisites

- Python 3.9 or higher
- Conda or Mamba (the canonical and supported pipeline profile)
- Nextflow 25.10 or newer (for running analysis pipelines)
- A Kraken2 database

### Install with pip

```bash
# Create virtual environment
python -m venv nanometa_env
source nanometa_env/bin/activate

# Install
pip install nanometa-live
```

### Install with conda

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

## Quick start

### View existing results

If you already have nanometanf pipeline output:

```bash
nanometa-live --main_dir /path/to/results
```

Open http://localhost:8050 in your browser.

### Run new analysis

To analyse new sequencing data:

```bash
nanometa-live --config my_config.yaml
```

## Input data

### Supported input formats

| Format | Description | Example |
|--------|-------------|---------|
| Barcoded directories | Each barcode in subdirectory | `barcode01/`, `barcode02/` |
| Flat FASTQ | All files in one directory | `*.fastq.gz` |
| nanometanf output | Pre-analyzed results | `kraken2/`, `fastp/` subdirs |

### Barcoded data structure

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

### Flat directory structure

```
input_directory/
├── sample_001.fastq.gz
├── sample_002.fastq.gz
└── sample_003.fastq.gz
```

## Dashboard tabs

### Dashboard tab

Operator-facing summary view. Four zones, top to bottom:

- **Zone 1 — Clinical verdict banner**. A full-width card whose background color is the answer: green "ALL CLEAR", red "ACTION REQUIRED", amber "MONITORING", blue "SCREENING IN PROGRESS", grey "STANDBY". Shows run state, elapsed time, last-updated timestamp, and (when applicable) a "pending confirmatory validation" qualifier.
- **Zone 2 — Pathogen alert cards** (shown only when alerts exist). Each alert card names the detected organism, read count and abundance, confidence level, and a "DETECTED IN:" row with per-sample chips indicating which samples the pathogen was found in. Chips are colored by severity tier. Samples marked as negative controls appear as flat gray chips with an `(NC)` suffix.
- **Zone 3 — Supporting metrics** (four cards): Sequences Analyzed, Sample Quality (Excellent / Good / Fair / Poor with Q-score subtitle), Species Detected, Run Time.
- **Zone 4 — Sample Details** (collapsed accordion). Per-sample table with plain-language column names: "Sequences Analyzed", "Sample Quality", "Read Length", "Match Rate".

### Organisms tab

Detected organisms and classification results:

- **Organism cards**: each detected organism with abundance bars and confidence badges
- **Summary card**: total organisms, DNA sequences (cumulative across all batches), classification rate
- **Watchlist matches**: organisms matching active watchlist entries are highlighted
- **On-demand validation**: validate unexpected organisms with BLAST

### Quality Control tab

Quality control metrics:

- **Stage Strip** at top: horizontal `Raw → Quality-filtered → Classified` with counts, tool subtitles, arrows, and a classification-rate delta beneath. For Chopper pipelines the Raw slot shows a dashed "Not available" placeholder because Chopper has no pre-filter stage.
- **Read Quality** card: Avg Q, Q20, Q30, GC with color-coded thresholds (Q30 green ≥45%, amber 25–44%, red <25%)
- **Read Length** card: N50, average length, total bases
- **Sample Breakdown** table: per-sample filtered reads, classification rate, and average Q score with tool-source tooltips
- **Advanced** sections (accordion): detailed processing charts and technical statistics

### Taxonomy tab

Interactive taxonomic visualizations:
- **Sankey Diagram**: Flow visualization of taxonomic hierarchy
- **Sunburst Chart**: Radial hierarchical view
- Filters for minimum reads, domains, and taxonomy levels

### Validation tab

Organism identity verification:
- **BLAST Sub-tab**: Read-centric validation with identity scores, filtering, and statistics
- **Coverage Sub-tab**: Genome-centric minimap2 coverage plots (depth, cumulative, histogram)
- Species selector and mapping quality filters

### Watchlist & Preparation tab

Pathogen monitoring management (watchlist selection and pre-run preparation are
combined in this single tab):
- Browse and activate the 9 built-in watchlists (clinical_pathogens, cdc_bioterrorism, who_priority, foodborne, respiratory, who_drinking_water, nosocomial_eskape, wastewater_surveillance, zoonotic_one_health)
- Upload custom watchlist YAML files
- Toggle individual pathogen entries on/off
- Kraken2 taxid mapping for database compatibility

### Configuration tab

Analysis settings:
- Input/output directories
- Kraken2 database selection
- Processing mode (batch/real-time)
- Start/stop analysis controls

### Preparation (part of the Watchlist & Preparation tab)

Pre-run setup, in the lower section of the Watchlist & Preparation tab:
- Reference genome downloads for watchlist pathogens
- BLAST database preparation
- Genome management status

## Processing modes

### Batch mode

Processes all existing FASTQ files once:

1. Set Processing Mode to "Batch"
2. Select your input directory
3. Click "Start Analysis"
4. Results appear after pipeline completes

Best for: Completed sequencing runs, re-analysis

### Real-time mode

Continuously monitors for new files:

1. Set Processing Mode to "Real-time"
2. Point to your sequencing output directory
3. Click "Start Analysis"
4. Results update as new data arrives

Best for: Active sequencing runs, live monitoring

## Sample handling

### By barcode

Use when your data is in barcode subdirectories:
- Automatically detects `barcode01/`, `barcode02/`, etc.
- Each subdirectory becomes a separate sample
- Use sample selector to view individual barcodes

### Single sample

Use when all files belong to one sample:
- All FASTQ files merged for analysis
- Enter a sample name in the configuration
- Good for non-multiplexed runs

### Per file

Use when each file is a separate sample:
- Sample names derived from filenames
- Each file processed independently
- Useful for plate-based experiments

## Status indicators

### Header status

- **Status light**: Green (running), Gray (idle), Red (error)
- **Timer**: Countdown to next data refresh
- **Elapsed time**: Time since analysis started
- **Current stage**: Active pipeline process

### Pipeline progress

When analysis is running:
- Stage name (Chopper, Kraken2, SeqKit, etc.)
- Process counts (completed/total)
- Batch number (in real-time mode)

### Dashboard verdict states

The Dashboard verdict banner color is the primary signal:

| State | Color | Meaning |
|-------|-------|---------|
| ALL CLEAR | Green | No watched pathogens detected; run is progressing or complete |
| ACTION REQUIRED | Red | A critical or high-risk watched pathogen was detected — follow your safety protocol |
| MONITORING | Amber | Only moderate-risk watched species detected |
| SCREENING IN PROGRESS | Blue | Run is active; first batch not yet processed |
| STANDBY | Grey | No run active |

## Configuration file

Save your settings for reuse:

```yaml
analysis_name: "My Analysis"
nanopore_output_directory: "/data/sequencing/run_001"
results_output_directory: "/data/results/run_001"
kraken_db: "/databases/kraken2_standard"

processing_mode: "realtime"
sample_handling: "by_barcode"
update_interval_seconds: 30

pipeline_profile: "conda"
blast_validation: false

# Watchlists are managed via the watchlist tab in the GUI
# 9 built-in watchlists: clinical_pathogens, cdc_bioterrorism, who_priority,
# foodborne, respiratory, who_drinking_water, nosocomial_eskape,
# wastewater_surveillance, zoonotic_one_health
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
- Verify the conda environment is activated and `nextflow -version` reports 25.10 or newer
- Verify Kraken2 database path is correct
- Review Nextflow logs in the results directory

## Next steps

- [Configuration reference](configuration.md) -- all available options
- [Operator guide](OPERATOR_GUIDE.md) -- field-deployment reference and decision trees
- [Developer guide](developer-guide.md) -- extending Nanometa Live
