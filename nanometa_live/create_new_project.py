import argparse
import os
import shutil
import pkg_resources

def create_new():
    """
    This script is used to create a new Nanometa project.
    A project directory is created with a config file specific
    for the project.
    The script is called as a bash command after installation.
    User instructions in readme.
    """
    # Creates the object that stores the arguments given to the bash command.
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--path', help="The path to the project directory.")
    args = parser.parse_args()
    # Extract the project path as a variable.
    project_path = args.path
    
    # The path to the general config file in the install directory.
    config_path = pkg_resources.resource_filename(__name__, 'config.yaml')
    
    # Create the specified project path. 
    if not os.path.exists(project_path):
        os.mkdir(project_path)
    
    # Make a project specific copy of the config file in the
    # user specified project path.
    shutil.copy(config_path, os.path.join(project_path, "config.yaml"))
    
    # Add the project path to the end of the config file. 
    # This makes all other scripts find the correct paths for each project.
    with open(os.path.join(project_path, "config.yaml"), 'a') as f:
        f.write('\n# Path to the main project folder.\nmain_dir: "' + project_path + '"')
    
#create_new()
    
