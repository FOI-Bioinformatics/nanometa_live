"""
Quality Control (QC) tab callbacks for Nanometa Live v2.0.

This module defines the callbacks for the QC tab, which displays quality metrics
and processing statistics with multi-sample/barcode support.
"""

import os
import logging
import pandas as pd
import time
import json
import glob
from datetime import datetime

from dash import Dash, Input, Output, State, html, no_update
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


def _get_empty_qc_figures():
    """Return fresh empty QC figures for placeholder display.

    Creates new figure objects on each call to prevent mutable state
    from being shared across callback invocations or browser sessions.
    """
    return [
        px.line(title="Cumulative Sequences"),
        px.line(title="Cumulative Base Pairs"),
        px.bar(title="Sequences per Sample"),
        px.bar(title="Base Pairs per Sample"),
    ]


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
        ],
        prevent_initial_call=False,
    )
    def load_qc_data_cache(n_intervals, selected_sample, config, status):
        """
        Load all QC data once per interval and cache it.

        This prevents multiple callbacks from redundantly loading the same data.
        Returns a dict with kraken_df and fastp_data for the selected sample.
        """

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
        ],
    )
    def update_qc_plots(n_intervals, selected_sample, config, status):
        """
        Update the QC plots based on actual processed data from FASTP/Kraken2.

        Shows actual reads and base pairs that passed through the pipeline,
        ordered by file modification time to show processing progress.
        """

        # Check if we have valid config and main_dir
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
        if not main_dir or not os.path.exists(main_dir):
            return _get_empty_qc_figures()

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
                    px.line(title="Cumulative Sequences").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
                    px.line(title="Cumulative Base Pairs").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
                    px.bar(title="Sequences per Sample").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
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
                template="nanometa",
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
                title="Cumulative Processed Sequences",
            )
            cumul_reads_fig.update_traces(
                line=dict(color="#0d6efd", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(13, 110, 253, 0.08)",
                hovertemplate="Sequences: %{y:,.0f}<extra></extra>",
            )
            cumul_reads_fig.update_layout(
                **_qc_layout,
                xaxis_title="Processing Time",
                yaxis_title="Cumulative Sequences",
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
                qc_df, x="Sample", y="Reads", title="Sequences per Sample"
            )
            reads_fig.update_traces(
                marker_color="#0d6efd",
                marker_line_width=0,
                hovertemplate="<b>%{x}</b><br>Sequences: %{y:,.0f}<extra></extra>",
            )
            reads_fig.update_layout(
                **_qc_layout,
                xaxis_title="Sample",
                yaxis_title="Sequences",
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
            logging.error(f"Error updating QC plots: {e}")
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
        ],
    )
    def update_qc_stats(n_intervals, selected_sample, config, status):
        """Update the QC statistics based on the latest data."""
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
            chopper_estimated = False

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

                            # Chopper does not produce a per-category breakdown
                            # of removed reads. The proportions below are rough
                            # estimates only and are labelled as such in the UI.
                            if tot_reads_pre_filt > 0:
                                tot_removed_reads = max(0, tot_reads_pre_filt - tot_passed_reads)
                                # Approximate distribution: 60% quality, 30% length, 10% complexity
                                tot_low_quality_reads = int(tot_removed_reads * 0.6)
                                tot_too_short_reads = int(tot_removed_reads * 0.3)
                                tot_too_many_N_reads = tot_removed_reads - tot_low_quality_reads - tot_too_short_reads
                                chopper_estimated = True

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

            # When chopper is used, the per-category breakdown is an
            # approximation (chopper does not report these individually).
            est = " (est.)" if chopper_estimated else ""
            low_quality = f"Too low quality{est}: {tot_low_quality_reads:,} ({percentage_low_quality}%)"
            too_short = f"Too short{est}: {tot_too_short_reads:,} ({percentage_too_short}%)"
            low_complexity = f"Too low complexity{est}: {tot_too_many_N_reads:,} ({percentage_too_many_N}%)"

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
            logging.error(f"Error updating QC stats: {e}")
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
        prevent_initial_call=True,
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
        prevent_initial_call=True,
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
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
            if export_dir:
                export_path = export_dir
            else:
                export_path = os.path.join(main_dir, "reports")

            # Path traversal protection: ensure export path is within main_dir
            if main_dir:
                resolved_export = os.path.realpath(export_path)
                resolved_base = os.path.realpath(main_dir)
                if not resolved_export.startswith(resolved_base + os.sep) and resolved_export != resolved_base:
                    return {
                        "title": "Export Failed",
                        "message": "Export directory must be within the results directory.",
                        "color": "danger",
                    }

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
        Output("per-sample-table", "rowData"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
    )
    def update_per_sample_table(n_intervals, selected_sample, config, status):
        """
        Update the per-sample breakdown table with statistics for each barcode.

        This table shows individual stats for each detected sample/barcode.
        """

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
            logging.error(f"Error updating per-sample table: {e}")
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
        ],
    )
    def update_base_quality_card(n_intervals, selected_sample, config, status):
        """
        Update the base quality card showing Q20/Q30 rates and optional sparkline.

        Data sources:
        - FASTP: q20_bases, q30_bases, total_bases, quality_curves
        - Seqkit (Chopper): Q20(%), Q30(%), sum_len
        """

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
            logging.error(f"Error updating base quality card: {e}")
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
        ],
    )
    def update_read_statistics_card(n_intervals, selected_sample, config, status):
        """
        Update the read statistics card showing mean length, N50, and GC content.

        Data sources:
        - FASTP: read1_mean_length (before/after), gc_content
        - Seqkit (Chopper): avg_len, N50, GC(%)
        """

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
            logging.error(f"Error updating read statistics card: {e}")
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
        ],
    )
    def update_filtering_breakdown(n_intervals, selected_sample, config, status):
        """
        Update the visual filtering breakdown component.

        Shows a visual representation of quality filtering statistics.
        """

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
            chopper_estimated = False

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
                            # Chopper does not produce a per-category breakdown
                            # of removed reads. The proportions below are rough
                            # estimates only and are labelled as such in the UI.
                            removed = max(0, tot_reads_pre_filt - tot_passed_reads)
                            # Approximate distribution (60% quality, 30% length, 10% complexity)
                            tot_low_quality_reads = int(removed * 0.6)
                            tot_too_short_reads = int(removed * 0.3)
                            tot_too_many_N_reads = removed - tot_low_quality_reads - tot_too_short_reads
                            chopper_estimated = True

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
            breakdown = FilteringBreakdownVisual(
                total_reads=tot_reads_pre_filt,
                passed_reads=tot_passed_reads,
                removal_reasons=removal_reasons
            )
            if chopper_estimated:
                return html.Div([
                    breakdown,
                    html.Small(
                        "Removal breakdown is estimated (chopper does not "
                        "report per-category statistics).",
                        className="text-muted fst-italic mt-1 d-block"
                    )
                ])
            return breakdown

        except Exception as e:
            logging.error(f"Error updating filtering breakdown: {e}")
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
        ],
    )
    def update_qc_metrics_summary(n_intervals, selected_sample, config):
        """
        Update the key metrics summary card with QC data.

        Returns a KeyMetricsSummaryCard component matching the QualityScoreIndicator design.
        """

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
            logging.error(f"Error updating QC metrics summary: {e}")
            return empty_state

    # =========================================================================
    # QC REPORT EXPORT
    # =========================================================================

    @app.callback(
        Output("download-qc-report", "data"),
        Input("export-qc-report", "n_clicks"),
        [
            State("qc-data-cache", "data"),
            State("selected-sample", "data"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def export_qc_report(n_clicks, qc_cache, selected_sample, config):
        """Export QC metrics as a CSV report."""
        if not n_clicks or not config:
            return no_update

        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
        if not main_dir:
            return no_update

        try:
            fastp_data = load_fastp_data(main_dir, selected_sample)
            seqkit_data = load_seqkit_stats(main_dir, selected_sample)

            rows = []

            if fastp_data and fastp_data.get("total_reads_before", 0) > 0:
                rows.append({
                    "metric": "Total Reads (pre-filter)",
                    "value": fastp_data.get("total_reads_before", 0),
                })
                rows.append({
                    "metric": "Total Reads (post-filter)",
                    "value": fastp_data.get("total_reads_after", 0),
                })
                before = fastp_data.get("total_reads_before", 0)
                after = fastp_data.get("total_reads_after", 0)
                rate = (after / before * 100) if before > 0 else 0
                rows.append({
                    "metric": "Pass Rate (%)",
                    "value": f"{min(rate, 100.0):.1f}",
                })
                rows.append({
                    "metric": "Q20 Rate (%)",
                    "value": fastp_data.get("q20_rate", "N/A"),
                })
                rows.append({
                    "metric": "Q30 Rate (%)",
                    "value": fastp_data.get("q30_rate", "N/A"),
                })
                rows.append({
                    "metric": "GC Content (%)",
                    "value": fastp_data.get("gc_content", "N/A"),
                })

            if not seqkit_data.empty:
                rows.append({
                    "metric": "SeqKit Total Sequences",
                    "value": int(seqkit_data["num_seqs"].sum()) if "num_seqs" in seqkit_data.columns else "N/A",
                })
                if "avg_len" in seqkit_data.columns:
                    rows.append({
                        "metric": "Average Read Length",
                        "value": f"{seqkit_data['avg_len'].mean():.0f}",
                    })

            if not rows:
                return no_update

            df = pd.DataFrame(rows)
            sample_label = selected_sample if selected_sample and selected_sample != "All Samples" else "all_samples"
            filename = f"qc_report_{sample_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            return {
                "content": df.to_csv(index=False),
                "filename": filename,
                "type": "text/csv",
            }

        except Exception as e:
            logging.error(f"Error exporting QC report: {e}")
            return no_update

    # =========================================================================
    # ACTION GUIDANCE BANNER
    # Provides plain-language next-step guidance based on current QC metrics.
    # =========================================================================

    @app.callback(
        Output("qc-action-guidance-container", "children"),
        [
            Input("update-interval", "n_intervals"),
            Input("selected-sample", "data"),
        ],
        [
            State("app-config", "data"),
        ],
    )
    def update_qc_action_guidance(n_intervals, selected_sample, config):
        """
        Generate a contextual action guidance banner based on QC metrics.

        Translates raw metrics into plain-language recommendations for
        operators who may not have bioinformatics expertise.
        """

        main_dir = (
            config.get("results_output_directory", "")
            or config.get("main_dir", "")
            if config
            else ""
        )
        if not main_dir or not os.path.exists(main_dir):
            return ""

        try:
            # Gather metrics
            tot_reads_pre_filt = 0
            tot_passed_reads = 0
            classified_reads = 0
            total_kraken_reads = 0

            fastp_stats = load_fastp_data(main_dir, selected_sample)
            if fastp_stats.get("total_reads_after", 0) > 0:
                tot_reads_pre_filt = fastp_stats["total_reads_before"]
                tot_passed_reads = fastp_stats["total_reads_after"]

            kraken_df = load_kraken_data(main_dir, selected_sample)

            if tot_passed_reads == 0:
                seqkit_data = load_seqkit_stats(main_dir, selected_sample)
                if not seqkit_data.empty and "num_seqs" in seqkit_data.columns:
                    tot_passed_reads = int(seqkit_data["num_seqs"].sum())
                    if not kraken_df.empty:
                        c, u, _ = get_classification_stats(kraken_df)
                        tot_reads_pre_filt = c + u

            if not kraken_df.empty:
                classified_reads, unclassified_reads, _ = get_classification_stats(kraken_df)
                total_kraken_reads = classified_reads + unclassified_reads

            if tot_reads_pre_filt == 0 and total_kraken_reads == 0:
                return ""

            pass_rate = min(
                (tot_passed_reads / tot_reads_pre_filt * 100) if tot_reads_pre_filt > 0 else 0,
                100.0,
            )
            classification_rate = (
                (classified_reads / total_kraken_reads * 100) if total_kraken_reads > 0 else 0
            )

            # Determine guidance level and message
            issues = []
            if pass_rate < 60:
                issues.append(
                    "Pass rate is below 60% - consider checking flow cell health "
                    "and sample quality. Re-sequencing may be needed for reliable results."
                )
            elif pass_rate < 75:
                issues.append(
                    "Pass rate is moderate. Results are usable but quality could be improved."
                )

            if classification_rate < 40 and total_kraken_reads > 100:
                issues.append(
                    "Less than 40% of sequences could be identified. This may indicate "
                    "the sample contains organisms not in the database, or that sequencing "
                    "quality is limiting identification."
                )

            if tot_reads_pre_filt < 1000 and tot_reads_pre_filt > 0:
                issues.append(
                    "Fewer than 1,000 total sequences. Continue sequencing for "
                    "more reliable results, especially for low-abundance organisms."
                )

            if not issues:
                # All good
                if tot_reads_pre_filt > 0:
                    return dbc.Alert(
                        [
                            html.I(className="bi bi-check-circle-fill me-2"),
                            html.Strong("Data quality looks good. "),
                            html.Span(
                                "Proceed to the Organisms or Validation tabs to review findings."
                            ),
                        ],
                        color="success",
                        className="mb-0",
                        dismissable=True,
                    )
                return ""

            # Build warning/danger alert
            severity = "danger" if pass_rate < 60 or classification_rate < 40 else "warning"
            icon = "exclamation-triangle-fill" if severity == "warning" else "x-circle-fill"

            return dbc.Alert(
                [
                    html.I(className=f"bi bi-{icon} me-2"),
                    html.Strong("Action needed: " if severity == "danger" else "Review recommended: "),
                    html.Ul(
                        [html.Li(issue) for issue in issues],
                        className="mb-0 mt-2",
                    ),
                ],
                color=severity,
                className="mb-0",
                dismissable=True,
            )

        except Exception as e:
            logging.error(f"Error generating QC action guidance: {e}")
            return ""
