# Nanometa Live: Real-time Metagenomic Analysis

![Cite](https://img.shields.io/badge/Cite-Our%20Paper-blue)

Nanometa Live is a comprehensive workflow equipped with a graphical user interface (GUI) for real-time metagenomic sequencing analysis. It is designed for Oxford Nanopore MinION and Flongle flow cells and utilizes Kraken2 for classification and BLAST for sequence validation. The tool offers a dynamic, offline-capable solution with custom database support.

## Features

- 📊 **Real-time Visualization**: Offers dynamic Sankey plots, sunburst charts, and more.
- 🌐 **Offline Support**: Operates without internet connectivity.
- 🛠️ **Custom Database Support**: Tailor the tool to your specific needs.
- 🔍 **Quality Control**: Features an inbuilt QC tab for basic data quality checks.
  
Visit our [Nanometa Live Wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki) for detailed documentation.

## Citation

If you use Nanometa Live in your research, please cite our publication:

> **Kristofer Sandås**, Jacob Lewerentz, Edvin Karlsson, Linda Karlsson, David Sundell, Kotryna Simonyté-Sjödin, Andreas Sjödin, *Nanometa Live: a user-friendly application for real-time metagenomic data analysis and pathogen identification*, **Bioinformatics**, Volume 40, Issue 3, March 2024, btae108, [https://doi.org/10.1093/bioinformatics/btae108](https://doi.org/10.1093/bioinformatics/btae108)

## Screenshots

<img src="https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/screenshots/main_tab.png" alt="main view" width="900" height="450">

<img src="https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/screenshots/sankey_plot.png" alt="sankey plot" width="900" height="450">

## Installation Guide

This section provides detailed instructions on how to install Nanometa Live. We recommend using [Miniforge](https://github.com/conda-forge/miniforge?tab=readme-ov-file#download) for a seamless installation experience.

### Prerequisites

Before you begin with the installation of `Nanometa Live`, make sure your system meets the following prerequisites:

#### System Requirements
- **Operating System**: Linux/Unix or macOS
- **Processor**: Intel Core i5 or equivalent
- **RAM**: 8GB minimum, 16GB recommended
- **Disk Space**: At least 10GB of free space



#### Software Dependencies
- [Python](https://www.python.org/downloads/): Version 3.9 or higher
- [Miniforge](https://github.com/conda-forge/miniforge?tab=readme-ov-file#download) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html)
- [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git) for cloning the repository
- [Kraken2](https://github.com/DerrickWood/kraken2) if not using the bundled version
- [BLAST](https://blast.ncbi.nlm.nih.gov/Blast.cgi?CMD=Web&PAGE_TYPE=BlastDocs&DOC_TYPE=Download) if not using the bundled version
- [NCBI Datasets](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/command-line/datasets/) if not using the bundled version

#### Network Requirements
- Internet access is required for initial setup and optional updates. The tool supports offline usage after the initial setup.

Make sure to meet all these prerequisites to avoid installation issues and to ensure smooth operation of `Nanometa Live`.


## Installation Guide

This section provides detailed instructions on how to install Nanometa Live. We recommend using [Mambaforge](https://github.com/conda-forge/miniforge#mambaforge) for a seamless installation experience.

1. [Install with Conda/Mamba (Recommended)](https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/Installation.md#option-1-install-with-condamamba-recommended)
2. [Install with Docker](https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/Installation.md#option-2-install-with-docker)
3. [Install with Singularity](https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/Installation.md#option-3-install-with-singularity)
4. [Install from Source Code](https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/Installation.md#option-4-install-from-source-code)

### Post-Installation

After installation, you can access the program from any directory by following the usage instructions below.

## Quick Start Tutorial

This guide will walk you through two options for getting started with Nanometa Live. Option A runs `nanometa-demo` to automatically download tutorial data and initiate the workflow. Option B guides you through a more manual setup process. To get started with the manual option , download the required tutorial files from [Figshare](https://figshare.com/articles/dataset/Nanometa_Live_tutorial_files/24233020).

### Option 1: Quick Start with Automated Demo

1. **Activate the Conda Environment**

```bash
mamba activate nanometa_live_env
```

2. **Run Automated Demo**

This step will automatically download the tutorial data from [Figshare](https://figshare.com/articles/dataset/Nanometa_Live_tutorial_files/24233020). Following the download, the `nanometa-demo` script will execute `nanometa-new` and `nanometa-prepare` to set up and configure your project for analysis. Lastly, it will automatically launch `nanometa-live` to initiate both the backend analysis and the graphical user interface (GUI).

```bash
nanometa-demo --path YOUR_DEMO_PATH
```

You might need to click or ctrl + click the port link that appears in your terminal to open the GUI.

To terminate the process, use the Shut down program button in the interface, or press Ctrl+C in the terminal multiple times if needed.

### Option 2: Manual Setup

For a manual project setup, please follow the detailed steps outlined below.

#### Step 1: Activate the Conda Environment
Ensure your Conda/Mamba environment is active by running:

```bash
mamba activate nanometa_live_env
```

#### Step 2: Initialize a New Project
Initialize your project by specifying various parameters. Replace the placeholders in the example command below with the appropriate paths.

```bash
working_dir=YOUR_PATH/metagenomic_project
species_file=PATH_TO/species.txt
kraken_folder=PATH_TO/kraken_db
fastq_folder=PATH_TO/fastq
kraken_tax=gtdb

nanometa-new --path ${working_dir} --species_of_interest ${species_file} --nanopore_output_directory  ${fastq_folder} --kraken_db ${kraken_folder} --kraken_taxonomy ${kraken_tax}
```

For a complete list of arguments, run: `nanometa-new --help`.


#### Step 3: Optional Configuration
Navigate to your newly-created project directory and open the `config.yaml` file. Verify the **Nanopore Output Directory** and the **Kraken 2 Database** directory.

📝 **Note**: Save your changes.


#### Step 4: Automatic Data Preparation
Execute the `nanometa-prepare` command to automatically download and create files needed for analysis.

```bash
nanometa-prepare --path ${working_dir} 
```

After this step, Nanometa Live will not need an internet connection.

#### Step 5: Simulate Nanopore Sequencing
Place the tutorial batch files (ending in `.fastq.gz`) in a directory, e.g., `/home/user/nanometa_test_data`. Then run:

```bash
nanometa-sim -i /SOMEPATH/nanometa_test_data -o  ${fastq_folder}
```

Ensure the `-o` flag's value matches the **Nanopore Output Directory** in your `config.yaml` file.


#### Step 6: Start Live Analysis
Execute the following command in another terminal to begin live analysis:

```bash
nanometa-live -p ${working_dir}
```

You might need to click or `ctrl` + click the port link that appears in your terminal to open the GUI.

To terminate the process, use the `Shut down program` button in the interface, or press `Ctrl+C` in the terminal multiple times if needed.

#### Step 7: Explore the GUI
- Use the `INFO/HELP` buttons for info about the different sections.
- Tooltips: Hover over GUI elements to view helpful tooltips.
- Wiki: For detailed descriptions, visit the [project wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki).
- Visual cues: In the "Species of interest" section in the GUI, species with a read count >100 will appear in red by default.

---

## Community & Support

- **Issues**: For bug reports, feature requests, or any other queries, please [open an issue](https://github.com/FOI-Bioinformatics/nanometa_live/issues).
- **Documentation**: Refer to our [Nanometa Live Wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki) for detailed guides, tutorials, and FAQs.


---

## License

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)

`Nanometa Live` is licensed under the GNU General Public License v3.0. This license grants you the freedom to use, modify, and distribute the software in both source and binary form, provided that you include the original copyright and
license notice in any copy of the software or source code.

For the full license text, please refer to the [LICENSE](LICENSE.txt) file in the repository. This license was chosen to promote freedom in using the software and to ensure that derivative works are shared with the community.


---


