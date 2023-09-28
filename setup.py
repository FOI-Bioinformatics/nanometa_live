"""
Setup file for the Nanometa Live project.

This script specifies the Python packages, additional files, and entry points needed for the project.
It also creates the bash commands used to run the program and maps them to the corresponding Python functions.

Installation instructions:
- Detailed installation instructions can be found in the README file on GitHub.

Structure:
- `name`: Specifies the package name.
- `version`: Specifies the package version, imported from __init__.py.
- `description`: Brief description of the package.
- `packages`: Lists the Python packages included in the project.
- `package_data`: Specifies additional non-Python files and Snakemake scripts.
- `entry_points`: Defines the bash commands and maps them to Python functions.
- `data_files`: Ensures that specified files are found after installation.
- `install_requires`: Lists the package dependencies, read from requirements.txt.

"""

from setuptools import setup, find_packages
import os

# Import the version number
__version__="0.2.1"

# Read requirements.txt and store its content in a list
with open("requirements.txt", "r") as f:
    requirements = f.read().splitlines()

setup(
      name = "Nanometa_Live",
      version = __version__,
      description = "Real-time metagenomic analysis.",
      # Specifying python packages.
      packages = find_packages(),
      # Specifying non-pyscript files and snakemake scripts.
      package_data={'nanometa_live': ['Snakefile',
                                      'config.yaml',
                                      'snakemake_envs/*.yaml',
                                      'snakemake_scripts/*.py']
                    },
      # These are the bash commands and the functions they map to.
      # "run_app" is a solution to make the main gui script into a command,
      # since a function needs to be specified.
      entry_points = {'console_scripts':
                      ['nanometa-sim = nanometa_live.nanopore_simulator:nano_sim', # nanopore simulator
                       'nanometa-new = nanometa_live.nanometa_new:main', # create new project
                       'nanometa-blastdb = nanometa_live.build_blast_db:build_blast', # create blast validation databases
                       'nanometa-backend = nanometa_live.nanometa_backend:main', # run backend pipeline
                       'nanometa-gui = nanometa_live.nanometa_gui:run_app', # run gui
                       'nanometa-live = nanometa_live.nanometa_runner:main',  # wrapper to run both backend and GUI.
                       'nanometa-prepare = nanometa_live.nanometa_prepare:main'  # Autmatically download genomes and create blast databases
                       ]
                      },
      # Makes sure the files are found after install.
      data_files=[('nanometa_live/',['nanometa_live/config.yaml']),
                  ('nanometa_live/snakemake_envs',
                   ['nanometa_live/snakemake_envs/' + f for f in os.listdir('nanometa_live/snakemake_envs') if f.endswith('.yaml')])],
      install_requires=requirements  # Read from requirements.txt
      )
