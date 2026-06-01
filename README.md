<p align="center">
  <img src="nanometa_live/app/assets/logo.png" alt="Nanometa Live" width="420">
</p>

# Nanometa Live

Real-time visualisation dashboard for Oxford Nanopore metagenomic sequencing
analysis.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

Nanometa Live is the front end for the
[nanometanf](https://github.com/FOI-Bioinformatics/nanometanf) Nextflow
pipeline. It monitors taxonomic classification output during sequencing,
surfaces detections of pathogens of interest, and provides per-sample
quality control and validation views. The application is a single-page
Dash web app that runs locally; the analysis itself is delegated to
nanometanf.

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
- Offline deployment workflow: bundle export and import for air-gapped
  field laboratories, with a pre-flight readiness checker.
- Web-based control of pipeline lifecycle (start, stop, configure) for
  operators without command-line access.

## Get started

- [Quick start with nanorunner](docs/quickstart-with-nanorunner.md) --
  end-to-end demo using simulated input.
- [User guide](docs/user-guide.md) -- full reference, including
  installation, configuration, and tab-by-tab walkthrough.
- [Operator guide](docs/OPERATOR_GUIDE.md) -- field-deployment reference
  and decision trees.

## Dashboard tabs

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

For pipeline execution: Nextflow 25.10 or later. Container engines are
not required; nanometanf runs under the `conda` profile by default.

## Development

The test suite needs the runtime dependencies (Dash, Plotly, pandas), so
install the package with its dev extras into a virtual environment:

```
pip install -e ".[dev]"
pytest               # full suite, parallel (pytest-xdist)
pytest -n 0          # serial, for pdb/print debugging
pytest --cov=nanometa_live --cov-report=term-missing   # with coverage gate
```

Tests marked `slow` need Nextflow/conda and are skipped by default; run them
with `pytest -m slow`. CI runs the suite and the coverage gate on Python 3.11
and 3.12 for every push and pull request to `main` and `dev`.

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
- [Documentation](docs/README.md)
