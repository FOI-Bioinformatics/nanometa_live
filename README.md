# Nanometa Live

Real-time visualization dashboard for Oxford Nanopore metagenomic sequencing analysis.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Nanometa Live provides real-time monitoring and visualization of taxonomic classification results from nanopore sequencing runs. It integrates with the [nanometanf](https://github.com/FOI-Bioinformatics/nanometanf) Nextflow pipeline for automated analysis.

## Features

- **Real-time Monitoring**: Watch classification results update as sequencing progresses
- **Interactive Visualizations**: Sankey diagrams and sunburst charts for taxonomic exploration
- **Multi-sample Support**: Analyze barcoded/multiplexed sequencing runs
- **Species Tracking**: Configure alerts for organisms of interest
- **Quality Control**: Monitor read quality and filtering statistics
- **GUI-based Control**: Start/stop analysis and configure settings from the web interface

## Quick Start

### Prerequisites

- Python 3.9+
- Docker (recommended) or Conda
- [Nextflow](https://www.nextflow.io/) (for running the analysis pipeline)

### Installation

```bash
# Create and activate environment
conda create -n nanometa python=3.10
conda activate nanometa

# Install from source
git clone https://github.com/FOI-Bioinformatics/nanometa_live.git
cd nanometa_live
pip install -e .
```

### Running the Dashboard

**Visualization mode** (view existing results):
```bash
python -m nanometa_live.app --main_dir /path/to/nanometanf/output
```

**Full analysis mode** (run pipeline from GUI):
```bash
python -m nanometa_live.app --config config.yaml
```

Then open http://localhost:8050 in your browser.

## Usage

### Input Data Formats

Nanometa Live supports multiple input configurations:

| Input Type | Directory Structure | Sample Handling |
|------------|---------------------|-----------------|
| Barcoded FASTQ | `barcode01/`, `barcode02/`, ... | Automatic detection |
| Flat FASTQ | `*.fastq.gz` files | Single sample or per-file |
| Pipeline Output | nanometanf results directory | Direct visualization |

### Configuration

Key settings in the Configuration tab:

- **Input Directory**: Path to FASTQ files or nanometanf output
- **Kraken2 Database**: Path to classification database
- **Processing Mode**: Batch (one-time) or Real-time (continuous monitoring)
- **Sample Handling**: By barcode, single sample, or per-file

### Dashboard Tabs

| Tab | Purpose |
|-----|---------|
| **Dashboard** | Overview with status indicators and alerts |
| **Main Results** | Species of interest and top classifications |
| **QC** | Quality metrics and filtering statistics |
| **Classification** | Interactive Sankey/Sunburst visualizations |
| **Configuration** | Analysis settings and pipeline control |

## Documentation

| Document | Description |
|----------|-------------|
| [User Guide](docs/user-guide.md) | Complete usage instructions |
| [Configuration Reference](docs/configuration.md) | All configuration options |
| [Developer Guide](docs/developer-guide.md) | Architecture and contributing |
| [API Reference](docs/api-reference.md) | Parser and data loader APIs |

## Example

```bash
# Run with test data
python -m nanometa_live.app \
    --main_dir /path/to/test_data \
    --port 8050

# The dashboard will:
# 1. Auto-detect samples from the directory
# 2. Load Kraken2 classification results
# 3. Display interactive visualizations
# 4. Update automatically every 30 seconds
```

## Requirements

```
dash>=2.0.0
dash-bootstrap-components>=1.0.0
plotly>=5.0.0
pandas>=1.3.0
pyyaml>=5.4
```

For pipeline execution:
- Nextflow 23.04+
- Docker or Singularity

## Citation

If you use Nanometa Live in your research, please cite:

> Sandas K, Lewerentz J, Karlsson E, et al. *Nanometa Live: a user-friendly application for real-time metagenomic data analysis and pathogen identification.* Bioinformatics. 2024;40(3):btae108. [doi:10.1093/bioinformatics/btae108](https://doi.org/10.1093/bioinformatics/btae108)

## License

GNU General Public License v3.0. See [LICENSE](LICENSE.txt).

## Links

- [GitHub Repository](https://github.com/FOI-Bioinformatics/nanometa_live)
- [nanometanf Pipeline](https://github.com/FOI-Bioinformatics/nanometanf)
- [Issue Tracker](https://github.com/FOI-Bioinformatics/nanometa_live/issues)
