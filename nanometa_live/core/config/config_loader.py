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

logger = logging.getLogger(__name__)
import glob
from pathlib import Path
from typing import Dict, Any, Optional, List

# Use ruamel.yaml for comment preservation
from ruamel.yaml import YAML, YAMLError, constructor as yaml_constructor


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

        # Initialize ruamel.yaml with round-trip mode for comment preservation,
        # but use SafeConstructor to prevent processing of arbitrary YAML tags
        # (e.g. !!python/object) which could be a security concern with
        # user-supplied configuration files.
        self.yaml = YAML()
        self.yaml.Constructor = yaml_constructor.SafeConstructor
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
            "minimap2_preset": "map-ont",
            "minimap2_min_mapq": 30,
            # Genome cache directory for downloaded reference genomes
            "genome_cache_dir": os.path.join(os.path.expanduser("~"), ".nanometa"),
            "external_kraken2_db": "",
            "local_package_management": None,
            "conda_frontend": "mamba",
            "remove_temp_files": True,
            "main_dir": "",
            # QC and analysis tools
            "qc_tool": "chopper",
            "skip_nanoplot": False,
            # Kraken2 realtime incremental classification
            "kraken2_enable_incremental": True,
            # Visualization options
            "enable_krona_plots": False,
            "enable_nanopore_stats_mqc": False,
            # Offline mode: when enabled, skip all network calls and use cached data only
            "offline_mode": False,
            # Processing mode settings
            "processing_mode": "batch",
            "sample_handling": "by_barcode",
            "sample_name": "sample",
            # Pipeline execution settings
            "pipeline_profile": "conda",
            # Pinned remote default: tracks the main branch of the upstream
            # nanometanf repository. A fresh install without this pin silently
            # fell back to an unresolved spec, so the GUI would report
            # "pipeline not found" after the first run attempt. Override in
            # config.yaml (e.g. "remote:dev" for active development, or a
            # local path "local:/path/to/checkout") as needed.
            "pipeline_source": "remote:main",
            # Realtime mode settings
            "max_file_age_minutes": 1000000,
            # Stop real-time monitoring after N minutes with no new files (null = run indefinitely)
            "realtime_timeout_minutes": 60,
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

            # Merge with defaults so missing keys get default values
            defaults = self.create_default_config()
            for key, value in defaults.items():
                if key not in config:
                    config[key] = value

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
        except YAMLError as e:
            # Provide location information when available
            location = ""
            if hasattr(e, "problem_mark") and e.problem_mark is not None:
                mark = e.problem_mark
                location = f" at line {mark.line + 1}, column {mark.column + 1}"
            logging.error(
                f"YAML syntax error in {config_path}{location}: {e}"
            )
            raise ValueError(
                f"Invalid YAML in configuration file '{config_path}'{location}. "
                f"Check for indentation or formatting errors."
            ) from e
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.error(f"Could not read configuration {config_path}: {e}")
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
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.error(f"Failed to write configuration to {config_path}: {e}")
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
        except YAMLError as e:
            location = ""
            if hasattr(e, "problem_mark") and e.problem_mark is not None:
                mark = e.problem_mark
                location = f" at line {mark.line + 1}, column {mark.column + 1}"
            logger.warning(f"Skipping {config_path}: YAML syntax error{location}")
            return None
        except (FileNotFoundError, PermissionError, OSError):
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

    def delete_config(self, config_path: str) -> bool:
        """
        Delete a saved configuration file.

        The auto-save file (last-session.yaml) cannot be deleted through
        this method to prevent accidental loss of session state.

        Args:
            config_path: Path to the configuration file to delete.

        Returns:
            True if the file was deleted, False otherwise.
        """
        path = Path(config_path).resolve()
        allowed_dir = Path(self.config_dir).resolve()
        if not str(path).startswith(str(allowed_dir) + os.sep) and path != allowed_dir:
            logger.warning(f"Path traversal blocked: {config_path} is outside {self.config_dir}")
            return False
        if path.name == "last-session.yaml":
            logger.warning("Cannot delete the auto-save configuration")
            return False
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return False
        try:
            path.unlink()
            logger.info(f"Deleted config: {path.name}")
            return True
        except OSError as e:
            logger.error(f"Failed to delete config {path.name}: {e}")
            return False

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
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.error(f"Could not read Kraken databases file {db_file}: {e}")
            return {}
        except yaml.YAMLError as e:
            logging.error(f"Malformed Kraken databases file {db_file}: {e}")
            return {}