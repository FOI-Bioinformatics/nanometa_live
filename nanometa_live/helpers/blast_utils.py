import os
import logging
import subprocess
from typing import Any, List, Dict, Union, NoReturn, List

def build_blast_databases(workdir: str, missing_databases: List[str] = None) -> NoReturn:
    """
    Build BLAST databases for each reference sequence in the genomes folder
    located in the working directory. Only builds databases for genomes
    that are in the missing_databases list.

    Parameters:
        workdir (str): Path to the working directory.
        missing_databases (List[str]): List of missing BLAST databases by Tax ID.

    Raises:
        Exception: Any exception that occurs during the database build process.
    """
    try:
        input_folder = os.path.join(workdir, "genomes")
        blast_db_folder = os.path.join(workdir, "blast")

        if not os.path.exists(input_folder):
            logging.error(f"Input folder {input_folder} does not exist. Exiting.")
            return

        files_to_process = os.listdir(input_folder)

        if not files_to_process:
            logging.warning(f"No files found in {input_folder}. Nothing to process.")
            return

        if not missing_databases:
            logging.info("No missing databases. Skipping BLAST database building.")
            return

        logging.info(f"Found {len(files_to_process)} files to process.")

        for file in files_to_process:
            # Extract taxid from the file name
            taxid = os.path.splitext(file)[0]

            # Check if BLAST database needs to be built for this genome
            if missing_databases and taxid not in missing_databases:
                logging.info(f"BLAST database already exists for Tax ID: {taxid}. Skipping.")
                continue

            file_path = os.path.join(input_folder, file)
            logging.info(f"Processing file: {file_path}")

            database_name = os.path.join(blast_db_folder, file)
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

def check_blast_dbs_exist(species_to_taxid: Dict[str, int], data_files_folder: str) -> List[str]:
    """
    Parameters:
        species_to_taxid (Dict[str, int]): Dictionary mapping species names to tax IDs.
        data_files_folder (str): Path to the folder containing the BLAST databases.

    Returns:
        List[str]: List of missing databases by taxid.
    """

    logging.info("Starting to check existence of BLAST databases.")
    data_files_folder = os.path.join(data_files_folder, "blast")

    missing_dbs = []

    if not species_to_taxid:
        logging.warning("Received an empty species to taxid map. No BLAST databases to check.")
        return missing_dbs

    if not os.path.exists(data_files_folder):
        logging.error(f"Data files folder '{data_files_folder}' does not exist.")
        return missing_dbs

    for species, taxid in species_to_taxid.items():
        blast_db_file = os.path.join(data_files_folder, f"{taxid}.fasta.nhr")

        if not os.path.exists(blast_db_file):
            logging.info(f"BLAST database for {species} (Tax ID: {taxid}) does not exist.")
            missing_dbs.append(str(taxid))
        else:
            logging.info(f"BLAST database for {species} (Tax ID: {taxid}) exists.")

    if missing_dbs:
        logging.warning(f"Missing BLAST databases for Tax IDs: {', '.join(missing_dbs)}")
    else:
        logging.info("All BLAST databases exist for the given species list.")

    return missing_dbs
