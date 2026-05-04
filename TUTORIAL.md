# Nanometa Live Tutorial

This tutorial will guide you through setting up and using Nanometa Live for real-time metagenomic analysis.

## Table of Contents

1. [Installation](#installation)
2. [First Run](#first-run)
3. [Configuration](#configuration)
4. [Starting Analysis](#starting-analysis)
5. [Monitoring Results](#monitoring-results)
6. [Exploring Visualizations](#exploring-visualizations)
7. [Exporting Data](#exporting-data)
8. [Troubleshooting](#troubleshooting)

## Installation

### Prerequisites

Before installing Nanometa Live, ensure you have:

- Python 3.9 or higher
- Conda/Mamba (recommended) or pip
- At least 8GB of RAM
- Sufficient disk space for sequence data and analysis results

### Installing with Conda/Mamba

```bash
# Create and activate a new environment
mamba create --name nanometa_live_env
mamba activate nanometa_live_env

# Install Nanometa Live
mamba install -c conda-forge -c bioconda nanometa-live
```

### Installing with pip

```bash
# Create and activate a virtual environment
python -m venv nanometa_env
source nanometa_env/bin/activate  # On Windows: nanometa_env\Scripts\activate

# Install Nanometa Live
pip install nanometa-live
```

## First Run

To start Nanometa Live, simply run:

```bash
nanometa-live
```

This command will:

1. Create a default data directory at `~/.nanometa`
2. Launch the application interface in your default web browser
3. Present the configuration tab as the first step

Additional command-line options:

```bash
# Specify a configuration file to load
nanometa-live --config /path/to/config.yaml

# Specify a data directory
nanometa-live --data-dir /path/to/data/directory

# Run in debug mode
nanometa-live --debug

# Use a specific port
nanometa-live --port 8080
```

## Configuration

The configuration tab is where you set up your analysis parameters:

### Basic Settings

1. **Analysis Name**: Enter a descriptive name for your analysis
2. **Nanopore Output Directory**: Specify the directory where the sequencer outputs FASTQ files
3. **Kraken2 Database**: Specify the path to your Kraken2 database
4. **Species of Interest**: Add species names to track in the results

### Advanced Settings

1. **Update Interval**: How often the interface should update (in seconds)
2. **Alert Threshold**: Species with reads above this threshold will be highlighted
3. **Taxonomy Settings**: Choose between GTDB or NCBI taxonomy
4. **Validation Settings**: Configure BLAST validation parameters
5. **Performance Settings**: Adjust CPU cores and memory usage

### Saving and Loading Configurations

- Click "Save Configuration" to save your settings for future use
- Click "Load Configuration" to select from previously saved configurations
- Click "Reset to Defaults" to reset all settings to their default values

## Starting Analysis

Once your configuration is complete:

1. Review your settings to ensure everything is correctly specified
2. Click the "Start Analysis" button in the header
3. Monitor the status indicator to confirm the analysis is running
4. Watch the file processing counts to track progress

## Monitoring Results

### Main Results Tab

The Main Results tab shows:

1. **Species of Interest**: A bar chart and table showing read counts for species you specified
2. **Top Matches**: A table of the most abundant taxonomic classifications

Use the controls to:
- Adjust the alert threshold for highlighting
- Toggle BLAST validation display
- Filter top matches by taxonomy level and domain
- Change the number of displayed entries

### QC Tab

The QC tab provides quality metrics:

1. **QC Statistics**: Processing statistics, filtering results, and classification rates
2. **QC Plots**:
   - Cumulative reads over time
   - Cumulative base pairs over time
   - Reads per batch
   - Base pairs per batch

## Exploring Visualizations

### Sankey Plot

The Sankey plot shows taxonomic relationships:

1. Use the "Filter by top reads" option to control how many taxa appear at each level
2. Select which domains to include (Bacteria, Archaea, Eukaryota, Viruses)
3. Choose which taxonomic levels to display
4. Click nodes to focus on specific branches
5. Drag nodes to rearrange the visualization

### Sunburst Chart

The Sunburst chart provides a radial view of taxonomic hierarchy:

1. Filter by minimum reads to control which taxa appear
2. Select which domains to include
3. Click on segments to zoom in and explore specific branches
4. Hover over segments to see details about each taxon
5. Click the center to zoom back out

## Exporting Data

Nanometa Live provides several ways to export your results:

### Export Tables

1. In the Main Results tab, click "Export Data" under either the Species of Interest or Top Matches sections
2. Enter a filename (or use the default)
3. Click "Export" to save as CSV

### Export Plots

1. In the QC tab, click "Export Plots"
2. Specify an export directory and base filename
3. Click "Export" to save images of all four QC plots

### Export Configuration

1. In the Configuration tab, click "Save Configuration"
2. Enter a name for your configuration
3. The configuration will be saved as a YAML file in the data directory

### Reports Directory

All exported files are saved to the reports directory within your data directory unless you specify otherwise:

```
~/.nanometa/reports/
```

## Troubleshooting

### Common Issues

#### Configuration Problems

- **Database not found**: Ensure the Kraken2 database path is correct
- **Input directory not found**: Check that the Nanopore output directory exists and is accessible
- **Permission denied**: Make sure you have read/write permissions for all specified directories

#### Performance Issues

- **Slow processing**: Try increasing the number of CPU cores in the Advanced Settings
- **High memory usage**: Enable memory mapping in the Advanced Settings
- **Interface lag**: Increase the update interval to reduce browser load

#### Data Problems

- **No species of interest showing**: Check that species names are correctly spelled
- **No data appearing**: Ensure that FASTQ files are being written to the specified input directory
- **Classification errors**: Verify that the Kraken2 database is compatible with your data

### Getting Help

If you encounter issues not covered in this guide:

1. Check the [GitHub Issues](https://github.com/FOI-Bioinformatics/nanometa_live/issues) for similar problems
2. Check the log files in `~/.nanometa/logs/` for error messages
3. Open a new issue on GitHub with details about your problem

## Next Steps

Once you're comfortable with the basic workflow, try:

- Creating custom databases for specific organisms
- Running simulations for testing and training
- Integrating Nanometa Live into your lab's workflow
- Contributing to the project by reporting bugs or suggesting features

Happy analyzing!