"""
Watchlist Modal Component for Nanometa Live.

Provides modal dialogs for:
- Viewing pathogens in a watchlist
- Configuring individual pathogen settings
- Editing alert thresholds
- Viewing pathogen details
"""

from typing import Any, Dict, List
from dash import html, dcc
import dash_bootstrap_components as dbc


def create_watchlist_view_modal(id_prefix: str = "watchlist") -> dbc.Modal:
    """
    Create the modal for viewing pathogens in a watchlist.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Modal component
    """
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle(
                id=f"{id_prefix}-view-modal-title"
            ),
        ]),
        dbc.ModalBody([
            # Watchlist info
            html.Div(
                id=f"{id_prefix}-view-modal-description",
                className="text-muted mb-3"
            ),

            # Filter/search
            dbc.InputGroup([
                dbc.InputGroupText(
                    html.I(className="bi bi-search")
                ),
                dbc.Input(
                    id=f"{id_prefix}-view-modal-search",
                    placeholder="Filter pathogens...",
                    type="text"
                ),
            ], className="mb-3"),

            # Pathogen list
            html.Div(
                id=f"{id_prefix}-view-modal-list",
                style={"maxHeight": "400px", "overflowY": "auto"}
            ),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Enable All",
                id=f"{id_prefix}-view-modal-enable-all",
                color="primary",
                outline=True,
                size="sm"
            ),
            dbc.Button(
                "Disable All",
                id=f"{id_prefix}-view-modal-disable-all",
                color="secondary",
                outline=True,
                size="sm"
            ),
            dbc.Button(
                "Close",
                id=f"{id_prefix}-view-modal-close",
                color="secondary"
            ),
        ]),
    ], id=f"{id_prefix}-view-modal", size="lg", scrollable=True)


def create_pathogen_list_content(
    pathogens: List[Dict[str, Any]],
    watchlist_id: str,
    id_prefix: str = "watchlist"
) -> html.Div:
    """
    Create the content for the pathogen list in the view modal.

    Args:
        pathogens: List of pathogen entries
        watchlist_id: ID of the current watchlist
        id_prefix: Prefix for component IDs

    Returns:
        html.Div with pathogen list
    """
    if not pathogens:
        return html.Div(
            "No pathogens in this watchlist.",
            className="text-muted text-center py-4"
        )

    rows = []
    threat_colors = {
        "critical": "danger",
        "high": "warning",
        "moderate": "info",
        "low": "secondary"
    }

    for p in pathogens:
        name = p.get("name", "Unknown")
        taxid = p.get("taxid") or p.get("taxid_ncbi", 0)
        common_name = p.get("common_name", "")
        threat_level = p.get("threat_level", "moderate")
        bsl = p.get("bsl_level")
        threshold = p.get("alert_threshold", 10)
        enabled = p.get("enabled", True)

        rows.append(
            html.Div([
                dbc.Row([
                    # Toggle
                    dbc.Col([
                        dbc.Checkbox(
                            id={"type": f"{id_prefix}-modal-toggle", "index": taxid},
                            value=enabled,
                        ),
                    ], width=1),

                    # Name and details
                    dbc.Col([
                        html.Div([
                            html.Span(
                                name,
                                className="fw-bold" + (
                                    " text-decoration-line-through text-muted"
                                    if not enabled else ""
                                )
                            ),
                            html.Small(
                                f" ({common_name})" if common_name else "",
                                className="text-muted"
                            ),
                        ]),
                        html.Small([
                            f"Taxid: {taxid}" if taxid else "Name-based matching",
                        ], className="text-muted"),
                    ], width=5),

                    # Badges
                    dbc.Col([
                        dbc.Badge(
                            threat_level.title(),
                            color=threat_colors.get(threat_level, "secondary"),
                            className="me-1"
                        ),
                        dbc.Badge(
                            f"BSL-{bsl}" if bsl else "N/A",
                            color="dark",
                            outline=True,
                            className="me-1"
                        ),
                    ], width=3),

                    # Threshold
                    dbc.Col([
                        dbc.Input(
                            type="number",
                            value=threshold,
                            min=1,
                            size="sm",
                            style={"width": "70px"},
                            id={"type": f"{id_prefix}-modal-threshold", "index": taxid},
                            disabled=not enabled
                        ),
                    ], width=2),

                    # Info button
                    dbc.Col([
                        dbc.Button(
                            html.I(className="bi bi-info-circle"),
                            id={"type": f"{id_prefix}-modal-info", "index": taxid},
                            size="sm",
                            color="link",
                            className="p-0"
                        ),
                    ], width=1, className="text-end"),
                ], align="center", className="py-2 border-bottom"),
            ], className="pathogen-row")
        )

    return html.Div([
        # Header row
        html.Div([
            dbc.Row([
                dbc.Col(html.Small(""), width=1),
                dbc.Col(html.Small("Pathogen", className="fw-bold"), width=5),
                dbc.Col(html.Small("Level", className="fw-bold"), width=3),
                dbc.Col(html.Small("Threshold", className="fw-bold"), width=2),
                dbc.Col(html.Small(""), width=1),
            ], className="py-1 bg-light border-bottom"),
        ]),
        # Rows
        html.Div(rows),
    ])


def create_pathogen_detail_modal(id_prefix: str = "watchlist") -> dbc.Modal:
    """
    Create the modal for viewing pathogen details.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Modal component
    """
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle(
                id=f"{id_prefix}-detail-modal-title"
            ),
        ]),
        dbc.ModalBody([
            html.Div(
                id=f"{id_prefix}-detail-modal-content"
            ),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Close",
                id=f"{id_prefix}-detail-modal-close",
                color="secondary"
            ),
        ]),
    ], id=f"{id_prefix}-detail-modal", size="md")


def create_pathogen_detail_content(pathogen: Dict[str, Any]) -> html.Div:
    """
    Create the detail content for a single pathogen.

    Args:
        pathogen: Pathogen entry dict

    Returns:
        html.Div with pathogen details
    """
    name = pathogen.get("name", "Unknown")
    common_name = pathogen.get("common_name", "")
    taxid = pathogen.get("taxid") or pathogen.get("taxid_ncbi", 0)
    threat_level = pathogen.get("threat_level", "moderate")
    bsl = pathogen.get("bsl_level")
    category = pathogen.get("category", "")
    notes = pathogen.get("notes", "")
    action_required = pathogen.get("action_required", "")
    threshold = pathogen.get("alert_threshold", 10)
    names_alt = pathogen.get("names_alt", [])
    watchlist_id = pathogen.get("watchlist_id", "")

    threat_colors = {
        "critical": "danger",
        "high": "warning",
        "moderate": "info",
        "low": "secondary"
    }

    return html.Div([
        # Header
        html.Div([
            html.H5(name, className="mb-1"),
            html.P(common_name, className="text-muted mb-3") if common_name else html.Div(),
        ]),

        # Badges
        html.Div([
            dbc.Badge(
                threat_level.upper(),
                color=threat_colors.get(threat_level, "secondary"),
                className="me-2"
            ),
            dbc.Badge(
                f"BSL-{bsl}" if bsl else "No BSL specified",
                color="dark",
                outline=True,
                className="me-2"
            ),
            dbc.Badge(
                category,
                color="primary",
                outline=True
            ) if category else html.Span(),
        ], className="mb-3"),

        # Details table
        html.Table([
            html.Tbody([
                html.Tr([
                    html.Td("NCBI Taxid:", className="fw-bold pe-3"),
                    html.Td(str(taxid) if taxid else "Name-based matching"),
                ]),
                html.Tr([
                    html.Td("Alert Threshold:", className="fw-bold pe-3"),
                    html.Td(f"{threshold} reads"),
                ]),
                html.Tr([
                    html.Td("Source:", className="fw-bold pe-3"),
                    html.Td(watchlist_id if watchlist_id else "User-defined"),
                ]),
            ])
        ], className="table table-sm mb-3"),

        # Alternative names
        html.Div([
            html.H6("Alternative Names (for GTDB matching):", className="mb-2"),
            html.Div([
                dbc.Badge(alt, color="secondary", className="me-1 mb-1")
                for alt in names_alt
            ] if names_alt else [
                html.Small("None specified", className="text-muted")
            ]),
        ], className="mb-3") if names_alt or True else html.Div(),

        # Notes
        html.Div([
            html.H6("Notes:", className="mb-2"),
            html.P(notes, className="small text-muted"),
        ], className="mb-3") if notes else html.Div(),

        # Action required
        html.Div([
            html.H6("Required Action:", className="mb-2"),
            dbc.Alert(
                action_required,
                color=threat_colors.get(threat_level, "info"),
                className="mb-0"
            ),
        ]) if action_required else html.Div(),
    ])


def create_threshold_edit_modal(id_prefix: str = "watchlist") -> dbc.Modal:
    """
    Create a quick threshold edit modal.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Modal component
    """
    return dbc.Modal([
        dbc.ModalHeader([
            dbc.ModalTitle("Edit Alert Threshold"),
        ]),
        dbc.ModalBody([
            html.Div(
                id=f"{id_prefix}-threshold-modal-name",
                className="mb-3"
            ),
            dbc.Label("Alert Threshold (reads):"),
            dbc.Input(
                id=f"{id_prefix}-threshold-modal-input",
                type="number",
                min=1,
                value=10
            ),
            html.Small(
                "Alert is triggered when reads exceed this threshold.",
                className="text-muted"
            ),
            # Hidden store for taxid
            dcc.Store(
                id=f"{id_prefix}-threshold-modal-taxid",
                data=0
            ),
        ]),
        dbc.ModalFooter([
            dbc.Button(
                "Save",
                id=f"{id_prefix}-threshold-modal-save",
                color="primary"
            ),
            dbc.Button(
                "Cancel",
                id=f"{id_prefix}-threshold-modal-cancel",
                color="secondary"
            ),
        ]),
    ], id=f"{id_prefix}-threshold-modal", size="sm")


def create_all_modals(id_prefix: str = "watchlist") -> html.Div:
    """
    Create all watchlist-related modals.

    Args:
        id_prefix: Prefix for component IDs

    Returns:
        html.Div containing all modals
    """
    return html.Div([
        create_watchlist_view_modal(id_prefix),
        create_pathogen_detail_modal(id_prefix),
        create_threshold_edit_modal(id_prefix),
    ])
