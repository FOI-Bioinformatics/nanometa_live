# Nanometa Live: Real-time Metagenomic Analysis

Nanometa Live is a comprehensive workflow equipped with a graphical user interface (GUI) for real-time metagenomic sequencing analysis. It is designed for Oxford Nanopore MinION and Flongle flow cells and utilizes Kraken2 for classification and BLAST for sequence validation. The tool offers a dynamic, offline-capable solution with custom database support.


<img src="https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/screenshots/main_tab.png" alt="main view" width="900" height="450">

<img src="https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/screenshots/sankey_plot.png" alt="main view" width="900" height="450">

## Features

- 📊 **Real-time Visualization**: Offers dynamic Sankey plots, sunburst charts, and more.
- 🌐 **Offline Support**: Operates without internet connectivity.
- 🛠️ **Custom Database Support**: Tailor the tool to your specific needs.
- 🔍 **Quality Control**: Features an inbuilt QC tab for basic data quality checks.
  
For further details, visit our [Wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki).


## Prerequisites

Before you begin with the installation of `Nanometa Live`, make sure your system meets the following prerequisites:

### System Requirements
- Operating System: Linux/Unix or macOS
- Processor: Intel Core i5 or equivalent
- RAM: 8GB minimum, 16GB recommended
- Disk Space: At least 10GB of free space

### Software Dependencies
- [Python](https://www.python.org/downloads/): Version 3.9 or higher
- [Mambaforge](https://github.com/conda-forge/miniforge#mambaforge) or [Conda](https://docs.conda.io/en/latest/miniconda.html)
- [Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git) for cloning the repository
- [Kraken2](https://github.com/DerrickWood/kraken2) if not using the bundled version
- [BLAST](https://blast.ncbi.nlm.nih.gov/Blast.cgi?CMD=Web&PAGE_TYPE=BlastDocs&DOC_TYPE=Download) if not using the bundled version
- [NCBI Datasets](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/command-line/datasets/) if not using the bundled version

### Network Requirements
- Internet access is required for initial setup and optional updates. The tool supports offline usage after the initial setup.

Make sure to meet all these prerequisites to avoid installation issues and to ensure smooth operation of `Nanometa Live`.


## Installation Guide
This section provides detailed instructions on how to install Nanometa Live. We recommend using [Mambaforge](https://github.com/conda-forge/miniforge#mambaforge) for a seamless installation experience.

### Option 1: Install with Conda/Mamba (Recommended)

1. **Create a New Environment:**

    Create a new Conda or Mamba environment and install Nanometa Live. Run the following command in your terminal:

    ```bash
    mamba create --name nanometa_live_env nanometa-live
    ```

2. **Activate the Environment:**

    After the environment is created, activate it using the following command:

    ```bash
    mamba activate nanometa_live_env
    ```

    You should now see the environment name in your command prompt.



### Option 2: Install with Singularity and Biocontainers

Nanometa Live can be operated using Singularity, a container platform ideal for environments where Docker is not available or preferred. This approach is suitable for users interested in leveraging Biocontainers for a ready-to-use Singularity container.

1. **Verify Singularity Installation:**

   Ensure Singularity is installed on your system. Verify its presence by running:

   ```bash
   singularity --version
   ```

   If Singularity is not installed, follow the installation guide on the [official Singularity website](https://sylabs.io/guides/3.0/user-guide/installation.html).

2. **Pull Nanometa Live Container:**

   Obtain the Nanometa Live container from Biocontainers with this command:

   ```bash
   singularity pull nanometa-live.sif docker://quay.io/biocontainers/nanometa-live:latest
   ```

   This command downloads the Singularity Image File (SIF) with Nanometa Live.

3. **Run Nanometa Live Using Singularity:**

   After downloading the container, start Nanometa Live with:

   ```bash
   singularity run nanometa-live.sif
   ```

   This will launch Nanometa Live within the Singularity container.

4. **Access Host System Data:**

   To use data from your host system inside the container, mount host directories using the `--bind` option:

   ```bash
   singularity run --bind /path/to/host/data:/data nanometa-live.sif
   ```

   Replace `/path/to/host/data` with your host system's data directory path.

5. **Explore Additional Commands:**

   For further customization and control in Singularity, refer to the [Singularity user guide](https://sylabs.io/guides/3.0/user-guide/).

With this setup, Nanometa Live can be efficiently run in a containerized environment, ensuring reproducibility and ease of use across various computational platforms.


Certainly! Here is an additional installation option for running Nanometa Live using Docker:


### Option 3: Install with Docker

Docker provides a convenient and consistent platform for running software in containers, making it an excellent choice for deploying Nanometa Live in a variety of environments.

1. **Install Docker:**

   If Docker is not already installed on your system, download and install it from the [official Docker website](https://www.docker.com/get-started). Follow the installation instructions for your specific operating system.

2. **Pull the Nanometa Live Docker Image:**

   Pull the official Nanometa Live image from Docker Hub using this command:

   ```bash
   docker pull nanometa/nanometa-live:latest
   ```

   This command downloads the latest version of the Nanometa Live Docker image.

3. **Run Nanometa Live in a Docker Container:**

   Start Nanometa Live within a Docker container using:

   ```bash
   docker run -p 8080:8080 nanometa/nanometa-live:latest
   ```

   The `-p` flag maps a port from your host machine to the container, allowing you to access the Nanometa Live GUI via a web browser.

4. **Access the Web Interface:**

   Open a web browser and navigate to `http://localhost:8080` to access the Nanometa Live GUI. This interface will be served from the Docker container.

5. **Data Volume Mounting (Optional):**

   If you wish to process data stored on your host machine, mount the data directory as a volume in the Docker container:

   ```bash
   docker run -p 8080:8080 -v /path/to/host/data:/data nanometa/nanometa-live:latest
   ```

   Replace `/path/to/host/data` with the path to your data directory. This step ensures that the Docker container has access to your local data.

6. **Additional Docker Commands:**

   For more advanced Docker usage, such as setting environment variables or running in detached mode, consult the [Docker documentation](https://docs.docker.com).

With Docker, you can rapidly deploy Nanometa Live across different systems with minimal setup, ensuring consistent performance and behavior regardless of the underlying host environment.


### Option 4: Install from Source Code

1. **Clone the Repository:**

    First, clone the Nanometa Live repository from GitHub to your local machine:

    ```bash
    git clone https://github.com/FOI-Bioinformatics/nanometa_live
    ```

2. **Navigate to the Project Directory:**

    Move to the directory where the cloned repository is located. The directory should contain a file named `nanometa_live_env.yml`.

3. **Create the Environment from the YML File:**

    Run the following command to create a new environment based on the `nanometa_live_env.yml` file:

    ```bash
    mamba env create -f nanometa_live_env.yml
    ```

4. **Activate the Environment:**

    Activate the newly created environment:

    ```bash
    mamba activate nanometa_live_env
    ```

5. **Install the Program:**

    While in the directory that contains the `setup.py` file, execute the following command to install the program:

    ```bash
    pip install .
    ```

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

- **Contact**: Kristoffer Sandås, [kristoffersandas@yahoo.se](mailto:kristoffersandas@yahoo.se)
- **Issues**: For bug reports, feature requests, or any other queries, please [open an issue](https://github.com/FOI-Bioinformatics/nanometa_live/issues).

Certainly! Below is a draft section about licensing that you can include in your README. It provides a brief explanation and directs the reader to the full license text.

---

## License

`Nanometa Live` is licensed under the GNU General Public License v3.0. This license grants you the freedom to use, modify, and distribute the software in both source and binary form, provided that you include the original copyright and license notice in any copy of the software or source code.

For the full license text, please refer to the [LICENSE](LICENSE.txt) file in the repository. This license was chosen to promote freedom in using the software and to ensure that derivative works are shared with the community.

---


