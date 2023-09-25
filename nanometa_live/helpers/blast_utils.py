import os
import logging
import subprocess
from typing import Any, List, Dict, Union, NoReturn, List

def build_blast_databases(workdir: str) -> NoReturn:
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

        if not os.path.exists(input_folder):
            logging.error(f"Input folder {input_folder} does not exist. Exiting.")
            return

        files_to_process = os.listdir(input_folder)

        if not files_to_process:
            logging.warning(f"No files found in {input_folder}. Nothing to process.")
            return

        logging.info(f"Found {len(files_to_process)} files to process.")

        for file in files_to_process:
            file_path = os.path.join(input_folder, file)
            logging.info(f"Processing file: {file_path}")

            database_name = os.path.join(workdir, "blast", file)
            system_cmd = ["makeblastdb", "-in", file_path, "-dbtype", "nucl", "-out", database_name]

            # Create a database for the reference sequence using BLAST
            logging.info(f"Running command: {' '.join(system_cmd)}")
            subprocess.run(system_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        logging.info('All databases built successfully.')

    except subprocess.CalledProcessError as cpe:
        logging.error(f"Command failed: {cpe}. Command was {' '.join(cpe.cmd)}.")
        raise
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        raise

