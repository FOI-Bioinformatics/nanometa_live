import time
import os
from ruamel.yaml import YAML
import pkg_resources
import shutil
import argparse
import logging
import subprocess
import sys
from typing import List, Dict, Union, NoReturn


from nanometa_live.helpers.config_utils import update_nested_dict, load_config
from nanometa_live.helpers.pipeline_utils import execute_snakemake, timed_senser
from nanometa_live.helpers.file_utils import remove_temp_files


from nanometa_live import __version__

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def main():
    """
    Main function that parses command-line arguments and executes the timed_senser function.
    """

    parser = argparse.ArgumentParser(description='A script that runs the Snakemake workflow at a set time interval.')
    parser.add_argument('--config', default='config.yaml', help='Path to the configuration file. Default is config.yaml.')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}', help="Show the current version of the script.")
    parser.add_argument('-p', '--path', default='', help="The path to the project directory.")
    args = parser.parse_args()


    if '--version' not in sys.argv:
        # Initialize logging only if '--version' is not in the argument list
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.info("nanometa_live backend started")

    # Check if any arguments were provided
    if not any(vars(args).values()):
        print("No arguments provided. Using default values.")
        onfig_contents = load_config('config.yaml')
        timed_senser('config.yaml', config_contents)
    else:
        if hasattr(args, 'version') and args.version:
            parser.print_version()
        else:
            config_file_path = os.path.join(args.path, args.config) if args.path else args.config
            config_contents = load_config(config_file_path)
            timed_senser(config_file_path, config_contents)

if __name__ == "__main__":
    main()
