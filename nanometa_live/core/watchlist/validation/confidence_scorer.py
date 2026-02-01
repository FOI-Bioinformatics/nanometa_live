"""
Confidence Scorer for Nanometa Live.

This module calculates confidence scores for taxonomy matches and
determines whether matches should be auto-accepted, require review,
or be flagged as unmapped.

Scoring is based on:
- Match type (exact, fuzzy, parent taxon, etc.)
- Name similarity
- Rank agreement
- Taxid verification (for NCBI databases)
- Number of alternative matches
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from nanometa_live.core.watchlist.validation.match_strategies import (
    MatchResult,
    MatchType,
)

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    """Status of a validation attempt."""
    EXACT_MATCH = "exact_match"           # High confidence, auto-accept
    HIGH_CONFIDENCE = "high_confidence"   # Good match, likely correct
    NEEDS_REVIEW = "needs_review"         # Ambiguous or moderate match
    LOW_CONFIDENCE = "low_confidence"     # Poor match, likely wrong
    NOT_FOUND = "not_found"               # No match at all
    AMBIGUOUS = "ambiguous"               # Multiple equally good matches


@dataclass
class ConfidenceScore:
    """Detailed confidence score for a match."""
    # Component scores
    base_score: float                     # From match strategy (0-100)
    name_similarity: float                # String similarity component
    rank_match: bool                      # Does rank match expected?
    has_taxid_match: bool                 # Direct taxid match (NCBI only)
    alternative_matches: int              # Number of other candidates

    # Final calculation
    final_score: float                    # Weighted combination (0-100)
    status: ValidationStatus              # Derived status
    confidence_factors: List[str] = field(default_factory=list)

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "base_score": self.base_score,
            "name_similarity": self.name_similarity,
            "rank_match": self.rank_match,
            "has_taxid_match": self.has_taxid_match,
            "alternative_matches": self.alternative_matches,
            "final_score": self.final_score,
            "status": self.status.value,
            "confidence_factors": self.confidence_factors
        }


class ConfidenceScorer:
    """
    Calculate validation confidence scores.

    Uses configurable thresholds and weights to determine match quality
    and assign validation status.

    Usage:
        scorer = ConfidenceScorer()
        score = scorer.calculate_score(match_result, alternatives_count=2)
        if score.status == ValidationStatus.NEEDS_REVIEW:
            # Flag for manual review
    """

    # Default thresholds (0-100 scale)
    EXACT_THRESHOLD = 95.0
    HIGH_CONFIDENCE_THRESHOLD = 85.0
    REVIEW_THRESHOLD = 70.0
    LOW_CONFIDENCE_THRESHOLD = 50.0

    # Score weights
    WEIGHTS = {
        "match_type": 0.50,       # Strategy match type
        "name_similarity": 0.25,  # String similarity
        "rank_agreement": 0.10,   # Rank matches expected
        "taxid_verified": 0.15,   # NCBI taxid confirmed
    }

    # Base scores by match type
    MATCH_TYPE_SCORES = {
        MatchType.EXACT_TAXID: 100.0,
        MatchType.EXACT_NAME: 100.0,
        MatchType.VARIANT: 95.0,
        MatchType.RECLASSIFIED: 90.0,  # Known taxonomic reclassification
        MatchType.FUZZY: 75.0,
        MatchType.PARENT_TAXON: 50.0,
        MatchType.SUBSTRING: 70.0,
        MatchType.NO_MATCH: 0.0,
    }

    def __init__(
        self,
        exact_threshold: Optional[float] = None,
        high_confidence_threshold: Optional[float] = None,
        review_threshold: Optional[float] = None,
        low_confidence_threshold: Optional[float] = None
    ):
        """
        Initialize with optional custom thresholds.

        Args:
            exact_threshold: Score >= this is EXACT_MATCH
            high_confidence_threshold: Score >= this is HIGH_CONFIDENCE
            review_threshold: Score >= this is NEEDS_REVIEW
            low_confidence_threshold: Score >= this is LOW_CONFIDENCE
        """
        self.exact_threshold = exact_threshold or self.EXACT_THRESHOLD
        self.high_confidence_threshold = (
            high_confidence_threshold or self.HIGH_CONFIDENCE_THRESHOLD
        )
        self.review_threshold = review_threshold or self.REVIEW_THRESHOLD
        self.low_confidence_threshold = (
            low_confidence_threshold or self.LOW_CONFIDENCE_THRESHOLD
        )

    def calculate_score(
        self,
        match_result: MatchResult,
        query_taxid: Optional[int] = None,
        expected_rank: str = "species",
        alternative_count: int = 0,
        is_custom_database: bool = False
    ) -> ConfidenceScore:
        """
        Calculate comprehensive confidence score.

        Args:
            match_result: Result from matching strategy
            query_taxid: Original NCBI taxid (if known)
            expected_rank: Expected taxonomic rank
            alternative_count: Number of alternative matches found
            is_custom_database: True if database uses custom taxids (not NCBI)

        Returns:
            ConfidenceScore with detailed breakdown
        """
        factors: List[str] = []

        # 1. Base score from match type
        base_score = self.MATCH_TYPE_SCORES.get(
            match_result.match_type,
            0.0
        )
        factors.append(f"Match type: {match_result.match_type.value} ({base_score:.0f})")

        # 2. Name similarity (from match result score)
        name_similarity = match_result.score * 100
        if match_result.match_type == MatchType.FUZZY:
            factors.append(f"Fuzzy match: {name_similarity:.1f}% similar")

        # 3. Rank agreement
        rank_match = False
        expected_code = self._rank_to_code(expected_rank)
        if match_result.matched_rank:
            rank_match = match_result.matched_rank == expected_code
            if rank_match:
                factors.append("Rank matches expected")
            else:
                factors.append(
                    f"Rank mismatch: expected {expected_rank}, "
                    f"got {match_result.matched_rank}"
                )

        # 4. Taxid verification (not applicable for custom databases)
        has_taxid_match = False
        if not is_custom_database and query_taxid and match_result.matched_taxid:
            has_taxid_match = (query_taxid == match_result.matched_taxid)
            if has_taxid_match:
                factors.append("NCBI taxid verified")

        # 5. Calculate weighted final score
        # For custom databases, redistribute the taxid weight to other factors
        if is_custom_database:
            # Redistribute weights: taxid weight goes to match_type and name_similarity
            weights = {
                "match_type": 0.60,       # 50% + 7.5%
                "name_similarity": 0.30,  # 25% + 7.5%
                "rank_agreement": 0.10,   # unchanged
            }
            final_score = (
                base_score * weights["match_type"] +
                name_similarity * weights["name_similarity"] +
                (100.0 if rank_match else 50.0) * weights["rank_agreement"]
            )
            factors.append("Custom database (taxid verification N/A)")
        else:
            final_score = (
                base_score * self.WEIGHTS["match_type"] +
                name_similarity * self.WEIGHTS["name_similarity"] +
                (100.0 if rank_match else 50.0) * self.WEIGHTS["rank_agreement"] +
                (100.0 if has_taxid_match else 0.0) * self.WEIGHTS["taxid_verified"]
            )

        # 6. Penalty for multiple alternatives (ambiguity)
        # Don't penalize exact matches, high-confidence variants, or known reclassifications
        # - These are high-confidence matches where alternatives are expected (e.g., Escherichia species)
        is_exact_match = match_result.match_type in [MatchType.EXACT_TAXID, MatchType.EXACT_NAME]
        is_high_confidence_variant = (
            match_result.match_type == MatchType.VARIANT and match_result.score >= 0.9
        )
        is_reclassified = match_result.match_type == MatchType.RECLASSIFIED
        skip_penalty = is_exact_match or is_high_confidence_variant or is_reclassified

        if alternative_count > 1 and not skip_penalty:
            penalty = min(alternative_count * 5, 20)
            final_score -= penalty
            factors.append(
                f"{alternative_count} alternative matches (-{penalty})"
            )
        elif alternative_count > 1:
            factors.append(f"{alternative_count} similar names (no penalty for high-confidence match)")

        # 7. Determine status
        status = self._determine_status(
            final_score,
            alternative_count,
            match_result.match_type,
            match_result.score
        )

        return ConfidenceScore(
            base_score=base_score,
            name_similarity=name_similarity,
            rank_match=rank_match,
            has_taxid_match=has_taxid_match,
            alternative_matches=alternative_count,
            final_score=final_score,
            status=status,
            confidence_factors=factors
        )

    def _determine_status(
        self,
        final_score: float,
        alternative_count: int,
        match_type: MatchType,
        match_score: float = 1.0
    ) -> ValidationStatus:
        """Determine validation status from score."""
        # No match
        if match_type == MatchType.NO_MATCH:
            return ValidationStatus.NOT_FOUND

        # Exact matches, high-confidence variants, and reclassifications are not ambiguous
        is_exact_match = match_type in [MatchType.EXACT_TAXID, MatchType.EXACT_NAME]
        is_high_confidence_variant = match_type == MatchType.VARIANT and match_score >= 0.9
        is_reclassified = match_type == MatchType.RECLASSIFIED
        skip_ambiguous = is_exact_match or is_high_confidence_variant or is_reclassified

        # Ambiguous (multiple good alternatives) - but not for high-confidence matches
        if alternative_count > 1 and final_score > self.low_confidence_threshold and not skip_ambiguous:
            return ValidationStatus.AMBIGUOUS

        # Score-based thresholds
        if final_score >= self.exact_threshold:
            return ValidationStatus.EXACT_MATCH
        elif final_score >= self.high_confidence_threshold:
            return ValidationStatus.HIGH_CONFIDENCE
        elif final_score >= self.review_threshold:
            return ValidationStatus.NEEDS_REVIEW
        elif final_score >= self.low_confidence_threshold:
            return ValidationStatus.LOW_CONFIDENCE
        else:
            return ValidationStatus.NOT_FOUND

    def _rank_to_code(self, rank: str) -> str:
        """Convert rank name to single letter code."""
        rank_map = {
            "domain": "D",
            "phylum": "P",
            "class": "C",
            "order": "O",
            "family": "F",
            "genus": "G",
            "species": "S",
            "subspecies": "S1",
            "strain": "S2",
        }
        return rank_map.get(rank.lower(), "U")

    def should_auto_accept(self, score: ConfidenceScore) -> bool:
        """Check if a match should be auto-accepted."""
        return score.status in [
            ValidationStatus.EXACT_MATCH,
            ValidationStatus.HIGH_CONFIDENCE
        ]

    def needs_manual_review(self, score: ConfidenceScore) -> bool:
        """Check if a match needs manual review."""
        return score.status in [
            ValidationStatus.NEEDS_REVIEW,
            ValidationStatus.AMBIGUOUS,
            ValidationStatus.LOW_CONFIDENCE
        ]


# Default scorer instance
_scorer: Optional[ConfidenceScorer] = None


def get_confidence_scorer() -> ConfidenceScorer:
    """Get the default ConfidenceScorer instance."""
    global _scorer
    if _scorer is None:
        _scorer = ConfidenceScorer()
    return _scorer
