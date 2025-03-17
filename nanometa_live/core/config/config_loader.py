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

def _process_boolean_toggles(config_dict):
    """
    Process boolean toggle values to ensure they're in the correct format.
    Must be called before saving to YAML.
    """
    if not isinstance(config_dict, dict):
        return config_dict

    # Create a copy to avoid modifying the original
    result = dict(config_dict)

    # Handle blast_validation explicitly
    if "blast_validation" in result:
        # Force to Python boolean value
        if isinstance(result["blast_validation"], str):
            result["blast_validation"] = result["blast_validation"].lower() in ["true", "yes", "y", "1"]
        else:
            result["blast_validation"] = bool(result["blast_validation"])

    # Handle kraken_memory_mapping
    if "kraken_memory_mapping" in result:
        # Should be string "--memory-mapping" when true, "" when false
        if isinstance(result["kraken_memory_mapping"], bool):
            result["kraken_memory_mapping"] = "--memory-mapping" if result["kraken_memory_mapping"] else ""
        elif result["kraken_memory_mapping"] not in ["--memory-mapping", ""]:
            # Handle other string values like "True"/"False"
            result["kraken_memory_mapping"] = "--memory-mapping" if str(result["kraken_memory_mapping"]).lower() in ["true", "yes", "y", "1"] else ""

    # Handle remove_temp_files
    if "remove_temp_files" in result:
        # Should be string "yes" when true, "no" when false
        if isinstance(result["remove_temp_files"], bool):
            result["remove_temp_files"] = "yes" if result["remove_temp_files"] else "no"
        elif result["remove_temp_files"] not in ["yes", "no"]:
            # Handle other string values
            result["remove_temp_files"] = "yes" if str(result["remove_temp_files"]).lower() in ["true", "yes", "y", "1"] else "no"

    return result

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

        # Force booleans to be strings in specific cases
        original_represent_bool = self.yaml.representer.represent_bool

        def custom_represent_bool(self_repr, data):
            # Handle specific config keys that should NOT be represented as booleans
            if self_repr.serializer and hasattr(self_repr.serializer, 'current_key'):
                if self_repr.serializer.current_key == 'remove_temp_files':
                    return self_repr.represent_scalar('tag:yaml.org,2002:str', 'yes' if data else 'no')
                elif self_repr.serializer.current_key == 'kraken_memory_mapping':
                    return self_repr.represent_scalar('tag:yaml.org,2002:str', '--memory-mapping' if data else '')
            # Default boolean handling
            return original_represent_bool(data)

        # Replace the boolean representer
        self.yaml.representer.represent_bool = custom_represent_bool

    def create_default_config(self) -> Dict[str, Any]:
        """
        Create a default configuration with sensible defaults.

        Returns:
            A dictionary containing the default configuration
        """
        default_config = {
            "analysis_name": "Nanometa Live Analysis",
            "nanopore_output_directory": "",
            "species_of_interest": [],
            "update_interval_seconds": 30,
            "gui_port": 8050,
            "danger_lower_limit": 100,
            "taxonomic_hierarchy_letters": ["D", "P", "C", "O", "F", "G", "S"],
            "default_hierarchy_letters": ["D", "C", "G", "S"],
            "default_reads_per_level": 10,
            "snakemake_cores": 1,
            "kraken_cores": 1,
            "validation_cores": 1,
            "blast_cores": 1,
            "check_intervals_seconds": 15,
            "kraken_db": "",
            "kraken_taxonomy": "gtdb",
            # Now using boolean values consistently
            "kraken_memory_mapping": True,
            "blast_validation": True,
            "min_perc_identity": 90,
            "e_val_cutoff": 0.01,
            "external_kraken2_db": "",
            "local_package_management": None,
            "conda_frontend": "mamba",
            "remove_temp_files": True,
            "main_dir": "",
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

        # CRITICAL: Explicitly handle each toggle value
        if "blast_validation" in save_config:
            # Force to Python boolean type and then to correct string representation
            blast_val = bool(save_config["blast_validation"])
            save_config["blast_validation"] = False if blast_val is False else True

        if "kraken_memory_mapping" in save_config:
            # If it's a boolean already, leave it; if it's "--memory-mapping", convert to boolean
            if save_config["kraken_memory_mapping"] == "--memory-mapping":
                save_config["kraken_memory_mapping"] = True
            elif save_config["kraken_memory_mapping"] == "":
                save_config["kraken_memory_mapping"] = False

        if "remove_temp_files" in save_config:
            # Convert "yes"/"no" to boolean for consistency
            if isinstance(save_config["remove_temp_files"], str):
                save_config["remove_temp_files"] = save_config["remove_temp_files"] == "yes"

        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        config_path = os.path.join(self.config_dir, filename)

        # Configure YAML specifically for this save operation
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.boolean_representation = ['false', 'true']

        try:
            with open(config_path, "w") as f:
                yaml.dump(save_config, f)
            return config_path
        except Exception as e:
            logging.error(f"Failed to save configuration: {e}")
            raise

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
            try:
                config = self.load_config(config_file)
                configs.append(
                    {
                        "path": config_file,
                        "name": config.get("analysis_name", os.path.basename(config_file)),
                        "timestamp": config.get("timestamp", "Unknown"),
                        "filename": os.path.basename(config_file),
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to load config {config_file}: {e}")

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

        return config