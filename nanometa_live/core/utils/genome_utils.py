"""
Genome utility functions for Nanometa Live.

This module provides functions for fetching, downloading, and processing genome data
from various sources like GTDB and NCBI.
"""

import os
import logging
import subprocess
import requests
import zipfile
import shutil
import pandas as pd
from typing import Dict, List, Any, Union, Optional

# GTDB API Integration Functions
def fetch_species_data(search_query: str, taxonomy_db: str = "gtdb") -> List[Dict[str, Any]]:
    """Fetch species data from GTDB API."""
    base_url = "https://gtdb-api.ecogenomic.org/search/gtdb"
    params = {
        "search": search_str,
        "page": page,
        "itemsPerPage": itemsPerPage,
        "searchField": f"{db}_tax",
        "gtdbSpeciesRepOnly": True if db == "gtdb" else False,
        "ncbiTypeMaterialOnly": True if db == "ncbi" else False,
    }
    try:
        response = requests.get(
            base_url, params=params, headers={"accept": "application/json"}
        )
        if response.status_code == 200:
            rows = json.loads(response.text)["rows"]
            num_rows = len(rows)  # Get the number of rows

            # Stop if no rows are returned
            if num_rows == 0:
                logging.warning(
                    f"No data fetched for {search_str} from {db}. Stopping function."
                )
                sys.exit(
                    "Terminating the program due to zero fetched rows."
                )  # Terminate the program

            logging.info(
                f"Successfully fetched {num_rows} rows for {search_str} from {db}."
            )

            # Log details of fetched data for debugging
            for row in rows:
                ncbiorgname = row.get("ncbiOrgName", "N/A")
                gid = row.get("gid", "N/A")
                gtdb_rep = row.get("isGtdbSpeciesRep", "N/A")
                ncbi_type = row.get("isGtdbSpeciesRep", "N/A")
                # logging.info(f"Search string: {search_str}, Fetched row details: NCBI organism: {ncbiorgname}, GID: {gid}, GTDB representative: {gtdb_rep}, NCBI type strain: {ncbi_type}")
            return rows
        else:
            logging.warning(
                f"Failed to get data for {search_str} from {db}. HTTP Status Code: {response.status_code}"
            )
            return []
    except Exception as e:
        logging.error(f"An error occurred while fetching data: {e}")
        sys.exit(
            f"Terminating the program due to an error: {e}"
        )  # Terminate the program

def filter_data_by_exact_match(results: Dict[str, Any], taxonomy_db: str = "gtdb") -> Dict[str, Any]:
    """
    Filter data by exact species match from a given database.

    Parameters:
        data (Dict[str, Dict[str, Any]]): The data dictionary containing species information.
        db (Any): The database to search for exact matches.

    Returns:
        Dict[str, Dict[str, Any]]: A dictionary containing filtered data.
    """
    filtered_data = {}

    for species, species_info in data.items():
        filtered_rows = filter_exact_match(
            species_info["rows"], f"s__{species}", db
        )
        filtered_data[species] = {
            "rows": filtered_rows,
            "tax_id": species_info.get("tax_id", "N/A"),
        }

    return filtered_data

def update_results_with_taxid_dict(results: Dict[str, Any], species_taxid_dict: Dict[str, str]) -> Dict[str, Any]:
    """Update results with taxonomy IDs from species_taxid_dict."""
    """
    Update the results dictionary with taxonomic IDs.

    Parameters:
    - results (dict): Dictionary containing species information based on API calls.
    - species_taxid_dict (dict): Dictionary mapping species names to taxonomic IDs.

    Returns:
    - dict: Updated results dictionary.
    """
    logging.info("Starting the update of results with taxonomic IDs.")

    # Loop through the dictionary keys and update tax IDs
    for species_name in results.keys():
        logging.debug(f"Processing species: {species_name}")

        # Look up the tax ID
        tax_id = species_taxid_dict.get(species_name, None)

        # Update the dictionary
        if tax_id is not None:
            logging.info(
                f"Found tax ID {tax_id} in kraken2 inspect file for species {species_name}. Updating results."
            )
            results[species_name]["tax_id"] = tax_id
        else:
            logging.warning(
                f"Tax ID not found for species {species_name}. Setting it to 'N/A'."
            )
            results[species_name][
                "tax_id"
            ] = "N/A"  # If the tax ID is not found, set it to 'N/A'

    logging.info("Finished updating results with taxonomic IDs.")

    return results

def parse_to_table_with_taxid(filtered_data: Dict[str, Any]) -> pd.DataFrame:
    """
    Parse filtered data into a DataFrame.

    Parameters:
    - filtered_data (dict): Filtered data containing species and their information.

    Returns:
    - pd.DataFrame: DataFrame containing parsed data.
    """
    logging.info("Starting the parsing of filtered data into a DataFrame.")

    # Initialize an empty list to hold the parsed data.
    parsed_data = []

    # Loop through each species and its corresponding information.
    for species, species_info in filtered_data.items():
        logging.debug(f"Parsing information for species: {species}")

        # Loop through each row of species_info.
        for row in species_info["rows"]:
            logging.debug(f"Parsing row for species {species}")

            # Create a row dictionary.
            row_dict = create_row_dict(species, species_info, row)

            # Append the row dictionary to parsed_data.
            parsed_data.append(row_dict)

        logging.debug(f"Finished parsing information for species: {species}")

    # Create a DataFrame from the parsed data.
    parsed_df = pd.DataFrame(parsed_data)

    logging.info(
        f"Finished parsing filtered data into a DataFrame with {len(parsed_df)} rows."
    )

    return parsed_df

# GTDB Metadata Functions
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
        logging.info(
            f"Downloading GTDB metadata from {file_url} to {file_path}."
        )
        urllib.request.urlretrieve(file_url, file_path)
    else:
        logging.info("GTDB metadata already exists. Skipping download.")

    return file_path
def read_and_process_gtdb_metadata(file_path: str, taxonomy_db: str, species_list: List[str]) -> pd.DataFrame:
    """Process GTDB metadata file."""
    logging.info(f"Reading GTDB metadata from {file_path}.")

    # Pandas can read compressed .gz files directly
    df = pd.read_csv(file_path, sep="\t", compression="gzip")

    initial_row_count = len(df)
    logging.info(f"Initial number of rows: {initial_row_count}")

    # Keep only necessary columns
    logging.info("Filtering necessary columns.")
    df = df[
        [
            "accession",
            "gtdb_taxonomy",
            "gtdb_representative",
            "ncbi_taxonomy",
            "ncbi_type_material_designation",
            "gtdb_type_designation_ncbi_taxa",
        ]
    ]

    # Rename 'accession' to 'GID' and remove 'RS_' prefix
    df.rename(columns={"accession": "GID"}, inplace=True)
    df["GID"] = df["GID"].str.lstrip("RS_")

    # Transform 'gtdb_taxonomy' and 'ncbi_taxonomy' to keep only species and remove 's__'
    logging.info(
        "Transforming taxonomy columns to keep only species information."
    )
    df["gtdb_taxonomy"] = (
        df["gtdb_taxonomy"]
        .apply(lambda x: x.split(";")[-1][3:])
        .str.lstrip("s__")
    )
    df["ncbi_taxonomy"] = (
        df["ncbi_taxonomy"]
        .apply(lambda x: x.split(";")[-1][3:])
        .str.lstrip("s__")
    )

    # Filter based on Kraken2 taxonomy database and species list
    if kraken_taxonomy == "gtdb":
        logging.info(
            "Filtering rows based on GTDB taxonomy and representative status."
        )
        df = df[
            df["gtdb_taxonomy"].isin(species_list)
            & (df["gtdb_representative"] == "t")
        ]
        df["Species"] = df["gtdb_taxonomy"]
    elif kraken_taxonomy == "ncbi":
        logging.info(
            "Filtering rows based on NCBI taxonomy and type material designation."
        )
        df = df[
            df["ncbi_taxonomy"].isin(species_list)
            & (df["ncbi_type_material_designation"] != "none")
        ]
        df["Species"] = df["ncbi_taxonomy"]

    final_row_count = len(df)
    logging.info(f"Final number of rows after filtering: {final_row_count}")

    logging.info("Successfully processed GTDB metadata.")
    return df



# Genome File Handling Functions
def check_genome_files_existence(workdir: str, species_taxid_dict: Dict[str, str]) -> List[str]:
    """Check which genome files are missing."""
    genomes_dir = os.path.join(workdir, "genomes")

    missing_species = []
    for species, taxid in species_taxid_dict.items():
        genome_file_path = os.path.join(genomes_dir, f"{taxid}.fasta")

        if not os.path.exists(genome_file_path):
            missing_species.append(species)

    if missing_species:
        logging.warning(
            f"Genome files for the following species are missing: {', '.join(missing_species)}"
        )

    else:
        logging.info("All genome files already exist!")

    return missing_species

def write_accessions_to_file(accessions: List[str], filename: str) -> None:
    """Write accessions to a file for NCBI datasets CLI."""
    logging.info(
        f"Attempting to write {len(accessions)} accessions to {filename}."
    )

    try:
        # Open the file in write mode
        with open(filename, "w") as f:
            # Write each accession to the file, separated by a newline
            f.write("\n".join(accessions) + "\n")

        logging.info(
            f"Successfully wrote {len(accessions)} accessions to {filename}."
        )
    except FileNotFoundError:
        logging.error(f"File not found: {filename}")
    except PermissionError:
        logging.error(f"Permission denied: Cannot write to {filename}")
    except Exception as e:
        logging.error(
            f"An unexpected error occurred while writing to {filename}: {e}"
        )

def download_genomes_from_ncbi(workdir: str, prefix: str, accession_filename: str) -> None:
    """Download genomes using NCBI datasets CLI."""
    # Logging the start of the download process
    logging.info(f"Starting download of genomes with prefix: {prefix}")

    # Define the output filename and its full path
    output_filename = f"{prefix}_ncbi_download.zip"
    output_filepath = os.path.join(workdir, output_filename)
    logging.info(f"Output will be saved as: {output_filepath}")

    # Prepare the command for subprocess
    ncbi_datasets_cmd = [
        "datasets",
        "download",
        "genome",
        "accession",
        "--inputfile",
        os.path.join(workdir, accession_filename),
        "--filename",
        output_filepath,
    ]

    logging.info(f"Running command: {' '.join(ncbi_datasets_cmd)}")

    try:
        ncbi_datasets_process = subprocess.Popen(
            ncbi_datasets_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

        while ncbi_datasets_process.poll() is None:
            line = ncbi_datasets_process.stdout.readline().decode().strip()
            if line:
                logging.info(f"[NCBI-DATASETS] {line}")

    except FileNotFoundError:
        logging.error(f"Command not found: {ncbi_datasets_cmd[0]}")
    except PermissionError:
        logging.error("Permission denied: Cannot execute command")
    except Exception as e:
        logging.error(
            f'Failed to download from NCBI using "datasets" software. Exception: {e}'
        )
        logging.info("You can try to run the command manually:")
        logging.info(" ".join(ncbi_datasets_cmd))


def decompress_and_rename_zip(zip_filename: str, species_data: pd.DataFrame, workdir: str) -> None:
    """Extract and rename genome files."""

    # Step 1: Decompress the ZIP file
    if not decompress_zip(zip_filename, workingdir):
        return False  # Stop execution if decompression failed

    # Step 2: Rename files based on species data
    if not rename_files(species_data, workingdir):
        return False  # Stop execution if renaming failed

    return True
