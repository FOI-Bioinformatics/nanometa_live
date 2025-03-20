"""
Backend manager for Nanometa Live.

This module manages the backend processes for the application, including:
- Starting/stopping the Snakemake workflow
- Monitoring the processing status
- Checking files and directories
"""

import os
import sys
import time
import logging
import threading
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import pandas as pd
import subprocess
import zipfile, shutil

from nanometa_live.core.utils.file_utils import check_command_exists
from nanometa_live.core.workflow.snakemake_manager import SnakemakeManager
from nanometa_live.core.utils.database_utils import download_and_prepare_kraken_database
from nanometa_live.core.utils.data_utils import fetch_species_data, test_gtdb_api_directly


def _adapt_boolean_for_snakemake(config):
    """
    Convert boolean parameters to the format expected by the Snakefile.

    Args:
        config: Configuration dictionary to adapt

    Returns:
        Modified configuration with adapted boolean values
    """
    # Create a copy to prevent modifying the original
    adapted_config = dict(config)

    # Convert kraken_memory_mapping to the expected flag format for CLI
    if "kraken_memory_mapping" in adapted_config:
        adapted_config["kraken_memory_mapping"] = "--memory-mapping" if adapted_config["kraken_memory_mapping"] else ""

    # Convert remove_temp_files to "yes"/"no" format for Snakemake onsuccess rule
    if "remove_temp_files" in adapted_config:
        adapted_config["remove_temp_files"] = "yes" if adapted_config["remove_temp_files"] else "no"

    return adapted_config


class BackendManager:
    """Manages backend processes for Nanometa Live."""

    def __init__(self, data_dir: str):
        """
        Initialize the BackendManager.

        Args:
            data_dir: Directory where application data is stored
        """
        self.data_dir = data_dir
        self.log_dir = os.path.join(data_dir, "logs")
        self.snakemake_manager = SnakemakeManager(data_dir)
        self.config = None
        self.status_thread = None
        self.status = {
            "running": False,
            "pipeline_status": "idle",
            "files_processed": 0,
            "files_waiting": 0,
            "last_update": None,
            "errors": [],
        }

        # Create logs directory
        os.makedirs(self.log_dir, exist_ok=True)

    def setup_project(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Set up a project with the given configuration."""
        # Ensure we're working with a copy
        self.config = dict(config)

        # Validate required directories
        if not self.config.get("nanopore_output_directory"):
            return False, "Nanopore output directory is required"

        if not self.config.get("kraken_db"):
            return False, "Kraken database is required"

        # Ensure boolean parameters are strictly boolean
        if "kraken_memory_mapping" in self.config:
            self.config["kraken_memory_mapping"] = bool(self.config["kraken_memory_mapping"])

        if "blast_validation" in self.config:
            self.config["blast_validation"] = bool(self.config["blast_validation"])

        if "remove_temp_files" in self.config:
            self.config["remove_temp_files"] = bool(self.config["remove_temp_files"])

        # Create required directories
        main_dir = self.config.get("main_dir")
        if not main_dir:
            # Create a timestamped directory in the data directory
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            main_dir = os.path.join(self.data_dir, "data", f"analysis_{timestamp}")
            self.config["main_dir"] = main_dir

        os.makedirs(main_dir, exist_ok=True)

        # Create subdirectories
        for subdir in [
            "kraken_cumul", "qc_data", "fastp_reports", "validation_fastas",
            "blast_result_files", "kraken_results", "fastp_filtered", "reports",
        ]:
            os.makedirs(os.path.join(main_dir, subdir), exist_ok=True)

        # Adapt boolean values for Snakefile
        yaml_config = _adapt_boolean_for_snakemake(self.config)

        # Write configuration to project directory
        config_path = os.path.join(main_dir, "config.yaml")
        with open(config_path, "w") as f:
            import yaml
            yaml.safe_dump(yaml_config, f, default_flow_style=False, sort_keys=False)

        # Set up Snakemake workflow
        success, message = self.snakemake_manager.setup(config_path)
        if not success:
            return False, message

        return True, f"Project set up successfully in {main_dir}"

    def start(self) -> Tuple[bool, str]:
        """
        Start the backend processes.

        Returns:
            Tuple of (success, message)
        """
        if self.status.get("running"):
            return False, "Backend is already running"

        if not self.config:
            return False, "No configuration loaded"

        # Set up the project
        success, message = self.setup_project(self.config)
        if not success:
            return False, message

        # Start the Snakemake workflow
        cores = self.config.get("snakemake_cores", 1)
        success, message = self.snakemake_manager.start(cores=cores)
        if not success:
            return False, message

        # Mark as running
        self.status["running"] = True
        self.status["pipeline_status"] = "running"
        self.status["last_update"] = time.time()

        # Start status monitoring thread
        self.status_thread = threading.Thread(target=self._monitor_status, daemon=True)
        self.status_thread.start()

        return True, "Backend started successfully"

    def stop(self) -> Tuple[bool, str]:
        """
        Stop the backend processes.

        Returns:
            Tuple of (success, message)
        """
        if not self.status.get("running"):
            return False, "Backend is not running"

        # Stop the Snakemake workflow
        success, message = self.snakemake_manager.stop()
        if not success:
            return False, message

        # Mark as stopped
        self.status["running"] = False
        self.status["pipeline_status"] = "stopped"
        self.status["last_update"] = time.time()

        return True, "Backend stopped successfully"

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the backend.

        Returns:
            Dictionary with status information
        """
        # Update with Snakemake status
        snakemake_status = self.snakemake_manager.get_status()

        # Update pipeline status based on Snakemake status
        if snakemake_status.get("running"):
            self.status["pipeline_status"] = "running"
        elif len(snakemake_status.get("errors", [])) > 0:
            self.status["pipeline_status"] = "error"
            self.status["errors"].extend(snakemake_status.get("errors", []))
        elif self.status.get("running"):
            self.status["pipeline_status"] = "stopping"
        else:
            self.status["pipeline_status"] = "stopped"

        # If we're running, update the file counts
        if self.status.get("running") and self.config:
            self._update_file_counts()

        return self.status

    def _update_file_counts(self):
        """Update the file processing counts from the file system."""
        try:
            nanopore_dir = self.config.get("nanopore_output_directory", "")
            qc_file = os.path.join(
                self.config.get("main_dir", ""), "qc_data/cumul_qc.txt"
            )

            # Count files in nanopore directory
            waiting_files = 0
            if os.path.exists(nanopore_dir):
                waiting_files = len(
                    [
                        f
                        for f in os.listdir(nanopore_dir)
                        if f.endswith((".fastq", ".fastq.gz"))
                    ]
                )

            # Count processed files from QC data
            processed_files = 0
            if os.path.exists(qc_file):
                with open(qc_file, "r") as f:
                    processed_files = sum(1 for _ in f)

            # Update status
            self.status["files_waiting"] = waiting_files
            self.status["files_processed"] = processed_files

        except Exception as e:
            logging.error(f"Error updating file counts: {e}")

    def _monitor_status(self):
        """Monitor the status of the backend processes in a separate thread."""
        while self.status.get("running"):
            # Get Snakemake status
            snakemake_status = self.snakemake_manager.get_status()

            # Update status based on Snakemake status
            if (
                not snakemake_status.get("running")
                and len(snakemake_status.get("errors", [])) > 0
            ):
                self.status["pipeline_status"] = "error"
                self.status["errors"].extend(snakemake_status.get("errors", []))
                self.status["running"] = False

            # Update file counts
            self._update_file_counts()

            # Update last update time
            self.status["last_update"] = time.time()

            # Sleep for a bit
            time.sleep(5)

    def _update_progress(self, progress: int, message: str):
        """
        Update preparation progress.
        This is a helper method for callbacks.
        """
        # Calculate the actual progress value based on the stage
        if self.prep_status["progress"] < 30:
            # We're in the database preparation stage (0-30%)
            self.prep_status["progress"] = progress
        else:
            # We're in a later stage, adjust progress accordingly
            self.prep_status["progress"] = 30 + int(progress * 0.7)

        self.prep_status["message"] = message
        self.prep_status["last_update"] = time.time()

    def handle_external_kraken_database(self):
        """
        Check for and handle external Kraken2 database if specified in config.
        This method should be called from _run_data_preparation.
        """
        try:
            config = self.config

            # Check if an external Kraken2 database is specified
            external_db_key = (config.get("external_kraken2_db") or "").strip()
            external_db_info = config.get("external_kraken2_info", {})

            if external_db_key and external_db_key in external_db_info:
                self.prep_status["message"] = f"Checking external Kraken2 database: {external_db_key}"
                self.prep_status["progress"] = 10
                self.prep_status["last_update"] = time.time()

                # Prepare database folders
                kraken_db_folder = os.path.join(self.data_dir, "kraken2_databases")
                os.makedirs(kraken_db_folder, exist_ok=True)

                # Download and prepare the database
                success, message, db_path = download_and_prepare_kraken_database(
                    external_db_key,
                    external_db_info,
                    kraken_db_folder,
                    progress_callback=self._update_progress
                )

                if not success:
                    self.prep_status["errors"].append(message)
                    self.prep_status["message"] = f"Error: {message}"
                    self.prep_status["progress"] = 100
                    self.prep_status["running"] = False
                    self.prep_status["last_update"] = time.time()
                    return False

                # Update configuration with new database path
                if db_path:
                    # Get taxonomy from database info
                    db_details = external_db_info[external_db_key]
                    kraken_taxonomy = db_details.get("kraken_taxonomy", config.get("kraken_taxonomy", "gtdb"))

                    # Update config
                    config["kraken_db"] = os.path.abspath(db_path)
                    config["kraken_taxonomy"] = kraken_taxonomy
                    self.config = config

                    self.prep_status["message"] = f"Successfully prepared external Kraken2 database: {external_db_key}"
                    self.prep_status["progress"] = 30
                    self.prep_status["last_update"] = time.time()

                return True

            return True  # No external database specified, continue with preparation

        except Exception as e:
            error_msg = f"Error handling external Kraken2 database: {str(e)}"
            self.prep_status["errors"].append(error_msg)
            self.prep_status["message"] = f"Error: {error_msg}"
            self.prep_status["progress"] = 100
            self.prep_status["running"] = False
            self.prep_status["last_update"] = time.time()
            return False

    def prepare_data(self) -> Tuple[bool, str]:
        """
        Prepare data for analysis by:
        1. Checking for required external dependencies
        2. Extracting taxonomy IDs from Kraken database
        3. Downloading genome sequences for species of interest
        4. Building BLAST databases for validation

        Returns:
            Tuple of (success, message)
        """
        if not self.config:
            return False, "No configuration loaded"

        # Check for required external dependencies
        missing_deps = []
        if not check_command_exists("kraken2"):
            missing_deps.append("kraken2")
        if not check_command_exists("kraken2-inspect"):
            missing_deps.append("kraken2-inspect")
        if self.config.get("blast_validation", True):
            if not check_command_exists("makeblastdb"):
                missing_deps.append("makeblastdb")
            if not check_command_exists("blastn"):
                missing_deps.append("blastn")

        if missing_deps:
            missing_str = ", ".join(missing_deps)
            return False, f"Missing required dependencies: {missing_str}. Please install and ensure they are in your PATH."

        # Create a temporary progress file to track preparation progress
        self.prep_status = {
            "running": True,
            "progress": 0,
            "message": "Initializing data preparation...",
            "errors": [],
            "last_update": time.time()
        }

        # Start the preparation process in a background thread
        prep_thread = threading.Thread(target=self._run_data_preparation, daemon=True)
        prep_thread.start()

        return True, "Data preparation started"

    def get_preparation_status(self) -> Dict[str, Any]:
        """
        Get the current status of data preparation.

        Returns:
            Dictionary with preparation status information
        """
        if not hasattr(self, 'prep_status'):
            return {
                "running": False,
                "progress": 0,
                "message": "No preparation in progress",
                "errors": [],
                "last_update": None
            }
        return self.prep_status

    def _run_data_preparation(self):
        """Run data preparation in a background thread."""
        try:
            config = self.config

            # STEP 1: Validate inputs and dependencies
            kraken_db = config.get("kraken_db", "")
            main_dir = config.get("main_dir", "")
            species_list = [s.get("name", "") for s in config.get("species_of_interest", [])]

            # Validate Kraken database
            if not kraken_db:
                self.prep_status["running"] = False
                self.prep_status["errors"].append("Kraken database path not specified")
                self.prep_status["message"] = "Error: Kraken database path not specified"
                self.prep_status["progress"] = 100
                return

            if not os.path.exists(kraken_db):
                self.prep_status["running"] = False
                self.prep_status["errors"].append(f"Kraken database directory not found: {kraken_db}")
                self.prep_status["message"] = f"Error: Kraken database directory not found: {kraken_db}"
                self.prep_status["progress"] = 100
                return

            # Check if it's a valid Kraken database
            required_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]
            missing_files = [f for f in required_files if not os.path.exists(os.path.join(kraken_db, f))]

            if missing_files:
                self.prep_status["running"] = False
                missing_str = ", ".join(missing_files)
                self.prep_status["errors"].append(f"Invalid Kraken2 database: missing files {missing_str}")
                self.prep_status["message"] = f"Error: Invalid Kraken2 database: missing files {missing_str}"
                self.prep_status["progress"] = 100
                return

            # Validate species list
            if not species_list and not any(s.get("taxid") for s in config.get("species_of_interest", [])):
                self.prep_status["running"] = False
                self.prep_status["errors"].append("No species of interest defined")
                self.prep_status["message"] = "Error: No species of interest defined. Please add species in the Configuration tab."
                self.prep_status["progress"] = 100
                return

            # STEP 1.5: Check for external Kraken2 database
            if not self.handle_external_kraken_database():
                return  # Error occurred during database handling

            # STEP 2: Extract taxonomy IDs from Kraken database
            self.prep_status["message"] = "Extracting taxonomy IDs from Kraken database..."
            self.prep_status["progress"] = 10
            self.prep_status["last_update"] = time.time()

            # Create data directories
            data_dir = os.path.join(main_dir, "data-files")
            os.makedirs(data_dir, exist_ok=True)

            # Run kraken2-inspect to get taxonomy IDs
            inspect_file = os.path.join(data_dir, f"{os.path.basename(kraken_db)}-inspect.txt")

            if not os.path.exists(inspect_file):
                try:
                    self.prep_status["message"] = "Running kraken2-inspect..."
                    self.prep_status["progress"] = 20
                    self.prep_status["last_update"] = time.time()

                    cmd = ["kraken2-inspect", "--db", kraken_db]
                    with open(inspect_file, 'w') as f:
                        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True)
                except subprocess.CalledProcessError as e:
                    self.prep_status["running"] = False
                    self.prep_status["errors"].append(f"Error running kraken2-inspect: {e.stderr.decode() if e.stderr else str(e)}")
                    self.prep_status["message"] = f"Error running kraken2-inspect. Check if Kraken2 is properly installed."
                    self.prep_status["progress"] = 100
                    return

            # Parse the inspect file to extract taxonomy IDs
            self.prep_status["message"] = "Parsing taxonomy information..."
            self.prep_status["progress"] = 30
            self.prep_status["last_update"] = time.time()

            # Define taxonomic level mappings
            level_mappings = {
                'S': 'species',
                'G': 'genus',
                'F': 'family',
                'O': 'order',
                'C': 'class',
                'P': 'phylum',
                'D': 'superkingdom',
                'K': 'kingdom'
            }

            species_taxids = {}
            try:
                with open(inspect_file, 'r') as f:
                    for line in f:
                        parts = line.strip().split('\t')
                        if len(parts) >= 6:  # At least 6 columns expected
                            # Column format: %krakenuniq, cumul reads, reads, level_type, taxid, name
                            level_type = parts[3]
                            taxid = parts[4]
                            name = parts[5].strip()

                            # Only process species level entries - checking both abbreviated and full names
                            if level_type == 'S' or level_type == 'species' or level_mappings.get(level_type) == 'species':
                                # Check if any of our species match this name
                                for species in species_list:
                                    if species and species.lower() in name.lower():
                                        species_taxids[species] = taxid
            except Exception as e:
                self.prep_status["running"] = False
                self.prep_status["errors"].append(f"Error parsing inspect file: {e}")
                self.prep_status["message"] = f"Error parsing taxonomy data: {str(e)}"
                self.prep_status["progress"] = 100
                return

            # Update config with taxonomy IDs
            self.prep_status["message"] = "Updating configuration with taxonomy IDs..."
            self.prep_status["progress"] = 40
            self.prep_status["last_update"] = time.time()

            updated_species = []
            matched_species_count = 0

            for species in config.get("species_of_interest", []):
                name = species.get("name", "")
                taxid = species.get("taxid", "")

                # If taxid already provided, keep it
                if taxid:
                    updated_species.append(species)
                    matched_species_count += 1
                # Otherwise try to match by name
                elif name in species_taxids:
                    updated_species.append({
                        "name": name,
                        "taxid": species_taxids[name]
                    })
                    matched_species_count += 1
                else:
                    # Keep the original entry even if no match found
                    updated_species.append(species)

            # Check if we matched any species
            if matched_species_count == 0:
                self.prep_status["running"] = False
                self.prep_status["errors"].append("No species matched in the database. Check species names.")
                self.prep_status["message"] = "Error: No species matched in the database. Check species names."
                self.prep_status["progress"] = 100
                self.prep_status["last_update"] = time.time()
                return
            else:
                self.prep_status["message"] = f"Found taxonomy IDs for {matched_species_count} out of {len(config.get('species_of_interest', []))} species."
                self.prep_status["progress"] = 45
                self.prep_status["last_update"] = time.time()

            self.config["species_of_interest"] = updated_species

            # STEP 3: Prepare directories for genome data
            self.prep_status["message"] = "Setting up directories for genome data..."
            self.prep_status["progress"] = 45
            self.prep_status["last_update"] = time.time()

            # Create data directories
            data_dir = os.path.join(main_dir, "data-files")
            genomes_dir = os.path.join(data_dir, "genomes")
            os.makedirs(data_dir, exist_ok=True)
            os.makedirs(genomes_dir, exist_ok=True)

            # STEP 4: Check which genomes need to be downloaded
            self.prep_status["message"] = "Checking for missing genome files..."
            self.prep_status["progress"] = 50
            self.prep_status["last_update"] = time.time()

            # Create a dictionary mapping species names to taxonomy IDs
            # FIXED: Make sure to include all species with valid taxids, even newly found ones
            species_to_taxid = {}
            for species in self.config["species_of_interest"]:
                name = species.get("name", "")
                taxid = species.get("taxid", "")
                if name and taxid:
                    species_to_taxid[name] = taxid

            # Check which genomes are missing
            missing_species = []
            for species, taxid in species_to_taxid.items():
                genome_file = os.path.join(genomes_dir, f"{taxid}.fasta")
                if not os.path.exists(genome_file):
                    missing_species.append(species)

            # STEP 5: Download missing genomes using GTDB API
            # Modified: Always proceed to download section, but with proper handling for empty list
            self.prep_status["message"] = f"Found {len(missing_species)} missing genomes. Preparing to download..."
            self.prep_status["progress"] = 55
            self.prep_status["last_update"] = time.time()


            # STEP 5: Download missing genomes using GTDB API
            if missing_species:

                try:
                    # Initialize results dictionary
                    results = {}
                    kraken_taxonomy = config.get("kraken_taxonomy", "gtdb")

                    # Fetch data for each missing species from GTDB
                    for species in missing_species:
                        # Test API directly first - for diagnostic purposes
                        test_result = test_gtdb_api_directly(species)
                        if test_result:
                            logging.info(f"Direct API test successful for {species}")
                        else:
                            logging.error(f"Direct API test failed for {species}")

                        # Now use the fetch_species_data function
                        search_query = f"s__{species.replace(' ', '_')}"
                        logging.info(f"Querying GTDB API for: {search_query}")

                        species_data = fetch_species_data(search_query, kraken_taxonomy)

                        # Log diagnostics
                        logging.info(f"Species data type: {type(species_data)}")
                        logging.info(f"Species data length: {len(species_data) if species_data else 0}")

                        # Store results
                        if species_data:
                            results[species] = {"rows": species_data}
                            logging.info(f"Stored results for {species}")
                        else:
                            logging.warning(f"No data found for {species}")

                    # Update results with taxonomy IDs
                    for species_name in results.keys():
                        tax_id = species_to_taxid.get(species_name, None)
                        if tax_id is not None:
                            results[species_name]["tax_id"] = tax_id
                        else:
                            results[species_name]["tax_id"] = "N/A"

                    logging.info(f"Species list: {species_list}")
                    logging.info(f"API results: {results}")

                    # Filter results to include only exact matches
                    filtered_results = {}
                    for species, species_info in results.items():
                        if "rows" not in species_info:
                            continue

                        exact_matches = []
                        for row in species_info["rows"]:
                            # Get the taxonomy field based on the taxonomy database
                            if kraken_taxonomy == "gtdb":
                                taxonomy = row.get("gtdbTaxonomy", "")
                            else:  # ncbi
                                taxonomy = row.get("ncbiTaxonomy", "")

                            # Check for exact match
                            if taxonomy and (taxonomy.endswith(f"s__{species}") or taxonomy.endswith(f"s__{species.replace(' ', '_')}")):
                                exact_matches.append(row)

                        if exact_matches:
                            filtered_results[species] = {"rows": exact_matches, "tax_id": species_info.get("tax_id", "N/A")}

                    # Convert to DataFrame
                    parsed_data = []
                    logging.info(f"Starting taxonomy filtering on {len(results)} species")
                    for species, species_info in filtered_results.items():
                        for row in species_info["rows"]:
                            row_dict = {
                                "Species": species,
                                "Tax_ID": species_info.get("tax_id", "N/A"),
                                "SearchQuery": f"s__{species.replace(' ', '_')}",
                                "GID": row.get("gid", "N/A"),
                                "Accession": row.get("accession", "N/A"),
                                "NCBI_OrgName": row.get("ncbiOrgName", "N/A"),
                                "NCBI_Taxonomy": row.get("ncbiTaxonomy", "N/A"),
                                "GTDB_Taxonomy": row.get("gtdbTaxonomy", "N/A"),
                                "Is_GTDB_Species_Rep": row.get("isGtdbSpeciesRep", "N/A"),
                                "Is_NCBI_Type_Material": row.get("isNcbiTypeMaterial", "N/A"),
                            }
                            parsed_data.append(row_dict)

                    df = pd.DataFrame(parsed_data)
                    logging.info(f"Created DataFrame with {len(df)} rows")

                    # Extract accessions for download
                    if df is not None and not df.empty and "GID" in df.columns:
                        self.prep_status["message"] = "Preparing to download genomes from NCBI..."
                        self.prep_status["progress"] = 60
                        self.prep_status["last_update"] = time.time()

                        # Get accessions
                        accessions = df["GID"].tolist()
                        if accessions:
                            logging.info(f"Found {len(accessions)} accessions: {accessions}")

                            # Write accessions to file
                            accession_file = os.path.join(data_dir, "ncbi_download_list.txt")
                            with open(accession_file, "w") as f:
                                f.write("\n".join(accessions) + "\n")

                            # Download genomes
                            self.prep_status["message"] = f"Downloading {len(accessions)} genomes from NCBI..."
                            self.prep_status["progress"] = 65
                            self.prep_status["last_update"] = time.time()
                            download_prefix = "nanometa"
                            output_zip = os.path.join(data_dir, f"{download_prefix}_ncbi_download.zip")

                            # Use datasets command line tool to download genomes
                            cmd = [
                                "datasets", "download", "genome", "accession",
                                "--inputfile", accession_file,
                                "--filename", output_zip
                            ]
                            try:
                                subprocess.run(cmd, check=True)

                                # Decompress and rename
                                self.prep_status["message"] = "Processing downloaded genomes..."
                                self.prep_status["progress"] = 75
                                self.prep_status["last_update"] = time.time()

                                # Extract zip file
                                with zipfile.ZipFile(output_zip, 'r') as zip_ref:
                                    zip_ref.extractall(data_dir)

                                # Rename files based on taxids
                                for species, taxid in species_to_taxid.items():
                                    if species in missing_species:
                                        species_rows = df[df["Species"] == species]
                                        if not species_rows.empty:
                                            gid = species_rows.iloc[0]["GID"]
                                            ncbi_data_dir = os.path.join(data_dir, "ncbi_dataset", "data")
                                            accession_path = os.path.join(ncbi_data_dir, gid)

                                            if os.path.isdir(accession_path):
                                                # Find FNA file
                                                for filename in os.listdir(accession_path):
                                                    if filename.endswith(".fna"):
                                                        source_file = os.path.join(accession_path, filename)
                                                        target_file = os.path.join(genomes_dir, f"{taxid}.fasta")
                                                        shutil.copy(source_file, target_file)
                                                        break
                            except subprocess.CalledProcessError as e:
                                self.prep_status["errors"].append(f"Error downloading genomes: {str(e)}")
                        else:
                            logging.warning("DataFrame has GID column but no accessions found")
                            self.prep_status["errors"].append("No accessions found for download. Check species names and try again.")
                    else:
                        if df is None:
                            logging.error("DataFrame is None - API results parsing failed")
                        elif df.empty:
                            logging.error("DataFrame is empty - no results from API")
                        else:
                            logging.error(f"GID column missing from DataFrame. Available columns: {df.columns.tolist()}")

                        self.prep_status["errors"].append("Failed to find accessions for download. Check species names and try again.")

                        # Continue with preparation even without genomes
                        self.prep_status["message"] = "Continuing preparation without genome downloads..."

                except Exception as e:
                    self.prep_status["errors"].append(f"Error downloading genomes: {str(e)}")

            # STEP 6: Build BLAST databases
            self.prep_status["message"] = "Building BLAST databases for validation..."
            self.prep_status["progress"] = 85
            self.prep_status["last_update"] = time.time()

            # Check which BLAST databases are missing
            missing_dbs = []
            blast_dir = os.path.join(data_dir, "blast")
            os.makedirs(blast_dir, exist_ok=True)

            for species, taxid in species_to_taxid.items():
                blast_db_file = os.path.join(blast_dir, f"{taxid}.fasta.nhr")
                if not os.path.exists(blast_db_file):
                    missing_dbs.append(str(taxid))

            # Build missing BLAST databases
            if missing_dbs:
                input_folder = os.path.join(data_dir, "genomes")
                for taxid in missing_dbs:
                    file_path = os.path.join(input_folder, f"{taxid}.fasta")
                    database_name = os.path.join(blast_dir, f"{taxid}.fasta")

                    if os.path.exists(file_path):
                        system_cmd = [
                            "makeblastdb",
                            "-in", file_path,
                            "-dbtype", "nucl",
                            "-out", database_name,
                        ]

                        try:
                            subprocess.run(system_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                        except subprocess.CalledProcessError as e:
                            self.prep_status["errors"].append(f"Error building BLAST database for {taxid}: {e.stderr.decode() if e.stderr else str(e)}")

            # STEP 7: Complete preparation
            self.prep_status["message"] = "Data preparation completed successfully!"
            self.prep_status["progress"] = 100
            self.prep_status["running"] = False
            self.prep_status["last_update"] = time.time()

        except Exception as e:
            self.prep_status["message"] = f"Error: {str(e)}"
            self.prep_status["progress"] = 100
            self.prep_status["running"] = False
            self.prep_status["errors"].append(str(e))
            self.prep_status["last_update"] = time.time()

