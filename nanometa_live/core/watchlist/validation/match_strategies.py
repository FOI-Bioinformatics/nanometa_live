"""
Matching Strategies for Nanometa Live.

This module implements multiple matching algorithms for finding
taxonomy entries in Kraken2 databases. Strategies are tried in
priority order to find the best match.

Strategies (in priority order):
1. Exact taxid match - Direct NCBI taxid lookup
2. Exact name match - After normalization
3. Variant match - GTDB naming variants
4. Fuzzy match - Edit distance for typos
5. Parent taxon match - Genus-level fallback
6. Substring match - For strain matching
"""

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from nanometa_live.core.taxonomy.taxid_mapping import (
    DatabaseTaxonomyIndex,
    DatabaseTaxonomyNode,
)
from nanometa_live.core.watchlist.validation.name_normalizer import (
    GENUS_RECLASSIFICATIONS,
    KNOWN_RECLASSIFICATIONS,
    NormalizedName,
    get_name_normalizer,
)

logger = logging.getLogger(__name__)


class MatchType(Enum):
    """Type of match achieved."""
    EXACT_TAXID = "exact_taxid"       # Direct taxid match (NCBI databases)
    EXACT_NAME = "exact_name"          # Exact normalized name match
    VARIANT = "variant"                # Match via name variant
    RECLASSIFIED = "reclassified"      # Match via known taxonomic reclassification
    FUZZY = "fuzzy"                    # Edit distance match
    PARENT_TAXON = "parent_taxon"      # Genus-level match
    SUBSTRING = "substring"            # One contains the other
    NO_MATCH = "no_match"


@dataclass
class MatchResult:
    """Result from a matching strategy."""
    match_type: MatchType
    matched_node: Optional[DatabaseTaxonomyNode]
    score: float                       # 0.0-1.0
    details: Dict[str, Any]            # Strategy-specific details

    @property
    def matched_name(self) -> Optional[str]:
        """Get the matched name."""
        return self.matched_node.name if self.matched_node else None

    @property
    def matched_taxid(self) -> Optional[int]:
        """Get the matched taxid."""
        return self.matched_node.taxid if self.matched_node else None

    @property
    def matched_rank(self) -> Optional[str]:
        """Get the matched rank."""
        return self.matched_node.rank if self.matched_node else None


class MatchStrategy(ABC):
    """Base class for matching strategies."""

    @abstractmethod
    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """
        Attempt to match query against database index.

        Args:
            query: Normalized query name
            query_taxid: Optional NCBI taxid for direct lookup
            index: Database taxonomy index

        Returns:
            MatchResult or None if no match
        """
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """Strategy priority (lower = try first)."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging."""
        pass


class ExactTaxidStrategy(MatchStrategy):
    """Match by exact NCBI taxid lookup."""

    priority = 1
    name = "exact_taxid"

    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """Try exact taxid match."""
        if not query_taxid:
            return None

        node = index.get_by_taxid(query_taxid)
        if node:
            return MatchResult(
                match_type=MatchType.EXACT_TAXID,
                matched_node=node,
                score=1.0,
                details={"method": "taxid_lookup", "taxid": query_taxid}
            )

        return None


class ExactNameStrategy(MatchStrategy):
    """Match by exact normalized name."""

    priority = 2
    name = "exact_name"

    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """Try exact name match after normalization."""
        # Track if query is for a species (has species epithet)
        query_is_species = bool(query.species_epithet)

        # Look up by normalized name
        taxids = index.by_name.get(query.canonical, [])

        # Prefer species-rank matches
        for taxid in taxids:
            node = index.by_taxid.get(taxid)
            if node and node.rank == "S":
                return MatchResult(
                    match_type=MatchType.EXACT_NAME,
                    matched_node=node,
                    score=1.0,
                    details={"method": "exact_name", "query": query.canonical}
                )

        # Accept any rank ONLY if query is NOT looking for a species
        # This prevents genus-level matches when searching for species
        if taxids and not query_is_species:
            node = index.by_taxid.get(taxids[0])
            if node:
                return MatchResult(
                    match_type=MatchType.EXACT_NAME,
                    matched_node=node,
                    score=0.95,  # Slightly lower for non-species
                    details={"method": "exact_name_any_rank", "query": query.canonical}
                )

        return None


class VariantMatchStrategy(MatchStrategy):
    """Match using generated name variants (GTDB style)."""

    priority = 3
    name = "variant"

    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """Try matching via name variants."""
        # Track if query is for a species (has species epithet)
        query_is_species = bool(query.species_epithet)

        for variant in query.variants:
            # Skip canonical (already tried in ExactNameStrategy)
            if variant == query.canonical:
                continue

            # Skip genus-only variants if we're looking for a species
            # This prevents premature genus-level matches
            if query_is_species and variant == query.genus.lower() if query.genus else False:
                continue
            if query_is_species and variant.startswith("g__"):
                continue

            # Try normalized name index
            taxids = index.by_name.get(variant, [])
            if not taxids:
                # Try GTDB-style index
                taxids = index.by_name_gtdb.get(variant, [])

            # Prefer species-rank matches
            for taxid in taxids:
                node = index.by_taxid.get(taxid)
                if node and node.rank == "S":
                    return MatchResult(
                        match_type=MatchType.VARIANT,
                        matched_node=node,
                        score=0.95,
                        details={"method": "variant_match", "variant": variant}
                    )

            # Accept non-species rank ONLY if query is NOT looking for a species
            if taxids and not query_is_species:
                node = index.by_taxid.get(taxids[0])
                if node:
                    return MatchResult(
                        match_type=MatchType.VARIANT,
                        matched_node=node,
                        score=0.90,
                        details={"method": "variant_match_any_rank", "variant": variant}
                    )

        return None


class ReclassificationStrategy(MatchStrategy):
    """
    Match using known taxonomic reclassifications.

    Some genera have been reclassified in GTDB (e.g., Shigella -> Escherichia).
    This strategy checks if the query species has a known reclassification
    and tries to match the reclassified name.
    """

    priority = 35  # After variant (30), before fuzzy (40)
    name = "reclassification"

    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """Try matching via known reclassifications."""
        normalizer = get_name_normalizer()

        # Check species-level reclassifications first
        canonical = query.canonical
        if canonical in KNOWN_RECLASSIFICATIONS:
            reclassified_names = KNOWN_RECLASSIFICATIONS[canonical]
            for new_name in reclassified_names:
                # Try to find the reclassified species
                new_normalized = normalizer.normalize(new_name)
                for variant in new_normalized.variants:
                    taxids = index.by_name.get(variant, [])
                    if taxids:
                        node = index.by_taxid.get(taxids[0])
                        if node:
                            logger.debug(
                                f"Reclassification match: {canonical} -> {new_name} "
                                f"(now: {node.name})"
                            )
                            return MatchResult(
                                match_type=MatchType.RECLASSIFIED,
                                matched_node=node,
                                score=0.90,  # High score since it's a known reclassification
                                details={
                                    "method": "reclassification",
                                    "original_name": query.original,
                                    "reclassified_to": new_name,
                                    "reason": f"{query.original} reclassified to {node.name}"
                                }
                            )

        # Check genus-level reclassifications
        if query.genus and query.genus.lower() in GENUS_RECLASSIFICATIONS:
            new_genus = GENUS_RECLASSIFICATIONS[query.genus.lower()]
            # Try to find any species in the new genus
            # For Shigella -> Escherichia, we suggest E. coli specifically
            if query.species_epithet:
                # Try the reclassified genus with same species epithet
                new_name = f"{new_genus} {query.species_epithet}"
                new_normalized = normalizer.normalize(new_name)
                for variant in new_normalized.variants:
                    taxids = index.by_name.get(variant, [])
                    if taxids:
                        node = index.by_taxid.get(taxids[0])
                        if node:
                            return MatchResult(
                                match_type=MatchType.RECLASSIFIED,
                                matched_node=node,
                                score=0.85,
                                details={
                                    "method": "genus_reclassification",
                                    "original_name": query.original,
                                    "reclassified_to": new_name,
                                    "reason": f"Genus {query.genus} reclassified to {new_genus}"
                                }
                            )

        return None


class FuzzyMatchStrategy(MatchStrategy):
    """Fuzzy matching using edit distance."""

    priority = 40  # Updated from 4 to 40 for consistency
    name = "fuzzy"

    def __init__(self, threshold: float = 0.85):
        """
        Initialize with similarity threshold.

        Args:
            threshold: Minimum similarity score (0.0-1.0) to accept
        """
        self.threshold = threshold

    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """Try fuzzy matching using prefix-based candidate filtering."""
        best_match: Optional[DatabaseTaxonomyNode] = None
        best_score = 0.0
        best_name = ""

        # Use prefix-based search instead of scanning ALL species
        # This is critical for performance with large databases
        genus = query.genus.lower() if query.genus else ""
        canonical = query.canonical.lower()

        candidates = set()

        # Get candidates by genus prefix
        if genus and len(genus) >= 2:
            for node in index.search_by_prefix(genus, limit=500):
                candidates.add(node.taxid)

        # Get candidates by full name prefix
        if len(canonical) >= 2:
            for node in index.search_by_prefix(canonical[:2], limit=500):
                candidates.add(node.taxid)

        # Score only candidates, not all species
        for taxid in candidates:
            node = index.get_by_taxid(taxid)
            if not node or node.rank != "S":
                continue

            similarity = self._calculate_similarity(
                query.canonical,
                node.name_normalized
            )

            if similarity > best_score and similarity >= self.threshold:
                best_score = similarity
                best_match = node
                best_name = node.name_normalized

                # Early termination on excellent match
                if best_score >= 0.95:
                    break

        if best_match:
            return MatchResult(
                match_type=MatchType.FUZZY,
                matched_node=best_match,
                score=best_score,
                details={
                    "method": "fuzzy_match",
                    "similarity": best_score,
                    "matched_name": best_name
                }
            )

        return None

    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using SequenceMatcher."""
        if not s1 or not s2:
            return 0.0
        return SequenceMatcher(None, s1, s2).ratio()


class ParentTaxonStrategy(MatchStrategy):
    """Fall back to genus-level matching."""

    priority = 5
    name = "parent_taxon"

    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """Try genus-level match."""
        if not query.genus:
            return None

        genus_normalized = query.genus.lower()

        # Look for genus match - O(1) dict lookup instead of O(n) iteration
        taxids = index.by_name.get(genus_normalized, [])
        for taxid in taxids:
            node = index.by_taxid.get(taxid)
            if node and node.rank == "G":
                return MatchResult(
                    match_type=MatchType.PARENT_TAXON,
                    matched_node=node,
                    score=0.5,  # Lower score for genus-only
                    details={
                        "method": "genus_match",
                        "genus": query.genus
                    }
                )

        # Try GTDB-style genus
        gtdb_genus = f"g__{genus_normalized}"
        taxids = index.by_name_gtdb.get(gtdb_genus, [])
        for taxid in taxids:
            node = index.by_taxid.get(taxid)
            if node and node.rank == "G":
                return MatchResult(
                    match_type=MatchType.PARENT_TAXON,
                    matched_node=node,
                    score=0.5,
                    details={"method": "gtdb_genus_match", "genus": query.genus}
                )

        return None


class SubstringMatchStrategy(MatchStrategy):
    """Match via substring containment (for strain matching)."""

    priority = 6
    name = "substring"

    def __init__(self, min_overlap: float = 0.7):
        """
        Initialize with minimum overlap ratio.

        Args:
            min_overlap: Minimum fraction of query that must match
        """
        self.min_overlap = min_overlap

    def match(
        self,
        query: NormalizedName,
        query_taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> Optional[MatchResult]:
        """Try substring matching using prefix-based candidate filtering."""
        query_words = set(query.canonical.split())

        best_match: Optional[DatabaseTaxonomyNode] = None
        best_score = 0.0
        best_name = ""

        # Use prefix-based search instead of scanning ALL species
        genus = query.genus.lower() if query.genus else ""
        canonical = query.canonical.lower()

        candidates = set()

        # Get candidates by genus prefix
        if genus and len(genus) >= 2:
            for node in index.search_by_prefix(genus, limit=500):
                candidates.add(node.taxid)

        # Get candidates by full name prefix
        if len(canonical) >= 2:
            for node in index.search_by_prefix(canonical[:2], limit=500):
                candidates.add(node.taxid)

        # Score only candidates, not all species
        for taxid in candidates:
            node = index.get_by_taxid(taxid)
            if not node or node.rank != "S":
                continue

            target_words = set(node.name_normalized.split())

            # Check if query is substring of target
            if query.canonical in node.name_normalized:
                overlap = len(query.canonical) / len(node.name_normalized)
                if overlap >= self.min_overlap:
                    score = 0.7 + (overlap * 0.2)  # 0.7-0.9 range
                    if score > best_score:
                        best_score = score
                        best_match = node
                        best_name = node.name_normalized

            # Check word-level overlap
            else:
                if query_words and target_words:
                    intersection = query_words & target_words
                    overlap = len(intersection) / len(query_words)

                    if overlap >= self.min_overlap:
                        score = 0.6 + (overlap * 0.2)  # 0.6-0.8 range
                        if score > best_score:
                            best_score = score
                            best_match = node
                            best_name = node.name_normalized

        if best_match:
            return MatchResult(
                match_type=MatchType.SUBSTRING,
                matched_node=best_match,
                score=best_score,
                details={
                    "method": "substring_match",
                    "matched_name": best_name
                }
            )

        return None


class CompositeMatchStrategy:
    """
    Try multiple strategies in priority order.

    This is the main entry point for matching. It tries each strategy
    in order and returns the first successful match.
    """

    def __init__(
        self,
        strategies: Optional[List[MatchStrategy]] = None,
        fuzzy_threshold: float = 0.85
    ):
        """
        Initialize with strategies.

        Args:
            strategies: List of strategies (default: all strategies)
            fuzzy_threshold: Threshold for fuzzy matching
        """
        if strategies is None:
            strategies = [
                ExactTaxidStrategy(),
                ExactNameStrategy(),
                VariantMatchStrategy(),
                ReclassificationStrategy(),
                FuzzyMatchStrategy(threshold=fuzzy_threshold),
                ParentTaxonStrategy(),
                SubstringMatchStrategy(),
            ]

        self.strategies = sorted(strategies, key=lambda s: s.priority)
        self._normalizer = get_name_normalizer()

    def match(
        self,
        name: str,
        taxid: Optional[int],
        index: DatabaseTaxonomyIndex
    ) -> MatchResult:
        """
        Try each strategy until a match is found.

        Args:
            name: Species name to match
            taxid: Optional NCBI taxid
            index: Database taxonomy index

        Returns:
            MatchResult (may be NO_MATCH if nothing found)
        """
        from nanometa_live.core.taxonomy.taxid_mapping import DatabaseTaxonomyType

        # Normalize the query
        normalized = self._normalizer.normalize(name)

        # For custom databases, skip taxid-based matching since taxids are incompatible
        # Custom databases (e.g., GTDB-based) use arbitrary sequential taxid schemes
        skip_taxid_match = index.database_type == DatabaseTaxonomyType.CUSTOM

        # Try each strategy
        for strategy in self.strategies:
            # Skip ExactTaxidStrategy for custom databases
            if skip_taxid_match and isinstance(strategy, ExactTaxidStrategy):
                logger.debug(f"Skipping taxid match for custom database")
                continue

            try:
                result = strategy.match(normalized, taxid, index)
                if result:
                    logger.debug(
                        f"Match found via {strategy.name}: "
                        f"{name} -> {result.matched_name} (score={result.score:.2f})"
                    )
                    return result
            except Exception as e:
                logger.warning(f"Strategy {strategy.name} failed: {e}")
                continue

        # No match found
        return MatchResult(
            match_type=MatchType.NO_MATCH,
            matched_node=None,
            score=0.0,
            details={"method": "no_match", "query": name}
        )

    def find_alternatives(
        self,
        name: str,
        index: DatabaseTaxonomyIndex,
        limit: int = 5
    ) -> List[Tuple[DatabaseTaxonomyNode, float]]:
        """
        Find alternative matches for manual review.

        Uses prefix-based filtering for performance (avoids O(n) full scan).

        Prioritizes:
        1. Same-genus species (highest relevance)
        2. Species from reclassified genus (e.g., Shigella -> Escherichia)
        3. Fuzzy string matches (fallback)

        Args:
            name: Species name to match
            index: Database taxonomy index
            limit: Maximum number of alternatives

        Returns:
            List of (node, score) tuples sorted by relevance
        """
        normalized = self._normalizer.normalize(name)
        genus = normalized.genus.lower() if normalized.genus else None

        # Track alternatives with priority tiers
        same_genus: List[Tuple[DatabaseTaxonomyNode, float]] = []
        reclassified_genus: List[Tuple[DatabaseTaxonomyNode, float]] = []
        fuzzy_matches: List[Tuple[DatabaseTaxonomyNode, float]] = []

        # Check for genus reclassification (e.g., Shigella -> Escherichia)
        reclassified_genus_name = None
        if genus and genus in GENUS_RECLASSIFICATIONS:
            reclassified_genus_name = GENUS_RECLASSIFICATIONS[genus].lower()

        # Use prefix-based search instead of scanning ALL species
        # This is the key optimization - O(candidates) instead of O(all_species)
        candidates = set()

        # Get candidates matching genus prefix
        if genus and len(genus) >= 2:
            genus_candidates = index.search_by_prefix(genus[:2], limit=500)
            for node in genus_candidates:
                candidates.add(node.taxid)

        # Get candidates matching reclassified genus prefix
        if reclassified_genus_name and len(reclassified_genus_name) >= 2:
            reclassified_candidates = index.search_by_prefix(reclassified_genus_name[:2], limit=500)
            for node in reclassified_candidates:
                candidates.add(node.taxid)

        # Get candidates matching species epithet prefix (for fuzzy matches)
        canonical_lower = normalized.canonical.lower()
        if len(canonical_lower) >= 2:
            name_candidates = index.search_by_prefix(canonical_lower[:2], limit=300)
            for node in name_candidates:
                candidates.add(node.taxid)

        # Process only the candidates (not all species)
        for taxid in candidates:
            node = index.get_by_taxid(taxid)
            if not node or node.rank != "S":  # Only species level
                continue

            node_name_lower = node.name_normalized.lower()
            node_genus = node_name_lower.split()[0] if node_name_lower else ""

            # Priority 1: Same genus (boost score significantly)
            if genus and node_genus == genus:
                # Calculate similarity within genus
                similarity = SequenceMatcher(
                    None, normalized.canonical, node.name_normalized
                ).ratio()
                # Boost score for same genus (ensure it ranks higher)
                boosted_score = min(1.0, similarity + 0.3)
                same_genus.append((node, boosted_score))
                continue

            # Priority 2: Reclassified genus
            if reclassified_genus_name and node_genus == reclassified_genus_name:
                similarity = SequenceMatcher(
                    None, normalized.canonical, node.name_normalized
                ).ratio()
                # Moderate boost for reclassified genus
                boosted_score = min(1.0, similarity + 0.2)
                reclassified_genus.append((node, boosted_score))
                continue

            # Priority 3: Fuzzy matches
            similarity = SequenceMatcher(
                None, normalized.canonical, node.name_normalized
            ).ratio()
            if similarity >= 0.5:
                fuzzy_matches.append((node, similarity))

            # Early termination: if we have enough high-quality matches, stop
            if len(same_genus) >= limit * 2 and len(fuzzy_matches) >= limit:
                break

        # Sort each tier by score
        same_genus.sort(key=lambda x: x[1], reverse=True)
        reclassified_genus.sort(key=lambda x: x[1], reverse=True)
        fuzzy_matches.sort(key=lambda x: x[1], reverse=True)

        # Combine: same genus first, then reclassified, then fuzzy
        alternatives = same_genus + reclassified_genus + fuzzy_matches

        # Remove duplicates while preserving order
        seen = set()
        unique_alternatives = []
        for node, score in alternatives:
            if node.taxid not in seen:
                seen.add(node.taxid)
                unique_alternatives.append((node, score))

        return unique_alternatives[:limit]


# Default strategy instance -- protected by lock against concurrent initialization.
_default_strategy: Optional[CompositeMatchStrategy] = None
_default_strategy_lock = threading.Lock()


def get_match_strategy(fuzzy_threshold: float = 0.85) -> CompositeMatchStrategy:
    """Get the default match strategy (thread-safe)."""
    global _default_strategy
    if _default_strategy is not None:
        return _default_strategy
    with _default_strategy_lock:
        if _default_strategy is None:
            _default_strategy = CompositeMatchStrategy(fuzzy_threshold=fuzzy_threshold)
        return _default_strategy
