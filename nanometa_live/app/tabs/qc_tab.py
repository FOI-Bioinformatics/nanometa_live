"""
Quality Control (QC) tab callbacks for Nanometa Live.

This module defines the callbacks for the QC tab, which displays quality metrics
and processing statistics.
"""

import os
import pandas as pd
import numpy as np
import time
from datetime import datetime
from typing import Dict, Any, List

from dash import Dash, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc
import plotly.express as px


def register_qc_callbacks(app: Dash):
    """
    Register callbacks for the QC tab.

    Args:
        app: Dash application
    """

    @app.callback(
        [
            Output("cumul-reads-graph", "figure"),
            Output("cumul-bp-graph", "figure"),
            Output("reads-graph", "figure"),
            Output("bp-graph", "figure"),
        ],
        Input("update-interval", "n_intervals"),
        [State("app-config", "data"), State("backend-status", "data")],
    )
    def update_qc_plots(n_intervals, config, status):
        """Update the QC plots based on the latest data."""
        if not config or not status or not status.get("running", False):
            # Return empty plots if not running
            empty_figures = [
                px.line(title="Cumulative Reads"),
                px.line(title="Cumulative Base Pairs"),
                px.bar(title="Reads per Batch"),
                px.bar(title="Base Pairs per Batch"),
            ]
            return empty_figures

        try:
            # Load the QC data from the output file
            main_dir = config.get("main_dir", "")
            qc_file = os.path.join(main_dir, "qc_data/cumul_qc.txt")

            if not os.path.exists(qc_file):
                # Return empty plots if QC file doesn't exist
                empty_figures = [
                    px.line(title="Cumulative Reads - No Data"),
                    px.line(title="Cumulative Base Pairs - No Data"),
                    px.bar(title="Reads per Batch - No Data"),
                    px.bar(title="Base Pairs per Batch - No Data"),
                ]
                return empty_figures

            # Load QC data
            qc_df = pd.read_csv(qc_file, names=["Time", "Reads", "Bp"])

            # Sort by time
            qc_df["Time"] = pd.to_datetime(qc_df["Time"])
            qc_df = qc_df.sort_values("Time")

            # Calculate cumulative values
            qc_df["Cumulative Reads"] = qc_df["Reads"].cumsum()
            qc_df["Cumulative Bp"] = qc_df["Bp"].cumsum()

            # Format time for display
            time_for_display = qc_df["Time"].dt.strftime("%Y-%m-%d %H:%M:%S")
            time_for_barplots = qc_df["Time"].dt.strftime("%H:%M:%S")

            # Create plots
            cumul_reads_fig = px.line(
                qc_df,
                x=time_for_display,
                y="Cumulative Reads",
                title="Cumulative Reads Over Time",
            )

            cumul_bp_fig = px.line(
                qc_df,
                x=time_for_display,
                y="Cumulative Bp",
                title="Cumulative Base Pairs Over Time",
            )

            reads_fig = px.bar(
                qc_df, x=time_for_barplots, y="Reads", title="Reads per Batch"
            )

            bp_fig = px.bar(
                qc_df, x=time_for_barplots, y="Bp", title="Base Pairs per Batch"
            )

            # Update layout for better appearance
            for fig in [cumul_reads_fig, cumul_bp_fig, reads_fig, bp_fig]:
                fig.update_layout(height=350, margin=dict(l=50, r=50, t=50, b=50))

            # Update x-axis labels for bar charts
            reads_fig.update_xaxes(title_text="Batch Timestamp")
            bp_fig.update_xaxes(title_text="Batch Timestamp")

            # Make bar charts discrete
            reads_fig.update_xaxes(type="category")
            bp_fig.update_xaxes(type="category")

            return cumul_reads_fig, cumul_bp_fig, reads_fig, bp_fig

        except Exception as e:
            print(f"Error updating QC plots: {e}")
            # Return empty plots on error
            error_figures = [
                px.line(title=f"Error: {str(e)}"),
                px.line(title=f"Error: {str(e)}"),
                px.bar(title=f"Error: {str(e)}"),
                px.bar(title=f"Error: {str(e)}"),
            ]
            return error_figures

    @app.callback(
        [
            Output("qc-reads-pre-filtering", "children"),
            Output("qc-reads-passed", "children"),
            Output("qc-reads-removed", "children"),
            Output("qc-low-quality", "children"),
            Output("qc-too-short", "children"),
            Output("qc-low-complexity", "children"),
            Output("qc-classified-reads", "children"),
            Output("qc-unclassified-reads", "children"),
            Output("qc-processed-files", "children"),
            Output("qc-waiting-files", "children"),
        ],
        Input("update-interval", "n_intervals"),
        [State("app-config", "data"), State("backend-status", "data")],
    )
    def update_qc_stats(n_intervals, config, status):
        """Update the QC statistics based on the latest data."""
        if not config or not status or not status.get("running", False):
            # Return default values if not running
            return [
                "Total reads pre-filtering: 0",
                "Reads that passed filtering: 0",
                "Total reads removed: 0",
                "Too low quality: 0 (0%)",
                "Too short: 0 (0%)",
                "Too low complexity: 0 (0%)",
                "Classified reads: 0 (0%)",
                "Unclassified reads: 0 (0%)",
                "Files processed: 0",
                "Files awaiting processing: 0",
            ]

        try:
            # Load necessary files
            main_dir = config.get("main_dir", "")
            qc_file = os.path.join(main_dir, "qc_data/cumul_qc.txt")
            fastp_file = os.path.join(main_dir, "fastp_reports/compiled_fastp.txt")
            kraken_file = os.path.join(
                main_dir, "kraken_cumul/kraken_cumul_report.kreport2"
            )
            nanopore_dir = config.get("nanopore_output_directory", "")

            # Initialize variables
            tot_reads_pre_filt = 0
            tot_passed_reads = 0
            tot_low_quality_reads = 0
            tot_too_many_N_reads = 0
            tot_too_short_reads = 0
            tot_removed_reads = 0

            processed_files = 0
            waiting_files = 0

            # Get QC data if file exists
            if os.path.exists(qc_file):
                qc_df = pd.read_csv(qc_file, names=["Time", "Reads", "Bp"])
                tot_reads_pre_filt = qc_df["Reads"].sum()
                processed_files = len(qc_df)

            # Get filtering stats if file exists
            if os.path.exists(fastp_file):
                fastp_df = pd.read_csv(
                    fastp_file,
                    names=[
                        "passed_filter_reads",
                        "low_quality_reads",
                        "too_many_N_reads",
                        "too_short_reads",
                    ],
                )

                tot_passed_reads = fastp_df["passed_filter_reads"].sum()
                tot_low_quality_reads = fastp_df["low_quality_reads"].sum()
                tot_too_many_N_reads = fastp_df["too_many_N_reads"].sum()
                tot_too_short_reads = fastp_df["too_short_reads"].sum()
                tot_removed_reads = (
                    tot_low_quality_reads + tot_too_many_N_reads + tot_too_short_reads
                )

            # Get classification stats if file exists
            classified_reads = 0
            unclassified_reads = 0
            if os.path.exists(kraken_file):
                kraken_df = pd.read_csv(
                    kraken_file,
                    sep="\t",
                    header=None,
                    names=["%", "cumul_reads", "reads", "rank", "taxid", "name"],
                )

                # Unclassified reads are in the first row (taxid 0)
                unclassified_row = kraken_df[kraken_df["taxid"] == 0]
                if not unclassified_row.empty:
                    unclassified_reads = int(unclassified_row.iloc[0]["reads"])

                # Classified reads are the sum of all other rows
                classified_reads = int(kraken_df["reads"].sum() - unclassified_reads)

            # Get waiting files
            if os.path.exists(nanopore_dir):
                all_files = [
                    f
                    for f in os.listdir(nanopore_dir)
                    if f.endswith((".fastq", ".fastq.gz"))
                ]
                waiting_files = len(all_files) - processed_files
                if waiting_files < 0:
                    waiting_files = 0

            # Calculate percentages
            percentage_passed = 0
            percentage_removed = 0
            if tot_reads_pre_filt > 0:
                percentage_passed = round(
                    (tot_passed_reads * 100) / tot_reads_pre_filt, 1
                )
                percentage_removed = round(
                    (tot_removed_reads * 100) / tot_reads_pre_filt, 1
                )

            percentage_low_quality = 0
            percentage_too_many_N = 0
            percentage_too_short = 0
            if tot_removed_reads > 0:
                percentage_low_quality = round(
                    (tot_low_quality_reads * 100) / tot_removed_reads, 1
                )
                percentage_too_many_N = round(
                    (tot_too_many_N_reads * 100) / tot_removed_reads, 1
                )
                percentage_too_short = round(
                    (tot_too_short_reads * 100) / tot_removed_reads, 1
                )

            percentage_classified = 0
            percentage_unclassified = 0
            total_kraken_reads = classified_reads + unclassified_reads
            if total_kraken_reads > 0:
                percentage_classified = round(
                    (classified_reads * 100) / total_kraken_reads, 1
                )
                percentage_unclassified = round(
                    (unclassified_reads * 100) / total_kraken_reads, 1
                )

            # Format output strings
            reads_pre_filtering = f"Total reads pre-filtering: {tot_reads_pre_filt:,}"
            reads_passed = f"Reads that passed filtering: {tot_passed_reads:,} ({percentage_passed}%)"
            reads_removed = (
                f"Total reads removed: {tot_removed_reads:,} ({percentage_removed}%)"
            )

            low_quality = f"Too low quality: {tot_low_quality_reads:,} ({percentage_low_quality}%)"
            too_short = f"Too short: {tot_too_short_reads:,} ({percentage_too_short}%)"
            low_complexity = f"Too low complexity: {tot_too_many_N_reads:,} ({percentage_too_many_N}%)"

            classified = (
                f"Classified reads: {classified_reads:,} ({percentage_classified}%)"
            )
            unclassified = f"Unclassified reads: {unclassified_reads:,} ({percentage_unclassified}%)"

            processed = f"Files processed: {processed_files:,}"
            waiting = f"Files awaiting processing: {waiting_files:,}"

            return [
                reads_pre_filtering,
                reads_passed,
                reads_removed,
                low_quality,
                too_short,
                low_complexity,
                classified,
                unclassified,
                processed,
                waiting,
            ]

        except Exception as e:
            print(f"Error updating QC stats: {e}")
            # Return default values on error
            return [
                f"Error: {str(e)}",
                "Reads that passed filtering: 0",
                "Total reads removed: 0",
                "Too low quality: 0 (0%)",
                "Too short: 0 (0%)",
                "Too low complexity: 0 (0%)",
                "Classified reads: 0 (0%)",
                "Unclassified reads: 0 (0%)",
                "Files processed: 0",
                "Files awaiting processing: 0",
            ]

    @app.callback(
        Output("qc-help-modal", "is_open"),
        [Input("qc-help-button", "n_clicks"), Input("close-qc-help", "n_clicks")],
        State("qc-help-modal", "is_open"),
    )
    def toggle_qc_help_modal(help_clicks, close_clicks, is_open):
        """Toggle the QC help modal."""
        if help_clicks or close_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("qc-export-modal", "is_open"),
        [
            Input("export-qc-button", "n_clicks"),
            Input("confirm-qc-export", "n_clicks"),
            Input("cancel-qc-export", "n_clicks"),
        ],
        State("qc-export-modal", "is_open"),
    )
    def toggle_qc_export_modal(export_clicks, confirm_clicks, cancel_clicks, is_open):
        """Toggle the QC export modal."""
        if export_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        Input("confirm-qc-export", "n_clicks"),
        [
            State("qc-export-dir", "value"),
            State("qc-export-filename", "value"),
            State("app-config", "data"),
            State("cumul-reads-graph", "figure"),
            State("cumul-bp-graph", "figure"),
            State("reads-graph", "figure"),
            State("bp-graph", "figure"),
        ],
        prevent_initial_call=True,
    )
    def export_qc_plots(n_clicks, export_dir, export_filename, config, *figures):
        """Export QC plots to image files."""
        if not n_clicks:
            return no_update

        try:
            # Determine export directory
            if export_dir:
                export_path = export_dir
            else:
                main_dir = config.get("main_dir", "")
                export_path = os.path.join(main_dir, "reports")

            # Create directory if it doesn't exist
            os.makedirs(export_path, exist_ok=True)

            # Determine base filename
            base_filename = export_filename or "qc_plots"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Export each figure
            figure_names = ["cumul_reads", "cumul_bp", "batch_reads", "batch_bp"]
            export_files = []

            for i, fig in enumerate(figures):
                if fig:
                    filename = f"{base_filename}_{figure_names[i]}_{timestamp}.png"
                    filepath = os.path.join(export_path, filename)

                    import plotly.io as pio

                    pio.write_image(fig, filepath)
                    export_files.append(filepath)

            return {
                "title": "Export Successful",
                "message": f"Exported {len(export_files)} plots to {export_path}",
                "color": "success",
            }

        except Exception as e:
            return {
                "title": "Export Failed",
                "message": f"Failed to export plots: {str(e)}",
                "color": "danger",
            }
