"""
Configuration form component for Nanometa Live v2.0.

This module defines a simplified two-mode configuration interface:
- Essential Settings: Output directory, Kraken2 database, processing mode
- Advanced Settings: Technical parameters (collapsible)

Species watchlist management is handled in the dedicated Watchlist tab.
"""

import os
from typing import Dict, Any

from dash import html, dcc
import dash_bootstrap_components as dbc



def create_config_form():
    """
    Create a simplified two-mode configuration form.

    Returns:
        A dash component representing the configuration form
    """
    return html.Div([
        # Essential Settings Section (Always visible)
        dbc.Card([
            dbc.CardHeader([
                html.Div([
                    html.I(className="bi bi-gear-fill me-2", style={"fontSize": "20px"}),
                    html.H5("Essential Settings", className="mb-0 d-inline"),
                    dbc.Badge("Required", color="danger", className="ms-2",
                              style={"fontSize": "0.7rem", "verticalAlign": "middle"})
                ], className="d-flex align-items-center")
            ]),
            dbc.CardBody([
                # Analysis Name
                dbc.Row([
                    dbc.Col([
                        dbc.Label([
                            "Analysis Name ",
                            html.I(className="bi bi-info-circle text-muted", id="analysis-name-info")
                        ], html_for="analysis-name-input"),
                        dbc.Input(
                            id="analysis-name-input",
                            type="text",
                            placeholder="My Nanopore Analysis",
                            className="mb-2"
                        ),
                        dbc.Tooltip(
                            "Give your analysis a descriptive name for easy reference",
                            target="analysis-name-info"
                        )
                    ], md=12)
                ], className="mb-3"),

                # Data Directory
                dbc.Row([
                    dbc.Col([
                        dbc.Label([
                            "Nanopore Output Directory ",
                            html.Span("*", className="text-danger"),
                            html.I(className="bi bi-info-circle text-muted ms-1", id="nanopore-dir-info")
                        ], html_for="nanopore-dir-input"),
                        dbc.InputGroup([
                            dbc.Input(
                                id="nanopore-dir-input",
                                type="text",
                                placeholder="/path/to/nanopore/output"
                            ),
                            dbc.Button(
                                [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                                id="browse-nanopore-dir",
                                color="secondary",
                                outline=True
                            ),
                            dbc.InputGroupText(
                                html.Span(id="nanopore-dir-status", children="")
                            )
                        ]),
                        dbc.Tooltip(
                            "Directory containing FASTQ files from the nanopore sequencer",
                            target="nanopore-dir-info"
                        ),
                        html.Div(id="nanopore-dir-feedback", className="mt-1")
                    ], md=12)
                ], className="mb-4"),

                # Input Mode Section
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.I(className="bi bi-sliders me-2", style={"fontSize": "16px"}),
                            html.Strong("Input Mode Settings", className="mb-0 d-inline")
                        ], className="d-flex align-items-center mb-2 text-muted"),
                    ], md=12)
                ]),
                dbc.Row([
                    dbc.Col([
                        dbc.Label([
                            "Processing Mode ",
                            html.I(className="bi bi-info-circle text-muted ms-1", id="processing-mode-info")
                        ], html_for="processing-mode-input"),
                        dbc.Select(
                            id="processing-mode-input",
                            options=[
                                {"label": "Batch (process existing files)", "value": "batch"},
                                {"label": "Realtime (watch for new files)", "value": "realtime"}
                            ],
                            value="batch"
                        ),
                        dbc.Tooltip(
                            "Batch: Process all existing files at once. "
                            "Realtime: Continuously watch for new files during active sequencing.",
                            target="processing-mode-info"
                        ),
                        dbc.FormText("Batch is recommended for completed sequencing runs")
                    ], md=4),
                    dbc.Col([
                        dbc.Label([
                            "Sample Handling ",
                            html.I(className="bi bi-info-circle text-muted ms-1", id="sample-handling-info")
                        ], html_for="sample-handling-input"),
                        dbc.Select(
                            id="sample-handling-input",
                            options=[
                                {"label": "Single sample (all files = 1 sample)", "value": "single_sample"},
                                {"label": "Per file (each file = 1 sample)", "value": "per_file"},
                                {"label": "By barcode (subdirectories)", "value": "by_barcode"}
                            ],
                            value="single_sample"
                        ),
                        dbc.Tooltip(
                            "Single sample: All FASTQ files belong to one sample. "
                            "Per file: Each file is a separate sample. "
                            "By barcode: Files in barcode01/, barcode02/ etc. are separate samples.",
                            target="sample-handling-info"
                        ),
                        dbc.FormText("How to group input files into samples")
                    ], md=4),
                    dbc.Col([
                        dbc.Label([
                            "Sample Name ",
                            html.I(className="bi bi-info-circle text-muted ms-1", id="sample-name-info")
                        ], html_for="sample-name-input"),
                        dbc.Input(
                            id="sample-name-input",
                            type="text",
                            value="sample",
                            placeholder="sample"
                        ),
                        dbc.Tooltip(
                            "Name to use when all files belong to one sample. "
                            "Only used with 'Single sample' handling mode.",
                            target="sample-name-info"
                        ),
                        dbc.FormText("Used when 'Single sample' is selected")
                    ], md=4, id="sample-name-col")
                ], className="mb-4"),

                # Kraken2 Database
                dbc.Row([
                    dbc.Col([
                        dbc.Label([
                            "Kraken2 Database ",
                            html.Span("*", className="text-danger"),
                            html.I(className="bi bi-info-circle text-muted ms-1", id="kraken-db-info")
                        ], html_for="kraken-db-input"),
                        dbc.InputGroup([
                            dbc.Input(
                                id="kraken-db-input",
                                type="text",
                                placeholder="/path/to/kraken2/database"
                            ),
                            dbc.Button(
                                [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                                id="browse-kraken-db",
                                color="secondary",
                                outline=True
                            ),
                            dbc.InputGroupText(
                                html.Span(id="kraken-db-status", children="")
                            )
                        ]),
                        dbc.Tooltip(
                            "Path to Kraken2 database directory (must contain hash.k2d, opts.k2d, and taxo.k2d)",
                            target="kraken-db-info"
                        ),
                        html.Div(id="kraken-db-feedback", className="mt-1")
                    ], md=12)
                ], className="mb-4"),

                # Results Output Directory (NEW)
                dbc.Row([
                    dbc.Col([
                        dbc.Label([
                            "Results Output Directory ",
                            html.I(className="bi bi-info-circle text-muted ms-1", id="results-dir-info")
                        ], html_for="results-dir-input"),
                        dbc.InputGroup([
                            dbc.Input(
                                id="results-dir-input",
                                type="text",
                                placeholder="Leave empty to use ~/nanometa_results"
                            ),
                            dbc.Button(
                                [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                                id="browse-results-dir",
                                color="secondary",
                                outline=True
                            ),
                            dbc.InputGroupText(
                                html.Span(id="results-dir-status", children="")
                            )
                        ]),
                        dbc.Tooltip(
                            "Primary output directory for the analysis pipeline. Contains all results "
                            "including Kraken2 reports, QC data, and validation output.",
                            target="results-dir-info"
                        ),
                        dbc.FormText(
                            "Where to save exported reports, PDFs, and analysis summaries",
                            className="text-muted"
                        )
                    ], md=12)
                ], className="mb-4"),

            ])
        ], className="mb-4", style={"boxShadow": "0 4px 6px rgba(0,0,0,0.1)"}),

        # Advanced Settings (Collapsible)
        dbc.Accordion([
            dbc.AccordionItem([
                # GUI Settings
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-display me-2"),
                        html.Strong("Display Settings")
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Update Interval (seconds)", html_for="update-interval-input"),
                                dbc.Input(
                                    id="update-interval-input",
                                    type="number",
                                    min=5,
                                    max=300,
                                    step=5,
                                    value=30
                                ),
                                dbc.FormText("How often to refresh data (5-300 seconds)")
                            ], md=6),
                            dbc.Col([
                                dbc.Label("Alert Threshold (reads)", html_for="danger-threshold-input"),
                                dbc.Input(
                                    id="danger-threshold-input",
                                    type="number",
                                    min=1,
                                    step=10,
                                    value=100
                                ),
                                dbc.FormText("Minimum reads to trigger species alert")
                            ], md=6)
                        ])
                    ])
                ], className="mb-3"),

                # Database Settings (simplified - taxonomy auto-detected by TaxidMapper)
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-database me-2"),
                        html.Strong("Database Settings")
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    html.I(className="bi bi-info-circle text-info me-2"),
                                    html.Span(
                                        "Taxonomy mapping is handled automatically. "
                                        "Database downloads are available in the Preparation tab.",
                                        className="text-muted small"
                                    )
                                ], className="mt-2"),
                            ], md=12),
                        ]),
                        # Hidden inputs to maintain backward compatibility
                        dbc.Input(id="kraken-taxonomy-input", type="hidden", value="gtdb"),
                        dbc.Input(id="watchlist-taxonomy-mode", type="hidden", value="auto"),
                    ])
                ], className="mb-3"),

                # Pipeline Source Settings
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-git me-2"),
                        html.Strong("Pipeline Source")
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Pipeline Location ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="pipeline-source-info")
                                ], html_for="pipeline-source-type-input"),
                                dbc.Select(
                                    id="pipeline-source-type-input",
                                    options=[
                                        {"label": "Remote (GitHub)", "value": "remote"},
                                        {"label": "Local Path", "value": "local"}
                                    ],
                                    value="remote"
                                ),
                                dbc.FormText("Where to load the nanometanf pipeline from"),
                                dbc.Tooltip(
                                    "Remote: Downloads from GitHub (requires internet). "
                                    "Local: Use a local copy of the pipeline.",
                                    target="pipeline-source-info"
                                )
                            ], md=4),
                            dbc.Col([
                                dbc.Label([
                                    "Branch/Version ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="pipeline-branch-info")
                                ], html_for="pipeline-branch-input"),
                                dbc.Select(
                                    id="pipeline-branch-input",
                                    options=[
                                        {"label": "master (Stable)", "value": "master"},
                                        {"label": "dev (Development)", "value": "dev"}
                                    ],
                                    value="master"
                                ),
                                dbc.FormText("Pipeline version to use"),
                                dbc.Tooltip(
                                    "master: Stable release, recommended for production. "
                                    "dev: Latest features, may be less stable.",
                                    target="pipeline-branch-info"
                                )
                            ], md=4, id="pipeline-branch-col"),
                            dbc.Col([
                                dbc.Label([
                                    "Local Pipeline Path ",
                                    html.Span(id="pipeline-path-status", className="ms-1")
                                ], html_for="pipeline-local-path-input"),
                                dbc.InputGroup([
                                    dbc.Input(
                                        id="pipeline-local-path-input",
                                        type="text",
                                        placeholder="/path/to/nanometanf"
                                    ),
                                    dbc.Button(
                                        [html.I(className="bi bi-folder2-open me-1"), "Browse"],
                                        id="browse-pipeline-path",
                                        color="secondary",
                                        outline=True
                                    )
                                ]),
                                dbc.FormText("Path to local nanometanf directory (must contain main.nf)")
                            ], md=4, id="pipeline-local-path-col", style={"display": "none"})
                        ])
                    ])
                ], className="mb-3"),

                # Processing Settings
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-cpu me-2"),
                        html.Strong("Processing Settings")
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Pipeline Profile ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="profile-info")
                                ], html_for="pipeline-profile-input"),
                                dbc.Select(
                                    id="pipeline-profile-input",
                                    options=[
                                        {"label": "Docker (Recommended)", "value": "docker"},
                                        {"label": "Singularity", "value": "singularity"},
                                        {"label": "Conda", "value": "conda"},
                                        {"label": "Local (no containers)", "value": "standard"}
                                    ],
                                    value="docker"
                                ),
                                dbc.FormText("Container/environment system for tools"),
                                dbc.Tooltip(
                                    "Docker: Best for most users. Singularity: HPC clusters. "
                                    "Conda: If Docker unavailable. Local: Tools must be in PATH.",
                                    target="profile-info"
                                )
                            ], md=6),
                            dbc.Col([
                                dbc.Label("Check Interval (seconds)", html_for="check-interval-input"),
                                dbc.Input(
                                    id="check-interval-input",
                                    type="number",
                                    min=5,
                                    max=300,
                                    step=5,
                                    value=15
                                ),
                                dbc.FormText("How often to check for new data")
                            ], md=6)
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Minimum Reads per Level", html_for="min-reads-per-level-input"),
                                dbc.Input(
                                    id="min-reads-per-level-input",
                                    type="number",
                                    min=1,
                                    step=1,
                                    value=10
                                ),
                                dbc.FormText("Filter low-abundance taxa")
                            ], md=6),
                            dbc.Col([
                                dbc.Switch(
                                    id="memory-mapping-input",
                                    label="Use memory mapping for Kraken2",
                                    value=True,
                                    className="mt-3"
                                ),
                                dbc.FormText("Reduces RAM usage but may be slower")
                            ], md=6)
                        ])
                    ])
                ], className="mb-3"),

                # Validation Settings
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-shield-check me-2"),
                        html.Strong("Pathogen Validation")
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Switch(
                                    id="blast-validation-input",
                                    label="Enable validation",
                                    value=False
                                ),
                                dbc.FormText("Validate detected species against reference genomes")
                            ], md=3),
                            dbc.Col([
                                dbc.Label("Method", html_for="validation-method-input"),
                                dcc.Dropdown(
                                    id="validation-method-input",
                                    options=[
                                        {"label": "BLAST (per-read validation)", "value": "blast"},
                                        {"label": "minimap2 (mapping statistics)", "value": "minimap2"},
                                        {"label": "Both (validation + mapping)", "value": "both"}
                                    ],
                                    value="both",
                                    clearable=False
                                )
                            ], md=3),
                            dbc.Col([
                                dbc.Label("Min Identity (%)", html_for="min-identity-input"),
                                dbc.Input(
                                    id="min-identity-input",
                                    type="number",
                                    min=50,
                                    max=100,
                                    step=1,
                                    value=90
                                )
                            ], md=3),
                            dbc.Col([
                                dbc.Label("E-value Cutoff", html_for="e-value-cutoff-input"),
                                dbc.Input(
                                    id="e-value-cutoff-input",
                                    type="number",
                                    min=0,
                                    max=1,
                                    step=0.001,
                                    value=0.01
                                )
                            ], md=3)
                        ]),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("minimap2 Preset", html_for="minimap2-preset-input"),
                                dbc.Select(
                                    id="minimap2-preset-input",
                                    options=[
                                        {"label": "map-ont (Oxford Nanopore)", "value": "map-ont"},
                                        {"label": "map-hifi (PacBio HiFi)", "value": "map-hifi"},
                                        {"label": "map-pb (PacBio CLR)", "value": "map-pb"}
                                    ],
                                    value="map-ont"
                                ),
                                dbc.FormText("Alignment preset for minimap2")
                            ], md=6),
                            dbc.Col([
                                dbc.Label("Min Mapping Quality", html_for="minimap2-min-mapq-input"),
                                dbc.Input(
                                    id="minimap2-min-mapq-input",
                                    type="number",
                                    min=0,
                                    max=60,
                                    step=1,
                                    value=30
                                ),
                                dbc.FormText("Minimum MAPQ to count as mapped")
                            ], md=6)
                        ], className="mt-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Genome Cache Directory", html_for="genome-cache-dir-input"),
                                dbc.Input(
                                    id="genome-cache-dir-input",
                                    type="text",
                                    value="~/.nanometa",
                                    placeholder="Path to genome cache (default: ~/.nanometa)"
                                ),
                                dbc.FormText("Location for downloaded reference genomes")
                            ], md=12)
                        ], className="mt-3"),
                        html.Div([
                            html.I(className="bi bi-info-circle me-2"),
                            html.Span(
                                "Genomes are downloaded automatically for enabled watchlist pathogens. "
                                "Enable pathogens in the Watchlist tab and download genomes before starting.",
                                className="text-muted small"
                            )
                        ], className="mt-2")
                    ])
                ], className="mb-3"),

                # Performance Settings
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-speedometer2 me-2"),
                        html.Strong("Performance")
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("CPU Cores", html_for="cores-input"),
                                dbc.Input(
                                    id="cores-input",
                                    type="number",
                                    min=1,
                                    step=1,
                                    value=4
                                ),
                                dbc.FormText("Number of processing threads")
                            ], md=4),
                            dbc.Col([
                                dbc.Label("GUI Port", html_for="gui-port-input"),
                                dbc.Input(
                                    id="gui-port-input",
                                    type="number",
                                    min=1024,
                                    max=65535,
                                    step=1,
                                    value=8050
                                ),
                                dbc.FormText("Web interface port")
                            ], md=4),
                            dbc.Col([
                                dbc.Switch(
                                    id="clean-temp-input",
                                    label="Clean temp files",
                                    value=True,
                                    className="mt-4"
                                ),
                                dbc.FormText("Remove after processing")
                            ], md=4)
                        ])
                    ])
                ])
            ], title="Advanced Settings (Optional)")
        ], start_collapsed=True, className="mb-4"),

    ])
