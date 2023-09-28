import os
import random
import time
import shutil
import argparse
import logging

from nanometa_live import __version__

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def nano_sim():
    """
    A real-time nanopore simulator for use with test data in the form of nanopore/guppy fastq.gz batch files.
    Files are copied at random intervals to a simulated output folder to mimic a real nanopore run.
    """

    # Argument parsing
    parser = argparse.ArgumentParser(description="A real-time nanopore simulator.")
    parser.add_argument('-i', '--input_folder', required=True, help="Folder containing test fastq.gz files.")
    parser.add_argument('-o', '--output_folder', required=True, help="Simulated nanopore output directory.")
    parser.add_argument('--min_delay', default=1, type=float, help="Minimum interval between file copies (minutes).")
    parser.add_argument('--max_delay', default=2, type=float, help="Maximum interval between file copies (minutes).")
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}',
                        help="Show the current version of the script.")
    args = parser.parse_args()

    logging.info("Starting nanopore simulation.")
    logging.info(f"Using version {__version__} of the script.")

    # Variables
    input_folder = args.input_folder
    output_folder = args.output_folder
    min_delay = args.min_delay * 60  # Convert to seconds
    max_delay = args.max_delay * 60  # Convert to seconds

    # Create output directory if it doesn't exist
    if not os.path.exists(output_folder):
        os.mkdir(output_folder)
        logging.info(f"Output directory created at {output_folder}")
    else:
        logging.info(f"Output directory already exists at {output_folder}")

    # List all files in the input directory
    file_list = os.listdir(input_folder)
    logging.info(f"Found {len(file_list)} files in the input folder.")

    try:
        for file in file_list:
            delay = random.randint(min_delay, max_delay)
            logging.info(f"Waiting for {round(delay / 60, 1)} minutes before copying the next file.")
            time.sleep(delay)
            shutil.copy(os.path.join(input_folder, file), os.path.join(output_folder, file))
            logging.info(f"{file} copied successfully.")
    except KeyboardInterrupt:
        logging.warning("Process aborted by user.")


if __name__ == '__main__':
    nano_sim()
