"""
Database utilities for Nanometa Live.

This module provides utility functions for downloading and managing Kraken2 databases.
"""

import os
import logging
import requests
import tarfile
import time
from typing import Optional, Tuple, Dict, Any, Callable


def download_and_prepare_kraken_database(
    external_db_key: str,
    external_db_info: Dict[str, Dict[str, str]],
    destination_folder: str,
    progress_callback: Optional[Callable] = None
) -> Tuple[bool, str, str]:
    """
    Download and decompress an external Kraken2 database.

    Args:
        external_db_key: Key of the database in external_db_info
        external_db_info: Dictionary of database information
        destination_folder: Folder to download the database to
        progress_callback: Callback function for progress updates

    Returns:
        Tuple of (success, message, database_path)
    """
    try:
        if external_db_key not in external_db_info:
            return False, f"Database '{external_db_key}' not found in configuration", ""

        db_details = external_db_info[external_db_key]
        db_url = db_details.get("database_url")

        if not db_url:
            return False, f"No URL provided for database '{external_db_key}'", ""

        # Create destination folder if it doesn't exist
        os.makedirs(destination_folder, exist_ok=True)

        # Define database file and extraction folder paths
        db_file_name = os.path.join(destination_folder, f"{external_db_key}.tar.gz")
        db_extract_folder = os.path.join(destination_folder, external_db_key)
        hash_file_path = os.path.join(db_extract_folder, "hash.k2d")

        # Check if already downloaded and extracted
        if os.path.exists(hash_file_path):
            logging.info(f"Database '{external_db_key}' already exists at {db_extract_folder}")
            return True, f"Database '{external_db_key}' already exists", db_extract_folder

        # Download the database if needed
        if not os.path.exists(db_file_name):
            if progress_callback:
                progress_callback(10, f"Downloading Kraken2 database '{external_db_key}' from {db_url}")

            # Stream the download with progress updates
            download_success = download_database(db_url, db_file_name, progress_callback)

            if not download_success:
                return False, f"Failed to download database '{external_db_key}'", ""
        else:
            if progress_callback:
                progress_callback(40, f"Database file '{db_file_name}' already downloaded.")

        # Create extraction folder if needed
        os.makedirs(db_extract_folder, exist_ok=True)

        # Extract the database if needed
        if not os.path.exists(hash_file_path):
            if progress_callback:
                progress_callback(45, f"Extracting database '{external_db_key}'...")

            extract_success = decompress_database(db_file_name, db_extract_folder, progress_callback)

            if not extract_success:
                return False, f"Failed to extract database '{external_db_key}'", ""
        else:
            if progress_callback:
                progress_callback(80, f"Database '{external_db_key}' already extracted.")

        if progress_callback:
            progress_callback(100, f"Database '{external_db_key}' successfully prepared")

        return True, f"Successfully prepared database '{external_db_key}'", db_extract_folder

    except Exception as e:
        error_msg = f"Error preparing Kraken2 database: {str(e)}"
        logging.error(error_msg)
        if progress_callback:
            progress_callback(100, f"Error: {error_msg}")
        return False, error_msg, ""


def download_database(
    url: str,
    dest_file_path: str,
    progress_callback: Optional[Callable] = None
) -> bool:
    """
    Download a file from the specified URL with progress reporting.

    Args:
        url: URL to download from
        dest_file_path: Path to save the downloaded file
        progress_callback: Callback function for progress updates

    Returns:
        True if successful, False otherwise
    """
    try:
        # Start the download
        response = requests.get(url, stream=True)
        response.raise_for_status()

        # Get file size for progress reporting
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 8192  # 8KB chunks

        # Download in chunks with progress reporting
        with open(dest_file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Update progress every 5MB
                    if progress_callback and total_size > 0 and downloaded % (5 * 1024 * 1024) < chunk_size:
                        percent = int((downloaded / total_size) * 30) + 10  # Scale to 10-40%
                        progress_callback(
                            percent,
                            f"Downloading... {downloaded/(1024*1024):.1f} MB / {total_size/(1024*1024):.1f} MB ({downloaded/total_size*100:.1f}%)"
                        )

        logging.info(f"Successfully downloaded file to {dest_file_path}")
        return True

    except Exception as e:
        logging.error(f"Error downloading file: {str(e)}")
        if progress_callback:
            progress_callback(40, f"Error downloading file: {str(e)}")
        return False


def decompress_database(
    tar_file_path: str,
    extract_folder: str,
    progress_callback: Optional[Callable] = None
) -> bool:
    """
    Decompress a TAR.GZ file with progress reporting.

    Args:
        tar_file_path: Path to the TAR.GZ file
        extract_folder: Folder to extract the contents to
        progress_callback: Callback function for progress updates

    Returns:
        True if successful, False otherwise
    """
    try:
        if progress_callback:
            progress_callback(50, f"Decompressing {os.path.basename(tar_file_path)}...")

        # Open the tar file
        with tarfile.open(tar_file_path, "r:gz") as tar:
            # Get member info for progress reporting
            members = tar.getmembers()
            total_members = len(members)

            # Extract with progress updates
            for i, member in enumerate(members):
                tar.extract(member, path=extract_folder)

                # Update progress every 100 files
                if progress_callback and i % 100 == 0:
                    percent = 50 + int((i / total_members) * 30)  # Scale to 50-80%
                    progress_callback(
                        percent,
                        f"Extracting... {i}/{total_members} files ({i/total_members*100:.1f}%)"
                    )

        logging.info(f"Successfully extracted {tar_file_path} to {extract_folder}")
        if progress_callback:
            progress_callback(80, f"Extraction complete.")

        return True

    except Exception as e:
        logging.error(f"Error extracting file: {str(e)}")
        if progress_callback:
            progress_callback(80, f"Error extracting file: {str(e)}")
        return False


def verify_kraken_database(db_path: str) -> bool:
    """
    Verify that a Kraken2 database is valid.

    Args:
        db_path: Path to the Kraken2 database folder

    Returns:
        True if valid, False otherwise
    """
    # Required files for a Kraken2 database
    required_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]

    for file in required_files:
        file_path = os.path.join(db_path, file)
        if not os.path.exists(file_path):
            logging.warning(f"Missing required Kraken2 database file: {file}")
            return False

    return True