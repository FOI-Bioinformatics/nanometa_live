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
        1. Extracting taxonomy IDs from Kraken database
        2. Downloading genome sequences for species of interest
        3. Building BLAST databases for validation

        Returns:
            Tuple of (success, message)
        """
        if not self.config:
            return False, "No configuration loaded"

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

            # Step 1: Extract taxonomy IDs from Kraken database
            self.prep_status["message"] = "Extracting taxonomy IDs from Kraken database..."
            self.prep_status["progress"] = 10
            self.prep_status["last_update"] = time.time()

            species_list = [s.get("name", "") for s in config.get("species_of_interest", [])]
            kraken_db = config.get("kraken_db", "")
            main_dir = config.get("main_dir", "")

            if not species_list:
                self.prep_status["running"] = False
                self.prep_status["errors"].append("No species of interest defined")
                return

            if not kraken_db:
                self.prep_status["running"] = False
                self.prep_status["errors"].append("Kraken database not specified")
                return

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
                        subprocess.run(cmd, stdout=f, check=True)
                except subprocess.CalledProcessError as e:
                    self.prep_status["running"] = False
                    self.prep_status["errors"].append(f"Error running kraken2-inspect: {e}")
                    return

            # Parse the inspect file to extract taxonomy IDs
            self.prep_status["message"] = "Parsing taxonomy information..."
            self.prep_status["progress"] = 30
            self.prep_status["last_update"] = time.time()

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

                            # Only process species level entries
                            if level_type == 'species':
                                # Check if any of our species match this name
                                for species in species_list:
                                    if species in name:
                                        species_taxids[species] = taxid
            except Exception as e:
                self.prep_status["running"] = False
                self.prep_status["errors"].append(f"Error parsing inspect file: {e}")
                return

            # Update config with taxonomy IDs
            self.prep_status["message"] = "Updating configuration with taxonomy IDs..."
            self.prep_status["progress"] = 40
            self.prep_status["last_update"] = time.time()

            updated_species = []
            for species in config.get("species_of_interest", []):
                name = species.get("name", "")
                if name in species_taxids:
                    updated_species.append({
                        "name": name,
                        "taxid": species_taxids[name]
                    })
                else:
                    updated_species.append(species)

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
                self.prep_status["message"] = f"Found {len(missing_genomes)} missing genomes"
                self.prep_status["progress"] = 60
                self.prep_status["last_update"] = time.time()

                # For now, just report missing genomes
                # In a full implementation, would download them from NCBI here
                pass

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
                        cmd = [
                            "makeblastdb",
                            "-in", genome_file,
                            "-dbtype", "nucl",
                            "-out", db_file
                        ]
                        subprocess.run(cmd, check=True)
                    except subprocess.CalledProcessError as e:
                        self.prep_status["errors"].append(f"Error building BLAST database for {taxid}: {e}")

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