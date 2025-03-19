"""
Data utility functions for Nanometa Live.

This module provides utility functions for data handling and processing
used by the application.
"""

import os
import sys
import logging
import json
import requests
import csv
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple, Union


def read_species_from_file(filename: str) -> Optional[List[str]]:
    """
    Read a list of species from a file.

    Args:
        filename: Path to the file containing species names

    Returns:
        List of species names or None if file cannot be read
    """
    try:
        with open(filename, "r") as f:
            species_list = [line.strip() for line in f if line.strip()]

        if species_list:
            logging.info(f"Read {len(species_list)} species from {filename}")
        else:
            logging.warning(f"No species found in {filename}")

        return species_list

    except FileNotFoundError:
        logging.error(f"File not found: {filename}")
        return None
    except PermissionError:
        logging.error(f"Permission denied: {filename}")
        return None
    except Exception as e:
        logging.error(f"Error reading species file {filename}: {e}")
        return None


def read_species_from_config(config: Dict[str, Any]) -> List[str]:
    """
    Extract species list from configuration dictionary.

    Args:
        config: Configuration dictionary

    Returns:
        List of species names
    """
    species_list = []
    raw_species = config.get("species_of_interest", [])

    for species_entry in raw_species:
        species_name = species_entry.get("name", "")
        if species_name:
            species_list.append(species_name)

    if species_list:
        logging.info(f"Extracted {len(species_list)} species from configuration")
    else:
        logging.warning("No species found in configuration")

    return species_list


def parse_kraken_report(report_file: str) -> pd.DataFrame:
    """
    Parse a Kraken report file into a pandas DataFrame.

    Args:
        report_file: Path to the Kraken report file

    Returns:
        DataFrame with parsed report data
    """
    try:
        df = pd.read_csv(
            report_file,
            sep="\t",
            header=None,
            names=["%", "cumul_reads", "reads", "rank", "taxid", "name"],
        )

        logging.info(f"Parsed Kraken report {report_file} with {len(df)} entries")
        return df

    except Exception as e:
        logging.error(f"Error parsing Kraken report {report_file}: {e}")
        # Return empty DataFrame with correct columns
        return pd.DataFrame(
            columns=["%", "cumul_reads", "reads", "rank", "taxid", "name"]
        )


def parse_kraken_output(kraken_file: str) -> Dict[str, int]:
    """
    Parse a Kraken output file to extract read counts by taxid.

    Args:
        kraken_file: Path to the Kraken output file

    Returns:
        Dictionary mapping taxids to read counts
    """
    taxid_counts = {}

    try:
        with open(kraken_file, "r") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 3:
                    continue

                # Extract classification
                classification = parts[2]
                taxid = classification

                # Handle format variations
                if classification.startswith("taxid "):
                    taxid = classification.split(" ")[1].strip()

                # Count reads
                try:
                    taxid = int(taxid)
                    if taxid in taxid_counts:
                        taxid_counts[taxid] += 1
                    else:
                        taxid_counts[taxid] = 1
                except ValueError:
                    # Skip non-integer taxids
                    continue

        logging.info(
            f"Parsed Kraken output {kraken_file} with {len(taxid_counts)} unique taxids"
        )
        return taxid_counts

    except Exception as e:
        logging.error(f"Error parsing Kraken output {kraken_file}: {e}")
        return {}


def parse_fastq_file(fastq_file: str) -> Tuple[int, int]:
    """
    Parse a FASTQ file to extract basic statistics.

    Args:
        fastq_file: Path to the FASTQ file (can be gzipped)

    Returns:
        Tuple of (read_count, total_base_pairs)
    """
    try:
        read_count = 0
        total_bp = 0

        # Open file based on extension
        if fastq_file.endswith(".gz"):
            import gzip

            f = gzip.open(fastq_file, "rt")
        else:
            f = open(fastq_file, "r")

        # Process file
        line_count = 0
        for line in f:
            line_count += 1
            if line_count % 4 == 1:  # Header line
                read_count += 1
            elif line_count % 4 == 2:  # Sequence line
                total_bp += len(line.strip())

        f.close()

        logging.info(f"Parsed {fastq_file}: {read_count} reads, {total_bp} bp")
        return read_count, total_bp

    except Exception as e:
        logging.error(f"Error parsing FASTQ file {fastq_file}: {e}")
        return 0, 0


def parse_fastp_report(report_file: str) -> Dict[str, int]:
    """
    Parse a FastP JSON report file.

    Args:
        report_file: Path to the FastP JSON report file

    Returns:
        Dictionary with filtering statistics
    """
    try:
        with open(report_file, "r") as f:
            report_data = json.load(f)

        # Extract filtering results
        filtering_result = report_data.get("filtering_result", {})
        stats = {
            "passed_filter_reads": filtering_result.get("passed_filter_reads", 0),
            "low_quality_reads": filtering_result.get("low_quality_reads", 0),
            "too_many_N_reads": filtering_result.get("too_many_N_reads", 0),
            "too_short_reads": filtering_result.get("too_short_reads", 0),
        }

        logging.info(f"Parsed FastP report {report_file}")
        return stats

    except Exception as e:
        logging.error(f"Error parsing FastP report {report_file}: {e}")
        return {
            "passed_filter_reads": 0,
            "low_quality_reads": 0,
            "too_many_N_reads": 0,
            "too_short_reads": 0,
        }


def parse_blast_results(blast_file: str) -> Tuple[int, int]:
    """
    Parse BLAST results to count validated reads.

    Args:
        blast_file: Path to BLAST results file

    Returns:
        Tuple of (unique_reads, total_alignments)
    """
    try:
        # Read BLAST output
        df = pd.read_csv(
            blast_file,
            sep="\t",
            header=None,
            names=[
                "qseqid",
                "sseqid",
                "pident",
                "length",
                "mismatch",
                "gapopen",
                "qstart",
                "qend",
                "sstart",
                "send",
                "evalue",
                "bitscore",
            ],
        )

        # Count unique reads and total alignments
        unique_reads = df["qseqid"].nunique()
        total_alignments = len(df)

        logging.info(
            f"Parsed BLAST results {blast_file}: {unique_reads} unique reads, {total_alignments} alignments"
        )
        return unique_reads, total_alignments

    except Exception as e:
        logging.error(f"Error parsing BLAST results {blast_file}: {e}")
        return 0, 0

def test_gtdb_api_directly(species_name):
    """Direct test of GTDB API"""
    import requests
    import json

    formatted_name = f"s__{species_name.replace(' ', '_')}"
    logging.info(f"Direct API test for: {formatted_name}")

    url = "https://gtdb-api.ecogenomic.org/search/gtdb"
    params = {
        "search": formatted_name,
        "page": 1,
        "itemsPerPage": 10,
        "searchField": "gtdb_tax"
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        logging.info(f"API Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            logging.info(f"Raw API response: {json.dumps(data)[:200]}...")
            return data
        else:
            logging.error(f"API error: {response.text}")
            return None
    except Exception as e:
        logging.exception(f"API request failed: {e}")
        return None

def fetch_species_data(search_str: str, db: str = "gtdb") -> List[Dict[str, Any]]:
    """Fetch species data from GTDB API."""
    if not search_str.startswith("s__"):
        formatted_search = f"s__{search_str.replace(' ', '_')}"
        logging.info(f"Reformatting search: '{search_str}' → '{formatted_search}'")
        search_str = formatted_search

    base_url = "https://gtdb-api.ecogenomic.org/search/gtdb"
    params = {
        "search": search_str,
        "page": 1,
        "itemsPerPage": 1000,
        "searchField": f"{db}_tax",
        "gtdbSpeciesRepOnly": True if db == "gtdb" else False,
        "ncbiTypeMaterialOnly": True if db == "ncbi" else False,
    }

    logging.info(f"API URL: {base_url}")
    logging.info(f"API params: {params}")

    try:
        response = requests.get(
            base_url, params=params, headers={"accept": "application/json"}, timeout=30
        )

        logging.info(f"API status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            logging.info(f"API response keys: {list(result.keys() if result else [])}")
            rows = result.get("rows", [])

            if rows:
                logging.info(f"Found {len(rows)} results")
                logging.info(f"Sample row: {rows[0]}" if rows else "No rows")
            else:
                # Try alternate form with underscores instead of spaces
                alt_search = search_str.replace(' ', '_')
                logging.info(f"No results, trying alternate form: {alt_search}")
                params["search"] = alt_search
                alt_response = requests.get(base_url, params=params, headers={"accept": "application/json"})
                if alt_response.status_code == 200:
                    alt_result = alt_response.json()
                    rows = alt_result.get("rows", [])
                    logging.info(f"Alternate search found {len(rows)} results")

            return rows
        else:
            logging.error(f"API request failed: {response.text}")
            return []
    except Exception as e:
        logging.exception(f"API exception: {e}")
        return []


def create_species_taxid_map(
    species_list: List[str], kraken_report: str
) -> Dict[str, str]:
    """
    Create a mapping from species names to taxonomy IDs.

    Args:
        species_list: List of species names
        kraken_report: Path to a Kraken report file

    Returns:
        Dictionary mapping species names to taxonomy IDs
    """
    species_taxid_map = {}

    try:
        # Parse the Kraken report
        df = parse_kraken_report(kraken_report)

        # Extract species entries
        species_entries = df[df["rank"] == "S"].copy()

        # Clean up names
        species_entries["clean_name"] = species_entries["name"].str.strip()

        # Map species names to taxids
        for species in species_list:
            matches = species_entries[
                species_entries["clean_name"].str.endswith(species)
            ]

            if not matches.empty:
                # Take the first match
                taxid = matches.iloc[0]["taxid"]
                species_taxid_map[species] = taxid
                logging.info(f"Mapped species {species} to taxid {taxid}")
            else:
                logging.warning(f"No taxid found for species {species}")

        return species_taxid_map

    except Exception as e:
        logging.error(f"Error creating species-taxid map: {e}")
        return {}


def extract_classified_reads(kraken_report: str) -> Tuple[int, int, float, float]:
    """
    Extract classification statistics from a Kraken report.

    Args:
        kraken_report: Path to a Kraken report file

    Returns:
        Tuple of (classified_reads, unclassified_reads, percent_classified, percent_unclassified)
    """
    try:
        # Parse the Kraken report
        df = parse_kraken_report(kraken_report)

        # Extract unclassified reads (first row, taxid 0)
        unclassified_row = df[df["taxid"] == 0]

        if unclassified_row.empty:
            unclassified_reads = 0
            percent_unclassified = 0.0
        else:
            unclassified_reads = int(unclassified_row.iloc[0]["reads"])
            percent_unclassified = float(unclassified_row.iloc[0]["%"])

        # Get total reads from cumulative reads
        root_row = df[df["taxid"] == 1]

        if root_row.empty:
            # If no root row, use sum of all reads
            total_reads = unclassified_reads + df[df["taxid"] != 0]["reads"].sum()
        else:
            # Use root row cumulative reads
            total_reads = int(root_row.iloc[0]["cumul_reads"]) + unclassified_reads

        # Calculate classified reads
        classified_reads = total_reads - unclassified_reads

        # Calculate percentages
        if total_reads > 0:
            percent_classified = 100.0 - percent_unclassified
        else:
            percent_classified = 0.0

        logging.info(
            f"Extracted classification stats from {kraken_report}: {classified_reads} classified ({percent_classified:.1f}%), {unclassified_reads} unclassified ({percent_unclassified:.1f}%)"
        )
        return (
            classified_reads,
            unclassified_reads,
            percent_classified,
            percent_unclassified,
        )

    except Exception as e:
        logging.error(
            f"Error extracting classification stats from {kraken_report}: {e}"
        )
        return 0, 0, 0.0, 0.0
