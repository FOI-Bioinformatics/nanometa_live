import argparse
import os
import shutil
import logging
import pkg_resources
from nanometa_live import __version__  # Import the version number


# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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


def create_new():
    """
    Create a new Nanometa project by setting up the project directory and copying the config file.
    This function is intended to be called as a bash command after installation.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--path', help="The path to the project directory.")
    parser.add_argument('-c', '--config', default="config.yaml",
                        help="The name of the config file. Default is 'config.yaml'.")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}', help="Show the current version of the script.")
    args = parser.parse_args()
    project_path = args.path

    # Show help message if no arguments are provided
    if not any(vars(args).values()):
        parser.print_help()
        return

    config_file_name = args.config  # Get the custom config file name
    project_path = args.path

    # Show help message if no arguments are provided
    if not any(vars(args).values()) or project_path is None:
        parser.print_help()
        return

    logging.info("Starting new Nanometa project creation.")
    config_path = pkg_resources.resource_filename(__name__, "config.yaml")

    create_new_project_directory(project_path)
    backup_config_file(project_path, config_file_name)
    copy_config_file(config_path, project_path, config_file_name)
    append_project_path_to_config(project_path, config_file_name)
    logging.info("Nanometa project created successfully.")

def main():
    """
    Main function to execute the create_new function.
    """
    create_new()


if __name__ == "__main__":
    main()
