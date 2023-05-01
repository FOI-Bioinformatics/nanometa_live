"""
This scripts asks the user for a path to a folder containing the refseqs 
to be used for validating the species of interest.
It then creates BLAST databases in a specific folder for the pipeline to use.

The files in the input folder should be formatted as: "ID_name.fasta"
For example, for a species with ID nr 1381124, the corresponding file should
be named simply "1381124.fasta".
The file should contain the reference genome that the user has chosen for 
that species.
"""
import argparse
import os
import yaml

def build_blast():
    # Creates the object that contains the arguments passed to the shell command.
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input_folder', help="The folder where the reference fastas are stored. See readme for formats.")
    args = parser.parse_args()
    # Variables:
    input_folder = args.input_folder
    
    # only for constuction/debugging
    #input_folder = "example_refseqs"
    
    # load config variables
    with open('config.yaml', 'r') as cf:
        config_contents = yaml.safe_load(cf)
    
    # path to where the databases will be created
    database_path = os.path.join(config_contents["main_dir"], 'blast_databases')
    
    # create path
    if not os.path.exists(database_path): 
        os.mkdir(database_path)
    
    # list all the files/refseqs
    file_list = os.listdir(input_folder) 
    
    try:
        for file in file_list: # for each refseq
            file_path = os.path.join(input_folder, file)
            print('Current file:\n' + file_path)
            # name the corresponding database 
            database_name = os.path.join(database_path, file)
            # create system command string
            system_cmd = "makeblastdb -in " + file_path + " -dbtype nucl -out " + database_name
            # create a db for the refseq with BLAST
            os.system(system_cmd)
        print('Database built.\n')
    except: # in case something goes wrong
        print('\nSomething went wrong. Make sure that the specififed input directory contains the proper files:')
        print('A fasta file for each taxon ID, named "id_number.fasta" (for example "1381124.fasta"). This fasta should contain the reference genome you wish to use for this taxon.')

#build_blast()