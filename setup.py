'''
Setup file for Nanometa Live.
Specifies python packages and additional files. Creates the bash commands used
to run the program and maps to the functions they execute.

Installation instructions can be found in the readme file on github.

'''

from setuptools import setup
import os

setup(
      name = "Nanometa_Live",
      version = "0.1.0",
      description = "Real-time metagenomic analysis.",
      # Specifying python packages.
      packages = ['nanometa_live', 
                  'nanometa_live.gui_scripts'],
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
                       'nanometa-new = nanometa_live.create_new_project:create_new', # create new project
                       'nanometa-blastdb = nanometa_live.build_blast_db:build_blast', # create blast validation databases
                       'nanometa-pipe = nanometa_live.nanometa_backend:timed_senser', # run backend pipeline
                       'nanometa = nanometa_live.nanometa_gui:run_app' # run gui
                       ]
                      },
      # Makes sure the files are found after install.
      data_files=[('nanometa_live/',['nanometa_live/config.yaml']),
                  ('nanometa_live/snakemake_envs', 
                   ['nanometa_live/snakemake_envs/' + f for f in os.listdir('nanometa_live/snakemake_envs') if f.endswith('.yaml')])]
          
      )
