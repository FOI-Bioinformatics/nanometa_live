"""
Taxonomy Validator for Nanometa Live v2.0.

Validates species names and taxids against Kraken2 database taxonomy.
Supports NCBI and GTDB taxonomies via kraken2-inspect output files.
"""

import os
import logging
import subprocess
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TaxonomyValidator:
    """Validate species names against Kraken2 database taxonomy.

    Supports multiple taxonomy sources:
    1. Pre-generated inspect file (fastest, no kraken2 needed)
    2. Cached inspect.txt in database directory
    3. Live kraken2-inspect execution (requires kraken2)
    """

    def __init__(
        self,
        kraken_db_path: Optional[str] = None,
        inspect_file: Optional[str] = None
    ):
        """Initialize validator with database path or inspect file.

        Args:
            kraken_db_path: Path to Kraken2 database directory
            inspect_file: Path to pre-generated inspect file (preferred)
        """
        self.db_path = kraken_db_path
        self.inspect_file = inspect_file
        self._taxonomy_cache: Optional[Dict[str, List[Dict]]] = None
        self._taxid_cache: Optional[Dict[int, Dict]] = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        """Check if taxonomy data is loaded."""
        return self._loaded and self._taxonomy_cache is not None

    @property
    def species_count(self) -> int:
        """Return number of species in taxonomy cache."""
        if not self._taxonomy_cache:
            return 0
        return len(self._taxonomy_cache)

    def load_taxonomy(self) -> bool:
        """Load taxonomy from inspect file, names.dmp, or kraken2-inspect.

        Priority:
        1. Pre-generated inspect file (if provided)
        2. Cached inspect file at {db_path}/inspect.txt
        3. Taxonomy names.dmp file at {db_path}/taxonomy/names.dmp
        4. Run kraken2-inspect (requires kraken2 installed)

        Returns:
            True if taxonomy loaded successfully, False otherwise
        """
        # Check for pre-provided inspect file
        if self.inspect_file and os.path.exists(self.inspect_file):
            logger.info(f"Loading taxonomy from inspect file: {self.inspect_file}")
            return self._parse_inspect_file(self.inspect_file)

        # Check for cached inspect file alongside database
        if self.db_path:
            cached_file = os.path.join(self.db_path, "inspect.txt")
            if os.path.exists(cached_file):
                logger.info(f"Loading taxonomy from cached inspect: {cached_file}")
                return self._parse_inspect_file(cached_file)

            # Try names.dmp file from taxonomy directory (direct database lookup)
            names_dmp = os.path.join(self.db_path, "taxonomy", "names.dmp")
            if os.path.exists(names_dmp):
                logger.info(f"Loading taxonomy from names.dmp: {names_dmp}")
                if self._parse_names_dmp(names_dmp):
                    return True

            # Try running kraken2-inspect as fallback
            logger.info("No cached inspect or names.dmp found, attempting kraken2-inspect")
            return self._run_kraken2_inspect()

        logger.warning("No taxonomy source available")
        return False

    def _parse_inspect_file(self, filepath: str) -> bool:
        """Parse kraken2-inspect output file.

        Format: percent\\tcumul_reads\\treads\\trank\\ttaxid\\tname

        Args:
            filepath: Path to inspect file

        Returns:
            True if parsing successful
        """
        self._taxonomy_cache = {}
        self._taxid_cache = {}

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) >= 6:
                        try:
                            rank = parts[3].strip()
                            taxid = int(parts[4].strip())
                            # Name may have leading spaces from hierarchy indentation
                            name = parts[5].strip()

                            # Skip unclassified and root
                            if taxid <= 0:
                                continue

                            # Build name -> entries lookup (case-insensitive)
                            name_lower = name.lower()
                            if name_lower not in self._taxonomy_cache:
                                self._taxonomy_cache[name_lower] = []
                            self._taxonomy_cache[name_lower].append({
                                "taxid": taxid,
                                "rank": rank,
                                "name": name  # Original case preserved
                            })

                            # Build taxid -> info lookup
                            self._taxid_cache[taxid] = {
                                "name": name,
                                "rank": rank
                            }
                        except (ValueError, IndexError) as e:
                            # Skip malformed lines
                            continue

            self._loaded = len(self._taxonomy_cache) > 0
            logger.info(f"Loaded {len(self._taxonomy_cache)} unique names, "
                       f"{len(self._taxid_cache)} taxids from taxonomy")
            return self._loaded

        except Exception as e:
            logger.error(f"Error parsing inspect file: {e}")
            return False

    def _parse_names_dmp(self, filepath: str) -> bool:
        """Parse NCBI-format names.dmp file from Kraken2 database taxonomy.

        Format: taxid | name | unique name | name class |

        This provides direct access to species names and taxids without
        needing kraken2-inspect or a cached inspect file.

        Args:
            filepath: Path to names.dmp file

        Returns:
            True if parsing successful
        """
        self._taxonomy_cache = {}
        self._taxid_cache = {}

        try:
            entry_count = 0
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    # Format: taxid | name | unique name | name class |
                    # Fields are separated by \t|\t
                    parts = line.strip().split('\t|\t')
                    if len(parts) < 4:
                        continue

                    try:
                        taxid_str = parts[0].strip()
                        name = parts[1].strip()
                        name_class = parts[3].strip().rstrip('|').strip()

                        taxid = int(taxid_str)
                        if taxid <= 0 or not name:
                            continue

                        # Build name -> entries lookup (case-insensitive)
                        name_lower = name.lower()
                        if name_lower not in self._taxonomy_cache:
                            self._taxonomy_cache[name_lower] = []

                        # Only add if not already present for this taxid
                        existing_taxids = {e["taxid"] for e in self._taxonomy_cache[name_lower]}
                        if taxid not in existing_taxids:
                            # Determine rank indicator from name class
                            # names.dmp doesn't have rank, but we can infer species from name pattern
                            rank = "S" if name_class == "scientific name" and " " in name else "U"

                            self._taxonomy_cache[name_lower].append({
                                "taxid": taxid,
                                "rank": rank,
                                "name": name
                            })

                        # Build taxid -> info lookup (prefer scientific name)
                        if taxid not in self._taxid_cache or name_class == "scientific name":
                            self._taxid_cache[taxid] = {
                                "name": name,
                                "rank": rank if name_class == "scientific name" else "U"
                            }

                        entry_count += 1

                    except (ValueError, IndexError):
                        continue

            self._loaded = len(self._taxonomy_cache) > 0
            logger.info(f"Loaded {len(self._taxonomy_cache)} unique names, "
                       f"{len(self._taxid_cache)} taxids from names.dmp ({entry_count} entries)")
            return self._loaded

        except Exception as e:
            logger.error(f"Error parsing names.dmp file: {e}")
            return False

    def _run_kraken2_inspect(self) -> bool:
        """Run kraken2-inspect to generate taxonomy data.

        Returns:
            True if successful
        """
        if not self.db_path or not os.path.isdir(self.db_path):
            logger.warning("Invalid Kraken2 database path")
            return False

        try:
            # Run kraken2-inspect
            cmd = ["kraken2-inspect", "--db", self.db_path]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                logger.error(f"kraken2-inspect failed: {result.stderr}")
                return False

            # Parse output directly
            self._taxonomy_cache = {}
            self._taxid_cache = {}

            for line in result.stdout.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 6:
                    try:
                        rank = parts[3].strip()
                        taxid = int(parts[4].strip())
                        name = parts[5].strip()

                        if taxid <= 0:
                            continue

                        name_lower = name.lower()
                        if name_lower not in self._taxonomy_cache:
                            self._taxonomy_cache[name_lower] = []
                        self._taxonomy_cache[name_lower].append({
                            "taxid": taxid,
                            "rank": rank,
                            "name": name
                        })

                        self._taxid_cache[taxid] = {"name": name, "rank": rank}
                    except (ValueError, IndexError):
                        continue

            # Cache the inspect output for future use
            cache_file = os.path.join(self.db_path, "inspect.txt")
            try:
                with open(cache_file, 'w') as f:
                    f.write(result.stdout)
                logger.info(f"Cached inspect output to: {cache_file}")
            except Exception as e:
                logger.warning(f"Could not cache inspect output: {e}")

            self._loaded = len(self._taxonomy_cache) > 0
            return self._loaded

        except subprocess.TimeoutExpired:
            logger.error("kraken2-inspect timed out")
            return False
        except FileNotFoundError:
            logger.error("kraken2-inspect not found in PATH")
            return False
        except Exception as e:
            logger.error(f"Error running kraken2-inspect: {e}")
            return False

    def validate_species(self, query: str) -> Dict[str, Any]:
        """Validate species name or taxid against database.

        Args:
            query: Species name or taxid (as string)

        Returns:
            Dict with:
            - status: "valid", "fuzzy_match", "not_found", "not_loaded"
            - name: Matched species name (if found)
            - taxid: Matched taxonomy ID (if found)
            - rank: Taxonomic rank (if found)
            - suggestions: List of similar names (if fuzzy/not found)
        """
        # Ensure taxonomy is loaded
        if not self._taxonomy_cache:
            if not self.load_taxonomy():
                return {
                    "status": "not_loaded",
                    "name": None,
                    "taxid": None,
                    "rank": None,
                    "suggestions": [],
                    "message": "Taxonomy not loaded. Configure a Kraken2 database."
                }

        query = query.strip()
        if not query:
            return {
                "status": "not_found",
                "name": None,
                "taxid": None,
                "rank": None,
                "suggestions": []
            }

        # Try as taxid first (if numeric)
        if query.isdigit():
            taxid = int(query)
            if taxid in self._taxid_cache:
                entry = self._taxid_cache[taxid]
                return {
                    "status": "valid",
                    "name": entry["name"],
                    "taxid": taxid,
                    "rank": entry["rank"],
                    "suggestions": []
                }

        # Try exact name match (case-insensitive)
        query_lower = query.lower()
        if query_lower in self._taxonomy_cache:
            entries = self._taxonomy_cache[query_lower]
            # Prefer species-level match
            for entry in entries:
                if entry["rank"] == "S":
                    return {
                        "status": "valid",
                        "name": entry["name"],
                        "taxid": entry["taxid"],
                        "rank": entry["rank"],
                        "suggestions": []
                    }
            # Fallback to first match (could be genus, etc.)
            return {
                "status": "valid",
                "name": entries[0]["name"],
                "taxid": entries[0]["taxid"],
                "rank": entries[0]["rank"],
                "suggestions": []
            }

        # Fuzzy matching - search for names containing query
        suggestions = self._find_suggestions(query_lower)
        if suggestions:
            return {
                "status": "fuzzy_match",
                "name": None,
                "taxid": None,
                "rank": None,
                "suggestions": suggestions[:5]
            }

        return {
            "status": "not_found",
            "name": None,
            "taxid": None,
            "rank": None,
            "suggestions": []
        }

    def _find_suggestions(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Find species names containing the query string.

        Args:
            query: Search query (lowercase)
            limit: Maximum suggestions to return

        Returns:
            List of matching species dicts with name and taxid
        """
        if not self._taxonomy_cache:
            return []

        suggestions = []

        # Search for names containing query
        for name_lower, entries in self._taxonomy_cache.items():
            if query in name_lower:
                for entry in entries:
                    # Prefer species-level matches
                    if entry["rank"] == "S":
                        suggestions.append({
                            "name": entry["name"],
                            "taxid": entry["taxid"],
                            "rank": entry["rank"]
                        })
                        if len(suggestions) >= limit * 2:
                            break
            if len(suggestions) >= limit * 2:
                break

        # Sort by relevance (exact prefix match first, then alphabetically)
        def sort_key(s):
            name_lower = s["name"].lower()
            # Prefix matches rank higher
            if name_lower.startswith(query):
                return (0, name_lower)
            return (1, name_lower)

        suggestions.sort(key=sort_key)
        return suggestions[:limit]

    def get_by_taxid(self, taxid: int) -> Optional[Dict[str, Any]]:
        """Look up species by taxonomy ID.

        Args:
            taxid: Taxonomy ID to look up

        Returns:
            Dict with name and rank, or None if not found
        """
        if not self._taxid_cache:
            self.load_taxonomy()

        if self._taxid_cache and taxid in self._taxid_cache:
            return self._taxid_cache[taxid]
        return None

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for species matching query.

        Args:
            query: Search string (name or partial name)
            limit: Maximum results to return

        Returns:
            List of matching species dicts
        """
        if not self._taxonomy_cache:
            self.load_taxonomy()

        if not self._taxonomy_cache:
            return []

        return self._find_suggestions(query.lower().strip(), limit)


# Global validator instance (singleton pattern)
_validator_instance: Optional[TaxonomyValidator] = None
_validator_db_path: Optional[str] = None
_validator_inspect_file: Optional[str] = None


def get_taxonomy_validator(
    kraken_db: Optional[str] = None,
    inspect_file: Optional[str] = None
) -> TaxonomyValidator:
    """Get or create taxonomy validator instance.

    Uses singleton pattern - reuses existing validator if same database.

    Args:
        kraken_db: Path to Kraken2 database
        inspect_file: Path to pre-generated inspect file

    Returns:
        TaxonomyValidator instance
    """
    global _validator_instance, _validator_db_path, _validator_inspect_file

    # Reuse existing validator if same configuration
    if (_validator_instance is not None and
        _validator_db_path == kraken_db and
        _validator_inspect_file == inspect_file):
        return _validator_instance

    # Create new validator
    _validator_instance = TaxonomyValidator(
        kraken_db_path=kraken_db,
        inspect_file=inspect_file
    )
    _validator_db_path = kraken_db
    _validator_inspect_file = inspect_file

    return _validator_instance


def reset_taxonomy_validator():
    """Reset the global validator instance.

    Call this when database configuration changes.
    """
    global _validator_instance, _validator_db_path, _validator_inspect_file
    _validator_instance = None
    _validator_db_path = None
    _validator_inspect_file = None
