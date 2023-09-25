from typing import Any, List, Dict, Union, NoReturn, List
import os
import subprocess
import pandas as pd
import logging

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
        logging.error(f"Kraken2 database path {kraken2_db_path} does not exist.")
        raise FileNotFoundError(f"Kraken2 database path {kraken2_db_path} does not exist.")

    if os.path.exists(output_path):
        logging.info(f"Kraken2 inspect file already exists at {output_path}.")
        logging.info(f"Skipping running Kraken2 inspect.")
        return True

    try:
        logging.info(f"Running Kraken2 inspect on database: {kraken2_db_path}")
        with open(output_path, 'w') as f:
            subprocess.run(['kraken2-inspect', '--db', kraken2_db_path], stdout=f, check=True)
        logging.info(f"Kraken2 inspect completed successfully. Output saved to {output_path}.")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error in running Kraken2 inspect: {e}")
        return False

def parse_kraken2_inspect(output_path: str) -> dict:
    """
    Parse the Kraken2 inspect output file to extract tax IDs and species strings.

    Parameters:
        output_path (str): The path where the Kraken2 inspect output is saved.

    Returns:
        dict: Dictionary with species strings as keys and tax IDs as values.
    """
    try:
        logging.info(f"Attempting to read Kraken2 inspect file from: {output_path}")

        # Read the file into a DataFrame, ignoring comment lines
        df = pd.read_csv(output_path, sep='\t', comment="#", header=None)
        logging.info(f"Successfully read the file into a DataFrame.")

        # Strip leading spaces from the species string column
        df.iloc[:, -1] = df.iloc[:, -1].str.strip()
        logging.info("Stripped leading spaces from species strings.")

        # Create a dictionary of species and tax IDs
        species_taxid_dict = df.set_index(df.columns[-1])[df.columns[-2]].to_dict()
        logging.info("Successfully created species to tax ID dictionary.")

        return species_taxid_dict

    except Exception as e:
        logging.error(f"Error in parsing Kraken2 inspect file: {e}")
        return None

