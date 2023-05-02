# Nanometa Live

Version beta 0.0.1

## INTRODUCTION

Nanometa Live is a tool for performing real-time analysis of metagenomic samples sequenced with an Oxford Nanopore. The program consists of a  backend pipeline that processes the files and a frontend graphical user interface (GUI) that displays the data. The analysis can commence as soon as the Nanopore basecaller starts producing batch files, and there is no need to wait for the sequencing to finish. The GUI displays an overview of the total species composition of the sample, as well as the prescence/abundance of a set of pre-defined species (pathogens), which are determined by the user. Both the backend and the GUI updates at user-set intervals, allowing data to be displayed in real-time as it is produced by the Nanopore. 

This is a prototype of the program, meaning there are some limitations in functionality and user-friendliness, but the data displayed should be fully reliable. The program was created and tested on Ubuntu 22.04.2 LTS, but should run on any Linux distro and probably on Mac as well.

#### Backend - file processing pipeline

The backend consists of a snakemake workflow that processes the batch files produced by the Nanopore. The fastq.gz files are filtered with fastP, before classifiaction using Kraken 2. Quality control (QC) data is acquired from the Nanopore batch files in the form of the timestamp of the file, and the number of reads and base pairs in the batch. The sequences belonging to the user-defined species of interest are collected using KrakenTools, and BLASTed against reference genomes for validation.

#### Frontend - graphical user inter

The GUI is a Dash app which runs on any standard web-browser. It refreshes all displayed data on a specific time interval, using the files produced by the backend workflow. It is run separately from the backend and the live updating can be paused at any time, to allow for exploration of the graphs. When the updates are turned on again, the app refreshes with any new data that has been produced.

### Commands 

The program includes five terminal commands, which are described in greated detail under the USE section. This is a brief summary:

**nanometa-new** 

&emsp;&emsp;- creates a new project in the user specified path, and a config file for the project. MUST BE AN ABSOLUTE PATH!

&emsp;&emsp;*nanometa-new --path /home/path/to/project*

**nanometa-blastdb** 

&emsp;&emsp;- builds the BLAST databases used for validation. Specifications on files in the input folder are found below.

&emsp;&emsp;*nanometa-blastdb --input_folder /home/path/to/refseqs*

**nanometa-pipe** 

&emsp;&emsp;- runs the backend. User needs to be in the folder containing the config file for the project.

**nanometa** 

&emsp;&emsp;- runs the GUI. User needs to be in the folder containing the config file for the project.

**nanometa-sim** 

&emsp;&emsp;- a nanpopore simulator that can be used to test the program. Copies test files into a simulated output folder on a set time interval.

&emsp;&emsp;*nanometa-sim --input_folder /home/path/to/test/files --output_folder /home/path/to/simulated/nanopore/output*

## INSTALL

The program uses a conda environment, so conda or mamba will need to be installed for it to work. Mambaforge is recommended.

To install the program, follow these instructions (Linux).

&emsp;&emsp;**1.** Clone or download the files from GitHub, for example:

&emsp;&emsp;&emsp;&emsp;*git clone https://github.com/KristofferSandas/nanometa_live*

&emsp;&emsp;**2.** From the main folder, containing **nanometa_live_env.yml**, create a conda/mamba environment from the yml file, for example:

&emsp;&emsp;&emsp;&emsp;*mamba env create -f nanometa_live_env.yml*

&emsp;&emsp;**3.** Activate the environment:

&emsp;&emsp;&emsp;&emsp;*conda activate nanometa_live_env*

&emsp;&emsp;**4.** Install the program in the environment. While standing in the directory containing **setup.py**:

&emsp;&emsp;&emsp;&emsp;*pip install .*

The program is now installed and can be accessed from any directory using the commands listed below.

## USE

**Tutorial**

To get familiar with the program, there is a tutorial included in these instructions. If you wish to follow along with the tutorial, the files needed can be downloaded at https://www.mediafire.com/folder/ndg9150i2070n/nanometa_tutorial_files. The sections are divided into general instructions followed by a tutorial part. If you're not following the tutorial, you can skip these parts.

To use the program, follow these steps:

### 1. Make sure the environment is activated:

&emsp;&emsp;*conda activate nanometa_live_env*

### 2. Create a new project

Use the *nanometa-new* command to create the directory for your new project. THIS MUST BE AN ABSOLUTE PATH or the later functions will not find the directory. In this directory, a config file will be created where you can specify the parameters for your project.

**Tutorial:**

&emsp;&emsp;*nanometa-new --path /home/bioinf/metagenomic_project*

### 3. Modify the config file

Go into the newly created directory and open the config file. A thorough explanation of all the parameters in the config file can be found in the CONFIG section below. The essential aspects are:

&emsp;&emsp;**Species of interest**: a list of the NCBI (or GTDB) IDs of the species of interest for the analysis. 

&emsp;&emsp;**Nanopore output directory**: the absolute path to the directory where the Nanopore produces its fastq.gz batch files.

&emsp;&emsp;**Kraken 2 database**: the absolute path to the Kraken 2 database used in the analysis.

Remember to save your config file after modification.

More info on how to use the IDs found below in the section NCBI/GTDB IDs.

**Tutorial:** 

For the tutorial, we will use the nanopore simulator to do a test run using a GTDB database for Kraken 2. 

Let the **species of interest** IDs be as they are. These IDs have been chosen to display all the possible abundance visualizations in the GUI:

&emsp;**ID 5061** - *Clostridium_H novyi* - **0 reads** in test data - corresponding NCBI taxID: 386415 - refseq accession: GCF_000014125.1

&emsp;**ID 13373** - *Faecalibacterium prausnitzii_M* - **3 reads** in test data - corresponding NCBI taxID: 853 - refseq accession: GCF_000154385.1

&emsp;**ID 852** - *Bacteroides fragilis_A* - **48 reads** in test data - corresponding NCBI taxID: 817 - refseq accession: GCF_002849695.1

&emsp;**ID 321** - *Bifidobacterium adolescentis* - **552 reads** in test data - corresponding NCBI taxID: 367928 - refseq accession: GCF_000010425.1

Leave the **Nanopore output directory** to */home/bioinf/nanopore_out*

Set the **Kraken 2 database** directory to wherever you put your database from the tutorial files, for example */home/bioinf/kraken2.gtdb_bac120_4Gb* 

### 4. Build BLAST databases for validation

The *nanometa-blastdb* command constructs the needed files for validating the sequences that Kraken 2 finds. It requires the genome refseq files corresponding to the species of interest to be located in a specific directory, and to be named according to the IDs of the species: for example, a species with ID 321 needs to have a refseq file named "321.fasta" in the designated refseq directory. The user can download the desired refseqs from NCBI, GTDB or any other source, but it needs to be a standard nucleotide fasta file. Standing in the project direcory containing the config file, run *nanometa-blastdb -i /home/absoulte/path/to/refseq/directory* and the program will create the database from the refseqs. See tutorial below for an example.

If you wish to disable the validation, simply change the config file value for **Blast validation** to *False* and you can skip this step.

**Tutorial:**

The example refseqs from the tutorial files should be placed in a directory, for example */home/bioinf/example_refseqs*. This directory should contain the following files: "321.fasta", "852.fasta", "5061.fasta", "13373.fasta", corresponding to the IDs listed in the config file.

Standing in your project directory (*/home/bioinf/metagenomic_project*), run the command with the example_refseqs directory in as input:

&emsp;&emsp;*nanometa-blastdb -i /home/bioinf/example_refseqs*

The folder *blast_databases* should be created in your project directory, containing 8 database files for each ID, with different endings: "idnumber.fasta.xxx".

### 5. Start Nanopore sequencing

Now the preparation is done and you can start the Nanopore sequencing. Alternatively, the backend and GUI can be started before the sequencing and will then simply wait until the sequencer starts producing files. Just make sure your specified **Nanopore output directory** is the directory in which the Nanopore produces its files.

**Tutorial:**

For the tutorial, we will use the Nanopore simulator that comes with the program. Put the test batch files, ending in fastq.gz in a folder called */home/bioinf/nanometa_test_data*, and from a separate terminal run:

&emsp;&emsp;*nanometa-sim -i /home/bioinf/nanometa_test_data -o /home/bioinf/nanopore_out*

The -o folder is the simulated Nanopore output, and needs to be the same as specified in the config under **Nanopore output directory**. The simulator automatically copies a file from the nanometa_test_data directory every 1-2 minutes until all the files are copied, to mimic the Nanopore batches. You can change this interval with the arguments *--min_delay x* and *--max_delay y*, where x and y are minutes. You can specify the minutes as floats (0.1 for example) if you wish to speed up the simulation. 

### 6. Start the backend

Standing in your project folder, run the *nanometa-pipe* command in a separate terminal to start the backend pipeline. This can be done before the sequencing starts as well, and the workflow will simply wait until there are files in the designated nanopore output directory. When running the workflow for the first time, the required programs will be installed so it might take a while before the processing starts. To exit the pipeline, press *ctrl+C*. It may need to be pressed repeatedly, since the first time will exit any ongoing snakmake run and the second one will exit the python script that controls it.

**Tutorial:**

Start a separate terminal, make sure you are in the project directory */home/bioinf/metagenomic_project* and run:

&emsp;&emsp;*nanometa-pipe*

### 7. Start the GUI

Standing in your project folder, run *nanometa* in a separate terminal to start the GUI. You might need to hold *ctrl* and press the port link that is displayed. This can be done before the sequencing and pipeline are started as well, then the GUI will simply display empty plots until data is produced. To exit the GUI, press *ctrl+C* in this terminal. The browser window can be closed as a regular window.

**Tutorial:**

Start a separate terminal, make sure you are in the project directory and run:

&emsp;&emsp;*nanometa*

Hold *ctrl* and click the port link if the GUI does not open by itself.

## NCBI/GTDB IDs



## CONFIG


## GUI








