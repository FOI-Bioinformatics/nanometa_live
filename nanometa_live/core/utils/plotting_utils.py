"""
Plotting utility functions for Nanometa Live.

This module provides utility functions for generating and manipulating plots
and visualizations used by the application.
"""

import os
import logging
import math
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional

import plotly.graph_objects as go
import plotly.express as px


def create_top_list(
    raw_df: pd.DataFrame, domains: List[str], keep_letters: List[str], top: int = 15
) -> pd.DataFrame:
    """
    Create a dataframe of the top taxa by read count.

    Args:
        raw_df: Raw Kraken report dataframe
        domains: Domains to include (Bacteria, Archaea, Eukaryota, Viruses)
        keep_letters: Taxonomy letters to include (D, P, C, O, F, G, S)
        top: Number of top taxa to include

    Returns:
        Dataframe with top taxa
    """
    # Disable SettingWithCopyWarning
    pd.options.mode.chained_assignment = None

    # Filter by domains
    filtered_df = domain_filtering(raw_df, domains)

    # Filter by taxonomy levels
    filtered_df = filtered_df[filtered_df["rank"].isin(keep_letters)]

    # Sort by reads in descending order
    sorted_df = filtered_df.sort_values("reads", ascending=False)

    # Get top entries
    top_df = sorted_df.head(top).copy()

    # Add index column
    top_df["Index"] = range(1, len(top_df) + 1)

    # Reorganize columns
    result_df = top_df[["Index", "name", "taxid", "rank", "reads"]]
    result_df.columns = ["Index", "Name", "Tax ID", "Tax Rank", "Reads"]

    return result_df


def domain_filtering(raw_df: pd.DataFrame, selected_domains: List[str]) -> pd.DataFrame:
    """
    Filter the Kraken report dataframe by domains.

    Args:
        raw_df: Raw Kraken report dataframe
        selected_domains: Domains to include (Bacteria, Archaea, Eukaryota, Viruses)

    Returns:
        Filtered dataframe
    """
    # Add column names for ease of parsing
    if raw_df.shape[1] == 6 and not all(isinstance(c, str) for c in raw_df.columns):
        raw_df.columns = ["%", "cuml_reads", "reads", "rank", "taxid", "name"]

    # All possible domains
    all_domains = ["Bacteria", "Archaea", "Eukaryota", "Viruses"]

    # Find start index for each domain
    domain_indices = {}
    for domain in all_domains:
        domain_rows = raw_df[raw_df["name"].str.strip() == domain]
        if not domain_rows.empty:
            domain_indices[domain] = domain_rows.index[0]

    # Sort domains by their index in the report
    sorted_domains = sorted(domain_indices.items(), key=lambda x: x[1])

    # Define domain ranges
    domain_ranges = []
    for i, (domain, start_idx) in enumerate(sorted_domains):
        if i + 1 < len(sorted_domains):
            # End index is the start of the next domain
            domain_ranges.append((domain, start_idx, sorted_domains[i + 1][1]))
        else:
            # End index for the last domain is the end of the dataframe
            domain_ranges.append((domain, start_idx, len(raw_df)))

    # Filter rows based on selected domains
    selected_rows = []
    for domain, start_idx, end_idx in domain_ranges:
        if domain in selected_domains:
            selected_rows.extend(range(start_idx, end_idx))

    # Return filtered dataframe
    return raw_df.iloc[selected_rows]


def create_sankey_data(
    filt_df: pd.DataFrame, tax_levels: List[str], top_entries: int = 10
) -> go.Sankey:
    """
    Create Sankey plot data from filtered dataframe.

    Args:
        filt_df: Filtered Kraken report dataframe
        tax_levels: Taxonomy levels to include
        top_entries: Number of top entries to include per level

    Returns:
        Plotly Sankey graph object
    """
    # Create node data
    nodes = []
    node_map = {}  # Maps (level, taxid) to node index
    node_idx = 0

    # Create link data
    links = {"source": [], "target": [], "value": [], "level": []}

    # Process each taxonomy level
    for i, level in enumerate(tax_levels):
        # Filter entries for this level
        level_df = filt_df[filt_df["rank"] == level]

        # Sort by reads and take top entries
        level_df = level_df.sort_values("reads", ascending=False).head(top_entries)

        for _, row in level_df.iterrows():
            taxid = row["taxid"]
            name = row["name"].strip()
            reads = row["reads"]

            # Add node if it doesn't exist
            if (level, taxid) not in node_map:
                node_map[(level, taxid)] = node_idx
                nodes.append(name)
                node_idx += 1

            # Add link to parent if not the first level
            if i > 0:
                # Find parent by traversing up the taxonomy tree
                parent_found = False
                parent_level = tax_levels[i - 1]

                # Get all entries with this taxid
                all_entries = filt_df[filt_df["taxid"] == taxid]

                for _, entry in all_entries.iterrows():
                    # Get all entries above this one in the report
                    above_entries = filt_df.iloc[: entry.name]

                    # Find the closest entry with the parent level
                    parent_entries = above_entries[
                        above_entries["rank"] == parent_level
                    ]

                    if not parent_entries.empty:
                        parent_entry = parent_entries.iloc[-1]
                        parent_taxid = parent_entry["taxid"]

                        # Check if parent is in the node map
                        if (parent_level, parent_taxid) in node_map:
                            links["source"].append(
                                node_map[(parent_level, parent_taxid)]
                            )
                            links["target"].append(node_map[(level, taxid)])
                            links["value"].append(reads)
                            links["level"].append(level)
                            parent_found = True
                            break

                # If no parent found, link to a dummy root node
                if not parent_found:
                    # Add root node if it doesn't exist
                    if ("root", "0") not in node_map:
                        node_map[("root", "0")] = node_idx
                        nodes.append("Root")
                        node_idx += 1

                    links["source"].append(node_map[("root", "0")])
                    links["target"].append(node_map[(level, taxid)])
                    links["value"].append(reads)
                    links["level"].append(level)

    # Create Sankey data
    sankey_data = go.Sankey(
        node=dict(
            pad=15, thickness=20, line=dict(color="black", width=0.5), label=nodes
        ),
        link=dict(source=links["source"], target=links["target"], value=links["value"]),
    )

    return sankey_data


def create_sunburst_data(filt_df: pd.DataFrame, min_reads: int = 10) -> Dict[str, List]:
    """
    Create Sunburst chart data from filtered dataframe.

    Args:
        filt_df: Filtered Kraken report dataframe
        min_reads: Minimum reads for a taxon to be included

    Returns:
        Dictionary with taxon, parent, and reads data
    """
    # Filter by minimum reads
    filt_df = filt_df[filt_df["reads"] >= min_reads]

    # Add column for parent taxon
    filt_df["parent"] = ""

    # Initialize data
    taxon_data = []
    parent_data = []
    reads_data = []

    # Add root node
    taxon_data.append("root")
    parent_data.append("")
    reads_data.append(0)

    # Process each row
    for _, row in filt_df.iterrows():
        taxid = row["taxid"]
        name = row["name"].strip()
        reads = row["reads"]
        level = row["rank"]

        # Find parent
        parent = "root"

        # If not a top-level entry, look for a parent
        if level not in ["D", "K"]:
            # Get all entries above this one in the report
            above_entries = filt_df.iloc[:_]

            # Find entries at higher ranks
            for parent_level in ["K", "D", "P", "C", "O", "F", "G"]:
                if parent_level >= level:
                    continue

                parent_entries = above_entries[above_entries["rank"] == parent_level]

                if not parent_entries.empty:
                    # Get the closest parent
                    parent_entry = parent_entries.iloc[-1]
                    parent = parent_entry["name"].strip()
                    break

        # Add to data
        taxon_data.append(name)
        parent_data.append(parent)
        reads_data.append(reads)

    return {"Taxon": taxon_data, "Parent": parent_data, "Reads": reads_data}


def format_sankey_plot(fig: go.Figure) -> go.Figure:
    """
    Format a Sankey plot with standard styling.

    Args:
        fig: Plotly figure object with Sankey plot

    Returns:
        Formatted figure
    """
    fig.update_layout(
        font_size=12, height=900, width=1700, margin=dict(t=20, l=20, b=20, r=50)
    )

    fig.update_traces(orientation="h", arrangement="freeform", textfont_size=12)

    return fig


def format_sunburst_plot(fig: go.Figure) -> go.Figure:
    """
    Format a Sunburst plot with standard styling.

    Args:
        fig: Plotly figure object with Sunburst plot

    Returns:
        Formatted figure
    """
    fig.update_layout(height=900, width=900, margin=dict(t=50, l=25, r=25, b=25))

    fig.update_traces(hovertemplate="<b>%{label}</b><br>Reads: %{value}")

    return fig


def format_qc_plots(
    cumul_reads_fig: go.Figure,
    cumul_bp_fig: go.Figure,
    reads_fig: go.Figure,
    bp_fig: go.Figure,
) -> Tuple[go.Figure, go.Figure, go.Figure, go.Figure]:
    """
    Format QC plots with standard styling.

    Args:
        cumul_reads_fig: Cumulative reads plot
        cumul_bp_fig: Cumulative base pairs plot
        reads_fig: Reads per batch plot
        bp_fig: Base pairs per batch plot

    Returns:
        Tuple of formatted figures
    """
    # Set common layout properties
    layout = dict(height=350, margin=dict(l=50, r=50, t=50, b=50), font=dict(size=12))

    # Format cumulative reads plot
    cumul_reads_fig.update_layout(
        title="Cumulative Reads Over Time",
        xaxis_title="Time",
        yaxis_title="Reads",
        **layout,
    )

    # Format cumulative base pairs plot
    cumul_bp_fig.update_layout(
        title="Cumulative Base Pairs Over Time",
        xaxis_title="Time",
        yaxis_title="Base Pairs",
        **layout,
    )

    # Format reads per batch plot
    reads_fig.update_layout(
        title="Reads per Batch",
        xaxis_title="Batch Timestamp",
        yaxis_title="Reads",
        **layout,
    )

    # Format base pairs per batch plot
    bp_fig.update_layout(
        title="Base Pairs per Batch",
        xaxis_title="Batch Timestamp",
        yaxis_title="Base Pairs",
        **layout,
    )

    # Make bar plots discrete on x-axis
    reads_fig.update_xaxes(type="category")
    bp_fig.update_xaxes(type="category")

    return cumul_reads_fig, cumul_bp_fig, reads_fig, bp_fig


def create_pathogen_plot(pathogen_df: pd.DataFrame, threshold: int = 100) -> go.Figure:
    """
    Create a plot of species of interest.

    Args:
        pathogen_df: Dataframe with pathogen data
        threshold: Threshold for highlighting

    Returns:
        Plotly figure
    """
    # Add color column based on threshold
    pathogen_df["Color"] = pathogen_df["Reads"].apply(
        lambda x: "Red" if x > threshold else "Green"
    )

    # Create plot
    fig = px.bar(
        pathogen_df,
        x="Name",
        y="Reads",
        color="Color",
        title="Species of Interest",
        labels={"Reads": "Number of Reads", "Name": "Species"},
        color_discrete_map={"Red": "red", "Green": "green"},
    )

    # Format plot
    fig.update_layout(showlegend=False, xaxis_tickangle=-45, height=400, width=700)

    # Update bar width
    fig.update_traces(width=0.4)

    # Update hover template
    fig.update_traces(
        hovertemplate="<b>%{x}</b><br>Number of Reads: %{y}", hoverinfo="x+y"
    )

    return fig


def get_color_scale(
    values: List[float],
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> List[str]:
    """
    Generate a list of colors based on values.

    Args:
        values: List of values to map to colors
        min_val: Minimum value for scaling (defaults to min of values)
        max_val: Maximum value for scaling (defaults to max of values)

    Returns:
        List of hex color strings
    """
    if min_val is None:
        min_val = min(values)

    if max_val is None:
        max_val = max(values)

    # Normalize values to 0-1 range
    if max_val == min_val:
        normalized = [0.5 for _ in values]
    else:
        normalized = [(v - min_val) / (max_val - min_val) for v in values]

    # Create colors (blue gradient)
    colors = []
    for n in normalized:
        # Map 0-1 to blue color (from light to dark)
        r = int(255 * (1 - n))
        g = int(255 * (1 - n))
        b = 255
        colors.append(f"#{r:02x}{g:02x}{b:02x}")

    return colors
