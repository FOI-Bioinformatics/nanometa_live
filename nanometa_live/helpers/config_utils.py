import os
import logging
import subprocess
import shutil
from typing import List, Dict, Union, NoReturn
from ruamel.yaml import YAML
import pandas as pd

def load_config(config_file: str) -> Union[Dict, None]:
    """
    Load configuration settings from a YAML file using ruamel.yaml.

    Parameters:
        config_file (str): Path to the YAML configuration file.

    Returns:
        Union[Dict, None]: Dictionary containing the configuration settings, or None if an error occurs.
    """
    logging.info(f"Attempting to load configuration from {config_file}")

    try:
        yaml = YAML(typ='safe')
        with open(config_file, 'r') as cf:
            config_data = yaml.load(cf)
        logging.info(f"Successfully loaded configuration from {config_file}")
        return config_data
    except FileNotFoundError:
        logging.error(f"Configuration file {config_file} not found")
    except PermissionError:
        logging.error(f"Permission denied: Cannot read {config_file}")
    except Exception as e:
        logging.error(f"Failed to load configuration from {config_file}. Exception: {e}")
    return None

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

# Update nested keys in a dictionary
def update_nested_dict(d, keys, value):
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def update_yaml_config_with_taxid(df: pd.DataFrame, yaml_config_path: str):
    logging.info("Starting the process to update YAML config file with taxid.")

    if "Species" not in df.columns or "Tax_ID" not in df.columns:
        logging.error("DataFrame is missing either 'Species' or 'Tax_ID' columns. Aborting.")
        raise ValueError("DataFrame is missing either 'Species' or 'Tax_ID' columns.")

    species_taxid_dict = dict(zip(df['Species'], df['Tax_ID']))

    yaml = YAML()

    try:
        with open(yaml_config_path, 'r') as stream:
            yaml_data = yaml.load(stream)
    except Exception as e:
        logging.error(f"An error occurred while reading the YAML file: {e}")
        raise

    # Directly targeting the 'species_of_interest' section
    species_of_interest = yaml_data.get('species_of_interest', [])

    try:
        for entry in species_of_interest:
            species_name = entry.get('name', '')
            if species_name in species_taxid_dict:
                entry['taxid'] = species_taxid_dict[species_name]
    except Exception as e:
        logging.error(f"An error occurred while updating the YAML data: {e}")
        raise

    try:
        with open(yaml_config_path, 'w') as stream:
            yaml.dump(yaml_data, stream)
    except Exception as e:
        logging.error(f"An error occurred while writing the updated YAML data: {e}")
        raise

    logging.info(f"Successfully updated YAML config file at {yaml_config_path} with taxid.")



