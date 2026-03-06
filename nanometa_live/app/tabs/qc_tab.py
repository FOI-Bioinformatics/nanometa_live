"""
Quality Control (QC) tab callbacks for Nanometa Live v2.0.

This module defines the callbacks for the QC tab, which displays quality metrics
and processing statistics with multi-sample/barcode support.
"""

import os
import logging
import pandas as pd
import numpy as np
import time
import json
import glob
from datetime import datetime
from typing import Dict, Any, List

from dash import Dash, Input, Output, State, callback, ctx, no_update, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.express as px

from nanometa_live.core.utils.data_loaders import (
    load_fastp_data,
    load_kraken_data,
    get_sample_statistics_summary,
    get_qc_stats,
    load_seqkit_stats
)
from nanometa_live.app.components.organism_components import (
    FilteringBreakdownVisual,
    BaseQualityCard,
    ReadStatisticsCard
)
from nanometa_live.app.components.modern_components import EmptyStateMessage
from nanometa_live.app.utils.callback_helpers import (
    validate_config_and_get_main_dir,
    log_callback_error,
    get_classification_stats,
)


def register_qc_callbacks(app: Dash):
    """
    Register callbacks for the QC tab.

    Args:
        app: Dash application
    """

    # =========================================================================
    # CENTRALIZED QC DATA LOADING
    # This callback loads all QC data once per interval cycle and stores it
    # in qc-data-cache. Other callbacks should read from this cache.
    # =========================================================================

    @app.callback(
        Output("qc-data-cache", "data"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
        prevent_initial_call=False,
    )
    def load_qc_data_cache(n_intervals, selected_sample, config, status, active_tab, data_fingerprint):
        """
        Load all QC data once per interval and cache it.

        This prevents multiple callbacks from redundantly loading the same data.
        Returns a dict with kraken_df and fastp_data for the selected sample.
        """
        # Tab skip guard - skip interval updates when tab is not active
        if ctx.triggered_id == 'update-interval' and active_tab != 'qc-tab':
            raise PreventUpdate
        # Fingerprint guard - skip if data unchanged on interval tick
        if ctx.triggered_id == 'update-interval' and not hasattr(load_qc_data_cache, '_last_fp'):
            load_qc_data_cache._last_fp = None
        if ctx.triggered_id == 'update-interval':
            if data_fingerprint and data_fingerprint == load_qc_data_cache._last_fp:
                raise PreventUpdate
            load_qc_data_cache._last_fp = data_fingerprint

        cache_data = {
            "loaded": False,
            "sample": selected_sample,
            "kraken_data": None,
            "fastp_data": None,
            "seqkit_data": None,
            "timestamp": time.time(),
        }

        # Validate config and get output directory using centralized helper
        main_dir = validate_config_and_get_main_dir(config)
        if not main_dir:
            return cache_data

        try:
            # Load Kraken2 data
            kraken_df = load_kraken_data(main_dir, selected_sample)
            if not kraken_df.empty:
                # Convert to dict for JSON serialization in store
                cache_data["kraken_data"] = kraken_df.to_dict("records")

            # Load FASTP data
            fastp_data = load_fastp_data(main_dir, selected_sample)
            if fastp_data:
                cache_data["fastp_data"] = fastp_data

            # Load SeqKit stats if available
            try:
                seqkit_data = load_seqkit_stats(main_dir, selected_sample)
                if seqkit_data:
                    cache_data["seqkit_data"] = seqkit_data
            except Exception:
                pass  # SeqKit stats are optional

            cache_data["loaded"] = True

        except Exception as e:
            logging.error(f"Error loading QC data cache: {e}")

        return cache_data

    # =========================================================================
    # QC PLOTS (Processing Graphs)
    # =========================================================================

    @app.callback(
        [
            Output("cumul-reads-graph", "figure"),
            Output("cumul-bp-graph", "figure"),
            Output("reads-graph", "figure"),
            Output("bp-graph", "figure"),
        ],
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
    )
    def update_qc_plots(n_intervals, selected_sample, config, status, active_tab, data_fingerprint):
        """
        Update the QC plots based on actual processed data from FASTP/Kraken2.

        Shows actual reads and base pairs that passed through the pipeline,
        ordered by file modification time to show processing progress.
        """
        # Tab + fingerprint guard
        if ctx.triggered_id == 'update-interval':
            if active_tab != 'qc-tab':
                raise PreventUpdate
            if not hasattr(update_qc_plots, '_last_fp'):
                update_qc_plots._last_fp = None
            if data_fingerprint and data_fingerprint == update_qc_plots._last_fp:
                raise PreventUpdate
            update_qc_plots._last_fp = data_fingerprint

        # Default empty plots
        empty_figures = [
            px.line(title="Cumulative Reads"),
            px.line(title="Cumulative Base Pairs"),
            px.bar(title="Reads per Sample"),
            px.bar(title="Base Pairs per Sample"),
        ]

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return empty_figures

        try:
            fastp_dir = os.path.join(main_dir, "fastp")
            seqkit_dir = os.path.join(main_dir, "seqkit")
            kraken_dir = os.path.join(main_dir, "kraken2")

            # Collect actual processed data from FASTP, seqkit, or Kraken2
            sample_data = []

            # Try FASTP first (most detailed)
            if os.path.exists(fastp_dir):
                fastp_files = glob.glob(os.path.join(fastp_dir, "*.fastp.json"))
                for fastp_file in fastp_files:
                    try:
                        with open(fastp_file, 'r') as f:
                            fastp_data = json.load(f)
                            summary = fastp_data.get("summary", {})
                            after = summary.get("after_filtering", {})

                            reads = after.get("total_reads", 0)
                            bases = after.get("total_bases", 0)

                            if reads > 0:
                                # Get file modification time for ordering
                                mtime = os.path.getmtime(fastp_file)
                                sample_name = os.path.basename(fastp_file).replace(".fastp.json", "")

                                sample_data.append({
                                    "Sample": sample_name,
                                    "Time": datetime.fromtimestamp(mtime),
                                    "Reads": reads,
                                    "Bp": bases
                                })
                    except (json.JSONDecodeError, IOError, KeyError) as e:
                        logging.debug(f"Error reading FASTP file {fastp_file}: {e}")
                        continue

            # Fallback to seqkit stats if no FASTP (chopper QC tool)
            if not sample_data and os.path.exists(seqkit_dir):
                seqkit_df = load_seqkit_stats(main_dir)
                if not seqkit_df.empty and 'num_seqs' in seqkit_df.columns:
                    for _, row in seqkit_df.iterrows():
                        sample_name = row.get('file', 'unknown')
                        if isinstance(sample_name, str):
                            sample_name = os.path.basename(sample_name).split('.')[0]
                        reads = int(row.get('num_seqs', 0))
                        bases = int(row.get('sum_len', 0))

                        if reads > 0:
                            sample_data.append({
                                "Sample": str(sample_name),
                                "Time": datetime.now(),  # No mtime available
                                "Reads": reads,
                                "Bp": bases
                            })

            # Last resort: use Kraken2 reports
            if not sample_data and os.path.exists(kraken_dir):
                kreport_files = glob.glob(os.path.join(kraken_dir, "*.cumulative.kraken2.report.txt"))
                if not kreport_files:
                    kreport_files = glob.glob(os.path.join(kraken_dir, "*.kraken2.report.txt"))
                if not kreport_files:
                    kreport_files = glob.glob(os.path.join(kraken_dir, "*.kreport2.txt"))

                for kreport_file in kreport_files:
                    try:
                        kraken_df = pd.read_csv(
                            kreport_file, sep="\t", header=None,
                            names=["%", "cumul_reads", "reads", "rank", "taxid", "name"]
                        )
                        # Total reads = root + unclassified
                        root = kraken_df[kraken_df['name'].str.strip() == 'root']
                        unclass = kraken_df[kraken_df['name'].str.strip() == 'unclassified']

                        classified = int(root.iloc[0]['cumul_reads']) if not root.empty else 0
                        unclassified = int(unclass.iloc[0]['cumul_reads']) if not unclass.empty else 0
                        total_reads = classified + unclassified

                        if total_reads > 0:
                            mtime = os.path.getmtime(kreport_file)
                            sample_name = os.path.basename(kreport_file).replace(".cumulative.kraken2.report.txt", "").replace(".kraken2.report.txt", "").replace(".kreport2.txt", "")

                            sample_data.append({
                                "Sample": sample_name,
                                "Time": datetime.fromtimestamp(mtime),
                                "Reads": total_reads,
                                "Bp": total_reads * 1500  # Estimate bp
                            })
                    except Exception as e:
                        logging.debug(f"Error reading Kraken report {kreport_file}: {e}")
                        continue

            if not sample_data:
                message = "No processed data available.<br>Plots will appear once FASTP or Kraken2 analysis is complete."
                empty_figures = [
                    px.line(title="Cumulative Reads").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
                    px.line(title="Cumulative Base Pairs").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
                    px.bar(title="Reads per Sample").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
                    px.bar(title="Base Pairs per Sample").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
                ]
                return empty_figures

            # Create DataFrame and sort by time
            qc_df = pd.DataFrame(sample_data)
            qc_df = qc_df.sort_values("Time")

            # Calculate cumulative values
            qc_df["Cumulative Reads"] = qc_df["Reads"].cumsum()
            qc_df["Cumulative Bp"] = qc_df["Bp"].cumsum()

            # Format time for display
            time_for_display = qc_df["Time"].dt.strftime("%Y-%m-%d %H:%M:%S")

            # Shared Plotly layout for consistent QC chart styling
            _qc_layout = dict(
                template="plotly_white",
                height=350,
                margin=dict(l=50, r=30, t=50, b=60),
                font=dict(family="Arial, sans-serif", size=12),
                title_font=dict(size=14, color="#374151"),
                hovermode="x unified",
            )

            # Cumulative reads line chart
            cumul_reads_fig = px.line(
                qc_df,
                x=time_for_display,
                y="Cumulative Reads",
                title="Cumulative Processed Reads",
            )
            cumul_reads_fig.update_traces(
                line=dict(color="#0d6efd", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(13, 110, 253, 0.08)",
                hovertemplate="Reads: %{y:,.0f}<extra></extra>",
            )
            cumul_reads_fig.update_layout(
                **_qc_layout,
                xaxis_title="Processing Time",
                yaxis_title="Cumulative Reads",
                yaxis_tickformat=",",
            )

            # Cumulative base pairs line chart
            cumul_bp_fig = px.line(
                qc_df,
                x=time_for_display,
                y="Cumulative Bp",
                title="Cumulative Processed Base Pairs",
            )
            cumul_bp_fig.update_traces(
                line=dict(color="#198754", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(25, 135, 84, 0.08)",
                hovertemplate="Bases: %{y:,.0f}<extra></extra>",
            )
            cumul_bp_fig.update_layout(
                **_qc_layout,
                xaxis_title="Processing Time",
                yaxis_title="Cumulative Base Pairs",
                yaxis_tickformat=",",
            )

            # Reads per sample bar chart
            reads_fig = px.bar(
                qc_df, x="Sample", y="Reads", title="Processed Reads per Sample"
            )
            reads_fig.update_traces(
                marker_color="#0d6efd",
                marker_line_width=0,
                hovertemplate="<b>%{x}</b><br>Reads: %{y:,.0f}<extra></extra>",
            )
            reads_fig.update_layout(
                **_qc_layout,
                xaxis_title="Sample",
                yaxis_title="Reads",
                yaxis_tickformat=",",
                xaxis_type="category",
                bargap=0.3,
            )

            # Base pairs per sample bar chart
            bp_fig = px.bar(
                qc_df, x="Sample", y="Bp", title="Processed Base Pairs per Sample"
            )
            bp_fig.update_traces(
                marker_color="#198754",
                marker_line_width=0,
                hovertemplate="<b>%{x}</b><br>Base pairs: %{y:,.0f}<extra></extra>",
            )
            bp_fig.update_layout(
                **_qc_layout,
                xaxis_title="Sample",
                yaxis_title="Base Pairs",
                yaxis_tickformat=",",
                xaxis_type="category",
                bargap=0.3,
            )

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
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
    )
    def update_qc_stats(n_intervals, selected_sample, config, status, active_tab, data_fingerprint):
        """Update the QC statistics based on the latest data."""
        # Tab + fingerprint guard
        if ctx.triggered_id == 'update-interval':
            if active_tab != 'qc-tab':
                raise PreventUpdate
            if not hasattr(update_qc_stats, '_last_fp'):
                update_qc_stats._last_fp = None
            if data_fingerprint and data_fingerprint == update_qc_stats._last_fp:
                raise PreventUpdate
            update_qc_stats._last_fp = data_fingerprint
        # Default values for when no data is available
        default_values = [
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

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return default_values

        try:
            # Load necessary files from nanometanf structure
            batch_stats_dir = os.path.join(main_dir, "realtime_batch_stats")
            fastp_dir = os.path.join(main_dir, "fastp")
            kraken_dir = os.path.join(main_dir, "kraken2")
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

            # Get batch statistics for read counts
            if os.path.exists(batch_stats_dir):
                # Support both naming conventions
                batch_files = glob.glob(os.path.join(batch_stats_dir, "batch_*_snapshot.json"))
                if not batch_files:
                    batch_files = glob.glob(os.path.join(batch_stats_dir, "batch_*.json"))
                # Exclude non-JSON files
                batch_files = [f for f in batch_files if f.endswith('.json')]

                for batch_file in batch_files:
                    try:
                        with open(batch_file, 'r') as f:
                            batch = json.load(f)
                            # Support both new nested format and legacy flat format
                            if "batch_info" in batch:
                                file_stats = batch.get("file_statistics", {})
                                tot_reads_pre_filt += file_stats.get("estimated_total_reads", 0)
                                processed_files += file_stats.get("file_count", 0)
                            else:
                                tot_reads_pre_filt += batch.get("reads_in_batch", 0)
                                processed_files += batch.get("files_in_batch", 0)
                    except (json.JSONDecodeError, IOError, KeyError) as e:
                        logging.debug(f"Error reading batch file {batch_file}: {e}")
                        continue

            # Get filtering stats from FASTP (sample-filtered) or seqkit if chopper is used
            fastp_found = False
            fastp_stats = load_fastp_data(main_dir, selected_sample)
            if fastp_stats.get('total_reads_after', 0) > 0:
                fastp_found = True
                tot_passed_reads = fastp_stats['total_reads_after']
                tot_reads_pre_filt = fastp_stats['total_reads_before']
                tot_low_quality_reads = fastp_stats['low_quality']
                tot_too_many_N_reads = fastp_stats['too_many_N']
                tot_too_short_reads = fastp_stats['too_short']
                tot_removed_reads = tot_low_quality_reads + tot_too_many_N_reads + tot_too_short_reads

            # Fallback to seqkit stats if FASTP not found (used with chopper QC tool)
            if not fastp_found:
                seqkit_dir = os.path.join(main_dir, "seqkit")
                if os.path.exists(seqkit_dir):
                    seqkit_df = load_seqkit_stats(main_dir, selected_sample)
                    if not seqkit_df.empty and 'num_seqs' in seqkit_df.columns:
                        tot_passed_reads = int(seqkit_df['num_seqs'].sum())
                        # Use Kraken2 for pre-filter baseline (total classified + unclassified)
                        # This ensures consistent data source with seqkit post-filter reads
                        kraken_df = load_kraken_data(main_dir, selected_sample)
                        if not kraken_df.empty:
                            root = kraken_df[kraken_df['name'].str.strip() == 'root']
                            unclassified = kraken_df[kraken_df['name'].str.strip() == 'unclassified']
                            classified_total = int(root.iloc[0]['cumul_reads']) if not root.empty else 0
                            unclassified_total = int(unclassified.iloc[0]['cumul_reads']) if not unclassified.empty else 0
                            tot_reads_pre_filt = classified_total + unclassified_total

                            # Estimate removal reasons (chopper doesn't provide breakdown)
                            # Use same estimation as FilteringBreakdownVisual for consistency
                            if tot_reads_pre_filt > 0:
                                tot_removed_reads = max(0, tot_reads_pre_filt - tot_passed_reads)
                                # Approximate distribution: 60% quality, 30% length, 10% complexity
                                tot_low_quality_reads = int(tot_removed_reads * 0.6)
                                tot_too_short_reads = int(tot_removed_reads * 0.3)
                                tot_too_many_N_reads = tot_removed_reads - tot_low_quality_reads - tot_too_short_reads

            # Get classification stats from Kraken2 (sample-filtered)
            classified_reads = 0
            unclassified_reads = 0
            kraken_df = load_kraken_data(main_dir, selected_sample)
            if not kraken_df.empty:
                classified_reads, unclassified_reads, _ = get_classification_stats(kraken_df)

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

            # When post-filter count exceeds pre-filter baseline (seqkit may count
            # slightly more reads than kraken2 processed), adjust to avoid impossible %
            if tot_passed_reads > tot_reads_pre_filt and tot_reads_pre_filt > 0:
                tot_reads_pre_filt = tot_passed_reads
                tot_removed_reads = 0
            percentage_passed = 0
            percentage_removed = 0
            if tot_reads_pre_filt > 0:
                percentage_passed = min(round(
                    (tot_passed_reads * 100) / tot_reads_pre_filt, 1
                ), 100.0)
                percentage_removed = max(round(
                    (tot_removed_reads * 100) / tot_reads_pre_filt, 1
                ), 0.0)

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
            Input("export-qc-plots", "n_clicks"),
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
                main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
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

    @app.callback(
        Output("per-sample-table", "data"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
    )
    def update_per_sample_table(n_intervals, selected_sample, config, status, active_tab, data_fingerprint):
        """
        Update the per-sample breakdown table with statistics for each barcode.

        This table shows individual stats for each detected sample/barcode.
        """
        # Tab + fingerprint guard
        if ctx.triggered_id == 'update-interval':
            if active_tab != 'qc-tab':
                raise PreventUpdate
            if not hasattr(update_per_sample_table, '_last_fp'):
                update_per_sample_table._last_fp = None
            if data_fingerprint and data_fingerprint == update_per_sample_table._last_fp:
                raise PreventUpdate
            update_per_sample_table._last_fp = data_fingerprint

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return []

        try:

            # Get per-sample statistics summary
            summary_df = get_sample_statistics_summary(main_dir)

            if summary_df.empty:
                return []

            # Convert to records for DataTable
            return summary_df.to_dict('records')

        except Exception as e:
            print(f"Error updating per-sample table: {e}")
            return []

    @app.callback(
        Output("base-quality-card-container", "children"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
    )
    def update_base_quality_card(n_intervals, selected_sample, config, status, active_tab, data_fingerprint):
        """
        Update the base quality card showing Q20/Q30 rates and optional sparkline.

        Data sources:
        - FASTP: q20_bases, q30_bases, total_bases, quality_curves
        - Seqkit (Chopper): Q20(%), Q30(%), sum_len
        """
        # Tab + fingerprint guard
        if ctx.triggered_id == 'update-interval':
            if active_tab != 'qc-tab':
                raise PreventUpdate
            if not hasattr(update_base_quality_card, '_last_fp'):
                update_base_quality_card._last_fp = None
            if data_fingerprint and data_fingerprint == update_base_quality_card._last_fp:
                raise PreventUpdate
            update_base_quality_card._last_fp = data_fingerprint

        # Default empty state
        empty_state = EmptyStateMessage(
            title="No Quality Data",
            message="Base quality metrics will appear here once data is loaded",
            icon="bi-speedometer2"
        )

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return empty_state

        try:
            fastp_dir = os.path.join(main_dir, "fastp")

            # Initialize metrics
            q20_rate = 0.0
            q30_rate = 0.0
            total_bases = 0
            quality_curve = None
            source = "unknown"

            # Try FASTP first
            if os.path.exists(fastp_dir):
                fastp_files = glob.glob(os.path.join(fastp_dir, "*.fastp.json"))
                if fastp_files:
                    source = "fastp"
                    total_q20_bases = 0
                    total_q30_bases = 0
                    quality_curves_all = []

                    for fastp_file in fastp_files:
                        try:
                            with open(fastp_file, 'r') as f:
                                fastp_data = json.load(f)
                                after = fastp_data.get("summary", {}).get("after_filtering", {})
                                total_bases += after.get("total_bases", 0)
                                total_q20_bases += after.get("q20_bases", 0)
                                total_q30_bases += after.get("q30_bases", 0)

                                # Get quality curve (use first file's curve)
                                if not quality_curve:
                                    read1_after = fastp_data.get("read1_after_filtering", {})
                                    curve = read1_after.get("quality_curves", {}).get("mean", [])
                                    if curve:
                                        quality_curve = curve
                        except (json.JSONDecodeError, IOError, KeyError, TypeError) as e:
                            logging.debug(f"Error reading FASTP quality data from {fastp_file}: {e}")
                            continue

                    if total_bases > 0:
                        q20_rate = (total_q20_bases / total_bases) * 100
                        q30_rate = (total_q30_bases / total_bases) * 100

            # Fallback to seqkit if no FASTP data
            if total_bases == 0:
                seqkit_df = load_seqkit_stats(main_dir, selected_sample)
                if not seqkit_df.empty:
                    source = "seqkit"
                    total_bases = int(seqkit_df['sum_len'].sum()) if 'sum_len' in seqkit_df.columns else 0
                    q20_rate = float(seqkit_df['Q20(%)'].mean()) if 'Q20(%)' in seqkit_df.columns else 0.0
                    q30_rate = float(seqkit_df['Q30(%)'].mean()) if 'Q30(%)' in seqkit_df.columns else 0.0

            # If no data, show empty state
            if total_bases == 0:
                return empty_state

            # Generate BaseQualityCard component
            return BaseQualityCard(
                q20_rate=q20_rate,
                q30_rate=q30_rate,
                total_bases=total_bases,
                quality_curve=quality_curve,
                source=source
            )

        except Exception as e:
            print(f"Error updating base quality card: {e}")
            return dbc.Alert(
                f"Error loading base quality: {str(e)}",
                color="danger",
                className="text-center"
            )

    @app.callback(
        Output("read-statistics-card-container", "children"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
    )
    def update_read_statistics_card(n_intervals, selected_sample, config, status, active_tab, data_fingerprint):
        """
        Update the read statistics card showing mean length, N50, and GC content.

        Data sources:
        - FASTP: read1_mean_length (before/after), gc_content
        - Seqkit (Chopper): avg_len, N50, GC(%)
        """
        # Tab + fingerprint guard
        if ctx.triggered_id == 'update-interval':
            if active_tab != 'qc-tab':
                raise PreventUpdate
            if not hasattr(update_read_statistics_card, '_last_fp'):
                update_read_statistics_card._last_fp = None
            if data_fingerprint and data_fingerprint == update_read_statistics_card._last_fp:
                raise PreventUpdate
            update_read_statistics_card._last_fp = data_fingerprint

        # Default empty state
        empty_state = EmptyStateMessage(
            title="No Read Statistics",
            message="Read statistics will appear here once data is loaded",
            icon="bi-rulers"
        )

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return empty_state

        try:
            fastp_dir = os.path.join(main_dir, "fastp")

            # Initialize metrics
            mean_length = 0.0
            mean_length_before = None
            n50 = None
            gc_content = None
            source = "unknown"

            # Try FASTP first
            if os.path.exists(fastp_dir):
                fastp_files = glob.glob(os.path.join(fastp_dir, "*.fastp.json"))
                if fastp_files:
                    source = "fastp"
                    total_reads_after = 0
                    total_reads_before = 0
                    total_length_after = 0
                    total_length_before = 0
                    gc_values = []

                    for fastp_file in fastp_files:
                        try:
                            with open(fastp_file, 'r') as f:
                                fastp_data = json.load(f)
                                summary = fastp_data.get("summary", {})
                                before = summary.get("before_filtering", {})
                                after = summary.get("after_filtering", {})

                                # Accumulate for weighted average
                                reads_before = before.get("total_reads", 0)
                                reads_after = after.get("total_reads", 0)
                                total_reads_before += reads_before
                                total_reads_after += reads_after

                                # Mean length calculation (weighted)
                                len_after = after.get("read1_mean_length", 0)
                                len_before = before.get("read1_mean_length", 0)
                                total_length_after += len_after * reads_after
                                total_length_before += len_before * reads_before

                                # GC content
                                gc = after.get("gc_content", 0)
                                if gc > 0:
                                    gc_values.append(gc * 100)  # Convert to percentage
                        except (json.JSONDecodeError, IOError, KeyError, TypeError) as e:
                            logging.debug(f"Error reading FASTP length data from {fastp_file}: {e}")
                            continue

                    if total_reads_after > 0:
                        mean_length = total_length_after / total_reads_after
                    if total_reads_before > 0:
                        mean_length_before = total_length_before / total_reads_before
                    if gc_values:
                        gc_content = sum(gc_values) / len(gc_values)

            # Fallback to seqkit if no FASTP data
            if mean_length == 0:
                seqkit_df = load_seqkit_stats(main_dir, selected_sample)
                if not seqkit_df.empty:
                    source = "seqkit"
                    mean_length = float(seqkit_df['avg_len'].mean()) if 'avg_len' in seqkit_df.columns else 0.0
                    n50 = int(seqkit_df['N50'].mean()) if 'N50' in seqkit_df.columns else None
                    gc_content = float(seqkit_df['GC(%)'].mean()) if 'GC(%)' in seqkit_df.columns else None

            # If no data, show empty state
            if mean_length == 0:
                return empty_state

            # Generate ReadStatisticsCard component
            return ReadStatisticsCard(
                mean_length=mean_length,
                mean_length_before=mean_length_before,
                n50=n50,
                gc_content=gc_content,
                source=source
            )

        except Exception as e:
            print(f"Error updating read statistics card: {e}")
            return dbc.Alert(
                f"Error loading read statistics: {str(e)}",
                color="danger",
                className="text-center"
            )

    @app.callback(
        Output("filtering-breakdown-container", "children"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
    )
    def update_filtering_breakdown(n_intervals, selected_sample, config, status, active_tab, data_fingerprint):
        """
        Update the visual filtering breakdown component.

        Shows a visual representation of quality filtering statistics.
        """
        # Tab + fingerprint guard
        if ctx.triggered_id == 'update-interval':
            if active_tab != 'qc-tab':
                raise PreventUpdate
            if not hasattr(update_filtering_breakdown, '_last_fp'):
                update_filtering_breakdown._last_fp = None
            if data_fingerprint and data_fingerprint == update_filtering_breakdown._last_fp:
                raise PreventUpdate
            update_filtering_breakdown._last_fp = data_fingerprint

        # Default empty state
        empty_state = EmptyStateMessage(
            title="No Filtering Data",
            message="Filtering statistics will appear here once analysis is complete",
            icon="bi-funnel"
        )

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return empty_state

        try:
            fastp_dir = os.path.join(main_dir, "fastp")

            # Initialize variables
            tot_reads_pre_filt = 0
            tot_passed_reads = 0
            tot_low_quality_reads = 0
            tot_too_many_N_reads = 0
            tot_too_short_reads = 0

            # Get filtering stats from FASTP (sample-filtered)
            fastp_found = False
            fastp_stats = load_fastp_data(main_dir, selected_sample)
            if fastp_stats.get('total_reads_after', 0) > 0:
                fastp_found = True
                tot_reads_pre_filt = fastp_stats['total_reads_before']
                tot_passed_reads = fastp_stats['total_reads_after']
                tot_low_quality_reads = fastp_stats['low_quality']
                tot_too_many_N_reads = fastp_stats['too_many_N']
                tot_too_short_reads = fastp_stats['too_short']

            # Fallback to seqkit/Kraken2 if FASTP not found (chopper QC)
            if not fastp_found:
                seqkit_df = load_seqkit_stats(main_dir, selected_sample)
                if not seqkit_df.empty and 'num_seqs' in seqkit_df.columns:
                    tot_passed_reads = int(seqkit_df['num_seqs'].sum())

                    # Use Kraken2 for pre-filter baseline (all reads that entered classification)
                    # This is the correct source since seqkit measures post-chopper reads
                    kraken_df = load_kraken_data(main_dir, selected_sample)
                    if not kraken_df.empty:
                        # In Kraken2: root cumul_reads = classified, unclassified cumul_reads = unclassified
                        # Total reads = classified + unclassified
                        root = kraken_df[kraken_df['name'].str.strip() == 'root']
                        unclassified = kraken_df[kraken_df['name'].str.strip() == 'unclassified']

                        classified_reads = int(root.iloc[0]['cumul_reads']) if not root.empty else 0
                        unclassified_reads = int(unclassified.iloc[0]['cumul_reads']) if not unclassified.empty else 0
                        tot_reads_pre_filt = classified_reads + unclassified_reads

                        if tot_reads_pre_filt > 0:
                            # Estimate removal reasons (chopper doesn't provide breakdown)
                            removed = max(0, tot_reads_pre_filt - tot_passed_reads)
                            # Approximate distribution (60% quality, 30% length, 10% complexity)
                            tot_low_quality_reads = int(removed * 0.6)
                            tot_too_short_reads = int(removed * 0.3)
                            tot_too_many_N_reads = removed - tot_low_quality_reads - tot_too_short_reads

            # If we have no data, show empty state
            if tot_reads_pre_filt == 0:
                return empty_state

            # Build removal reasons dict
            removal_reasons = {}
            if tot_low_quality_reads > 0:
                removal_reasons["low_quality"] = tot_low_quality_reads
            if tot_too_short_reads > 0:
                removal_reasons["too_short"] = tot_too_short_reads
            if tot_too_many_N_reads > 0:
                removal_reasons["low_complexity"] = tot_too_many_N_reads

            # If no removals, add a placeholder
            if not removal_reasons:
                removal_reasons = {"low_quality": 0, "too_short": 0, "low_complexity": 0}

            # Generate filtering breakdown component
            return FilteringBreakdownVisual(
                total_reads=tot_reads_pre_filt,
                passed_reads=tot_passed_reads,
                removal_reasons=removal_reasons
            )

        except Exception as e:
            print(f"Error updating filtering breakdown: {e}")
            return dbc.Alert(
                f"Error loading filtering statistics: {str(e)}",
                color="danger",
                className="text-center"
            )

    @app.callback(
        Output("qc-metrics-summary-container", "children"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("active-tab", "data"),
            State("data-fingerprint", "data"),
        ],
    )
    def update_qc_metrics_summary(n_intervals, selected_sample, config, active_tab, data_fingerprint):
        """
        Update the key metrics summary card with QC data.

        Returns a KeyMetricsSummaryCard component matching the QualityScoreIndicator design.
        """
        # Tab + fingerprint guard
        if ctx.triggered_id == 'update-interval':
            if active_tab != 'qc-tab':
                raise PreventUpdate
            if not hasattr(update_qc_metrics_summary, '_last_fp'):
                update_qc_metrics_summary._last_fp = None
            if data_fingerprint and data_fingerprint == update_qc_metrics_summary._last_fp:
                raise PreventUpdate
            update_qc_metrics_summary._last_fp = data_fingerprint

        from nanometa_live.app.components.organism_components import KeyMetricsSummaryCard

        # Default empty state
        empty_state = dbc.Alert(
            "Key metrics will appear here once data is loaded",
            color="light",
            className="text-center"
        )

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return empty_state

        try:
            # Initialize metrics
            tot_reads_pre_filt = 0
            tot_passed_reads = 0
            classified_reads = 0
            total_kraken_reads = 0

            # Count samples
            from nanometa_live.core.utils.sample_detector import get_available_samples
            samples = get_available_samples(main_dir)
            sample_count = len([s for s in samples if s != "All Samples"])

            # Get filtering stats from FASTP (sample-filtered)
            fastp_stats = load_fastp_data(main_dir, selected_sample)
            if fastp_stats.get('total_reads_after', 0) > 0:
                tot_reads_pre_filt = fastp_stats['total_reads_before']
                tot_passed_reads = fastp_stats['total_reads_after']

            # Load Kraken2 data once (sample-filtered) for reuse
            kraken_df = load_kraken_data(main_dir, selected_sample)

            # Fallback to seqkit/Kraken2 if FASTP not found
            if tot_passed_reads == 0:
                seqkit_df = load_seqkit_stats(main_dir, selected_sample)
                if not seqkit_df.empty and 'num_seqs' in seqkit_df.columns:
                    tot_passed_reads = int(seqkit_df['num_seqs'].sum())
                    if not kraken_df.empty:
                        classified_count, unclassified_count, _ = get_classification_stats(kraken_df)
                        tot_reads_pre_filt = classified_count + unclassified_count

            # Get classification stats from Kraken2 (sample-filtered)
            if not kraken_df.empty:
                classified_reads, unclassified_kraken, _ = get_classification_stats(kraken_df)
                total_kraken_reads = classified_reads + unclassified_kraken

            # Calculate rates (cap pass_rate at 100% to handle edge cases
            # where chopper/seqkit totals differ from kraken pre-filter counts)
            pass_rate = (tot_passed_reads / tot_reads_pre_filt * 100) if tot_reads_pre_filt > 0 else 0
            pass_rate = min(pass_rate, 100.0)
            classification_rate = (classified_reads / total_kraken_reads * 100) if total_kraken_reads > 0 else 0

            # If no data, show empty state
            if tot_reads_pre_filt == 0 and total_kraken_reads == 0:
                return empty_state

            # Return the KeyMetricsSummaryCard component
            return KeyMetricsSummaryCard(
                total_reads=tot_reads_pre_filt,
                pass_rate=pass_rate,
                classified_rate=classification_rate,
                sample_count=sample_count
            )

        except Exception as e:
            print(f"Error updating QC metrics summary: {e}")
            return empty_state
