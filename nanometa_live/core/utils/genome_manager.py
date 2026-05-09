"""
Genome Download Manager for Nanometa Live.

This module manages pathogen reference genome downloads for BLAST validation.
Supports both GTDB (bacteria/archaea) and NCBI RefSeq (other kingdoms) sources.

Usage:
    manager = GenomeDownloadManager()

    # Check what's missing
    missing = manager.get_missing_genomes(watchlist_entries)

    # Download genomes
    for entry in missing:
        path = manager.download_genome(entry)
        if path:
            manager.build_blast_db(path)
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from nanometa_live.core.taxonomy.taxonomy_api import get_ncbi_client

logger = logging.getLogger(__name__)


# GTDB API endpoint
GTDB_API_BASE = "https://api.gtdb.ecogenomic.org"

# NCBI Datasets API
NCBI_DATASETS_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"


@dataclass
class GenomeMetadata:
    """Metadata for a downloaded genome."""

    taxid: int
    species_name: str
    accession: str  # GCF_/GCA_ accession
    source: str  # "gtdb" or "ncbi"
    kingdom: str  # "Bacteria", "Archaea", "Fungi", etc.
    fasta_path: str
    blast_db_path: Optional[str] = None
    download_date: str = field(default_factory=lambda: datetime.now().isoformat())
    file_size: int = 0
    is_representative: bool = True
    gtdb_taxonomy: Optional[str] = None
    ncbi_taxonomy: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GenomeMetadata":
        """Create from dictionary."""
        return cls(**data)


def _extract_fasta_accession(fasta_path: Path) -> Optional[str]:
    """Extract the first accession from a FASTA file header.

    Parses the first line of the FASTA file and extracts common NCBI
    accession patterns (e.g. NC_003461.1, GCF_000009045.1).

    Returns:
        Accession string, or None if no recognisable accession found.
    """
    accession_pattern = re.compile(
        r'((?:NC|NZ|NW|NT|AC|GCF|GCA)_[A-Z]*\d+(?:\.\d+)?)'
    )
    try:
        with open(fasta_path, 'r') as f:
            header = f.readline(1024)
        if header.startswith('>'):
            match = accession_pattern.search(header)
            if match:
                return match.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return None


def _validate_fasta(fasta_path: Path) -> bool:
    """Validate that a file is a valid FASTA file.

    Checks that the file is non-empty, starts with a header line ('>'),
    and contains only valid nucleotide/amino-acid sequence characters.

    Args:
        fasta_path: Path to the FASTA file to validate.

    Returns:
        True if the file appears to be a valid FASTA, False otherwise.
    """
    valid_seq_chars = set("ACGTNURYSWKMBDHVacgtnuryswkmbdhv.-\n\r\t ")
    try:
        size = fasta_path.stat().st_size
        if size == 0:
            logger.error(f"FASTA validation failed: {fasta_path} is empty")
            return False

        with open(fasta_path, "r") as f:
            first_line = f.readline()
            if not first_line.startswith(">"):
                logger.error(
                    f"FASTA validation failed: {fasta_path} does not start "
                    f"with a header line ('>')"
                )
                return False

            # Check first 10000 characters of sequence data for validity
            chars_checked = 0
            for line in f:
                if line.startswith(">"):
                    continue
                for ch in line:
                    if ch not in valid_seq_chars:
                        logger.error(
                            f"FASTA validation failed: {fasta_path} contains "
                            f"invalid character '{ch}' in sequence data"
                        )
                        return False
                chars_checked += len(line)
                if chars_checked > 10000:
                    break

        return True

    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"FASTA validation failed for {fasta_path}: {e}")
        return False


class GenomeDownloadManager:
    """
    Manages pathogen reference genome downloads and BLAST database building.

    Downloads reference genomes for pathogens in the watchlist:
    - Bacteria/Archaea: Uses GTDB representative genomes
    - Other kingdoms: Uses NCBI RefSeq representative genomes

    Caches downloads in ~/.nanometa/genomes/ with metadata tracking.
    """

    # Class-level per-host circuit breaker for GTDB/NCBI lookups.
    # After CIRCUIT_THRESHOLD consecutive failures the host is marked
    # OPEN for the rest of the process, subsequent calls return None
    # without firing more requests or log lines. Without this the same
    # SSL/timeout/429 failure prints once per watchlist entry (17+ for
    # a typical clinical_pathogens list).
    _host_failures: Dict[str, int] = {}
    _host_open: Dict[str, bool] = {}
    CIRCUIT_THRESHOLD = 3

    @classmethod
    def _circuit_is_open(cls, host: str) -> bool:
        return cls._host_open.get(host, False)

    @classmethod
    def _circuit_record_failure(cls, host: str, label: str, error: Exception) -> None:
        count = cls._host_failures.get(host, 0) + 1
        cls._host_failures[host] = count
        if count >= cls.CIRCUIT_THRESHOLD and not cls._host_open.get(host, False):
            cls._host_open[host] = True
            logger.warning(
                "%s unreachable after %d failures (%s); skipping further "
                "lookups for this session.",
                label, count, error,
            )

    @classmethod
    def _circuit_record_success(cls, host: str) -> None:
        cls._host_failures[host] = 0

    def __init__(self, cache_dir: Optional[str] = None, offline_mode: bool = False):
        """
        Initialize the genome download manager.

        Args:
            cache_dir: Base cache directory. Defaults to ~/.nanometa
            offline_mode: If True, refuse all genome downloads
        """
        if cache_dir is None:
            # Resolve from NANOMETA_DATA_DIR (set by the CLI entry
            # point from --data-dir) so this default-construction
            # branch follows the operator's chosen data directory.
            from nanometa_live.core.utils.paths import get_data_dir_from_env
            cache_dir = get_data_dir_from_env()

        # Always expand user home directory and resolve to absolute path
        self.cache_dir = Path(os.path.expanduser(cache_dir)).resolve()
        self.genomes_dir = self.cache_dir / "genomes"
        self.blast_dir = self.cache_dir / "blast"
        self.metadata_file = self.cache_dir / "genome_metadata.json"
        self.offline_mode = offline_mode

        # Create directories
        self.genomes_dir.mkdir(parents=True, exist_ok=True)
        self.blast_dir.mkdir(parents=True, exist_ok=True)

        # Load existing metadata
        self._metadata: Dict[int, GenomeMetadata] = {}
        self._last_errors: Dict[int, str] = {}  # taxid -> error message
        self._load_metadata()

        # Scan for existing genome files without metadata
        self._scan_existing_genomes()

    def _resolve_species_name(self, taxid: int) -> Tuple[str, str]:
        """
        Resolve species name and kingdom for a taxid using NCBI API.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Tuple of (species_name, kingdom). Returns defaults if lookup fails.
        """
        try:
            ncbi_client = get_ncbi_client()
            result = ncbi_client.get_by_taxid(taxid)

            if result:
                species_name = result.sciname or f"Unknown (taxid {taxid})"

                # Determine kingdom from lineage or division
                kingdom = "Unknown"
                if result.lineage:
                    # Check lineage for kingdom/domain
                    for name in result.lineage:
                        name_lower = name.lower()
                        if name_lower in ("bacteria", "archaea", "fungi", "viruses", "eukaryota"):
                            kingdom = name.capitalize()
                            break
                elif result.division:
                    # Fall back to division if lineage not available
                    kingdom = result.division

                logger.info(f"Resolved taxid {taxid}: {species_name} ({kingdom})")
                return species_name, kingdom

        except (requests.exceptions.RequestException, ValueError, AttributeError,
                KeyError, TypeError) as e:
            logger.warning(f"Failed to resolve species name for taxid {taxid}: {e}")

        # Fall back to watchlist name if NCBI lookup failed
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            wm = get_watchlist_manager()
            entry = wm.get_entry_by_taxid(taxid)
            if entry and entry.name:
                logger.info(f"Using watchlist name for taxid {taxid}: {entry.name}")
                return entry.name, "Unknown"
        except (ImportError, AttributeError):
            pass

        return f"Unknown (taxid {taxid})", "Unknown"

    def _scan_existing_genomes(self) -> None:
        """
        Scan the genomes directory for existing FASTA files without metadata.

        This detects genomes that were downloaded manually or by other tools,
        and creates basic metadata entries for them.
        """
        if not self.genomes_dir.exists():
            return

        # Find all FASTA files in the genomes directory
        fasta_extensions = ['.fasta', '.fna', '.fa', '.fasta.gz', '.fna.gz', '.fa.gz']
        found_new = 0

        for fasta_file in self.genomes_dir.iterdir():
            if not fasta_file.is_file():
                continue

            # Check if it's a FASTA file
            name_lower = fasta_file.name.lower()
            if not any(name_lower.endswith(ext) for ext in fasta_extensions):
                continue

            # Try to extract taxid from filename (expecting {taxid}.fasta pattern)
            stem = fasta_file.stem
            # Handle .fasta.gz by removing .fasta too
            if stem.endswith('.fasta') or stem.endswith('.fna') or stem.endswith('.fa'):
                stem = Path(stem).stem

            try:
                taxid = int(stem)
            except ValueError:
                # Filename doesn't start with a taxid number, skip
                continue

            # Skip if we already have metadata for this taxid
            if taxid in self._metadata:
                continue

            # Create metadata entry for discovered genome with resolved species name
            logger.info(f"Discovered existing genome file: {fasta_file.name} (taxid: {taxid})")

            # Resolve species name from NCBI (falls back to watchlist)
            species_name, kingdom = self._resolve_species_name(taxid)

            # Infer source from kingdom when possible
            source = "discovered"
            if kingdom == "Viruses":
                source = "ncbi_virus"
            elif kingdom in ("Bacteria", "Archaea"):
                source = "gtdb"

            # Try to extract a real accession from the FASTA header
            discovered_accession = _extract_fasta_accession(fasta_file) or "discovered"

            # Check if a BLAST DB already exists on disk
            blast_db_path = None
            existing_blast = self.get_blast_db_path(taxid)
            if existing_blast:
                blast_db_path = str(existing_blast)

            self._metadata[taxid] = GenomeMetadata(
                taxid=taxid,
                species_name=species_name,
                accession=discovered_accession,
                source=source,
                kingdom=kingdom,
                fasta_path=str(fasta_file),
                blast_db_path=blast_db_path,
                file_size=fasta_file.stat().st_size,
                is_representative=False,
            )
            found_new += 1

        if found_new > 0:
            logger.info(f"Discovered {found_new} existing genome files without metadata")
            self._save_metadata()

        # Build BLAST databases for genomes that don't have them
        self._build_missing_blast_dbs()

    def _build_missing_blast_dbs(self) -> None:
        """
        Build BLAST databases for any genomes that don't have them yet.

        This runs automatically after loading/scanning genomes to ensure
        all downloaded genomes have corresponding BLAST databases.
        Also syncs metadata for existing BLAST DBs that lack blast_db_path.
        """
        # Check if makeblastdb is available
        has_makeblastdb = bool(shutil.which("makeblastdb"))
        if not has_makeblastdb:
            logger.debug("makeblastdb not found, skipping auto-build of BLAST databases")

        built = 0
        synced = 0
        for taxid, meta in self._metadata.items():
            # Check if genome file exists
            genome_path = Path(meta.fasta_path)
            if not genome_path.exists():
                continue

            # Check if BLAST database already exists on disk
            if self.has_blast_db(taxid):
                # Sync metadata if it lacks the blast_db_path
                if meta.blast_db_path is None:
                    meta.blast_db_path = str(self.get_blast_db_path(taxid))
                    synced += 1
                continue

            if not has_makeblastdb:
                continue

            # Build BLAST database
            logger.info(f"Building BLAST database for taxid {taxid} ({meta.species_name})")
            if self.build_blast_db(taxid):
                built += 1

        if synced > 0:
            logger.info(f"Synced blast_db_path for {synced} existing BLAST databases")
            self._save_metadata()
        if built > 0:
            logger.info(f"Built {built} missing BLAST databases")

    def _load_metadata(self) -> None:
        """Load genome metadata from cache."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    data = json.load(f)
                    for taxid_str, meta_dict in data.items():
                        self._metadata[int(taxid_str)] = GenomeMetadata.from_dict(meta_dict)
                logger.debug(f"Loaded metadata for {len(self._metadata)} genomes")
            except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError,
                    json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(f"Failed to load genome metadata: {e}")

    def _save_metadata(self) -> None:
        """Save genome metadata to cache.

        Uses atomic write-then-rename so a concurrent reader (e.g. a
        second nanometa-live process sharing the same data_dir) never
        observes a half-written or zero-byte file. The fcntl lock
        scopes the read-modify-write sequence so two writers do not
        clobber each other's additions.
        """
        from nanometa_live.core.utils.atomic_write import (
            atomic_write_json, file_lock,
        )
        try:
            with file_lock(self.metadata_file):
                # Re-read inside the lock so a concurrent writer's
                # additions are merged rather than overwritten.
                disk_data: Dict[str, Any] = {}
                if self.metadata_file.exists():
                    try:
                        with open(self.metadata_file, "r") as f:
                            disk_data = json.load(f) or {}
                    except (json.JSONDecodeError, OSError):
                        disk_data = {}
                merged = dict(disk_data)
                for k, v in self._metadata.items():
                    merged[str(k)] = v.to_dict()
                atomic_write_json(self.metadata_file, merged)
        except (PermissionError, OSError, TypeError, ValueError) as e:
            logger.exception(f"Failed to save genome metadata: {e}")

    def get_genome_path(self, taxid: int) -> Optional[Path]:
        """
        Get path to downloaded genome for a taxid.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Path to genome FASTA if downloaded, None otherwise
        """
        if taxid in self._metadata:
            path = Path(self._metadata[taxid].fasta_path)
            if path.exists():
                return path

        # Check for file even without metadata
        genome_file = self.genomes_dir / f"{taxid}.fasta"
        if genome_file.exists():
            return genome_file

        return None

    def get_blast_db_path(self, taxid: int) -> Optional[Path]:
        """
        Get path to BLAST database for a taxid.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Path to BLAST database if built, None otherwise
        """
        blast_db = self.blast_dir / f"{taxid}.fasta"
        # Check for .nhr file (BLAST database index)
        if Path(f"{blast_db}.nhr").exists():
            return blast_db
        return None

    def get_last_error(self, taxid: int) -> Optional[str]:
        """Get the last download error message for a taxid, or None."""
        return self._last_errors.get(taxid)

    def has_genome(self, taxid: int) -> bool:
        """Check if genome is downloaded for a taxid."""
        return self.get_genome_path(taxid) is not None

    def has_blast_db(self, taxid: int) -> bool:
        """Check if BLAST database exists for a taxid."""
        return self.get_blast_db_path(taxid) is not None

    def get_missing_genomes(
        self,
        entries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Get watchlist entries that don't have downloaded genomes.

        Args:
            entries: List of watchlist entry dicts with 'taxid' and 'name'

        Returns:
            List of entries without downloaded genomes
        """
        missing = []
        for entry in entries:
            taxid = entry.get("taxid", 0)
            if taxid and not self.has_genome(taxid):
                missing.append(entry)
        return missing

    def get_kingdom(self, taxid: int) -> Optional[str]:
        """
        Determine the kingdom/domain for a taxid using NCBI API.

        Parses the XML response to extract superkingdom from the lineage,
        avoiding false matches from species names that happen to contain
        kingdom-level terms.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Kingdom name (Bacteria, Archaea, Fungi, Viruses, etc.) or None
        """
        if self.offline_mode:
            logger.debug(f"Offline mode: skipping NCBI kingdom lookup for taxid {taxid}")
            return None
        try:
            url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            params = {
                "db": "taxonomy",
                "id": taxid,
                "retmode": "xml"
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            root = ET.fromstring(response.text)

            # Check LineageEx for superkingdom and kingdom ranks
            superkingdom = None
            kingdom_name = None
            for taxon_el in root.iter("LineageEx"):
                for child in taxon_el.findall("Taxon"):
                    rank = child.findtext("Rank", "")
                    name = child.findtext("ScientificName", "")
                    if rank == "superkingdom":
                        superkingdom = name
                    elif rank == "kingdom":
                        kingdom_name = name

            if superkingdom:
                # For Eukaryota, refine to Fungi if kingdom is Fungi
                if superkingdom == "Eukaryota" and kingdom_name == "Fungi":
                    return "Fungi"
                name_map = {
                    "Bacteria": "Bacteria",
                    "Archaea": "Archaea",
                    "Eukaryota": "Eukaryota",
                    "Viruses": "Viruses",
                }
                if superkingdom in name_map:
                    return name_map[superkingdom]

            # Fallback: check the Lineage text element
            lineage = root.findtext(".//Lineage", "")
            if lineage:
                # Lineage is semicolon-separated, check first few entries
                parts = [p.strip() for p in lineage.split(";")]
                for part in parts[:3]:
                    if part in ("Bacteria", "Archaea", "Eukaryota", "Viruses"):
                        return part

            # Check Division element as last resort
            division = root.findtext(".//Division", "")
            if division:
                div_lower = division.lower()
                if div_lower == "bacteria":
                    return "Bacteria"
                elif div_lower == "archaea":
                    return "Archaea"
                elif div_lower == "viruses":
                    return "Viruses"
                elif div_lower in ("fungi", "plants", "primates", "mammals",
                                   "rodents", "invertebrates", "vertebrates"):
                    return "Eukaryota"

            return None

        except (requests.exceptions.RequestException, ET.ParseError,
                ValueError, KeyError) as e:
            logger.exception(f"Failed to get kingdom for taxid {taxid}: {e}")
            return None

    def fetch_gtdb_accession(
        self,
        species_name: str
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Get GTDB representative genome accession for a species.

        Args:
            species_name: Species name (e.g., "Escherichia coli")

        Returns:
            Tuple of (accession, metadata_dict) or None if not found
        """
        if self.offline_mode:
            logger.debug(f"Offline mode: skipping GTDB lookup for '{species_name}'")
            return None
        if self._circuit_is_open("gtdb"):
            return None
        try:
            # Format for GTDB search
            search_term = f"s__{species_name.replace(' ', '_')}"

            url = f"{GTDB_API_BASE}/search/gtdb"
            params = {
                "search": search_term,
                "page": 1,
                "itemsPerPage": 10,
                "searchField": "gtdb_tax",
                "gtdbSpeciesRepOnly": True
            }

            response = requests.get(
                url,
                params=params,
                headers={"accept": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            self._circuit_record_success("gtdb")

            data = response.json()
            rows = data.get("rows", [])

            if not rows:
                # Try without species prefix
                params["search"] = species_name
                response = requests.get(url, params=params, timeout=30)
                data = response.json()
                rows = data.get("rows", [])

            # Find exact match with representative status
            for row in rows:
                if row.get("isGtdbSpeciesRep"):
                    accession = row.get("gid", "").lstrip("RS_")
                    if accession:
                        return (accession, row)

            # Return first result if no exact rep found
            if rows:
                accession = rows[0].get("gid", "").lstrip("RS_")
                if accession:
                    return (accession, rows[0])

            return None

        except (requests.exceptions.RequestException, json.JSONDecodeError,
                ValueError, KeyError, AttributeError) as e:
            if not self._circuit_is_open("gtdb"):
                logger.warning("GTDB API unreachable for '%s': %s", species_name, e)
            logger.debug("GTDB API traceback for '%s'", species_name, exc_info=True)
            self._circuit_record_failure("gtdb", "GTDB API", e)
            return None

    def fetch_ncbi_accession(self, taxid: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Get NCBI RefSeq representative genome accession for a taxid.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Tuple of (accession, metadata_dict) or None if not found
        """
        if self.offline_mode:
            logger.debug(f"Offline mode: skipping NCBI accession lookup for taxid {taxid}")
            return None
        if self._circuit_is_open("ncbi"):
            return None
        try:
            url = f"{NCBI_DATASETS_API}/genome/taxon/{taxid}"
            params = {
                "filters.reference_only": "true",
                "page_size": 5
            }
            headers = {"accept": "application/json"}

            response = requests.get(url, params=params, headers=headers, timeout=30)

            if response.status_code == 404:
                # Try without reference filter
                logger.info(f"No reference genome for taxid {taxid}, trying all assemblies...")
                params.pop("filters.reference_only")
                response = requests.get(url, params=params, headers=headers, timeout=30)

            if response.status_code == 404:
                self._circuit_record_success("ncbi")
                logger.info(f"No genome assemblies found at NCBI for taxid {taxid}")
                return None

            response.raise_for_status()
            self._circuit_record_success("ncbi")
            data = response.json()

            reports = data.get("reports", [])
            if not reports:
                logger.warning(f"NCBI returned empty results for taxid {taxid}")
                return None

            report = reports[0]
            accession = report.get("accession", "")
            if accession:
                return (accession, report)

            return None

        except (requests.exceptions.RequestException, json.JSONDecodeError,
                ValueError, KeyError, AttributeError) as e:
            if not self._circuit_is_open("ncbi"):
                logger.warning("NCBI API error for taxid %s: %s", taxid, e)
            logger.debug("NCBI API traceback for taxid %s", taxid, exc_info=True)
            self._circuit_record_failure("ncbi", "NCBI Datasets API", e)
            return None

    def download_genome(
        self,
        taxid: int,
        species_name: str,
        force: bool = False
    ) -> Optional[Path]:
        """
        Download reference genome for a species.

        Routes to GTDB for bacteria/archaea, NCBI for other kingdoms.

        Args:
            taxid: NCBI taxonomy ID
            species_name: Species name
            force: Force re-download even if exists

        Returns:
            Path to downloaded FASTA file, or None on failure
        """
        if self.offline_mode:
            # In offline mode, return existing genome if available, otherwise refuse
            if self.has_genome(taxid):
                return self.get_genome_path(taxid)
            msg = "Offline mode -- use Import to add genomes"
            logger.warning(f"{msg} (taxid={taxid}, species={species_name})")
            self._last_errors[taxid] = msg
            return None

        # Check if already downloaded
        if not force and self.has_genome(taxid):
            logger.info(f"Genome already downloaded for taxid {taxid}")
            return self.get_genome_path(taxid)

        # Clear previous error for this taxid
        self._last_errors.pop(taxid, None)

        # Determine kingdom to route to correct source
        kingdom = self.get_kingdom(taxid)
        if not kingdom:
            msg = f"Could not determine kingdom for taxid {taxid} (NCBI API may be unreachable)"
            logger.error(msg)
            self._last_errors[taxid] = msg
            # Still try NCBI directly
        logger.info(f"Downloading genome for {species_name} (taxid={taxid}, kingdom={kingdom})")

        # Viruses: use dedicated virus download path (NCBI genome API
        # does not index viral genomes - they are nucleotide records)
        if kingdom == "Viruses":
            fasta_path, virus_accession = self._download_virus_genome(taxid, species_name)
            if fasta_path:
                self._metadata[taxid] = GenomeMetadata(
                    taxid=taxid,
                    species_name=species_name,
                    accession=virus_accession or f"virus_taxid_{taxid}",
                    source="ncbi_virus",
                    kingdom="Viruses",
                    fasta_path=str(fasta_path),
                    file_size=fasta_path.stat().st_size if fasta_path.exists() else 0,
                )
                self._save_metadata()
                return fasta_path
            else:
                msg = f"Virus genome download failed for {species_name} (taxid={taxid})"
                logger.error(msg)
                self._last_errors[taxid] = msg
                return None

        accession = None
        metadata = {}
        source = "ncbi"

        if kingdom in ("Bacteria", "Archaea"):
            # Try GTDB first for bacteria/archaea
            logger.info(f"Querying GTDB API for {species_name}...")
            result = self.fetch_gtdb_accession(species_name)
            if result:
                accession, metadata = result
                source = "gtdb"
                logger.info(f"Found GTDB representative genome: {accession}")
            else:
                logger.info(f"No GTDB match found for {species_name}, trying NCBI...")

        if not accession:
            # Fall back to NCBI
            logger.info(f"Querying NCBI for taxid {taxid}...")
            result = self.fetch_ncbi_accession(taxid)
            if result:
                accession, metadata = result
                source = "ncbi"
                logger.info(f"Found NCBI RefSeq genome: {accession}")

        if not accession:
            # REST API failed — try direct download by taxid via datasets CLI
            # (the CLI supports more taxa than the REST API, especially fungi)
            logger.info(f"No accession found via API, trying direct taxid download for {species_name}...")
            fasta_path, cli_accession = self._download_ncbi_genome_by_taxid(taxid, species_name)
            if fasta_path:
                self._metadata[taxid] = GenomeMetadata(
                    taxid=taxid,
                    species_name=species_name,
                    accession=cli_accession or f"taxid_{taxid}",
                    source="ncbi_cli",
                    kingdom=kingdom or "Unknown",
                    fasta_path=str(fasta_path),
                    file_size=fasta_path.stat().st_size if fasta_path.exists() else 0,
                )
                self._save_metadata()
                return fasta_path
            msg = f"No genome assembly found for {species_name} (taxid={taxid}) in GTDB or NCBI"
            logger.error(msg)
            self._last_errors[taxid] = msg
            return None

        # Download using NCBI datasets CLI
        fasta_path = self._download_ncbi_genome(accession, taxid)

        if fasta_path:
            # Save metadata
            self._metadata[taxid] = GenomeMetadata(
                taxid=taxid,
                species_name=species_name,
                accession=accession,
                source=source,
                kingdom=kingdom or "Unknown",
                fasta_path=str(fasta_path),
                file_size=fasta_path.stat().st_size if fasta_path.exists() else 0,
                gtdb_taxonomy=metadata.get("gtdbTaxonomy"),
                ncbi_taxonomy=metadata.get("ncbiTaxonomy") or metadata.get("organism", {}).get("organism_name"),
            )
            self._save_metadata()

            return fasta_path

        self._last_errors[taxid] = f"NCBI datasets download failed for accession {accession}"
        return None

    def _download_virus_genome(self, taxid: int, species_name: str) -> Tuple[Optional[Path], Optional[str]]:
        """
        Download a viral genome using the NCBI datasets virus subcommand.

        The standard NCBI Datasets genome API does not index viral genomes.
        Viral reference sequences are nucleotide records, not genome assemblies.
        The datasets CLI provides a dedicated `download virus genome` command.

        Args:
            taxid: NCBI taxonomy ID
            species_name: Species name (for logging)

        Returns:
            Tuple of (path to FASTA, accession) or (None, None) on failure
        """
        if not shutil.which("datasets"):
            logger.error(
                "NCBI 'datasets' CLI not found. "
                "Install from: https://www.ncbi.nlm.nih.gov/datasets/docs/v2/download-and-install/"
            )
            return None, None

        output_file = self.genomes_dir / f"{taxid}.fasta"

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_file = Path(tmpdir) / "virus_genome.zip"

                cmd = [
                    "datasets", "download", "virus", "genome", "taxon",
                    str(taxid),
                    "--refseq",
                    "--complete-only",
                    "--include", "genome",
                    "--filename", str(zip_file)
                ]

                logger.info(
                    f"Downloading virus genome for {species_name} "
                    f"(taxid={taxid}) via datasets CLI..."
                )
                logger.debug(f"Running: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                if result.returncode != 0:
                    logger.error(f"Virus genome download failed: {result.stderr}")
                    return None, None

                if not zip_file.exists():
                    logger.error("Downloaded virus archive not found")
                    return None, None

                # Extract FASTA from zip
                # Virus zips use a flat path: ncbi_dataset/data/genomic.fna
                with zipfile.ZipFile(zip_file, "r") as zf:
                    fasta_files = [
                        f for f in zf.namelist()
                        if f.endswith(".fna") or f.endswith(".fasta")
                    ]

                    if not fasta_files:
                        logger.error(
                            "No FASTA file found in virus genome archive"
                        )
                        return None, None

                    fasta_name = fasta_files[0]
                    temp_fasta = Path(tmpdir) / "virus_genome.fasta"

                    with zf.open(fasta_name) as src, \
                            open(temp_fasta, "wb") as dst:
                        dst.write(src.read())

                    shutil.move(str(temp_fasta), str(output_file))

                if not _validate_fasta(output_file):
                    logger.error(f"Downloaded virus genome failed FASTA validation: {output_file}")
                    output_file.unlink(missing_ok=True)
                    return None, None

                accession = _extract_fasta_accession(output_file)
                logger.info(
                    f"Downloaded virus genome to {output_file} "
                    f"(accession={accession or 'unknown'})"
                )
                return output_file, accession

        except subprocess.TimeoutExpired:
            logger.error(f"Virus genome download timed out for taxid {taxid}")
            return None, None
        except (subprocess.CalledProcessError, FileNotFoundError, PermissionError,
                OSError, zipfile.BadZipFile) as e:
            logger.exception(
                f"Virus genome download failed for taxid {taxid}: {e}"
            )
            return None, None

    def _download_ncbi_genome(self, accession: str, taxid: int) -> Optional[Path]:
        """
        Download genome from NCBI using datasets CLI.

        Args:
            accession: Genome accession (GCF_/GCA_)
            taxid: Taxonomy ID (for naming output)

        Returns:
            Path to FASTA file, or None on failure
        """
        # Check if datasets CLI is available
        if not shutil.which("datasets"):
            logger.error(
                "NCBI 'datasets' CLI not found. "
                "Install from: https://www.ncbi.nlm.nih.gov/datasets/docs/v2/download-and-install/"
            )
            return None

        output_file = self.genomes_dir / f"{taxid}.fasta"

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_file = Path(tmpdir) / "genome.zip"

                # Download genome
                cmd = [
                    "datasets", "download", "genome", "accession",
                    accession,
                    "--include", "genome",
                    "--filename", str(zip_file)
                ]

                logger.info(f"Downloading genome from NCBI (accession: {accession})...")
                logger.debug(f"Running: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout
                )

                if result.returncode != 0:
                    logger.error(f"Download failed: {result.stderr}")
                    return None

                if not zip_file.exists():
                    logger.error("Downloaded file not found")
                    return None

                # Extract FASTA from zip
                with zipfile.ZipFile(zip_file, 'r') as zf:
                    # Find FASTA file in zip
                    fasta_files = [
                        f for f in zf.namelist()
                        if f.endswith('.fna') or f.endswith('.fasta')
                    ]

                    if not fasta_files:
                        logger.error("No FASTA file found in downloaded archive")
                        return None

                    # Extract to temp, then rename
                    fasta_name = fasta_files[0]
                    temp_fasta = Path(tmpdir) / "genome.fasta"

                    with zf.open(fasta_name) as src, open(temp_fasta, 'wb') as dst:
                        dst.write(src.read())

                    # Move to final location
                    shutil.move(str(temp_fasta), str(output_file))

                if not _validate_fasta(output_file):
                    logger.error(f"Downloaded genome failed FASTA validation: {output_file}")
                    output_file.unlink(missing_ok=True)
                    return None

                logger.info(f"Downloaded genome to {output_file}")
                return output_file

        except subprocess.TimeoutExpired:
            logger.error(f"Download timed out for {accession}")
            return None
        except (subprocess.CalledProcessError, FileNotFoundError, PermissionError,
                OSError, zipfile.BadZipFile) as e:
            logger.exception(f"Download failed for {accession}: {e}")
            return None

    def _download_ncbi_genome_by_taxid(self, taxid: int, species_name: str) -> Tuple[Optional[Path], Optional[str]]:
        """
        Download genome directly by taxid using datasets CLI.

        This bypasses the REST API accession lookup, which fails for some
        taxa (notably fungi). The datasets CLI supports downloading by
        taxid and handles reference genome selection internally.

        Args:
            taxid: NCBI taxonomy ID
            species_name: Species name (for logging)

        Returns:
            Tuple of (path to FASTA, accession) or (None, None) on failure
        """
        if not shutil.which("datasets"):
            logger.error("NCBI 'datasets' CLI not found.")
            return None, None

        output_file = self.genomes_dir / f"{taxid}.fasta"

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_file = Path(tmpdir) / "genome.zip"

                cmd = [
                    "datasets", "download", "genome", "taxon",
                    str(taxid),
                    "--reference",
                    "--include", "genome",
                    "--filename", str(zip_file)
                ]

                logger.info(f"Downloading genome by taxid for {species_name} (taxid={taxid})...")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                if result.returncode != 0:
                    # Try without --reference flag
                    logger.info(f"No reference genome, retrying without --reference...")
                    cmd.remove("--reference")
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=600
                    )

                if result.returncode != 0:
                    logger.error(f"Download by taxid failed for {species_name}: {result.stderr}")
                    return None, None

                if not zip_file.exists():
                    logger.error("Downloaded file not found")
                    return None, None

                with zipfile.ZipFile(zip_file, 'r') as zf:
                    fasta_files = [
                        f for f in zf.namelist()
                        if f.endswith('.fna') or f.endswith('.fasta')
                    ]

                    if not fasta_files:
                        logger.error("No FASTA file found in downloaded archive")
                        return None, None

                    fasta_name = fasta_files[0]
                    temp_fasta = Path(tmpdir) / "genome.fasta"

                    with zf.open(fasta_name) as src, open(temp_fasta, 'wb') as dst:
                        dst.write(src.read())

                    shutil.move(str(temp_fasta), str(output_file))

                if not _validate_fasta(output_file):
                    logger.error(f"Downloaded genome failed FASTA validation: {output_file}")
                    output_file.unlink(missing_ok=True)
                    return None, None

                accession = _extract_fasta_accession(output_file)
                logger.info(
                    f"Downloaded genome by taxid to {output_file} "
                    f"(accession={accession or 'unknown'})"
                )
                return output_file, accession

        except subprocess.TimeoutExpired:
            logger.error(f"Download timed out for taxid {taxid}")
            return None, None
        except (subprocess.CalledProcessError, FileNotFoundError, PermissionError,
                OSError, zipfile.BadZipFile) as e:
            logger.exception(f"Download by taxid failed for {taxid}: {e}")
            return None, None

    def build_blast_db(self, taxid: int) -> bool:
        """
        Build BLAST database for a downloaded genome.

        Args:
            taxid: Taxonomy ID

        Returns:
            True if successful, False otherwise
        """
        genome_path = self.get_genome_path(taxid)
        if not genome_path:
            logger.error(f"No genome found for taxid {taxid}")
            return False

        # Check if makeblastdb is available
        if not shutil.which("makeblastdb"):
            logger.error("makeblastdb not found. Install BLAST+ toolkit.")
            return False

        output_db = self.blast_dir / f"{taxid}.fasta"
        genome_size_mb = genome_path.stat().st_size / (1024 * 1024) if genome_path.exists() else 0

        # Check available disk space before building
        try:
            usage = shutil.disk_usage(str(self.blast_dir))
            free_gb = usage.free / (1024**3)
            if free_gb < 2.0:
                logger.warning(
                    f"Low disk space: {free_gb:.1f} GB free in {self.blast_dir}. "
                    "Minimum 2 GB recommended for BLAST DB builds."
                )
        except OSError as e:
            logger.debug(f"Could not check disk space: {e}")

        logger.info(f"Building BLAST database for taxid {taxid} (genome size: {genome_size_mb:.1f} MB)...")

        try:
            cmd = [
                "makeblastdb",
                "-in", str(genome_path),
                "-dbtype", "nucl",
                "-out", str(output_db)
            ]

            logger.debug(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                logger.error(f"makeblastdb failed for taxid {taxid}: {result.stderr}")
                return False

            # Update metadata
            if taxid in self._metadata:
                self._metadata[taxid].blast_db_path = str(output_db)
                self._save_metadata()

            logger.info(f"Successfully built BLAST database: {output_db}")
            return True

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, PermissionError, OSError) as e:
            logger.exception(f"Failed to build BLAST database: {e}")
            return False

    def get_all_genomes(self) -> List[GenomeMetadata]:
        """Get list of all downloaded genomes, including on-disk orphans."""
        self._scan_existing_genomes()
        return list(self._metadata.values())

    def generate_pathogen_genomes_json(
        self,
        taxids: List[int],
        output_path: Optional[Path] = None,
        taxid_mapping: Optional[Dict[int, int]] = None
    ) -> Optional[Path]:
        """
        Generate a pathogen_genomes.json file for nanometanf validation.

        Creates a JSON file mapping taxids to genome FASTA paths, suitable
        for passing to the nanometanf VALIDATION subworkflow.

        Args:
            taxids: List of NCBI taxids to include (for looking up downloaded genomes)
            output_path: Where to write the JSON file. Defaults to cache_dir/pathogen_genomes.json
            taxid_mapping: Optional mapping of NCBI taxid -> Kraken2 database taxid.
                          If provided, the JSON keys will use the Kraken2 taxids
                          (for GTDB databases), while file lookup uses NCBI taxids.

        Returns:
            Path to the generated JSON file, or None if no genomes available
        """
        if output_path is None:
            output_path = self.cache_dir / "pathogen_genomes.json"

        # Build mapping of taxid -> genome path
        # Key is kraken_taxid (for pipeline filtering), lookup by ncbi_taxid (for file)
        genome_mapping = {}
        for ncbi_taxid in taxids:
            genome_path = self.get_genome_path(ncbi_taxid)
            if genome_path and genome_path.exists():
                # Use kraken_taxid as key if mapping provided, otherwise use ncbi_taxid
                if taxid_mapping and ncbi_taxid in taxid_mapping:
                    key_taxid = taxid_mapping[ncbi_taxid]
                else:
                    key_taxid = ncbi_taxid
                genome_mapping[str(key_taxid)] = str(genome_path)

        if not genome_mapping:
            logger.warning("No downloaded genomes found for provided taxids")
            return None

        # Write JSON file
        try:
            with open(output_path, 'w') as f:
                json.dump(genome_mapping, f, indent=2)
            logger.info(
                f"Generated pathogen_genomes.json with {len(genome_mapping)} genomes at {output_path}"
            )
            return output_path
        except (PermissionError, OSError, TypeError, ValueError) as e:
            logger.exception(f"Failed to write pathogen_genomes.json: {e}")
            return None

    def get_all_genome_status(
        self,
        entries: List[Dict[str, Any]],
    ) -> Dict[int, Dict[str, bool]]:
        """
        Get per-entry status for genome and BLAST database availability.

        Args:
            entries: List of watchlist entry dicts with 'taxid' key.

        Returns:
            Dict mapping taxid to {"genome": bool, "blast_db": bool}.
        """
        status = {}
        for entry in entries:
            taxid = entry.get("taxid", 0)
            if taxid:
                status[taxid] = {
                    "genome": self.has_genome(taxid),
                    "blast_db": self.has_blast_db(taxid),
                }
        return status

    def get_statistics(self) -> Dict[str, Any]:
        """Get download statistics."""
        total = len(self._metadata)
        # Count BLAST DBs by checking filesystem, not just metadata
        with_blast = sum(1 for taxid in self._metadata.keys() if self.has_blast_db(taxid))

        by_kingdom = {}
        by_source = {}
        total_size = 0

        for meta in self._metadata.values():
            by_kingdom[meta.kingdom] = by_kingdom.get(meta.kingdom, 0) + 1
            by_source[meta.source] = by_source.get(meta.source, 0) + 1
            total_size += meta.file_size

        return {
            "total_genomes": total,
            "with_blast_db": with_blast,
            "by_kingdom": by_kingdom,
            "by_source": by_source,
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }

    def build_missing_blast_dbs(self) -> int:
        """
        Build BLAST databases for all genomes that don't have them.

        This is a public method that can be called from the UI to
        build BLAST databases for all downloaded genomes.

        Returns:
            Number of BLAST databases built
        """
        # Check if makeblastdb is available
        if not shutil.which("makeblastdb"):
            logger.error("makeblastdb not found. Install BLAST+ toolkit.")
            return 0

        built = 0
        for taxid, meta in self._metadata.items():
            # Check if genome file exists
            genome_path = Path(meta.fasta_path)
            if not genome_path.exists():
                continue

            # Check if BLAST database already exists
            if self.has_blast_db(taxid):
                continue

            # Build BLAST database
            logger.info(f"Building BLAST database for taxid {taxid} ({meta.species_name})")
            if self.build_blast_db(taxid):
                built += 1

        if built > 0:
            logger.info(f"Built {built} BLAST databases")

        return built

    def refresh_unknown_metadata(self) -> int:
        """
        Update metadata for entries that still show "Unknown" species names.

        This retroactively resolves species names for genomes that were
        previously added without proper NCBI lookup.

        Returns:
            Number of entries updated
        """
        updated = 0

        for taxid, meta in list(self._metadata.items()):
            # Check if species name needs resolution
            if meta.species_name.startswith("Unknown (taxid"):
                logger.info(f"Resolving unknown species for taxid {taxid}")

                species_name, kingdom = self._resolve_species_name(taxid)

                # Only update if we got a real name
                if not species_name.startswith("Unknown"):
                    meta.species_name = species_name
                    meta.kingdom = kingdom
                    updated += 1

        if updated > 0:
            self._save_metadata()
            logger.info(f"Updated {updated} genome metadata entries")

        return updated

    # ------------------------------------------------------------------
    # Batch / concurrent download methods
    # ------------------------------------------------------------------

    def get_kingdoms_batch(self, taxids: List[int]) -> Dict[int, str]:
        """
        Fetch kingdoms for multiple taxids in a single NCBI efetch request.

        The efetch API accepts comma-separated IDs, allowing one HTTP
        round-trip instead of N individual calls.

        Args:
            taxids: List of NCBI taxonomy IDs.

        Returns:
            Dict mapping taxid to kingdom string. Missing entries are
            omitted from the result.
        """
        if not taxids:
            return {}
        if self.offline_mode:
            logger.debug(f"Offline mode: skipping batch NCBI kingdom lookup for {len(taxids)} taxids")
            return {}

        results: Dict[int, str] = {}

        # Process in chunks of 200 to stay within URL length limits
        chunk_size = 200
        for i in range(0, len(taxids), chunk_size):
            chunk = taxids[i : i + chunk_size]

            if i > 0:
                time.sleep(0.5)  # rate-limit between chunks

            try:
                url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                params = {
                    "db": "taxonomy",
                    "id": ",".join(str(t) for t in chunk),
                    "retmode": "xml",
                }

                response = requests.get(url, params=params, timeout=60)
                response.raise_for_status()

                root = ET.fromstring(response.text)

                for taxon_el in root.findall("Taxon"):
                    tid_text = taxon_el.findtext("TaxId")
                    if not tid_text:
                        continue
                    tid = int(tid_text)

                    # Parse superkingdom / kingdom from LineageEx
                    superkingdom = None
                    kingdom_name = None
                    lineage_ex = taxon_el.find("LineageEx")
                    if lineage_ex is not None:
                        for child in lineage_ex.findall("Taxon"):
                            rank = child.findtext("Rank", "")
                            name = child.findtext("ScientificName", "")
                            if rank == "superkingdom":
                                superkingdom = name
                            elif rank == "kingdom":
                                kingdom_name = name

                    if superkingdom:
                        if superkingdom == "Eukaryota" and kingdom_name == "Fungi":
                            results[tid] = "Fungi"
                        elif superkingdom in ("Bacteria", "Archaea", "Eukaryota", "Viruses"):
                            results[tid] = superkingdom
                        continue

                    # Fallback: Lineage text
                    lineage = taxon_el.findtext("Lineage", "")
                    if lineage:
                        parts = [p.strip() for p in lineage.split(";")]
                        for part in parts[:3]:
                            if part in ("Bacteria", "Archaea", "Eukaryota", "Viruses"):
                                results[tid] = part
                                break

            except (requests.exceptions.RequestException, ET.ParseError,
                    ValueError, KeyError) as e:
                logger.exception(f"Batch kingdom lookup failed for chunk starting at index {i}: {e}")

        logger.info(f"Batch kingdom lookup: resolved {len(results)}/{len(taxids)} taxids")
        return results

    def fetch_ncbi_accessions_batch(
        self, taxids: List[int]
    ) -> Dict[int, Tuple[str, Dict[str, Any]]]:
        """
        Fetch NCBI genome accessions for multiple taxids.

        Uses the NCBI Datasets API, querying in small groups to reduce
        the number of HTTP requests while staying within API limits.

        Args:
            taxids: List of NCBI taxonomy IDs.

        Returns:
            Dict mapping taxid to (accession, report_dict). Missing
            entries are omitted.
        """
        if not taxids:
            return {}
        if self.offline_mode:
            logger.debug(f"Offline mode: skipping batch NCBI accession lookup for {len(taxids)} taxids")
            return {}

        results: Dict[int, Tuple[str, Dict[str, Any]]] = {}

        # Query individually but with rate limiting -- the Datasets API
        # taxon endpoint accepts a single taxid per call.
        for idx, taxid in enumerate(taxids):
            if idx > 0:
                time.sleep(0.5)

            result = self.fetch_ncbi_accession(taxid)
            if result:
                results[taxid] = result

        logger.info(
            f"Batch NCBI accession lookup: found {len(results)}/{len(taxids)} accessions"
        )
        return results

    def download_genomes_batch(
        self,
        entries: List[Dict[str, Any]],
        max_workers: int = 3,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[int, Optional[Path]]:
        """
        Download genomes for multiple watchlist entries concurrently.

        Performs batch kingdom lookups first, then downloads genomes
        using a thread pool. This is substantially faster than
        sequential calls to download_genome() for large watchlists.

        Args:
            entries: List of dicts with 'taxid' and 'name' keys.
            max_workers: Maximum concurrent downloads (default 3).
            progress_callback: Optional callback(completed, total, name)
                invoked after each download finishes.

        Returns:
            Dict mapping taxid to Path (success) or None (failure).
        """
        if not entries:
            return {}

        # In offline mode, return only already-downloaded genomes
        if self.offline_mode:
            results: Dict[int, Optional[Path]] = {}
            for entry in entries:
                taxid = entry.get("taxid", 0)
                if not taxid:
                    continue
                if self.has_genome(taxid):
                    results[taxid] = self.get_genome_path(taxid)
                else:
                    msg = "Offline mode -- use Import to add genomes"
                    logger.warning(f"{msg} (taxid={taxid})")
                    self._last_errors[taxid] = msg
                    results[taxid] = None
            return results

        # Deduplicate and filter already-downloaded
        to_download: List[Dict[str, Any]] = []
        results: Dict[int, Optional[Path]] = {}

        for entry in entries:
            taxid = entry.get("taxid", 0)
            if not taxid:
                continue
            if self.has_genome(taxid):
                results[taxid] = self.get_genome_path(taxid)
            else:
                to_download.append(entry)

        if not to_download:
            logger.info("All genomes already downloaded")
            return results

        total = len(to_download)
        logger.info(f"Batch download: {total} genomes to download")

        # Step 1: Batch kingdom lookup
        all_taxids = [e["taxid"] for e in to_download]
        kingdoms = self.get_kingdoms_batch(all_taxids)

        # Step 2: Group entries by download strategy
        virus_entries: List[Dict[str, Any]] = []
        bacteria_entries: List[Dict[str, Any]] = []
        other_entries: List[Dict[str, Any]] = []

        for entry in to_download:
            taxid = entry["taxid"]
            kingdom = kingdoms.get(taxid)
            entry["_kingdom"] = kingdom  # stash for worker
            if kingdom == "Viruses":
                virus_entries.append(entry)
            elif kingdom in ("Bacteria", "Archaea"):
                bacteria_entries.append(entry)
            else:
                other_entries.append(entry)

        # Step 3: Batch NCBI accession lookup for non-virus entries
        ncbi_lookup_taxids = [
            e["taxid"]
            for e in other_entries
            if kingdoms.get(e["taxid"]) not in ("Bacteria", "Archaea")
        ]
        ncbi_accessions: Dict[int, Tuple[str, Dict[str, Any]]] = {}
        if ncbi_lookup_taxids:
            ncbi_accessions = self.fetch_ncbi_accessions_batch(ncbi_lookup_taxids)

        completed = 0
        lock = __import__("threading").Lock()

        def _download_single(entry: Dict[str, Any]) -> Tuple[int, Optional[Path]]:
            """Worker function for a single genome download."""
            nonlocal completed
            taxid = entry["taxid"]
            name = entry.get("name", f"taxid {taxid}")
            kingdom = entry.get("_kingdom")

            self._last_errors.pop(taxid, None)

            path: Optional[Path] = None

            try:
                if kingdom == "Viruses":
                    virus_path, virus_accession = self._download_virus_genome(taxid, name)
                    if virus_path:
                        self._metadata[taxid] = GenomeMetadata(
                            taxid=taxid,
                            species_name=name,
                            accession=virus_accession or f"virus_taxid_{taxid}",
                            source="ncbi_virus",
                            kingdom="Viruses",
                            fasta_path=str(virus_path),
                            file_size=virus_path.stat().st_size if virus_path.exists() else 0,
                        )
                        path = virus_path
                else:
                    accession = None
                    meta_dict: Dict[str, Any] = {}
                    source = "ncbi"

                    # Bacteria/archaea: try GTDB first
                    if kingdom in ("Bacteria", "Archaea"):
                        gtdb_result = self.fetch_gtdb_accession(name)
                        if gtdb_result:
                            accession, meta_dict = gtdb_result
                            source = "gtdb"

                    # Fallback to NCBI
                    if not accession:
                        if taxid in ncbi_accessions:
                            accession, meta_dict = ncbi_accessions[taxid]
                        else:
                            ncbi_result = self.fetch_ncbi_accession(taxid)
                            if ncbi_result:
                                accession, meta_dict = ncbi_result

                    if accession:
                        path = self._download_ncbi_genome(accession, taxid)
                        if path:
                            self._metadata[taxid] = GenomeMetadata(
                                taxid=taxid,
                                species_name=name,
                                accession=accession,
                                source=source,
                                kingdom=kingdom or "Unknown",
                                fasta_path=str(path),
                                file_size=path.stat().st_size if path.exists() else 0,
                                gtdb_taxonomy=meta_dict.get("gtdbTaxonomy"),
                                ncbi_taxonomy=(
                                    meta_dict.get("ncbiTaxonomy")
                                    or meta_dict.get("organism", {}).get("organism_name")
                                ),
                            )

                    # Fallback: download directly by taxid via CLI
                    if not path:
                        logger.info(f"Trying direct taxid download for {name}...")
                        cli_path, cli_accession = self._download_ncbi_genome_by_taxid(taxid, name)
                        if cli_path:
                            self._metadata[taxid] = GenomeMetadata(
                                taxid=taxid,
                                species_name=name,
                                accession=cli_accession or f"taxid_{taxid}",
                                source="ncbi_cli",
                                kingdom=kingdom or "Unknown",
                                fasta_path=str(cli_path),
                                file_size=cli_path.stat().st_size if cli_path.exists() else 0,
                            )
                            path = cli_path
                        else:
                            msg = f"No genome assembly found for {name} (taxid={taxid})"
                            logger.warning(msg)
                            self._last_errors[taxid] = msg

                if not path and taxid not in self._last_errors:
                    self._last_errors[taxid] = f"Download failed for {name} (taxid={taxid})"

            except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                    FileNotFoundError, PermissionError, OSError,
                    requests.exceptions.RequestException, json.JSONDecodeError,
                    zipfile.BadZipFile, ValueError, KeyError, AttributeError) as e:
                # Worker is invoked from a ThreadPoolExecutor; the inner helpers
                # already catch their own narrow families, so anything reaching
                # here is one of: subprocess failure, network failure, JSON or
                # archive corruption, or a known data-shape error.
                logger.warning(
                    "Batch download failed for %s (taxid=%s): %s", name, taxid, e
                )
                logger.debug(
                    "Batch download traceback for %s (taxid=%s)",
                    name, taxid, exc_info=True,
                )
                self._last_errors[taxid] = str(e)

            with lock:
                completed += 1
                if progress_callback:
                    try:
                        progress_callback(completed, total, name)
                    except Exception:
                        # User-supplied callback may raise anything; isolate
                        # the batch loop from caller errors.
                        logger.exception(
                            f"Progress callback raised for taxid {taxid}"
                        )

            return taxid, path

        # Step 4: Run downloads concurrently
        all_entries = virus_entries + bacteria_entries + other_entries

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_download_single, entry): entry
                for entry in all_entries
            }
            for future in as_completed(futures):
                taxid, path = future.result()
                results[taxid] = path

        # Save metadata once at the end
        self._save_metadata()

        succeeded = sum(1 for p in results.values() if p is not None)
        logger.info(
            f"Batch download complete: {succeeded}/{total} succeeded"
        )
        return results

    def build_blast_dbs_batch(
        self, taxids: List[int], max_workers: int = 2
    ) -> int:
        """
        Build BLAST databases for multiple genomes concurrently.

        Args:
            taxids: List of taxonomy IDs to build databases for.
            max_workers: Maximum concurrent makeblastdb processes.

        Returns:
            Number of databases successfully built.
        """
        if not shutil.which("makeblastdb"):
            logger.error("makeblastdb not found. Install BLAST+ toolkit.")
            return 0

        # Filter to taxids that have genomes but no BLAST DB
        to_build = [
            t for t in taxids
            if self.has_genome(t) and not self.has_blast_db(t)
        ]

        if not to_build:
            logger.info("All BLAST databases already built")
            return 0

        logger.info(f"Building {len(to_build)} BLAST databases (workers={max_workers})")
        built = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.build_blast_db, taxid): taxid
                for taxid in to_build
            }
            for future in as_completed(futures):
                taxid = futures[future]
                try:
                    if future.result():
                        built += 1
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                        FileNotFoundError, PermissionError, OSError) as e:
                    logger.exception(f"BLAST DB build failed for taxid {taxid}: {e}")

        logger.info(f"Built {built}/{len(to_build)} BLAST databases")
        return built

    def delete_genome(self, taxid: int) -> bool:
        """
        Delete a downloaded genome and its BLAST database.

        Args:
            taxid: Taxonomy ID

        Returns:
            True if deleted, False otherwise
        """
        try:
            # Delete genome file
            genome_path = self.get_genome_path(taxid)
            if genome_path and genome_path.exists():
                genome_path.unlink()

            # Delete BLAST database files
            blast_db = self.blast_dir / f"{taxid}.fasta"
            for ext in [".nhr", ".nin", ".nsq", ".ndb", ".not", ".ntf", ".nto"]:
                db_file = Path(f"{blast_db}{ext}")
                if db_file.exists():
                    db_file.unlink()

            # Remove from metadata
            if taxid in self._metadata:
                del self._metadata[taxid]
                self._save_metadata()

            logger.info(f"Deleted genome for taxid {taxid}")
            return True

        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.exception(f"Failed to delete genome for taxid {taxid}: {e}")
            return False

    def delete_all_genomes(self) -> int:
        """
        Delete all downloaded genomes and their BLAST databases.

        Returns:
            Number of genomes deleted.
        """
        taxids = list(self._metadata.keys())
        deleted = 0
        for taxid in taxids:
            if self.delete_genome(taxid):
                deleted += 1
        logger.info(f"Deleted {deleted}/{len(taxids)} genomes")
        return deleted

    def import_genomes_from_directory(
        self, source_dir: str
    ) -> Tuple[int, List[Dict[str, str]]]:
        """
        Import genome FASTA files from a local directory.

        Files named ``{taxid}.fasta`` (or ``.fna``, ``.fa``, optionally gzipped)
        are automatically recognized. Other filenames are returned for the caller
        to map manually.

        Args:
            source_dir: Path to directory containing FASTA files.

        Returns:
            Tuple of (number imported, list of unrecognized file dicts).
            Each unrecognized dict has keys ``filename`` and ``path``.
        """
        src = Path(source_dir)
        if not src.is_dir():
            raise ValueError(f"Source directory does not exist: {source_dir}")

        fasta_extensions = {".fasta", ".fna", ".fa"}
        imported = 0
        unrecognized: List[Dict[str, str]] = []

        for fpath in sorted(src.iterdir()):
            if not fpath.is_file():
                continue

            # Determine if it's a FASTA file (optionally gzipped)
            name_lower = fpath.name.lower()
            is_gz = name_lower.endswith(".gz")
            check_name = name_lower[:-3] if is_gz else name_lower
            ext = Path(check_name).suffix

            if ext not in fasta_extensions:
                continue

            # Try to extract taxid from filename
            stem = Path(check_name).stem
            try:
                taxid = int(stem)
            except ValueError:
                unrecognized.append({
                    "filename": fpath.name,
                    "path": str(fpath),
                })
                continue

            # Copy to genomes directory
            dst = self.genomes_dir / fpath.name
            if not dst.exists():
                shutil.copy2(fpath, dst)

            # Create metadata
            species_name, kingdom = self._resolve_species_name(taxid)
            self._metadata[taxid] = GenomeMetadata(
                taxid=taxid,
                species_name=species_name,
                accession="manual_import",
                source="manual",
                kingdom=kingdom,
                fasta_path=str(dst),
                file_size=dst.stat().st_size,
                is_representative=False,
            )
            imported += 1
            logger.info(f"Imported genome: {fpath.name} (taxid {taxid})")

        if imported > 0:
            self._save_metadata()
            # Build BLAST databases for newly imported genomes
            self._build_missing_blast_dbs()

        logger.info(
            f"Imported {imported} genome(s), "
            f"{len(unrecognized)} unrecognized file(s)"
        )
        return imported, unrecognized

    def import_genomes_from_archive(
        self, archive_path: str
    ) -> Tuple[int, List[Dict[str, str]]]:
        """
        Import genome FASTA files from a tar.gz or zip archive.

        Extracts to a temporary directory and delegates to
        ``import_genomes_from_directory``.

        Args:
            archive_path: Path to ``.tar.gz`` or ``.zip`` archive.

        Returns:
            Tuple of (number imported, list of unrecognized file dicts).
        """
        archive = Path(archive_path)
        if not archive.exists():
            raise ValueError(f"Archive not found: {archive_path}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            if archive.name.endswith(".tar.gz") or archive.name.endswith(".tgz"):
                import tarfile as _tarfile
                with _tarfile.open(str(archive), "r:gz") as tar:
                    tar.extractall(path=str(tmp))
            elif archive.name.endswith(".zip"):
                with zipfile.ZipFile(str(archive), "r") as zf:
                    zf.extractall(str(tmp))
            else:
                raise ValueError(
                    f"Unsupported archive format: {archive.name}. "
                    "Use .tar.gz, .tgz, or .zip."
                )

            # The archive may contain files at the top level or in a subdirectory
            # Check if there's a single subdirectory containing the files
            entries = list(tmp.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                extract_dir = entries[0]
            else:
                extract_dir = tmp

            return self.import_genomes_from_directory(str(extract_dir))

    def import_genome_with_taxid(self, fasta_path: str, taxid: int) -> bool:
        """
        Import a single genome file with an explicit taxid mapping.

        Used by the UI when a user manually maps an unrecognized filename
        to a taxid.

        Args:
            fasta_path: Path to the FASTA file.
            taxid: NCBI taxonomy ID to assign.

        Returns:
            True if the import succeeded.
        """
        src = Path(fasta_path)
        if not src.exists():
            logger.error(f"FASTA file not found: {fasta_path}")
            return False

        # Copy with taxid-based naming
        suffix = ".fasta.gz" if src.name.endswith(".gz") else ".fasta"
        dst = self.genomes_dir / f"{taxid}{suffix}"
        if not dst.exists():
            shutil.copy2(src, dst)

        species_name, kingdom = self._resolve_species_name(taxid)
        self._metadata[taxid] = GenomeMetadata(
            taxid=taxid,
            species_name=species_name,
            accession="manual_import",
            source="manual",
            kingdom=kingdom,
            fasta_path=str(dst),
            file_size=dst.stat().st_size,
            is_representative=False,
        )
        self._save_metadata()

        # Build BLAST DB
        self.build_blast_db(taxid)
        logger.info(f"Imported genome {src.name} as taxid {taxid}")
        return True


# Module-level singleton instance with thread-safe initialization and
# reinitialization. Mirrors the locking pattern in
# core/watchlist/watchlist_manager.py:1572-1579 so the two singletons
# behave consistently under Dash's threaded Flask worker model.
_genome_manager: Optional[GenomeDownloadManager] = None
_gm_lock = threading.Lock()


def get_genome_manager(
    cache_dir: Optional[str] = None,
    offline_mode: Optional[bool] = None,
) -> GenomeDownloadManager:
    """
    Get the GenomeDownloadManager instance.

    Args:
        cache_dir: Optional cache directory. If provided and different from
                   current manager's cache_dir, a new instance is created.
                   Defaults to ~/.nanometa if not specified.
        offline_mode: If provided, update the instance's offline_mode flag.

    Returns:
        GenomeDownloadManager instance
    """
    global _genome_manager

    # Normalize cache_dir for comparison
    if cache_dir:
        normalized_cache = Path(cache_dir).expanduser().resolve()
    else:
        normalized_cache = None

    # First-time creation -- double-checked locking so the global is
    # only ever assigned by one thread; concurrent first callers
    # otherwise overwrite each other and orphan in-flight downloads.
    if _genome_manager is None:
        with _gm_lock:
            if _genome_manager is None:
                _genome_manager = GenomeDownloadManager(
                    cache_dir=cache_dir,
                    offline_mode=bool(offline_mode) if offline_mode is not None else False,
                )

    # Reinitialize-on-cache-dir-change and offline_mode toggle both
    # mutate _genome_manager; serialize them under the same lock so a
    # caller observing the new instance also sees the offline_mode
    # update consistently.
    if cache_dir is not None or offline_mode is not None:
        with _gm_lock:
            if cache_dir is not None and normalized_cache is not None:
                current_cache = _genome_manager.cache_dir
                if normalized_cache != current_cache:
                    logger.debug(
                        f"Reinitializing genome manager with new cache_dir: {cache_dir}"
                    )
                    _genome_manager = GenomeDownloadManager(
                        cache_dir=cache_dir,
                        offline_mode=(
                            bool(offline_mode)
                            if offline_mode is not None
                            else _genome_manager.offline_mode
                        ),
                    )

            if (
                offline_mode is not None
                and _genome_manager.offline_mode != offline_mode
            ):
                _genome_manager.offline_mode = offline_mode
                logger.info(
                    f"Genome manager offline_mode updated to {offline_mode}"
                )

    return _genome_manager
