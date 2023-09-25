import os
import logging
import subprocess
import shutil
import pkg_resources
import time
from typing import  Any, List, Dict, Union, NoReturn, List

from nanometa_live.helpers.config_utils import load_config

def execute_snakemake(snakefile_path, configfile_path, snakemake_cores, log_file_path="snakemake_output.log", config_contents=None):
    """
    Execute the Snakemake workflow with the specified number of cores and package management settings.

    Parameters:
        snakefile_path (str): Path to the Snakefile.
        snakemake_cores (int): Number of cores to use for Snakemake.
        log_file_path (str): Path to the log file (default is "snakemake_output.log").
        config_contents (dict): Dictionary containing configuration settings including
                               'conda_frontend' and 'local_package_management'.
    """
    conda_frontend = config_contents["conda_frontend"]
    local_package_management = config_contents["local_package_management"]

    logging.info(f"Executing Snakemake workflow with {snakemake_cores} cores")

    # Build the Snakemake command
    snakemake_cmd = [
        "snakemake",
        "--cores", str(snakemake_cores),
        "--rerun-incomplete",
        "--snakefile", snakefile_path,
        "--configfile", configfile_path
    ]

    # Add conda-related options if local_package_management is 'conda'
    if local_package_management == 'conda':
        snakemake_cmd.extend([
            "--use-conda",
            "--conda-frontend", conda_frontend
        ])

    logging.info(f'Executing shell command: {" ".join(snakemake_cmd)}')

    # Execute the command and log the output
    with open(log_file_path, "a") as log_file:
        subprocess.run(snakemake_cmd, stdout=log_file, stderr=subprocess.STDOUT)


def timed_senser(config_file: str) -> None:
    """
    Continuously execute the Snakemake workflow at a set time interval.

    Parameters:
        config_file (str): Path to the YAML configuration file.
    """
    logging.info("Starting timed Snakemake workflow")
    config_contents = load_config(config_file)
    check_interval = config_contents['check_intervals_seconds']
    snakemake_cores = config_contents['snakemake_cores']
    snakefile_path = pkg_resources.resource_filename('nanometa_live', 'Snakefile')
    should_remove_temp = config_contents.get('remove_temp_files') == "yes"

    try:
        while True:
            logging.info(f"Current interval: {check_interval} seconds.")
            execute_snakemake(snakefile_path, config_file, snakemake_cores, config_contents=config_contents)
            logging.info("Run completed.")
            time.sleep(check_interval)

    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
        if should_remove_temp:
            remove_temp_files(config_contents)