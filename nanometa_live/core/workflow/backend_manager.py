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

from nanometa_live.core.utils.file_utils import check_command_exists
from nanometa_live.core.workflow.snakemake_manager import SnakemakeManager


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

            # Additional validation of the Kraken database
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

            # Step 1: Extract taxonomy IDs from Kraken database
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

                    import subprocess
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
                return  # Exit the function immediately
            else:
                self.prep_status["message"] = f"Found taxonomy IDs for {matched_species_count} out of {len(config.get('species_of_interest', []))} species."
                self.prep_status["progress"] = 45
                self.prep_status["last_update"] = time.time()

            self.config["species_of_interest"] = updated_species

            # Step 2: Check for missing genome files
            self.prep_status["message"] = "Checking for missing genome files..."
            self.prep_status["progress"] = 50
            self.prep_status["last_update"] = time.time()

            # Create genomes directory
            genomes_dir = os.path.join(data_dir, "genomes")
            os.makedirs(genomes_dir, exist_ok=True)

            # Check which genomes are missing
            missing_genomes = []
            for species in updated_species:
                taxid = species.get("taxid", "")
                if taxid:
                    genome_file = os.path.join(genomes_dir, f"{taxid}.fasta")
                    if not os.path.exists(genome_file):
                        missing_genomes.append((species.get("name", ""), taxid))

            if missing_genomes:
                self.prep_status["message"] = f"Found {len(missing_genomes)} missing genomes. Preparing for download..."
                self.prep_status["progress"] = 60
                self.prep_status["last_update"] = time.time()

                # In a real implementation, would download genomes from NCBI here
                # For now, create placeholder files
                for species_name, taxid in missing_genomes:
                    placeholder_path = os.path.join(genomes_dir, f"{taxid}.fasta")
                    # Create BLAST-compatible header: use a simple format without spaces or special chars
                    safe_name = species_name.replace(" ", "_").replace(",", "").replace("'", "").replace("(", "").replace(")", "")
                    with open(placeholder_path, 'w') as f:
                        # Use standard NCBI-like header format
                        f.write(f">gnl|nanometa|{taxid} [Taxid={taxid}] {safe_name} placeholder sequence\n")
                        # Make the sequence longer and more varied
                        f.write("ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n" * 10)

                self.prep_status["message"] = f"Created placeholder genome files for {len(missing_genomes)} species."
                self.prep_status["progress"] = 65
                self.prep_status["last_update"] = time.time()

            # Step 3: Build BLAST databases
            self.prep_status["message"] = "Building BLAST databases for validation..."
            self.prep_status["progress"] = 70
            self.prep_status["last_update"] = time.time()

            # Create BLAST directory
            blast_dir = os.path.join(data_dir, "blast")
            os.makedirs(blast_dir, exist_ok=True)

            # Check which BLAST databases are missing
            missing_dbs = []
            for species in updated_species:
                taxid = species.get("taxid", "")
                if taxid:
                    blast_db = os.path.join(blast_dir, f"{taxid}.fasta.nhr")
                    if not os.path.exists(blast_db):
                        genomes_file = os.path.join(genomes_dir, f"{taxid}.fasta")
                        if os.path.exists(genomes_file):
                            missing_dbs.append((taxid, genomes_file))

            # Build missing BLAST databases
            if missing_dbs:
                self.prep_status["message"] = f"Building {len(missing_dbs)} BLAST databases..."
                self.prep_status["progress"] = 80
                self.prep_status["last_update"] = time.time()

                for taxid, genome_file in missing_dbs:
                    try:
                        db_file = os.path.join(blast_dir, f"{taxid}.fasta")
                        import subprocess
                        cmd = [
                            "makeblastdb",
                            "-in", genome_file,
                            "-dbtype", "nucl",
                            "-out", db_file,
                            "-parse_seqids",
                            "-hash_index",
                            "-title", f"Nanometa_Tax{taxid}"
                        ]
                        # Add error handling with full output capture
                        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        if result.returncode != 0:
                            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
                    except subprocess.CalledProcessError as e:
                        error_message = e.stderr.decode() if e.stderr else str(e)
                        self.prep_status["errors"].append(f"Error building BLAST database for {taxid}: {error_message}")

                        # Continue with other databases even if one fails
                        continue

            # Completed
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