"""
Sankey plot tab callbacks for Nanometa Live.

This module defines the callbacks for the Sankey plot tab, which displays
hierarchical taxonomic relationships as a Sankey diagram.
"""

import os
import numpy as np
import pandas as pd
import json
from typing import Dict, Any, List

from dash import Dash, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go


def register_sankey_callbacks(app: Dash):
    """
    Register callbacks for the Sankey plot tab.

    Args:
        app: Dash application
    """

    @app.callback(
        Output("sankey-plot", "figure"),
        [Input("update-interval", "n_intervals"), Input("filter-submit", "n_clicks")],
        [
            State("filter-value", "value"),
            State("domains", "value"),
            State("clades", "value"),
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
    )
    def update_sankey_plot(
        n_intervals, filter_clicks, filter_value, domains, tax_levels, config, status
    ):
        """Update the Sankey plot based on filter criteria and latest data."""
        if not config or not status or not status.get("running", False):
            # Return empty plot if not running
            return create_placeholder_sankey()

        # Set defaults
        filter_value = filter_value or 10
        domains = domains or ["Bacteria", "Archaea", "Eukaryota", "Viruses"]

        # Get the valid taxonomy levels in the correct order
        all_tax_levels = config.get(
            "taxonomic_hierarchy_letters", ["D", "P", "C", "O", "F", "G", "S"]
        )
        if not tax_levels:
            tax_levels = config.get("default_hierarchy_letters", ["D", "C", "G", "S"])

        # Keep only valid taxonomy levels in the correct order
        tax_levels = [level for level in all_tax_levels if level in tax_levels]

        try:
            # Load the Kraken report
            main_dir = config.get("main_dir", "")
            kraken_report_file = os.path.join(
                main_dir, "kraken_cumul/kraken_cumul_report.kreport2"
            )

            if not os.path.exists(kraken_report_file):
                return create_placeholder_sankey("No data available yet")

            # Load the Kraken report
            kraken_df = pd.read_csv(
                kraken_report_file,
                sep="\t",
                header=None,
                names=["%", "cumul_reads", "reads", "rank", "taxid", "name"],
            )

            # Create the Sankey plot data
            sankey_data = create_sankey_data(
                kraken_df, domains, tax_levels, filter_value
            )

            if not sankey_data:
                return create_placeholder_sankey("No data matches the selected filters")

            return sankey_data

        except Exception as e:
            print(f"Error updating Sankey plot: {e}")
            return create_placeholder_sankey(f"Error: {str(e)}")

    @app.callback(
        Output("sankey-export-modal", "is_open"),
        [
            Input("export-sankey-button", "n_clicks"),
            Input("confirm-sankey-export", "n_clicks"),
            Input("cancel-sankey-export", "n_clicks"),
        ],
        State("sankey-export-modal", "is_open"),
    )
    def toggle_sankey_export_modal(
        export_clicks, confirm_clicks, cancel_clicks, is_open
    ):
        """Toggle the Sankey export modal."""
        if export_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        Input("confirm-sankey-export", "n_clicks"),
        [
            State("sankey-export-filename", "value"),
            State("sankey-plot", "figure"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def export_sankey_plot(n_clicks, filename, figure, config):
        """Export the Sankey plot as an HTML file."""
        if not n_clicks or not figure:
            return no_update

        try:
            main_dir = config.get("main_dir", "")
            reports_dir = os.path.join(main_dir, "reports")
            os.makedirs(reports_dir, exist_ok=True)

            # Set a default filename if none provided
            if not filename:
                filename = "sankey_plot"

            # Ensure it has the right extension
            if not filename.endswith(".html"):
                filename += ".html"

            # Save the figure as HTML
            output_path = os.path.join(reports_dir, filename)

            import plotly.io as pio

            pio.write_html(figure, file=output_path, auto_open=False)

            return {
                "title": "Export Successful",
                "message": f"Sankey plot exported to {output_path}",
                "color": "success",
            }

        except Exception as e:
            return {
                "title": "Export Failed",
                "message": f"Failed to export Sankey plot: {str(e)}",
                "color": "danger",
            }


def create_placeholder_sankey(message="Waiting for data"):
    """
    Create a placeholder Sankey plot.

    Args:
        message: Message to display in the plot

    Returns:
        A Go.Figure object with a placeholder Sankey plot
    """
    # Create a minimal Sankey diagram
    placeholder_link = dict(source=[0], target=[1], value=[1])
    placeholder_node = dict(label=[message, ""], pad=25, thickness=10)

    figure = go.Figure(go.Sankey(link=placeholder_link, node=placeholder_node))

    # Update layout
    figure.update_layout(height=600, margin=dict(l=50, r=50, t=50, b=50))

    return figure


def create_sankey_data(kraken_df, domains, tax_levels, top_filter):
    """
    Create Sankey plot data from Kraken report.

    Args:
        kraken_df: DataFrame containing Kraken report
        domains: List of domains to include
        tax_levels: List of taxonomy levels to include
        top_filter: Number of top entities to show at each level

    Returns:
        A Go.Figure object with the Sankey plot
    """
    # Filter by domains
    domain_indices = []
    for domain in domains:
        domain_rows = kraken_df[kraken_df["name"].str.strip() == domain]
        if not domain_rows.empty:
            start_idx = domain_rows.index[0]

            # Find next domain index
            next_domains = kraken_df.iloc[start_idx + 1 :][
                kraken_df["name"].isin(domains)
            ]
            if not next_domains.empty:
                end_idx = next_domains.index[0]
            else:
                end_idx = len(kraken_df)

            domain_indices.extend(range(start_idx, end_idx))

    # Filter dataframe by domains
    domain_df = kraken_df.iloc[domain_indices].copy()

    # Filter by taxonomy levels
    tax_df = domain_df[domain_df["rank"].isin(tax_levels)].copy()

    # Generate node IDs
    node_id = 0
    node_ids = {}
    nodes = []

    # Process levels in the order specified
    for level in tax_levels:
        level_df = tax_df[tax_df["rank"] == level].sort_values("reads", ascending=False)

        # Take top N at this level
        level_df = level_df.head(top_filter)

        for _, row in level_df.iterrows():
            name = row["name"].strip()
            node_ids[name] = node_id
            nodes.append(name)
            node_id += 1

    # Create links
    links = []
    values = []

    # For each level (except the highest), create links to parent level
    for i in range(len(tax_levels) - 1, 0, -1):
        current_level = tax_levels[i]
        parent_level = tax_levels[i - 1]

        # Get nodes at this level
        level_df = (
            tax_df[tax_df["rank"] == current_level]
            .sort_values("reads", ascending=False)
            .head(top_filter)
        )

        for _, row in level_df.iterrows():
            name = row["name"].strip()

            if name not in node_ids:
                continue

            # Find the parent
            path = name.split()
            parent_found = False

            for _, parent_row in tax_df[tax_df["rank"] == parent_level].iterrows():
                parent_name = parent_row["name"].strip()

                # Check if this is a parent (name is a subset of child)
                if parent_name in node_ids and all(
                    term in path for term in parent_name.split()
                ):
                    links.append((node_ids[parent_name], node_ids[name]))
                    values.append(row["reads"])
                    parent_found = True
                    break

            # If no parent found, link to the first node of parent level
            if not parent_found and len(tax_df[tax_df["rank"] == parent_level]) > 0:
                parent_name = (
                    tax_df[tax_df["rank"] == parent_level].iloc[0]["name"].strip()
                )
                if parent_name in node_ids:
                    links.append((node_ids[parent_name], node_ids[name]))
                    values.append(row["reads"])

    # Create figure
    if not links:
        return None

    figure = go.Figure(
        go.Sankey(
            node=dict(
                pad=15,
                thickness=20,
                line=dict(color="black", width=0.5),
                label=nodes,
                color="blue",
            ),
            link=dict(
                source=[link[0] for link in links],
                target=[link[1] for link in links],
                value=values,
            ),
        )
    )

    # Update layout
    figure.update_layout(
        height=600,
        margin=dict(l=50, r=50, t=50, b=50),
        font=dict(size=12),
        title="Taxonomic Classification",
    )

    # Update trace settings
    figure.update_traces(orientation="h", arrangement="freeform", textfont_size=12)

    return figure
