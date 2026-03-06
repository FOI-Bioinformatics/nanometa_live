"""
Configuration loader module for Nanometa Live.

This module handles loading, saving, and managing configuration files for the application.
It provides functionality to:
- Load configurations from YAML files
- Create default configurations
- Save configurations to YAML files
- Validate configurations
"""

import os
import logging
import datetime
import glob
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

# Use ruamel.yaml for comment preservation
from ruamel.yaml import YAML


class ConfigLoader:
    """Handles loading and saving of application configurations."""

    def __init__(self, config_dir: str):
        """
        Initialize the ConfigLoader.

        Args:
            config_dir: Directory where configuration files are stored
        """
        self.config_dir = config_dir
        os.makedirs(config_dir, exist_ok=True)

        # Initialize ruamel.yaml
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)

        # CRITICAL: Configure yaml to handle booleans correctly
        # This ensures true/false are output as lowercase in the YAML
        self.yaml.boolean_representation = ['false', 'true']

    def create_default_config(self) -> Dict[str, Any]:
        """
        Create a default configuration with sensible defaults.

        Returns:
            A dictionary containing the default configuration
        """
        # Default results directory: ~/nanometa_results
        default_results_dir = os.path.join(os.path.expanduser("~"), "nanometa_results")

        default_config = {
            "analysis_name": "Nanometa Live Analysis",
            "nanopore_output_directory": "",
            "results_output_directory": default_results_dir,
            "species_of_interest": [],
            "update_interval_seconds": 30,
            "gui_port": 8050,
            "danger_lower_limit": 100,
            "taxonomic_hierarchy_letters": ["D", "P", "C", "O", "F", "G", "S"],
            "default_hierarchy_letters": ["D", "C", "G", "S"],
            "default_reads_per_level": 10,
            "pipeline_cores": 1,
            "kraken_cores": 1,
            "validation_cores": 1,
            "blast_cores": 1,
            "check_intervals_seconds": 15,
            "kraken_db": "",
            "kraken_taxonomy": "gtdb",
            # Using strict boolean values
            "kraken_memory_mapping": True,
            # Validation settings
            "blast_validation": False,  # Disabled by default - requires genomes to be downloaded
            "validation_method": "blast",  # 'blast', 'minimap2', or 'both'
            "min_perc_identity": 90,
            "e_val_cutoff": 0.01,
            "validation_hit_rate_threshold": 0.5,
            "validation_identity_threshold": 90.0,
            # Genome cache directory for downloaded reference genomes
            "genome_cache_dir": os.path.join(os.path.expanduser("~"), ".nanometa"),
            "external_kraken2_db": "",
            "local_package_management": None,
            "conda_frontend": "mamba",
            "remove_temp_files": True,
            "main_dir": "",
            # Offline mode: when enabled, skip all network calls and use cached data only
            "offline_mode": False,
            # Processing mode settings
            "processing_mode": "batch",
            "sample_handling": "by_barcode",
            "sample_name": "sample",
            # Batch settings (for realtime mode, batch_size=1 processes files immediately)
            "batch_size": 1,
            "min_batch_size": 1,
            "timestamp": datetime.datetime.now().isoformat(),
        }

        return default_config

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """
        Load a configuration from a file with preserved comments.

        Args:
            config_path: Path to the configuration file

        Returns:
            A dictionary containing the configuration

        Raises:
            FileNotFoundError: If the configuration file does not exist
        """
        logging.info(f"Loading configuration from {config_path}")

        try:
            with open(config_path, "r") as f:
                config = self.yaml.load(f)

            # Ensure config is a dictionary
            if config is None:
                logging.warning(f"Configuration file {config_path} is empty, using defaults")
                config = self.create_default_config()

            # Update timestamp for tracking
            config["timestamp"] = datetime.datetime.now().isoformat()

            # Ensure boolean parameters are strictly boolean
            self._standardize_boolean_params(config)

            return config
        except FileNotFoundError:
            logging.error(f"Configuration file {config_path} not found")
            raise
        except PermissionError:
            logging.error(f"Permission denied: Cannot read {config_path}")
            raise
        except Exception as e:
            logging.error(f"Failed to load configuration from {config_path}. Exception: {e}")
            raise

    def _standardize_boolean_params(self, config: Dict[str, Any]) -> None:
        """
        Ensure boolean parameters are strictly boolean values.

        Args:
            config: Configuration dictionary to standardize
        """
        # Convert kraken_memory_mapping to boolean
        if "kraken_memory_mapping" in config:
            if isinstance(config["kraken_memory_mapping"], str):
                # Handle legacy format (convert "--memory-mapping" to True)
                config["kraken_memory_mapping"] = config["kraken_memory_mapping"] == "--memory-mapping" or \
                    config["kraken_memory_mapping"].lower() in ["true", "yes", "y", "1"]
            # Ensure final type is boolean
            config["kraken_memory_mapping"] = bool(config["kraken_memory_mapping"])

        # Convert blast_validation to boolean
        if "blast_validation" in config:
            if isinstance(config["blast_validation"], str):
                config["blast_validation"] = config["blast_validation"].lower() in ["true", "yes", "y", "1"]
            # Ensure final type is boolean
            config["blast_validation"] = bool(config["blast_validation"])

        # Convert remove_temp_files to boolean
        if "remove_temp_files" in config:
            if isinstance(config["remove_temp_files"], str):
                # Handle legacy format (convert "yes" to True)
                config["remove_temp_files"] = config["remove_temp_files"] == "yes" or \
                    config["remove_temp_files"].lower() in ["true", "yes", "y", "1"]
            # Ensure final type is boolean
            config["remove_temp_files"] = bool(config["remove_temp_files"])

        # Convert offline_mode to boolean
        if "offline_mode" in config:
            if isinstance(config["offline_mode"], str):
                config["offline_mode"] = config["offline_mode"].lower() in ["true", "yes", "y", "1"]
            config["offline_mode"] = bool(config["offline_mode"])

    def save_config(self, config: Dict[str, Any], filename: Optional[str] = None) -> str:
        """Save a configuration to a file with preserved comments."""
        if filename is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"config_{timestamp}.yaml"

        # Fix filename extensions
        if filename.endswith('.yaml.yaml'):
            filename = filename.replace('.yaml.yaml', '.yaml')
        elif not filename.endswith('.yaml'):
            filename = filename + '.yaml'

        # Update timestamp
        config["timestamp"] = datetime.datetime.now().isoformat()

        # Create a copy to prevent modifying the original
        save_config = dict(config)

        # Ensure boolean parameters are strictly boolean
        self._standardize_boolean_params(save_config)

        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        config_path = os.path.join(self.config_dir, filename)

        try:
            with open(config_path, "w") as f:
                self.yaml.dump(save_config, f)
            return config_path
        except Exception as e:
            logging.error(f"Failed to save configuration: {e}")
            raise

    def _get_config_metadata(self, config_path: str) -> Optional[Dict[str, Any]]:
        """
        Extract minimal metadata from a config file without full loading.

        This is a lightweight operation that only reads the fields needed
        for the config dropdown, avoiding excessive logging.

        Args:
            config_path: Path to the configuration file

        Returns:
            Dictionary with path, name, timestamp, filename or None on error
        """
        try:
            with open(config_path, "r") as f:
                config = self.yaml.load(f)

            if config is None:
                return None

            return {
                "path": config_path,
                "name": config.get("analysis_name", os.path.basename(config_path)),
                "timestamp": config.get("timestamp", "Unknown"),
                "filename": os.path.basename(config_path),
            }
        except Exception:
            return None

    def get_available_configs(self) -> List[Dict[str, Any]]:
        """
        Get a list of available configuration files.

        Returns:
            A list of dictionaries containing metadata about available configs
        """
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)

        config_files = glob.glob(os.path.join(self.config_dir, "*.yaml"))
        configs = []

        for config_file in config_files:
            # Use lightweight metadata extraction (no logging)
            metadata = self._get_config_metadata(config_file)
            if metadata:
                configs.append(metadata)

        # Sort by timestamp, newest first
        configs.sort(key=lambda x: x["timestamp"], reverse=True)

        return configs

    def get_most_recent_config(self) -> Optional[Dict[str, Any]]:
        """
        Get the most recently modified configuration.

        Returns:
            The most recent configuration or None if no configurations are available
        """
        configs = self.get_available_configs()

        if not configs:
            return None

        return self.load_config(configs[0]["path"])

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a configuration and fill in any missing values with defaults.

        Args:
            config: Configuration dictionary to validate

        Returns:
            A validated configuration dictionary
        """
        default_config = self.create_default_config()

        # Fill in missing values with defaults
        for key, value in default_config.items():
            if key not in config:
                config[key] = value

        # Ensure boolean parameters are strictly boolean
        self._standardize_boolean_params(config)

        return config


    @staticmethod
    def load_kraken_databases_from_file():
        """Load Kraken databases directly from YAML file."""
        import yaml
        import os

        db_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "kraken2_databases.yaml")
        try:
            with open(db_file, 'r') as f:
                db_config = yaml.safe_load(f)
            return db_config.get("kraken2_databases", {})
        except Exception as e:
            logging.error(f"Error loading Kraken databases: {e}")
            return {}