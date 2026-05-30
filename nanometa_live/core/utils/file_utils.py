"""
File utility functions for Nanometa Live.

This module provides utility functions for file operations used by the application.
"""

import os
import logging
import shutil
import zipfile
import gzip
import tarfile
import hashlib
import tempfile
from typing import List, Optional
import requests
from tqdm.auto import tqdm


def ensure_directory(directory: str) -> bool:
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        directory: Path to the directory

    Returns:
        True if successful, False otherwise
    """
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except (PermissionError, OSError) as e:
        logging.error(f"Error creating directory {directory}: {e}")
        return False


def clean_path(path: str) -> str:
    """
    Clean and normalize a file path.

    Args:
        path: The path to clean

    Returns:
        Cleaned path
    """
    # Expand user and environment variables
    expanded_path = os.path.expanduser(os.path.expandvars(path))

    # Normalize path separators and structure
    normalized_path = os.path.normpath(expanded_path)

    return normalized_path


def copy_file(source: str, destination: str, overwrite: bool = False) -> bool:
    """
    Copy a file from source to destination.

    Args:
        source: Source file path
        destination: Destination file path
        overwrite: Whether to overwrite existing destination file

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if source exists
        if not os.path.exists(source):
            logging.error(f"Source file {source} does not exist")
            return False

        # Check if destination exists and we don't want to overwrite
        if os.path.exists(destination) and not overwrite:
            logging.warning(
                f"Destination file {destination} already exists and overwrite=False"
            )
            return False

        # Ensure destination directory exists
        ensure_directory(os.path.dirname(destination))

        # Copy the file
        shutil.copy2(source, destination)
        logging.info(f"Copied {source} to {destination}")
        return True

    except (shutil.SameFileError, PermissionError, OSError) as e:
        logging.error(f"Error copying file from {source} to {destination}: {e}")
        return False


def extract_archive(archive_path: str, extract_dir: str) -> bool:
    """
    Extract an archive file (zip, tar.gz, gz).

    Args:
        archive_path: Path to the archive file
        extract_dir: Directory to extract to

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if archive exists
        if not os.path.exists(archive_path):
            logging.error(f"Archive file {archive_path} does not exist")
            return False

        # Ensure extraction directory exists
        ensure_directory(extract_dir)

        # Extract based on file extension
        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

        elif archive_path.endswith(".tar.gz") or archive_path.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tar_ref:
                # filter="data" is the safe extraction policy (no absolute paths,
                # no traversal, no special files) and silences the Python 3.14
                # change-of-default DeprecationWarning.
                tar_ref.extractall(extract_dir, filter="data")

        elif archive_path.endswith(".gz"):
            # For single-file gzip, extract to file without .gz extension
            output_path = os.path.join(extract_dir, os.path.basename(archive_path)[:-3])
            with gzip.open(archive_path, "rb") as f_in:
                with open(output_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

        else:
            logging.error(f"Unsupported archive format: {archive_path}")
            return False

        logging.info(f"Extracted {archive_path} to {extract_dir}")
        return True

    except (zipfile.BadZipFile, tarfile.TarError, gzip.BadGzipFile, EOFError) as e:
        logging.error(f"Corrupt archive {archive_path}: {e}")
        return False
    except (FileNotFoundError, PermissionError, OSError) as e:
        logging.error(f"I/O error extracting archive {archive_path}: {e}")
        return False


def download_file(url: str, destination: str, overwrite: bool = False) -> bool:
    """
    Download a file from a URL.

    Args:
        url: URL to download from
        destination: Local path to save the file
        overwrite: Whether to overwrite existing file

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if destination exists and we don't want to overwrite
        if os.path.exists(destination) and not overwrite:
            logging.info(f"File {destination} already exists and overwrite=False")
            return True

        # Ensure destination directory exists
        ensure_directory(os.path.dirname(destination))

        # Download with progress bar
        response = requests.get(url, stream=True, timeout=60)
        total_size = int(response.headers.get("content-length", 0))

        with open(destination, "wb") as f, tqdm(
            desc=os.path.basename(destination),
            total=total_size,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
        ) as pbar:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

        logging.info(f"Downloaded {url} to {destination}")
        return True

    except requests.exceptions.RequestException as e:
        logging.error(f"Network error downloading {url}: {e}")
        return False
    except (PermissionError, OSError) as e:
        logging.error(f"I/O error saving download to {destination}: {e}")
        return False


def calculate_file_hash(file_path: str, hash_type: str = "md5") -> str:
    """
    Calculate the hash of a file.

    Args:
        file_path: Path to the file
        hash_type: Type of hash (md5, sha1, sha256)

    Returns:
        Hash string
    """
    try:
        # Select hash algorithm
        if hash_type == "md5":
            hash_func = hashlib.md5()
        elif hash_type == "sha1":
            hash_func = hashlib.sha1()
        elif hash_type == "sha256":
            hash_func = hashlib.sha256()
        else:
            raise ValueError(f"Unsupported hash type: {hash_type}")

        # Calculate hash
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_func.update(chunk)

        return hash_func.hexdigest()

    except (FileNotFoundError, PermissionError, OSError) as e:
        logging.error(f"Could not read {file_path} to calculate hash: {e}")
        return ""


def get_file_list(
    directory: str, pattern: str = None, recursive: bool = False
) -> List[str]:
    """
    Get a list of files in a directory.

    Args:
        directory: Directory to search
        pattern: Pattern to match (e.g., "*.fastq.gz")
        recursive: Whether to search recursively

    Returns:
        List of file paths
    """
    try:
        # Check if directory exists
        if not os.path.exists(directory):
            logging.error(f"Directory {directory} does not exist")
            return []

        # Get file list
        file_list = []
        if recursive:
            for root, _, files in os.walk(directory):
                for file in files:
                    file_list.append(os.path.join(root, file))
        else:
            file_list = [
                os.path.join(directory, f)
                for f in os.listdir(directory)
                if os.path.isfile(os.path.join(directory, f))
            ]

        # Filter by pattern if provided
        if pattern:
            import fnmatch

            file_list = [
                f for f in file_list if fnmatch.fnmatch(os.path.basename(f), pattern)
            ]

        return file_list

    except (PermissionError, OSError) as e:
        logging.error(f"Error getting file list for {directory}: {e}")
        return []


def read_file_lines(file_path: str) -> List[str]:
    """
    Read lines from a file.

    Args:
        file_path: Path to the file

    Returns:
        List of lines
    """
    try:
        # Open in appropriate mode based on file extension
        if file_path.endswith(".gz"):
            with gzip.open(file_path, "rt") as f:
                return [line.strip() for line in f]
        else:
            with open(file_path, "r") as f:
                return [line.strip() for line in f]

    except (FileNotFoundError, PermissionError, OSError) as e:
        logging.error(f"Could not read file {file_path}: {e}")
        return []
    except (UnicodeDecodeError, EOFError, gzip.BadGzipFile) as e:
        logging.error(f"Malformed file {file_path}: {e}")
        return []


def write_file_lines(file_path: str, lines: List[str]) -> bool:
    """
    Write lines to a file.

    Args:
        file_path: Path to the file
        lines: List of lines to write

    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure directory exists
        ensure_directory(os.path.dirname(file_path))

        # Open in appropriate mode based on file extension
        if file_path.endswith(".gz"):
            with gzip.open(file_path, "wt") as f:
                for line in lines:
                    f.write(line + "\n")
        else:
            with open(file_path, "w") as f:
                for line in lines:
                    f.write(line + "\n")

        return True

    except (PermissionError, OSError) as e:
        logging.error(f"Error writing to file {file_path}: {e}")
        return False


def remove_temp_files(paths: List[str]) -> bool:
    """
    Remove temporary files and directories.

    Args:
        paths: List of paths to remove

    Returns:
        True if all successful, False if any fail
    """
    success = True
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
                logging.debug(f"Removed temporary file: {path}")
            elif os.path.isdir(path):
                shutil.rmtree(path)
                logging.debug(f"Removed temporary directory: {path}")
        except (PermissionError, OSError) as e:
            logging.error(f"Error removing temporary path {path}: {e}")
            success = False

    return success


def create_temp_directory() -> Optional[str]:
    """
    Create a temporary directory.

    Returns:
        Path to the temporary directory, or None if creation fails
    """
    try:
        temp_dir = tempfile.mkdtemp(prefix="nanometa_")
        logging.debug(f"Created temporary directory: {temp_dir}")
        return temp_dir

    except (PermissionError, OSError) as e:
        logging.error(f"Error creating temporary directory: {e}")
        return None


def get_most_recent_file(directory: str, pattern: str = None) -> Optional[str]:
    """
    Get the most recently modified file in a directory.

    Args:
        directory: Directory to search
        pattern: Pattern to match (e.g., "*.fastq.gz")

    Returns:
        Path to the most recent file, or None if none found
    """
    try:
        # Get file list
        file_list = get_file_list(directory, pattern)

        if not file_list:
            return None

        # Sort by modification time (newest first)
        file_list.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        return file_list[0]

    except (FileNotFoundError, PermissionError, OSError) as e:
        logging.error(f"Error finding most recent file in {directory}: {e}")
        return None

def check_command_exists(command: str) -> bool:
    """
    Check if an external command exists and is executable.

    Args:
        command: Name of the command to check

    Returns:
        True if the command exists and is executable, False otherwise
    """
    import subprocess
    try:
        result = subprocess.run(
            ["which", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False