#!/usr/bin/env python3
"""
Example Dash application using NanometanfOutputParser.

This demonstrates how to integrate the parser with a Dash dashboard for
real-time visualization of nanometanf pipeline outputs.

Usage:
    python dash_integration_example.py /path/to/nanometanf/results
"""

import sys
import argparse
from pathlib import Path
from dash import Dash, html, dcc, Input, Output
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from nanometa_live.core.parsers import NanometanfOutputParser, RealtimeMonitor


# Global parser instance
parser = None


def create_app(outdir: str) -> Dash:
    """
    Create Dash application with integrated parser.

    Args:
        outdir: Path to nanometanf output directory

    Returns:
        Configured Dash app
    """
    global parser
    parser = NanometanfOutputParser(outdir)

    app = Dash(__name__, title="Nanometa Live - Parser Demo")

    app.layout = html.Div([
        html.H1("Nanometa Live - NanometanfOutputParser Demo"),

        html.Div([
            html.H3("Output Directory:"),
            html.P(outdir, style={'fontFamily': 'monospace', 'fontSize': '14px'})
        ], style={'marginBottom': '20px'}),

        # Auto-refresh interval
        dcc.Interval(
            id='interval-component',
            interval=10*1000,  # Update every 10 seconds
            n_intervals=0
        ),

        # Classification Summary Section
        html.Div([
            html.H2("Classification Summary"),
            html.Div(id='classification-summary', style={'marginBottom': '30px'})
        ]),

        # Top Species Section
        html.Div([
            html.H2("Top 10 Species by Read Count"),
            dcc.Graph(id='top-species-chart')
        ], style={'marginBottom': '30px'}),

        # Quality Control Section
        html.Div([
            html.H2("Quality Control Metrics"),
            html.Div(id='qc-metrics', style={'marginBottom': '20px'}),
            dcc.Graph(id='qc-chart')
        ], style={'marginBottom': '30px'}),

        # Real-time Batch Processing Section
        html.Div([
            html.H2("Real-time Batch Processing"),
            html.Div(id='batch-summary', style={'marginBottom': '20px'}),
            dcc.Graph(id='batch-chart')
        ], style={'marginBottom': '30px'}),

    ], style={'padding': '20px', 'fontFamily': 'Arial, sans-serif'})

    # Callbacks
    register_callbacks(app)

    return app


def register_callbacks(app: Dash):
    """Register all Dash callbacks."""

    @app.callback(
        Output('classification-summary', 'children'),
        Input('interval-component', 'n_intervals')
    )
    def update_classification_summary(n):
        """Update classification summary cards."""
        summary = parser.get_classification_summary()
        overall = summary.get('overall', {})

        total_reads = overall.get('total_reads', 0)
        classified = overall.get('classified', 0)
        unclassified = overall.get('unclassified', 0)
        classification_rate = overall.get('classification_rate', 0.0)

        return html.Div([
            html.Div([
                create_metric_card("Total Reads", f"{total_reads:,}"),
                create_metric_card("Classified", f"{classified:,}"),
                create_metric_card("Unclassified", f"{unclassified:,}"),
                create_metric_card("Classification Rate", f"{classification_rate:.2%}"),
            ], style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap'})
        ])

    @app.callback(
        Output('top-species-chart', 'figure'),
        Input('interval-component', 'n_intervals')
    )
    def update_top_species_chart(n):
        """Update top species bar chart."""
        df = parser.get_top_species(n=10)

        if df.empty:
            # Return empty figure with message
            fig = go.Figure()
            fig.add_annotation(
                text="No species data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=16, color="gray")
            )
            fig.update_layout(
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                height=400
            )
            return fig

        # Create horizontal bar chart
        fig = px.bar(
            df,
            y='name',
            x='total_reads',
            orientation='h',
            title='Top 10 Species by Read Count',
            labels={'name': 'Species', 'total_reads': 'Read Count'},
            color='total_reads',
            color_continuous_scale='Viridis'
        )

        fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            height=500,
            showlegend=False
        )

        return fig

    @app.callback(
        [Output('qc-metrics', 'children'),
         Output('qc-chart', 'figure')],
        Input('interval-component', 'n_intervals')
    )
    def update_qc_section(n):
        """Update quality control metrics and charts."""
        fastp_summary = parser.get_fastp_summary()

        # Metrics cards
        total_samples = fastp_summary.get('total_samples', 0)
        reads_before = fastp_summary.get('total_reads_before', 0)
        reads_after = fastp_summary.get('total_reads_after', 0)
        q30_rate = fastp_summary.get('avg_q30_rate_after', 0.0)

        metrics = html.Div([
            create_metric_card("Samples", f"{total_samples}"),
            create_metric_card("Reads Before", f"{reads_before:,}"),
            create_metric_card("Reads After", f"{reads_after:,}"),
            create_metric_card("Avg Q30 Rate", f"{q30_rate:.2%}"),
        ], style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap'})

        # Per-sample quality chart
        combined_fastp = parser.combine_fastp_reports()

        if combined_fastp.empty:
            fig = go.Figure()
            fig.add_annotation(
                text="No FASTP data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=16, color="gray")
            )
            fig.update_layout(
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                height=400
            )
            return metrics, fig

        # Create subplot with two charts
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=('Read Retention by Sample', 'Q30 Rates by Sample'),
            specs=[[{"type": "bar"}, {"type": "bar"}]]
        )

        # Read retention chart
        combined_fastp['retention_rate'] = (
            combined_fastp['total_reads_after'] / combined_fastp['total_reads_before'] * 100
        )

        fig.add_trace(
            go.Bar(
                x=combined_fastp['sample'],
                y=combined_fastp['retention_rate'],
                name='Retention Rate',
                marker_color='lightblue'
            ),
            row=1, col=1
        )

        # Q30 rates chart
        fig.add_trace(
            go.Bar(
                x=combined_fastp['sample'],
                y=combined_fastp['q30_rate_after'] * 100,
                name='Q30 Rate',
                marker_color='lightgreen'
            ),
            row=1, col=2
        )

        fig.update_xaxes(title_text="Sample", row=1, col=1)
        fig.update_xaxes(title_text="Sample", row=1, col=2)
        fig.update_yaxes(title_text="Retention Rate (%)", row=1, col=1)
        fig.update_yaxes(title_text="Q30 Rate (%)", row=1, col=2)

        fig.update_layout(height=400, showlegend=False)

        return metrics, fig

    @app.callback(
        [Output('batch-summary', 'children'),
         Output('batch-chart', 'figure')],
        Input('interval-component', 'n_intervals')
    )
    def update_batch_section(n):
        """Update real-time batch processing section."""
        cumulative = parser.get_cumulative_stats()

        # Summary cards
        total_batches = cumulative.get('total_batches', 0)
        total_reads = cumulative.get('total_reads', 0)
        classification_rate = cumulative.get('classification_rate', 0.0)
        latest_batch = parser.get_latest_batch_number()

        summary = html.Div([
            create_metric_card("Total Batches", f"{total_batches}"),
            create_metric_card("Latest Batch", f"{latest_batch}"),
            create_metric_card("Total Reads", f"{total_reads:,}"),
            create_metric_card("Classification Rate", f"{classification_rate:.2%}"),
        ], style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap'})

        # Batch progression chart
        all_batches = parser.parse_all_batch_stats()

        if not all_batches:
            fig = go.Figure()
            fig.add_annotation(
                text="No batch data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=16, color="gray")
            )
            fig.update_layout(
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                height=400
            )
            return summary, fig

        # Create DataFrame from batches
        batch_df = pd.DataFrame([
            {
                'batch': b.get('batch_number', 0),
                'reads': b.get('reads_in_batch', 0),
                'classified': b.get('classified_in_batch', 0),
                'unclassified': b.get('unclassified_in_batch', 0)
            }
            for b in all_batches
        ])

        # Calculate cumulative reads
        batch_df['cumulative_reads'] = batch_df['reads'].cumsum()
        batch_df['cumulative_classified'] = batch_df['classified'].cumsum()

        # Create dual-axis chart
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Reads per batch (bars)
        fig.add_trace(
            go.Bar(
                x=batch_df['batch'],
                y=batch_df['reads'],
                name='Reads per Batch',
                marker_color='lightblue'
            ),
            secondary_y=False
        )

        # Cumulative reads (line)
        fig.add_trace(
            go.Scatter(
                x=batch_df['batch'],
                y=batch_df['cumulative_reads'],
                name='Cumulative Reads',
                line=dict(color='darkblue', width=2)
            ),
            secondary_y=True
        )

        fig.update_xaxes(title_text="Batch Number")
        fig.update_yaxes(title_text="Reads per Batch", secondary_y=False)
        fig.update_yaxes(title_text="Cumulative Reads", secondary_y=True)

        fig.update_layout(
            title='Batch Processing Progression',
            height=400,
            hovermode='x unified'
        )

        return summary, fig


def create_metric_card(title: str, value: str) -> html.Div:
    """
    Create a metric display card.

    Args:
        title: Metric name
        value: Metric value

    Returns:
        HTML div with styled metric card
    """
    return html.Div([
        html.H4(title, style={'margin': '0', 'color': '#666', 'fontSize': '14px'}),
        html.P(value, style={'margin': '10px 0 0 0', 'fontSize': '24px', 'fontWeight': 'bold'})
    ], style={
        'border': '1px solid #ddd',
        'borderRadius': '5px',
        'padding': '15px',
        'minWidth': '200px',
        'backgroundColor': '#f9f9f9'
    })


def main():
    """Main entry point."""
    parser_args = argparse.ArgumentParser(
        description='Example Dash application with NanometanfOutputParser integration'
    )

    parser_args.add_argument(
        'outdir',
        type=str,
        help='Path to nanometanf pipeline output directory'
    )

    parser_args.add_argument(
        '--port',
        type=int,
        default=8050,
        help='Port to run Dash server (default: 8050)'
    )

    parser_args.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )

    args = parser_args.parse_args()

    # Validate output directory
    outdir = Path(args.outdir)
    if not outdir.exists():
        print(f"Error: Output directory does not exist: {outdir}")
        sys.exit(1)

    print("=" * 60)
    print("Nanometa Live - Parser Integration Demo")
    print("=" * 60)
    print(f"\nOutput directory: {outdir}")
    print(f"Port: {args.port}")
    print(f"\nStarting Dash server...")
    print(f"Open browser to: http://localhost:{args.port}")
    print("\nPress Ctrl+C to stop\n")

    # Create and run app
    app = create_app(str(outdir))
    app.run_server(debug=args.debug, port=args.port)


if __name__ == '__main__':
    main()
