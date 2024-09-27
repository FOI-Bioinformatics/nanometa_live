from typing import Any, List, Dict, Union, NoReturn, List
import os
import subprocess
import pandas as pd
import requests
import tarfile
import shutil
import logging


def download_database(url: str, dest_file_path: str) -> bool:
    """
    Downloads a file from the given URL to the specified destination path.

    :param url: URL of the file to download.
    :param dest_file_path: Destination file path.
    :return: True if download is successful, False otherwise.
    """
    logging.info(f"Starting download from {url}")

    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(dest_file_path, "wb") as f:
                shutil.copyfileobj(response.raw, f)
            logging.info(
                f"Successfully downloaded and saved file to {dest_file_path}"
            )
            return True
        else:
            logging.error(
                f"Failed to download file from {url}. HTTP status code: {response.status_code}"
            )
            return False
    except Exception as e:
        logging.error(f"Error during file download from {url}: {e}")
        return False


def decompress_database(tar_file_path: str, extract_to_folder: str) -> bool:
    """
    Decompresses a tar.gz file to the specified folder.

    :param tar_file_path: Path to the tar.gz file.
    :param extract_to_folder: Folder where the contents should be extracted.
    :return: True if decompression is successful, False otherwise.
    """
    logging.info(
        f"Starting decompression of '{tar_file_path}' into '{extract_to_folder}'"
    )
    try:
        with tarfile.open(tar_file_path, "r:gz") as tar:
            tar.extractall(path=extract_to_folder)
        logging.info(
            f"Successfully unpacked '{tar_file_path}' into '{extract_to_folder}'"
        )
        return True
    except tarfile.TarError as e:
        logging.error(
            f"Error unpacking '{tar_file_path}' into '{extract_to_folder}': {e}"
        )
        return False


def copy_inspect_file(
    source_folder: str,
    destination_folder: str,
    new_filename: str = "kraken2_databases-inspect.txt",
) -> bool:
    """
    Copies the inspect.txt file from the source folder to the destination folder with a new filename.

    :param source_folder: Folder where the original inspect.txt file is located.
    :param destination_folder: Folder where the file should be copied to.
    :param new_filename: New filename for the copied file. Default is 'kraken2_databases-inspect.txt'.
    :return: True if the copy is successful, False otherwise.
    """
    source_file_path = os.path.join(source_folder, "inspect.txt")
    destination_file_path = os.path.join(destination_folder, new_filename)

    if not os.path.exists(source_file_path):
        logging.error(f"Source file '{source_file_path}' not found.")
        return False

    try:
        shutil.copyfile(source_file_path, destination_file_path)
        logging.info(
            f"Copied '{source_file_path}' to '{destination_file_path}'"
        )
        return True
    except Exception as e:
        logging.error(f"Failed to copy file: {e}")
        return False


def run_kraken2_inspect(kraken2_db_path: str, output_path: str) -> bool:
    """
    Run the Kraken2 inspect command to generate a report if the output file doesn't exist.

    Parameters:
        kraken2_db_path (str): The path to the Kraken2 database.
        output_path (str): The path where the Kraken2 inspect output will be saved.

    Raises:
        FileNotFoundError: If the Kraken2 database path does not exist.

    Returns:
        bool: True if the command was successful or if the output file already exists, False otherwise.
    """
    if not os.path.exists(kraken2_db_path):
        logging.error(
            f"Kraken2 database path {kraken2_db_path} does not exist."
        )
        raise FileNotFoundError(
            f"Kraken2 database path {kraken2_db_path} does not exist."
        )

    if os.path.exists(output_path):
        logging.info(f"Kraken2 inspect file already exists at {output_path}.")
        logging.info(f"Skipping running Kraken2 inspect.")
        return True

    try:
        logging.info(f"Running Kraken2 inspect on database: {kraken2_db_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["kraken2-inspect", "--db", kraken2_db_path],
                stdout=f,
                check=True,
            )
        logging.info(
            f"Kraken2 inspect completed successfully. Output saved to {output_path}."
        )
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error in running Kraken2 inspect: {e}")
        return False


def parse_kraken2_inspect(
    output_path: str, species_list: List[str] = None
) -> dict:
    """
    Parse the Kraken2 inspect output file to extract tax IDs and species strings.
    Only returns species that are in the provided list.

    Parameters:
        output_path (str): The path where the Kraken2 inspect output is saved.
        species_list (List[str]): List of species to keep in the output. If None, keeps all species.

    Returns:
        dict: Dictionary with species strings as keys and tax IDs as values.
    """
    try:
        logging.info(
            f"Attempting to read Kraken2 inspect file from: {output_path}"
        )

        # Read the file into a DataFrame, ignoring comment lines
        df = pd.read_csv(output_path, sep="\t", comment="#", header=None)
        logging.info(f"Successfully read the file into a DataFrame.")

        # Strip leading spaces from the species string column
        df.iloc[:, -1] = df.iloc[:, -1].str.strip()
        logging.info("Stripped leading spaces from species strings.")

        # If a species list is provided, filter the DataFrame
        if species_list:
            df = df[df.iloc[:, -1].isin(species_list)]
            logging.info(
                f"Filtered DataFrame based on provided species list. {len(df)} species remain."
            )

        # Create a dictionary of species and tax IDs
        species_taxid_dict = df.set_index(df.columns[-1])[
            df.columns[-2]
        ].to_dict()
        logging.info("Successfully created species to tax ID dictionary.")

        return species_taxid_dict

    except Exception as e:
        logging.error(f"Error in parsing Kraken2 inspect file: {e}")
        return None
