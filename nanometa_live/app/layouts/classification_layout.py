"""
Classification visualization layout for Nanometa Live v2.0.

This layout combines Sankey and Sunburst visualizations into a single
tab with toggleable views, supporting per-sample and aggregated analysis.

MODERNIZED: Added explanatory text, help sections, and operator-friendly guidance.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

from nanometa_live.app.components.sample_selector import create_sample_selector


def create_classification_layout() -> html.Div:
    """
    Create the classification tab layout with Sankey/Sunburst toggle.

    Returns:
        html.Div containing the classification visualization components
    """
    return html.Div([dbc.Container([
        # Header row with title, view toggle, and color scheme
        dbc.Row([
            # Title + view selector
            dbc.Col([
                html.H4("Organism Classification Relationships", className="mb-2"),
                dbc.RadioItems(
                    id='classification-view-type',
                    options=[
                        {'label': ' Sankey Diagram', 'value': 'sankey'},
                        {'label': ' Sunburst Chart', 'value': 'sunburst'}
                    ],
                    value='sankey',
                    inline=True,
                    className="mb-0"
                ),
            ], md=8),

            # Color scheme selector
            dbc.Col([
                html.Label("Color Scheme:", className="fw-bold mb-1", style={"fontSize": "0.9rem"}),
                dbc.Select(
                    id='classification-color-scheme',
                    options=[
                        {'label': 'Viridis (Colorblind-safe)', 'value': 'viridis'},
                        {'label': 'Tableau (Scientific)', 'value': 'tableau'},
                        {'label': 'Dark (High contrast)', 'value': 'dark'},
                    ],
                    value='viridis',
                ),
            ], md=3)
        ], className="mb-2", align="end"),

        # Essential filter - always visible (Phase 2.2)
        dbc.Row([
            dbc.Col([
                html.Label([
                    html.I(className="bi bi-funnel me-2"),
                    "Minimum DNA Sequences:"
                ], className="fw-bold"),
                dbc.InputGroup([
                    dbc.Input(
                        id='classification-filter-input',
                        type='number',
                        value=10,
                        min=1,
                        step=1
                    ),
                    dbc.Button(
                        "Apply",
                        id='apply-classification-settings',
                        color="primary"
                    )
                ]),
                html.Small(
                    "Hide organisms with fewer sequences than this value",
                    className="text-muted"
                )
            ], md=3),
            dbc.Col([
                html.Label([
                    html.I(className="bi bi-bar-chart-steps me-2"),
                    "Max Taxa Per Level:"
                ], className="fw-bold"),
                dbc.Select(
                    id='classification-max-taxa',
                    options=[
                        {'label': '5 taxa', 'value': '5'},
                        {'label': '10 taxa (default)', 'value': '10'},
                        {'label': '15 taxa', 'value': '15'},
                        {'label': '20 taxa', 'value': '20'},
                        {'label': '30 taxa', 'value': '30'},
                        {'label': '50 taxa', 'value': '50'},
                        {'label': 'All (no limit)', 'value': '0'},
                    ],
                    value='10',
                ),
                html.Small(
                    "Limit organisms shown at each classification level",
                    className="text-muted"
                )
            ], md=3),
            dbc.Col([
                html.Label([
                    html.I(className="bi bi-arrows-expand me-2"),
                    "Chart Height:"
                ], className="fw-bold"),
                dbc.Select(
                    id='classification-chart-height',
                    options=[
                        {'label': 'Auto (adaptive)', 'value': 'auto'},
                        {'label': 'Small (600px)', 'value': '600'},
                        {'label': 'Medium (800px)', 'value': '800'},
                        {'label': 'Large (1000px)', 'value': '1000'},
                        {'label': 'X-Large (1200px)', 'value': '1200'},
                        {'label': 'XX-Large (1500px)', 'value': '1500'},
                        {'label': 'Full Page (2000px)', 'value': '2000'},
                    ],
                    value='auto',
                ),
                html.Small(
                    "Auto adjusts based on number of taxa",
                    className="text-muted"
                )
            ], md=3),
            dbc.Col([
                dbc.Button(
                    [html.I(className="bi bi-download me-2"), "Export"],
                    id='export-classification-button',
                    color="secondary",
                    outline=True,
                    size="sm",
                    className="float-end"
                )
            ], md=3, className="d-flex align-items-end justify-content-end")
        ], className="mb-3"),

        # Advanced filter controls (collapsible - optional)
        dbc.Accordion([
            dbc.AccordionItem([
                dbc.Row([
                    # Domain selector
                    dbc.Col([
                        html.Label("Show Life Domains:", className="fw-bold"),
                        dcc.Dropdown(
                            id='classification-domains-input',
                            options=[
                                {'label': 'Bacteria (most common)', 'value': 'Bacteria'},
                                {'label': 'Archaea (rare microbes)', 'value': 'Archaea'},
                                {'label': 'Eukaryota (complex cells)', 'value': 'Eukaryota'},
                                {'label': 'Viruses', 'value': 'Viruses'}
                            ],
                            value=['Bacteria', 'Archaea', 'Eukaryota', 'Viruses'],
                            multi=True,
                            className="mb-2"
                        ),
                        html.Small(
                            "Select which major life groups to display",
                            className="text-muted"
                        )
                    ], md=5),

                    # Taxonomy levels selector
                    dbc.Col([
                        html.Label("Classification Levels to Show:", className="fw-bold"),
                        html.Div(
                            id='classification-levels-container',
                            children=[
                                # Preset selector with descriptive labels
                                html.Label("Preset Views:", className="fw-bold mt-2 mb-1", style={"fontSize": "0.9rem"}),
                                dbc.Select(
                                    id='classification-level-preset',
                                    options=[
                                        {'label': 'Standard (Phylum to Species)', 'value': 'standard'},
                                        {'label': 'Overview (Domain, Kingdom, Phylum, Class)', 'value': 'overview'},
                                        {'label': 'Species Focus (Family, Genus, Species)', 'value': 'species_focus'},
                                        {'label': 'Clinical (Family to Species)', 'value': 'clinical'},
                                        {'label': 'Full Taxonomy (all 8 levels)', 'value': 'full'},
                                        {'label': 'Custom (select levels below)', 'value': 'custom'},
                                    ],
                                    value='standard',
                                ),
                                html.Small(
                                    "Standard: general analysis. Overview: broad community structure. "
                                    "Species Focus / Clinical: identification to species level.",
                                    className="text-muted d-block mt-1 mb-2"
                                ),
                                # Manual multi-select for custom level filtering
                                html.Label("Individual Levels:", className="fw-bold mt-2 mb-1", style={"fontSize": "0.9rem"}),
                                dcc.Dropdown(
                                    id='classification-levels-input',
                                    options=[
                                        {'label': 'D - Domain', 'value': 'D'},
                                        {'label': 'K - Kingdom', 'value': 'K'},
                                        {'label': 'P - Phylum', 'value': 'P'},
                                        {'label': 'C - Class', 'value': 'C'},
                                        {'label': 'O - Order', 'value': 'O'},
                                        {'label': 'F - Family', 'value': 'F'},
                                        {'label': 'G - Genus', 'value': 'G'},
                                        {'label': 'S - Species', 'value': 'S'}
                                    ],
                                    value=['P', 'C', 'O', 'F', 'G', 'S'],  # Match 'standard' preset
                                    multi=True,
                                    className="mb-2"
                                ),
                                html.Small(
                                    "Select 'Custom' preset to freely choose levels. "
                                    "At least 2 levels are needed for Sankey diagrams.",
                                    className="text-muted"
                                )
                            ]
                        )
                    ], md=7)
                ])
            ], title="Advanced Filter Options", id="classification-filters-accordion")
        ], start_collapsed=True, className="mb-3"),

        # Divider
        html.Hr(),

        # Visualization container
        dbc.Row([
            dbc.Col([
                dcc.Loading(
                    id='classification-loading',
                    type='default',
                    children=[
                        dcc.Graph(
                            id='classification-plot',
                            config={
                                'displayModeBar': True,
                                'displaylogo': False,
                                'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                                'toImageButtonOptions': {
                                    'format': 'svg',
                                    'filename': 'taxonomy_visualization'
                                }
                            },
                            # Height is controlled dynamically via figure.update_layout
                            style={
                                'width': '100%'
                            }
                        )
                    ]
                )
            ])
        ]),

        # Info message area
        dbc.Row([
            dbc.Col([
                html.Div(id='classification-info-message', className="mt-3")
            ])
        ]),

        # Hidden div for clientside label-repositioning callback
        html.Div(id='classification-label-reposition', style={'display': 'none'}),

        html.Hr(className="my-4"),

        # Help Section - contextual to selected chart type
        html.Div(id='classification-help-section'),

        # Export modal
        dbc.Modal([
            dbc.ModalHeader("Export Classification Visualization"),
            dbc.ModalBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Export Directory:"),
                        dbc.Input(
                            id='classification-export-dir',
                            type='text',
                            placeholder='Leave empty to use default (reports/)',
                        )
                    ])
                ], className="mb-3"),
                dbc.Row([
                    dbc.Col([
                        html.Label("Filename:"),
                        dbc.Input(
                            id='classification-export-filename',
                            type='text',
                            placeholder='classification_plot',
                        )
                    ])
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id='cancel-classification-export', color="secondary"),
                dbc.Button("Export", id='confirm-classification-export', color="primary")
            ])
        ], id='classification-export-modal', is_open=False),

    ], fluid=True)], className="p-4")
