"""
Pipeline runner for Nanometa Live.

This module provides high-level functions to run the Snakemake pipeline
directly from Python code. It's used by the backend manager and can also
be used by scripts that need to run the pipeline programmatically.
"""

import os
import sys
import time
import logging
import subprocess
import pkg_resources
from typing import Dict, Any, Optional, List, Tuple


def run_pipeline(config_path: str, cores: int = 1, dryrun: bool = False) -> bool:
    """
    Run the Snakemake pipeline using the provided configuration.

    Args:
        config_path: Path to the configuration file
        cores: Number of CPU cores to use
        dryrun: Whether to perform a dry run

    Returns:
        True if the pipeline completed successfully, False otherwise
    """
    try:
        logging.info(f"Starting Snakemake pipeline with config: {config_path}")

        # Find the Snakefile
        import nanometa_live

        package_dir = os.path.dirname(nanometa_live.__file__)
        snakefile_path = os.path.join(package_dir, "Snakefile")

        if not os.path.exists(snakefile_path):
            logging.error(f"Snakefile not found at: {snakefile_path}")
            return False

        # Build the command
        cmd = [
            "snakemake",
            "--snakefile",
            snakefile_path,
            "--configfile",
            config_path,
            "--cores",
            str(cores),
            "--printshellcmds",
        ]

        if dryrun:
            cmd.append("--dryrun")

        # Log the command
        logging.info(f"Running command: {' '.join(cmd)}")

        # Run the command
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        # Log the output
        log_dir = os.path.dirname(config_path)
        log_path = os.path.join(log_dir, "snakemake.log")

        with open(log_path, "w") as f:
            f.write(result.stdout)

        # Check the result
        if result.returncode != 0:
            logging.error(f"Pipeline failed with return code: {result.returncode}")
            logging.error(f"See log file for details: {log_path}")
            return False

        logging.info("Pipeline completed successfully")
        return True

    except Exception as e:
        logging.error(f"Error running pipeline: {e}")
        return False


def run_pipeline_python_api(
    config_path: str, cores: int = 1, dryrun: bool = False
) -> bool:
    """
    Run the Snakemake pipeline using the Python API.

    Args:
        config_path: Path to the configuration file
        cores: Number of CPU cores to use
        dryrun: Whether to perform a dry run

    Returns:
        True if the pipeline completed successfully, False otherwise
    """
    try:
        logging.info(f"Starting Snakemake pipeline with config: {config_path}")

        # Find the Snakefile
        import nanometa_live

        package_dir = os.path.dirname(nanometa_live.__file__)
        snakefile_path = os.path.join(package_dir, "Snakefile")

        if not os.path.exists(snakefile_path):
            logging.error(f"Snakefile not found at: {snakefile_path}")
            return False

        # Import Snakemake
        try:
            import snakemake as sm
        except ImportError:
            logging.error("Failed to import Snakemake. Make sure it's installed.")
            return False

        # Log file setup
        log_dir = os.path.dirname(config_path)
        log_path = os.path.join(log_dir, "snakemake.log")

        # Run the workflow
        with open(log_path, "w") as log_file:
            success = sm.snakemake(
                snakefile_path,
                cores=cores,
                configfiles=[config_path],
                workdir=os.path.dirname(config_path),
                dryrun=dryrun,
                printshellcmds=True,
                printreason=True,
                printrulegraph=True,
                stats=os.path.join(log_dir, "stats.json"),
                unlock=False,
                keepgoing=True,
                quiet=False,
                log_handler=[log_file],
            )

        if not success:
            logging.error(f"Pipeline failed. See log file for details: {log_path}")
            return False

        logging.info("Pipeline completed successfully")
        return True

    except Exception as e:
        logging.error(f"Error running pipeline: {e}")
        return False


def setup_project_directories(main_dir: str) -> bool:
    """
    Set up the project directories needed for the pipeline.

    Args:
        main_dir: Main project directory

    Returns:
        True if the directories were created successfully, False otherwise
    """
    try:
        # Create main directory if it doesn't exist
        os.makedirs(main_dir, exist_ok=True)

        # Create subdirectories
        subdirs = [
            "kraken_cumul",
            "qc_data",
            "fastp_reports",
            "validation_fastas",
            "blast_result_files",
            "kraken_results",
            "fastp_filtered",
            "reports",
            "logs",
        ]

        for subdir in subdirs:
            os.makedirs(os.path.join(main_dir, subdir), exist_ok=True)

        return True

    except Exception as e:
        logging.error(f"Error creating project directories: {e}")
        return False


def check_pipeline_requirements(config: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check if all requirements are met to run the pipeline.

    Args:
        config: Pipeline configuration

    Returns:
        Tuple of (success, message)
    """
    # Check for required directories
    if not config.get("nanopore_output_directory"):
        return False, "Nanopore output directory is required"

    if not os.path.exists(config["nanopore_output_directory"]):
        return (
            False,
            f"Nanopore output directory does not exist: {config['nanopore_output_directory']}",
        )

    # Check for Kraken database
    if not config.get("kraken_db"):
        return False, "Kraken database is required"

    if not os.path.exists(config["kraken_db"]):
        return False, f"Kraken database does not exist: {config['kraken_db']}"

    # Check for main directory
    if not config.get("main_dir"):
        return False, "Main directory is required"

    # Check for required tools
    try:
        # Check for Kraken2
        result = subprocess.run(
            ["kraken2", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False, "Kraken2 is not installed or not in the PATH"

        # Check for FastP
        result = subprocess.run(
            ["fastp", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False, "FastP is not installed or not in the PATH"

        # If BLAST validation is enabled, check for BLAST
        if config.get("blast_validation", True):
            result = subprocess.run(
                ["blastn", "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return False, "BLAST is not installed or not in the PATH"

    except Exception as e:
        return False, f"Error checking for required tools: {e}"

    return True, "All requirements met"


def check_pipeline_status(main_dir: str) -> Dict[str, Any]:
    """
    Check the status of a running pipeline.

    Args:
        main_dir: Main project directory

    Returns:
        Dictionary with status information
    """
    status = {
        "files_processed": 0,
        "kraken_report_exists": False,
        "qc_data_exists": False,
        "validation_complete": False,
        "errors": [],
    }

    try:
        # Check for processed files
        qc_file = os.path.join(main_dir, "qc_data/cumul_qc.txt")
        if os.path.exists(qc_file):
            status["qc_data_exists"] = True
            with open(qc_file, "r") as f:
                status["files_processed"] = sum(1 for _ in f)

        # Check for Kraken report
        kraken_report = os.path.join(
            main_dir, "kraken_cumul/kraken_cumul_report.kreport2"
        )
        status["kraken_report_exists"] = os.path.exists(kraken_report)

        # Check for validation completion
        validation_marker = os.path.join(
            main_dir, "validation_fastas/force_validation.txt"
        )
        status["validation_complete"] = os.path.exists(validation_marker)

        # Check for log file and parse errors
        log_file = os.path.join(main_dir, "snakemake.log")
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                for line in f:
                    if "Error:" in line or "Exception:" in line:
                        status["errors"].append(line.strip())

        return status

    except Exception as e:
        logging.error(f"Error checking pipeline status: {e}")
        status["errors"].append(str(e))
        return status
