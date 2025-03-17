#!/usr/bin/env python3
"""
Nanopore simulator for Nanometa Live.

This script simulates Oxford Nanopore MinION/Flongle sequencing output for
testing and demonstration purposes. It can generate batches of FASTQ files
with random delays to mimic real-time sequencing output.
"""

import os
import sys
import argparse
import random
import time
import logging
import gzip
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pyfastx

from nanometa_live import __version__


def setup_logging(debug=False):
    """
    Set up logging configuration.

    Args:
        debug: Whether to use debug level logging
    """
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_arguments():
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Nanometa Live Simulator: Simulate nanopore sequencing output"
    )

    # Input/output options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "-i", "--input-folder", help="Folder containing test .fastq and .fastq.gz files"
    )
    input_group.add_argument(
        "-f",
        "--input-fastq",
        help="A single compressed fastq.gz file to subsample reads from",
    )

    parser.add_argument(
        "-o",
        "--output-folder",
        required=True,
        help="Simulated nanopore output directory",
    )

    # Timing options
    parser.add_argument(
        "--min-delay",
        type=float,
        default=1,
        help="Minimum delay between batches in seconds (default: 1)",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=5,
        help="Maximum delay between batches in seconds (default: 5)",
    )

    # Subsampling options
    parser.add_argument(
        "-n",
        "--num-reads",
        type=int,
        help="Number of reads to include in each output file",
    )
    parser.add_argument(
        "--num-files",
        type=int,
        default=1,
        help="Number of output files to generate (default: 1)",
    )

    # Misc options
    parser.add_argument(
        "--prefix", type=str, default="", help="Prefix for output filenames"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--version", action="version", version=f"Nanometa Live Simulator v{__version__}"
    )

    args = parser.parse_args()

    # Validate arguments
    if args.min_delay < 0 or args.max_delay < 0:
        parser.error("Delays must be non-negative")

    if args.min_delay > args.max_delay:
        parser.error("Minimum delay cannot be greater than maximum delay")

    if args.input_fastq and not args.num_reads:
        parser.error("--num-reads must be specified when using --input-fastq")

    if args.num_reads is not None and args.num_reads <= 0:
        parser.error("--num-reads must be positive")

    if args.num_files < 1:
        parser.error("--num-files must be at least 1")

    return args


def get_base_name(file_path: Path) -> str:
    """
    Extract the base name of the file without any suffixes.

    Args:
        file_path: Path to the file

    Returns:
        Base name without suffixes
    """
    base = file_path.name
    for suffix in file_path.suffixes:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base


def copy_files_simulation(
    input_folder: str,
    output_folder: str,
    min_delay: float,
    max_delay: float,
    prefix: str,
) -> bool:
    """
    Simulate nanopore reads by copying .fastq and .fastq.gz files with delays.

    Args:
        input_folder: Directory containing input files
        output_folder: Directory to write output files
        min_delay: Minimum delay between files in seconds
        max_delay: Maximum delay between files in seconds
        prefix: Prefix to add to output filenames

    Returns:
        True if successful, False otherwise
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)

    # Create output directory if it doesn't exist
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        logging.debug(f"Ensured output directory exists: {output_path}")
    except Exception as e:
        logging.error(f"Error creating output directory: {e}")
        return False

    # Find input files
    file_list = [
        f
        for f in input_path.iterdir()
        if f.is_file()
        and (f.suffix == ".fastq" or f.suffixes[-2:] == [".fastq", ".gz"])
    ]

    if not file_list:
        logging.error(f"No .fastq or .fastq.gz files found in {input_folder}")
        return False

    logging.info(f"Found {len(file_list)} input files")

    # Process each file
    try:
        for i, file in enumerate(file_list, 1):
            # Random delay
            delay = random.uniform(min_delay, max_delay)
            logging.info(
                f"[{i}/{len(file_list)}] Waiting {delay:.2f} seconds before copying next file"
            )
            time.sleep(delay)

            # Source file
            src = file
            base_name = get_base_name(file)

            # Destination file
            if prefix:
                dst_filename = f"{prefix}_{base_name}.fastq.gz"
            else:
                dst_filename = f"{base_name}.fastq.gz"

            dst = output_path / dst_filename

            # Copy/compress the file
            logging.info(
                f"[{i}/{len(file_list)}] Processing {file.name} -> {dst_filename}"
            )

            if file.suffix == ".fastq":
                # Compress FASTQ to FASTQ.GZ
                with file.open("rb") as f_in, gzip.open(dst, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                logging.info(f"Compressed and copied {file.name} to {dst_filename}")
            else:
                # Copy FASTQ.GZ as-is
                shutil.copy(src, dst)
                logging.info(f"Copied {file.name} to {dst_filename}")

        logging.info(f"Successfully copied {len(file_list)} files")
        return True

    except KeyboardInterrupt:
        logging.warning("Process aborted by user")
        return False
    except Exception as e:
        logging.error(f"Error during file processing: {e}")
        return False


def subsample_reads_simulation(
    input_fastq: str,
    output_folder: str,
    num_reads_per_file: int,
    num_files: int,
    min_delay: float,
    max_delay: float,
    prefix: str,
) -> bool:
    """
    Simulate nanopore reads by subsampling from a single input file.

    Args:
        input_fastq: Path to input FASTQ file
        output_folder: Directory to write output files
        num_reads_per_file: Number of reads per output file
        num_files: Number of output files to generate
        min_delay: Minimum delay between files in seconds
        max_delay: Maximum delay between files in seconds
        prefix: Prefix to add to output filenames

    Returns:
        True if successful, False otherwise
    """
    input_fastq_path = Path(input_fastq)
    output_path = Path(output_folder)

    # Verify input file
    if not input_fastq_path.is_file():
        logging.error(f"Input file does not exist: {input_fastq}")
        return False

    if not input_fastq.endswith((".fastq.gz", ".fq.gz")):
        logging.error(
            "Input file must be a compressed FASTQ file (.fastq.gz or .fq.gz)"
        )
        return False

    # Create output directory
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        logging.debug(f"Ensured output directory exists: {output_path}")
    except Exception as e:
        logging.error(f"Error creating output directory: {e}")
        return False

    # Load input file
    try:
        logging.info(f"Loading input file: {input_fastq}")
        fq = pyfastx.Fastq(str(input_fastq_path), build_index=True)
        total_reads = len(fq)
        logging.info(f"Input file contains {total_reads} reads")

        # Check if we have enough reads
        total_reads_needed = num_reads_per_file * num_files
        if total_reads_needed > total_reads:
            max_files = total_reads // num_reads_per_file
            if max_files == 0:
                logging.error(
                    f"Not enough reads in input file. Need at least {num_reads_per_file} reads."
                )
                return False

            logging.warning(
                f"Not enough reads for {num_files} files with {num_reads_per_file} reads each. "
                f"Adjusting to {max_files} files."
            )
            num_files = max_files
            total_reads_needed = num_reads_per_file * num_files

        # Select random read indices
        all_indices = list(range(total_reads))
        random.shuffle(all_indices)
        selected_indices = all_indices[:total_reads_needed]

        # Distribute reads to files
        reads_per_file = {}
        for i in range(num_files):
            start = i * num_reads_per_file
            end = start + num_reads_per_file
            reads_per_file[i] = sorted(selected_indices[start:end])

        # Generate output files
        base_name = get_base_name(input_fastq_path)

        for i in range(num_files):
            # Random delay
            if i > 0:  # No delay before first file
                delay = random.uniform(min_delay, max_delay)
                logging.info(
                    f"[{i+1}/{num_files}] Waiting {delay:.2f} seconds before generating next file"
                )
                time.sleep(delay)

            # Create output filename
            if prefix:
                output_filename = f"{prefix}_batch_{i+1}_{base_name}.fastq.gz"
            else:
                output_filename = f"batch_{i+1}_{base_name}.fastq.gz"

            output_file = output_path / output_filename

            # Write reads to output file
            logging.info(
                f"[{i+1}/{num_files}] Writing {num_reads_per_file} reads to {output_filename}"
            )

            with gzip.open(output_file, "wt") as outfile:
                for read_idx in reads_per_file[i]:
                    read = fq[read_idx]
                    outfile.write(f"@{read.name}\n{read.seq}\n+\n{read.qual}\n")

            logging.info(f"[{i+1}/{num_files}] Completed {output_filename}")

        logging.info(
            f"Successfully generated {num_files} files with {num_reads_per_file} reads each"
        )
        return True

    except KeyboardInterrupt:
        logging.warning("Process aborted by user")
        return False
    except Exception as e:
        logging.error(f"Error during subsampling: {e}")
        return False


def nano_sim():
    """
    Main function for nanopore simulation.
    """
    # Parse arguments
    args = parse_arguments()

    # Set up logging
    setup_logging(args.debug)

    # Log startup information
    logging.info(f"Nanometa Live Simulator v{__version__}")

    if args.input_folder:
        logging.info(f"Input folder: {args.input_folder}")
        success = copy_files_simulation(
            args.input_folder,
            args.output_folder,
            args.min_delay,
            args.max_delay,
            args.prefix,
        )
    else:
        logging.info(f"Input FASTQ: {args.input_fastq}")
        logging.info(f"Reads per file: {args.num_reads}")
        logging.info(f"Number of files: {args.num_files}")
        success = subsample_reads_simulation(
            args.input_fastq,
            args.output_folder,
            args.num_reads,
            args.num_files,
            args.min_delay,
            args.max_delay,
            args.prefix,
        )

    if success:
        logging.info("Simulation completed successfully")
        return 0
    else:
        logging.error("Simulation failed")
        return 1


if __name__ == "__main__":
    sys.exit(nano_sim())
