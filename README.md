# Nanometa Live
Nanometa Live is a workflow and graphical user interface (GUI) that displays real-time results from metagenomic sequencing with the Oxford Nanopore MinION and Flongle flow cells. The backend workflow uses Kraken2 for classification and BLAST for validation of sequences. The GUI consists of three tabs containing various plots.

<img src="https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/main%20pic2.png" alt="main view" width="900" height="500">

A Sankey plot displays the most abundant taxa in the sample and their lineage. The plot can be modified and filtered by domain, taxonomic levels and abundance. At the top of the app is a toggle to pause or resume live updates of the plots. When turned on, the plots are automatically updated with the latest results from the workflow on a set time interval.

<img src="https://github.com/FOI-Bioinformatics/nanometa_live/blob/main/pathogen%20pic.png" alt="pathogen table" width="400" height="390">

The user can select certain species of interest or pathogens that are displayed in a colored list along with a gauge to show abundance and potential threat level.
Included in the app are also sunburst and icicle charts in the Explore tab, basic quality control data in the QC tab, and a list of most abundant taxa.

For more information, see the [wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki).

## INSTALL
The program uses a conda environment, so conda or mamba will need to be installed for it to work. Mambaforge is recommended.

**Install with conda/mamba (recommended):**

Create a new conda environment, for example:

&emsp;&emsp;&emsp;&emsp;*$ mamba create --name nanometa_live_env*

Activate the environment:

&emsp;&emsp;&emsp;&emsp;*$ conda activate nanometa_live_env*

Install with conda or mamba, for example:

&emsp;&emsp;&emsp;&emsp;*$ mamba install nanometa-live*

**Install from source:**

&emsp;&emsp;**1.** Clone or download the files from GitHub, for example:

&emsp;&emsp;&emsp;&emsp;*$ git clone https://github.com/FOI-Bioinformatics/nanometa_live*

&emsp;&emsp;**2.** From the main folder, containing **nanometa_live_env.yml**, create a conda/mamba environment from the yml file, for example:

&emsp;&emsp;&emsp;&emsp;*$ mamba env create -f nanometa_live_env.yml*

&emsp;&emsp;**3.** Activate the environment:

&emsp;&emsp;&emsp;&emsp;*$ conda activate nanometa_live_env*

&emsp;&emsp;**4.** Install the program in the environment. While standing in the directory containing **setup.py**:

&emsp;&emsp;&emsp;&emsp;*$ pip install .*

The program is now installed and can be accessed from any directory using the instructions below.

## QUICK USE TUTORIAL
The tutorial files can be downloaded at https://drive.google.com/drive/folders/1fjAihcPw409Pw8C3z_YPQnBnRMuoDE4u?usp=sharing. We will use the built-in nanopore simulator to do a test run using a GTDB database for Kraken2.

#### 1. Make sure the environment is activated:
&emsp;&emsp;*$ conda activate nanometa_live_env*

#### 2. Create a new project
&emsp;&emsp;*$ nanometa-new --path /home/user/metagenomic_project*

#### 3. Modify the config file
Go into the newly created directory and open the config file.  

Change the **Nanopore output directory** */home/user/nanopore_out* to your user name (or other desired path).

Set the **Kraken 2 database** directory to wherever you put your database from the tutorial files, for example */home/user/kraken2.gtdb_bac120_4Gb*. Naturally you need to unpack it. 

Remember to save your config file after modification.

#### 4. Build BLAST databases for validation
The *nanometa-blastdb* command constructs the needed files for validating the sequences that Kraken 2 finds.

The example refseqs from the tutorial files should be placed in a directory, for example */home/user/example_refseqs*. This directory should contain the following files: "321.fasta", "852.fasta", "5061.fasta", "13373.fasta".

Standing in your project directory (*/home/user/metagenomic_project*), run the command with the example_refseqs directory in as input:

&emsp;&emsp;*$ nanometa-blastdb -i /home/user/example_refseqs*

The folder *blast_databases* should be created in your project directory, containing 8 database files for each ID, with different endings: "idnumber.fasta.xxx".

#### 5. Start Nanopore sequencing
For the tutorial, we will use the Nanopore simulator that comes with the program. Put the 8 tutorial test batch files, ending in fastq.gz, in a folder called */home/user/nanometa_test_data*, and from a separate terminal run:

&emsp;&emsp;*$ nanometa-sim -i /home/user/nanometa_test_data -o /home/user/nanopore_out*

The -o folder is the simulated Nanopore output, and needs to be the same as specified in the config under **Nanopore output directory**. The simulator automatically copies a file from the nanometa_test_data directory every 1-2 minutes until all the files are copied, to mimic the Nanopore batches. 

#### 6. Start the backend pipeline
Start a separate terminal, make sure you are in the project directory */home/user/metagenomic_project* and run:

&emsp;&emsp;*$ nanometa-pipe*

To exit the pipeline, press *ctrl+C*. Might have to be pressed several times.

#### 7. Start the GUI
Start a separate terminal, make sure you are in the project directory and run:

&emsp;&emsp;*$ nanometa*

Hold *ctrl* and click the port link if the GUI does not open by itself.

To exit the GUI, press *ctrl+C* in this terminal. The browser window can be closed as a regular window.

#### 8. Navigating the GUI

There are tooltips in the GUI for most of the settings. Hover over an object to display the tooltips. There are thorough descriptions of the plots in the [wiki](https://github.com/FOI-Bioinformatics/nanometa_live/wiki). 

The tutorial species of interest have been chosen to display all the possible abundance visualizations in the GUI. With the default settings, species with a read count higher than 10 will appear as yellow, and species with a read count higher than 100 will appear as red.

## Contact and community guidelines
Contact regarding Nanometa Live: Kristoffer, **kristoffersandas@yahoo.se**

For problems, comments or support, post an issue. 
