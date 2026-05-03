# Nanometa Live

Real-time visualisation dashboard for Oxford Nanopore metagenomic sequencing
analysis.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Nanometa Live is the front end for the
[nanometanf](https://github.com/FOI-Bioinformatics/nanometanf) Nextflow
pipeline. It monitors taxonomic classification output during sequencing,
surfaces detections of pathogens of interest, and provides per-sample quality
control and validation views. The application is a single-page Dash web app
that runs locally; the analysis itself is delegated to nanometanf.

## Features

- Real-time monitoring of cumulative Kraken2 reports during a sequencing run.
- Interactive taxonomic visualisations: Sankey flow and sunburst charts.
- Multi-sample support for barcoded (multiplexed) runs and flat directories.
- Pathogen screening against nine built-in watchlists (clinical pathogens,
  CDC bioterrorism agents, foodborne, respiratory, drinking water,
  nosocomial / ESKAPE, wastewater surveillance, zoonotic / One Health, and
  WHO priority pathogens), with operator-facing alert tiers and recommended
  actions.
- BLAST identity scoring and minimap2 coverage validation, including
  on-demand validation of unexpected detections via Nextflow `-resume`.
- Quality control panel with nanopore-calibrated thresholds and per-sample
  filtering statistics.
- Offline deployment workflow: bundle export and import for air-gapped field
  laboratories, with a pre-flight readiness checker.
- Web-based control of pipeline lifecycle (start, stop, configure) for
  operators without command-line access.

## Quick start

### Prerequisites

- Python 3.9 or later
- Conda or Miniconda
- Nextflow 25.10 or later (required by nanometanf)
- A Kraken2 database

The recommended environment manager is conda. For development, the
`nf-core` conda environment (used for nanometanf) is also suitable as a host
environment.

### Installation

```bash
conda create -n nanometa python=3.10
conda activate nanometa

git clone https://github.com/FOI-Bioinformatics/nanometa_live.git
cd nanometa_live
pip install -e .
```

### Running the dashboard

```bash
# Visualise an existing nanometanf results directory
nanometa-live --main_dir /path/to/results --port 8050

# Launch with a config file (full pipeline control)
nanometa-live --config config.yaml
```

Open <http://localhost:8050> in a browser. The dashboard auto-detects samples
in the configured directory, loads classification and QC outputs, and
refreshes on the configured interval.

### Offline deployment

```bash
# On a build host with internet access
nanometa-prepare deploy \
    --watchlists clinical_pathogens,cdc_bioterrorism \
    --db /path/to/kraken_db \
    --output /Volumes/USB/deployment_bundle

# On the air-gapped field machine
nanometa-prepare import --bundle /Volumes/USB/deployment_bundle

# Verify readiness before a run
nanometa-prepare check --db /path/to/kraken_db
```

Build and field machines must share the same operating system and CPU
architecture; conda environments contain absolute paths and per-architecture
binaries. See the [Operator Guide](docs/OPERATOR_GUIDE.md) for the full
workflow.

## Usage

### Input layouts

| Input type      | Directory structure                  | Sample handling      |
|-----------------|--------------------------------------|----------------------|
| Barcoded FASTQ  | `barcode01/`, `barcode02/`, ...      | Automatic detection  |
| Flat FASTQ      | `*.fastq.gz` files in one directory  | Single sample or per-file |
| Pipeline output | A nanometanf results directory       | Direct visualisation |

### Configuration

Key settings (configurable from the **Configuration** tab or in `config.yaml`):

- `nanopore_output_directory` -- input FASTQ directory
- `results_output_directory` -- output directory consumed by the dashboard
- `kraken_db` -- Kraken2 database path
- `processing_mode` -- `batch` (one-time) or `realtime` (continuous monitoring)
- `sample_handling` -- `by_barcode`, `single_sample`, or `per_file`
- `pipeline_profile` -- always `conda` for nanometanf

### Dashboard tabs

| Tab            | Purpose |
|----------------|---------|
| Dashboard      | Run status, pathogen alerts, sample summary, classification overview |
| Organisms      | Detected organisms with abundance, confidence, and watchlist flags |
| Quality Control| Nanopore-calibrated metrics and filtering statistics |
| Taxonomy       | Sankey flow and sunburst views for taxonomic exploration |
| Validation     | BLAST identity scores and minimap2 coverage plots |
| Watchlist      | Built-in watchlists, quick-start buttons, and custom imports |
| Configuration  | Analysis settings, pipeline control, save and load configurations |
| Preparation    | Offline bundle wizard, genome import, readiness checks |

## Documentation

| Document                                          | Content |
|---------------------------------------------------|---------|
| [User Guide](docs/user-guide.md)                  | End-to-end usage instructions |
| [Operator Guide](docs/OPERATOR_GUIDE.md)          | Field-deployment reference |
| [Configuration Reference](docs/configuration.md)  | All configuration options |
| [Developer Guide](docs/developer-guide.md)        | Architecture and contribution notes |
| [API Reference](docs/api-reference.md)            | Parser and data loader APIs |
| [Migration Guide](docs/MIGRATION_GUIDE_V2.md)     | Upgrading from v1.x to v2.0 |

## Example

```bash
# Visualise a test results directory
python -m nanometa_live.app --main_dir /path/to/test_data --port 8050
```

The dashboard will auto-detect samples, load Kraken2 reports, render the
visualisations, and refresh every 30 seconds (or whatever interval is
configured).

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

For pipeline execution: Nextflow 25.10 or later. Container engines are not
required; nanometanf runs under the `conda` profile by default.

## Citation

If you use Nanometa Live in research, please cite:

> Sandas K, Lewerentz J, Karlsson E, et al. *Nanometa Live: a user-friendly
> application for real-time metagenomic data analysis and pathogen
> identification.* Bioinformatics. 2024;40(3):btae108.
> [doi:10.1093/bioinformatics/btae108](https://doi.org/10.1093/bioinformatics/btae108)

## License

GNU General Public License v3.0. See [LICENSE](LICENSE.txt).

## Links

- [GitHub repository](https://github.com/FOI-Bioinformatics/nanometa_live)
- [nanometanf pipeline](https://github.com/FOI-Bioinformatics/nanometanf)
- [Issue tracker](https://github.com/FOI-Bioinformatics/nanometa_live/issues)
