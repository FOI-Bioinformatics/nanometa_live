"""
Main results tab callbacks for Nanometa Live.

This module defines the callbacks for the main results tab, which displays
the species of interest and top matches from the analysis.
"""

import os
import pandas as pd
import numpy as np
import json
import plotly.express as px
from typing import Dict, Any, List

from dash import Dash, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc


def register_main_callbacks(app: Dash):
    """
    Register callbacks for the main results tab.

    Args:
        app: Dash application
    """

    @app.callback(
        [
            Output("species-table", "data"),
            Output("species-table", "columns"),
            Output("species-table", "style_data_conditional"),
            Output("species-plot", "figure"),
        ],
        [
            Input("update-interval", "n_intervals"),
            Input("apply-species-settings", "n_clicks"),
        ],
        [
            State("species-threshold-input", "value"),
            State("show-validation-input", "value"),
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
    )
    def update_species_of_interest(
        n_intervals, apply_clicks, threshold, show_validation, config, status
    ):
        """Update the species of interest table and plot."""
        if not config or not status or not status.get("running", False):
            # Return empty data if not running
            return [], [], [], px.bar(title="Species of Interest")

        # Set threshold and validation options
        threshold = threshold or 100
        show_validation = show_validation and "true" in show_validation

        try:
            # Load the species data from the output files
            main_dir = config.get("main_dir", "")
            kraken_report_file = os.path.join(
                main_dir, "kraken_cumul/kraken_cumul_report.kreport2"
            )
            blast_dir = os.path.join(main_dir, "blast_result_files")

            # Only proceed if files exist
            if not os.path.exists(kraken_report_file):
                return [], [], [], px.bar(title="Species of Interest - No Data")

            # Load the Kraken report
            kraken_df = pd.read_csv(
                kraken_report_file,
                sep="\t",
                header=None,
                names=["%", "cumul_reads", "reads", "rank", "taxid", "name"],
            )

            # Extract species of interest
            species_of_interest = []
            for species in config.get("species_of_interest", []):
                species_name = species.get("name", "")
                taxid = species.get("taxid", "")
                if species_name and taxid:
                    species_of_interest.append((species_name, taxid))

            # Filter Kraken report for species of interest
            result_rows = []
            for _, taxid in species_of_interest:
                matches = kraken_df[kraken_df["taxid"] == taxid]
                if not matches.empty:
                    row = matches.iloc[0]
                    result_rows.append(
                        {
                            "Name": row["name"].strip(),
                            "Tax ID": row["taxid"],
                            "Reads": int(row["reads"]),
                            "Percent": float(row["%"]),
                            "Color": (
                                "Red" if int(row["reads"]) > threshold else "Green"
                            ),
                        }
                    )
                else:
                    # Species not found in data
                    for species_name, species_taxid in species_of_interest:
                        if species_taxid == taxid:
                            result_rows.append(
                                {
                                    "Name": species_name,
                                    "Tax ID": taxid,
                                    "Reads": 0,
                                    "Percent": 0.0,
                                    "Color": "Green",
                                }
                            )

            # Add validation data if requested
            if show_validation and os.path.exists(blast_dir):
                for i, row in enumerate(result_rows):
                    taxid = row["Tax ID"]
                    blast_file = os.path.join(blast_dir, f"{taxid}.txt")
                    if os.path.exists(blast_file):
                        # Count unique sequences in BLAST results
                        try:
                            blast_df = pd.read_csv(blast_file, sep="\t", header=None)
                            validated_reads = blast_df[0].nunique()
                            result_rows[i]["Validated"] = validated_reads
                        except Exception as e:
                            result_rows[i]["Validated"] = 0
                    else:
                        result_rows[i]["Validated"] = 0

            # Sort by read count
            result_rows = sorted(result_rows, key=lambda x: x["Reads"], reverse=True)

            # Generate table data and columns
            table_data = result_rows
            columns = [
                {"name": "Name", "id": "Name"},
                {"name": "Tax ID", "id": "Tax ID"},
                {"name": "Reads", "id": "Reads"},
            ]

            if show_validation:
                columns.append({"name": "Validated", "id": "Validated"})

            # Generate conditional styling
            style_conditional = [
                {
                    "if": {"filter_query": f"{{Reads}} > {threshold}"},
                    "backgroundColor": "#ffcccc",
                }
            ]

            # Generate plot
            plot_df = pd.DataFrame(result_rows)
            if not plot_df.empty:
                fig = px.bar(
                    plot_df,
                    x="Name",
                    y="Reads",
                    color="Color",
                    title="Species of Interest",
                    labels={"Reads": "Number of Reads", "Name": "Species"},
                    color_discrete_map={"Red": "red", "Green": "green"},
                )

                # Format the plot
                fig.update_layout(showlegend=False, xaxis_tickangle=-45, height=400)

                # Add validated reads if available
                if show_validation and "Validated" in plot_df.columns:
                    fig.add_trace(
                        px.bar(
                            plot_df,
                            x="Name",
                            y="Validated",
                            color_discrete_sequence=["blue"],
                        ).data[0]
                    )
                    fig.update_layout(barmode="group")
            else:
                fig = px.bar(title="Species of Interest - No Data")

            return table_data, columns, style_conditional, fig

        except Exception as e:
            print(f"Error updating species of interest: {e}")
            return [], [], [], px.bar(title=f"Error: {str(e)}")

    @app.callback(
        [Output("top-table", "data"), Output("top-table", "columns")],
        [
            Input("update-interval", "n_intervals"),
            Input("apply-top-settings", "n_clicks"),
        ],
        [
            State("top-entries-input", "value"),
            State("tax-level-input", "value"),
            State("domains-input", "value"),
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
    )
    def update_top_matches(
        n_intervals, apply_clicks, num_entries, tax_levels, domains, config, status
    ):
        """Update the top matches table."""
        if not config or not status or not status.get("running", False):
            # Return empty data if not running
            return [], []

        # Set defaults
        num_entries = num_entries or 20
        tax_levels = tax_levels or ["S"]
        domains = domains or ["Bacteria", "Archaea", "Eukaryota", "Viruses"]

        try:
            # Load the data from the Kraken report
            main_dir = config.get("main_dir", "")
            kraken_report_file = os.path.join(
                main_dir, "kraken_cumul/kraken_cumul_report.kreport2"
            )

            if not os.path.exists(kraken_report_file):
                return [], []

            # Load the Kraken report
            kraken_df = pd.read_csv(
                kraken_report_file,
                sep="\t",
                header=None,
                names=["%", "cumul_reads", "reads", "rank", "taxid", "name"],
            )

            # Filter by domains
            domain_rows = []
            for domain in domains:
                domain_data = kraken_df[kraken_df["name"].str.strip() == domain]
                if not domain_data.empty:
                    domain_row = domain_data.iloc[0]
                    domain_idx = domain_row.name

                    # Find next domain's index
                    next_domains = kraken_df.iloc[domain_idx + 1 :][
                        kraken_df["name"].isin(domains)
                    ]
                    if not next_domains.empty:
                        next_domain_idx = next_domains.iloc[0].name
                    else:
                        next_domain_idx = len(kraken_df)

                    # Get all rows for this domain
                    domain_rows.extend(range(domain_idx, next_domain_idx))

            # Filter the dataframe
            filtered_df = kraken_df.iloc[domain_rows]

            # Filter by taxonomy levels
            filtered_df = filtered_df[filtered_df["rank"].isin(tax_levels)]

            # Sort by reads
            filtered_df = filtered_df.sort_values("reads", ascending=False)

            # Take top entries
            top_df = filtered_df.head(num_entries).copy()

            # Add index column
            top_df["Index"] = range(1, len(top_df) + 1)

            # Clean up name column (remove leading spaces)
            top_df["name"] = top_df["name"].str.strip()

            # Generate table data
            result_data = []
            for _, row in top_df.iterrows():
                result_data.append(
                    {
                        "Index": int(row["Index"]),
                        "Name": row["name"],
                        "Tax ID": row["taxid"],
                        "Tax Rank": row["rank"],
                        "Reads": int(row["reads"]),
                    }
                )

            # Define columns
            columns = [
                {"name": "Index", "id": "Index"},
                {"name": "Name", "id": "Name"},
                {"name": "Tax ID", "id": "Tax ID"},
                {"name": "Tax Rank", "id": "Tax Rank"},
                {"name": "Reads", "id": "Reads"},
            ]

            return result_data, columns

        except Exception as e:
            print(f"Error updating top matches: {e}")
            return [], []

    # Export modals and functionality
    @app.callback(
        Output("species-export-modal", "is_open"),
        [
            Input("export-species-button", "n_clicks"),
            Input("confirm-species-export", "n_clicks"),
            Input("cancel-species-export", "n_clicks"),
        ],
        State("species-export-modal", "is_open"),
    )
    def toggle_species_export_modal(
        export_clicks, confirm_clicks, cancel_clicks, is_open
    ):
        """Toggle the species export modal."""
        if export_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("top-export-modal", "is_open"),
        [
            Input("export-top-button", "n_clicks"),
            Input("confirm-top-export", "n_clicks"),
            Input("cancel-top-export", "n_clicks"),
        ],
        State("top-export-modal", "is_open"),
    )
    def toggle_top_export_modal(export_clicks, confirm_clicks, cancel_clicks, is_open):
        """Toggle the top matches export modal."""
        if export_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        [
            Input("confirm-species-export", "n_clicks"),
            Input("confirm-top-export", "n_clicks"),
        ],
        [
            State("species-export-filename", "value"),
            State("top-export-filename", "value"),
            State("species-table", "data"),
            State("top-table", "data"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def export_data(
        species_clicks,
        top_clicks,
        species_filename,
        top_filename,
        species_data,
        top_data,
        config,
    ):
        """Export data to CSV files."""
        if not ctx.triggered:
            return no_update

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        try:
            main_dir = config.get("main_dir", "")
            reports_dir = os.path.join(main_dir, "reports")
            os.makedirs(reports_dir, exist_ok=True)

            if (
                trigger_id == "confirm-species-export"
                and species_clicks
                and species_data
            ):
                # Export species data
                if not species_filename:
                    species_filename = "species_of_interest"

                if not species_filename.endswith(".csv"):
                    species_filename += ".csv"

                species_path = os.path.join(reports_dir, species_filename)
                pd.DataFrame(species_data).to_csv(species_path, index=False)

                return {
                    "title": "Export Successful",
                    "message": f"Species data exported to {species_path}",
                    "color": "success",
                }

            elif trigger_id == "confirm-top-export" and top_clicks and top_data:
                # Export top matches data
                if not top_filename:
                    top_filename = "top_matches"

                if not top_filename.endswith(".csv"):
                    top_filename += ".csv"

                top_path = os.path.join(reports_dir, top_filename)
                pd.DataFrame(top_data).to_csv(top_path, index=False)

                return {
                    "title": "Export Successful",
                    "message": f"Top matches data exported to {top_path}",
                    "color": "success",
                }

            return no_update

        except Exception as e:
            return {
                "title": "Export Failed",
                "message": f"Failed to export data: {str(e)}",
                "color": "danger",
            }
