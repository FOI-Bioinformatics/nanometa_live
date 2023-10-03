import os
import logging
import subprocess
import shutil
from typing import Any, List, Dict, Union, NoReturn, List
import zipfile
import pandas as pd
import sys
import urllib.request
import gzip
import requests

def remove_temp_files(config_contents):
    """
    Remove temporary files and directories as specified in the configuration.

    Parameters:
        config_contents (dict): Dictionary containing the configuration settings.
    """
    logging.info("Initiating cleanup of temporary files")

    # Define the paths to temporary directories and files
    kraken_results_dir = os.path.join(config_contents["main_dir"], 'kraken_results/')
    qc_dir = os.path.join(config_contents["main_dir"], 'qc_data/')
    qc_file_to_keep = os.path.join(config_contents["main_dir"], 'qc_data/cumul_qc.txt')
    validation_placeholders = os.path.join(config_contents["main_dir"], 'validation_fastas/placeholders')
    force_valid_file = os.path.join(config_contents["main_dir"], 'validation_fastas/force_validation.txt')
    force_blast_file = os.path.join(config_contents["main_dir"], 'blast_result_files/force_blast.txt')
    fastp_dir = os.path.join(config_contents["main_dir"], 'fastp_reports/')
    fastp_file_to_keep = os.path.join(config_contents["main_dir"], 'fastp_reports/compiled_fastp.txt')

    # Remove Kraken results directory
    if os.path.exists(kraken_results_dir):
        shutil.rmtree(kraken_results_dir)
        logging.info('Kraken results directory removed.')

    # Remove QC files, but keep the cumulative file
    if os.path.exists(qc_dir):
        for filename in os.listdir(qc_dir):
            file_path = os.path.join(qc_dir, filename)
            if file_path != qc_file_to_keep and os.path.isfile(file_path):
                os.remove(file_path)
        logging.info('QC files removed. Cumulative file kept.')

    # Remove fastP reports, but keep the compiled file
    if os.path.exists(fastp_dir):
        for filename in os.listdir(fastp_dir):
            file_path = os.path.join(fastp_dir, filename)
            if file_path != fastp_file_to_keep and os.path.isfile(file_path):
                os.remove(file_path)
        logging.info('fastP reports removed. Compiled file kept.')

    # Remove validation placeholders
    if os.path.exists(validation_placeholders):
        shutil.rmtree(validation_placeholders)
        logging.info('Validation placeholders removed.')

    # Remove force_validation file
    if os.path.isfile(force_valid_file):
        os.remove(force_valid_file)
        logging.info('Force_validation file removed.')

    # Remove force_blast file
    if os.path.isfile(force_blast_file):
        os.remove(force_blast_file)
        logging.info('Force_blast file removed.')

    logging.info('Cleanup done.')

def decompress_zip(zip_filename: str, workingdir: str) -> Union[bool, None]:
    """
    Decompress a ZIP file into a specified working directory.

    Parameters:
        zip_filename (str): The name of the ZIP file.
        workingdir (str): The directory where the ZIP file is located and will be extracted.

    Returns:
        bool: True if successful, False if failed, None if an exception is caught.
    """
    zip_filepath = os.path.join(workingdir, zip_filename)

    try:
        logging.info(f"Attempting to decompress {zip_filepath} into {workingdir}")

        with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
            zip_ref.extractall(workingdir)

        logging.info(f"Successfully decompressed {zip_filepath} into {workingdir}")
        return True

    except FileNotFoundError:
        logging.error(f"File not found: {zip_filepath}")
    except zipfile.BadZipFile:
        logging.error(f"Invalid ZIP file: {zip_filepath}")
    except PermissionError:
        logging.error(f"Permission denied: {zip_filepath}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while decompressing {zip_filepath}: {e}")

    return False


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
                            target_file = os.path.join(genomes_dir, f'{tax_id}.fasta')

                            os.rename(source_file, target_file)
                            logging.info(f"Renamed {source_file} to {target_file}")
                            break

                else:
                    logging.info(f"Accession {accession} is already copied and renamed.")

            else:
                logging.warning("DataFrame is empty or does not contain 'GID' column. Skipping renaming.")

    except FileNotFoundError:
        logging.error("Specified directory or file not found.")
    except PermissionError:
        logging.error("Permission denied while accessing directory or file.")
    except Exception as e:
        logging.error(f"An unexpected error occurred while renaming files: {e}")


def decompress_and_rename_zip(
        zip_filename: str,
        species_data: Dict[str, Union[str, int]],
        workingdir: str
    ) -> bool:
    """
    Decompress a ZIP file and rename its contents based on the provided species data.

    Parameters:
        zip_filename (str): The name of the ZIP file.
        species_data (Dict[str, Union[str, int]]): A dictionary containing species data.
        workingdir (str): The directory where the ZIP file is located and will be extracted.

    Returns:
        bool: True if both tasks are successful, False otherwise.
    """
    # Step 1: Decompress the ZIP file
    if not decompress_zip(zip_filename, workingdir):
        return False  # Stop execution if decompression failed

    # Step 2: Rename files based on species data
    if not rename_files(species_data, workingdir):
        return False  # Stop execution if renaming failed

    return True


def generate_inspect_filename(file_path: str) -> str:
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

def save_species_and_taxid_to_txt(df: pd.DataFrame, workdir: str, filename: str = "species_taxid.txt"):
    """
    Save the "Species" and "Tax_ID" columns from a DataFrame to a text file.

    Parameters:
        df (pd.DataFrame): DataFrame containing parsed data.
        workdir (str): The working directory where the text file will be saved.
        filename (str, optional): The name of the text file. Defaults to "species_taxid.txt".

    Returns:
        str: The path to the saved text file.
    """
    logging.info("Starting the process to save 'Species' and 'Tax_ID' columns to a text file.")

    # Check if workdir exists, if not, create it
    if not os.path.exists(workdir):
        logging.info(f"Working directory {workdir} does not exist. Creating it.")
        os.makedirs(workdir)
    else:
        logging.info(f"Working directory {workdir} already exists. Proceeding.")

    output_path = os.path.join(workdir, filename)

    logging.debug(f"Target file path for saving is {output_path}.")

    # Check if DataFrame contains "Species" and "Tax_ID" columns
    if "Species" not in df.columns or "Tax_ID" not in df.columns:
        logging.error("DataFrame is missing either 'Species' or 'Tax_ID' columns. Aborting.")
        raise ValueError("DataFrame is missing either 'Species' or 'Tax_ID' columns.")

    logging.info(f"Found 'Species' and 'Tax_ID' columns in the DataFrame. Proceeding to save.")

    # Save to text file
    try:
        df[["Species", "Tax_ID"]].to_csv(output_path, sep='\t', index=False)
        logging.info(f"Successfully saved 'Species' and 'Tax_ID' columns to {output_path}.")
    except Exception as e:
        logging.error(f"An error occurred while saving the DataFrame to text: {e}")
        raise

    return output_path


def download_genomes_from_ncbi(workdir: str, prefix: str, accession_filename: str = 'ncbi_acc_download_list.txt'):
    """
    Download genomes from NCBI and save them to a specific directory.

    Parameters:
    - workdir (str): The working directory where files will be saved.
    - prefix (str): The prefix for the output filename.
    - accession_filename (str): The name of the file containing accession numbers. Default is 'ncbi_acc_download_list.txt'.
    """

    # Logging the start of the download process
    logging.info(f"Starting download of genomes with prefix: {prefix}")


    # Define the output filename and its full path
    output_filename = f"{prefix}_ncbi_download.zip"
    output_filepath = os.path.join(workdir, output_filename)
    logging.info(f"Output will be saved as: {output_filepath}")

    # Prepare the command for subprocess
    ncbi_datasets_cmd = [
        'datasets', 'download', 'genome', 'accession',
        '--inputfile', os.path.join(workdir, accession_filename),
        '--filename', output_filepath
    ]

    logging.info(f"Running command: {' '.join(ncbi_datasets_cmd)}")

    try:
        ncbi_datasets_process = subprocess.Popen(ncbi_datasets_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        while ncbi_datasets_process.poll() is None:
            line = ncbi_datasets_process.stdout.readline().decode().strip()
            if line:
                logging.info(f'[NCBI-DATASETS] {line}')

    except FileNotFoundError:
        logging.error(f"Command not found: {ncbi_datasets_cmd[0]}")
    except PermissionError:
        logging.error(f"Permission denied: Cannot execute command")
    except Exception as e:
        logging.error(f'Failed to download from NCBI using "datasets" software. Exception: {e}')
        logging.info('You can try to run the command manually:')
        logging.info(' '.join(ncbi_datasets_cmd))


def write_accessions_to_file(accessions: List[str], filename: str) -> None:
    """
    Writes a list of accessions to a file.

    Parameters:
    - accessions (List[str]): The list of accession numbers to write.
    - filename (str): The name of the file where accessions will be written.

    """
    logging.info(f"Attempting to write {len(accessions)} accessions to {filename}.")

    try:
        # Open the file in write mode
        with open(filename, 'w') as f:
            # Write each accession to the file, separated by a newline
            f.write('\n'.join(accessions) + '\n')

        logging.info(f"Successfully wrote {len(accessions)} accessions to {filename}.")
    except FileNotFoundError:
        logging.error(f"File not found: {filename}")
    except PermissionError:
        logging.error(f"Permission denied: Cannot write to {filename}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while writing to {filename}: {e}")


def process_local_files(indata_folder: str, workdir: str, id_dict: Dict[str, Union[str, int]],
                        id_type: str = 'species') -> bool:
    """
    Checks for the existence of {id}.fasta files in the indata-folder.
    Copies them to {workdir}/genomes and renames them if necessary.

    Parameters:
        indata_folder (str): The directory to look for input {id}.fasta files.
        workdir (str): The working directory where the genomes will be copied.
        id_dict (Dict[str, Union[str, int]]): Dictionary mapping original ID to new ID for renaming.
        id_type (str): The type of ID being processed ('species' or 'taxid').

    Returns:
        bool: True if all operations are successful, False otherwise.
    """

    logging.info(f"Initiating process to handle local {id_type} files.")

    # Create the genomes directory if it does not exist
    genomes_dir = os.path.join(workdir, 'data-files', 'genomes')
    if not os.path.exists(genomes_dir):
        os.makedirs(genomes_dir)
        logging.info(f"Created genomes directory at {genomes_dir}.")

    # Check for existence of each {id}.fasta file
    missing_files = []
    for original_id, new_id in id_dict.items():
        filename = f"{original_id}.fasta" if id_type == 'species' else f"{new_id}.fasta"
        original_file_path = os.path.join(indata_folder, filename)

        if not os.path.exists(original_file_path):
            missing_files.append(original_file_path)

    if missing_files:
        logging.error(f"Missing files: {', '.join(missing_files)}. Aborting process.")
        return False

    # If all files exist, copy and rename them
    for original_id, new_id in id_dict.items():
        filename = f"{original_id}.fasta" if id_type == 'species' else f"{new_id}.fasta"
        original_file_path = os.path.join(indata_folder, filename)

        dest_file_path = os.path.join(genomes_dir, f"{new_id}.fasta")
        shutil.copy(original_file_path, dest_file_path)
        logging.info(f"Copied and renamed {original_file_path} to {dest_file_path}.")

    logging.info(f"Successfully processed all local {id_type} files.")
    return True


def download_gtdb_metadata(workdir: str) -> str:
    """
    Downloads the GTDB metadata file and saves it in the metadata folder.

    Parameters:
        workdir (str): The working directory where data-files are stored.

    Returns:
        str: Path to the downloaded metadata file.
    """
    logging.info("Initiating GTDB metadata download.")

    # Correcting this line to ensure the folder structure is correct
    metadata_dir = os.path.join(workdir)

    if not os.path.exists(metadata_dir):
        os.makedirs(metadata_dir)
        logging.info(f"Created metadata directory at {metadata_dir}.")

    file_url = "https://data.gtdb.ecogenomic.org/releases/latest/bac120_metadata.tsv.gz"

    # This should now correctly place the file
    file_path = os.path.join(metadata_dir, "bac120_metadata.tsv.gz")

    if not os.path.exists(file_path):
        logging.info(f"Downloading GTDB metadata from {file_url} to {file_path}.")
        urllib.request.urlretrieve(file_url, file_path)
    else:
        logging.info("GTDB metadata already exists. Skipping download.")

    return file_path


def read_and_process_gtdb_metadata(file_path: str, kraken_taxonomy: str, species_list: List[str]) -> pd.DataFrame:
    """
    Reads the GTDB metadata file and filters and transforms the necessary columns.

    Parameters:
        file_path (str): Path to the GTDB metadata file.
        kraken_taxonomy (str): The taxonomy database used by Kraken2 ('gtdb' or 'ncbi').
        species_list (List[str]): List of species to filter by.

    Returns:
        pd.DataFrame: Processed DataFrame.
    """
    logging.info(f"Reading GTDB metadata from {file_path}.")

    # Pandas can read compressed .gz files directly
    df = pd.read_csv(file_path, sep='\t', compression='gzip')

    initial_row_count = len(df)
    logging.info(f"Initial number of rows: {initial_row_count}")

    # Keep only necessary columns
    logging.info("Filtering necessary columns.")
    df = df[['accession', 'gtdb_taxonomy', 'gtdb_representative', 'ncbi_taxonomy',
             'ncbi_type_material_designation', 'gtdb_type_designation_ncbi_taxa']]

    # Rename 'accession' to 'GID' and remove 'RS_' prefix
    df.rename(columns={'accession': 'GID'}, inplace=True)
    df['GID'] = df['GID'].str.lstrip('RS_')

    # Transform 'gtdb_taxonomy' and 'ncbi_taxonomy' to keep only species and remove 's__'
    logging.info("Transforming taxonomy columns to keep only species information.")
    df['gtdb_taxonomy'] = df['gtdb_taxonomy'].apply(lambda x: x.split(';')[-1][3:]).str.lstrip('s__')
    df['ncbi_taxonomy'] = df['ncbi_taxonomy'].apply(lambda x: x.split(';')[-1][3:]).str.lstrip('s__')

    # Filter based on Kraken2 taxonomy database and species list
    if kraken_taxonomy == 'gtdb':
        logging.info("Filtering rows based on GTDB taxonomy and representative status.")
        df = df[df['gtdb_taxonomy'].isin(species_list) & (df['gtdb_representative'] == 't')]
        df['Species'] = df['gtdb_taxonomy']
    elif kraken_taxonomy == 'ncbi':
        logging.info("Filtering rows based on NCBI taxonomy and type material designation.")
        df = df[df['ncbi_taxonomy'].isin(species_list) & (df['ncbi_type_material_designation'] != 'none')]
        df['Species'] = df['ncbi_taxonomy']

    final_row_count = len(df)
    logging.info(f"Final number of rows after filtering: {final_row_count}")

    logging.info("Successfully processed GTDB metadata.")
    return df

def check_genome_files_existence(workdir: str, species_taxid_dict: dict) -> List[str]:
    """
    Check if genome files already exist in the workdir/data-files/genomes directory.

    Parameters:
        workdir (str): The working directory where data-files are stored.
        species_taxid_dict (dict): Dictionary of species names and their corresponding tax IDs.

    Returns:
        List[str]: List of species names for which genome files are missing.
    """
    genomes_dir = os.path.join(workdir, 'genomes')

    missing_species = []
    for species, taxid in species_taxid_dict.items():
        genome_file_path = os.path.join(genomes_dir, f"{taxid}.fasta")

        if not os.path.exists(genome_file_path):
            missing_species.append(species)

    if missing_species:
        logging.warning(f"Genome files for the following species are missing: {', '.join(missing_species)}")

    else:
        logging.info("All genome files already exist!")

    return missing_species


def download_figshare_files(figshare_id: str, file_names: List[str], download_dir: str = "./downloads") -> None:
    # Get the article metadata from the Figshare API
    response = requests.get(f"https://api.figshare.com/v2/articles/{figshare_id}")
    response.raise_for_status()  # Check for any HTTP errors
    article_metadata = response.json()

    # Build a dictionary to map file names to download URLs
    download_urls = {file['name']: file['download_url'] for file in article_metadata['files']}

    os.makedirs(download_dir, exist_ok=True)

    def download_file(url: str, file_path: str) -> None:
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Check for any HTTP errors
        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

    # Iterate through each file name to download the files
    for file_name in file_names:
        file_url = download_urls.get(file_name)
        if file_url:
            file_path = os.path.join(download_dir, file_name)
            try:
                download_file(file_url, file_path)
                logging.info(f"Successfully downloaded {file_name} to {file_path}")
            except requests.RequestException as e:
                logging.error(f"Failed to download {file_name} due to {str(e)}")
        else:
            logging.error(f"No download URL found for {file_name}")