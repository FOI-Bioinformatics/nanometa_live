import logging
import pandas as pd
from typing import Any, List, Dict, Union, NoReturn, List

def update_results_with_taxid_dict(results: dict, species_taxid_dict: dict) -> dict:
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
            logging.info(f"Found tax ID {tax_id} in kraken2 inspect file for species {species_name}. Updating results.")
            results[species_name]['tax_id'] = tax_id
        else:
            logging.warning(f"Tax ID not found for species {species_name}. Setting it to 'N/A'.")
            results[species_name]['tax_id'] = 'N/A'  # If the tax ID is not found, set it to 'N/A'

    logging.info("Finished updating results with taxonomic IDs.")

    return results

def create_row_dict(species: str, species_info: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        ('gid', 'GID'),
        ('accession', 'Accession'),
        ('ncbiOrgName', 'NCBI_OrgName'),
        ('ncbiTaxonomy', 'NCBI_Taxonomy'),
        ('gtdbTaxonomy', 'GTDB_Taxonomy'),
        ('isGtdbSpeciesRep', 'Is_GTDB_Species_Rep'),
        ('isNcbiTypeMaterial', 'Is_NCBI_Type_Material')
    ]
    row_dict = {
        'Species': species,
        'Tax_ID': species_info.get('tax_id', 'N/A'),
        'SearchQuery': f"s__{species}"
    }
    row_dict.update({new_key: row.get(old_key, 'N/A') for old_key, new_key in keys})
    return row_dict

def parse_to_table_with_taxid(filtered_data: dict) -> pd.DataFrame:
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
        for row in species_info['rows']:
            logging.debug(f"Parsing row for species {species}")

            # Create a row dictionary.
            row_dict = create_row_dict(species, species_info, row)

            # Append the row dictionary to parsed_data.
            parsed_data.append(row_dict)

        logging.debug(f"Finished parsing information for species: {species}")

    # Create a DataFrame from the parsed data.
    parsed_df = pd.DataFrame(parsed_data)

    logging.info(f"Finished parsing filtered data into a DataFrame with {len(parsed_df)} rows.")

    return parsed_df


