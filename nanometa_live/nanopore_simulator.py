#!/usr/bin/env python3

import random
import time
import shutil
import argparse
import logging
import gzip
import sys
from pathlib import Path

import pyfastx  # Importing pyfastx for efficient FASTQ indexing and access

from nanometa_live import __version__

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)


def get_base_name(file_path):
    """
    Extracts the base name of the file without any suffixes.
    For example, 'demo.fastq.gz' becomes 'demo'.
    """
    base = file_path.name
    for suffix in file_path.suffixes:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    return base


def copy_files_simulation(input_folder, output_folder, min_delay, max_delay, prefix):
    """
    Simulate nanopore reads by copying .fastq and .fastq.gz files from input_folder to output_folder at random intervals.
    Compresses .fastq files to .fastq.gz in the output folder.
    Delays are rounded to integer seconds.
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)

    # Ensure output directory exists
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        logging.debug(f"Ensured that output directory exists: {output_path}")
    except PermissionError:
        logging.error(f"Permission denied while creating output directory: {output_folder}. Check your permissions.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An error occurred while creating the output directory: {e}")
        sys.exit(1)

    # Filter files ending with .fastq or .fastq.gz
    file_list = [
        f for f in input_path.iterdir()
        if f.is_file() and (f.suffix == '.fastq' or f.suffixes[-2:] == ['.fastq', '.gz'])
    ]

    if not file_list:
        logging.error(f"No .fastq or .fastq.gz files found in the input folder: {input_folder}")
        sys.exit(1)
    logging.info(f"Found {len(file_list)} .fastq/.fastq.gz files in the input folder.")

    try:
        for file in file_list:
            delay = random.randint(int(min_delay), int(max_delay))  # Integer seconds
            logging.info(f"Waiting for {delay} seconds before copying the next file.")
            time.sleep(delay)
            src = file
            base_name = get_base_name(file)

            if file.suffix == '.fastq' and file.suffixes[-2:] != ['.fastq', '.gz']:
                # Compress and rename to .fastq.gz
                dst_filename = f"{prefix}_{base_name}.fastq.gz" if prefix else f"subsampled_{base_name}.fastq.gz"
                dst = output_path / dst_filename
                logging.info(f"Compressing and copying {file.name} to {dst_filename}.")
                with src.open('rb') as f_in, gzip.open(dst, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            else:
                # Copy as-is, optionally adding prefix
                dst_filename = f"{prefix}_{file.name}" if prefix else file.name
                dst = output_path / dst_filename
                shutil.copy(src, dst)
                logging.info(f"Copied {file.name} to {output_folder}.")
    except KeyboardInterrupt:
        logging.warning("Process aborted by user.")
        sys.exit(1)
    except PermissionError:
        logging.error(f"Permission denied while accessing files in {output_folder}. Check your permissions.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred during file copying: {e}")
        sys.exit(1)


def subsample_reads_simulation(input_fastq, output_folder, num_reads_per_file, num_files, min_delay, max_delay, prefix):
    """
    Simulate nanopore reads by subsampling reads from input_fastq and writing them to multiple output fastq.gz files in output_folder at random intervals.
    Each output file receives 'num_reads_per_file' reads, written sequentially.
    Utilizes pyfastx for efficient read access.
    Delays are rounded to integer seconds.
    """
    input_fastq_path = Path(input_fastq)
    output_path = Path(output_folder)

    # Verify input file
    if not input_fastq_path.is_file():
        logging.error(f"Input FASTQ file does not exist: {input_fastq}")
        sys.exit(1)
    if input_fastq_path.suffixes[-2:] not in [['.fastq', '.gz'], ['.fq', '.gz']]:
        logging.error("Input file must be a compressed .fastq.gz or .fq.gz file.")
        sys.exit(1)

    # Ensure output directory exists
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        logging.debug(f"Ensured that output directory exists: {output_path}")
    except PermissionError:
        logging.error(f"Cannot create or write to output directory: {output_folder}. Check your permissions.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An error occurred while creating the output directory: {e}")
        sys.exit(1)

    logging.info(f"Output directory is set to: {output_folder}")

    # Initialize pyfastx for the input FASTQ file
    try:
        fq = pyfastx.Fastq(str(input_fastq_path), build_index=True)
    except FileNotFoundError:
        logging.error(f"File not found: {input_fastq}")
        sys.exit(1)
    except IOError as e:
        logging.error(f"I/O error({e.errno}): {e.strerror}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred while initializing pyfastx: {e}")
        sys.exit(1)

    total_reads = len(fq)
    logging.info(f"Total reads in input file: {total_reads}")

    # Calculate total reads needed
    total_reads_needed = num_reads_per_file * num_files
    if total_reads_needed > total_reads:
        max_possible_files = total_reads // num_reads_per_file
        if max_possible_files == 0:
            logging.error(f"Number of reads per file ({num_reads_per_file}) exceeds total reads available ({total_reads}).")
            sys.exit(1)
        logging.warning(
            f"Requested total number of reads ({total_reads_needed}) exceeds total reads available ({total_reads}). "
            f"Adjusting to {max_possible_files} files with {num_reads_per_file} reads each."
        )
        num_files = max_possible_files
        total_reads_needed = num_reads_per_file * num_files
        logging.info(f"Adjusted number of output files to {num_files} based on available reads.")

    if total_reads_needed == 0:
        logging.error("No reads to subsample. Please check your --num_reads and --num_files parameters.")
        sys.exit(1)

    # Randomly select total_reads_needed unique read indices
    try:
        selected_indices = sorted(random.sample(range(total_reads), total_reads_needed))
    except ValueError as e:
        logging.error(f"Sampling error: {e}")
        sys.exit(1)
    logging.info(f"Subsampling {num_reads_per_file} reads into {num_files} files.")

    # Assign reads to files sequentially
    reads_per_file = {}
    for i in range(num_files):
        start = i * num_reads_per_file
        end = start + num_reads_per_file
        reads_per_file[i] = selected_indices[start:end]

    # Write reads to output files sequentially
    logging.info("Writing reads to output files sequentially...")
    for file_idx in range(num_files):
        # Construct output filename with prefix
        prefix_str = f"{prefix}_" if prefix else ""
        base_name = get_base_name(input_fastq_path)
        output_fastq = output_path / f"{prefix_str}subsampled_{file_idx + 1}_{base_name}.fastq.gz"
        logging.info(f"Writing {num_reads_per_file} reads to {output_fastq}...")
        try:
            with gzip.open(output_fastq, 'wt') as outfile:
                for read_num, read_index in enumerate(reads_per_file[file_idx], start=1):
                    try:
                        read = fq[read_index]  # Access read using pyfastx
                        outfile.write(f"@{read.name}\n{read.seq}\n+\n{read.qual}\n")
                    except AttributeError as e:
                        logging.error(f"AttributeError while accessing read at index {read_index}: {e}")
                        sys.exit(1)
                    except Exception as e:
                        logging.error(f"Unexpected error while writing read {read_num} to {output_fastq}: {e}")
                        sys.exit(1)
            logging.info(f"Wrote {num_reads_per_file} reads to {output_fastq}.")
            delay = random.randint(int(min_delay), int(max_delay))  # Integer seconds
            logging.info(f"Waiting for {delay} seconds before writing the next file.")
            time.sleep(delay)
        except PermissionError:
            logging.error(f"Permission denied while writing to {output_fastq}. Check your permissions.")
            sys.exit(1)
        except IOError as e:
            logging.error(f"I/O error({e.errno}): {e.strerror} while writing to {output_fastq}.")
            sys.exit(1)
        except KeyboardInterrupt:
            logging.warning("Process aborted by user.")
            sys.exit(1)
        except Exception as e:
            logging.error(f"An unexpected error occurred while writing to {output_fastq}: {e}")
            sys.exit(1)

    logging.info(f"Subsampled reads successfully written to {num_files} files in {output_folder}.")


def nano_sim():
    """
    A real-time nanopore simulator for use with test data in the form of nanopore/guppy fastq.gz batch files.
    Either copies .fastq/.fastq.gz files from a master folder to outputfolder at random intervals (compressing .fastq to .fastq.gz),
    or subsamples reads from a fastq.gz file into multiple output files.
    """
    # Argument parsing
    parser = argparse.ArgumentParser(
        description="A real-time nanopore simulator.",
        epilog="""
        Usage Examples:
        
        1. Simulate by copying files from a folder:
           python nanopore_simulator.py -i /path/to/input_folder -o /path/to/output_folder --min_delay 2 --max_delay 5 --prefix sample

        2. Simulate by subsampling reads:
           python nanopore_simulator.py -f /path/to/input.fastq.gz -o /path/to/output_folder -n 100 --num_files 5 --min_delay 1 --max_delay 2 --prefix subsample
        """
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-i",
        "--input_folder",
        help="Folder containing test .fastq and .fastq.gz files.",
    )
    group.add_argument(
        "-f",
        "--input_fastq",
        help="A single compressed fastq.gz file to subsample reads from.",
    )
    parser.add_argument(
        "-o",
        "--output_folder",
        required=True,
        help="Simulated nanopore output directory.",
    )
    parser.add_argument(
        "--min_delay",
        default=1,
        type=float,
        help="Minimum interval between file copies or file writes (seconds). Must be non-negative.",
    )
    parser.add_argument(
        "--max_delay",
        default=2,
        type=float,
        help="Maximum interval between file copies or file writes (seconds). Must be non-negative and >= min_delay.",
    )
    # Subsampling specific arguments
    parser.add_argument(
        "-n",
        "--num_reads",
        type=int,
        help="Number of reads to subsample per output file when using --input_fastq. Must be positive.",
    )
    parser.add_argument(
        "--num_files",
        type=int,
        default=1,
        help="Number of output files to generate when using --input_fastq. Must be at least 1. Default is 1.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="",
        help="Prefix for the output subsampled FASTQ.gz files.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the current version of the script.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Increase output verbosity to DEBUG level.",
    )
    args = parser.parse_args()

    # Adjust logging level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Verbose mode enabled.")

    # Validate delay arguments
    if args.min_delay < 0 or args.max_delay < 0:
        logging.error("Delays must be non-negative.")
        sys.exit(1)
    if args.min_delay > args.max_delay:
        logging.error("Minimum delay cannot be greater than maximum delay.")
        sys.exit(1)

    # Validate subsampling arguments
    if args.input_fastq:
        if args.num_reads is None:
            logging.error("Number of reads per file (--num_reads) must be specified when using --input_fastq.")
            sys.exit(1)
        if args.num_reads <= 0:
            logging.error("Number of reads per file (--num_reads) must be a positive integer.")
            sys.exit(1)
        if args.num_files < 1:
            logging.error("Number of output files (--num_files) must be at least 1.")
            sys.exit(1)
        if args.prefix and not args.prefix.isidentifier():
            logging.error("Prefix must be a valid identifier without spaces or special characters.")
            sys.exit(1)

    # Validate prefix (if pattern-based naming is implemented in the future)
    if args.prefix and not (args.prefix.isalnum() or "_" in args.prefix):
        logging.warning("Prefix contains special characters. It is recommended to use alphanumeric characters and underscores only.")

    logging.info("Starting nanopore simulation.")
    logging.info(f"Using version {__version__} of the script.")

    # Variables
    input_folder = args.input_folder
    input_fastq = args.input_fastq
    output_folder = args.output_folder
    min_delay = args.min_delay
    max_delay = args.max_delay
    num_reads_per_file = args.num_reads
    num_files = args.num_files
    prefix = args.prefix

    if input_folder:
        input_path = Path(input_folder)
        if not input_path.is_dir():
            logging.error(f"Input folder does not exist: {input_folder}")
            sys.exit(1)
        copy_files_simulation(input_folder, output_folder, min_delay, max_delay, prefix)
    elif input_fastq:
        subsample_reads_simulation(input_fastq, output_folder, num_reads_per_file, num_files, min_delay, max_delay, prefix)


if __name__ == "__main__":
    nano_sim()