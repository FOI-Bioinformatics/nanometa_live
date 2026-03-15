"""
Kraken2 report parsing and transformation helpers.

This module contains constants, rank normalization, and data transformation
functions specific to the Kraken2 taxonomic report format. These helpers
are used by classification_tab.py to prepare data for Sankey and Sunburst
visualizations.
"""

import logging
import pandas as pd


# ============================================================================
# Kraken2 Rank Constants
# ============================================================================

# Full names for taxonomy rank codes used in Kraken2 reports
RANK_NAMES = {
    "D": "Domain",
    "K": "Kingdom",
    "P": "Phylum",
    "C": "Class",
    "O": "Order",
    "F": "Family",
    "G": "Genus",
    "S": "Species",
    "R": "Root",
    "R1": "Superkingdom",
    "U": "Unclassified",
}

# Canonical ordering of taxonomy levels from broadest to most specific
CANONICAL_RANK_ORDER = ["D", "K", "P", "C", "O", "F", "G", "S"]

# Standard ranks that require no normalization
STANDARD_RANKS = {"D", "K", "P", "C", "O", "F", "G", "S", "R", "R1", "U"}

# Extended rank normalization for Kraken2 PlusPFP (NCBI extended taxonomy).
# PlusPFP uses sub-ranks (R2, R3, K, K1-K3, P1-P9, C1-C6, O1-O4, F1-F2, G1-G2, S1)
# that are mapped to the standard 8-level hierarchy (D, K, P, C, O, F, G, S).
# Kingdom (K) is preserved as a distinct level between Domain and Phylum.
RANK_NORMALIZATION = {
    "R2": "D",   # Root level 2 (Domain in PlusPFP)
    "R3": "K",   # Root level 3 (e.g. Opisthokonta) -> Kingdom level
    "K": "K",    # Kingdom stays as Kingdom (separate from Domain)
    "K1": "K", "K2": "K", "K3": "K",
    "P1": "P", "P2": "P", "P3": "P", "P4": "P", "P5": "P",
    "P6": "P", "P7": "P", "P8": "P", "P9": "P",
    "C1": "C", "C2": "C", "C3": "C", "C4": "C", "C5": "C", "C6": "C",
    "O1": "O", "O2": "O", "O3": "O", "O4": "O",
    "F1": "F", "F2": "F",
    "G1": "G", "G2": "G",
    "S1": "S",
}


# ============================================================================
# Color Scheme Definitions
# ============================================================================

# Tableau 10 - Scientific publication standard, colorblind-friendly
COLORS_TABLEAU = {
    "D": "#4E79A7",  # Domain - Steel blue
    "K": "#A0CBE8",  # Kingdom - Light blue
    "P": "#F28E2B",  # Phylum - Warm orange
    "C": "#E15759",  # Class - Soft red
    "O": "#76B7B2",  # Order - Teal
    "F": "#59A14F",  # Family - Forest green
    "G": "#EDC948",  # Genus - Gold/yellow
    "S": "#B07AA1",  # Species - Muted purple
}

# Viridis-inspired - Perceptually uniform, suitable for colorblind users
COLORS_VIRIDIS = {
    "D": "#440154",  # Domain - Deep purple
    "K": "#3B528B",  # Kingdom - Blue-purple
    "P": "#414487",  # Phylum - Indigo
    "C": "#2A788E",  # Class - Blue-teal
    "O": "#22A884",  # Order - Teal-green
    "F": "#7AD151",  # Family - Yellow-green
    "G": "#BDDF26",  # Genus - Lime
    "S": "#FDE725",  # Species - Yellow
}

# ColorBrewer Set2 - Pastel, softer colors for presentations
COLORS_PASTEL = {
    "D": "#66C2A5",  # Domain - Mint
    "K": "#B3E2CD",  # Kingdom - Light mint
    "P": "#FC8D62",  # Phylum - Salmon
    "C": "#8DA0CB",  # Class - Periwinkle
    "O": "#E78AC3",  # Order - Pink
    "F": "#A6D854",  # Family - Lime green
    "G": "#FFD92F",  # Genus - Yellow
    "S": "#E5C494",  # Species - Tan
}

# ColorBrewer Dark2 - High contrast for projectors/posters
COLORS_DARK = {
    "D": "#1B9E77",  # Domain - Teal
    "K": "#66C2A5",  # Kingdom - Mint
    "P": "#D95F02",  # Phylum - Orange
    "C": "#7570B3",  # Class - Purple
    "O": "#E7298A",  # Order - Magenta
    "F": "#66A61E",  # Family - Green
    "G": "#E6AB02",  # Genus - Gold
    "S": "#A6761D",  # Species - Brown
}

# Nature-inspired - Earthy tones for ecological studies
COLORS_NATURE = {
    "D": "#2D4739",  # Domain - Dark forest
    "K": "#3D6B52",  # Kingdom - Mid forest
    "P": "#5A8A5C",  # Phylum - Forest green
    "C": "#8CB369",  # Class - Sage
    "O": "#E9C46A",  # Order - Sandy
    "F": "#F4A261",  # Family - Terracotta
    "G": "#E76F51",  # Genus - Coral
    "S": "#264653",  # Species - Deep teal
}

# Ocean - Cool blues for marine studies
COLORS_OCEAN = {
    "D": "#03045E",  # Domain - Navy
    "K": "#023073",  # Kingdom - Deep navy-blue
    "P": "#023E8A",  # Phylum - Dark blue
    "C": "#0077B6",  # Class - Medium blue
    "O": "#0096C7",  # Order - Bright blue
    "F": "#00B4D8",  # Family - Light blue
    "G": "#48CAE4",  # Genus - Sky blue
    "S": "#90E0EF",  # Species - Pale blue
}

# Available color schemes (simplified to 3 essential options)
COLOR_SCHEMES = {
    "viridis": COLORS_VIRIDIS,
    "tableau": COLORS_TABLEAU,
    "dark": COLORS_DARK,
}

# Default color scheme
TAXONOMY_COLORS = COLORS_TABLEAU


# ============================================================================
# Rank Normalization
# ============================================================================

def normalize_ranks(df):
    """
    Normalize extended Kraken2 PlusPFP ranks to standard taxonomy levels.

    Maps sub-ranks (K1-K3, P1-P9, C1-C6, etc.) to their parent standard
    rank (K, P, C, O, F, G, S). K (Kingdom) is kept as a distinct level
    between D (Domain) and P (Phylum). Rows with unmappable ranks (R, R1, U)
    are left unchanged. Works on a copy of the dataframe.

    Args:
        df: DataFrame with a 'rank' column containing Kraken2 rank codes

    Returns:
        DataFrame with normalized rank column; original rank preserved in
        'original_rank' column for display purposes
    """
    if df.empty or "rank" not in df.columns:
        return df

    result = df.copy()
    result["original_rank"] = result["rank"]
    result["rank"] = result["rank"].map(lambda r: RANK_NORMALIZATION.get(r, r))
    return result


# ============================================================================
# Kraken2 Report Data Transformations
# ============================================================================

def recalculate_cumulative_reads(df):
    """
    Get cumulative reads from the Kraken2 cumul_reads column.

    The Kraken2 report format provides cumulative reads (column 2) which represents
    the total reads for a clade (this taxon + all descendants). This is the correct
    value to use for visualization.

    For single samples: cumul_reads is already correct from Kraken2.
    For aggregated samples: cumul_reads sum is an approximation.

    Uses composite keys f"{rank}_{name}" to avoid collisions when taxa at
    different ranks share the same stripped name.

    Args:
        df: DataFrame with Kraken2 data including 'name', 'rank', 'cumul_reads' columns

    Returns:
        Dict mapping composite key (f"{rank}_{name}") to cumulative reads
    """
    if df.empty:
        return {}

    result = {}
    for idx in range(len(df)):
        row = df.iloc[idx]
        name = row["name"].strip()
        rank = row.get("rank", "")
        composite_key = f"{rank}_{name}"
        # Use cumul_reads (column 2) - the cumulative/clade reads
        # NOT reads (column 3) which is only direct assignments
        result[composite_key] = row.get("cumul_reads", row.get("reads", 0))

    return result


def build_parent_map(tax_df, domain_df, tax_levels, node_ids, top_filter,
                     taxid_to_parent=None, taxid_to_key=None):
    """
    Build a mapping of child composite keys to their parent composite keys.

    Uses taxid-based parent lookup to walk up the taxonomy tree until finding
    an ancestor at the expected parent level. This is order-independent and
    works correctly for both single-sample and aggregated data.

    Args:
        tax_df: DataFrame filtered to selected taxonomy levels
        domain_df: Full DataFrame (unused, kept for API compatibility)
        tax_levels: List of taxonomy levels being displayed
        node_ids: Dict mapping composite key (f"{rank}_{name}") -> node index
        top_filter: Number of top entities at each level
        taxid_to_parent: Dict mapping taxid -> parent_taxid
        taxid_to_key: Dict mapping taxid -> composite key

    Returns:
        Dict mapping child composite key -> parent composite key
    """
    parent_map = {}

    for i in range(len(tax_levels) - 1, 0, -1):
        current_level = tax_levels[i]
        parent_level = tax_levels[i - 1]

        level_df = (
            tax_df[tax_df["rank"] == current_level]
            .sort_values("recalc_cumul", ascending=False)
            .head(top_filter)
        )

        child_names_stripped = level_df["name"].str.strip().tolist()
        child_taxids = level_df["taxid"].tolist()

        for child_name, child_taxid in zip(child_names_stripped, child_taxids):
            child_key = f"{current_level}_{child_name}"
            if child_key not in node_ids:
                continue

            # Walk up the taxid parent chain to find ancestor at parent_level
            current_taxid = taxid_to_parent.get(int(child_taxid), 0)
            while current_taxid != 0:
                ancestor_key = taxid_to_key.get(current_taxid)
                if ancestor_key is not None:
                    ancestor_rank = ancestor_key.split("_", 1)[0]
                    if ancestor_rank == parent_level:
                        if ancestor_key in node_ids:
                            parent_map[child_key] = ancestor_key
                        break
                    elif ancestor_rank in tax_levels and tax_levels.index(ancestor_rank) < tax_levels.index(parent_level):
                        break
                current_taxid = taxid_to_parent.get(current_taxid, 0)

    return parent_map


def filter_by_domains(kraken_df, domains):
    """
    Filter Kraken report by domains using indentation-based hierarchy.

    Uses leading spaces (indentation) in Kraken2 taxon names to determine
    parent-child relationships. Works correctly even when dataframe indices
    are non-sequential (after aggregation).

    Args:
        kraken_df: DataFrame containing Kraken report with 'name' column
        domains: List of domain names to include (e.g., ['Bacteria', 'Archaea'])

    Returns:
        DataFrame containing selected domains and all their descendants
    """
    if kraken_df.empty or not domains:
        return pd.DataFrame()

    selected_indices = []

    for domain in domains:
        # Find domain row (exact match, case-sensitive, stripped)
        domain_rows = kraken_df[kraken_df["name"].str.strip() == domain]

        if domain_rows.empty:
            logging.debug(f"Domain '{domain}' not found in Kraken data")
            continue

        # Get domain row index (first occurrence)
        domain_idx = domain_rows.index[0]
        domain_name_full = kraken_df.loc[domain_idx, "name"]
        domain_indent = len(domain_name_full) - len(domain_name_full.lstrip())

        # Add domain itself
        selected_indices.append(domain_idx)

        # Find all descendants (rows with greater indentation that come after this domain)
        # Stop when we hit another domain at same indentation level OR end of dataframe
        current_pos = list(kraken_df.index).index(domain_idx)

        for next_pos in range(current_pos + 1, len(kraken_df)):
            next_idx = kraken_df.index[next_pos]
            next_row = kraken_df.loc[next_idx]
            next_name_full = next_row["name"]
            next_indent = len(next_name_full) - len(next_name_full.lstrip())

            # If indentation is less than or equal to domain (same or shallower level),
            # we've left this domain's subtree
            if next_indent <= domain_indent:
                # Check if this is another selected domain
                if next_row["name"].strip() not in domains:
                    # Not a selected domain, and we're back at domain level - stop
                    break
                else:
                    # This is another selected domain - don't include it here
                    # (it will be added in its own iteration)
                    break
            else:
                # This is a descendant (greater indentation) - include it
                selected_indices.append(next_idx)

    # Remove duplicates while preserving order
    seen = set()
    unique_indices = []
    for idx in selected_indices:
        if idx not in seen:
            seen.add(idx)
            unique_indices.append(idx)

    # Return filtered dataframe in original order
    if not unique_indices:
        return pd.DataFrame()

    return kraken_df.loc[unique_indices].copy()


def get_level_color(rank, depth_in_level=0, total_in_level=1, color_palette=None):
    """
    Get color for a taxonomy level with brightness variation.

    Args:
        rank: Taxonomy rank code (D, P, C, O, F, G, S)
        depth_in_level: Position of this item within its level (for variation)
        total_in_level: Total items at this level
        color_palette: Optional color palette dictionary (defaults to TAXONOMY_COLORS)

    Returns:
        RGBA color string
    """
    colors = color_palette or TAXONOMY_COLORS
    base_color = colors.get(rank, "#94A3B8")

    # Convert hex to RGB
    hex_color = base_color.lstrip("#")
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    # Add subtle brightness variation within each level
    if total_in_level > 1:
        variation = 0.15 * (depth_in_level / max(1, total_in_level - 1)) - 0.075
        r = min(255, max(0, int(r * (1 + variation))))
        g = min(255, max(0, int(g * (1 + variation))))
        b = min(255, max(0, int(b * (1 + variation))))

    return f"rgb({r},{g},{b})"
