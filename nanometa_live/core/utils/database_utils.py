"""
Database utilities for Nanometa Live.

This module provides utility functions for managing databases used by Nanometa Live,
including downloading, extracting, and validating Kraken2 databases.
"""

import os
import logging
import requests
import tarfile
import yaml
import subprocess
from typing import Dict, Tuple, List, Optional, Any, Union
import time


def load_database_list() -> Dict[str, Dict[str, str]]:
    """
    Load the list of available external Kraken2 databases.

    Returns:
        Dictionary of database names mapped to their details
    """
    try:
        # Find the database list file in the package
        import nanometa_live
        package_dir = os.path.dirname(nanometa_live.__file__)
        db_list_path = os.path.join(package_dir, "kraken2_databases.yaml")

        # Load the database list
        with open(db_list_path, 'r') as f:
            db_list = yaml.safe_load(f)

        return db_list.get("kraken2_databases", {})
    except Exception as e:
        logging.error(f"Error loading database list: {e}")
        return {}


def download_kraken_database(
    db_info: Dict[str, str],
    dest_dir: str,
    progress_callback: Optional[callable] = None
) -> Tuple[bool, str]:
    """
    Download a Kraken2 database from the specified URL.

    Args:
        db_info: Dictionary containing database information (name, url, etc.)
        dest_dir: Directory to download the database to
        progress_callback: Optional callback function for progress updates

    Returns:
        Tuple of (success, message)
    """
    db_name = db_info.get("name", "unknown")
    db_url = db_info.get("database_url")

    if not db_url:
        return False, f"No download URL provided for database {db_name}"

    try:
        # Create destination directory if it doesn't exist
        os.makedirs(dest_dir, exist_ok=True)

        # Download to a temporary file first
        temp_path = os.path.join(dest_dir, f"{db_name}.tar.gz")

        # Send progress update if callback is provided
        if progress_callback:
            progress_callback(0, f"Starting download of {db_name} from {db_url}")

        # Stream the download to avoid loading the whole file into memory
        with requests.get(db_url, stream=True) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))

            # Use a small chunk size to show progress
            chunk_size = 8192
            downloaded = 0

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Send progress updates
                        if progress_callback and total_size > 0:
                            # Calculate progress as percentage
                            percent = (downloaded / total_size) * 100
                            progress_callback(
                                int(percent),
                                f"Downloading... {downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({percent:.1f}%)"
                            )

        # Extract the database
        extract_dir = os.path.join(dest_dir, db_name)
        os.makedirs(extract_dir, exist_ok=True)

        if progress_callback:
            progress_callback(50, f"Download complete. Extracting to {extract_dir}")

        with tarfile.open(temp_path, "r:gz") as tar:
            members = tar.getmembers()
            total_members = len(members)

            for i, member in enumerate(members):
                tar.extract(member, path=extract_dir)

                # Send progress updates
                if progress_callback and i % 10 == 0:
                    extract_percent = 50 + (i / total_members) * 50
                    progress_callback(
                        int(extract_percent),
                        f"Extracting... {i} / {total_members} files ({i / total_members * 100:.1f}%)"
                    )

        if progress_callback:
            progress_callback(100, f"Successfully downloaded and extracted {db_name}")

        # Return success
        return True, extract_dir

    except requests.exceptions.RequestException as e:
        return False, f"Error downloading database: {str(e)}"
    except tarfile.TarError as e:
        return False, f"Error extracting database: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def verify_kraken_db(db_path: str) -> bool:
    """
    Verify that a Kraken2 database is valid.

    Args:
        db_path: Path to the Kraken2 database

    Returns:
        True if the database is valid, False otherwise
    """
    # Check for key files that should be present in any Kraken database
    required_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]

    for file in required_files:
        if not os.path.isfile(os.path.join(db_path, file)):
            logging.warning(f"Kraken2 database missing required file: {file}")
            return False

    return True


def run_kraken2_inspect(
    db_path: str,
    output_path: str,
    progress_callback: Optional[callable] = None
) -> bool:
    """
    Run kraken2-inspect on a database to extract taxonomy information.

    Args:
        db_path: Path to the Kraken2 database
        output_path: Path to save the inspection report
        progress_callback: Optional callback function for progress updates

    Returns:
        True if successful, False otherwise
    """
    try:
        if not verify_kraken_db(db_path):
            return False

        if progress_callback:
            progress_callback(0, f"Starting kraken2-inspect on {db_path}")

        # Run kraken2-inspect
        cmd = ["kraken2-inspect", "--db", db_path]

        with open(output_path, "w") as f:
            process = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                text=True
            )

            # Monitor the process and provide progress updates
            if progress_callback:
                progress_callback(10, "kraken2-inspect running...")

                while process.poll() is None:
                    # Send periodic updates while the process is running
                    progress_callback(50, "kraken2-inspect in progress...")
                    time.sleep(1)

            # Wait for process to complete
            process.wait()

            if process.returncode != 0:
                error_msg = process.stderr.read() if process.stderr else "Unknown error"
                if progress_callback:
                    progress_callback(100, f"kraken2-inspect failed: {error_msg}")
                return False

        if progress_callback:
            progress_callback(100, "kraken2-inspect completed successfully")

        return True

    except Exception as e:
        if progress_callback:
            progress_callback(100, f"Error running kraken2-inspect: {str(e)}")
        return False


def parse_species_from_inspect(
    inspect_file: str,
    species_list: List[str],
    progress_callback: Optional[callable] = None
) -> Dict[str, str]:
    """
    Parse a kraken2-inspect output file to extract taxonomy IDs for species.

    Args:
        inspect_file: Path to the kraken2-inspect output file
        species_list: List of species names to search for
        progress_callback: Optional callback function for progress updates

    Returns:
        Dictionary mapping species names to taxonomy IDs
    """
    if progress_callback:
        progress_callback(0, f"Parsing taxonomy information from {inspect_file}")

    species_taxids = {}
    level_mappings = {
        'S': 'species',
        'G': 'genus',
        'F': 'family',
        'O': 'order',
        'C': 'class',
        'P': 'phylum',
        'D': 'superkingdom',
        'K': 'kingdom'
    }

    try:
        line_count = 0
        matched_count = 0

        # Count total lines for progress tracking
        with open(inspect_file, 'r') as f:
            total_lines = sum(1 for _ in f)

        with open(inspect_file, 'r') as f:
            for i, line in enumerate(f):
                line_count += 1

                # Update progress every 10,000 lines
                if progress_callback and line_count % 10000 == 0:
                    percent = (line_count / total_lines) * 100
                    progress_callback(
                        int(percent),
                        f"Processed {line_count:,} of {total_lines:,} entries ({percent:.1f}%)..."
                    )

                parts = line.strip().split('\t')
                if len(parts) >= 6:  # At least 6 columns expected
                    # Column format: %krakenuniq, cumul reads, reads, level_type, taxid, name
                    level_type = parts[3]
                    taxid = parts[4]
                    name = parts[5].strip()

                    # Only process species level entries - checking both abbreviated and full names
                    if level_type == 'S' or level_type == 'species' or level_mappings.get(level_type) == 'species':
                        # Check if any of our species match this name
                        for species in species_list:
                            if species and species.lower() in name.lower():
                                species_taxids[species] = taxid
                                matched_count += 1

                                if progress_callback:
                                    progress_callback(
                                        int((line_count / total_lines) * 100),
                                        f"Found taxonomy ID for {species}: {taxid} ({matched_count}/{len(species_list)} matched)"
                                    )

        if progress_callback:
            progress_callback(
                100,
                f"Finished parsing. Found taxonomy IDs for {matched_count} out of {len(species_list)} species."
            )

        return species_taxids

    except Exception as e:
        if progress_callback:
            progress_callback(100, f"Error parsing taxonomy information: {str(e)}")
        return {}


def download_genome_for_taxid(
    taxid: str,
    species: str,
    accession: str,
    output_dir: str,
    progress_callback: Optional[callable] = None
) -> Tuple[bool, str]:
    """
    Download a genome for a specific taxonomy ID using NCBI datasets tool.

    Args:
        taxid: Taxonomy ID
        species: Species name
        accession: NCBI accession number
        output_dir: Directory to save the genome
        progress_callback: Optional callback function for progress updates

    Returns:
        Tuple of (success, message)
    """
    try:
        if progress_callback:
            progress_callback(0, f"Starting download for {species} (taxid: {taxid})")

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        # Write accession to temporary file
        accession_file = os.path.join(output_dir, f"{taxid}_accession.txt")
        with open(accession_file, "w") as f:
            f.write(f"{accession}\n")

        # Define output zip file
        output_zip = os.path.join(output_dir, f"{taxid}_genome.zip")

        # Download using datasets command
        cmd = [
            "datasets", "download", "genome", "accession",
            "--inputfile", accession_file,
            "--filename", output_zip
        ]

        if progress_callback:
            progress_callback(10, f"Running NCBI datasets command for {species}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Monitor process output for progress updates
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                output = output.strip()
                if progress_callback:
                    progress_callback(50, f"NCBI download: {output}")

        rc = process.poll()
        if rc != 0:
            if progress_callback:
                progress_callback(100, f"Download failed with exit code {rc}")
            return False, f"Download failed with exit code {rc}"

        # Extract and process the downloaded file
        if progress_callback:
            progress_callback(70, f"Extracting genome files for {species}")

        import zipfile

        with zipfile.ZipFile(output_zip, 'r') as zip_ref:
            zip_ref.extractall(output_dir)

        # Find and copy the genome file
        ncbi_data_dir = os.path.join(output_dir, "ncbi_dataset", "data", accession)
        genome_file = None

        for root, dirs, files in os.walk(ncbi_data_dir):
            for file in files:
                if file.endswith(".fna"):
                    genome_file = os.path.join(root, file)
                    break
            if genome_file:
                break

        if not genome_file:
            if progress_callback:
                progress_callback(100, f"No genome file found for {species}")
            return False, f"No genome file found for {species}"

        # Copy the genome file to the final location
        import shutil
        target_file = os.path.join(output_dir, f"{taxid}.fasta")
        shutil.copy(genome_file, target_file)

        if progress_callback:
            progress_callback(100, f"Successfully downloaded genome for {species}")

        # Clean up intermediate files
        try:
            os.remove(accession_file)
            os.remove(output_zip)
            shutil.rmtree(os.path.join(output_dir, "ncbi_dataset"))
        except Exception as e:
            logging.warning(f"Error cleaning up temporary files: {str(e)}")

        return True, target_file

    except Exception as e:
        if progress_callback:
            progress_callback(100, f"Error downloading genome: {str(e)}")
        return False, f"Error downloading genome: {str(e)}"


def build_blast_database(
    genome_file: str,
    output_dir: str,
    progress_callback: Optional[callable] = None
) -> Tuple[bool, str]:
    """
    Build a BLAST database from a genome file.

    Args:
        genome_file: Path to the genome FASTA file
        output_dir: Directory to save the BLAST database
        progress_callback: Optional callback function for progress updates

    Returns:
        Tuple of (success, message)
    """
    try:
        if progress_callback:
            progress_callback(0, f"Starting BLAST database build for {os.path.basename(genome_file)}")

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        # Get base filename without extension
        base_name = os.path.splitext(os.path.basename(genome_file))[0]
        output_path = os.path.join(output_dir, base_name)

        # Build BLAST database
        cmd = [
            "makeblastdb",
            "-in", genome_file,
            "-dbtype", "nucl",
            "-out", output_path
        ]

        if progress_callback:
            progress_callback(20, "Running makeblastdb command...")

        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )

        # Check if required files were created
        for ext in [".nhr", ".nin", ".nsq"]:
            if not os.path.exists(f"{output_path}{ext}"):
                if progress_callback:
                    progress_callback(100, f"BLAST database file {output_path}{ext} not created")
                return False, f"BLAST database file {output_path}{ext} not created"

        if progress_callback:
            progress_callback(100, "BLAST database built successfully")

        return True, output_path

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        if progress_callback:
            progress_callback(100, f"Error building BLAST database: {error_msg}")
        return False, f"Error building BLAST database: {error_msg}"

    except Exception as e:
        if progress_callback:
            progress_callback(100, f"Error building BLAST database: {str(e)}")
        return False, f"Error building BLAST database: {str(e)}"


def fetch_gtdb_data(
    species: str,
    taxonomy_db: str = "gtdb",
    progress_callback: Optional[callable] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Fetch data for a species from the GTDB API.

    Args:
        species: Species name
        taxonomy_db: Taxonomy database to use ('gtdb' or 'ncbi')
        progress_callback: Optional callback function for progress updates

    Returns:
        Tuple of (success, data)
    """
    try:
        if progress_callback:
            progress_callback(0, f"Starting GTDB API query for {species}")

        search_query = f"s__{species}"

        # Fetch species data using requests
        base_url = "https://gtdb-api.ecogenomic.org/search/gtdb"
        params = {
            "search": search_query,
            "page": 1,
            "itemsPerPage": 1000,
            "searchField": f"{taxonomy_db}_tax",
            "gtdbSpeciesRepOnly": True if taxonomy_db == "gtdb" else False,
            "ncbiTypeMaterialOnly": True if taxonomy_db == "ncbi" else False,
        }

        if progress_callback:
            progress_callback(20, f"Sending API request for {species}")

        response = requests.get(base_url, params=params, headers={"accept": "application/json"})

        if response.status_code != 200:
            if progress_callback:
                progress_callback(100, f"API request failed with status code {response.status_code}")
            return False, {}

        result = response.json()
        rows = result.get("rows", [])

        if not rows:
            if progress_callback:
                progress_callback(100, f"No data found for {species}")
            return False, {}

        if progress_callback:
            progress_callback(50, f"Found {len(rows)} results for {species}")

        # Find exact matches
        exact_matches = []

        for row in rows:
            # Get the taxonomy field based on the taxonomy database
            if taxonomy_db == "gtdb":
                taxonomy = row.get("gtdbTaxonomy", "")
            else:  # ncbi
                taxonomy = row.get("ncbiTaxonomy", "")

            # Check for exact match
            if taxonomy and taxonomy.endswith(f"s__{species}"):
                exact_matches.append(row)

        if exact_matches:
            # Return the first exact match
            if progress_callback:
                progress_callback(100, f"Found exact match for {species}")
            return True, exact_matches[0]
        else:
            # Return first result if no exact match
            if progress_callback:
                progress_callback(100, f"No exact match found for {species}, using first result")
            return True, rows[0]

    except Exception as e:
        if progress_callback:
            progress_callback(100, f"Error fetching GTDB data: {str(e)}")
        return False, {}


def check_missing_genomes(
    species_to_taxid: Dict[str, str],
    genomes_dir: str
) -> List[str]:
    """
    Check which genomes are missing for the given species.

    Args:
        species_to_taxid: Dictionary mapping species names to taxonomy IDs
        genomes_dir: Directory where genome files should be located

    Returns:
        List of species names that are missing genome files
    """
    missing_species = []

    for species, taxid in species_to_taxid.items():
        genome_file = os.path.join(genomes_dir, f"{taxid}.fasta")
        if not os.path.exists(genome_file):
            missing_species.append(species)

    return missing_species


def check_missing_blast_dbs(
    species_to_taxid: Dict[str, str],
    blast_dir: str
) -> List[str]:
    """
    Check which BLAST databases are missing for the given species.

    Args:
        species_to_taxid: Dictionary mapping species names to taxonomy IDs
        blast_dir: Directory where BLAST databases should be located

    Returns:
        List of taxonomy IDs that are missing BLAST databases
    """
    missing_dbs = []

    for species, taxid in species_to_taxid.items():
        blast_db_file = os.path.join(blast_dir, f"{taxid}.fasta.nhr")
        if not os.path.exists(blast_db_file):
            missing_dbs.append(str(taxid))

    return missing_dbs