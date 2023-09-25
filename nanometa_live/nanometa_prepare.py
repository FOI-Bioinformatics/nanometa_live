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

from nanometa_live.helpers.blast_utils import build_blast_databases
from nanometa_live.helpers.config_utils import update_yaml_config_with_taxid, load_config
from nanometa_live.helpers.data_utils import (
    read_species_from_config,
    fetch_species_data,
    filter_exact_match,
    filter_data_by_exact_match
)
from nanometa_live.helpers.file_utils import write_accessions_to_file
from nanometa_live.helpers.kraken_utils import run_kraken2_inspect, parse_kraken2_inspect
from nanometa_live.helpers.transform_utils import (
    update_results_with_taxid_dict,
    create_row_dict,
    parse_to_table_with_taxid
)
from nanometa_live.helpers.file_utils import (
    save_species_and_taxid_to_txt,
    download_genomes_from_ncbi,
    decompress_zip,
	rename_files,
    decompress_and_rename_zip,
    generate_inspect_filename
)

__version__="0.2.1"


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



def main():
    # Command line arguments
    parser = argparse.ArgumentParser(description='Fetch and filter species data.')
    parser.add_argument('-x', '--prefix', default='parsed_species_data', help='Prefix for the output CSV file.')
    parser.add_argument('--config', default='config.yaml', help='Path to the configuration file. Default is config.yaml.')
    parser.add_argument('-p', '--path', default='', help="The path to the project directory.")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}',
                        help="Show the current version of the script.")
    args = parser.parse_args()

    config_file_path = os.path.join(args.path, args.config) if args.path else args.config
    config_contents = load_config(config_file_path)

    species_list = read_species_from_config(config_contents)
    if not species_list:
        logging.error("No species found in the input file.")
        sys.exit(1)  # Exit if no species are found

    kraken_taxonomy = config_contents["kraken_taxonomy"]
    results = {}

    for species in species_list:
        search_query = f"s__{species}"
        species_data = fetch_species_data(search_query, kraken_taxonomy)
        if species_data:
            results[species] = {'rows': species_data}

    if results:
        data_files_folder = os.path.join(args.path, 'data-files')
        if not os.path.exists(data_files_folder):
            os.makedirs(data_files_folder)

        #Extracting information from kraken2 db: Getting relation between species and tax id.
        kraken_db = config_contents["kraken_db"]
        inspect_file_name = os.path.join(data_files_folder, generate_inspect_filename(kraken_db))
        success = run_kraken2_inspect(kraken_db, inspect_file_name)
        species_taxid_dict = parse_kraken2_inspect(inspect_file_name)

        #logging.info(f"Extracted species and tax IDs: {list(species_taxid_dict.items())[:10]}")  # Displaying first 10 for example

        #Would need a function to update results to include tax ids using species_taxid_dict
        results = update_results_with_taxid_dict(results, species_taxid_dict)


        #Converting to data frame
        filtered_results = filter_data_by_exact_match(results, kraken_taxonomy)

        df = parse_to_table_with_taxid(filtered_results)
        #df = parse_to_table_with_taxid(results, kraken_taxonomy)

        save_species_and_taxid_to_txt(df, data_files_folder)
        update_yaml_config_with_taxid(df, config_file_path)

        output_file =  os.path.join(data_files_folder, f"{args.prefix}_{kraken_taxonomy}.csv")
        logging.info(f"Parsed data saved to {output_file}")
        df.to_csv(output_file, index=False)



        # Extract the GID column and store it in a list
        accessions_to_download = df['GID'].tolist()
        logging.info(f"Extracted assembly accessions for download: {accessions_to_download}")

        # Write the accessions to a file
        accession_file = os.path.join(data_files_folder, f"{args.prefix}_{kraken_taxonomy}_accessions.txt")
        write_accessions_to_file(accessions_to_download, accession_file)

        # Download genomes
        download_genomes_from_ncbi(data_files_folder, args.prefix, f"{args.prefix}_{kraken_taxonomy}_accessions.txt")
        decompress_and_rename_zip( f"{args.prefix}_ncbi_download.zip", df, data_files_folder)

        build_blast_databases(data_files_folder)

    else:
        logging.warning("No data found for any species.")

if __name__ == '__main__':
    main()
