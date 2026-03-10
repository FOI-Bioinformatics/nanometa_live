"""
Database utilities for Nanometa Live.

This module provides utility functions for downloading and managing Kraken2 databases.
"""

import os
import logging
import requests
import tarfile
import shutil
from typing import Optional, Tuple, Dict, Callable


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

        # Flag file to indicate download is in progress
        download_flag_file = f"{db_file_name}.downloading"

        # Check if already downloaded and extracted
        if os.path.exists(hash_file_path):
            logging.info(f"Database '{external_db_key}' already exists at {db_extract_folder}")
            # Remove any leftover flags - but NOT the tar.gz file which might be needed
            if os.path.exists(download_flag_file):
                try:
                    os.remove(download_flag_file)
                except (OSError, PermissionError) as e:
                    logging.debug(f"Could not remove flag file: {e}")
            return True, f"Database '{external_db_key}' already exists", db_extract_folder

        # Start fresh if redownloading
        if os.path.exists(download_flag_file):
            logging.warning(f"Previous download was incomplete. Removing and starting fresh.")
            if os.path.exists(db_file_name):
                try:
                    os.remove(db_file_name)
                except (OSError, PermissionError) as e:
                    logging.warning(f"Could not remove incomplete download: {e}")

        # Download the database
        if progress_callback:
            progress_callback(10, f"Downloading Kraken2 database '{external_db_key}' from {db_url}")

        # Create flag file to indicate download is in progress
        with open(download_flag_file, 'w') as f:
            f.write("Download in progress")

        # Stream the download with progress updates
        download_success = download_database(db_url, db_file_name, progress_callback)

        if not download_success:
            if os.path.exists(download_flag_file):
                os.remove(download_flag_file)
            return False, f"Failed to download database '{external_db_key}'", ""

        # Remove the download flag file when complete
        if os.path.exists(download_flag_file):
            os.remove(download_flag_file)

        # Create extraction folder if needed
        os.makedirs(db_extract_folder, exist_ok=True)

        # Extract the database
        if progress_callback:
            progress_callback(45, f"Extracting database '{external_db_key}'...")

        extract_success = decompress_database(db_file_name, db_extract_folder, progress_callback)

        if not extract_success:
            return False, f"Failed to extract database '{external_db_key}'", ""

        # Verify extraction worked by checking for the hash.k2d file
        if not os.path.exists(hash_file_path):
            return False, f"Extraction completed but database files are missing", ""

        if progress_callback:
            progress_callback(90, f"Verifying database installation...")

        # Verify the database installation is complete and valid
        is_valid = verify_kraken_database(db_extract_folder)
        if not is_valid:
            return False, f"Database verification failed", ""

        if progress_callback:
            progress_callback(100, f"Database '{external_db_key}' successfully prepared")

        # IMPORTANT: Only delete the archive file AFTER we've fully verified everything
        # This way if something goes wrong, we don't have to re-download
        if os.path.exists(db_file_name) and os.path.exists(hash_file_path) and is_valid:
            try:
                os.remove(db_file_name)
                logging.info(f"Removed downloaded archive {db_file_name} to save space")
            except Exception as e:
                # Just log this - not a critical error
                logging.warning(f"Could not remove downloaded archive {db_file_name}: {str(e)}")

        return True, f"Successfully prepared database '{external_db_key}'", db_extract_folder

    except Exception as e:
        error_msg = f"Error preparing Kraken2 database: {str(e)}"
        logging.error(error_msg)
        # Clean up any flag files
        if 'download_flag_file' in locals() and os.path.exists(download_flag_file):
            try:
                os.remove(download_flag_file)
            except (OSError, PermissionError) as e:
                logging.debug(f"Could not remove flag file during cleanup: {e}")
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
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        # Get file size for progress reporting
        total_size = int(response.headers.get("content-length", 0))
        if total_size == 0:
            logging.warning("Content-length header missing, progress reporting may be inaccurate")
            total_size = 1000000000  # Assume 1GB for progress calculation

        downloaded = 0
        chunk_size = 8192  # 8KB chunks

        # Temp file approach to avoid partial files
        temp_file_path = f"{dest_file_path}.tmp"

        # Download in chunks with progress reporting
        with open(temp_file_path, "wb") as f:
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

        # Make sure file is fully written to disk before continuing
        if progress_callback:
            progress_callback(40, f"Download complete. Finalizing file ({downloaded/(1024*1024):.1f} MB)...")

        # Double-check the file exists and has the right size
        if not os.path.exists(temp_file_path):
            logging.error(f"Downloaded file does not exist: {temp_file_path}")
            return False

        actual_size = os.path.getsize(temp_file_path)
        if total_size > 0 and abs(actual_size - downloaded) > 1024:  # Allow 1KB difference
            logging.error(f"Downloaded file size mismatch: expected {downloaded}, got {actual_size}")
            return False

        # Rename temp file to final file only after successful download
        if os.path.exists(dest_file_path):
            os.remove(dest_file_path)
        shutil.move(temp_file_path, dest_file_path)

        # Final verification
        if not os.path.exists(dest_file_path):
            logging.error(f"Final file does not exist after move: {dest_file_path}")
            return False

        logging.info(f"Successfully downloaded file to {dest_file_path}")
        return True

    except requests.RequestException as e:
        logging.error(f"Network error downloading file: {str(e)}")
        # Clean up temp file if it exists
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except (OSError, PermissionError) as cleanup_err:
                logging.debug(f"Could not remove temp file: {cleanup_err}")
        if progress_callback:
            progress_callback(40, f"Error downloading file: {str(e)}")
        return False
    except (IOError, OSError) as e:
        logging.error(f"I/O error downloading file: {str(e)}")
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except (OSError, PermissionError) as cleanup_err:
                logging.debug(f"Could not remove temp file: {cleanup_err}")
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
        if not os.path.exists(tar_file_path):
            logging.error(f"TAR file does not exist: {tar_file_path}")
            return False

        file_size = os.path.getsize(tar_file_path)
        if file_size < 10240:  # Less than 10KB is definitely wrong for a database
            logging.error(f"TAR file too small ({file_size} bytes): {tar_file_path}")
            return False

        if progress_callback:
            progress_callback(50, f"Decompressing {os.path.basename(tar_file_path)} ({file_size/(1024*1024):.1f} MB)...")

        # Try to use the system tar command first, which often handles large files better
        try:
            import subprocess
            if progress_callback:
                progress_callback(60, "Using system tar command for extraction...")

            result = subprocess.run(
                ["tar", "-xzf", tar_file_path, "-C", extract_folder],
                check=True,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE
            )
            logging.info(f"Extraction with system tar command succeeded: {extract_folder}")

            if progress_callback:
                progress_callback(80, "Extraction complete")

            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.warning(f"System tar command failed: {str(e)}. Falling back to Python tarfile.")

            # Fall back to Python's tarfile
            if progress_callback:
                progress_callback(60, "Using Python tar module for extraction...")

            with tarfile.open(tar_file_path, "r:gz", errorlevel=1) as tar:
                tar.extractall(path=extract_folder)

            if progress_callback:
                progress_callback(80, "Extraction complete")

            logging.info(f"Successfully extracted {tar_file_path} to {extract_folder}")
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

    logging.info(f"Verifying Kraken2 database in {db_path}")

    missing_files = []
    for file in required_files:
        file_path = os.path.join(db_path, file)
        if not os.path.exists(file_path):
            missing_files.append(file)
            logging.warning(f"Missing required Kraken2 database file: {file}")

    if missing_files:
        logging.error(f"Kraken2 database verification failed - missing files: {', '.join(missing_files)}")
        return False

    logging.info(f"Kraken2 database verification successful")
    return True