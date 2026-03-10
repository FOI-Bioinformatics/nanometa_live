"""
Taxonomy ID Mapping UI Components for Nanometa Live.

This module provides Dash UI components for displaying and managing
taxonomy ID mappings between NCBI and Kraken2 database taxids.

Components:
- Mapping Status Dashboard - Overview of mapping statistics
- Mapping Table - List of entries with status indicators
- Manual Mapping Modal - Interface for manual mapping overrides
- Mapping Controls - Re-scan, export/import buttons
"""

from typing import Any, Dict, List

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_mapping_status_dashboard(id_prefix: str = "taxmap") -> dbc.Card:
    """
    Create the mapping status dashboard card.

    Shows overall mapping statistics with visual indicators for
    exact, fuzzy, manual, and unmapped entries.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Card component
    """
    return dbc.Card([
        dbc.CardHeader([
            dbc.Row([
                dbc.Col([
                    html.H6("Taxonomy ID Mapping Status", className="mb-0"),
                ], width=8),
                dbc.Col([
                    dbc.Badge(
                        "Unknown Database",
                        id=f"{id_prefix}-db-type-badge",
                        color="secondary",
                        className="float-end"
                    ),
                ], width=4, className="text-end"),
            ], align="center"),
        ]),
        dbc.CardBody([
            # Overall mapping rate
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Span(
                            "0%",
                            id=f"{id_prefix}-mapped-pct",
                            className="h2 mb-0 text-primary"
                        ),
                        html.Small(" mapped", className="text-muted"),
                    ]),
                    dbc.Progress(
                        value=0,
                        id=f"{id_prefix}-mapped-progress",
                        color="primary",
                        className="mt-2",
                        style={"height": "8px"}
                    ),
                ], width=4),

                # Match type breakdown
                dbc.Col([
                    _create_match_type_indicators(id_prefix)
                ], width=8),
            ], className="mb-3"),

            # Last scan info
            html.Div([
                html.Small([
                    html.Strong("Last scan: "),
                    html.Span(id=f"{id_prefix}-last-scan", children="Never"),
                    html.Span(" | ", className="text-muted mx-2"),
                    html.Strong("Database: "),
                    html.Span(
                        id=f"{id_prefix}-db-path",
                        children="Not configured",
                        className="text-truncate",
                        style={"maxWidth": "300px", "display": "inline-block"}
                    ),
                ], className="text-muted"),
            ]),
        ]),
    ], className="mb-3 taxmap-dashboard")


def _create_match_type_indicators(id_prefix: str) -> html.Div:
    """Create visual indicators for each match type."""
    return html.Div([
        dbc.Row([
            # Exact match indicator
            dbc.Col([
                html.Div([
                    html.I(className="bi bi-check-circle-fill text-success me-2"),
                    html.Span("Exact", className="small"),
                    html.Br(),
                    html.Span(
                        "0",
                        id=f"{id_prefix}-exact-count",
                        className="h5 mb-0"
                    ),
                ], className="text-center"),
            ], width=3),

            # Fuzzy match indicator
            dbc.Col([
                html.Div([
                    html.I(className="bi bi-dash-circle-fill text-info me-2"),
                    html.Span("Fuzzy", className="small"),
                    html.Br(),
                    html.Span(
                        "0",
                        id=f"{id_prefix}-fuzzy-count",
                        className="h5 mb-0"
                    ),
                ], className="text-center"),
            ], width=3),

            # Manual override indicator
            dbc.Col([
                html.Div([
                    html.I(className="bi bi-pencil-fill text-warning me-2"),
                    html.Span("Manual", className="small"),
                    html.Br(),
                    html.Span(
                        "0",
                        id=f"{id_prefix}-manual-count",
                        className="h5 mb-0"
                    ),
                ], className="text-center"),
            ], width=3),

            # Unmapped indicator
            dbc.Col([
                html.Div([
                    html.I(className="bi bi-x-circle-fill text-danger me-2"),
                    html.Span("Unmapped", className="small"),
                    html.Br(),
                    html.Span(
                        "0",
                        id=f"{id_prefix}-unmapped-count",
                        className="h5 mb-0 text-danger"
                    ),
                ], className="text-center"),
            ], width=3),
        ]),
    ])


def create_mapping_controls(id_prefix: str = "taxmap") -> dbc.Card:
    """
    Create mapping control buttons.

    Includes re-scan, export/import, and options.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Card component
    """
    return dbc.Card([
        dbc.CardHeader([
            html.H6("Mapping Controls", className="mb-0"),
        ]),
        dbc.CardBody([
            dbc.Row([
                # Re-scan database button with loading state
                dbc.Col([
                    html.Div([
                        dbc.Button(
                            [
                                html.I(
                                    id=f"{id_prefix}-rescan-icon",
                                    className="bi bi-arrow-repeat me-2"
                                ),
                                html.Span(
                                    "Re-scan Database",
                                    id=f"{id_prefix}-rescan-text"
                                ),
                            ],
                            id=f"{id_prefix}-rescan-btn",
                            color="primary",
                            className="w-100",
                        ),
                        # Status message below button
                        html.Div(
                            id=f"{id_prefix}-rescan-status",
                            className="small text-center mt-1",
                            style={"minHeight": "20px"}
                        ),
                    ]),
                ], width=4),

                # Options
                dbc.Col([
                    dbc.Checklist(
                        id=f"{id_prefix}-rescan-options",
                        options=[
                            {
                                "label": " Preserve manual overrides",
                                "value": "preserve_manual"
                            },
                            {
                                "label": " Auto-accept high-confidence (>85%)",
                                "value": "auto_accept"
                            },
                        ],
                        value=["preserve_manual"],
                        inline=False,
                        className="small",
                    ),
                ], width=5),

                # Export/Import
                dbc.Col([
                    dbc.ButtonGroup([
                        dbc.Button(
                            [html.I(className="bi bi-download me-1"), "Export"],
                            id=f"{id_prefix}-export-btn",
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-upload me-1"), "Import"],
                            id=f"{id_prefix}-import-btn",
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                    ], vertical=True, className="w-100"),
                ], width=3),
            ], className="mb-3"),

            # Progress indicator (hidden by default)
            html.Div([
                html.P(
                    id=f"{id_prefix}-scan-status",
                    children="Ready to scan",
                    className="small text-muted mb-2"
                ),
                dbc.Progress(
                    id=f"{id_prefix}-scan-progress",
                    value=0,
                    striped=True,
                    animated=True,
                    className="mb-2",
                ),
            ], id=f"{id_prefix}-progress-container", style={"display": "none"}),

            # Validation feedback
            html.Div(id=f"{id_prefix}-validation-feedback"),
        ]),
    ], className="mb-3")


def create_mapping_table_section(id_prefix: str = "taxmap") -> dbc.Card:
    """
    Create the mapping table card.

    Shows all watchlist entries with their mapping status.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Card component
    """
    return dbc.Card([
        dbc.CardHeader([
            dbc.Row([
                dbc.Col([
                    html.H6("Watchlist Mappings", className="mb-0 d-inline"),
                    dbc.Badge(
                        "0",
                        id=f"{id_prefix}-entry-count",
                        color="primary",
                        className="ms-2"
                    ),
                ], width=4),
                dbc.Col([
                    dbc.InputGroup([
                        dbc.InputGroupText(html.I(className="bi bi-search")),
                        dbc.Input(
                            id=f"{id_prefix}-search-input",
                            type="text",
                            placeholder="Filter entries...",
                            debounce=True,
                        ),
                    ], size="sm"),
                ], width=4),
                dbc.Col([
                    dbc.Select(
                        id=f"{id_prefix}-filter-status",
                        options=[
                            {"label": "All Entries", "value": "all"},
                            {"label": "Exact Matches", "value": "exact"},
                            {"label": "Fuzzy Matches", "value": "fuzzy"},
                            {"label": "Manual Overrides", "value": "manual"},
                            {"label": "Unmapped Only", "value": "unmapped"},
                            {"label": "Needs Review", "value": "review"},
                        ],
                        value="all",
                        size="sm",
                    ),
                ], width=4, className="text-end"),
            ], align="center"),
        ]),
        dbc.CardBody([
            # Table header
            html.Div([
                dbc.Row([
                    dbc.Col(html.Small("Status", className="fw-bold"), width=1),
                    dbc.Col(html.Small("NCBI Name", className="fw-bold"), width=2),
                    dbc.Col(html.Small("NCBI TaxID", className="fw-bold"), width=1),
                    dbc.Col(html.Small("Kraken TaxID", className="fw-bold"), width=1),
                    dbc.Col(html.Small("Kraken Name", className="fw-bold"), width=3),
                    dbc.Col(html.Small("Score", className="fw-bold"), width=2),
                    dbc.Col(html.Small("Actions", className="fw-bold"), width=2),
                ], className="py-2 bg-light border-bottom"),
            ]),

            # Table body (populated by callback)
            html.Div(
                id=f"{id_prefix}-mapping-table",
                style={"maxHeight": "400px", "overflowY": "auto"}
            ),

            # Empty state
            html.Div([
                html.P(
                    "No mappings found. Load a watchlist and scan the database.",
                    className="text-muted text-center py-4"
                ),
            ], id=f"{id_prefix}-empty-state"),
        ]),
    ], className="mb-3")


def create_mapping_row(
    mapping: Dict[str, Any],
    id_prefix: str = "taxmap"
) -> html.Div:
    """
    Create a single mapping row.

    Args:
        mapping: Dict with mapping data
        id_prefix: Prefix for component IDs

    Returns:
        html.Div component
    """
    confidence = mapping.get("confidence", "unmapped")
    ncbi_taxid = mapping.get("ncbi_taxid", 0)

    # Status icons and colors
    status_config = {
        "exact": {"icon": "bi-check-circle-fill", "color": "text-success"},
        "fuzzy": {"icon": "bi-dash-circle-fill", "color": "text-info"},
        "partial": {"icon": "bi-question-circle-fill", "color": "text-warning"},
        "manual": {"icon": "bi-pencil-fill", "color": "text-warning"},
        "unmapped": {"icon": "bi-x-circle-fill", "color": "text-danger"},
    }

    config = status_config.get(confidence, status_config["unmapped"])
    score = mapping.get("match_score", 0.0)

    # Get Kraken name (database name)
    db_name = mapping.get("db_name", "")

    return html.Div([
        dbc.Row([
            # Status indicator
            dbc.Col([
                html.I(
                    className=f"bi {config['icon']} {config['color']}",
                    title=confidence.title(),
                ),
            ], width=1, className="text-center"),

            # NCBI Name
            dbc.Col([
                html.Span(
                    mapping.get("canonical_name", "Unknown"),
                    className="fw-bold" if confidence == "unmapped" else "",
                    style={"fontStyle": "italic"}
                ),
            ], width=2),

            # NCBI TaxID
            dbc.Col([
                html.Code(str(ncbi_taxid), className="small"),
            ], width=1),

            # Kraken TaxID
            dbc.Col([
                html.Code(
                    str(mapping.get("db_taxid", "-")),
                    className="small" + (" text-muted" if not mapping.get("db_taxid") else ""),
                ),
            ], width=1),

            # Kraken Name (database description)
            dbc.Col([
                html.Span(
                    db_name if db_name else "-",
                    className="text-muted" if not db_name else "",
                    style={"fontStyle": "italic", "fontSize": "0.9rem"},
                    title=db_name,  # Full name on hover
                ),
            ], width=3, className="text-truncate"),

            # Match Score
            dbc.Col([
                _create_score_badge(score),
            ], width=2),

            # Actions
            dbc.Col([
                dbc.ButtonGroup([
                    dbc.Button(
                        html.I(className="bi bi-pencil"),
                        id={"type": f"{id_prefix}-edit-mapping", "index": ncbi_taxid},
                        size="sm",
                        color="secondary",
                        outline=True,
                        title="Edit mapping",
                    ),
                ], size="sm"),
            ], width=2, className="text-end"),
        ], align="center", className="py-2 border-bottom mapping-row"),
    ])


def _create_score_badge(score: float) -> dbc.Badge:
    """Create a color-coded score badge."""
    if score >= 0.95:
        color = "success"
    elif score >= 0.8:
        color = "info"
    elif score >= 0.5:
        color = "warning"
    else:
        color = "secondary"

    return dbc.Badge(
        f"{score:.0%}" if score > 0 else "-",
        color=color,
        className="px-2",
    )


def create_manual_mapping_modal(id_prefix: str = "taxmap") -> dbc.Modal:
    """
    Create the manual mapping modal.

    Allows users to manually set taxid mappings.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Modal component
    """
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle("Manual Taxonomy Mapping"),
        ]),
        dbc.ModalBody([
            dcc.Store(id=f"{id_prefix}-edit-ncbi-taxid", data=None),

            # Entry being mapped
            dbc.Card([
                dbc.CardBody([
                    html.H6("Watchlist Entry", className="text-muted mb-2"),
                    dbc.Row([
                        dbc.Col([
                            html.Strong("Name: "),
                            html.Span(
                                id=f"{id_prefix}-edit-ncbi-name",
                                style={"fontStyle": "italic"}
                            ),
                        ], width=8),
                        dbc.Col([
                            html.Strong("NCBI TaxID: "),
                            html.Code(id=f"{id_prefix}-edit-ncbi-taxid-display"),
                        ], width=4),
                    ]),
                ]),
            ], className="mb-3 border-start border-primary border-3"),

            # Search Kraken database
            html.Div([
                html.H6("Search Kraken2 Database", className="mb-2"),
                dbc.InputGroup([
                    dbc.Input(
                        id=f"{id_prefix}-kraken-search",
                        type="text",
                        placeholder="Search by name or taxid...",
                        debounce=True,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-search me-1"), "Search"],
                        id=f"{id_prefix}-kraken-search-btn",
                        color="primary",
                        n_clicks=0,
                    ),
                ]),
                html.Small(
                    "Search the Kraken2 database for matching taxa",
                    className="text-muted"
                ),
            ], className="mb-3"),

            # Suggestions
            html.Div([
                html.H6("Suggested Matches", className="mb-2"),
                dcc.Loading(
                    id=f"{id_prefix}-suggestions-loading",
                    children=[
                        html.Div(id=f"{id_prefix}-suggestions-list")
                    ],
                    type="circle",
                ),
            ], className="mb-3"),

            # Selected mapping
            html.Div([
                html.H6("Selected Mapping", className="mb-2"),
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Strong("Kraken Name: "),
                                html.Span(
                                    id=f"{id_prefix}-selected-kraken-name",
                                    children="None selected",
                                    className="text-muted",
                                ),
                            ], width=8),
                            dbc.Col([
                                html.Strong("TaxID: "),
                                html.Code(
                                    id=f"{id_prefix}-selected-kraken-taxid",
                                    children="-",
                                ),
                            ], width=4),
                        ]),
                    ]),
                ], id=f"{id_prefix}-selected-card",
                   className="border-start border-success border-3",
                   style={"display": "none"}),
            ], className="mb-3"),

            # Notes field
            html.Div([
                dbc.Label("Mapping Notes (optional)", className="small"),
                dbc.Textarea(
                    id=f"{id_prefix}-mapping-notes",
                    placeholder="Why was this mapping chosen?",
                    rows=2,
                ),
            ]),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Clear Selection",
                id=f"{id_prefix}-clear-selection-btn",
                color="secondary",
                outline=True,
                n_clicks=0,
            ),
            dbc.Button(
                [html.I(className="bi bi-check-lg me-1"), "Confirm Mapping"],
                id=f"{id_prefix}-confirm-mapping-btn",
                color="success",
                disabled=False,  # Always enabled - validation done in callback
                n_clicks=0,
            ),
            dbc.Button(
                "Cancel",
                id=f"{id_prefix}-cancel-mapping-btn",
                color="secondary",
                n_clicks=0,
            ),
        ]),
    ], id=f"{id_prefix}-mapping-modal", size="lg", centered=True)


def create_mapping_section(id_prefix: str = "taxmap") -> html.Div:
    """
    Create the complete mapping section for the Watchlist tab.

    Combines dashboard, controls, and table into one section.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        html.Div containing all mapping components
    """
    return html.Div([
        # Stores
        dcc.Store(id=f"{id_prefix}-rescan-complete", data=None),
        dcc.Download(id=f"{id_prefix}-export-download"),

        # Dashboard
        create_mapping_status_dashboard(id_prefix),

        # Controls (collapsible)
        dbc.Collapse(
            create_mapping_controls(id_prefix),
            id=f"{id_prefix}-controls-collapse",
            is_open=True,
        ),

        # Table
        create_mapping_table_section(id_prefix),

        # Modal
        create_manual_mapping_modal(id_prefix),

    ], id=f"{id_prefix}-section", className="mapping-section")
