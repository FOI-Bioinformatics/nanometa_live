'''
A script that runs in the background, executing the snakemake 
workflow at a set time interval.

The time interval and nr of cores can be set in the config.yaml file.

Also removes unecessary temp files upon used exit with ctrl+C.
Ctrl+C might need to be pressed twice or more, since it will first disrupt the 
snakemake workflow while this script will continue to run unless ctrl+C
is pressed again.
'''

import time
import os
import yaml
import pkg_resources
import shutil

def timed_senser():
    # This need to be filddled with for packaging !!!!!!!!!!!!!!!! -fiddled
    # This makes the system find the proper snakefile after installation.
    snakefile_path = pkg_resources.resource_filename('nanometa_live', 'Snakefile')
    # Load variables from config file.
    with open('config.yaml', 'r') as cf:
        config_contents = yaml.safe_load(cf)
        # Time between checks.
        t = config_contents['check_intervals_seconds']
        # How many cores to assign snakemake.
        snakemake_cores = config_contents['snakemake_cores'] 
        remove_temp_files = config_contents['remove_temp_files'] # yes or no
        
    # Paths to temp files that will be removed when the user aborts the program.
    kraken_results_dir = os.path.join(config_contents["main_dir"], 'kraken_results/')
    qc_dir = os.path.join(config_contents["main_dir"], 'qc_data/')
    qc_file_to_keep = os.path.join(config_contents["main_dir"], 'qc_data/cumul_qc.txt')
    validation_placeholders = os.path.join(config_contents["main_dir"], 'validation_fastas/placeholders')
    force_valid_file = os.path.join(config_contents["main_dir"], 'validation_fastas/force_validation.txt')
    force_blast_file = os.path.join(config_contents["main_dir"], 'blast_result_files/force_blast.txt')
    
    while True: # endless loop
        try:
            # time delay
            time.sleep(t)
            print("\n----- running -----")
            print("current interval:", str(t), "seconds.")
            # rememeber to change this when packaging !!!!!!!!!!!!! -changed
            # The command that this script will send to the shell.
            # rerun-incomplete parameter important:
            # makes snakemake rerun half-processed files from interrupted runs.
            system_cmd = "snakemake --cores " + str(snakemake_cores) + " --rerun-incomplete --use-conda --snakefile " + str(snakefile_path)
            print('shell command: ' + system_cmd)
            # Run the snakeflow as a system process.
            # This should probably be a popen, but will do for now.
            os.system(system_cmd)
            print("\n----- run completed -----")
        
        # Happens upon ctrl+C:
        except KeyboardInterrupt:
            print("\n\n----- interrupted by user -----")
            # Cleaning up temp files if not disabled from config.
            if remove_temp_files == "yes":
                print('\nCleaning up temp files.')
                if os.path.exists(kraken_results_dir):
                    shutil.rmtree(kraken_results_dir)
                    print('\nKraken results directory removed.')
                if os.path.exists(qc_dir):
                    for filename in os.listdir(qc_dir):
                        file_path = os.path.join(qc_dir, filename)
                        if file_path != qc_file_to_keep and os.path.isfile(file_path):
                            os.remove(file_path)
                    print('\nQC files removed. Cumulative file kept.')
                if os.path.exists(validation_placeholders):
                    shutil.rmtree(validation_placeholders)
                    print('\nValidation placeholders removed.')
                if os.path.isfile(force_valid_file):
                    os.remove(force_valid_file)
                    print('\nForce_validation file removed.')
                if os.path.isfile(force_blast_file):
                    os.remove(force_blast_file)
                    print('\nForce_blast file removed.')
                print('\ndone')
            
            break

# comment out when packaging !!!!!!!!!!!!!!! -done    
#timed_senser()