import os
import logging
import subprocess
import shutil
from typing import Any, List, Dict, Union, NoReturn, List
from ruamel.yaml import YAML
import pandas as pd
import requests
import json
import sys

def read_species_from_file(filename: str) -> Union[List[str], None]:
    """
    Read the list of species from a file.

    Parameters:
        filename (str): The name of the file containing the species list.

    Returns:
        List[str]: A list of species read from the file, or None if an error occurs.
    """
    try:
        with open(filename, 'r') as f:
            species_list = [line.strip() for line in f if line.strip()]

        if species_list:
            logging.info(f"Read {len(species_list)} species from {filename}.")
        else:
            logging.warning(f"No species found in {filename}.")

        return species_list

    except FileNotFoundError:
        logging.error(f"File not found: {filename}")
        return None
    except PermissionError:
        logging.error(f"Permission denied: {filename}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return None


def read_species_from_config(config_contents: Dict[str, Any]) -> List[str]:
    """
    Read the list of species from preloaded config contents.

    Parameters:
        config_contents (Dict[str, Any]): The dictionary containing the config data.

    Returns:
        List[str]: A list of species read from the config contents.
    """
    raw_species_list = config_contents.get('species_of_interest', [])
    species_list = []

    if raw_species_list:
        logging.info(f"Read {len(raw_species_list)} species from preloaded config.")

        for i, species_entry in enumerate(raw_species_list, 1):
            species_name = species_entry.get('name', 'Unknown')
            logging.info(f"  {i}. s__{species_name}")

            species_list.append(species_name)
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

            # Stop if no rows are returned
            if num_rows == 0:
                logging.warning(f"No data fetched for {search_str} from {db}. Stopping function.")
                sys.exit("Terminating the program due to zero fetched rows.")  # Terminate the program

            logging.info(f"Successfully fetched {num_rows} rows for {search_str} from {db}.")

            # Log details of fetched data for debugging
            for row in rows:
                ncbiorgname = row.get('ncbiOrgName', 'N/A')
                gid = row.get('gid', 'N/A')
                gtdb_rep = row.get('isGtdbSpeciesRep', 'N/A')
                ncbi_type = row.get('isGtdbSpeciesRep', 'N/A')
                #logging.info(f"Search string: {search_str}, Fetched row details: NCBI organism: {ncbiorgname}, GID: {gid}, GTDB representative: {gtdb_rep}, NCBI type strain: {ncbi_type}")
            return rows
        else:
            logging.warning(f"Failed to get data for {search_str} from {db}. HTTP Status Code: {response.status_code}")
            return []
    except Exception as e:
        logging.error(f"An error occurred while fetching data: {e}")
        sys.exit(f"Terminating the program due to an error: {e}")  # Terminate the program



def filter_exact_match(rows: list, search_str: str, db: str) -> list:
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

    if len(filtered_rows) != 1:
        logging.error(f"Filtered rows count is not 1. Stopping the program.")
        sys.exit(1)  # You can replace this with a raise Exception("Filtered rows count is not 1.") if you prefer


def filter_data_by_exact_match(data: Dict[str, Dict[str, Any]], db: Any) -> Dict[str, Dict[str, Any]]:
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
        filtered_rows = filter_exact_match(species_info['rows'], f"s__{species}", db)
        filtered_data[species] = {
            'rows': filtered_rows,
            'tax_id': species_info.get('tax_id', 'N/A')
        }

    return filtered_data
