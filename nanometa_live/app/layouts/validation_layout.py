"""
Validation results layout for Nanometa Live v2.1.

Split into two sub-tabs:
1. Read Validation (BLAST) - sequence identity and read-level confirmation
2. Coverage Validation (minimap2) - genome coverage depth and breadth
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from nanometa_live.app.components.modern_components import EmptyStateMessage
from nanometa_live.app.utils.plotly_theme import CHART_CONFIG


def create_validation_status_card(
    confirmed: int = 0,
    partial: int = 0,
    low_confidence: int = 0,
    no_data: int = 0,
    total: int = 0,
    reads_validated: int = 0,
    reads_total: int = 0,
) -> dbc.Card:
    """
    Create a summary card showing validation status counts plus the
    aggregate read totals.

    The status counts (top row) tell the operator how many *species*
    fell into each confidence tier. The aggregate read row underneath
    answers a different question -- "of the reads we tested across
    those species, how many actually validated?" -- which is the
    metric clinical users keep asking for ("show absolute reads
    confirmed AND the percentage").

    Args:
        confirmed: Number of confirmed detections (>=80% validated reads)
        partial: Number of partial confirmations (50-80%)
        low_confidence: Low confidence detections (<50%)
        no_data: Species with no validation data
        total: Total species checked
        reads_validated: Reads that passed validation across all species
        reads_total: Total reads tested by the validation flow
            (Kraken2-classified reads handed to BLAST/minimap2)

    Returns:
        dbc.Card component
    """
    pct_validated = (
        (reads_validated / reads_total * 100.0) if reads_total > 0 else 0.0
    )

    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-shield-check me-2"),
            html.H5("Validation Summary", className="mb-0 d-inline")
        ]),
        dbc.CardBody([
            # Per-tier species counts. The H2 captions give a quick
            # at-a-glance read across the four confidence buckets.
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.H2(str(confirmed), className="text-success mb-0"),
                        html.Small("Confirmed", className="text-muted")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(str(partial), className="text-warning mb-0"),
                        html.Small("Partial", className="text-muted")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(str(low_confidence), className="text-danger mb-0"),
                        html.Small("Low Confidence", className="text-muted")
                    ], className="text-center")
                ], md=3),
                dbc.Col([
                    html.Div([
                        html.H2(str(no_data), className="text-secondary mb-0"),
                        html.Small("No Data", className="text-muted")
                    ], className="text-center")
                ], md=3),
            ]),
            html.Hr(className="my-3"),
            # Aggregate footer. Two lines: species-checked count, then
            # the actual read totals so operators can answer "is this
            # 5/5 reads or 5000/10000 reads?". Without absolute counts
            # the species-tier badges above are easy to misinterpret.
            dbc.Row([
                dbc.Col([
                    html.Small([
                        html.Strong("Species checked: "),
                        str(total),
                    ], className="text-muted d-block"),
                ], md=6, className="text-center text-md-end"),
                dbc.Col([
                    html.Small([
                        html.Strong(
                            f"{reads_validated:,} of {reads_total:,}",
                            className="me-1",
                        ),
                        html.Span(
                            "reads validated",
                            className="me-1 text-muted",
                        ),
                        html.Span(
                            f"({pct_validated:.1f}%)",
                            className="text-muted",
                        ),
                    ], className="d-block") if reads_total > 0 else html.Small(
                        "Reads validated: -- (no validation data)",
                        className="text-muted d-block",
                    ),
                ], md=6, className="text-center text-md-start"),
            ]),
        ])
    ], className="mb-4")


def _create_blast_tab() -> dbc.Tab:
    """Create the Read Validation (BLAST) sub-tab."""
    return dbc.Tab(
        label="Sequence Matching",
        tab_id="blast-tab",
        children=html.Div([
            # Summary container
            html.Div(id="blast-summary-container", className="mb-4"),

            # Empty state (shown when no data)
            html.Div(
                id="blast-empty-message",
                children=[
                    EmptyStateMessage(
                        title="No Validation Results",
                        message="No BLAST validation results available. Run the pipeline with BLAST validation enabled to see results here.",
                        icon="bi-shield-check"
                    )
                ]
            ),

            # Results section - hidden when no data loaded
            html.Div(
                id="blast-results-section",
                style={"display": "none"},
                children=[
                    # Controls row
                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Filter by Status:", className="fw-bold"),
                            dcc.Dropdown(
                                id="blast-status-filter",
                                options=[
                                    {"label": "All", "value": "all"},
                                    {"label": "Confirmed (>80%)", "value": "confirmed"},
                                    {"label": "Partial (50-80%)", "value": "partial"},
                                    {"label": "Low Confidence (<50%)", "value": "low"},
                                    {"label": "No Data", "value": "no_data"},
                                ],
                                value="all",
                                clearable=False,
                            )
                        ], md=3),
                        dbc.Col([
                            dbc.Label("Sort By:", className="fw-bold"),
                            dcc.Dropdown(
                                id="blast-sort-select",
                                options=[
                                    {"label": "Validation %", "value": "percent_validated"},
                                    {"label": "Read Count", "value": "validated_reads"},
                                    {"label": "Identity %", "value": "percent_identity_mean"},
                                    {"label": "Species Name", "value": "species"},
                                ],
                                value="percent_validated",
                                clearable=False,
                            )
                        ], md=3),
                        dbc.Col([
                            dbc.Button(
                                [html.I(className="bi bi-download me-2"), "Export Report"],
                                id="export-blast-button",
                                color="secondary",
                                outline=True,
                                className="float-end mt-4"
                            )
                        ], md=6, className="d-flex justify-content-end align-items-end")
                    ], className="mb-4"),

                    html.Hr(),

                    # Results cards container
                    html.Div(id="blast-results-container", className="mb-4"),

                    # Identity distribution plot (collapsible)
                    dbc.Accordion([
                        dbc.AccordionItem([
                            html.P(
                                "How closely the sample DNA matches each species' reference genome. "
                                "Scores above 95% are strong matches; below 90% should be treated with caution.",
                                className="text-muted mb-3",
                            ),
                            dcc.Loading(
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        id="blast-identity-plot",
                                        config=CHART_CONFIG,
                                        style={"height": "400px"},
                                    )
                                ]
                            )
                        ], title="Match % Distribution (Advanced)")
                    ], start_collapsed=True, className="mb-4"),

                    # Stats table (collapsible)
                    dbc.Accordion([
                        dbc.AccordionItem([
                            html.P(
                                "Full numerical results for each species checked. "
                                "Use for reporting or technical review.",
                                className="text-muted mb-3",
                            ),
                            dcc.Loading(
                                type="circle",
                                children=[
                                    dag.AgGrid(
                                        id="blast-stats-table",
                                        columnDefs=[
                                            {"headerName": "Species", "field": "species"},
                                            {"headerName": "Sample", "field": "sample_id"},
                                            {"headerName": "Total Seqs", "field": "total_reads", "type": "numericColumn",
                                             "headerTooltip": "Total sequences classified as this species"},
                                            {"headerName": "Confirmed", "field": "validated_reads", "type": "numericColumn",
                                             "headerTooltip": "Sequences confirmed by reference comparison"},
                                            {"headerName": "Confirmed %", "field": "percent_validated", "type": "numericColumn",
                                             "headerTooltip": "Percentage of sequences confirmed. 80%+ is strong evidence."},
                                            {"headerName": "Match %", "field": "percent_identity_mean", "type": "numericColumn",
                                             "headerTooltip": "How closely sequences match the reference. 95%+ is a strong match."},
                                            {"headerName": "Read Alignment %", "field": "coverage_breadth", "type": "numericColumn",
                                             "headerTooltip": "Average percentage of each sequence that aligned to the reference. Higher = stronger matches. Computed per-method: BLAST uses qcovs, minimap2 uses span/qlen."},
                                            {
                                                "headerName": "Status",
                                                "field": "status",
                                                "cellStyle": {
                                                    "styleConditions": [
                                                        {
                                                            "condition": "params.value === 'confirmed'",
                                                            "style": {"backgroundColor": "#d4edda", "color": "#155724"},
                                                        },
                                                        {
                                                            "condition": "params.value === 'partial'",
                                                            "style": {"backgroundColor": "#fff3cd", "color": "#664d03"},
                                                        },
                                                        {
                                                            "condition": "params.value === 'low'",
                                                            "style": {"backgroundColor": "#f8d7da", "color": "#721c24"},
                                                        },
                                                    ],
                                                },
                                            },
                                        ],
                                        rowData=[],
                                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                                        # Composite ``getRowId`` -- the
                                        # same species can appear in
                                        # multiple samples, so the row id
                                        # joins species + sample_id with a
                                        # delimiter that cannot occur in a
                                        # taxon name. Preserves sort,
                                        # filter, and selection across the
                                        # 30s interval tick that rewrites
                                        # rowData.
                                        dashGridOptions={
                                            "pagination": True,
                                            "paginationPageSize": 25,
                                            "getRowId": {
                                                "function": "params.data.species + '||' + params.data.sample_id"
                                            },
                                        },
                                    )
                                ]
                            )
                        ], title="Detailed Results Table (Advanced)")
                    ], start_collapsed=True, className="mb-4"),
                ]
            ),

            # Download component
            dcc.Download(id="download-blast-report"),
        ], className="pt-3")
    )


def _create_coverage_tab() -> dbc.Tab:
    """Create the Coverage Validation (minimap2) sub-tab."""
    return dbc.Tab(
        label="Genome Coverage",
        tab_id="coverage-tab",
        children=html.Div([
            # Summary container
            html.Div(id="coverage-summary-container", className="mb-4"),

            # Empty state (shown when no minimap2 data)
            html.Div(
                id="coverage-empty-message",
                children=[
                    EmptyStateMessage(
                        title="No Coverage Data",
                        message="No minimap2 coverage data available. Run minimap2 validation or select a validated species.",
                        icon="bi-bar-chart-line"
                    )
                ]
            ),

            # Controls row - only shown when minimap2 results exist
            html.Div(
                id="coverage-controls-section",
                style={"display": "none"},
                children=[
                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Species / Sample:", className="fw-bold"),
                            dcc.Dropdown(
                                id="coverage-species-selector",
                                placeholder="Select a species to view coverage...",
                                clearable=True,
                                persistence=True,
                                persistence_type="session",
                            ),
                        ], md=4),
                        dbc.Col([
                            dbc.Label([
                                "Confidence filter:",
                                dbc.Badge(
                                    "?",
                                    color="secondary",
                                    pill=True,
                                    className="ms-1",
                                    id="mapq-help-badge",
                                    style={"cursor": "pointer", "fontSize": "0.7rem"},
                                ),
                                dbc.Tooltip(
                                    "Filter out low-confidence alignments. "
                                    "0 = show everything, 20+ = show only reliable matches. "
                                    "Increase this value if you see noisy results.",
                                    target="mapq-help-badge",
                                    placement="top",
                                ),
                            ], className="fw-bold"),
                            dcc.Input(
                                id="coverage-mapq-filter",
                                type="number",
                                value=0,
                                min=0,
                                max=60,
                                step=1,
                                className="form-control",
                                style={"maxWidth": "120px"},
                            ),
                        ], md=2),
                        dbc.Col([
                            dbc.Label([
                                "Depth threshold:",
                                dbc.Badge(
                                    "?",
                                    color="secondary",
                                    pill=True,
                                    className="ms-1",
                                    id="depth-threshold-help-badge",
                                    style={"cursor": "pointer", "fontSize": "0.7rem"},
                                ),
                                dbc.Tooltip(
                                    "Below this depth (x), regions are highlighted red on the depth plot. "
                                    "The default of 10x is a reasonable starting point for whole-genome data. "
                                    "Lower it (1-5x) for amplicon or low-coverage protocols; "
                                    "raise it (20-50x) for high-depth WGS runs where 10x is below the noise floor.",
                                    target="depth-threshold-help-badge",
                                    placement="top",
                                ),
                            ], className="fw-bold"),
                            dcc.Input(
                                id="coverage-depth-threshold",
                                type="number",
                                value=10,
                                min=1,
                                max=1000,
                                step=1,
                                className="form-control",
                                style={"maxWidth": "120px"},
                            ),
                        ], md=3),
                        dbc.Col([
                            dbc.Button(
                                [html.I(className="bi bi-download me-2"), "Export Report"],
                                id="export-coverage-button",
                                color="secondary",
                                outline=True,
                                className="float-end mt-4"
                            )
                        ], md=3, className="d-flex justify-content-end align-items-end")
                    ], className="mb-3"),
                ]
            ),

            # Coverage plots section - hidden when no data is loaded
            html.Div(
                id="coverage-plots-section",
                style={"display": "none"},
                children=[
                    # Coverage stats badges
                    html.Div(id="coverage-stats-container", className="mb-3"),

                    # Main coverage depth plot (full width)
                    dcc.Loading(
                        type="circle",
                        children=[
                            dcc.Graph(
                                id="coverage-depth-plot",
                                config=CHART_CONFIG,
                                style={"height": "450px"},
                            )
                        ],
                    ),

                    # Cumulative + Histogram side by side
                    dbc.Row([
                        dbc.Col([
                            dcc.Loading(
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        id="coverage-cumulative-plot",
                                        config=CHART_CONFIG,
                                        style={"height": "280px"},
                                    )
                                ],
                            ),
                        ], md=6),
                        dbc.Col([
                            dcc.Loading(
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        id="coverage-histogram-plot",
                                        config=CHART_CONFIG,
                                        style={"height": "280px"},
                                    )
                                ],
                            ),
                        ], md=6),
                    ], className="mb-4"),
                ]
            ),

            html.Hr(),

            # Results cards container (minimap2 cards)
            html.Div(id="coverage-results-container", className="mb-4"),

            # Download component
            dcc.Download(id="download-coverage-report"),
        ], className="pt-3")
    )


def create_validation_layout() -> html.Div:
    """
    Create the validation results tab layout with BLAST and coverage sub-tabs.

    Returns:
        html.Div containing the validation visualization components
    """
    return html.Div([dbc.Container([
        # Page title
        html.H4("Species Confirmation Results", className="mb-3"),
        html.P(
            "This page checks whether the organisms identified by the classifier are "
            "correct by comparing the DNA sequences against known reference genomes. "
            "Species marked 'Confirmed' have strong evidence; 'Partial' or 'Low Confidence' "
            "results should be interpreted with caution.",
            className="text-muted mb-3",
        ),

        # Scope + criteria banner. The Validation tab's species set is
        # NOT the same as the Dashboard / Organism tab's species set --
        # validation only runs for taxids that the operator has added
        # to the watchlist AND for which a reference genome is
        # available. Organism / Dashboard tabs show every Kraken2
        # detection (subject to the abundance threshold). Operators
        # have repeatedly asked why species seen on the Organism tab
        # don't appear here; this banner spells out the reason and
        # the active cutoffs in one place.
        dbc.Alert(
            [
                html.Div([
                    html.I(className="bi bi-info-circle me-2"),
                    html.Strong("What you see here vs Dashboard / Organism tabs"),
                ], className="mb-2"),
                html.Ul([
                    html.Li([
                        html.Strong("Scope: "),
                        "validation runs only for species you have enabled in the ",
                        html.Em("Watchlist"),
                        " tab and for which a reference genome has been downloaded ",
                        "(Preparation tab). A Kraken2 hit on the Organism tab will not ",
                        "appear here unless those two preconditions are met.",
                    ]),
                    html.Li([
                        html.Strong("Sample filter: "),
                        "the global sample selector at the top of the dashboard "
                        "applies here too. ",
                        html.Span(id="validation-sample-scope-note", className="text-muted"),
                    ]),
                    html.Li([
                        html.Strong("Validation status thresholds: "),
                        html.Span(id="validation-criteria-note", className="text-muted"),
                    ]),
                ], className="mb-0 small"),
            ],
            color="light",
            className="border mb-4",
        ),

        # Shared data store
        dcc.Store(id="validation-data-store", data={}),

        # Sub-tabs
        dbc.Tabs(
            id="validation-sub-tabs",
            active_tab="blast-tab",
            persistence=True,
            persistence_type="session",
            children=[
                _create_blast_tab(),
                _create_coverage_tab(),
            ],
            className="mb-4",
        ),

        # Help Section (outside tabs)
        dbc.Card([
            dbc.CardHeader(html.H5("Understanding This Page", className="mb-0")),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.H6("What The Status Means", className="fw-bold mb-2"),
                        html.Ul([
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-check-circle-fill text-success me-2"),
                                ),
                                html.Strong("Confirmed: "),
                                "Strong match to a known reference genome. High confidence this organism is present."
                            ]),
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-exclamation-circle-fill text-warning me-2"),
                                ),
                                html.Strong("Partial: "),
                                "Some evidence, but not conclusive. May need more sequencing data or could be a related species."
                            ]),
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-x-circle-fill text-danger me-2"),
                                ),
                                html.Strong("Low Confidence: "),
                                "Weak match. The identification may be incorrect - treat with caution."
                            ]),
                            html.Li([
                                html.Span(
                                    html.I(className="bi bi-question-circle-fill text-secondary me-2"),
                                ),
                                html.Strong("No Data: "),
                                "Confirmation check has not run yet or no reference genome is available."
                            ])
                        ])
                    ], md=6),
                    dbc.Col([
                        html.H6("What To Do", className="fw-bold mb-2"),
                        html.Ul([
                            html.Li([
                                html.Strong("Confirmed species: "),
                                "Proceed with confidence. Report and act on findings."
                            ]),
                            html.Li([
                                html.Strong("Partial match: "),
                                "Continue sequencing for more data, or verify with an alternative method."
                            ]),
                            html.Li([
                                html.Strong("Low confidence: "),
                                "Do not rely on this identification. Re-sequence or use a different "
                                "detection method before taking action."
                            ]),
                            html.Li([
                                html.Strong("No data: "),
                                "Wait for the pipeline to finish, or check that validation is enabled "
                                "in the Configuration tab."
                            ]),
                        ])
                    ], md=6)
                ]),
                html.Hr(),
                html.P([
                    html.Strong("Important: "),
                    "Even confirmed results should be interpreted alongside other evidence. "
                    "Validation reduces false positives but does not replace clinical judgment."
                ], className="text-muted mb-0")
            ])
        ], className="mb-4", style={"backgroundColor": "#f8f9fa"}),

    ], fluid=True)], className="p-4")


def create_validation_result_card(
    species: str,
    taxid: int,
    status: str,
    percent_validated: float,
    percent_identity: float,
    total_reads: int,
    validated_reads: int,
    coverage: float = 0.0,
    sample_id: str = "",
    validation_method: str = "blast",
    avg_mapq: float = 0.0,
    show_coverage_button: bool = False
) -> dbc.Card:
    """
    Create a card displaying validation results for a single species.

    Args:
        species: Species name
        taxid: Taxonomy ID
        status: Validation status (confirmed, partial, low, no_data)
        percent_validated: Percentage of reads validated
        percent_identity: Mean identity percentage
        total_reads: Total reads from Kraken2
        validated_reads: Reads validated by BLAST
        coverage: Mean query alignment coverage fraction (0-1, from BLAST qcovs)
        sample_id: Sample identifier
        validation_method: Validation method used (blast or minimap2)
        avg_mapq: Average mapping quality (minimap2)
        show_coverage_button: Whether to show the View Coverage button

    Returns:
        dbc.Card component
    """
    status_config = {
        "confirmed": {
            "icon": "bi-check-circle-fill",
            "color": "success",
            "badge": "Confirmed",
            "border": "border-success"
        },
        "partial": {
            "icon": "bi-exclamation-circle-fill",
            "color": "warning",
            "badge": "Partial",
            "border": "border-warning"
        },
        "low": {
            "icon": "bi-x-circle-fill",
            "color": "danger",
            "badge": "Low Confidence",
            "border": "border-danger"
        },
        "no_data": {
            "icon": "bi-question-circle-fill",
            "color": "secondary",
            "badge": "No Data",
            "border": "border-secondary"
        },
        "failed": {
            "icon": "bi-exclamation-triangle-fill",
            "color": "dark",
            "badge": "Failed",
            "border": "border-dark"
        }
    }

    config = status_config.get(status, status_config["no_data"])

    # Plain-language explanation for the status
    status_explanation = {
        "confirmed": "Strong match to reference genome",
        "partial": "Some evidence, may need more data",
        "low": "Weak match - treat with caution",
        "no_data": "Confirmation not yet available",
        "failed": "Check did not complete",
    }

    return dbc.Card([
        dbc.CardHeader([
            dbc.Row([
                dbc.Col([
                    html.I(className=f"bi {config['icon']} text-{config['color']} me-2"),
                    html.Strong(species, style={"fontSize": "1.1rem"}),
                ], md=8),
                dbc.Col([
                    dbc.Badge(
                        config["badge"],
                        color=config["color"],
                        className="float-end"
                    ),
                ], md=4, className="text-end")
            ])
        ], className=f"py-2 {config['border']}"),
        dbc.CardBody([
            # Status explanation
            html.Div([
                html.Small(
                    status_explanation.get(status, ""),
                    className=f"text-{config['color']}",
                    style={"fontSize": "12px", "fontWeight": "500"}
                )
            ], className="mb-2"),
            # Three operator-facing metrics. The previous layout had
            # four columns where "Confirmed %" and "Sequences X/Y"
            # were two views of the same number; operators had to
            # mentally combine them to interpret. The new column 1
            # shows BOTH the absolute count (primary, since it
            # conveys statistical scale -- "5/5" vs "500/500" reads
            # very differently) and the percentage (secondary, for
            # at-a-glance comparison across cards).
            dbc.Row([
                # Validated reads -- absolute count + percentage in
                # one place
                dbc.Col([
                    html.Div([
                        html.Small(
                            "Reads validated",
                            className="text-muted d-block",
                        ),
                        html.Strong(
                            f"{validated_reads:,} of {total_reads:,}",
                            style={"fontSize": "1.2rem"},
                        ),
                        html.Small(
                            f"({percent_validated:.1f}%)",
                            className=f"text-{config['color']} d-block",
                            style={"fontSize": "0.85rem", "fontWeight": "500"},
                        ),
                    ])
                ], md=4),
                # Mean identity across the validated reads
                dbc.Col([
                    html.Div([
                        html.Small(
                            "Mean identity",
                            className="text-muted d-block",
                        ),
                        html.Strong(
                            f"{percent_identity:.1f}%",
                            style={"fontSize": "1.2rem"},
                        ),
                        html.Small(
                            "95%+ is a strong match",
                            className="text-muted d-block",
                            style={"fontSize": "0.75rem"},
                        ),
                    ])
                ], md=4),
                # Method-conditional: minimap2 mapq (0-60 scale) or
                # BLAST read-alignment % (qcovs averaged across
                # validated reads).
                dbc.Col([
                    html.Div([
                        html.Small(
                            "Mapping Confidence" if validation_method == "minimap2" else "Read Alignment %",
                            className="text-muted d-block"
                        ),
                        html.Strong(
                            f"{avg_mapq:.0f} / 60" if validation_method == "minimap2" else f"{coverage*100:.1f}%",
                            style={"fontSize": "1.2rem"}
                        ),
                        html.Small(
                            "30+ reliable" if validation_method == "minimap2" else "Higher = stronger",
                            className="text-muted d-block",
                            style={"fontSize": "0.75rem"},
                        ),
                    ])
                ], md=4),
            ]),
            html.Div([
                dbc.Progress(
                    value=percent_validated,
                    color=config["color"],
                    className="mt-3",
                    style={"height": "8px"}
                )
            ])
        ]),
        dbc.CardFooter([
            html.Small([
                html.Span(f"Sample: {sample_id}", className="me-3") if sample_id else "",
            ], className="text-muted d-inline"),
            dbc.Button(
                [html.I(className="bi bi-bar-chart-line me-1"), "View Coverage"],
                id={"type": "view-coverage-btn", "index": f"{sample_id}_{taxid}"},
                color="info",
                size="sm",
                outline=True,
                className="float-end",
            ) if show_coverage_button else html.Span(),
        ], className="py-1")
    ], className=f"mb-3 {config['border']}", style={"borderLeftWidth": "6px"})
