import argparse
import os
import shutil
import logging
from importlib.resources import files
from ruamel.yaml import YAML
__version__="0.2.1"


# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config(config_file):
    """
    Load configuration settings from a YAML file using ruamel.yaml.

    Parameters:
        config_file (str): Path to the YAML configuration file.

    Returns:
        dict: Dictionary containing the configuration settings.
    """
    logging.info(f"Loading configuration from {config_file}")
    yaml = YAML(typ='safe')
    with open(config_file, 'r') as cf:
        return yaml.load(cf)

def create_new_project_directory(project_path):
    """
    Create a new directory for the Nanometa project if it doesn't exist.

    Parameters:
        project_path (str): The path where the project directory will be created.

    Returns:
        bool: True if the directory exists or was successfully created, False otherwise.
    """
    logging.info(f"Creating project directory at {project_path}")
    if not os.path.exists(project_path):
        os.mkdir(project_path)
        logging.info(f"Project directory created at {project_path}")
    else:
        logging.info(f"Project directory already exists at {project_path}")
    return os.path.exists(project_path)

def backup_config_file(project_path, config_file_name):
    """
    Backup the existing config file by renaming it with a .bak extension.

    Parameters:
        project_path (str): The path to the project directory where the config file is located.

    Returns:
        bool: True if the backup is successful or if there is no existing config file to backup; False otherwise.
    """
    config_file_path = os.path.join(project_path, config_file_name)
    backup_file_path = os.path.join(project_path, f"{config_file_name}.bak")

    if os.path.exists(config_file_path):
        shutil.move(config_file_path, backup_file_path)
        logging.info(f"Existing config file backed up as {config_file_name}.bak")
    return True

def copy_config_file(config_path, project_path, config_file_name):
    """
    Copy the general config file to the specified project directory.

    Parameters:
        config_path (str): The path to the general config file.
        project_path (str): The path to the project directory.

    Returns:
        bool: True if the config file was successfully copied, False otherwise.
    """
    logging.info(f"Copying config file from {config_path} to {project_path}")
    shutil.copy(config_path, os.path.join(project_path, config_file_name))
    logging.info("Config file copied successfully.")
    return os.path.exists(os.path.join(project_path, config_file_name))

def append_project_path_to_config(project_path, config_file_name):
    """
    Append the project path to the config file. This helps other scripts find the correct paths.

    Parameters:
        project_path (str): The path to the project directory.

    Returns:
        bool: True if the project path was successfully appended, False otherwise.
    """
    logging.info(f"Appending project path {project_path} to config file")
    with open(os.path.join(project_path, config_file_name), 'a') as f:
        f.write('\n# Path to the main project folder.\nmain_dir: "' + project_path + '"')
    logging.info("Project path appended to config file successfully.")
    return True


def read_species_from_file(filename):
    try:
        with open(filename, 'r') as f:
            species_list = [line.strip() for line in f if line.strip()]

        if species_list:
            logging.info(f"Read {len(species_list)} species from {filename}.")
            for i, species in enumerate(species_list, 1):
                logging.info(f"  {i}. {species}")
        else:
            logging.warning(f"No species found in {filename}.")

        return species_list

    except FileNotFoundError:
        logging.error(f"File not found: {filename}")
        return []
    except PermissionError:
        logging.error(f"Permission denied: {filename}")
        return []

# Update nested keys in a dictionary
def update_nested_dict(d, keys, value):
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value

# Update variables in the config file
def update_config_file_with_comments(project_path, config_file_name, variable, new_value):
    config_file_path = os.path.join(project_path, config_file_name)
    try:
        yaml = YAML()
        yaml.preserve_quotes = True
        with open(config_file_path, 'r') as f:
            config_data = yaml.load(f)

        update_nested_dict(config_data, variable.split('.'), new_value)

        with open(config_file_path, 'w') as f:
            yaml.dump(config_data, f)

        logging.info(f"Updated {variable} in config file to {new_value}.")
        return True
    except Exception as e:
        logging.error(f"Failed to update config file: {e}")
        return False

def update_species_of_interest(project_path, config_file_name, species_list):
    if species_list:
        species_data = [{"name": species, "taxid": ""} for species in species_list]
        return update_config_file_with_comments(project_path, config_file_name, "species_of_interest", species_data)
    else:
        return False


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
