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
            "kraken_memory_mapping": "--memory-mapping",
            "blast_validation": True,
            "min_perc_identity": 90,
            "e_val_cutoff": 0.01,
            "external_kraken2_db": "",
            "local_package_management": None,
            "conda_frontend": "mamba",
            "remove_temp_files": "yes",
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

    def save_config(
        self, config: Dict[str, Any], filename: Optional[str] = None
    ) -> str:
        """
        Save a configuration to a file with preserved comments.

        Args:
            config: Configuration dictionary to save
            filename: Filename to save the configuration to. If None, a timestamp-based
                      filename will be generated.

        Returns:
            The path to the saved configuration file
        """
        if filename is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"config_{timestamp}.yaml"

        # Fix for duplicate .yaml extensions in the filename
        if filename.endswith('.yaml.yaml'):
            filename = filename.replace('.yaml.yaml', '.yaml')
        elif not filename.endswith('.yaml'):
            filename = filename + '.yaml'

        # Update timestamp in config
        config["timestamp"] = datetime.datetime.now().isoformat()

        config_path = os.path.join(self.config_dir, filename)
        logging.info(f"Saving configuration to {config_path}")

        # Check if the file already exists and use existing file to preserve comments
        if os.path.exists(config_path):
            try:
                # Load existing file to preserve comments
                with open(config_path, "r") as f:
                    existing_config = self.yaml.load(f)

                # Update with new values
                for key, value in config.items():
                    existing_config[key] = value

                # Write back
                with open(config_path, "w") as f:
                    self.yaml.dump(existing_config, f)
            except Exception as e:
                logging.warning(f"Failed to preserve comments in {config_path}: {e}")
                # Fallback to direct write
                with open(config_path, "w") as f:
                    self.yaml.dump(config, f)
        else:
            # New file, just write directly
            with open(config_path, "w") as f:
                self.yaml.dump(config, f)

        return config_path

    def get_available_configs(self) -> List[Dict[str, Any]]:
        """
        Get a list of available configuration files.

        Returns:
            A list of dictionaries containing metadata about available configs
        """
        config_files = glob.glob(os.path.join(self.config_dir, "*.yaml"))
        configs = []

        for config_file in config_files:
            try:
                config = self.load_config(config_file)
                configs.append(
                    {
                        "path": config_file,
                        "name": config.get("analysis_name", "Unnamed"),
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