"""
Configuration form component for Nanometa Live v2.0.

This module defines a simplified two-mode configuration interface:
- Essential Settings: Output directory, Kraken2 database, processing mode
- Advanced Settings: Technical parameters (collapsible)

Species watchlist management is handled in the dedicated Watchlist tab.
"""

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
                    dbc.Badge("Start here", color="primary", className="ms-2",
                              style={"fontSize": "0.7rem", "verticalAlign": "middle"})
                ], className="d-flex align-items-center")
            ]),
            dbc.CardBody([
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
                            "The folder where your sequencer writes data files. "
                            "Look for a folder containing .fastq or .fastq.gz files.",
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
                            "Species Identification Database ",
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
                            "Folder containing the Kraken2 reference database used to identify organisms. "
                            "If you do not have one, download it from the Preparation tab.",
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
                            "Where the analysis saves its output files (species reports, "
                            "quality data, and validation results). Defaults to a folder "
                            "in your home directory if left empty.",
                            target="results-dir-info"
                        ),
                        dbc.FormText(
                            "Where to save analysis results and reports",
                            className="text-muted"
                        )
                    ], md=12)
                ], className="mb-4"),

                # Pipeline Profile (essential - determines how pipeline runs)
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
                            value="docker",
                            persistence=True,
                            persistence_type="session",
                        ),
                        dbc.Tooltip(
                            "How pipeline tools (Kraken2, fastp, etc.) are run. "
                            "Docker: Best for most users, requires Docker Desktop. "
                            "Singularity: For HPC clusters. "
                            "Conda: If Docker is unavailable. "
                            "Local: Tools must already be installed in your PATH.",
                            target="profile-info"
                        ),
                        dbc.FormText("How to run pipeline tools (requires Docker Desktop, Conda, or local install)")
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
                                dbc.Label([
                                    "Update Interval (seconds) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="update-interval-info")
                                ], html_for="update-interval-input"),
                                dbc.Input(
                                    id="update-interval-input",
                                    type="number",
                                    min=5,
                                    max=300,
                                    step=5,
                                    value=30
                                ),
                                dbc.FormText("How often the dashboard refreshes (5-300 seconds)"),
                                dbc.Tooltip(
                                    "Controls how frequently the dashboard charts and tables update. "
                                    "Lower values show results faster but increase CPU usage. "
                                    "Different from Check Interval which controls pipeline file scanning.",
                                    target="update-interval-info"
                                )
                            ], md=6),
                            dbc.Col([
                                dbc.Label([
                                    "Alert Threshold (reads) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="alert-threshold-info")
                                ], html_for="danger-threshold-input"),
                                dbc.Input(
                                    id="danger-threshold-input",
                                    type="number",
                                    min=1,
                                    step=10,
                                    value=100
                                ),
                                dbc.FormText("Minimum reads before an organism triggers a dashboard alert"),
                                dbc.Tooltip(
                                    "When an organism reaches this many classified reads, "
                                    "it will appear in the dashboard alerts panel. "
                                    "Lower values are more sensitive but may produce false alerts.",
                                    target="alert-threshold-info"
                                )
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
                        # Hidden input to maintain backward compatibility
                        dbc.Input(id="kraken-taxonomy-input", type="hidden", value="gtdb"),
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
                                    "Analysis Name ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="analysis-name-info")
                                ], html_for="analysis-name-input"),
                                dbc.Input(
                                    id="analysis-name-input",
                                    type="text",
                                    placeholder="My Nanopore Analysis",
                                ),
                                dbc.FormText("Optional label for this analysis run"),
                                dbc.Tooltip(
                                    "Give your analysis a descriptive name for easy reference",
                                    target="analysis-name-info"
                                )
                            ], md=6),
                            dbc.Col([
                                dbc.Label([
                                    "Check Interval (seconds) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="check-interval-info")
                                ], html_for="check-interval-input"),
                                dbc.Input(
                                    id="check-interval-input",
                                    type="number",
                                    min=5,
                                    max=300,
                                    step=5,
                                    value=15
                                ),
                                dbc.FormText("How often the pipeline checks for new input files"),
                                dbc.Tooltip(
                                    "Controls how frequently the Nextflow pipeline scans for new FASTQ files. "
                                    "Lower values detect files faster but use more resources. "
                                    "Different from the dashboard Update Interval which controls GUI refresh.",
                                    target="check-interval-info"
                                )
                            ], md=6)
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Realtime Timeout (minutes) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="realtime-timeout-minutes-info")
                                ], html_for="realtime-timeout-minutes-input"),
                                dbc.Input(
                                    id="realtime-timeout-minutes-input",
                                    type="number",
                                    min=1,
                                    max=10080,
                                    step=1,
                                    value=60,
                                    placeholder="Leave empty to run indefinitely"
                                ),
                                dbc.FormText(
                                    "Stop real-time monitoring after this many minutes without new files. "
                                    "Empty = run until manually stopped."
                                ),
                                dbc.Tooltip(
                                    "Only applies in real-time mode. The pipeline watches for new FASTQ files "
                                    "and stops when no new files appear within this window. Maps to nanometanf's "
                                    "--realtime_timeout_minutes. Default 60; clear the field for no timeout.",
                                    target="realtime-timeout-minutes-info"
                                )
                            ], md=6)
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Minimum Detection Count ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="min-reads-info")
                                ], html_for="min-reads-per-level-input"),
                                dbc.Input(
                                    id="min-reads-per-level-input",
                                    type="number",
                                    min=1,
                                    step=1,
                                    value=10
                                ),
                                dbc.FormText("Hide organisms detected fewer times than this"),
                                dbc.Tooltip(
                                    "Organisms detected fewer times than this value are hidden "
                                    "from the classification charts. Higher values reduce noise "
                                    "but may hide rare species. Default: 10.",
                                    target="min-reads-info"
                                )
                            ], md=6),
                            dbc.Col([
                                html.Div([
                                    dbc.Switch(
                                        id="memory-mapping-input",
                                        label="Low-memory mode",
                                        value=True,
                                        className="mt-3"
                                    ),
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="memory-mapping-info"),
                                    dbc.Badge("Recommended", color="success", className="ms-2",
                                              style={"fontSize": "0.65rem"}),
                                ], className="d-flex align-items-center"),
                                dbc.FormText("Uses less memory; recommended for laptops and field computers"),
                                dbc.Tooltip(
                                    "When enabled, the species database is read from disk instead of "
                                    "being loaded entirely into memory. Recommended for portable "
                                    "computers and large databases.",
                                    target="memory-mapping-info"
                                )
                            ], md=6)
                        ])
                    ])
                ], className="mb-3"),

                # Validation Settings
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-shield-check me-2"),
                        html.Strong("Confirmation Testing"),
                        html.I(className="bi bi-info-circle text-muted ms-2",
                               id="validation-section-info",
                               style={"fontSize": "0.85rem", "cursor": "help"}),
                        dbc.Tooltip(
                            "After initial species identification, confirmation testing "
                            "compares DNA sequences against known reference genomes to "
                            "verify results. This reduces false positives.",
                            target="validation-section-info",
                        ),
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Switch(
                                    id="blast-validation-input",
                                    label="Enable confirmation testing",
                                    value=False
                                ),
                                dbc.FormText("Double-check detected species against reference genomes")
                            ], md=3),
                            dbc.Col([
                                dbc.Label([
                                    "Confirmation Method ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="validation-method-info"),
                                ], html_for="validation-method-input"),
                                dcc.Dropdown(
                                    id="validation-method-input",
                                    options=[
                                        {"label": "Sequence search (thorough)", "value": "blast"},
                                        {"label": "Genome alignment (fast)", "value": "minimap2"},
                                        {"label": "Both (recommended)", "value": "both"}
                                    ],
                                    value="both",
                                    clearable=False
                                ),
                                dbc.Tooltip(
                                    "Sequence search (BLAST) checks individual DNA reads against "
                                    "a reference. Genome alignment (minimap2) maps reads to a full "
                                    "genome. Using both gives the highest confidence.",
                                    target="validation-method-info"
                                )
                            ], md=3),
                            dbc.Col([
                                dbc.Label([
                                    "Min. Similarity (%) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="min-identity-info"),
                                ], html_for="min-identity-input"),
                                dbc.Input(
                                    id="min-identity-input",
                                    type="number",
                                    min=50,
                                    max=100,
                                    step=1,
                                    value=90
                                ),
                                dbc.FormText("90% is recommended"),
                                dbc.Tooltip(
                                    "How closely a DNA sequence must match the reference "
                                    "to count as a confirmed identification. "
                                    "90% is a good default for nanopore data.",
                                    target="min-identity-info"
                                )
                            ], md=3),
                            dbc.Col([
                                dbc.Label([
                                    "Strictness Filter ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="evalue-info")
                                ], html_for="e-value-cutoff-input"),
                                dbc.Input(
                                    id="e-value-cutoff-input",
                                    type="number",
                                    min=0,
                                    max=1,
                                    step=0.001,
                                    value=0.01
                                ),
                                dbc.FormText("0.01 is recommended"),
                                dbc.Tooltip(
                                    "Controls how strict sequence matching is. "
                                    "Lower values are stricter (fewer false positives). "
                                    "0.01 is recommended for most uses.",
                                    target="evalue-info"
                                )
                            ], md=3)
                        ]),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Sequencing Platform ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="minimap2-preset-info"),
                                ], html_for="minimap2-preset-input"),
                                dbc.Select(
                                    id="minimap2-preset-input",
                                    options=[
                                        {"label": "Oxford Nanopore (default)", "value": "map-ont"},
                                        {"label": "Short reads <500 bp (amplicons)", "value": "sr"},
                                        {"label": "PacBio HiFi", "value": "map-hifi"},
                                        {"label": "PacBio CLR", "value": "map-pb"}
                                    ],
                                    value="map-ont"
                                ),
                                dbc.FormText("Select your sequencing instrument type or sr for short amplicons"),
                                dbc.Tooltip(
                                    "Choose the sequencing technology that produced your data. "
                                    "Use 'Short reads' (sr) for amplicons under ~500 bp where "
                                    "the long-read preset under-aligns. "
                                    "This adjusts alignment sensitivity to match the error profile "
                                    "of your instrument.",
                                    target="minimap2-preset-info"
                                )
                            ], md=6),
                            dbc.Col([
                                dbc.Label([
                                    "Alignment Confidence ",
                                    html.I(className="bi bi-info-circle text-muted ms-1", id="mapq-info")
                                ], html_for="minimap2-min-mapq-input"),
                                dbc.Input(
                                    id="minimap2-min-mapq-input",
                                    type="number",
                                    min=0,
                                    max=60,
                                    step=1,
                                    value=30
                                ),
                                dbc.FormText("30 is recommended (scale 0-60)"),
                                dbc.Tooltip(
                                    "Minimum confidence score (0-60) for genome alignments. "
                                    "Higher values keep only highly confident matches. "
                                    "30 is recommended; use 0 to accept all.",
                                    target="mapq-info"
                                )
                            ], md=6)
                        ], className="mt-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Reference Genome Storage ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="genome-cache-info"),
                                ], html_for="genome-cache-dir-input"),
                                dbc.Input(
                                    id="genome-cache-dir-input",
                                    type="text",
                                    value="~/.nanometa",
                                    placeholder="Path to genome cache (default: ~/.nanometa)"
                                ),
                                dbc.FormText("Where downloaded reference genomes are stored on this computer"),
                                dbc.Tooltip(
                                    "Folder where reference genomes are cached locally. "
                                    "These are downloaded once and reused across analyses.",
                                    target="genome-cache-info"
                                )
                            ], md=12)
                        ], className="mt-3"),
                        html.Div([
                            html.I(className="bi bi-info-circle me-2"),
                            html.Span(
                                "Reference genomes are downloaded in the Preparation tab. "
                                "Enable the organisms you want to monitor in the Watchlist tab first.",
                                className="text-muted small"
                            )
                        ], className="mt-2")
                    ])
                ], className="mb-3"),

                # Pipeline Options
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-sliders2 me-2"),
                        html.Strong("Analysis Options")
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Quality Filter ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="qc-tool-info"),
                                ], html_for="qc-tool-input"),
                                dbc.Select(
                                    id="qc-tool-input",
                                    options=[
                                        {"label": "fastp (recommended)", "value": "fastp"},
                                        {"label": "chopper", "value": "chopper"},
                                    ],
                                    value="fastp"
                                ),
                                dbc.FormText("Tool used to filter out low-quality DNA sequences"),
                                dbc.Tooltip(
                                    "Filters low-quality DNA sequences before species "
                                    "identification. fastp is recommended for most users.",
                                    target="qc-tool-info"
                                )
                            ], md=4),
                            dbc.Col([
                                dbc.Switch(
                                    id="skip-nanoplot-input",
                                    label="Skip detailed QC report",
                                    value=False,
                                    className="mt-3"
                                ),
                                dbc.FormText("Makes analysis faster but produces fewer quality details")
                            ], md=4),
                            dbc.Col([
                                dbc.Switch(
                                    id="kraken2-incremental-input",
                                    label="Running totals in live mode",
                                    value=True,
                                    className="mt-3"
                                ),
                                dbc.FormText("Show cumulative species counts during live sequencing"),
                                dbc.Badge("Recommended", color="success",
                                          style={"fontSize": "0.6rem", "verticalAlign": "middle"}),
                            ], md=4),
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Switch(
                                    id="enable-krona-input",
                                    label="Generate interactive taxonomy charts",
                                    value=False,
                                    className="mt-1"
                                ),
                                dbc.FormText("Creates browsable species classification charts (slower)")
                            ], md=4),
                            dbc.Col([
                                dbc.Switch(
                                    id="enable-nanopore-stats-input",
                                    label="Include sequencing quality summary",
                                    value=False,
                                    className="mt-1"
                                ),
                                dbc.FormText("Adds sequencer-specific metrics to the combined report")
                            ], md=4),
                        ]),
                    ])
                ], className="mb-3"),

                # Read filtering and validation -- amplicon-friendly
                # overrides for the long-read defaults. Operators
                # running V3-V4 / 16S / ITS amplicons (any read pile
                # under 1 kb) need to relax the chopper / filtlong
                # length filter or all reads are dropped at QC.
                # See docs/audit-2026-04-29-short-amplicons.md for
                # the rationale and recommended preset.
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-funnel me-2"),
                        html.Strong("Read Filtering and Validation"),
                    ], className="py-2"),
                    dbc.CardBody([
                        dbc.Alert(
                            [
                                html.I(className="bi bi-info-circle me-2"),
                                html.Strong("For amplicon or short-read protocols: "),
                                "lower the length filter and validation identity. "
                                "The defaults below assume ONT whole-genome reads (5-50 kb).",
                            ],
                            color="light",
                            className="small py-2 mb-3 border",
                        ),

                        # Row 1: chopper / filtlong length filters
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Chopper minimum length (bp) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="chopper-minlength-info"),
                                ], html_for="chopper-minlength-input"),
                                dbc.Input(
                                    id="chopper-minlength-input",
                                    type="number",
                                    min=0,
                                    max=50000,
                                    step=50,
                                    value=1000,
                                ),
                                dbc.FormText("Reads shorter than this are dropped (set to 100 for V3-V4 amplicons; 0 disables)"),
                                dbc.Tooltip(
                                    "Chopper's --minlength filter. Default 1000 is "
                                    "tuned for whole-genome ONT reads. For V3-V4 "
                                    "(~460 bp) set to 100; for ITS/16S amplicons "
                                    "use 250-500. Set to 0 to disable length "
                                    "filtering entirely.",
                                    target="chopper-minlength-info",
                                ),
                            ], md=4),
                            dbc.Col([
                                dbc.Label([
                                    "Chopper minimum quality (Q) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="chopper-quality-info"),
                                ], html_for="chopper-quality-input"),
                                dbc.Input(
                                    id="chopper-quality-input",
                                    type="number",
                                    min=0,
                                    max=30,
                                    step=1,
                                    value=10,
                                ),
                                dbc.FormText("Per-read mean Q-score threshold (lower for short ONT reads)"),
                                dbc.Tooltip(
                                    "Chopper's --quality filter. ONT short-read "
                                    "Q-scores trend lower than long-read because "
                                    "the Q-score ramp-up region is a larger "
                                    "fraction of a short read. Try 7 for amplicons.",
                                    target="chopper-quality-info",
                                ),
                            ], md=4),
                            dbc.Col([
                                dbc.Label([
                                    "Filtlong minimum length (bp) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="filtlong-minlength-info"),
                                ], html_for="filtlong-minlength-input"),
                                dbc.Input(
                                    id="filtlong-minlength-input",
                                    type="number",
                                    min=0,
                                    max=50000,
                                    step=50,
                                    value=1000,
                                ),
                                dbc.FormText("Only used when QC tool is filtlong (above)"),
                                dbc.Tooltip(
                                    "Filtlong's --min_length filter. Same "
                                    "amplicon guidance as chopper_minlength: "
                                    "100 for V3-V4, 250-500 for ITS/16S.",
                                    target="filtlong-minlength-info",
                                ),
                            ], md=4),
                        ], className="mb-3"),

                        # Row 2: validation identity + Kraken2 confidence
                        # Minimap2 preset (incl. the new ``sr`` short-read
                        # option for amplicons) and MAPQ threshold live in
                        # the Validation Settings card above; keeping them
                        # there avoids duplicate component IDs.
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Validation identity threshold (%) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="validation-identity-info"),
                                ], html_for="validation-identity-input"),
                                dbc.Input(
                                    id="validation-identity-input",
                                    type="number",
                                    min=0,
                                    max=100,
                                    step=1,
                                    value=90,
                                ),
                                dbc.FormText("Percent identity required to confirm a read"),
                                dbc.Tooltip(
                                    "Minimum percent identity for a read to "
                                    "count as confirming validation. The 90% "
                                    "default is hard for short ONT reads to "
                                    "clear because Q-score noise hits short "
                                    "reads proportionally harder. Try 80% for "
                                    "amplicons.",
                                    target="validation-identity-info",
                                ),
                            ], md=6),
                            dbc.Col([
                                html.Div([
                                    html.I(className="bi bi-arrow-up-circle me-2 text-muted"),
                                    html.Span(
                                        "Minimap2 preset and MAPQ threshold are "
                                        "in Validation Settings above. Switch to "
                                        "'Short reads <500 bp (amplicons)' for "
                                        "amplicon protocols.",
                                        className="small text-muted",
                                    ),
                                ], className="mt-4"),
                            ], md=6),
                        ], className="mb-3"),

                        # Row 3: kraken2 confidence
                        dbc.Row([
                            dbc.Col([
                                dbc.Label([
                                    "Kraken2 confidence (0.0-1.0) ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="kraken2-confidence-info"),
                                ], html_for="kraken2-confidence-input"),
                                dbc.Input(
                                    id="kraken2-confidence-input",
                                    type="number",
                                    min=0,
                                    max=1,
                                    step=0.05,
                                    value=0.0,
                                ),
                                dbc.FormText("Per-read classification confidence (0 disables)"),
                                dbc.Tooltip(
                                    "Kraken2 --confidence flag. 0 means accept "
                                    "every classification; raise (0.05-0.2) if "
                                    "you see noise in low-abundance taxa. "
                                    "Database-dependent.",
                                    target="kraken2-confidence-info",
                                ),
                            ], md=6),
                            dbc.Col([
                                dbc.Label([
                                    "Kraken2 minimum hit groups ",
                                    html.I(className="bi bi-info-circle text-muted ms-1",
                                           id="kraken2-hitgroups-info"),
                                ], html_for="kraken2-hitgroups-input"),
                                dbc.Input(
                                    id="kraken2-hitgroups-input",
                                    type="number",
                                    min=0,
                                    max=10,
                                    step=1,
                                    value=0,
                                ),
                                dbc.FormText("Hit groups required (0 disables)"),
                                dbc.Tooltip(
                                    "Kraken2 --minimum-hit-groups. Requires at "
                                    "least N distinct k-mer regions to support "
                                    "a classification. Lowers false positives "
                                    "but loses sensitivity on short reads.",
                                    target="kraken2-hitgroups-info",
                                ),
                            ], md=6),
                        ]),
                    ]),
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
                                dbc.Label("Dashboard Port", html_for="gui-port-input"),
                                dbc.Input(
                                    id="gui-port-input",
                                    type="number",
                                    min=1024,
                                    max=65535,
                                    step=1,
                                    value=8050
                                ),
                                dbc.FormText("Network port for this web interface (default: 8050)")
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
            ], title="Advanced Settings -- only change if you know what you need")
        ], start_collapsed=True, className="mb-4"),

    ])
