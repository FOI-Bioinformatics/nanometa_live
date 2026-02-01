"""
Taxonomy API Client for Nanometa Live.

Provides HTTP clients for NCBI E-utilities and GTDB API with persistent
local caching for offline use.

NCBI E-utilities:
- ESearch: Search taxonomy by name
- ESummary: Get taxonomy details by taxid
- Rate limit: 3 requests/sec without API key, 10/sec with key

GTDB API:
- Search species by name
- Get taxonomy string for species
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import requests

logger = logging.getLogger(__name__)

# Default cache location
DEFAULT_CACHE_DIR = Path.home() / ".nanometa" / "cache"
CACHE_FILE = "taxonomy_cache.json"
CACHE_VERSION = "1.0"

# Rate limiting
NCBI_RATE_LIMIT = 3  # requests per second without API key
GTDB_RATE_LIMIT = 5  # requests per second (reasonable default)


@dataclass
class NCBIResult:
    """Result from NCBI taxonomy lookup."""
    taxid: int
    sciname: str
    commonname: str = ""
    rank: str = ""
    division: str = ""
    lineage: List[str] = field(default_factory=list)
    ncbi_link: str = ""
    cached_at: Optional[str] = None

    def __post_init__(self):
        if not self.ncbi_link and self.taxid:
            self.ncbi_link = f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={self.taxid}"
        if not self.cached_at:
            self.cached_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for caching."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NCBIResult":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class GTDBResult:
    """Result from GTDB taxonomy lookup."""
    gtdb_taxonomy: str  # Full taxonomy string: d__Bacteria;p__...;s__Species
    species: str
    gtdb_link: str = ""
    genome_count: int = 0
    type_material: bool = False
    cached_at: Optional[str] = None

    def __post_init__(self):
        if not self.cached_at:
            self.cached_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for caching."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GTDBResult":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TaxonomyCache:
    """
    Persistent local cache for taxonomy API results.

    Cache format:
    {
        "version": "1.0",
        "last_updated": "2024-12-14T15:30:00Z",
        "ncbi": {
            "entries": { taxid_str: NCBIResult_dict, ... },
            "name_to_taxid": { name_lower: taxid, ... }
        },
        "gtdb": {
            "entries": { species_key: GTDBResult_dict, ... }
        }
    }
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize the cache."""
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_file = self.cache_dir / CACHE_FILE
        self._data: Dict[str, Any] = {
            "version": CACHE_VERSION,
            "last_updated": None,
            "ncbi": {"entries": {}, "name_to_taxid": {}},
            "gtdb": {"entries": {}},
        }
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if loaded.get("version") == CACHE_VERSION:
                        self._data = loaded
                        logger.debug(f"Loaded taxonomy cache: {self.cache_file}")
                    else:
                        logger.info("Cache version mismatch, starting fresh")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._data["last_updated"] = datetime.utcnow().isoformat() + "Z"
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            logger.debug(f"Saved taxonomy cache: {self.cache_file}")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    # NCBI cache methods
    def get_ncbi_by_taxid(self, taxid: int) -> Optional[NCBIResult]:
        """Get cached NCBI result by taxid."""
        entry = self._data["ncbi"]["entries"].get(str(taxid))
        if entry:
            return NCBIResult.from_dict(entry)
        return None

    def get_ncbi_by_name(self, name: str) -> Optional[NCBIResult]:
        """Get cached NCBI result by name."""
        taxid = self._data["ncbi"]["name_to_taxid"].get(name.lower())
        if taxid:
            return self.get_ncbi_by_taxid(taxid)
        return None

    def set_ncbi(self, result: NCBIResult) -> None:
        """Cache an NCBI result."""
        self._data["ncbi"]["entries"][str(result.taxid)] = result.to_dict()
        self._data["ncbi"]["name_to_taxid"][result.sciname.lower()] = result.taxid
        self._save()

    # GTDB cache methods
    def get_gtdb(self, species: str) -> Optional[GTDBResult]:
        """Get cached GTDB result by species name."""
        key = species.lower().replace(" ", "_")
        entry = self._data["gtdb"]["entries"].get(key)
        if entry:
            return GTDBResult.from_dict(entry)
        return None

    def set_gtdb(self, result: GTDBResult) -> None:
        """Cache a GTDB result."""
        key = result.species.lower().replace(" ", "_")
        self._data["gtdb"]["entries"][key] = result.to_dict()
        self._save()

    def clear(self) -> None:
        """Clear all cached entries."""
        self._data = {
            "version": CACHE_VERSION,
            "last_updated": None,
            "ncbi": {"entries": {}, "name_to_taxid": {}},
            "gtdb": {"entries": {}},
        }
        self._save()
        logger.info("Taxonomy cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "ncbi_entries": len(self._data["ncbi"]["entries"]),
            "gtdb_entries": len(self._data["gtdb"]["entries"]),
            "last_updated": self._data.get("last_updated"),
            "cache_file": str(self.cache_file),
        }


class TaxonomyAPIClient(ABC):
    """Base class for taxonomy API clients."""

    def __init__(
        self,
        cache: Optional[TaxonomyCache] = None,
        rate_limit: float = 3.0,
        timeout: int = 30,
    ):
        """
        Initialize the API client.

        Args:
            cache: TaxonomyCache instance (shared across clients)
            rate_limit: Maximum requests per second
            timeout: Request timeout in seconds
        """
        self.cache = cache or TaxonomyCache()
        self.rate_limit = rate_limit
        self.timeout = timeout
        self._last_request_time = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "NanometaLive/2.1 (taxonomy validation)"
        })

    def _rate_limit_wait(self) -> None:
        """Wait to respect rate limit."""
        if self.rate_limit > 0:
            elapsed = time.time() - self._last_request_time
            min_interval = 1.0 / self.rate_limit
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)

    def _make_request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
    ) -> Optional[Dict[str, Any]]:
        """Make an HTTP request with rate limiting."""
        self._rate_limit_wait()

        try:
            self._last_request_time = time.time()
            if method == "GET":
                response = self._session.get(url, params=params, timeout=self.timeout)
            else:
                response = self._session.post(url, data=params, timeout=self.timeout)

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.warning(f"API request failed: {url} - {e}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse API response: {e}")
            return None

    @abstractmethod
    def search_by_name(self, name: str) -> Optional[Any]:
        """Search for a species by name."""
        pass

    @abstractmethod
    def get_by_taxid(self, taxid: int) -> Optional[Any]:
        """Get species information by taxonomy ID."""
        pass


class NCBIClient(TaxonomyAPIClient):
    """
    NCBI E-utilities client for taxonomy lookups.

    Uses the E-utilities API:
    - esearch.fcgi: Search for taxids by name
    - esummary.fcgi: Get taxonomy details by taxid
    - efetch.fcgi: Get full taxonomy record (lineage)

    Rate limit: 3 requests/sec without API key, 10/sec with key.
    Register at: https://www.ncbi.nlm.nih.gov/account/
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(
        self,
        cache: Optional[TaxonomyCache] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize NCBI client.

        Args:
            cache: TaxonomyCache instance
            api_key: Optional NCBI API key for higher rate limits
        """
        rate_limit = 10.0 if api_key else NCBI_RATE_LIMIT
        super().__init__(cache=cache, rate_limit=rate_limit)
        self.api_key = api_key

    def _build_params(self, extra_params: Dict[str, Any]) -> Dict[str, Any]:
        """Build request parameters with API key if available."""
        params = {"retmode": "json"}
        if self.api_key:
            params["api_key"] = self.api_key
        params.update(extra_params)
        return params

    def search_by_name(self, name: str) -> Optional[NCBIResult]:
        """
        Search NCBI taxonomy by species name.

        Args:
            name: Scientific name to search for

        Returns:
            NCBIResult if found, None otherwise
        """
        # Check cache first
        cached = self.cache.get_ncbi_by_name(name)
        if cached:
            logger.debug(f"NCBI cache hit for name: {name}")
            return cached

        # Search for taxid
        url = f"{self.BASE_URL}/esearch.fcgi"
        params = self._build_params({
            "db": "taxonomy",
            "term": f'"{name}"[Scientific Name]',
        })

        result = self._make_request(url, params)
        if not result:
            return None

        try:
            id_list = result.get("esearchresult", {}).get("idlist", [])
            if not id_list:
                # Try broader search without quotes
                params["term"] = name
                result = self._make_request(url, params)
                if result:
                    id_list = result.get("esearchresult", {}).get("idlist", [])

            if id_list:
                taxid = int(id_list[0])
                return self.get_by_taxid(taxid)

        except (KeyError, ValueError, IndexError) as e:
            logger.warning(f"Failed to parse NCBI search result: {e}")

        return None

    def get_by_taxid(self, taxid: int) -> Optional[NCBIResult]:
        """
        Get taxonomy details by NCBI taxid.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            NCBIResult if found, None otherwise
        """
        # Check cache first
        cached = self.cache.get_ncbi_by_taxid(taxid)
        if cached:
            logger.debug(f"NCBI cache hit for taxid: {taxid}")
            return cached

        # Get summary
        url = f"{self.BASE_URL}/esummary.fcgi"
        params = self._build_params({
            "db": "taxonomy",
            "id": str(taxid),
        })

        result = self._make_request(url, params)
        if not result:
            return None

        try:
            doc_sum = result.get("result", {}).get(str(taxid), {})
            if not doc_sum or "error" in doc_sum:
                return None

            ncbi_result = NCBIResult(
                taxid=taxid,
                sciname=doc_sum.get("scientificname", ""),
                commonname=doc_sum.get("commonname", ""),
                rank=doc_sum.get("rank", ""),
                division=doc_sum.get("division", ""),
            )

            # Get lineage separately
            lineage = self.get_lineage(taxid)
            if lineage:
                ncbi_result.lineage = lineage

            # Cache the result
            self.cache.set_ncbi(ncbi_result)
            logger.info(f"NCBI lookup: {ncbi_result.sciname} (taxid: {taxid})")
            return ncbi_result

        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse NCBI summary: {e}")
            return None

    def get_lineage(self, taxid: int) -> List[str]:
        """
        Get the taxonomic lineage for a taxid.

        Args:
            taxid: NCBI taxonomy ID

        Returns:
            List of lineage names from domain to species
        """
        url = f"{self.BASE_URL}/efetch.fcgi"
        params = self._build_params({
            "db": "taxonomy",
            "id": str(taxid),
            "rettype": "xml",
        })

        # For lineage we need XML, so handle differently
        self._rate_limit_wait()
        try:
            self._last_request_time = time.time()
            response = self._session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            # Parse lineage from XML (simple extraction)
            text = response.text
            lineage = []

            # Extract lineage from <LineageEx> section
            if "<LineageEx>" in text:
                lineage_section = text.split("<LineageEx>")[1].split("</LineageEx>")[0]
                # Extract scientific names
                import re
                names = re.findall(r"<ScientificName>([^<]+)</ScientificName>", lineage_section)
                lineage = names

            return lineage

        except Exception as e:
            logger.debug(f"Failed to get lineage for {taxid}: {e}")
            return []

    def validate_taxid(self, taxid: int) -> bool:
        """
        Check if a taxid is valid in NCBI.

        Args:
            taxid: NCBI taxonomy ID to validate

        Returns:
            True if valid, False otherwise
        """
        result = self.get_by_taxid(taxid)
        return result is not None


class GTDBClient(TaxonomyAPIClient):
    """
    GTDB API client for taxonomy lookups.

    GTDB (Genome Taxonomy Database) provides a standardized bacterial
    and archaeal taxonomy based on genome phylogeny.

    API documentation: https://gtdb-api.ecogenomic.org/docs
    """

    BASE_URL = "https://api.gtdb.ecogenomic.org"

    def __init__(self, cache: Optional[TaxonomyCache] = None):
        """Initialize GTDB client."""
        super().__init__(cache=cache, rate_limit=GTDB_RATE_LIMIT)

    def search_by_name(self, name: str) -> Optional[GTDBResult]:
        """
        Search GTDB for a species by name.

        Args:
            name: Species name to search for

        Returns:
            GTDBResult if found, None otherwise
        """
        # Check cache first
        cached = self.cache.get_gtdb(name)
        if cached:
            logger.debug(f"GTDB cache hit for: {name}")
            return cached

        # Format name for GTDB search (replace space with underscore for species)
        search_term = name.replace(" ", "_")

        # Try species search endpoint
        url = f"{self.BASE_URL}/species/search"
        params = {"search": search_term, "limit": 5}

        result = self._make_request(url, params)
        if result and isinstance(result, list) and len(result) > 0:
            return self._parse_species_result(result[0])

        # Try taxon search as fallback
        url = f"{self.BASE_URL}/taxon/search"
        params = {"search": name, "limit": 5}

        result = self._make_request(url, params)
        if result and isinstance(result, list) and len(result) > 0:
            return self._parse_taxon_result(result[0])

        return None

    def get_by_taxid(self, taxid: int) -> Optional[GTDBResult]:
        """
        GTDB doesn't use NCBI taxids directly.
        This method attempts to search by the species name associated with the taxid.

        For GTDB-specific lookups, use search_by_name() with the species name.
        """
        # GTDB uses its own taxonomy, not NCBI taxids
        # Return None - caller should use search_by_name instead
        logger.debug(f"GTDB doesn't support direct taxid lookup: {taxid}")
        return None

    def search_species(self, query: str) -> List[GTDBResult]:
        """
        Search for species matching a query.

        Args:
            query: Search query

        Returns:
            List of matching GTDBResult objects
        """
        url = f"{self.BASE_URL}/species/search"
        params = {"search": query.replace(" ", "_"), "limit": 10}

        result = self._make_request(url, params)
        if not result or not isinstance(result, list):
            return []

        results = []
        for item in result:
            parsed = self._parse_species_result(item)
            if parsed:
                results.append(parsed)

        return results

    def get_taxonomy_string(self, species_name: str) -> Optional[str]:
        """
        Get the full GTDB taxonomy string for a species.

        Args:
            species_name: Species name (e.g., "Escherichia coli")

        Returns:
            Full taxonomy string (e.g., "d__Bacteria;p__Proteobacteria;...")
        """
        result = self.search_by_name(species_name)
        if result:
            return result.gtdb_taxonomy
        return None

    def _parse_species_result(self, data: Dict[str, Any]) -> Optional[GTDBResult]:
        """Parse a species search result."""
        try:
            # Extract species name from gtdb_taxonomy if available
            gtdb_taxonomy = data.get("gtdb_taxonomy", "")
            species = data.get("species", "")

            if not species and gtdb_taxonomy:
                # Extract species from taxonomy string
                parts = gtdb_taxonomy.split(";")
                for part in parts:
                    if part.startswith("s__"):
                        species = part[3:].replace("_", " ")
                        break

            if not species:
                return None

            # Build GTDB link
            gtdb_link = ""
            if species:
                encoded = quote(species.replace(" ", "_"))
                gtdb_link = f"https://gtdb.ecogenomic.org/species?id={encoded}"

            result = GTDBResult(
                gtdb_taxonomy=gtdb_taxonomy,
                species=species,
                gtdb_link=gtdb_link,
                genome_count=data.get("genome_count", 0),
                type_material=data.get("type_material", False),
            )

            # Cache the result
            self.cache.set_gtdb(result)
            logger.info(f"GTDB lookup: {species}")
            return result

        except (KeyError, ValueError) as e:
            logger.debug(f"Failed to parse GTDB result: {e}")
            return None

    def _parse_taxon_result(self, data: Dict[str, Any]) -> Optional[GTDBResult]:
        """Parse a taxon search result."""
        try:
            taxon = data.get("taxon", "")
            taxonomy = data.get("taxonomy", "")

            if not taxon:
                return None

            # Check if this is a species-level result
            if taxon.startswith("s__"):
                species = taxon[3:].replace("_", " ")
            else:
                # Not a species, but return anyway for reference
                species = taxon

            gtdb_link = f"https://gtdb.ecogenomic.org/tree?r={quote(taxon)}"

            result = GTDBResult(
                gtdb_taxonomy=taxonomy or taxon,
                species=species,
                gtdb_link=gtdb_link,
            )

            self.cache.set_gtdb(result)
            return result

        except (KeyError, ValueError) as e:
            logger.debug(f"Failed to parse GTDB taxon result: {e}")
            return None


# Module-level singleton instances
_taxonomy_cache: Optional[TaxonomyCache] = None
_ncbi_client: Optional[NCBIClient] = None
_gtdb_client: Optional[GTDBClient] = None


def get_taxonomy_cache() -> TaxonomyCache:
    """Get the shared taxonomy cache instance."""
    global _taxonomy_cache
    if _taxonomy_cache is None:
        _taxonomy_cache = TaxonomyCache()
    return _taxonomy_cache


def get_ncbi_client(api_key: Optional[str] = None) -> NCBIClient:
    """Get the NCBI client instance."""
    global _ncbi_client
    if _ncbi_client is None:
        _ncbi_client = NCBIClient(cache=get_taxonomy_cache(), api_key=api_key)
    return _ncbi_client


def get_gtdb_client() -> GTDBClient:
    """Get the GTDB client instance."""
    global _gtdb_client
    if _gtdb_client is None:
        _gtdb_client = GTDBClient(cache=get_taxonomy_cache())
    return _gtdb_client


def validate_taxid_source(taxid: int) -> Dict[str, Any]:
    """
    Validate a taxid and determine its source (NCBI or custom).

    Args:
        taxid: Taxonomy ID to validate

    Returns:
        Dict with:
        - is_ncbi: True if valid in NCBI
        - ncbi_result: NCBIResult if found
        - gtdb_result: GTDBResult if species name matches in GTDB
    """
    ncbi = get_ncbi_client()
    gtdb = get_gtdb_client()

    result = {
        "taxid": taxid,
        "is_ncbi": False,
        "ncbi_result": None,
        "gtdb_result": None,
        "source": "unknown",
    }

    # Check NCBI
    ncbi_result = ncbi.get_by_taxid(taxid)
    if ncbi_result:
        result["is_ncbi"] = True
        result["ncbi_result"] = ncbi_result
        result["source"] = "ncbi"

        # Also try to find GTDB equivalent
        gtdb_result = gtdb.search_by_name(ncbi_result.sciname)
        if gtdb_result:
            result["gtdb_result"] = gtdb_result

    return result


def lookup_species(
    name: str,
    use_ncbi: bool = True,
    use_gtdb: bool = True,
) -> Dict[str, Any]:
    """
    Look up a species by name in both NCBI and GTDB.

    Args:
        name: Species name to search
        use_ncbi: Whether to query NCBI
        use_gtdb: Whether to query GTDB

    Returns:
        Dict with:
        - name: Search name
        - ncbi_result: NCBIResult if found
        - gtdb_result: GTDBResult if found
    """
    result = {
        "name": name,
        "ncbi_result": None,
        "gtdb_result": None,
    }

    if use_ncbi:
        ncbi = get_ncbi_client()
        result["ncbi_result"] = ncbi.search_by_name(name)

    if use_gtdb:
        gtdb = get_gtdb_client()
        result["gtdb_result"] = gtdb.search_by_name(name)

    return result
