"""
Configuration validator for Nanometa Live.

This module provides functions for validating configuration settings
to ensure they are appropriate for the application.
"""

from typing import Dict, Any


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate a configuration and fill in any missing values with defaults.

    Args:
        config: Configuration dictionary to validate

    Returns:
        A validated configuration dictionary
    """
    if not config:
        raise ValueError("Configuration cannot be empty")

    # Create a copy of the configuration
    validated_config = dict(config)

    # Fill in required fields with defaults if missing
    _validate_basic_settings(validated_config)
    _validate_paths(validated_config)
    _validate_performance_settings(validated_config)
    _validate_taxonomy_settings(validated_config)
    _validate_validation_settings(validated_config)
    _validate_gui_settings(validated_config)

    # Critical: Validate boolean parameters
    _validate_boolean_parameters(validated_config)

    return validated_config


def _validate_boolean_parameters(config: Dict[str, Any]) -> None:
    """
    Ensure key boolean parameters are strictly True or False.

    Args:
        config: Configuration dictionary to validate
    """
    # Ensure kraken_memory_mapping is a boolean
    if "kraken_memory_mapping" in config:
        if isinstance(config["kraken_memory_mapping"], str):
            # Handle legacy format
            config["kraken_memory_mapping"] = config["kraken_memory_mapping"] == "--memory-mapping" or \
                config["kraken_memory_mapping"].lower() in ["true", "yes", "y", "1"]
        config["kraken_memory_mapping"] = bool(config["kraken_memory_mapping"])
    else:
        config["kraken_memory_mapping"] = True  # Default value

    # Ensure blast_validation is a boolean
    if "blast_validation" in config:
        if isinstance(config["blast_validation"], str):
            config["blast_validation"] = config["blast_validation"].lower() in ["true", "yes", "y", "1"]
        config["blast_validation"] = bool(config["blast_validation"])
    else:
        config["blast_validation"] = True  # Default value

    # Ensure remove_temp_files is a boolean
    if "remove_temp_files" in config:
        if isinstance(config["remove_temp_files"], str):
            # Handle legacy format
            config["remove_temp_files"] = config["remove_temp_files"] == "yes" or \
                config["remove_temp_files"].lower() in ["true", "yes", "y", "1"]
        config["remove_temp_files"] = bool(config["remove_temp_files"])
    else:
        config["remove_temp_files"] = True  # Default value


def _validate_basic_settings(config: Dict[str, Any]) -> None:
    """
    Validate basic settings like analysis name.

    Args:
        config: Configuration dictionary to validate
    """
    # Analysis name
    if not config.get("analysis_name"):
        config["analysis_name"] = "Nanometa Live Analysis"

    # Species of interest
    if "species_of_interest" not in config:
        config["species_of_interest"] = []

    # Ensure species of interest is a list of dictionaries with name and taxid
    species_list = []
    for species in config["species_of_interest"]:
        if isinstance(species, dict) and "name" in species:
            species_list.append(species)
        elif isinstance(species, str):
            species_list.append({"name": species, "taxid": ""})
    config["species_of_interest"] = species_list


def _validate_paths(config: Dict[str, Any]) -> None:
    """
    Validate path settings like input and output directories.

    Args:
        config: Configuration dictionary to validate
    """
    # Nanopore output directory
    if not config.get("nanopore_output_directory"):
        config["nanopore_output_directory"] = ""

    # Kraken database path
    if not config.get("kraken_db"):
        config["kraken_db"] = ""

    # Main directory
    if not config.get("main_dir"):
        config["main_dir"] = ""


def _validate_performance_settings(config: Dict[str, Any]) -> None:
    """
    Validate performance settings like CPU cores and memory usage.

    Args:
        config: Configuration dictionary to validate
    """
    # CPU cores
    for core_type in [
        "pipeline_cores",  # Renamed from snakemake_cores for Nextflow
        "snakemake_cores",  # Deprecated - kept for backward compatibility
        "kraken_cores",
        "validation_cores",
        "blast_cores",
    ]:
        if (
            core_type not in config
            or not isinstance(config[core_type], int)
            or config[core_type] < 1
        ):
            config[core_type] = 1

    # Check intervals
    if (
        "check_intervals_seconds" not in config
        or not isinstance(config["check_intervals_seconds"], int)
        or config["check_intervals_seconds"] < 1
    ):
        config["check_intervals_seconds"] = 15

    # Realtime timeout (minutes). None means "run indefinitely" and is a valid value.
    # Only coerce if the key is missing or the value is an invalid type/out of range.
    if "realtime_timeout_minutes" not in config:
        config["realtime_timeout_minutes"] = 60
    elif config["realtime_timeout_minutes"] is not None:
        rtm = config["realtime_timeout_minutes"]
        if not isinstance(rtm, int) or isinstance(rtm, bool) or rtm < 1 or rtm > 10080:
            config["realtime_timeout_minutes"] = 60

    # Local package management
    if "local_package_management" not in config:
        config["local_package_management"] = None

    # Conda frontend
    if "conda_frontend" not in config:
        config["conda_frontend"] = "mamba"


def _validate_taxonomy_settings(config: Dict[str, Any]) -> None:
    """
    Validate taxonomy settings like Kraken database and taxonomy.

    Args:
        config: Configuration dictionary to validate
    """
    # Kraken taxonomy
    if "kraken_taxonomy" not in config or config["kraken_taxonomy"] not in [
        "gtdb",
        "ncbi",
    ]:
        config["kraken_taxonomy"] = "gtdb"

    # External Kraken database
    if "external_kraken2_db" not in config:
        config["external_kraken2_db"] = ""

    # Taxonomic hierarchy letters
    if (
        "taxonomic_hierarchy_letters" not in config
        or not config["taxonomic_hierarchy_letters"]
    ):
        config["taxonomic_hierarchy_letters"] = ["D", "P", "C", "O", "F", "G", "S"]

    # Default hierarchy letters
    if (
        "default_hierarchy_letters" not in config
        or not config["default_hierarchy_letters"]
    ):
        config["default_hierarchy_letters"] = ["D", "C", "G", "S"]

    # Default reads per level
    if (
        "default_reads_per_level" not in config
        or not isinstance(config["default_reads_per_level"], int)
        or config["default_reads_per_level"] < 1
    ):
        config["default_reads_per_level"] = 10


def _validate_validation_settings(config: Dict[str, Any]) -> None:
    """
    Validate validation settings like BLAST parameters.

    Args:
        config: Configuration dictionary to validate
    """
    # Minimum percent identity
    if (
        "min_perc_identity" not in config
        or not isinstance(config["min_perc_identity"], (int, float))
        or config["min_perc_identity"] < 50
        or config["min_perc_identity"] > 100
    ):
        config["min_perc_identity"] = 90

    # E-value cutoff
    if (
        "e_val_cutoff" not in config
        or not isinstance(config["e_val_cutoff"], (int, float))
        or config["e_val_cutoff"] < 0
    ):
        config["e_val_cutoff"] = 0.01


def _validate_gui_settings(config: Dict[str, Any]) -> None:
    """
    Validate GUI settings like update interval and port.

    Args:
        config: Configuration dictionary to validate
    """
    # Update interval
    if (
        "update_interval_seconds" not in config
        or not isinstance(config["update_interval_seconds"], int)
        or config["update_interval_seconds"] < 1
    ):
        config["update_interval_seconds"] = 30

    # GUI port
    if "gui_port" not in config:
        config["gui_port"] = 8050

    # Danger threshold
    if (
        "danger_lower_limit" not in config
        or not isinstance(config["danger_lower_limit"], int)
        or config["danger_lower_limit"] < 1
    ):
        config["danger_lower_limit"] = 100