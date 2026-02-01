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
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from nanometa_live.core.taxonomy.taxonomy_api import get_ncbi_client

logger = logging.getLogger(__name__)


# GTDB API endpoint
GTDB_API_BASE = "https://gtdb-api.ecogenomic.org"

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


class GenomeDownloadManager:
    """
    Manages pathogen reference genome downloads and BLAST database building.

    Downloads reference genomes for pathogens in the watchlist:
    - Bacteria/Archaea: Uses GTDB representative genomes
    - Other kingdoms: Uses NCBI RefSeq representative genomes

    Caches downloads in ~/.nanometa/genomes/ with metadata tracking.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the genome download manager.

        Args:
            cache_dir: Base cache directory. Defaults to ~/.nanometa
        """
        if cache_dir is None:
            cache_dir = "~/.nanometa"

        # Always expand user home directory and resolve to absolute path
        self.cache_dir = Path(os.path.expanduser(cache_dir)).resolve()
        self.genomes_dir = self.cache_dir / "genomes"
        self.blast_dir = self.cache_dir / "blast"
        self.metadata_file = self.cache_dir / "genome_metadata.json"

        # Create directories
        self.genomes_dir.mkdir(parents=True, exist_ok=True)
        self.blast_dir.mkdir(parents=True, exist_ok=True)

        # Load existing metadata
        self._metadata: Dict[int, GenomeMetadata] = {}
        self._last_errors: Dict[int, str] = {}  # taxid → error message
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

        except Exception as e:
            logger.warning(f"Failed to resolve species name for taxid {taxid}: {e}")

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

            # Resolve species name from NCBI
            species_name, kingdom = self._resolve_species_name(taxid)

            self._metadata[taxid] = GenomeMetadata(
                taxid=taxid,
                species_name=species_name,
                accession="discovered",
                source="discovered",
                kingdom=kingdom,
                fasta_path=str(fasta_file),
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
        """
        # Check if makeblastdb is available
        if not shutil.which("makeblastdb"):
            logger.debug("makeblastdb not found, skipping auto-build of BLAST databases")
            return

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
            logger.info(f"Built {built} missing BLAST databases")

    def _load_metadata(self) -> None:
        """Load genome metadata from cache."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    data = json.load(f)
                    for taxid_str, meta_dict in data.items():
                        self._metadata[int(taxid_str)] = GenomeMetadata.from_dict(meta_dict)
                logger.info(f"Loaded metadata for {len(self._metadata)} genomes")
            except Exception as e:
                logger.warning(f"Failed to load genome metadata: {e}")

    def _save_metadata(self) -> None:
        """Save genome metadata to cache."""
        try:
            data = {str(k): v.to_dict() for k, v in self._metadata.items()}
            with open(self.metadata_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save genome metadata: {e}")

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

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Kingdom name (Bacteria, Archaea, Fungi, Viruses, etc.) or None
        """
        try:
            # Use NCBI Taxonomy API
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            params = {
                "db": "taxonomy",
                "id": taxid,
                "retmode": "xml"
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            # Parse XML to find kingdom/domain
            content = response.text

            # Look for superkingdom/domain in lineage
            if "Bacteria" in content:
                return "Bacteria"
            elif "Archaea" in content:
                return "Archaea"
            elif "Fungi" in content:
                return "Fungi"
            elif "Viruses" in content or "Viridae" in content:
                return "Viruses"
            elif "Eukaryota" in content:
                return "Eukaryota"

            return None

        except Exception as e:
            logger.error(f"Failed to get kingdom for taxid {taxid}: {e}")
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

        except Exception as e:
            logger.error(f"GTDB API error for '{species_name}': {e}")
            return None

    def fetch_ncbi_accession(self, taxid: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Get NCBI RefSeq representative genome accession for a taxid.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            Tuple of (accession, metadata_dict) or None if not found
        """
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
                logger.warning(f"No genome assemblies found at NCBI for taxid {taxid}")
                return None

            response.raise_for_status()
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

        except Exception as e:
            logger.error(f"NCBI API error for taxid {taxid}: {e}")
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

                logger.info(f"Downloaded genome to {output_file}")
                return output_file

        except subprocess.TimeoutExpired:
            logger.error(f"Download timed out for {accession}")
            return None
        except Exception as e:
            logger.error(f"Download failed for {accession}: {e}")
            return None

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

        except Exception as e:
            logger.error(f"Failed to build BLAST database: {e}")
            return False

    def get_all_genomes(self) -> List[GenomeMetadata]:
        """Get list of all downloaded genomes."""
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
        except Exception as e:
            logger.error(f"Failed to write pathogen_genomes.json: {e}")
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

        except Exception as e:
            logger.error(f"Failed to delete genome for taxid {taxid}: {e}")
            return False


# Singleton instance
_genome_manager: Optional[GenomeDownloadManager] = None


def get_genome_manager(cache_dir: Optional[str] = None) -> GenomeDownloadManager:
    """
    Get the GenomeDownloadManager instance.

    Args:
        cache_dir: Optional cache directory. If provided and different from
                   current manager's cache_dir, a new instance is created.
                   Defaults to ~/.nanometa if not specified.

    Returns:
        GenomeDownloadManager instance
    """
    global _genome_manager

    # Normalize cache_dir for comparison
    if cache_dir:
        normalized_cache = Path(cache_dir).expanduser().resolve()
    else:
        normalized_cache = None

    # Check if we need to create a new instance
    if _genome_manager is None:
        _genome_manager = GenomeDownloadManager(cache_dir=cache_dir)
    elif cache_dir is not None:
        # Check if cache_dir differs from current instance
        current_cache = _genome_manager.cache_dir
        if normalized_cache and normalized_cache != current_cache:
            logger.info(f"Reinitializing genome manager with new cache_dir: {cache_dir}")
            _genome_manager = GenomeDownloadManager(cache_dir=cache_dir)

    return _genome_manager
