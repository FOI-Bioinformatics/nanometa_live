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
# PlusPFP uses sub-ranks (R2, R3, K, K1-K3, P1-P9, C1-C6, O1-O4, F1-F7, G1-G2, S1-S3)
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
    "F1": "F", "F2": "F", "F3": "F", "F4": "F", "F5": "F", "F6": "F", "F7": "F",
    "G1": "G", "G2": "G",
    "S1": "S", "S2": "S", "S3": "S",
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

    Maps sub-ranks (K1-K3, P1-P9, C1-C6, O1-O4, F1-F7, G1-G2, S1-S3) to their
    parent standard rank (K, P, C, O, F, G, S). K (Kingdom) is kept as a distinct level
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
# Authoritative Taxonomy from Kraken2 Database
# ============================================================================
#
# Kraken2 per-sample reports can have non-standard file ordering (nodes
# appearing out of DFS order or in the wrong subtree). The indentation-based
# parent_taxid parser in classification_loaders assumes strict DFS order,
# which produces incorrect parent chains for some organisms (observed with
# the PlusPFP database: Bacillus appears before Bacillaceae in the report,
# and Bacillus cereus is placed inside the Lactobacillales subtree).
#
# The database's inspect.txt contains the full taxonomy tree in correct DFS
# order, so parsing it once gives us authoritative taxid -> parent_taxid
# mappings that we can apply to the per-sample reports.

_TAXONOMY_CACHE: dict = {}


def load_kraken2_taxonomy(kraken_db_path: str) -> dict:
    """Load authoritative taxid -> parent_taxid mapping from Kraken2 inspect.txt.

    The inspect.txt file in a Kraken2 database contains the full taxonomy
    tree in proper DFS order. Parsing its indentation yields correct parent
    relationships (unlike per-sample reports which may be disordered).

    Args:
        kraken_db_path: Path to the Kraken2 database directory.

    Returns:
        Dict mapping taxid -> parent_taxid. Returns empty dict if the
        inspect.txt file is missing or cannot be read.
    """
    import gzip
    import os

    if not kraken_db_path:
        return {}

    # Cache on the database directory so a gz-only DB is cached too (the cache
    # key used to be the plain inspect.txt path).
    if kraken_db_path in _TAXONOMY_CACHE:
        return _TAXONOMY_CACHE[kraken_db_path]

    # Prefer a plain inspect.txt; fall back to a gzipped inspect.txt.gz. Some
    # Kraken2 builds (e.g. GTDB-derived / size-conscious DBs) ship only the
    # compressed form. The DB indexer already reads the .gz
    # (database_indexer.build_from_inspect_gz); mirror that here so the
    # authoritative-taxonomy correction for Sankey/Sunburst is not silently
    # disabled on those databases.
    plain_path = os.path.join(kraken_db_path, "inspect.txt")
    gz_path = os.path.join(kraken_db_path, "inspect.txt.gz")
    if os.path.exists(plain_path):
        inspect_path = plain_path
        _opener = lambda p: open(p)
    elif os.path.exists(gz_path):
        inspect_path = gz_path
        _opener = lambda p: gzip.open(p, "rt", encoding="utf-8")
    else:
        logging.debug(f"Kraken2 inspect.txt[.gz] not found in {kraken_db_path}")
        _TAXONOMY_CACHE[kraken_db_path] = {}
        return {}

    taxid_to_parent: dict = {}
    indent_stack = []  # list of (indent, taxid)

    try:
        with _opener(inspect_path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 6:
                    continue
                try:
                    taxid = int(parts[4])
                except (ValueError, IndexError):
                    continue
                name = parts[5]
                indent = len(name) - len(name.lstrip())

                while indent_stack and indent_stack[-1][0] >= indent:
                    indent_stack.pop()

                parent = indent_stack[-1][1] if indent_stack else 0
                taxid_to_parent[taxid] = parent
                indent_stack.append((indent, taxid))
    except (OSError, EOFError) as exc:
        # EOFError / gzip.BadGzipFile (an OSError subclass) cover a truncated or
        # malformed .gz; a plain-text OSError covers an unreadable inspect.txt.
        logging.warning(f"Failed to read Kraken2 {os.path.basename(inspect_path)}: {exc}")
        _TAXONOMY_CACHE[kraken_db_path] = {}
        return {}

    logging.info(
        f"Loaded Kraken2 taxonomy from {inspect_path}: "
        f"{len(taxid_to_parent)} taxa"
    )
    _TAXONOMY_CACHE[kraken_db_path] = taxid_to_parent
    return taxid_to_parent


def apply_authoritative_taxonomy(df, taxid_to_parent: dict):
    """Replace parent_taxid column with authoritative values from Kraken2 taxonomy.

    The per-sample report's indentation-based parent_taxid can be wrong when
    the report file has non-standard ordering. This function replaces each
    entry's parent_taxid with the value from inspect.txt (if available).

    Args:
        df: DataFrame with 'taxid' and 'parent_taxid' columns.
        taxid_to_parent: Authoritative taxid -> parent_taxid mapping
                         (from load_kraken2_taxonomy).

    Returns:
        DataFrame with corrected parent_taxid values. If the mapping is
        empty, returns the input unchanged.
    """
    if not taxid_to_parent or df.empty or "taxid" not in df.columns:
        return df

    result = df.copy()
    # Map each taxid to its authoritative parent. Taxids not present in the
    # taxonomy (e.g. U/unclassified) keep their existing parent_taxid.
    mapped = result["taxid"].astype(int).map(taxid_to_parent)
    if "parent_taxid" in result.columns:
        result["parent_taxid"] = mapped.fillna(result["parent_taxid"]).astype(int)
    else:
        result["parent_taxid"] = mapped.fillna(0).astype(int)
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

    # Vectorized build of the composite-key -> cumulative-reads map. This
    # is on the hot Sankey/Sunburst rebuild path; the previous df.iloc[idx]
    # row loop was quadratic in access cost for large databases.
    names = df["name"].str.strip()
    if "rank" in df.columns:
        ranks = df["rank"].astype(str)
    else:
        ranks = pd.Series("", index=df.index)
    keys = ranks + "_" + names

    # Use cumul_reads (cumulative/clade reads) when present, else fall back
    # to reads (direct assignments), else 0 -- matching the per-row .get
    # precedence the loop used.
    if "cumul_reads" in df.columns:
        vals = df["cumul_reads"]
    elif "reads" in df.columns:
        vals = df["reads"]
    else:
        vals = pd.Series(0, index=df.index)

    # dict(zip(...)) keeps the last value on duplicate composite keys,
    # exactly as repeated dict assignment in the loop did. Materialise both
    # columns with .tolist() first: zipping the arrow-backed string `keys`
    # Series directly iterates it element-by-element through arrow __iter__,
    # which is ~3 full-column iterations of pure overhead on every Sankey/
    # Sunburst rebuild (cProfile, GTDB scale). Native Python lists zip in C.
    return dict(zip(keys.tolist(), vals.tolist()))


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
