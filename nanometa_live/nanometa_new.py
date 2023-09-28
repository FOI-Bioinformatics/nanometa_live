import argparse
import os
import shutil
import logging
from importlib.resources import files
from ruamel.yaml import YAML
import sys


from nanometa_live.helpers.config_utils import (
    create_new_project_directory,
    backup_config_file,
    copy_config_file,
    append_project_path_to_config,
    update_config_file_with_comments,
    update_species_of_interest,
    update_nested_dict,
	load_config
)
from nanometa_live.helpers.data_utils import read_species_from_file


from nanometa_live import __version__


# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_new():
    """
    Create a new Nanometa project by setting up the project directory and copying the config file.
    This function is intended to be called as a bash command after installation.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--path', help="The path to the project directory.")
    parser.add_argument('-c', '--config', default="config.yaml", help="The name of the config file. Default is 'config.yaml'.")
    parser.add_argument('--analysis_name', type=str, help="Name of the analysis.")
    parser.add_argument('--species_of_interest', type=str, help="File containing species of interest.")
    parser.add_argument('--warning_lower_limit', type=int, help="Warning lower limit.")
    parser.add_argument('--danger_lower_limit', type=int, help="Danger lower limit.")
    parser.add_argument('--nanopore_output_directory', type=str, help="Nanopore output directory.")
    parser.add_argument('--kraken_db', type=str, help="Kraken database.")
    parser.add_argument('--kraken_taxonomy', type=str, help="Kraken taxonomy.")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}', help="Show the current version of the script.")
    args = parser.parse_args()
    project_path = args.path

    # Show help message if no arguments are provided
    if not any(vars(args).values()):
        parser.print_help()
        return

    config_file_name = args.config  # Get the custom config file name
    project_path = os.path.abspath(args.path)



    # Show help message if no arguments are provided
    if not any(vars(args).values()) or project_path is None:
        parser.print_help()
        return

    logging.info("Starting new Nanometa project creation.")
    config_path = files('nanometa_live').joinpath('config.yaml')

    create_new_project_directory(project_path)
    backup_config_file(project_path, config_file_name)
    copy_config_file(config_path, project_path, config_file_name)

    config_file_path = os.path.join(args.path, args.config)
    config_contents = load_config(config_file_path)

    update_config_file_with_comments(args.path, args.config, 'main_dir', project_path)

    if args.analysis_name:
        update_config_file_with_comments(args.path, args.config, 'analysis_name', args.analysis_name)

    if args.species_of_interest:
        species_list = read_species_from_file(args.species_of_interest)
        if species_list:
            update_species_of_interest(project_path, config_file_name, species_list)

    if args.warning_lower_limit is not None:
        update_config_file_with_comments(args.path, args.config, 'warning_lower_limit', args.warning_lower_limit)

    if args.danger_lower_limit is not None:
        update_config_file_with_comments(args.path, args.config, 'danger_lower_limit', args.danger_lower_limit)

    if args.nanopore_output_directory:
        nanopore_output_directory = os.path.abspath(args.nanopore_output_directory)
        update_config_file_with_comments(args.path, args.config, 'nanopore_output_directory',
                                         nanopore_output_directory)

    if args.kraken_db:
        kraken_db = os.path.abspath(args.kraken_db)
        update_config_file_with_comments(args.path, args.config, 'kraken_db', kraken_db)

    if args.kraken_taxonomy:
        update_config_file_with_comments(args.path, args.config, 'kraken_taxonomy', args.kraken_taxonomy)

    if not args.analysis_name:
        analysis_name=config_contents["analysis_name"]
    else:
        analysis_name=args.analysis_name
    logging.info(f"Nanometa project ({analysis_name}) created successfully.")

def main():
    """

    Main function to execute the create_new function.
    """
    create_new()


if __name__ == "__main__":
    main()
