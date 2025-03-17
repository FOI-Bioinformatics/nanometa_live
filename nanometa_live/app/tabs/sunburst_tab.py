"""
Sunburst chart tab callbacks for Nanometa Live.

This module defines the callbacks for the Sunburst chart tab, which displays
hierarchical taxonomic relationships as a sunburst visualization.
"""

import os
import numpy as np
import pandas as pd
from typing import Dict, Any, List

from dash import Dash, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc
import plotly.express as px


def register_sunburst_callbacks(app: Dash):
    """
    Register callbacks for the Sunburst chart tab.

    Args:
        app: Dash application
    """

    @app.callback(
        Output("sunburst-chart", "figure"),
        [Input("update-interval", "n_intervals"), Input("sun-submit", "n_clicks")],
        [
            State("sun-filter-val", "value"),
            State("sun-domains", "value"),
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
    )
    def update_sunburst_chart(
        n_intervals, submit_clicks, min_reads, domains, config, status
    ):
        """Update the Sunburst chart based on filter criteria and latest data."""
        if not config or not status or not status.get("running", False):
            # Return empty chart if not running
            return create_empty_sunburst()

        # Set defaults
        min_reads = min_reads or 10
        domains = domains or ["Bacteria", "Archaea", "Eukaryota", "Viruses"]

        try:
            # Load the Kraken report
            main_dir = config.get("main_dir", "")
            kraken_report_file = os.path.join(
                main_dir, "kraken_cumul/kraken_cumul_report.kreport2"
            )

            if not os.path.exists(kraken_report_file):
                return create_empty_sunburst("No data available yet")

            # Load the data
            kraken_df = pd.read_csv(
                kraken_report_file,
                sep="\t",
                header=None,
                names=["%", "cumul_reads", "reads", "rank", "taxid", "name"],
            )

            # Create sunburst data
            sunburst_data = create_sunburst_data(kraken_df, domains, min_reads, config)

            if sunburst_data is None:
                return create_empty_sunburst("No data matches the selected filters")

            return sunburst_data

        except Exception as e:
            print(f"Error updating Sunburst chart: {e}")
            return create_empty_sunburst(f"Error: {str(e)}")

    @app.callback(
        Output("sunburst-export-modal", "is_open"),
        [
            Input("export-sunburst-button", "n_clicks"),
            Input("confirm-sunburst-export", "n_clicks"),
            Input("cancel-sunburst-export", "n_clicks"),
        ],
        State("sunburst-export-modal", "is_open"),
    )
    def toggle_sunburst_export_modal(
        export_clicks, confirm_clicks, cancel_clicks, is_open
    ):
        """Toggle the Sunburst export modal."""
        if export_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        Input("confirm-sunburst-export", "n_clicks"),
        [
            State("sunburst-export-filename", "value"),
            State("sunburst-chart", "figure"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def export_sunburst_chart(n_clicks, filename, figure, config):
        """Export the Sunburst chart as an HTML file."""
        if not n_clicks or not figure:
            return no_update

        try:
            main_dir = config.get("main_dir", "")
            reports_dir = os.path.join(main_dir, "reports")
            os.makedirs(reports_dir, exist_ok=True)

            # Set a default filename if none provided
            if not filename:
                filename = "sunburst_chart"

            # Ensure it has the right extension
            if not filename.endswith(".html"):
                filename += ".html"

            # Save the figure as HTML
            output_path = os.path.join(reports_dir, filename)

            import plotly.io as pio

            pio.write_html(figure, file=output_path, auto_open=False)

            return {
                "title": "Export Successful",
                "message": f"Sunburst chart exported to {output_path}",
                "color": "success",
            }

        except Exception as e:
            return {
                "title": "Export Failed",
                "message": f"Failed to export Sunburst chart: {str(e)}",
                "color": "danger",
            }


def create_empty_sunburst(message="Waiting for data"):
    """
    Create an empty Sunburst chart.

    Args:
        message: Message to display in the chart

    Returns:
        A px.sunburst figure with a placeholder message
    """
    # Create a minimal dataframe
    df = pd.DataFrame(
        {"Taxon": [message, ""], "Parent": ["", message], "Reads": [1, 0]}
    )

    # Create the sunburst chart
    fig = px.sunburst(
        df,
        names="Taxon",
        parents="Parent",
        values="Reads",
        title="Taxonomic Classification",
    )

    # Update layout
    fig.update_layout(height=700, margin=dict(l=20, r=20, t=60, b=20))

    return fig


def create_sunburst_data(kraken_df, domains, min_reads, config):
    """
    Create Sunburst chart data from Kraken report.

    Args:
        kraken_df: DataFrame containing Kraken report
        domains: List of domains to include
        min_reads: Minimum number of reads for a taxon to be included
        config: Application configuration

    Returns:
        A px.sunburst figure with the Sunburst chart
    """
    # Filter by domains and minimum reads
    domain_filtered_df = filter_by_domains(kraken_df, domains)
    filtered_df = domain_filtered_df[domain_filtered_df["reads"] >= min_reads].copy()

    if filtered_df.empty:
        return None

    # Get taxonomy hierarchy
    tax_levels = config.get(
        "taxonomic_hierarchy_letters", ["D", "P", "C", "O", "F", "G", "S"]
    )

    # Prepare data for sunburst chart
    taxon_data = []  # List of (taxon, parent, reads)
    taxon_parents = {}  # Map of taxon to parent

    # Add root node
    taxon_data.append(("root", "", 0))

    # Process each taxonomy level
    for level_idx, level in enumerate(tax_levels):
        level_df = filtered_df[filtered_df["rank"] == level]

        for _, row in level_df.iterrows():
            taxon = row["name"].strip()
            reads = row["reads"]

            # Find parent
            parent = "root"  # Default parent is root

            if level_idx > 0:
                # Look for parent in previous levels
                parent_found = False

                # Try to find parent by name matching
                taxon_parts = taxon.split()

                for prev_level in tax_levels[:level_idx]:
                    prev_level_df = filtered_df[filtered_df["rank"] == prev_level]

                    for _, prev_row in prev_level_df.iterrows():
                        prev_taxon = prev_row["name"].strip()
                        prev_parts = prev_taxon.split()

                        # Check if previous taxon name is contained in current taxon name
                        if all(part in taxon_parts for part in prev_parts):
                            parent = prev_taxon
                            parent_found = True
                            break

                    if parent_found:
                        break

            # Add to data
            taxon_data.append((taxon, parent, reads))
            taxon_parents[taxon] = parent

    # Create DataFrame for plotting
    sunburst_df = pd.DataFrame(taxon_data, columns=["Taxon", "Parent", "Reads"])

    # Create the sunburst chart
    fig = px.sunburst(
        sunburst_df,
        names="Taxon",
        parents="Parent",
        values="Reads",
        title="Taxonomic Classification",
        color="Reads",
        color_continuous_scale="Viridis",
    )

    # Update layout
    fig.update_layout(height=700, margin=dict(l=20, r=20, t=60, b=20))

    # Update hover template
    fig.update_traces(
        hovertemplate="<b>%{label}</b><br>Reads: %{value}<br>Percentage: %{percentRoot:.2%}"
    )

    return fig


def filter_by_domains(kraken_df, domains):
    """
    Filter Kraken report by domains.

    Args:
        kraken_df: DataFrame containing Kraken report
        domains: List of domains to include

    Returns:
        DataFrame filtered by domains
    """
    # Find domain indices
    domain_indices = []

    for domain in domains:
        domain_rows = kraken_df[kraken_df["name"].str.strip() == domain]

        if not domain_rows.empty:
            start_idx = domain_rows.index[0]

            # Find next domain index or end of dataframe
            next_domains = kraken_df.iloc[start_idx + 1 :][
                kraken_df["name"].isin(domains)
            ]
            if not next_domains.empty:
                end_idx = next_domains.index[0]
            else:
                end_idx = len(kraken_df)

            # Add range of indices for this domain
            domain_indices.extend(range(start_idx, end_idx))

    # Return filtered dataframe
    return kraken_df.iloc[domain_indices].copy()
