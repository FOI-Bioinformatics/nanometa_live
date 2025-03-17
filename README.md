# Nanometa Live: Real-time Metagenomic Analysis

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)

Nanometa Live is a comprehensive workflow with a user-friendly graphical interface for real-time metagenomic sequencing analysis. It is designed for Oxford Nanopore MinION and Flongle flow cells, utilizing Kraken2 for classification and BLAST for sequence validation.

## New Streamlined Interface

This updated version of Nanometa Live features a completely redesigned user experience that makes it easier than ever to get started:

- **Single Command Setup**: Start the application with a single `nanometa-live` command
- **In-App Configuration**: Configure all settings directly within the user interface
- **Save/Load Configurations**: Save your configurations for future use and quickly switch between projects
- **Real-time Monitoring**: View analysis progress, quality metrics, and results in real-time
- **Interactive Visualizations**: Explore your data with dynamic, interactive charts and plots

## Features

- 📊 **Real-time Visualization**: Dynamic Sankey plots, sunburst charts, and more
- 🌐 **Offline Support**: Operates without internet connectivity after initial setup
- 🛠️ **Custom Database Support**: Use your own custom Kraken2 databases
- 🔍 **Quality Control**: Built-in QC tab for monitoring data quality
- 🔄 **Automated Analysis**: Continuously processes new data as it becomes available

## Screenshots

![Main View](https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/screenshots/main_tab.png)

![Sankey Plot](https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/screenshots/sankey_plot.png)

## Quick Start

### Installation

#### Option 1: Install with Conda/Mamba (Recommended)

```bash
# Create a new environment
mamba create --name nanometa_live_env
# Activate the environment
mamba activate nanometa_live_env
# Install Nanometa Live
mamba install -c conda-forge -c bioconda nanometa-live
```

#### Option 2: Install with pip

```bash
# Create a virtual environment
python -m venv nanometa_env
# Activate the environment
source nanometa_env/bin/activate
# Install Nanometa Live
pip install nanometa-live
```

### Running Nanometa Live

Simply run the following command to start the application:

```bash
nanometa-live
```

This will:
1. Start the Nanometa Live interface in your default web browser
2. Load any existing configuration or create a default one
3. Allow you to configure and start your analysis workflow

### Configuration

In the Configuration tab, you can:

1. Set up your project with a name and description
2. Specify the Nanopore output directory and Kraken2 database
3. Add species of interest to track
4. Adjust performance settings
5. Save your configuration for future use

Once configured, click "Start Analysis" to begin processing.

## Usage Guide

### Main Results Tab

The Main Results tab displays:
- Species of interest with read counts
- Top matches from the analysis
- Export options for saving results

### QC Tab

The QC tab provides:
- Processing statistics
- Read quality metrics
- Interactive charts of cumulative and per-batch data

### Sankey Plot Tab

The Sankey Plot tab offers:
- Hierarchical visualization of taxonomic classifications
- Filtering options for domains and taxonomic levels
- Customizable visualization settings

### Sunburst Chart Tab

The Sunburst Chart provides:
- Radial visualization of taxonomic hierarchy
- Interactive zooming for detailed exploration
- Filtering options for minimum read counts

## Advanced Usage

### Running a Simulated Analysis

For testing or demonstration purposes, you can use the built-in simulator:

```bash
# Simulate Nanopore sequencing output
nanometa-sim -f reference.fastq.gz -o output_dir -n 100 --num_files 10
```

### Manual Backend Control

If needed, you can manually control the backend process:

```bash
# Start only the backend processing
nanometa-backend --config your_config.yaml
```

## Community & Support

- **Issues**: For bug reports, feature requests, or questions, please [open an issue](https://github.com/FOI-Bioinformatics/nanometa_live/issues)
- **Documentation**: Refer to our [Wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki) for detailed guides

## Citation

If you use Nanometa Live in your research, please cite our publication:

> **Kristofer Sandås**, Jacob Lewerentz, Edvin Karlsson, Linda Karlsson, David Sundell, Kotryna Simonyté-Sjödin, Andreas Sjödin, *Nanometa Live: a user-friendly application for real-time metagenomic data analysis and pathogen identification*, **Bioinformatics**, Volume 40, Issue 3, March 2024, btae108, [https://doi.org/10.1093/bioinformatics/btae108](https://doi.org/10.1093/bioinformatics/btae108)

## License

Nanometa Live is licensed under the GNU General Public License v3.0. See the [LICENSE](LICENSE.txt) file for details.