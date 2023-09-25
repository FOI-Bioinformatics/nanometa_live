# Nanometa Live: Real-time Metagenomic Analysis

Nanometa Live is a comprehensive workflow equipped with a graphical user interface (GUI) for real-time metagenomic sequencing analysis. It's designed for the Oxford Nanopore MinION and Flongle flow cells. Utilizing Kraken2 for classification and BLAST for sequence validation, it offers a dynamic, offline-capable solution with custom database support.


<img src="https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/main%20pic2.png" alt="main view" width="900" height="500">

## Features

- 📊 **Real-time Visualization**: Dynamic Sankey plots, sunburst charts, and more.
- 🌐 **Offline Support**: Operate without internet connectivity.
- 🛠️ **Custom Database Support**: Tailor the tool to your specific needs.
- 🔍 **Quality Control**: Inbuilt QC tab for basic data quality checks.
  
For further details, visit our [Wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki).


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

### Option 2: Install from Source Code

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

Once the program is installed, you can access it from any directory by following the usage instructions below.

## Quick Start Tutorial

This guide will walk you through a simulated analysis using a GTDB database for Kraken2. To get started, download the required tutorial files from [Google Drive](https://drive.google.com/drive/folders/1fjAihcPw409Pw8C3z_YPQnBnRMuoDE4u?usp=sharing).



### Step 1: Activate the Conda Environment
Ensure your Conda/Mamba environment is active by running:

```bash
mamba activate nanometa_live_env
```

### Step 2: Initialize a New Project
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


### Step 3: Optional Configuration
Navigate to your newly created project directory and open the `config.yaml` file.

- Verify the **Nanopore Output Directory**.
- Verify the **Kraken 2 Database** directory.

📝 **Note**: Save your changes.


### Step 4: Automatic Data Preparation
Execute the `nanometa-prepare` command to automatically download and create files needed for analysis.

```bash
nanometa-prepare --path ${working_dir} 
```

### Step 5: Simulate Nanopore Sequencing
Place the tutorial batch files (ending in `.fastq.gz`) in a directory, e.g., `/home/user/nanometa_test_data`. Then run:

```bash
nanometa-sim -i /SOMEPATH/nanometa_test_data -o  ${fastq_folder}
```

Ensure the `-o` flag's value matches the **Nanopore Output Directory** in your `config.yaml` file.


### Step 6: Start Live Analysis
Execute the following command in another terminal to begin live analysis:

```bash
nanometa-live -p ${working_dir}
```

To terminate the process, press `Ctrl+C` multiple times if needed.

### Step 7: Explore the GUI
- Tooltips: Hover over GUI elements to view helpful tooltips.
- Wiki: For detailed descriptions, visit the [project wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki).
- Visual cues: In the GUI, species with a read count >100 will appear in red.



## Contact and community guidelines
Contact regarding Nanometa Live: Kristoffer, **kristoffersandas@yahoo.se**

For problems, comments or support, post an issue.  
