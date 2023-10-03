import requests
import json
import pandas as pd
import logging
import argparse
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
import zipfile
import os
from ruamel.yaml import YAML
import shutil
from typing import List, Dict, Union, NoReturn


from nanometa_live.helpers.config_utils import load_config
from nanometa_live.helpers.file_utils import (
    download_from_figshare,
    unzip_files
)

from nanometa_live import __version__

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



def main():
    # Command line arguments
    parser = argparse.ArgumentParser(description='Fetch and filter species data.')
    parser.add_argument('--config', default='config.yaml', help='Path to the configuration file. Default is config.yaml.')
    parser.add_argument('-p', '--path', default='', help="The path to the project directory.")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}',
                        help="Show the current version of the script.")
    args = parser.parse_args()


    # Determine the full path of the configuration file. If a path argument is provided, join it with the config filename.
    config_file_path = os.path.join(args.path, args.config) if args.path else args.config

    # Load the configuration file into a dictionary.
    #config_contents = load_config(config_file_path)

    # Provide the Figshare article ID from the URL
    figshare_article_id = 24233020

    # Prepare the folder where data files will be stored.
    demo_files_folder = os.path.join(args.path, 'demo-files')
    if not os.path.exists(demo_files_folder):
        os.makedirs(demo_files_folder)

    download_from_figshare(figshare_article_id, demo_files_folder)

    unzip_files(demo_files_folder)

    # Prepare the folder where data files will be stored.
    data_files_folder = os.path.join(args.path, 'data-files')
    if not os.path.exists(data_files_folder):
        os.makedirs(data_files_folder)

    species_file = os.path.join(demo_files_folder, 'species.txt')
    fastq_dir = os.path.join(demo_files_folder, 'nanometa_test_data')
    kraken_dir = os.path.join(demo_files_folder, 'kraken2.gtdb_bac120_4Gb')
    live_dir = os.path.join(demo_files_folder, 'live_reads')


    nanometa_new_cmd = [
        "nanometa-new",
        "-p", args.path,
        "--analysis_name", "Demo",
        "--species_of_interest", species_file,
        "--nanopore_output_directory", fastq_dir,
        "--kraken_db", kraken_dir
    ]
    # Execute the command
    try:
        subprocess.run(nanometa_new_cmd, check=True)
        logging.info("nanometa-new command executed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"nanometa-new command failed with error: {e}")

    nanometa_prepare_cmd = [
        "nanometa-prepare",
        "-p", args.path
    ]
    # Execute the command
    try:
        subprocess.run(nanometa_prepare_cmd, check=True)
        logging.info("nanometa-prepare command executed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"nanometa-prepare command failed with error: {e}")

    def runner_command(command):
        try:
            subprocess.run(command, shell=True, check=True)
            logging.info(f"Successfully executed: {command}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to execute: {command}. Error: {e}")

    commands = [
        f"nanometa-sim -i {fastq_dir} -o {live_dir}",
        f"nanometa-live -p {args.path}"
    ]

    with ThreadPoolExecutor() as executor:
        executor.map(runner_command, commands)



if __name__ == '__main__':
    main()
