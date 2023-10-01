import requests
import json
import pandas as pd
import logging
import argparse
import sys
import subprocess
import zipfile
import os
from ruamel.yaml import YAML
import shutil
from typing import List, Dict, Union, NoReturn

from nanometa_live.helpers.blast_utils import build_blast_databases, check_blast_dbs_exist
from nanometa_live.helpers.config_utils import update_yaml_config_with_taxid, load_config
from nanometa_live.helpers.data_utils import (
    read_species_from_config,
    fetch_species_data,
    filter_exact_match,
    filter_data_by_exact_match
)
from nanometa_live.helpers.file_utils import (write_accessions_to_file,
    process_local_files,
    read_and_process_gtdb_metadata,
    download_gtdb_metadata
    )
from nanometa_live.helpers.kraken_utils import run_kraken2_inspect, parse_kraken2_inspect
from nanometa_live.helpers.transform_utils import (
    update_results_with_taxid_dict,
    create_row_dict,
    parse_to_table_with_taxid,
    add_taxid_to_results
)
from nanometa_live.helpers.file_utils import (
    save_species_and_taxid_to_txt,
    download_genomes_from_ncbi,
    decompress_zip,
	rename_files,
    decompress_and_rename_zip,
    generate_inspect_filename
)

from nanometa_live import __version__

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



def main():
    # Command line arguments
    parser = argparse.ArgumentParser(description='Fetch and filter species data.')
    parser.add_argument('-x', '--prefix', default='parsed_species_data', help='Prefix for the output CSV file.')
    parser.add_argument('--config', default='config.yaml', help='Path to the configuration file. Default is config.yaml.')
    parser.add_argument('-p', '--path', default='', help="The path to the project directory.")
    parser.add_argument('--mode', default='gtdb-api', choices=['gtdb-api', 'gtdb-file', 'local-species', 'local-taxid'],
                        help="The mode of operation handling genome files. Can be 'gtdb-api', 'gtdb-file', 'local-species', or 'local-taxid'. Default is 'gtdb-api'.")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}',
                        help="Show the current version of the script.")
    args = parser.parse_args()

    #if args.mode in ['gtdb-file']:
    #    logging.error(f"The selected mode '{args.mode}' is not implemented yet.")
    #    sys.exit(1)  # Exit if the mode is not implemented

    # Determine the full path of the configuration file. If a path argument is provided, join it with the config filename.
    config_file_path = os.path.join(args.path, args.config) if args.path else args.config

    # Load the configuration file into a dictionary.
    config_contents = load_config(config_file_path)

    # Read the list of species from the configuration file.
    species_list = read_species_from_config(config_contents)

    # Exit the script if no species are found in the configuration file.
    if not species_list:
        logging.error("No species found in the input file.")
        sys.exit(1)  # Exit if no species are found

    # Retrieve the taxonomy database used by Kraken2 from the configuration file.
    kraken_taxonomy = config_contents["kraken_taxonomy"]

    # Retrieve the Kraken2 database path from the configuration file.
    kraken_db = config_contents["kraken_db"]

    # Prepare the folder where data files will be stored.
    data_files_folder = os.path.join(args.path, 'data-files')
    if not os.path.exists(data_files_folder):
        os.makedirs(data_files_folder)

##############################################################################################################
    # SECTION: Extract taxid from kraken2 database.

    # Run Kraken2's inspect command to generate a file that contains species to taxid mapping.
    inspect_file_name = os.path.join(data_files_folder, generate_inspect_filename(kraken_db))
    success = run_kraken2_inspect(kraken_db, inspect_file_name)

    # Parse the generated file from Kraken2's inspect command to get a dictionary mapping species to tax IDs.
    species_taxid_dict = parse_kraken2_inspect(inspect_file_name, species_list)


##############################################################################################################
    # SECTION: Fetch species data from GTDB.

    if args.mode in ['gtdb-api']:
        # Initialize an empty dictionary to store results.
        results = {}

        # Loop through the list of species and fetch their data from GTDB.
        for species in species_list:
            # Prepare the query string for GTDB.
            search_query = f"s__{species}"
            # Fetch data for the current species from GTDB.
            species_data = fetch_species_data(search_query, kraken_taxonomy)
            # If data is found for the species, add it to the results dictionary.
            if species_data:
                results[species] = {'rows': species_data}

        # Update the results dictionary to include tax IDs using the mapping from species to tax IDs.
        results = update_results_with_taxid_dict(results, species_taxid_dict)

        # Filter the results to include only exact matches and convert it to a DataFrame.
        filtered_results = filter_data_by_exact_match(results, kraken_taxonomy)
        df = parse_to_table_with_taxid(filtered_results)

        # Create a dictionary that maps species names to tax IDs, based on the DataFrame (only species in config).
        #species_to_taxid = dict(zip(df['Species'], df['Tax_ID']))

        # Save the species and their corresponding tax IDs to a text file.
        save_species_and_taxid_to_txt(df, data_files_folder)

        # Update the YAML config file with the species and tax IDs.
        update_yaml_config_with_taxid(df, config_file_path)

        # Save the DataFrame to a CSV file.
        output_file =  os.path.join(data_files_folder, f"{args.prefix}_{kraken_taxonomy}.csv")
        logging.info(f"Parsed data saved to {output_file}")
        df.to_csv(output_file, index=False)

        # Extract the Genome IDs (GID) from the DataFrame and store them in a list.
        accessions_to_download = df['GID'].tolist()
        logging.info(f"Extracted assembly accessions for download: {accessions_to_download}")

    elif args.mode == 'gtdb-file':
        # Prepare the folder where data files will be stored.
        data_files_folder = os.path.join(args.path, 'data-files')
        metadata_folder = os.path.join(data_files_folder, 'metadata')

        if not os.path.exists(metadata_folder):
            os.makedirs(metadata_folder)
            logging.info(f"Created metadata directory at {metadata_folder}.")

        gtdb_metadata_file = os.path.join(metadata_folder, 'bac120_metadata.tsv.gz')

        # Download the file if it doesn't exist
        if not os.path.exists(gtdb_metadata_file):
            logging.info("GTDB metadata file not found. Downloading now.")
            download_gtdb_metadata(metadata_folder)

        # Read and process the GTDB metadata
        filtered_results = read_and_process_gtdb_metadata(gtdb_metadata_file, kraken_taxonomy, species_list)
        df = add_taxid_to_results(filtered_results, species_taxid_dict)

        # Save the species and their corresponding tax IDs to a text file.
        save_species_and_taxid_to_txt(df, data_files_folder)

        # Update the YAML config file with the species and tax IDs.
        update_yaml_config_with_taxid(df, config_file_path)

        # Save the DataFrame to a CSV file.
        output_file =  os.path.join(data_files_folder, f"{args.prefix}_{kraken_taxonomy}.csv")
        logging.info(f"Parsed data saved to {output_file}")
        df.to_csv(output_file, index=False)

        # Extract the Genome IDs (GID) from the DataFrame and store them in a list.
        accessions_to_download = df['GID'].tolist()
        logging.info(f"Extracted assembly accessions for download: {accessions_to_download}")




    elif args.mode == 'local-species':
        # Process local species fasta files
        indata_folder = os.path.join(args.path, 'indata')
        success = process_local_files(indata_folder, args.path, species_taxid_dict, id_type='species')
        if not success:
            logging.error("Failed to process local species files.")
            sys.exit(1)
    elif args.mode == 'local-taxid':
        # Process local taxid fasta files
        indata_folder = os.path.join(args.path, 'indata')
        success = process_local_files(indata_folder, args.path, species_taxid_dict, id_type='taxid')
        if not success:
            logging.error("Failed to process local taxid files.")
            sys.exit(1)


##############################################################################################################
    # SECTION: Download genomes from NCBI using accession numbers.
    if args.mode in ['gtdb-api', 'gtdb-file']:
        # Write the list of Genome IDs to a text file for later use in downloading.
        accession_file = os.path.join(data_files_folder, f"{args.prefix}_{kraken_taxonomy}_accessions.txt")
        write_accessions_to_file(accessions_to_download, accession_file)

        # Download genomes from NCBI based on the list of Genome IDs.
        download_genomes_from_ncbi(data_files_folder, args.prefix, f"{args.prefix}_{kraken_taxonomy}_accessions.txt")

        # Decompress the downloaded ZIP file and rename the genomes.
        decompress_and_rename_zip( f"{args.prefix}_ncbi_download.zip", df, data_files_folder)

##############################################################################################################
    # SECTION: Build BLAST databases.

    # Check for any missing BLAST databases based on the tax IDs.
    missing_dbs = check_blast_dbs_exist(species_taxid_dict, data_files_folder)

    # Build BLAST databases, but only for the missing ones.
    build_blast_databases(data_files_folder, missing_databases=missing_dbs)




if __name__ == '__main__':
    main()
