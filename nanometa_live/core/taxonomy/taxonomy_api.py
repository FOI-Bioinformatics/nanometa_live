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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
import urllib3

from nanometa_live.core.utils.offline_cache import get_cache as get_offline_cache

logger = logging.getLogger(__name__)


def _utcnow():
    """Naive UTC timestamp, replacing the deprecated stdlib utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Default cache location. Resolved from NANOMETA_DATA_DIR (set by the CLI
# entry point from --data-dir) so the taxonomy cache follows the operator's
# chosen data directory, matching offline_cache._default_cache_dir(). Falls
# back to the legacy ~/.nanometa/cache when the env var is unset.
def _default_taxonomy_cache_dir() -> Path:
    from nanometa_live.core.utils.paths import get_data_dir_from_env
    return Path(get_data_dir_from_env()) / "cache"


DEFAULT_CACHE_DIR = _default_taxonomy_cache_dir()
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
            self.cached_at = _utcnow().isoformat() + "Z"

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
            self.cached_at = _utcnow().isoformat() + "Z"

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
            except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as e:
                logger.exception(f"Failed to load cache: {e}")

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._data["last_updated"] = _utcnow().isoformat() + "Z"
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            logger.debug(f"Saved taxonomy cache: {self.cache_file}")
        except (FileNotFoundError, PermissionError, OSError, TypeError, ValueError) as e:
            logger.exception(f"Failed to save cache: {e}")

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


def _classify_request_error(exc: Exception) -> str:
    """Map a requests exception to a short, operator-facing reason code."""
    if isinstance(exc, requests.exceptions.SSLError):
        return "ssl_error"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return f"http_{status}" if status else "http_error"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    return "network_error"


# Human-readable phrasing for the reason codes above, for UI toasts.
_REASON_LABELS = {
    "ssl_error": "SSL certificate verification failed",
    "timeout": "request timed out",
    "connection_error": "could not connect",
    "bad_response": "unexpected response",
    "http_400": "rejected the request (HTTP 400)",
    "http_error": "returned an HTTP error",
    "network_error": "network error",
    "circuit_open": "skipped after repeated failures",
}


def describe_failure_reason(reason: str) -> str:
    """Return a human phrase for a circuit-breaker reason code."""
    return _REASON_LABELS.get(reason, reason.replace("_", " "))


class TaxonomyAPIClient(ABC):
    """Base class for taxonomy API clients."""

    # Per-host circuit breaker. Once a host has failed
    # _CIRCUIT_FAILURE_THRESHOLD times in a row in the current process,
    # subsequent calls are short-circuited for the remainder of the
    # session. Prevents the GUI lockup that would otherwise hit when
    # GTDB is degraded -- 17 watchlist entries x 2 APIs x ~5 s per
    # SSL-failing call would block the Dash callback thread for over
    # a minute. The breaker is in-memory, per-process, and resets on
    # app restart so a transient outage does not leave a permanent
    # disabled flag on disk.
    _CIRCUIT_FAILURE_THRESHOLD: int = 3
    _circuit_failures: Dict[str, int] = {}
    _circuit_open: Dict[str, bool] = {}
    # Last failure reason per host (ssl_error / http_4xx / timeout /
    # connection_error / network_error), so callers can tell the operator
    # WHY a host failed rather than reporting a silent partial count.
    _circuit_last_reason: Dict[str, str] = {}

    # NCBI taxids at/above this synthetic band are pseudo-taxids minted by
    # the watchlist for name-only/custom entries (see watchlist_manager
    # _PSEUDO_TAXID_BASE). They are NOT real NCBI ids; sending one to NCBI
    # esummary returns HTTP 400, so by-taxid lookups must skip them.
    _PSEUDO_TAXID_MIN: int = 2_000_000_000

    @classmethod
    def reset_circuit_breaker(cls) -> None:
        """Clear all circuit-breaker state for this process.

        Called at the start of a bulk validation run so a transient host
        failure from an earlier run cannot silently short-circuit the whole
        new run. The in-run breaker still trips after the threshold, so a
        genuinely-down host does not stall the rest of the batch.
        """
        cls._circuit_failures.clear()
        cls._circuit_open.clear()
        cls._circuit_last_reason.clear()

    @classmethod
    def circuit_failure_summary(cls) -> Dict[str, str]:
        """Return {host: last_failure_reason} for hosts that have failed."""
        return dict(cls._circuit_last_reason)

    def __init__(
        self,
        cache: Optional[TaxonomyCache] = None,
        rate_limit: float = 3.0,
        timeout: int = 5,
        offline_mode: bool = False,
    ):
        """
        Initialize the API client.

        Args:
            cache: TaxonomyCache instance (shared across clients)
            rate_limit: Maximum requests per second
            timeout: Request timeout in seconds. Default lowered to 5 s
                because every taxonomy lookup runs on the synchronous
                Dash callback thread; longer waits manifest to the
                operator as an unresponsive watchlist tab.
            offline_mode: If True, skip all network calls and use cached data only
        """
        self.cache = cache or TaxonomyCache()
        self.rate_limit = rate_limit
        self.timeout = timeout
        self.offline_mode = offline_mode
        self._last_request_time = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "NanometaLive/2.1 (taxonomy validation)"
        })

    @classmethod
    def _circuit_host(cls, url: str) -> str:
        """Return the host portion used as the circuit-breaker key."""
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc or url
        except Exception:
            # Fall back to the raw URL as the breaker key, but log it: a URL
            # that cannot be parsed points at a malformed endpoint that
            # warrants triage rather than silent per-call retries.
            logger.warning("Could not parse circuit-breaker host from URL %r; "
                           "using raw URL as key", url, exc_info=True)
            return url

    @classmethod
    def _circuit_record_failure(cls, url: str, reason: str = "network_error") -> None:
        host = cls._circuit_host(url)
        cls._circuit_last_reason[host] = reason
        cls._circuit_failures[host] = cls._circuit_failures.get(host, 0) + 1
        if cls._circuit_failures[host] >= cls._CIRCUIT_FAILURE_THRESHOLD:
            if not cls._circuit_open.get(host):
                logger.warning(
                    "Taxonomy API circuit breaker OPEN for %s after %d "
                    "consecutive failures; skipping further calls for "
                    "this session.",
                    host,
                    cls._circuit_failures[host],
                )
            cls._circuit_open[host] = True

    @classmethod
    def _circuit_record_success(cls, url: str) -> None:
        host = cls._circuit_host(url)
        cls._circuit_failures.pop(host, None)
        cls._circuit_open.pop(host, None)

    @classmethod
    def _circuit_is_open(cls, url: str) -> bool:
        return cls._circuit_open.get(cls._circuit_host(url), False)

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
        if self.offline_mode:
            logger.debug(f"Offline mode: skipping request to {url}")
            return None

        # Short-circuit if this host has been failing all session.
        # Avoids the 5 s x N timeout pile-up that locks the Dash
        # callback thread when GTDB or NCBI is degraded.
        if self._circuit_is_open(url):
            logger.debug("Circuit open for %s, skipping request", url)
            return None

        self._rate_limit_wait()

        try:
            self._last_request_time = time.time()
            if method == "GET":
                response = self._session.get(url, params=params, timeout=self.timeout)
            else:
                response = self._session.post(url, data=params, timeout=self.timeout)

            response.raise_for_status()
            self._circuit_record_success(url)
            return response.json()

        except requests.exceptions.SSLError:
            # DEBUG, not WARNING: the per-call SSL fallback is
            # routine on networks with corporate MITM proxies. The
            # circuit-breaker OPEN warning below covers the case
            # where the host is genuinely unreachable.
            logger.debug(
                "SSL verification failed for %s, retrying without verification", url
            )
            try:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                self._last_request_time = time.time()
                if method == "GET":
                    response = self._session.get(
                        url, params=params, timeout=self.timeout, verify=False
                    )
                else:
                    response = self._session.post(
                        url, data=params, timeout=self.timeout, verify=False
                    )
                response.raise_for_status()
                self._circuit_record_success(url)
                return response.json()
            except requests.exceptions.RequestException as e:
                # Per-call failure recorded; the circuit breaker
                # surfaces the user-visible WARNING once the threshold
                # is crossed, so individual failures stay at DEBUG.
                logger.debug("API request failed (SSL fallback): %s - %s", url, e)
                # The host's TLS could not be verified even with the fallback;
                # report it as an SSL error so the operator can fix trust.
                self._circuit_record_failure(url, "ssl_error")
                return None

        except requests.exceptions.RequestException as e:
            logger.debug(f"API request failed: {url} - {e}")
            self._circuit_record_failure(url, _classify_request_error(e))
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse API response: {e}")
            self._circuit_record_failure(url, "bad_response")
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

        # In offline mode, also check OfflineTaxonomyCache before giving up
        if self.offline_mode:
            offline_cache = get_offline_cache(offline_mode=True)
            offline_data = offline_cache.get(name, cache_type="ncbi")
            if offline_data:
                logger.debug(f"Offline cache hit for name: {name}")
                return NCBIResult.from_dict(offline_data) if isinstance(offline_data, dict) else None
            logger.debug(f"Offline mode: no cached data for {name}")
            return None

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

        # In offline mode, also check OfflineTaxonomyCache before giving up
        if self.offline_mode:
            offline_cache = get_offline_cache(offline_mode=True)
            offline_data = offline_cache.get_ncbi_taxonomy(taxid)
            if offline_data:
                logger.debug(f"Offline cache hit for taxid: {taxid}")
                return NCBIResult.from_dict(offline_data) if isinstance(offline_data, dict) else None
            logger.debug(f"Offline mode: no cached data for taxid {taxid}")
            return None

        # Pseudo-taxids (name-only / custom watchlist entries) are not real
        # NCBI ids -- esummary returns HTTP 400 for them, which would trip the
        # circuit breaker and silently fail the rest of a bulk run. Skip the
        # request; the caller falls back to search_by_name.
        if taxid <= 0 or taxid >= self._PSEUDO_TAXID_MIN:
            logger.debug("Skipping NCBI by-taxid for non-real taxid %s", taxid)
            return None

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
        if self.offline_mode:
            logger.debug(f"Offline mode: skipping lineage fetch for taxid {taxid}")
            return []

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

        except (requests.exceptions.RequestException, IndexError, AttributeError) as e:
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

    API documentation: https://api.gtdb.ecogenomic.org/docs
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

        # In offline mode, also check OfflineTaxonomyCache before giving up
        if self.offline_mode:
            offline_cache = get_offline_cache(offline_mode=True)
            offline_data = offline_cache.get_gtdb_taxonomy(name)
            if offline_data:
                logger.debug(f"Offline cache hit for GTDB: {name}")
                return GTDBResult.from_dict(offline_data) if isinstance(offline_data, dict) else None
            logger.debug(f"Offline mode: no cached GTDB data for {name}")
            return None

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


def get_ncbi_client(api_key: Optional[str] = None, offline_mode: bool = False) -> NCBIClient:
    """Get the NCBI client instance."""
    global _ncbi_client
    if _ncbi_client is None:
        _ncbi_client = NCBIClient(cache=get_taxonomy_cache(), api_key=api_key)
    # Update offline mode if changed
    if _ncbi_client.offline_mode != offline_mode:
        _ncbi_client.offline_mode = offline_mode
    return _ncbi_client


def get_gtdb_client(offline_mode: bool = False) -> GTDBClient:
    """Get the GTDB client instance."""
    global _gtdb_client
    if _gtdb_client is None:
        _gtdb_client = GTDBClient(cache=get_taxonomy_cache())
    # Update offline mode if changed
    if _gtdb_client.offline_mode != offline_mode:
        _gtdb_client.offline_mode = offline_mode
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
    offline_mode: bool = False,
) -> Dict[str, Any]:
    """
    Look up a species by name in both NCBI and GTDB.

    Args:
        name: Species name to search
        use_ncbi: Whether to query NCBI
        use_gtdb: Whether to query GTDB
        offline_mode: When True, query the cached clients only;
            no live HTTP requests are made.

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
        ncbi = get_ncbi_client(offline_mode=offline_mode)
        result["ncbi_result"] = ncbi.search_by_name(name)

    if use_gtdb:
        gtdb = get_gtdb_client(offline_mode=offline_mode)
        result["gtdb_result"] = gtdb.search_by_name(name)

    return result
