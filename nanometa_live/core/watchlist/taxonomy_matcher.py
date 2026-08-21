"""
Name matching across NCBI and GTDB spellings of the same organism.

Matching is by normalized species name only. Whether a taxid comparison is
meaningful is a property of the loaded database, answered by
``core.taxonomy.database_profile.DatabaseProfile``, and the callers resolve
it against an index before reaching this module.

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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from nanometa_live.core.watchlist.validation.name_normalizer import GTDB_RANK_PREFIXES

logger = logging.getLogger(__name__)


@dataclass
class EntryMatchIndex:
    """Precomputed lookup structures over a fixed list of watchlist entries.

    Built once per watchlist state by ``TaxonomyMatcher.build_entry_index``
    and probed per report row by ``match_row_indexed``, replacing the
    O(rows x entries) inner loop that recomputed name variants for every
    pair. Dict values are ``(position, entry)`` so ties resolve to the
    entry earliest in iteration order, matching the naive loop's strict-``>``
    first-wins behaviour.

    Only the alert-relevant tiers (score >= 0.7) are indexed: the 0.6 and
    0.3 tiers of ``match_organism`` sit below the 0.7 alert floor in both
    ``check_organisms`` paths, so a sub-0.7 winner and no winner are
    indistinguishable to every caller.
    """

    exact: Dict[str, Tuple[int, Any]] = field(default_factory=dict)
    alt: Dict[str, Tuple[int, Any]] = field(default_factory=dict)
    variants: Dict[str, Tuple[int, Any]] = field(default_factory=dict)
    genus_species: Dict[Tuple[str, str], Tuple[int, Any]] = field(
        default_factory=dict)
    # (normalized entry name, entry) in entry order, for the substring tier.
    substring_scan: List[Tuple[str, Any]] = field(default_factory=list)


class TaxonomyMatcher:
    """Name-based matching of a detected organism to a watchlist entry.

    Stateless, and deliberately so. It used to carry a taxonomy-type field
    whose only effect was an exact-taxid comparison -- work both callers
    already do, against a properly indexed dict, *before* reaching here.
    Removing it leaves the matcher doing the one thing it is actually good
    at: deciding whether two names refer to the same organism, across NCBI
    and GTDB spellings.

    Scores run from 1.0 (exact normalized name) down through alternative
    names, GTDB variants and genus-only agreement.

    Usage:
        score = TaxonomyMatcher().match_organism(detected, entry_name, ...)
    """

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

    def build_entry_index(self, entries: List[Any]) -> EntryMatchIndex:
        """Precompute the alert-relevant match tiers for a list of entries.

        Entries are objects with ``name`` and ``names_alt`` attributes
        (``WatchlistEntry``), in the iteration order the caller's loop would
        have used -- position decides ties.
        """
        index = EntryMatchIndex()
        for pos, entry in enumerate(entries):
            normalized = self.normalize_name(getattr(entry, "name", "") or "")
            if not normalized:
                continue
            index.exact.setdefault(normalized, (pos, entry))
            for alt_name in (getattr(entry, "names_alt", None) or []):
                alt_norm = self.normalize_name(alt_name)
                if alt_norm:
                    index.alt.setdefault(alt_norm, (pos, entry))
            for variant in self.get_name_variants(entry.name):
                index.variants.setdefault(variant, (pos, entry))
            parts = normalized.split()
            if len(parts) >= 2:
                index.genus_species.setdefault(
                    (parts[0], parts[1]), (pos, entry))
            index.substring_scan.append((normalized, entry))
        return index

    def match_row_indexed(
        self, detected_name: str, index: EntryMatchIndex
    ) -> Tuple[Optional[Any], float]:
        """Resolve one detected name against a prebuilt entry index.

        Returns ``(entry, score)`` for the best alert-relevant match
        (score >= 0.7) or ``(None, 0.0)``. Equivalent to running
        ``match_organism`` against every indexed entry and keeping the
        highest score, first entry winning ties -- proven by the
        equivalence tests in ``tests/test_watchlist_matching_equivalence``.

        Tiers are probed in descending score order. An entry that can
        score at a higher tier is always discoverable at that tier's dict,
        so a hit at tier t means no indexed entry scores above t.
        """
        detected_normalized = self.normalize_name(detected_name)
        if not detected_normalized:
            return None, 0.0

        hit = index.exact.get(detected_normalized)
        if hit is not None:
            return hit[1], 1.0

        hit = index.alt.get(detected_normalized)
        if hit is not None:
            return hit[1], 0.95

        candidates = [
            index.variants[v]
            for v in self.get_name_variants(detected_name)
            if v in index.variants
        ]
        if candidates:
            return min(candidates, key=lambda t: t[0])[1], 0.9

        parts = detected_normalized.split()
        if len(parts) >= 2:
            hit = index.genus_species.get((parts[0], parts[1]))
            if hit is not None:
                return hit[1], 0.85

        for entry_normalized, entry in index.substring_scan:
            if entry_normalized in detected_normalized:
                return entry, 0.7

        return None, 0.0

    def match_organism(
        self,
        detected: Dict[str, Any],
        entry_name: str,
        entry_alt_names: Optional[List[str]] = None,
        entry_taxid: Optional[int] = None,
    ) -> float:
        """
        Calculate match score between detected organism and watchlist entry.

        Names only. Taxid equality is resolved by the caller against an index
        before it gets here -- both callers build a database-taxid map and
        try the direct NCBI key first, so repeating either comparison inside
        this per-entry loop would be redundant work at O(entries) cost.

        Args:
            detected: Dict with 'taxid', 'name' keys from Kraken2 output
            entry_name: Watchlist entry primary name
            entry_alt_names: Alternative names for matching (e.g., GTDB variants)
            entry_taxid: Accepted for call-site compatibility; unused.

        Returns:
            Match score from 0.0 (no match) to 1.0 (exact match)
        """
        detected_name = detected.get("name", "")

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

        # Check for substring match (species name in detected name). Tried
        # BEFORE the same-genus fallback: a GTDB polyphyly-suffixed report
        # name ("Escherichia coli_D") shares the genus with the watchlist
        # binomial, and returning 0.3 there shadowed the 0.7 substring score
        # that clears the detection threshold -- a silent miss for exactly
        # the names GTDB databases produce.
        if entry_normalized in detected_normalized:
            return 0.7
        if detected_normalized in entry_normalized:
            return 0.6

        # Same genus, different species: the weakest signal, so it comes last.
        if (len(entry_parts) >= 2 and len(detected_parts) >= 2
                and entry_parts[0] == detected_parts[0]):
            return 0.3

        return 0.0


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
