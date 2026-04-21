"""
Name Normalizer for Nanometa Live.

This module provides comprehensive name normalization for species names,
handling differences between NCBI and GTDB taxonomy naming conventions.

GTDB conventions:
- Rank prefixes: d__, p__, c__, o__, f__, g__, s__
- Underscores instead of spaces: Bacillus_anthracis
- Domain included in full lineage

NCBI conventions:
- Spaces in names: Bacillus anthracis
- No rank prefixes
- Various strain/subspecies notations
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# GTDB rank prefixes
GTDB_RANK_PREFIXES = {
    "d__": "domain",
    "p__": "phylum",
    "c__": "class",
    "o__": "order",
    "f__": "family",
    "g__": "genus",
    "s__": "species",
}

# Common abbreviations in species names
ABBREVIATIONS = {
    "sp.": "species",
    "spp.": "species",
    "subsp.": "subspecies",
    "var.": "variety",
    "str.": "strain",
    "cf.": "confer",
    "aff.": "affinis",
}

# Known taxonomic reclassifications (old name -> new name)
# GTDB and modern phylogenomics have reclassified several genera
KNOWN_RECLASSIFICATIONS = {
    # Clostridioides (formerly Clostridium)
    "clostridium difficile": ["clostridioides difficile"],
    "clostridium bifermentans": ["paraclostridium bifermentans"],
    # Cutibacterium (formerly Propionibacterium)
    "propionibacterium acnes": ["cutibacterium acnes"],
    "propionibacterium avidum": ["cutibacterium avidum"],
    "propionibacterium granulosum": ["cutibacterium granulosum"],
    # Enterobacter / Klebsiella
    "enterobacter aerogenes": ["klebsiella aerogenes"],
    # Bacillus cereus sensu lato
    "bacillus cereus group": ["bacillus cereus", "bacillus anthracis", "bacillus thuringiensis"],
    # Shigella is phylogenetically within E. coli (same species in GTDB)
    "shigella": ["escherichia coli"],
    "shigella flexneri": ["escherichia coli"],
    "shigella sonnei": ["escherichia coli"],
    "shigella dysenteriae": ["escherichia coli"],
    "shigella boydii": ["escherichia coli"],
    # Stenotrophomonas (formerly Pseudomonas / Xanthomonas)
    "pseudomonas maltophilia": ["stenotrophomonas maltophilia"],
    "xanthomonas maltophilia": ["stenotrophomonas maltophilia"],
    # Kytococcus (formerly Micrococcus)
    "micrococcus sedentarius": ["kytococcus sedentarius"],
    # Limosilactobacillus / Lacticaseibacillus / Ligilactobacillus / Latilactobacillus
    # (formerly Lactobacillus, split into multiple genera in 2020)
    "lactobacillus reuteri": ["limosilactobacillus reuteri"],
    "lactobacillus fermentum": ["limosilactobacillus fermentum"],
    "lactobacillus casei": ["lacticaseibacillus casei"],
    "lactobacillus paracasei": ["lacticaseibacillus paracasei"],
    "lactobacillus rhamnosus": ["lacticaseibacillus rhamnosus"],
    "lactobacillus salivarius": ["ligilactobacillus salivarius"],
    "lactobacillus sakei": ["latilactobacillus sakei"],
    # Reverse mappings (new name -> old name) for databases using older taxonomy
    "clostridioides difficile": ["clostridium difficile"],
    "paraclostridium bifermentans": ["clostridium bifermentans"],
    "cutibacterium acnes": ["propionibacterium acnes"],
    "stenotrophomonas maltophilia": ["pseudomonas maltophilia", "xanthomonas maltophilia"],
    "kytococcus sedentarius": ["micrococcus sedentarius"],
    "limosilactobacillus reuteri": ["lactobacillus reuteri"],
    "limosilactobacillus fermentum": ["lactobacillus fermentum"],
    "lacticaseibacillus casei": ["lactobacillus casei"],
    "lacticaseibacillus paracasei": ["lactobacillus paracasei"],
    "lacticaseibacillus rhamnosus": ["lactobacillus rhamnosus"],
    "ligilactobacillus salivarius": ["lactobacillus salivarius"],
    "latilactobacillus sakei": ["lactobacillus sakei"],
    # ICTV virus reclassifications
    "zaire ebolavirus": ["orthoebolavirus zairense"],
    "ebola virus": ["orthoebolavirus zairense"],
    "sudan ebolavirus": ["orthoebolavirus sudanense"],
    "marburg marburgvirus": ["orthomarburgvirus marburgense"],
    "marburg virus": ["orthomarburgvirus marburgense"],
    "variola virus": ["orthopoxvirus variola"],
    "smallpox virus": ["orthopoxvirus variola"],
    "monkeypox virus": ["orthopoxvirus monkeypox"],
    "mpox virus": ["orthopoxvirus monkeypox"],
    "lassa mammarenavirus": ["mammarenavirus lassaense"],
    "lassa virus": ["mammarenavirus lassaense"],
    # ICTV reverse mappings (new name -> old name)
    "orthoebolavirus zairense": ["zaire ebolavirus", "ebola virus"],
    "orthoebolavirus sudanense": ["sudan ebolavirus"],
    "orthomarburgvirus marburgense": ["marburg marburgvirus", "marburg virus"],
    "orthopoxvirus variola": ["variola virus", "smallpox virus"],
    "orthopoxvirus monkeypox": ["monkeypox virus", "mpox virus"],
    "mammarenavirus lassaense": ["lassa mammarenavirus", "lassa virus"],
}

# Genus-level reclassifications (for suggesting alternatives)
GENUS_RECLASSIFICATIONS = {
    "shigella": "escherichia",  # All Shigella species are in Escherichia in GTDB
    "propionibacterium": "cutibacterium",  # Most clinical species moved to Cutibacterium
    "lactobacillus": "limosilactobacillus",  # Split into multiple genera in 2020
}


@dataclass
class NormalizedName:
    """Result of name normalization."""
    original: str                    # Original input
    canonical: str                   # Lowercase, standardized spacing
    genus: Optional[str] = None      # Extracted genus
    species_epithet: Optional[str] = None  # Species epithet
    subspecies: Optional[str] = None # Subspecies if present
    strain: Optional[str] = None     # Strain identifier if present
    variants: List[str] = field(default_factory=list)  # All matching forms
    taxonomy_hints: List[str] = field(default_factory=list)  # Detected patterns

    def __post_init__(self):
        """Generate variants after initialization."""
        if not self.variants:
            self.variants = self._generate_variants()

    def _generate_variants(self) -> List[str]:
        """Generate name variants for matching."""
        variants = [self.canonical]

        # Species-only form (genus + species_epithet, no strain/serovar)
        # This is the most important variant for matching
        if self.genus and self.species_epithet:
            species_only = f"{self.genus.lower()} {self.species_epithet.lower()}"
            if species_only != self.canonical:
                variants.insert(1, species_only)  # High priority after canonical
            # Also add underscore form for species-only
            variants.append(f"{self.genus.lower()}_{self.species_epithet.lower()}")

        # GTDB-style with underscores
        underscore_form = self.canonical.replace(" ", "_")
        if underscore_form != self.canonical:
            variants.append(underscore_form)

        # GTDB prefixed form
        if self.genus and self.species_epithet:
            gtdb_species = f"s__{self.genus}_{self.species_epithet}"
            variants.append(gtdb_species.lower())

        # GTDB genus suffix variants (e.g., Bacillus -> Bacillus_A, Clostridium -> Clostridium_P)
        # GTDB uses alphabetic suffixes for taxonomic reorganizations
        if self.genus and self.species_epithet:
            # Generate all possible GTDB suffixes (A-Z)
            for letter in 'abcdefghijklmnopqrstuvwxyz':
                suffix = f"_{letter}"
                gtdb_genus = f"{self.genus.lower()}{suffix}"
                variants.append(f"{gtdb_genus} {self.species_epithet.lower()}")
                variants.append(f"{gtdb_genus}_{self.species_epithet.lower()}")
                # Also add GTDB species prefix form
                variants.append(f"s__{gtdb_genus}_{self.species_epithet.lower()}")

        # Genus-only form (LOWEST priority - only for fallback matching)
        if self.genus:
            variants.append(self.genus.lower())
            variants.append(f"g__{self.genus.lower()}")

        return list(dict.fromkeys(variants))  # Remove duplicates, preserve order


class NameNormalizer:
    """
    Normalize species names for cross-taxonomy matching.

    This class handles the conversion between NCBI and GTDB naming
    conventions, providing consistent name forms for matching.

    Usage:
        normalizer = NameNormalizer()
        result = normalizer.normalize("s__Bacillus_anthracis")
        print(result.canonical)  # "bacillus anthracis"
        print(result.variants)   # ["bacillus anthracis", "bacillus_anthracis", ...]
    """

    def __init__(self, cache_size: int = 10000):
        """Initialize the name normalizer with caching."""
        self._gtdb_pattern = re.compile(r'^([dgpcofgs])__(.+)$')
        # Match strain identifiers: "str. X", "strain X"
        self._strain_pattern = re.compile(r'\s+(str\.|strain)\s+\S+', re.IGNORECASE)
        # Match serovar/serotype patterns: "O157:H7", "O1:K1:H7", etc.
        self._serovar_pattern = re.compile(r'\s+[A-Z]\d+(?::[A-Z]?\d+)*(?:\s|$)', re.IGNORECASE)
        self._subspecies_pattern = re.compile(r'\s+subsp\.\s+(\S+)', re.IGNORECASE)
        # Cache for normalized names (dict-based with size limit)
        # Protected by _cache_lock for thread safety in concurrent Dash callbacks.
        self._cache: Dict[str, NormalizedName] = {}
        self._cache_lock = threading.Lock()
        self._cache_size = cache_size

    def normalize(self, name: str) -> NormalizedName:
        """
        Normalize a species name (cached).

        Args:
            name: Input species name (NCBI or GTDB format)

        Returns:
            NormalizedName with canonical form and variants
        """
        if not name or not isinstance(name, str):
            return NormalizedName(original="", canonical="")

        # Check cache first (thread-safe)
        with self._cache_lock:
            if name in self._cache:
                return self._cache[name]

        original = name.strip()
        taxonomy_hints = []

        # Step 1: Detect and strip GTDB prefix
        working_name, rank = self.strip_gtdb_prefix(original)
        if rank:
            taxonomy_hints.append("gtdb")
            taxonomy_hints.append(f"rank:{rank}")

        # Step 2: Replace underscores with spaces
        if "_" in working_name and " " not in working_name:
            working_name = working_name.replace("_", " ")
            if "gtdb" not in taxonomy_hints:
                taxonomy_hints.append("gtdb_style")

        # Step 3: Normalize whitespace and case
        working_name = " ".join(working_name.split()).lower()

        # Step 4: Parse binomial name components
        parsed = self.parse_binomial(working_name)

        # Step 5: Handle abbreviations
        working_name = self.expand_abbreviations(working_name)

        # Step 6: Remove strain and serovar identifiers for canonical form
        canonical = self._strain_pattern.sub("", working_name)
        canonical = self._serovar_pattern.sub("", canonical).strip()

        result = NormalizedName(
            original=original,
            canonical=canonical,
            genus=parsed.get("genus"),
            species_epithet=parsed.get("species_epithet"),
            subspecies=parsed.get("subspecies"),
            strain=parsed.get("strain"),
            taxonomy_hints=taxonomy_hints
        )

        # Cache the result (with size limit, thread-safe)
        with self._cache_lock:
            if len(self._cache) < self._cache_size:
                self._cache[name] = result

        return result

    def strip_gtdb_prefix(self, name: str) -> Tuple[str, Optional[str]]:
        """
        Remove GTDB rank prefix from a name.

        Args:
            name: Species name possibly with GTDB prefix

        Returns:
            Tuple of (name without prefix, rank or None)
        """
        match = self._gtdb_pattern.match(name)
        if match:
            prefix = match.group(1)
            stripped_name = match.group(2)
            rank = {
                "d": "domain", "p": "phylum", "c": "class",
                "o": "order", "f": "family", "g": "genus", "s": "species"
            }.get(prefix)
            return stripped_name, rank

        # Check for full prefix pattern (e.g., "s__")
        for prefix, rank in GTDB_RANK_PREFIXES.items():
            if name.lower().startswith(prefix):
                return name[len(prefix):], rank

        return name, None

    def parse_binomial(self, name: str) -> Dict[str, Optional[str]]:
        """
        Parse a species name into its components.

        Args:
            name: Normalized species name

        Returns:
            Dict with genus, species_epithet, subspecies, strain
        """
        result: Dict[str, Optional[str]] = {
            "genus": None,
            "species_epithet": None,
            "subspecies": None,
            "strain": None
        }

        if not name:
            return result

        # Handle strain patterns first
        strain_match = self._strain_pattern.search(name)
        if strain_match:
            result["strain"] = strain_match.group(0).strip()
            name = self._strain_pattern.sub("", name).strip()

        # Handle subspecies
        subsp_match = self._subspecies_pattern.search(name)
        if subsp_match:
            result["subspecies"] = subsp_match.group(1)
            name = self._subspecies_pattern.sub("", name).strip()

        # Split into words
        words = name.split()

        if len(words) >= 1:
            result["genus"] = words[0]

        if len(words) >= 2:
            # Second word is species epithet unless it's an abbreviation
            if words[1] not in ABBREVIATIONS:
                result["species_epithet"] = words[1]

        return result

    def expand_abbreviations(self, name: str) -> str:
        """
        Expand common abbreviations in species names.

        This is mainly for documentation; matching typically uses
        both abbreviated and expanded forms.
        """
        result = name
        for abbrev in ABBREVIATIONS:
            if abbrev in result.lower():
                # Keep the abbreviation, don't expand (it's part of the name)
                pass
        return result

    def get_name_variants(self, name: str) -> List[str]:
        """
        Get all name variants for matching.

        Args:
            name: Input species name

        Returns:
            List of name variants
        """
        normalized = self.normalize(name)
        return normalized.variants

    def get_reclassifications(self, name: str) -> List[str]:
        """
        Get known reclassifications for a species name.

        Args:
            name: Normalized species name

        Returns:
            List of alternative names due to reclassification
        """
        canonical = self.normalize(name).canonical
        return KNOWN_RECLASSIFICATIONS.get(canonical, [])

    def calculate_similarity(self, name1: str, name2: str) -> float:
        """
        Calculate similarity between two species names.

        Uses word-level Jaccard similarity with bonus for
        matching genus and species epithet.

        Args:
            name1: First species name
            name2: Second species name

        Returns:
            Similarity score from 0.0 to 1.0
        """
        norm1 = self.normalize(name1)
        norm2 = self.normalize(name2)

        # Exact match
        if norm1.canonical == norm2.canonical:
            return 1.0

        # Variant match
        for v1 in norm1.variants:
            if v1 in norm2.variants:
                return 0.95

        # Word-level Jaccard similarity
        words1 = set(norm1.canonical.split())
        words2 = set(norm2.canonical.split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2
        jaccard = len(intersection) / len(union)

        # Bonus for matching genus
        if norm1.genus and norm2.genus and norm1.genus == norm2.genus:
            jaccard = min(1.0, jaccard + 0.2)

        # Bonus for matching species epithet
        if norm1.species_epithet and norm2.species_epithet:
            if norm1.species_epithet == norm2.species_epithet:
                jaccard = min(1.0, jaccard + 0.2)

        return jaccard

    def is_gtdb_format(self, name: str) -> bool:
        """Check if a name is in GTDB format."""
        # Has GTDB prefix
        if self._gtdb_pattern.match(name):
            return True

        # Has underscores and no spaces (likely GTDB)
        if "_" in name and " " not in name:
            return True

        return False

    def is_ncbi_format(self, name: str) -> bool:
        """Check if a name is in NCBI format."""
        # Has spaces and no GTDB prefix
        if " " in name and not self._gtdb_pattern.match(name):
            return True

        return False


# Singleton instance -- protected by lock against concurrent initialization.
_normalizer: Optional[NameNormalizer] = None
_normalizer_lock = threading.Lock()


def get_name_normalizer() -> NameNormalizer:
    """Get the global NameNormalizer instance (thread-safe)."""
    global _normalizer
    if _normalizer is not None:
        return _normalizer
    with _normalizer_lock:
        if _normalizer is None:
            _normalizer = NameNormalizer()
        return _normalizer
