"""
BLAST utility functions for Nanometa Live.

This module provides utility functions for working with BLAST databases
and validation in the Nanometa Live application.
"""

import os
import logging
import shutil
import subprocess
from typing import Dict, Any, List, Optional, Union


def build_blast_databases(
    workdir: str, missing_databases: Optional[List[str]] = None
) -> bool:
    """
    Build BLAST databases for reference genomes.

    Args:
        workdir: Working directory containing genome files
        missing_databases: List of missing taxonomy IDs to build (or None for all)

    Returns:
        True if successful, False otherwise
    """
    try:
        input_folder = os.path.join(workdir, "genomes")
        blast_db_folder = os.path.join(workdir, "blast")

        # Check input folder
        if not os.path.exists(input_folder):
            logging.error(f"Input folder {input_folder} does not exist")
            return False

        # Create output folder if needed
        if not os.path.exists(blast_db_folder):
            os.makedirs(blast_db_folder, exist_ok=True)
            logging.info(f"Created BLAST database folder at {blast_db_folder}")

        # Check available disk space before building
        try:
            usage = shutil.disk_usage(blast_db_folder)
            free_gb = usage.free / (1024**3)
            if free_gb < 2.0:
                logging.warning(
                    f"Low disk space: {free_gb:.1f} GB free in {blast_db_folder}. "
                    "Minimum 2 GB recommended for BLAST DB builds."
                )
        except OSError as e:
            logging.debug(f"Could not check disk space: {e}")

        # Find files to process
        files_to_process = os.listdir(input_folder)

        if not files_to_process:
            logging.warning(f"No files found in {input_folder}")
            return False

        # Skip if no missing databases
        if missing_databases is not None and not missing_databases:
            logging.info("No missing databases to build")
            return True

        logging.info(f"Found {len(files_to_process)} files to process")

        # Process each file
        for file in files_to_process:
            # Extract taxid from filename
            taxid = os.path.splitext(file)[0]

            # Skip if not in missing databases
            if missing_databases and taxid not in missing_databases:
                continue

            file_path = os.path.join(input_folder, file)
            database_name = os.path.join(blast_db_folder, file)

            # Build BLAST database
            logging.info(f"Building BLAST database for {file}")
            command = [
                "makeblastdb",
                "-in",
                file_path,
                "-dbtype",
                "nucl",
                "-out",
                database_name,
            ]

            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                timeout=300,
            )

            if result.returncode != 0:
                logging.error(
                    f"Failed to build BLAST database for {file}: {result.stderr.decode()}"
                )
                return False

        logging.info("BLAST databases built successfully")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {e.cmd}. Error: {e.stderr.decode()}")
        return False
    except Exception as e:
        logging.error(f"Error building BLAST databases: {e}")
        return False


def check_blast_dbs_exist(
    species_to_taxid: Dict[str, Union[str, int]], data_dir: str
) -> List[str]:
    """
    Check which BLAST databases are missing.

    Args:
        species_to_taxid: Mapping from species names to taxonomy IDs
        data_dir: Data directory containing BLAST databases

    Returns:
        List of missing taxonomy IDs
    """
    blast_dir = os.path.join(data_dir, "blast")
    missing_dbs = []

    try:
        # Create directory if it doesn't exist
        if not os.path.exists(blast_dir):
            os.makedirs(blast_dir, exist_ok=True)
            logging.info(f"Created BLAST database directory at {blast_dir}")

        # Check for each species
        for species, taxid in species_to_taxid.items():
            taxid_str = str(taxid)
            blast_db_file = os.path.join(blast_dir, f"{taxid_str}.fasta.nhr")

            if not os.path.exists(blast_db_file):
                logging.info(
                    f"BLAST database missing for {species} (taxid: {taxid_str})"
                )
                missing_dbs.append(taxid_str)

        if missing_dbs:
            logging.warning(
                f"Missing BLAST databases for {len(missing_dbs)} taxa: {', '.join(missing_dbs)}"
            )
        else:
            logging.info("All BLAST databases exist")

        return missing_dbs

    except Exception as e:
        logging.error(f"Error checking BLAST databases: {e}")
        return list(str(taxid) for _, taxid in species_to_taxid.items())


def run_blast_validation(
    query_file: str,
    db_file: str,
    output_file: str,
    percent_identity: float = 90.0,
    e_value: float = 0.01,
    cores: int = 1,
) -> bool:
    """
    Run BLAST validation on a set of reads.

    Args:
        query_file: Path to query FASTA file
        db_file: Path to BLAST database (without extension)
        output_file: Path to output file
        percent_identity: Minimum percent identity
        e_value: Maximum E-value
        cores: Number of CPU cores to use

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if query file exists
        if not os.path.exists(query_file):
            logging.error(f"Query file {query_file} does not exist")
            return False

        # Check if database exists
        db_check_file = f"{db_file}.nsq"
        if not os.path.exists(db_check_file):
            logging.error(f"BLAST database {db_file} does not exist")
            return False

        # Create output directory if needed
        output_dir = os.path.dirname(output_file)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # Run BLAST
        logging.info(f"Running BLAST validation: {query_file} against {db_file}")
        command = [
            "blastn",
            "-db",
            db_file,
            "-query",
            query_file,
            "-out",
            output_file,
            "-outfmt",
            "6",
            "-perc_identity",
            str(percent_identity),
            "-evalue",
            str(e_value),
            "-num_threads",
            str(cores),
        ]

        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            timeout=1800,
        )

        if result.returncode != 0:
            logging.error(f"BLAST validation failed: {result.stderr.decode()}")
            return False

        logging.info(f"BLAST validation completed successfully: {output_file}")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"BLAST command failed: {e.cmd}. Error: {e.stderr.decode()}")
        return False
    except Exception as e:
        logging.error(f"Error running BLAST validation: {e}")
        return False


def count_validated_reads(blast_result_file: str) -> int:
    """
    Count unique validated reads from a BLAST result file.

    Args:
        blast_result_file: Path to BLAST result file

    Returns:
        Number of unique validated reads
    """
    try:
        if not os.path.exists(blast_result_file):
            logging.warning(f"BLAST result file {blast_result_file} does not exist")
            return 0

        # Empty file
        if os.path.getsize(blast_result_file) == 0:
            return 0

        # Read unique query ids
        unique_reads = set()
        with open(blast_result_file, "r") as f:
            for line in f:
                if line.strip():
                    parts = line.strip().split("\t")
                    if parts:
                        unique_reads.add(parts[0])

        count = len(unique_reads)
        logging.info(f"Counted {count} validated reads in {blast_result_file}")
        return count

    except Exception as e:
        logging.error(f"Error counting validated reads: {e}")
        return 0


def get_blast_validation_summary(
    blast_dir: str, species_to_taxid: Dict[str, Union[str, int]]
) -> Dict[str, Dict[str, Any]]:
    """
    Generate a summary of BLAST validation results.

    Args:
        blast_dir: Directory containing BLAST result files
        species_to_taxid: Mapping from species names to taxonomy IDs

    Returns:
        Dictionary with validation statistics per species
    """
    results = {}

    try:
        # Check if directory exists
        if not os.path.exists(blast_dir):
            logging.warning(f"BLAST results directory {blast_dir} does not exist")
            return {}

        # Invert mapping for looking up species by taxid
        taxid_to_species = {
            str(taxid): species for species, taxid in species_to_taxid.items()
        }

        # Process each result file
        for taxid, species in taxid_to_species.items():
            result_file = os.path.join(blast_dir, f"{taxid}.txt")

            if os.path.exists(result_file):
                validated_reads = count_validated_reads(result_file)

                results[species] = {"taxid": taxid, "validated_reads": validated_reads}
            else:
                results[species] = {"taxid": taxid, "validated_reads": 0}

        return results

    except Exception as e:
        logging.error(f"Error generating BLAST validation summary: {e}")
        return {}
