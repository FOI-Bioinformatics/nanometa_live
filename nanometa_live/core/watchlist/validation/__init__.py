"""
Validation subsystem for Nanometa Live watchlist.

Provides name normalization, matching strategies, and confidence scoring
for validating watchlist entries against Kraken2 databases.
"""

from nanometa_live.core.watchlist.validation.name_normalizer import (
    NormalizedName,
    NameNormalizer,
    get_name_normalizer,
)

from nanometa_live.core.watchlist.validation.match_strategies import (
    MatchType,
    MatchResult,
    MatchStrategy,
    ExactTaxidStrategy,
    ExactNameStrategy,
    VariantMatchStrategy,
    FuzzyMatchStrategy,
    ParentTaxonStrategy,
    SubstringMatchStrategy,
    CompositeMatchStrategy,
    get_match_strategy,
)

from nanometa_live.core.watchlist.validation.confidence_scorer import (
    ValidationStatus,
    ConfidenceScore,
    ConfidenceScorer,
    get_confidence_scorer,
)

__all__ = [
    # Name normalization
    "NormalizedName",
    "NameNormalizer",
    "get_name_normalizer",
    # Match strategies
    "MatchType",
    "MatchResult",
    "MatchStrategy",
    "ExactTaxidStrategy",
    "ExactNameStrategy",
    "VariantMatchStrategy",
    "FuzzyMatchStrategy",
    "ParentTaxonStrategy",
    "SubstringMatchStrategy",
    "CompositeMatchStrategy",
    "get_match_strategy",
    # Confidence scoring
    "ValidationStatus",
    "ConfidenceScore",
    "ConfidenceScorer",
    "get_confidence_scorer",
]
