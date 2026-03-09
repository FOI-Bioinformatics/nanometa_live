# Nanometa Live

Real-time visualization dashboard for Oxford Nanopore metagenomic sequencing analysis.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Nanometa Live provides real-time monitoring and visualization of taxonomic classification results from nanopore sequencing runs. It integrates with the [nanometanf](https://github.com/FOI-Bioinformatics/nanometanf) Nextflow pipeline for automated analysis.

## Features

- **Real-time Monitoring**: Watch classification results update as sequencing progresses
- **Interactive Visualizations**: Sankey diagrams and sunburst charts for taxonomic exploration
- **Multi-sample Support**: Analyze barcoded/multiplexed sequencing runs
- **Pathogen Screening**: 9 built-in watchlists (Clinical Pathogens, Federal Select Agents, WHO Priority, Foodborne, Respiratory, Water Safety, Nosocomial/ESKAPE, Wastewater Surveillance, Zoonotic One Health) with threat-level alerts and action guidance
- **Decision Support**: Traffic-light status indicators, severity-matched alerts, and confidence scoring for clinical operators
- **Validation**: BLAST identity scores and minimap2 coverage validation of detected organisms
- **Quality Control**: Nanopore-calibrated QC metrics with per-sample filtering statistics
- **Offline Deployment**: Preparation wizard for air-gapped field labs with bundle export/import
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

```bash
# Launch the dashboard
nanometa-live

# Or with a specific config
nanometa-live --config config.yaml
```

Then open http://localhost:8050 in your browser.

### Offline Deployment

```bash
# Prepare a deployment bundle (with internet)
nanometa-prepare deploy \
  --watchlists clinical_pathogens,cdc_bioterrorism \
  --db /path/to/kraken_db \
  --output /Volumes/USB/deployment_bundle

# Import bundle on air-gapped machine
nanometa-prepare import --bundle /Volumes/USB/deployment_bundle

# Verify readiness
nanometa-prepare check --db /path/to/kraken_db
```

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
| **Dashboard** | Run status, pathogen alerts, sample summary, classification overview |
| **Organisms** | Detected organisms with abundance, confidence, and watchlist flags |
| **Quality Control** | Nanopore-calibrated quality metrics and filtering statistics |
| **Taxonomy** | Interactive Sankey flow and sunburst charts for taxonomic exploration |
| **Validation** | BLAST identity scores and minimap2 genome coverage plots |
| **Watchlist** | 9 built-in pathogen watchlists with quick-start buttons and custom import |
| **Configuration** | Analysis settings, pipeline control, save/load configurations |
| **Preparation** | Offline deployment wizard, genome import, readiness checks |

## Documentation

| Document | Description |
|----------|-------------|
| [User Guide](docs/user-guide.md) | Complete usage instructions |
| [Operator Guide](docs/OPERATOR_GUIDE.md) | Quick reference for lab personnel |
| [Configuration Reference](docs/configuration.md) | All configuration options |
| [Developer Guide](docs/developer-guide.md) | Architecture and contributing |
| [API Reference](docs/api-reference.md) | Parser and data loader APIs |
| [Migration Guide](docs/MIGRATION_GUIDE_V2.md) | Upgrading from v1.x to v2.0 |

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
dash>=4.0.0
dash-ag-grid>=31.0.0
dash-bootstrap-components>=1.7.1
plotly>=6.0.0
pandas>=2.2.3
ruamel.yaml>=0.18.10
biopython>=1.85
psutil>=6.0.0
diskcache>=5.6.0
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
