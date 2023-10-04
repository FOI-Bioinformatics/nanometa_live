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

def main():
    """
    Create a new Nanometa project by setting up the project directory and copying the config file.
    This function is intended to be called as a bash command after installation.
    """

    parser = argparse.ArgumentParser()
    # Main config
    parser.add_argument('-p', '--path', help="The path to the project directory.")
    parser.add_argument('-c', '--config', default="config.yaml", help="The name of the config file. Default is 'config.yaml'.")

    # GUI Config
    parser.add_argument('--analysis_name', type=str, help="Name of the analysis")
    parser.add_argument('--species_of_interest', type=str, help="Path to file containing species of interest")
    parser.add_argument('--danger_lower_limit', type=int, help="Danger cutoff for species abundance")
    parser.add_argument('--taxonomic_hierarchy_letters', type=str, nargs='*', help="Taxonomic hierarchy levels used by Kraken2")
    parser.add_argument('--default_hierarchy_letters', type=str, nargs='*', help="Default taxonomy levels displayed in the Sankey plot")
    parser.add_argument('--default_reads_per_level', type=int, help="Default number of entries per taxonomy level in the Sankey plot")
    parser.add_argument('--update_interval_seconds', type=int, help="GUI update frequency in seconds")
    parser.add_argument('--gui_port', type=str, help="GUI port number")

    # Workflow Config
    parser.add_argument('--local_package_management', type=str, help="Package management for Snakemake (None/conda)")
    parser.add_argument('--conda_frontend', type=str, help="Conda frontend to use (mamba/conda)")
    parser.add_argument('--nanopore_output_directory', type=str, help="Path to Nanopore output directory")
    parser.add_argument('--remove_temp_files', type=str, help="Whether to remove temporary files (yes/no)")
    parser.add_argument('--check_intervals_seconds', type=int, help="Workflow frequency in seconds")
    parser.add_argument('--snakemake_cores', type=int, help="Number of cores for Snakemake")
    parser.add_argument('--kraken_cores', type=int, help="Number of cores for Kraken2")
    parser.add_argument('--validation_cores', type=int, help="Number of cores for KrakenTools")
    parser.add_argument('--blast_cores', type=int, help="Number of cores for BLAST")
    parser.add_argument('--kraken_db', type=str, help="Path to Kraken2 database")
    parser.add_argument('--kraken_taxonomy', type=str, help="Type of taxonomy for Kraken (gtdb/ncbi)")
    parser.add_argument('--kraken_memory_mapping', type=str, help="Memory mapping for Kraken2")
    parser.add_argument('--blast_validation', type=bool, help="Turn BLAST validation on/off")
    parser.add_argument('--min_perc_identity', type=float, help="Minimum percent identity for BLAST")
    parser.add_argument('--e_val_cutoff', type=float, help="E-value cutoff for BLAST")

    # Version
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


    # GUI Config
    if args.analysis_name:
        update_config_file_with_comments(args.path, args.config, 'analysis_name', args.analysis_name)

    if args.species_of_interest:
        species_list = read_species_from_file(args.species_of_interest)
        if species_list:
            update_species_of_interest(project_path, config_file_name, species_list)

    if args.danger_lower_limit is not None:
        update_config_file_with_comments(args.path, args.config, 'danger_lower_limit', args.danger_lower_limit)

    if args.taxonomic_hierarchy_letters:
        update_config_file_with_comments(args.path, args.config, 'taxonomic_hierarchy_letters',
                                         args.taxonomic_hierarchy_letters)

    if args.default_hierarchy_letters:
        update_config_file_with_comments(args.path, args.config, 'default_hierarchy_letters',
                                         args.default_hierarchy_letters)

    if args.default_reads_per_level is not None:
        update_config_file_with_comments(args.path, args.config, 'default_reads_per_level',
                                         args.default_reads_per_level)

    if args.update_interval_seconds is not None:
        update_config_file_with_comments(args.path, args.config, 'update_interval_seconds',
                                         args.update_interval_seconds)

    if args.gui_port:
        update_config_file_with_comments(args.path, args.config, 'gui_port', args.gui_port)

    # Workflow Config
    if args.local_package_management:
        update_config_file_with_comments(args.path, args.config, 'local_package_management',
                                         args.local_package_management)

    if args.conda_frontend:
        update_config_file_with_comments(args.path, args.config, 'conda_frontend', args.conda_frontend)

    if args.nanopore_output_directory:
        nanopore_output_directory = os.path.abspath(args.nanopore_output_directory)
        update_config_file_with_comments(args.path, args.config, 'nanopore_output_directory', nanopore_output_directory)

    if args.remove_temp_files:
        update_config_file_with_comments(args.path, args.config, 'remove_temp_files', args.remove_temp_files)

    if args.check_intervals_seconds is not None:
        update_config_file_with_comments(args.path, args.config, 'check_intervals_seconds',
                                         args.check_intervals_seconds)

    if args.snakemake_cores is not None:
        update_config_file_with_comments(args.path, args.config, 'snakemake_cores', args.snakemake_cores)

    if args.kraken_cores is not None:
        update_config_file_with_comments(args.path, args.config, 'kraken_cores', args.kraken_cores)

    if args.validation_cores is not None:
        update_config_file_with_comments(args.path, args.config, 'validation_cores', args.validation_cores)

    if args.blast_cores is not None:
        update_config_file_with_comments(args.path, args.config, 'blast_cores', args.blast_cores)

    if args.kraken_db:
        kraken_db = os.path.abspath(args.kraken_db)
        update_config_file_with_comments(args.path, args.config, 'kraken_db', kraken_db)

    if args.kraken_taxonomy:
        update_config_file_with_comments(args.path, args.config, 'kraken_taxonomy', args.kraken_taxonomy)

    if args.kraken_memory_mapping:
        update_config_file_with_comments(args.path, args.config, 'kraken_memory_mapping', args.kraken_memory_mapping)

    if args.blast_validation is not None:
        update_config_file_with_comments(args.path, args.config, 'blast_validation', args.blast_validation)

    if args.min_perc_identity is not None:
        update_config_file_with_comments(args.path, args.config, 'min_perc_identity', args.min_perc_identity)

    if args.e_val_cutoff is not None:
        update_config_file_with_comments(args.path, args.config, 'e_val_cutoff', args.e_val_cutoff)

    if not args.analysis_name:
        analysis_name=config_contents["analysis_name"]
    else:
        analysis_name=args.analysis_name

    update_config_file_with_comments(args.path, args.config, 'main_dir', project_path)

    logging.info(f"Nanometa project ({analysis_name}) created successfully.")


if __name__ == "__main__":
    main()
