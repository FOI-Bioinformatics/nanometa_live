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
from typing import List, Dict, Union

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

__version__="0.2.1"

def load_config(config_file):
    """
    Load configuration settings from a YAML file using ruamel.yaml.

    Parameters:
        config_file (str): Path to the YAML configuration file.

    Returns:
        dict: Dictionary containing the configuration settings.
    """
    logging.info(f"Loading configuration from {config_file}")
    yaml = YAML(typ='safe')
    with open(config_file, 'r') as cf:
        return yaml.load(cf)


def build_blast_databases(workdir):
    """
    Build BLAST databases for each reference sequence in the genomes folder
    located in the working directory.

    Parameters:
        workdir (str): Path to the working directory.

    Raises:
        Exception: Any exception that occurs during the database build process.
    """
    try:
        input_folder = os.path.join(workdir, "genomes")
        for file in os.listdir(input_folder):
            file_path = os.path.join(input_folder, file)
            logging.info(f"Processing file: {file_path}")

            database_name = os.path.join(workdir, "blast", file)
            system_cmd = ["makeblastdb", "-in", file_path, "-dbtype", "nucl", "-out", database_name]

            # Create a database for the reference sequence using BLAST
            logging.info(f"Running command: {' '.join(system_cmd)}")
            subprocess.run(system_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        logging.info('All databases built successfully.')

    except Exception as e:
        logging.error(f"An error occurred: {e}")
        raise


def read_species_from_config(config_file):
    try:
        config_data = load_config(config_file)
        species_list = config_data.get('species_of_interest', [])

        if species_list:
            logging.info(f"Read {len(species_list)} species from {config_file}.")
            for i, species in enumerate(species_list, 1):
                logging.info(f"  {i}. {species}")
        else:
            logging.warning(f"No species found in {config_file}.")

        return species_list
    except FileNotFoundError:
        logging.error(f"File not found: {config_file}")
        return []
    except PermissionError:
        logging.error(f"Permission denied: {config_file}")
        return []
    except yaml.YAMLError:
        logging.error(f"Error reading YAML file: {config_file}")
        return []





# Updated function to read species from config.yaml
def read_species_from_config(config_contents):
    species_list = config_contents.get('species_of_interest', [])

    if species_list:
        logging.info(f"Read {len(species_list)} species from preloaded config.")
        for i, species in enumerate(species_list, 1):
            logging.info(f"  {i}. {species}")
    else:
        logging.warning("No species found in preloaded config.")

    return species_list


def fetch_species_data(search_str: str, db: str, page: int = 1, itemsPerPage: int = 1000) -> List[Dict[str, Union[str, int]]]:
    base_url = 'https://gtdb-api.ecogenomic.org/search/gtdb'
    params = {
        'search': search_str,
        'page': page,
        'itemsPerPage': itemsPerPage,
        'searchField': f'{db}_tax',
        'gtdbSpeciesRepOnly': True if db == 'gtdb' else False,
        'ncbiTypeMaterialOnly': True if db == 'ncbi' else False
    }
    try:
        response = requests.get(base_url, params=params, headers={'accept': 'application/json'})
        if response.status_code == 200:
            rows = json.loads(response.text)['rows']
            num_rows = len(rows)  # Get the number of rows

            # Log number of fetched rows and success
            logging.info(f"Successfully fetched {num_rows} rows for {search_str} from {db}.")


            # Log details of fetched data for debugging
            for row in rows:
                ncbiorgname = row.get('ncbiOrgName', 'N/A')
                gid = row.get('gid', 'N/A')
                gtdb_rep = row.get('isGtdbSpeciesRep', 'N/A')
                ncbi_type = row.get('isGtdbSpeciesRep', 'N/A')
                #logging.info(f"Seatch string: {search_str}, Fetched row details: NCBI organism: {ncbiorgname}, GID: {gid}, GTDB reprentative: {gtdb_rep}, NCBI type strain: {ncbi_type}")
            return rows
        else:
            logging.warning(f"Failed to get data for {search_str} from {db}. HTTP Status Code: {response.status_code}")
            return []
    except Exception as e:
        logging.error(f"An error occurred while fetching data: {e}")
        return []


def filter_exact_match(rows, search_str, db):
    """
    Filters the rows for exact matches in a given taxonomy field, depending on the database.

    Parameters:
        rows (list of dict): The list of rows to filter.
        search_str (str): The taxonomy string to match exactly.
        db (str): The database ('gtdb' or 'ncbi').

    Returns:
        list of dict: The filtered rows.
    """
    logging.info(f"Filtering rows for exact match with search string: {search_str} using database: {db}")

    field = 'gtdbTaxonomy' if db == 'gtdb' else 'ncbiTaxonomy'
    rep_field = 'isGtdbSpeciesRep' if db == 'gtdb' else 'isNcbiTypeMaterial'

    # Standard filter logic
    filtered_rows = [
        row for row in rows
        if row[field].split(';')[-1].strip() == search_str and row[rep_field] is True
    ]

    logging.info(f"Number of rows after standard filtering: {len(filtered_rows)}")

    if len(filtered_rows) == 0:
        logging.warning(f"No rows found that match the search string: {search_str}. Unfiltered rows: {rows}")

    # Additional filtering for NCBI
    if db == 'ncbi' and len(filtered_rows) > 1:
        gtdb_rep_rows = [row for row in filtered_rows if row['isGtdbSpeciesRep'] is True]

        logging.info(f"Number of rows matching 'isGtdbSpeciesRep' after NCBI-specific filtering: {len(gtdb_rep_rows)}")

        if len(gtdb_rep_rows) == 1:
            return gtdb_rep_rows
        else:
            return [filtered_rows[0]]

    return filtered_rows


def run_kraken2_inspect(kraken2_db_path, output_path):
    """
    Run the Kraken2 inspect command to generate a report if the output file doesn't exist.

    Parameters:
        kraken2_db_path (str): The path to the Kraken2 database.
        output_path (str): The path where the Kraken2 inspect output will be saved.

    Returns:
        bool: True if the command was successful or if the output file already exists, False otherwise.
    """
    if os.path.exists(output_path):
        logging.info(f"kraken2 inspect file already exists at {output_path}.")
        logging.info(f"Skipping running Kraken2 inspect.")
        return True

    try:
        logging.info(f"Running Kraken2 inspect on database: {kraken2_db_path}")
        # Run the Kraken2 inspect command
        subprocess.run(['kraken2-inspect', '--db', kraken2_db_path], stdout=open(output_path, 'w'), check=True)
        logging.info(f"Kraken2 inspect completed successfully. Output saved to {output_path}.")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error in running Kraken2 inspect: {e}")
        return False

def parse_kraken2_inspect(output_path):
    """
    Parse the Kraken2 inspect output file to extract tax IDs and species strings.

    Parameters:
        output_path (str): The path where the Kraken2 inspect output is saved.

    Returns:
        dict: Dictionary with species strings as keys and tax IDs as values.
    """
    try:
        # Read the file into a DataFrame, ignoring comment lines
        df = pd.read_csv(output_path, sep='\t', comment="#", header=None)

        # Strip leading spaces from the species string column
        df.iloc[:, -1] = df.iloc[:, -1].str.strip()

        # Create a dictionary of species and tax IDs
        species_taxid_dict = df.set_index(df.columns[-1])[df.columns[-2]].to_dict()

        return species_taxid_dict
    except Exception as e:
        logging.error(f"Error in parsing Kraken2 inspect file: {e}")
        return None


def update_results_with_taxid_dict(results, species_taxid_dict):
    """
    Update the results dictionary with taxonomic IDs.

    Parameters:
    - results (dict): Dictionary containing species information based on API calls.
    - species_taxid_dict (dict): Dictionary mapping species names to taxonomic IDs.

    Returns:
    - dict: Updated results dictionary.
    """
    # Loop through the dictionary keys and update tax IDs
    for species_name in results.keys():
        # Look up the tax ID
        tax_id = species_taxid_dict.get(species_name, None)

        # Update the dictionary
        if tax_id is not None:
            results[species_name]['tax_id'] = tax_id
        else:
            results[species_name]['tax_id'] = 'N/A'  # If the tax ID is not found, set it to 'N/A'

    return results



def create_row_dict(species, species_info, row):
    return {
        'Species': species,
        'Tax_ID': species_info.get('tax_id', 'N/A'),
        'SearchQuery': f"s__{species}",
        'GID': row.get('gid', 'N/A'),
        'Accession': row.get('accession', 'N/A'),
        'NCBI_OrgName': row.get('ncbiOrgName', 'N/A'),
        'NCBI_Taxonomy': row.get('ncbiTaxonomy', 'N/A'),
        'GTDB_Taxonomy': row.get('gtdbTaxonomy', 'N/A'),
        'Is_GTDB_Species_Rep': row.get('isGtdbSpeciesRep', 'N/A'),
        'Is_NCBI_Type_Material': row.get('isNcbiTypeMaterial', 'N/A'),
    }

def parse_to_table_with_taxid(filtered_data):
    parsed_data = []

    for species, species_info in filtered_data.items():
        for row in species_info['rows']:
            row_dict = create_row_dict(species, species_info, row)
            parsed_data.append(row_dict)

    return pd.DataFrame(parsed_data)



def filter_data_by_exact_match(data, db):
    filtered_data = {}

    for species, species_info in data.items():
        filtered_rows = filter_exact_match(species_info['rows'], f"s__{species}", db)
        filtered_data[species] = {
            'rows': filtered_rows,
            'tax_id': species_info.get('tax_id', 'N/A')
        }

    return filtered_data



def write_accessions_to_file(accessions, filename):
    try:
        with open(filename, 'w') as f:
            f.write('\n'.join(accessions) + '\n')
        logging.info(f"Successfully wrote {len(accessions)} accessions to {filename}.")
    except Exception as e:
        logging.error(f"Failed to write to file: {e}")


def download_genomes_from_ncbi(workdir: str, prefix: str, accession_filename: str = 'ncbi_acc_download_list.txt'):
    # Define the subfolder and create it if it doesn't exist
    subfolder = os.path.join(workdir, 'data-files')
    if not os.path.exists(subfolder):
        os.makedirs(subfolder)
        logging.info(f"Created subfolder: {subfolder}")

    # Define the output filename and its full path
    output_filename = f"{prefix}_ncbi_download.zip"
    output_filepath = os.path.join(subfolder, output_filename)

    # Prepare the command for subprocess
    ncbi_datasets_cmd = [
        'datasets', 'download', 'genome', 'accession',
        '--inputfile', os.path.join(workdir, accession_filename),
        '--filename', output_filepath
    ]

    try:
        ncbi_datasets_process = subprocess.Popen(ncbi_datasets_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        while ncbi_datasets_process.poll() is None:
            line = ncbi_datasets_process.stdout.readline().decode().strip()
            if line:
                logging.info(f'[NCBI-DATASETS] {line}')

    except Exception as e:
        logging.error(f'Failed to download from NCBI using "datasets" software. Exception: {e}')
        logging.info('You can try to run the command manually:')
        logging.info(' '.join(ncbi_datasets_cmd))

def decompress_zip(zip_filename, workingdir):
    try:
        # Construct the full paths using workingdir as the parent directory
        zip_filepath = os.path.join(workingdir, zip_filename)

        logging.info(f"Attempting to decompress {zip_filepath} into {workingdir}")

        with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
            zip_ref.extractall(workingdir)

        logging.info(f"Successfully decompressed {zip_filepath} into {workingdir}")

    except FileNotFoundError:
        logging.error(f"File not found: {zip_filepath}")
    except zipfile.BadZipFile:
        logging.error(f"Invalid ZIP file: {zip_filepath}")
    except PermissionError:
        logging.error(f"Permission denied: {zip_filepath}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while decompressing {zip_filepath}: {e}")


def rename_files(df: pd.DataFrame, workingdir: str):
    try:
        genomes_dir = os.path.join(workingdir, 'genomes')

        # Create the 'genomes' directory if it doesn't exist
        if not os.path.exists(genomes_dir):
            os.makedirs(genomes_dir)
            logging.info(f"Created directory: {genomes_dir}")

        data_dir = os.path.join(workingdir, 'ncbi_dataset', 'data')
        subdirectories = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]

        for subdirectory in subdirectories:
            subdirectory_path = os.path.join(data_dir, subdirectory)

            accession = subdirectory
            species_name = accession  # Default to using the accession as the species name

            if not df.empty and 'GID' in df.columns:
                matching_species = df[df['GID'] == accession]

                if not matching_species.empty:
                    tax_id = matching_species.iloc[0].get('Tax_ID', 'N/A')
                    files_in_dir = os.listdir(subdirectory_path)

                    for filename in files_in_dir:
                        if filename.endswith('.fna'):
                            source_file = os.path.join(subdirectory_path, filename)
                            target_file = os.path.join(genomes_dir, f'{tax_id}.fna')

                            os.rename(source_file, target_file)
                            logging.info(f"Renamed {source_file} to {target_file}")
                            break

                else:
                    logging.warning(f"Accession {accession} not found in DataFrame. Using default name.")

            else:
                logging.warning("DataFrame is empty or does not contain 'GID' column. Skipping renaming.")

    except FileNotFoundError:
        logging.error("Specified directory or file not found.")
    except PermissionError:
        logging.error("Permission denied while accessing directory or file.")
    except Exception as e:
        logging.error(f"An unexpected error occurred while renaming files: {e}")

def decompress_and_rename_zip(zip_filename, species_data, workingdir):
    decompress_zip(zip_filename, workingdir)
    rename_files(species_data, workingdir)




def generate_inspect_filename(file_path):
    """
    Generate the name for the inspect file based on the original file path.

    Parameters:
    file_path (str): The original file path.

    Returns:
    str: The generated inspect file name.
    """
    # Extract the base file name from the path
    base_name = os.path.basename(file_path)

    # Concatenate to form the inspect file name
    inspect_file_name = f"{base_name}-inspect.txt"

    return inspect_file_name


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
        #Extracting information from kraken2 db: Getting relation between species and tax id.
        kraken_db = config_contents["kraken_db"]
        inspect_file_name = os.path.join(args.path, generate_inspect_filename(kraken_db))
        success = run_kraken2_inspect(kraken_db, inspect_file_name)
        species_taxid_dict = parse_kraken2_inspect(inspect_file_name)

        logging.info(f"Extracted species and tax IDs: {list(species_taxid_dict.items())[:10]}")  # Displaying first 10 for example

        #Would need a function to update results to include tax ids using species_taxid_dict
        results = update_results_with_taxid_dict(results, species_taxid_dict)


        #Converting to data frame
        filtered_results = filter_data_by_exact_match(results, kraken_taxonomy)

        df = parse_to_table_with_taxid(filtered_results)
        #df = parse_to_table_with_taxid(results, kraken_taxonomy)
        output_file =  os.path.join(args.path, f"{args.prefix}_{kraken_taxonomy}.csv")
        logging.info(f"Parsed data saved to {output_file}")
        df.to_csv(output_file, index=False)



        # Extract the GID column and store it in a list
        accessions_to_download = df['GID'].tolist()
        logging.info(f"Extracted assembly accessions for download: {accessions_to_download}")

        # Write the accessions to a file
        accession_file = os.path.join(args.path, f"{args.prefix}_{kraken_taxonomy}_accessions.txt")
        write_accessions_to_file(accessions_to_download, accession_file)

        # Download genomes
        download_genomes_from_ncbi(args.path, args.prefix, f"{args.prefix}_{kraken_taxonomy}_accessions.txt")
        decompress_and_rename_zip(f"{args.prefix}_ncbi_download.zip", df, args.path)

        build_blast_databases(args.path)

    else:
        logging.warning("No data found for any species.")

if __name__ == '__main__':
    main()
