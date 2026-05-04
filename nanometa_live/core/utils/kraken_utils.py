"""
Kraken utilities for Nanometa Live.

This module provides utility functions for working with Kraken2, including:
- Downloading and managing Kraken2 databases
- Parsing Kraken2 reports and output files
- Extracting taxonomic information from Kraken2 results
"""

import os
import logging
import subprocess
import tarfile
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import requests


def download_kraken_database(
    db_info: Dict[str, str], dest_dir: str
) -> Tuple[bool, str]:
    """
    Download a Kraken2 database from the specified URL.

    Args:
        db_info: Dictionary containing database information (name, url, etc.)
        dest_dir: Directory to download the database to

    Returns:
        Tuple of (success, message)
    """
    db_name = db_info.get("name", "unknown")
    db_url = db_info.get("database_url")

    if not db_url:
        return False, f"No download URL provided for database {db_name}"

    try:
        # Create destination directory if it doesn't exist
        os.makedirs(dest_dir, exist_ok=True)

        # Download to a temporary file first
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as temp_file:
            temp_path = temp_file.name
            logging.info(f"Downloading Kraken2 database {db_name} to {temp_path}")

            # Stream the download to avoid loading the whole file into memory
            with requests.get(db_url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))

                # Use a small chunk size to show progress
                chunk_size = 8192
                downloaded = 0

                for chunk in response.iter_content(chunk_size=chunk_size):
                    temp_file.write(chunk)
                    downloaded += len(chunk)

                    # Log progress
                    if total_size > 0:
                        percent = downloaded / total_size * 100
                        if downloaded % (20 * chunk_size) == 0:
                            logging.info(
                                f"Downloaded {downloaded / (1024*1024):.1f} MB ({percent:.1f}%)"
                            )

        # Extract the database
        extract_dir = os.path.join(dest_dir, db_name)
        os.makedirs(extract_dir, exist_ok=True)

        logging.info(f"Extracting Kraken2 database to {extract_dir}")
        with tarfile.open(temp_path, "r:gz") as tar:
            tar.extractall(path=extract_dir)

        # Remove the temporary file
        os.unlink(temp_path)

        # Validate the extracted database
        if verify_kraken_db(extract_dir):
            return (
                True,
                f"Successfully downloaded and extracted {db_name} to {extract_dir}",
            )
        else:
            return (
                False,
                f"Database extraction succeeded but verification failed for {db_name}",
            )

    except requests.exceptions.RequestException as e:
        return False, f"Error downloading database: {str(e)}"
    except tarfile.TarError as e:
        return False, f"Error extracting database: {str(e)}"
    except (FileNotFoundError, PermissionError, OSError) as e:
        return False, f"I/O error preparing database: {str(e)}"


def verify_kraken_db(db_path: str) -> bool:
    """
    Verify that a Kraken2 database is valid.

    Args:
        db_path: Path to the Kraken2 database

    Returns:
        True if the database is valid, False otherwise
    """
    # Check for key files that should be present in any Kraken database
    required_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]

    for file in required_files:
        if not os.path.isfile(os.path.join(db_path, file)):
            logging.warning(f"Kraken2 database missing required file: {file}")
            return False

    return True


def inspect_kraken_db(db_path: str, output_path: str = None) -> Tuple[bool, str]:
    """
    Run kraken2-inspect on a database to generate a report of its contents.

    Args:
        db_path: Path to the Kraken2 database
        output_path: Path to save the inspection report to (optional)

    Returns:
        Tuple of (success, message or output)
    """
    try:
        if not verify_kraken_db(db_path):
            return False, f"Invalid Kraken2 database at {db_path}"

        # Build the command
        cmd = ["kraken2-inspect", "--db", db_path]

        # If output path is provided, redirect output to a file
        if output_path:
            with open(output_path, "w") as f:
                result = subprocess.run(
                    cmd, stdout=f, stderr=subprocess.PIPE, check=True, text=True,
                    timeout=300,
                )
            return True, f"Inspection report saved to {output_path}"
        else:
            # Otherwise, capture and return the output
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
                timeout=300,
            )
            return True, result.stdout

    except subprocess.CalledProcessError as e:
        return False, f"Error running kraken2-inspect: {e.stderr}"
    except subprocess.TimeoutExpired as e:
        return False, f"kraken2-inspect timed out after {e.timeout}s"
    except (FileNotFoundError, PermissionError, OSError) as e:
        return False, f"Cannot launch kraken2-inspect: {str(e)}"


def ensure_inspect_file(db_path: str) -> Optional[str]:
    """
    Generate the inspect.txt file for a Kraken2 database if it does not exist.

    This ensures the inspect file is available for offline taxonomy index
    building without requiring network access.

    Args:
        db_path: Path to the Kraken2 database directory.

    Returns:
        Path to the inspect.txt file, or None if generation failed.
    """
    inspect_path = os.path.join(db_path, "inspect.txt")
    if os.path.exists(inspect_path):
        return inspect_path

    if not verify_kraken_db(db_path):
        logging.warning(f"Cannot generate inspect file: invalid database at {db_path}")
        return None

    if not shutil.which("kraken2-inspect"):
        logging.warning("kraken2-inspect not found in PATH, cannot generate inspect file")
        return None

    success, msg = inspect_kraken_db(db_path, inspect_path)
    if success:
        logging.info(f"Generated inspect file at {inspect_path}")
        return inspect_path
    else:
        logging.warning(f"Failed to generate inspect file: {msg}")
        return None


def parse_kraken_report(report_path: str) -> pd.DataFrame:
    """
    Parse a Kraken2 report file into a DataFrame.

    Args:
        report_path: Path to the Kraken2 report file

    Returns:
        DataFrame containing the parsed report
    """
    # Define column names for Kraken2 report format
    columns = ["percent", "cumulative_reads", "reads", "rank_code", "taxid", "name"]

    # Read the report file
    df = pd.read_csv(report_path, sep="\t", header=None, names=columns)

    # Clean up the name column (remove leading spaces)
    df["name"] = df["name"].str.strip()

    return df


def get_species_reads(
    report_df: pd.DataFrame, species_taxids: List[str]
) -> Dict[str, int]:
    """
    Extract read counts for specific species from a Kraken report DataFrame.

    Args:
        report_df: DataFrame containing parsed Kraken report
        species_taxids: List of taxonomic IDs to extract

    Returns:
        Dictionary mapping taxonomic IDs to read counts
    """
    result = {}

    # Filter for the specified taxids
    for taxid in species_taxids:
        matches = report_df[report_df["taxid"] == taxid]
        if not matches.empty:
            result[taxid] = int(matches.iloc[0]["reads"])
        else:
            result[taxid] = 0

    return result


def get_top_taxa(
    report_df: pd.DataFrame, rank_code: str = "S", n: int = 10
) -> pd.DataFrame:
    """
    Get the top taxa at a specific rank from a Kraken report DataFrame.

    Args:
        report_df: DataFrame containing parsed Kraken report
        rank_code: Rank code to filter by (S=species, G=genus, etc.)
        n: Number of top taxa to return

    Returns:
        DataFrame containing the top taxa
    """
    # Filter by rank code
    filtered = report_df[report_df["rank_code"] == rank_code]

    # Sort by read count (descending)
    sorted_df = filtered.sort_values("reads", ascending=False)

    # Return the top n
    return sorted_df.head(n)


def get_taxonomy_tree(
    report_df: pd.DataFrame, include_ranks: List[str] = None
) -> Dict[str, Any]:
    """
    Convert a Kraken report DataFrame into a hierarchical taxonomy tree.

    Args:
        report_df: DataFrame containing parsed Kraken report
        include_ranks: List of rank codes to include (None for all)

    Returns:
        Dictionary representing the taxonomy tree
    """
    # Initialize tree with root node
    tree = {"name": "root", "children": [], "reads": 0, "taxid": "1"}

    # Filter by rank if specified
    if include_ranks:
        filtered_df = report_df[report_df["rank_code"].isin(include_ranks)]
    else:
        filtered_df = report_df

    # Function to add a node to the tree
    def add_node(parent, node_data, level):
        if level == 0:
            parent["children"].append(node_data)
            return

        # Find the last child at each level
        if not parent["children"]:
            # No children yet, create a placeholder
            parent["children"].append(
                {"name": "unclassified", "children": [], "reads": 0, "taxid": "0"}
            )

        # Add to the last child
        add_node(parent["children"][-1], node_data, level - 1)

    # Add each row to the tree - pre-extract data for faster iteration
    names = filtered_df["name"].tolist()
    taxids = filtered_df["taxid"].astype(str).tolist()
    reads_vals = filtered_df["reads"].astype(int).tolist()

    for name, taxid, reads in zip(names, taxids, reads_vals):
        # Determine the level from the name (count leading spaces and divide by 2)
        level = (len(name) - len(name.lstrip())) // 2

        # Create node data
        node_data = {
            "name": name.strip(),
            "taxid": taxid,
            "reads": reads,
            "children": [],
        }

        # Add to tree
        add_node(tree, node_data, level)

    return tree


def extract_classification_stats(report_df: pd.DataFrame) -> Dict[str, int]:
    """
    Extract basic classification statistics from a Kraken report DataFrame.

    Args:
        report_df: DataFrame containing parsed Kraken report

    Returns:
        Dictionary with classification statistics
    """
    # First row should be unclassified
    unclassified = 0
    total = 0

    # Find unclassified row (usually has taxid=0)
    unclassified_row = report_df[report_df["taxid"] == 0]
    if not unclassified_row.empty:
        unclassified = int(unclassified_row.iloc[0]["reads"])

    # Calculate total reads
    total = int(report_df["reads"].sum())

    # Calculate classified reads
    classified = total - unclassified

    return {
        "total_reads": total,
        "classified_reads": classified,
        "unclassified_reads": unclassified,
        "classification_rate": classified / total if total > 0 else 0,
    }
