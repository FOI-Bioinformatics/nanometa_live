import os
import random
import time
import shutil
import sys
import argparse

def nano_sim():
    """
    A real-time nanopore simulator made to be used with test data. 
    The test data should be in the form of nanopore/guppy fastq.gz batch files.
    The fastq.gz files are copied one at a time at a specific time interval 
    to a simulated output folder to mimic the sequential output of batch 
    files from areal nanopore run.
    
    A file is copied every t seconds (min_delay =< t =< max_delay).
    """
    
    # Creates the object that contains the arguments passed to the shell command.
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input_folder', help="The folder where the test fastq.gz files are stored.")
    parser.add_argument('-o', '--output_folder', help="Where the files are copied to; the simulated nanopre output dir.")
    parser.add_argument('--min_delay', default = 1, type=float, help="The lower limit to the interval (minutes).")
    parser.add_argument('--max_delay', default = 2, type=float, help="The upper limit to the interval (minutes).")
    args = parser.parse_args()
    # Variables:
    input_folder = args.input_folder
    output_folder = args.output_folder
    min_delay = args.min_delay
    max_delay = args.max_delay
        
    # For debugging. if True: copied files are automatically removed upon user abort (ctrl+c)
    del_output_on_abort = False
    
    # Adjusts the delays to seconds.
    min_delay = min_delay * 60
    max_delay = max_delay * 60    

    # Creates the output dir if needed.
    if not os.path.exists(output_folder): 
        os.mkdir(output_folder)
    
    # List all the files in the original test data directory.
    file_list = os.listdir(input_folder) 
    
    # Info displayed to the user.
    print("Input folder: " + input_folder)
    print("Output_folder: " + output_folder)
    print("Minimum delay:", round(min_delay/60,1), "minutes")
    print("Maximum delay:", round(max_delay/60,1), "minutes")
    
    try:
        for i in file_list: # for each fastq.gz file
            # Wait t seconds between files.
            t = random.randint(min_delay, max_delay) 
            time.sleep(t)
            # Copy the file to the simulated nanopore dir.
            shutil.copy(os.path.join(input_folder, i), os.path.join(output_folder, i)) 
            print(i + " copied")
    except KeyboardInterrupt: # if user aborts the process
        print('\n----- aborted by user -----')
        if del_output_on_abort: # delete copied files if True (for debugging)
            print('----- removing output dir -----')
            shutil.rmtree(output_folder)

# Enables the function + args to be called from terminal.
if __name__ == '__main__':
    globals()[sys.argv[1]](sys.argv[2], 
                           sys.argv[3], 
                           sys.argv[4], 
                           sys.argv[5])
