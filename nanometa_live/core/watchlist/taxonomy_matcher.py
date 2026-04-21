"""
Taxonomy Matcher for Nanometa Live.

This module provides multi-taxonomy support, handling both NCBI and GTDB
taxonomy systems. Primary matching is done by normalized species name,
with taxid as a secondary identifier for NCBI databases.

GTDB characteristics:
- Names contain underscores (e.g., "Bacillus_anthracis")
- Domain prefixes: "d__Bacteria", "d__Archaea"
- Rank prefixes: "g__", "s__", "f__", etc.

NCBI characteristics:
- Names use spaces (e.g., "Bacillus anthracis")
- No prefix patterns
- Numeric taxonomy IDs
"""

import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nanometa_live.core.watchlist.validation.name_normalizer import GTDB_RANK_PREFIXES

logger = logging.getLogger(__name__)


class TaxonomyType(Enum):
    """Taxonomy system type."""
    NCBI = "ncbi"
    GTDB = "gtdb"
    UNKNOWN = "unknown"
    MIXED = "mixed"  # Some databases combine both


class TaxonomyMatcher:
    """
    Multi-taxonomy matching system for pathogen detection.

    This class provides name normalization and matching across both
    NCBI and GTDB taxonomy systems. Primary matching is by normalized
    scientific name, with taxid fallback for NCBI.

    Usage:
        matcher = TaxonomyMatcher()

        # Auto-detect taxonomy from Kraken2 report
        taxonomy = matcher.detect_taxonomy_from_report(report_path)

        # Match organisms
        score = matcher.match_organism(detected, watchlist_entry)
    """

    def __init__(self, taxonomy_type: TaxonomyType = TaxonomyType.UNKNOWN):
        """
        Initialize the taxonomy matcher.

        Args:
            taxonomy_type: The taxonomy system to use. Use UNKNOWN for auto-detect.
        """
        self._taxonomy_type = taxonomy_type
        self._detected_from_report = False

    @property
    def taxonomy_type(self) -> TaxonomyType:
        """Get the current taxonomy type."""
        return self._taxonomy_type

    @taxonomy_type.setter
    def taxonomy_type(self, value: TaxonomyType) -> None:
        """Set the taxonomy type."""
        self._taxonomy_type = value

    def detect_taxonomy_from_report(self, report_path: str) -> TaxonomyType:
        """
        Detect taxonomy system from a Kraken2 report file.

        Analyzes the naming patterns in the report to determine whether
        the database uses NCBI or GTDB taxonomy.

        Args:
            report_path: Path to a Kraken2 report file

        Returns:
            Detected TaxonomyType
        """
        path = Path(report_path)
        if not path.exists():
            logger.warning(f"Report file not found: {report_path}")
            return TaxonomyType.UNKNOWN

        gtdb_indicators = 0
        ncbi_indicators = 0
        lines_checked = 0
        max_lines = 100  # Check first 100 lines for efficiency

        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if lines_checked >= max_lines:
                        break

                    parts = line.strip().split('\t')
                    if len(parts) < 6:
                        continue

                    # Column 5 (0-indexed) contains the taxonomic name
                    name = parts[5].strip() if len(parts) > 5 else ""

                    if not name:
                        continue

                    lines_checked += 1

                    # Check for GTDB indicators
                    if self._has_gtdb_prefix(name):
                        gtdb_indicators += 2
                    elif '_' in name and ' ' not in name:
                        # Underscores without spaces suggest GTDB
                        gtdb_indicators += 1

                    # Check for NCBI indicators
                    if ' ' in name and '_' not in name:
                        ncbi_indicators += 1

                    # Strong GTDB indicator: rank prefix pattern
                    if re.match(r'^[a-z]__', name):
                        gtdb_indicators += 3

        except Exception as e:
            logger.error(f"Error reading report file: {e}")
            return TaxonomyType.UNKNOWN

        # Determine taxonomy type
        if gtdb_indicators > ncbi_indicators * 2:
            detected = TaxonomyType.GTDB
        elif ncbi_indicators > gtdb_indicators * 2:
            detected = TaxonomyType.NCBI
        elif gtdb_indicators > 0 and ncbi_indicators > 0:
            detected = TaxonomyType.MIXED
        else:
            detected = TaxonomyType.UNKNOWN

        self._taxonomy_type = detected
        self._detected_from_report = True

        logger.info(f"Detected taxonomy type: {detected.value} "
                   f"(GTDB indicators: {gtdb_indicators}, NCBI indicators: {ncbi_indicators})")

        return detected

    def _has_gtdb_prefix(self, name: str) -> bool:
        """Check if name has a GTDB rank prefix."""
        for prefix in GTDB_RANK_PREFIXES:
            if name.startswith(prefix):
                return True
        return False

    def normalize_name(self, name: str) -> str:
        """
        Normalize a species name using the shared NameNormalizer.

        Handles both NCBI (spaces) and GTDB (underscores) formats,
        converting to a canonical lowercase form.

        Args:
            name: Original species name

        Returns:
            Normalized name for comparison
        """
        if not name:
            return ""

        from nanometa_live.core.watchlist.validation.name_normalizer import get_name_normalizer
        normalizer = get_name_normalizer()
        normalized = normalizer.normalize(name)
        return normalized.canonical

    def get_name_variants(self, name: str) -> List[str]:
        """
        Generate name variants for matching.

        Creates multiple forms of a name to match across taxonomies:
        - Original normalized
        - GTDB format (underscores)
        - NCBI format (spaces)
        - With and without rank prefix

        Args:
            name: Species name

        Returns:
            List of name variants
        """
        variants = set()

        # Normalize first
        normalized = self.normalize_name(name)
        if normalized:
            variants.add(normalized)

        # Add underscore version (GTDB style)
        gtdb_style = normalized.replace(' ', '_')
        if gtdb_style:
            variants.add(gtdb_style)

        # Add space version (NCBI style)
        ncbi_style = normalized.replace('_', ' ')
        if ncbi_style:
            variants.add(ncbi_style)

        # Add with species prefix for GTDB
        if normalized and not normalized.startswith('s__'):
            variants.add(f"s__{gtdb_style}")

        return list(variants)

    def match_organism(
        self,
        detected: Dict[str, Any],
        entry_name: str,
        entry_alt_names: Optional[List[str]] = None,
        entry_taxid: Optional[int] = None
    ) -> float:
        """
        Calculate match score between detected organism and watchlist entry.

        Args:
            detected: Dict with 'taxid', 'name' keys from Kraken2 output
            entry_name: Watchlist entry primary name
            entry_alt_names: Alternative names for matching (e.g., GTDB variants)
            entry_taxid: NCBI taxid of watchlist entry (for NCBI databases)

        Returns:
            Match score from 0.0 (no match) to 1.0 (exact match)
        """
        detected_name = detected.get("name", "")
        detected_taxid = detected.get("taxid")

        # Exact taxid match (only for NCBI)
        if (self._taxonomy_type == TaxonomyType.NCBI and
            entry_taxid and detected_taxid and
            int(entry_taxid) == int(detected_taxid)):
            return 1.0

        # Name-based matching
        detected_normalized = self.normalize_name(detected_name)
        entry_normalized = self.normalize_name(entry_name)

        # Exact name match
        if detected_normalized == entry_normalized:
            return 1.0

        # Check alternative names
        if entry_alt_names:
            for alt_name in entry_alt_names:
                if self.normalize_name(alt_name) == detected_normalized:
                    return 0.95

        # Check if entry variants match
        entry_variants = self.get_name_variants(entry_name)
        detected_variants = self.get_name_variants(detected_name)

        for ev in entry_variants:
            if ev in detected_variants:
                return 0.9

        # Partial name match (genus + species)
        entry_parts = entry_normalized.split()
        detected_parts = detected_normalized.split()

        if len(entry_parts) >= 2 and len(detected_parts) >= 2:
            # Genus + species match
            if (entry_parts[0] == detected_parts[0] and
                entry_parts[1] == detected_parts[1]):
                return 0.85
            # Same genus
            if entry_parts[0] == detected_parts[0]:
                return 0.3

        # Check for substring match (species name in detected name)
        if entry_normalized in detected_normalized:
            return 0.7
        if detected_normalized in entry_normalized:
            return 0.6

        return 0.0

    def find_match(
        self,
        detected: Dict[str, Any],
        watchlist_entries: List[Dict[str, Any]],
        threshold: float = 0.7
    ) -> Optional[Tuple[Dict[str, Any], float]]:
        """
        Find the best matching watchlist entry for a detected organism.

        Args:
            detected: Dict with 'taxid', 'name' from detection
            watchlist_entries: List of watchlist entry dicts
            threshold: Minimum score to consider a match

        Returns:
            Tuple of (matching entry, score) or None if no match
        """
        best_match = None
        best_score = 0.0

        for entry in watchlist_entries:
            score = self.match_organism(
                detected=detected,
                entry_name=entry.get("name", ""),
                entry_alt_names=entry.get("names_alt", []),
                entry_taxid=entry.get("taxid") or entry.get("taxid_ncbi")
            )

            if score > best_score:
                best_score = score
                best_match = entry

        if best_score >= threshold:
            return (best_match, best_score)

        return None

    def get_taxonomy_indicator(self) -> str:
        """
        Get a human-readable indicator for the current taxonomy.

        Returns:
            String like "NCBI" or "GTDB" for display
        """
        return {
            TaxonomyType.NCBI: "NCBI",
            TaxonomyType.GTDB: "GTDB",
            TaxonomyType.MIXED: "Mixed",
            TaxonomyType.UNKNOWN: "Auto",
        }.get(self._taxonomy_type, "Unknown")


# Module-level singleton
_taxonomy_matcher: Optional[TaxonomyMatcher] = None


def get_taxonomy_matcher() -> TaxonomyMatcher:
    """Get the global TaxonomyMatcher instance."""
    global _taxonomy_matcher
    if _taxonomy_matcher is None:
        _taxonomy_matcher = TaxonomyMatcher()
    return _taxonomy_matcher


def reset_taxonomy_matcher() -> None:
    """Reset the global TaxonomyMatcher instance."""
    global _taxonomy_matcher
    _taxonomy_matcher = None
