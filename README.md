# Nanometa Live

Version beta 0.0.1

## INTRODUCTION

Nanometa Live is a tool for performing real-time analysis of metagenomic samples sequenced with an Oxford Nanopore. The program consists of a  backend pipeline that processes the files and a frontend graphical user interface (GUI) that displays the data. The analysis can commence as soon as the Nanopore basecaller starts producing batch files, and there is no need to wait for the sequencing to finish. The GUI displays an overview of the total species composition of the sample, as well as the prescence/abundance of a set of pre-defined species (pathogens), which are determined by the user. Both the backend and the GUI updates at user-set intervals, allowing data to be displayed in real-time as it is produced by the Nanopore. 

This is a prototype of the program, meaning there are some limitations in functionality and user-friendliness, but the data displayed should be fully reliable. The program was created and tested on Ubuntu 22.04.2 LTS, but should run on any Linux distro and probably on Mac as well.

#### Backend - file processing pipeline

The backend consists of a snakemake workflow that processes the batch files produced by the Nanopore. The fastq.gz files are filtered with fastP, before classifiaction using Kraken 2. Quality control (QC) data is acquired from the Nanopore batch files in the form of the timestamp of the file, and the number of reads and base pairs in the batch. The sequences belonging to the user-defined species of interest are collected using KrakenTools, and BLASTed against reference genomes for validation.

#### Frontend - graphical user interface

The GUI is a Dash app which runs on any standard web-browser. It refreshes all displayed data on a specific time interval, using the files produced by the backend workflow. It is run separately from the backend and the live updating can be paused at any time, to allow for exploration of the graphs. When the updates are turned on again, the app refreshes with any new data that has been produced. Further explanations can be found in the section GUI below.

### Commands 

The program includes five terminal commands, summarized below. Instructions on how to use them found in the USE section.

**nanometa-new** 

Creates a new project in the user specified path, and a config file for the project. MUST BE AN ABSOLUTE PATH!

&emsp;&emsp;*-p*,&emsp;&emsp;*--path*,&emsp;&emsp;The name of the new project directory.

&emsp;&emsp;&emsp;&emsp;*$ nanometa-new --path /home/path/to/project*

**nanometa-blastdb** 

Builds the BLAST databases used for validation. Specifications on files that should be in the input folder are found in the USE section below.

&emsp;&emsp;*-i*,&emsp;&emsp;*--input_folder*,&emsp;&emsp;The directory containing the refseqs for validation.

&emsp;&emsp;&emsp;&emsp;*$ nanometa-blastdb --input_folder /home/path/to/refseqs*

**nanometa-pipe** 

&emsp;&emsp;Runs the backend. User needs to be in the folder containing the config file for the project.

**nanometa** 

&emsp;&emsp;Runs the GUI. User needs to be in the folder containing the config file for the project.

**nanometa-sim** 

A nanpopore simulator that can be used to test the program. It mimics the Nanopore batch files output by copying fastq.gz test files into a simulated output folder on a set time interval.

&emsp;&emsp;*-i*,&emsp;&emsp;*--input_folder*,&emsp;&emsp;The directory containing test data.

&emsp;&emsp;*-o*,&emsp;&emsp;*--output_folder*,&emsp;&emsp;The simulated nanopore output directory.

&emsp;&emsp;&emsp;&emsp;&emsp;*--min_delay*,&emsp;&emsp;The lower limit to the interval (in minutes). Can be a float. Default = 1.

&emsp;&emsp;&emsp;&emsp;&emsp;*--max_delay*,&emsp;&emsp;The upper limit to the interval (in minutes). Can be a float. Default = 2.

&emsp;&emsp;&emsp;&emsp;*$ nanometa-sim -i /home/path/to/test/files -o /home/path/to/simulated/nanopore/output --min_delay 1 --max_delay 2*

## INSTALL

The program uses a conda environment, so conda or mamba will need to be installed for it to work. Mambaforge is recommended.

To install the program, follow these instructions (Linux).

&emsp;&emsp;**1.** Clone or download the files from GitHub, for example:

&emsp;&emsp;&emsp;&emsp;*$ git clone https://github.com/KristofferSandas/nanometa_live*

&emsp;&emsp;**2.** From the main folder, containing **nanometa_live_env.yml**, create a conda/mamba environment from the yml file, for example:

&emsp;&emsp;&emsp;&emsp;*$ mamba env create -f nanometa_live_env.yml*

&emsp;&emsp;**3.** Activate the environment:

&emsp;&emsp;&emsp;&emsp;*$ conda activate nanometa_live_env*

&emsp;&emsp;**4.** Install the program in the environment. While standing in the directory containing **setup.py**:

&emsp;&emsp;&emsp;&emsp;*$ pip install .*

The program is now installed and can be accessed from any directory using the commands listed below.

## USE

**Tutorial**

To get familiar with the program, there is a tutorial included in these instructions. If you wish to follow along with the tutorial, the files needed can be downloaded at https://www.mediafire.com/folder/ndg9150i2070n/nanometa_tutorial_files. The sections are divided into general instructions followed by a tutorial part. If you're not following the tutorial, you can skip these parts.

To use the program, follow these steps:

### 1. Make sure the environment is activated:

&emsp;&emsp;*$ conda activate nanometa_live_env*

### 2. Create a new project

Use the *nanometa-new* command to create the directory for your new project. THIS MUST BE AN ABSOLUTE PATH or the later functions will not find the directory. In this directory, a config file will be created where you can specify the parameters for your project.

**Tutorial:**

&emsp;&emsp;*$ nanometa-new --path /home/user/metagenomic_project*

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

Change the **Nanopore output directory** */home/user/nanopore_out* to your user name (or other desired path).

Set the **Kraken 2 database** directory to wherever you put your database from the tutorial files, for example */home/user/kraken2.gtdb_bac120_4Gb*. Naturally you need to unpack it. 

### 4. Build BLAST databases for validation

The *nanometa-blastdb* command constructs the needed files for validating the sequences that Kraken 2 finds. It requires the genome refseq files corresponding to the species of interest to be located in a specific directory, and to be named according to the IDs of the species: for example, a species with ID 321 needs to have a refseq file named "321.fasta" in the designated refseq directory. The user can download the desired refseqs from NCBI, GTDB or any other source, but it needs to be a standard nucleotide fasta file. Standing in the project direcory containing the config file, run *nanometa-blastdb -i /home/absoulte/path/to/refseq/directory* and the program will create the database from the refseqs. See tutorial below for an example.

If you wish to disable the validation, simply change the config file value for **Blast validation** to *False* and you can skip this step.

**Tutorial:**

The example refseqs from the tutorial files should be placed in a directory, for example */home/user/example_refseqs*. This directory should contain the following files: "321.fasta", "852.fasta", "5061.fasta", "13373.fasta", corresponding to the IDs listed in the config file.

Standing in your project directory (*/home/user/metagenomic_project*), run the command with the example_refseqs directory in as input:

&emsp;&emsp;*$ nanometa-blastdb -i /home/user/example_refseqs*

The folder *blast_databases* should be created in your project directory, containing 8 database files for each ID, with different endings: "idnumber.fasta.xxx".

### 5. Start Nanopore sequencing

Now the preparation is done and you can start the Nanopore sequencing. Alternatively, the backend and GUI can be started before the sequencing and will then simply wait until the sequencer starts producing files. Just make sure your specified **Nanopore output directory** is the directory in which the Nanopore produces its files.

**Tutorial:**

For the tutorial, we will use the Nanopore simulator that comes with the program. Put the 8 tutorial test batch files, ending in fastq.gz, in a folder called */home/user/nanometa_test_data*, and from a separate terminal run:

&emsp;&emsp;*$ nanometa-sim -i /home/user/nanometa_test_data -o /home/user/nanopore_out*

The -o folder is the simulated Nanopore output, and needs to be the same as specified in the config under **Nanopore output directory**. The simulator automatically copies a file from the nanometa_test_data directory every 1-2 minutes until all the files are copied, to mimic the Nanopore batches. You can change this interval with the arguments *--min_delay x* and *--max_delay y*, where x and y are minutes. You can specify the minutes as floats (0.1 for example) if you wish to speed up the simulation. 

### 6. Start the backend

Standing in your project folder, run the *nanometa-pipe* command in a separate terminal to start the backend pipeline. This can be done before the sequencing starts as well, and the workflow will simply wait until there are files in the designated nanopore output directory. When running the workflow for the first time, the required programs will be installed so it might take a while before the processing starts. To exit the pipeline, press *ctrl+C*. It may need to be pressed repeatedly, since the first time will exit any ongoing snakmake run and the second one will exit the python script that controls it.

**Tutorial:**

Start a separate terminal, make sure you are in the project directory */home/user/metagenomic_project* and run:

&emsp;&emsp;*$ nanometa-pipe*

### 7. Start the GUI

Standing in your project folder, run *nanometa* in a separate terminal to start the GUI. You might need to hold *ctrl* and press the port link that is displayed. This can be done before the sequencing and pipeline are started as well, then the GUI will simply display empty plots until data is produced. To exit the GUI, press *ctrl+C* in this terminal. The browser window can be closed as a regular window.

**Tutorial:**

Start a separate terminal, make sure you are in the project directory and run:

&emsp;&emsp;*$ nanometa*

Hold *ctrl* and click the port link if the GUI does not open by itself.

## NCBI/GTDB IDs

The taxonomy IDs for the species of interest specified in the config file need to correspond to the IDs in your Kraken 2 database and to the names of the refseq files if you are performing validation. 

### Using NCBI

If you use a standard Kraken 2 database, or a slimmed down version as can be found for example on https://benlangmead.github.io/aws-indexes/k2, it will contain the NCBI IDs. You can then simply use the NCBI webpage or API to find the IDs for the species you wish to specify. You can also find the corresponding refseqs at NCBI and simply rename them as "tax_id.fasta" (for example the ID 321 will need a refseq file called "321.fasta") and put them in a specific folder for the *nanometa-blastdb* command. 

### Using GTDB

If you are using a GTDB database, such as the example database in the tutorial files, you need to find your species at GTDB and then search for the name in the inspect.txt file in your database to find the ID. The IDs are randomly assigned and will not correspond to anything in either GTDB or NCBI. You can find the accession for the refseq for your species at GTDB, and rename the genome file using the ID from in your GTDB database for the validation refseqs (for example the ID 321 will need a refseq file called "321.fasta").

## CONFIG

Explanations of the settings in the config file.

**PROJECT NAME**

This is the main headline that will always be shown at the top of the interface. It can be set to whatever you want.

**SPECIES OF INTEREST**

This is a list of species IDs that the program will look for specifically. For more information on the IDs, see NCBI/GTDB IDs section above and step 4 in the USE section. The GUI will display these species in a separate table, colored to give a quick overview of the abundande in the sample, i.e. the number of reads belonging to that species identified by Kraken2. There is also a simple gauge meter that shows the overall pathogenicity in the sample using the same coloring sceme: yellow for warning and red for danger. There is no theoretical limit to how many species can be added to this list, and the only problem might be the aestethics of the GUI. The reads associated with each species will be filtered out and BLASTed agaist the chosen reference genomes, and the results of this validation can be shown in the GUI with a simple checkbox option.

**WARNING LIMITS**

Any species of interest with a number of reads above the warning_lower_limit will show up as yellow in the table and also cause the gauge to hit yellow. Species with a number of reads above the danger_lower_limit will show up as red and cause the gauge to hit red. These limits can be changed freely, but since the gauge displays the 10-logarithms of the read numbers, it may look strange if these numbers are modified.

**TAXONOMY LEVELS**

This is a python-formatted list of the taxonomy levels you wish to include in your analysis. It can be modified to include or exclude certain levels, or to add more precision in the form of sub-levels: G1, G2, S1, S2, S3 etc. If levels are added at the low end, S1, S2 and so on, when these levels are not included in the database used (as in the tutorial database), there will be empty nodes filling out the sankey plot in the GUI, decreasing readablity. This can be mitigated with the default_hierarchy_letters, which determines which levels will be displayed by default upon start of the GUI. These letters can be changed in the GUI as well. The taxonomic_hierarchy_letters parameter determines which levels the user can chose from in the GUI visualizations, while the default_hierarchy_letters simply determine which levels will be selected upon start. The default_reads_per_level also just determines the start value of this parameter, it can be changed in the GUI to any value. 

**GUI UPDATE FREQUENCY**

This is the number of seconds between updates of the GUI. It can be set to anything the user wants. Making it too short is usually unecessary, depending on the speed at which the nanopore produces batch files and the speed at which the backend processes these files. All zooming of plots in the GUI is reset upon every update, but the live updates can be paused at any time to explore the plots.

**GUI PORT**

The program is designed to be able to run without an internet connection. The default port is therefore set to 8050, which means the GUI will run locally on a web-browser. This port can presumably be used to host the program online or on a local network, although this has not been tested. 

**NANOPORE OUTPUT DIRECTORY**

This is the absolute path to the Nanopore output directory, where the batch fastq.gz files are produced. This is the main directory that Nanometa Live uses as input.

**REMOVE TEMP FILES**

By default, the pipeline removes all temporary files when exited. If you wish to keep these files for debugging or other purposes, change this to "no".

**WORKFLOW FREQUENCY**

The number of seconds between workflow updates. Every x seconds, the pipeline checks the nanopore output folder to see if there are any new files. If there are, it runs the workflow and processes the files for the GUI to use. This can be set to anything, but should optimally be balanced between how often the nanopore produces new files and how long the workflow takes to run, depending on the computer.

**CORES**

The number of cores assigned to the snakemake workflow and to the most demanding steps in the flow. The more cores assigned to a process, the faster it is, but the more computer resources it will consume. If you have a lot of power, assign these cores as high as you want. If not, see what your computer can handle. The program was created and tested on a 8GB RAM, Intel i7 laptop, where 3 cores assigned to all of these was the optmal balance.

**KRAKEN 2 DATABASE**

The ablolute path to the Kraken 2 database used for the analysis. More info on databases and IDs in the NCBI/GTDB IDs section above.

**KRAKEN 2 HIGH RAM REQUIREMENTS**

Kraken 2 by default loads the entire database into RAM to speed up the process. This means that a 8GB database needs 8GB of RAM to run. With larger databases this becomes a problem for standard computers and laptops. This functionality can be turned off with the --memory-mapping argument, loading the database in chunks, making the analysis slower but less resource-demanding. This high RAM requirement is turned off by default, but can be turned back on if you are using a powerful computer (or a very small database).

**BLAST VALIDATION**

Turn the validation on or off. More on validation in step 4 in the RUN section and in the NCBI/GTDB IDs section. If you set this to FALSE there is no need to do the BLAST database step and no need for refseqs. The pipeline will simply skip these steps

**BLAST CUTOFFS**

Here you can change the requirements for the sequences to be validated. Each sequence associated with a species of interest is BLASTed against its refseq and only the sequences with these set parameters of minimum percent identity and e-value are considered validated as belonging to the species. This is done since Kraken 2 finds notoriously many false positives.

**PROJECT MAIN DIRECTORY**

This is the directory created by the *nanometa-new* command. It is automatically added upon creating a new project. This should not be changed as the project will then not find the proper files. This needs to be an absolute path, so if the program behaves strangely, you can always check that this is an ablsolute path.

## GUI








