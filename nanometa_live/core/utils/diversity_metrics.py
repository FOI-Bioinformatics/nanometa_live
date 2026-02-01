"""
Diversity metrics for metagenomic analysis.

This module provides functions to calculate alpha and beta diversity metrics
for comparing microbial communities across samples.

Alpha Diversity: Within-sample diversity
- Shannon Index (H'): Accounts for both abundance and evenness
- Simpson Index (1-D): Probability that two individuals are different species
- Chao1: Estimates total species richness including unseen species
- Observed Species: Simple count of unique taxa

Beta Diversity: Between-sample diversity
- Bray-Curtis Dissimilarity: Quantitative measure of compositional dissimilarity
- Jaccard Index: Presence/absence based similarity
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class AlphaDiversity:
    """Alpha diversity metrics for a single sample."""
    sample_id: str
    shannon: float
    simpson: float
    observed_species: int
    chao1: float
    total_reads: int
    evenness: float  # Pielou's evenness (J')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for easy serialization."""
        return {
            "sample_id": self.sample_id,
            "shannon": round(self.shannon, 4),
            "simpson": round(self.simpson, 4),
            "observed_species": self.observed_species,
            "chao1": round(self.chao1, 2),
            "total_reads": self.total_reads,
            "evenness": round(self.evenness, 4)
        }


def calculate_shannon_index(counts: np.ndarray) -> float:
    """
    Calculate Shannon diversity index (H').

    H' = -sum(pi * ln(pi))

    where pi is the proportion of species i in the sample.
    Higher values indicate greater diversity.

    Args:
        counts: Array of species read counts (non-negative integers)

    Returns:
        Shannon diversity index (0 to ln(S) where S is species count)
    """
    counts = np.asarray(counts, dtype=float)
    counts = counts[counts > 0]  # Remove zeros

    if len(counts) == 0:
        return 0.0

    total = counts.sum()
    if total == 0:
        return 0.0

    proportions = counts / total
    # Use natural log (ln) for Shannon index
    shannon = -np.sum(proportions * np.log(proportions + 1e-10))

    return float(shannon)


def calculate_simpson_index(counts: np.ndarray) -> float:
    """
    Calculate Simpson diversity index (1 - D).

    D = sum(pi^2), so Simpson = 1 - D

    Higher values indicate greater diversity.
    Range: 0 (no diversity) to 1 (max diversity)

    Args:
        counts: Array of species read counts (non-negative integers)

    Returns:
        Simpson diversity index (0 to 1)
    """
    counts = np.asarray(counts, dtype=float)
    counts = counts[counts > 0]

    if len(counts) == 0:
        return 0.0

    total = counts.sum()
    if total == 0:
        return 0.0

    proportions = counts / total
    simpson = 1 - np.sum(proportions ** 2)

    return float(simpson)


def calculate_chao1(counts: np.ndarray) -> float:
    """
    Calculate Chao1 richness estimator.

    Estimates total species richness including unseen species based on
    the number of singletons and doubletons.

    Chao1 = S_obs + (f1^2 / (2 * f2))

    where:
    - S_obs = observed species count
    - f1 = number of singletons (species with 1 read)
    - f2 = number of doubletons (species with 2 reads)

    Args:
        counts: Array of species read counts

    Returns:
        Chao1 richness estimate
    """
    counts = np.asarray(counts, dtype=float)
    counts = counts[counts > 0]

    if len(counts) == 0:
        return 0.0

    observed = len(counts)
    singletons = np.sum(counts == 1)
    doubletons = np.sum(counts == 2)

    if doubletons == 0:
        # Bias-corrected form when doubletons = 0
        if singletons > 0:
            chao1 = observed + (singletons * (singletons - 1)) / 2
        else:
            chao1 = observed
    else:
        chao1 = observed + (singletons ** 2) / (2 * doubletons)

    return float(chao1)


def calculate_pielou_evenness(counts: np.ndarray) -> float:
    """
    Calculate Pielou's evenness index (J').

    J' = H' / ln(S)

    where H' is Shannon index and S is species count.
    Measures how evenly individuals are distributed among species.

    Args:
        counts: Array of species read counts

    Returns:
        Evenness index (0 to 1, where 1 = perfect evenness)
    """
    counts = np.asarray(counts, dtype=float)
    counts = counts[counts > 0]

    if len(counts) <= 1:
        return 0.0

    shannon = calculate_shannon_index(counts)
    max_shannon = np.log(len(counts))

    if max_shannon == 0:
        return 0.0

    return float(shannon / max_shannon)


def calculate_alpha_diversity(
    kraken_df: pd.DataFrame,
    sample_id: str = "sample"
) -> AlphaDiversity:
    """
    Calculate all alpha diversity metrics for a sample.

    Args:
        kraken_df: DataFrame with Kraken2 report data (must have 'reads' and 'rank' columns)
        sample_id: Identifier for this sample

    Returns:
        AlphaDiversity object with all metrics
    """
    # Filter to species level for meaningful diversity
    if 'rank' in kraken_df.columns:
        species_df = kraken_df[kraken_df['rank'] == 'S'].copy()
    else:
        species_df = kraken_df.copy()

    if species_df.empty or 'reads' not in species_df.columns:
        return AlphaDiversity(
            sample_id=sample_id,
            shannon=0.0,
            simpson=0.0,
            observed_species=0,
            chao1=0.0,
            total_reads=0,
            evenness=0.0
        )

    counts = species_df['reads'].values

    return AlphaDiversity(
        sample_id=sample_id,
        shannon=calculate_shannon_index(counts),
        simpson=calculate_simpson_index(counts),
        observed_species=len(counts[counts > 0]),
        chao1=calculate_chao1(counts),
        total_reads=int(counts.sum()),
        evenness=calculate_pielou_evenness(counts)
    )


def calculate_bray_curtis(counts1: np.ndarray, counts2: np.ndarray) -> float:
    """
    Calculate Bray-Curtis dissimilarity between two samples.

    BC = 1 - (2 * sum(min(n1i, n2i)) / (sum(n1) + sum(n2)))

    Range: 0 (identical) to 1 (completely different)

    Args:
        counts1: Read counts for sample 1 (aligned by taxon)
        counts2: Read counts for sample 2 (aligned by taxon)

    Returns:
        Bray-Curtis dissimilarity (0 to 1)
    """
    counts1 = np.asarray(counts1, dtype=float)
    counts2 = np.asarray(counts2, dtype=float)

    if len(counts1) != len(counts2):
        raise ValueError("Count arrays must have same length")

    sum_min = np.sum(np.minimum(counts1, counts2))
    sum_total = counts1.sum() + counts2.sum()

    if sum_total == 0:
        return 0.0

    bray_curtis = 1 - (2 * sum_min / sum_total)

    return float(bray_curtis)


def calculate_jaccard(counts1: np.ndarray, counts2: np.ndarray) -> float:
    """
    Calculate Jaccard similarity index (presence/absence based).

    J = |A intersection B| / |A union B|

    Range: 0 (no shared species) to 1 (identical species sets)

    Args:
        counts1: Read counts for sample 1
        counts2: Read counts for sample 2

    Returns:
        Jaccard similarity (0 to 1)
    """
    counts1 = np.asarray(counts1, dtype=float)
    counts2 = np.asarray(counts2, dtype=float)

    if len(counts1) != len(counts2):
        raise ValueError("Count arrays must have same length")

    # Convert to presence/absence
    present1 = counts1 > 0
    present2 = counts2 > 0

    intersection = np.sum(present1 & present2)
    union = np.sum(present1 | present2)

    if union == 0:
        return 0.0

    return float(intersection / union)


def build_abundance_matrix(
    sample_data: Dict[str, pd.DataFrame],
    rank: str = 'S'
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Build an abundance matrix from multiple sample DataFrames.

    Args:
        sample_data: Dict mapping sample_id -> Kraken2 DataFrame
        rank: Taxonomic rank to use ('S' for species, 'G' for genus, etc.)

    Returns:
        Tuple of (abundance_matrix, sample_list)
        Matrix has taxa as rows, samples as columns
    """
    all_taxa = set()
    sample_counts = {}

    for sample_id, df in sample_data.items():
        if 'rank' in df.columns:
            filtered = df[df['rank'] == rank].copy()
        else:
            filtered = df.copy()

        if filtered.empty or 'reads' not in filtered.columns:
            sample_counts[sample_id] = {}
            continue

        # Use taxid or name as identifier
        if 'taxid' in filtered.columns:
            taxon_col = 'taxid'
        elif 'name' in filtered.columns:
            taxon_col = 'name'
        else:
            sample_counts[sample_id] = {}
            continue

        counts = dict(zip(filtered[taxon_col], filtered['reads']))
        sample_counts[sample_id] = counts
        all_taxa.update(counts.keys())

    # Build matrix
    samples = list(sample_data.keys())
    taxa = sorted(list(all_taxa))

    matrix_data = []
    for taxon in taxa:
        row = [sample_counts.get(s, {}).get(taxon, 0) for s in samples]
        matrix_data.append(row)

    matrix = pd.DataFrame(matrix_data, index=taxa, columns=samples)

    return matrix, samples


def calculate_beta_diversity_matrix(
    sample_data: Dict[str, pd.DataFrame],
    method: str = "bray_curtis",
    rank: str = 'S'
) -> pd.DataFrame:
    """
    Calculate pairwise beta diversity between all samples.

    Args:
        sample_data: Dict mapping sample_id -> Kraken2 DataFrame
        method: 'bray_curtis' or 'jaccard'
        rank: Taxonomic rank to use

    Returns:
        DataFrame with pairwise dissimilarity/similarity values
    """
    # Build abundance matrix
    abundance_matrix, samples = build_abundance_matrix(sample_data, rank)

    if abundance_matrix.empty or len(samples) < 2:
        return pd.DataFrame()

    # Select distance function
    if method == "bray_curtis":
        dist_func = calculate_bray_curtis
    elif method == "jaccard":
        dist_func = calculate_jaccard
    else:
        raise ValueError(f"Unknown method: {method}")

    # Calculate pairwise distances
    n_samples = len(samples)
    distance_matrix = np.zeros((n_samples, n_samples))

    for i in range(n_samples):
        for j in range(i, n_samples):
            if i == j:
                distance_matrix[i, j] = 0.0
            else:
                counts_i = abundance_matrix[samples[i]].values
                counts_j = abundance_matrix[samples[j]].values
                dist = dist_func(counts_i, counts_j)
                distance_matrix[i, j] = dist
                distance_matrix[j, i] = dist

    return pd.DataFrame(distance_matrix, index=samples, columns=samples)


def get_diversity_summary(
    sample_data: Dict[str, pd.DataFrame]
) -> Dict[str, Any]:
    """
    Get a comprehensive diversity summary for multiple samples.

    Args:
        sample_data: Dict mapping sample_id -> Kraken2 DataFrame

    Returns:
        Dict with alpha and beta diversity summaries
    """
    # Calculate alpha diversity for each sample
    alpha_results = []
    for sample_id, df in sample_data.items():
        alpha = calculate_alpha_diversity(df, sample_id)
        alpha_results.append(alpha.to_dict())

    # Calculate beta diversity if multiple samples
    beta_matrix = None
    if len(sample_data) >= 2:
        try:
            beta_matrix = calculate_beta_diversity_matrix(sample_data, "bray_curtis")
            beta_matrix = beta_matrix.round(4).to_dict()
        except Exception as e:
            logger.warning(f"Could not calculate beta diversity: {e}")
            beta_matrix = None

    # Summary statistics
    if alpha_results:
        shannon_values = [a["shannon"] for a in alpha_results]
        simpson_values = [a["simpson"] for a in alpha_results]
        species_counts = [a["observed_species"] for a in alpha_results]

        summary_stats = {
            "mean_shannon": round(np.mean(shannon_values), 4),
            "std_shannon": round(np.std(shannon_values), 4),
            "mean_simpson": round(np.mean(simpson_values), 4),
            "mean_species": round(np.mean(species_counts), 1),
            "min_species": min(species_counts),
            "max_species": max(species_counts)
        }
    else:
        summary_stats = {}

    return {
        "alpha_diversity": alpha_results,
        "beta_diversity": beta_matrix,
        "summary": summary_stats,
        "sample_count": len(sample_data)
    }
