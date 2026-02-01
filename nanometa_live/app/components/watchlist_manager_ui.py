"""
Watchlist Manager UI Component for Nanometa Live.

Provides a comprehensive UI for managing species watchlists:
- Enable/disable builtin watchlists
- Import custom watchlist files
- Toggle individual pathogens
- Edit alert thresholds
- View taxonomy indicator
"""

from typing import Any, Dict, List, Optional
from dash import html, dcc
import dash_bootstrap_components as dbc


def create_watchlist_section(
    available_watchlists: Optional[List[Dict[str, Any]]] = None,
    taxonomy_indicator: str = "Auto",
    id_prefix: str = "watchlist"
) -> html.Div:
    """
    Create the main watchlist management section.

    Args:
        available_watchlists: List of available watchlist metadata
        taxonomy_indicator: Current taxonomy mode indicator
        id_prefix: Prefix for component IDs

    Returns:
        html.Div containing the watchlist management UI
    """
    if available_watchlists is None:
        available_watchlists = []

    # Group watchlists by source
    builtin = [w for w in available_watchlists if w.get("source") == "builtin"]
    user = [w for w in available_watchlists if w.get("source") == "user"]
    project = [w for w in available_watchlists if w.get("source") == "project"]

    return html.Div([
        # Header with taxonomy indicator
        dbc.Row([
            dbc.Col([
                html.H5("Species Watchlist", className="mb-0"),
            ], width=8),
            dbc.Col([
                dbc.Badge(
                    f"Taxonomy: {taxonomy_indicator}",
                    id=f"{id_prefix}-taxonomy-badge",
                    color="info",
                    className="float-end"
                ),
            ], width=4, className="text-end"),
        ], className="mb-3 align-items-center"),

        # Built-in watchlists section
        _create_watchlist_category(
            title="Built-in Watchlists",
            watchlists=builtin,
            source="builtin",
            id_prefix=id_prefix,
            collapsible=False
        ),

        # Custom watchlists section (user + project)
        html.Div([
            _create_watchlist_category(
                title="Custom Watchlists",
                watchlists=user + project,
                source="custom",
                id_prefix=id_prefix,
                collapsible=True,
                show_import=True
            ),
        ], className="mt-3") if user or project else html.Div([
            # Import section when no custom watchlists
            _create_import_section(id_prefix)
        ], className="mt-3"),

        # Quick add species section
        _create_quick_add_section(id_prefix),

        # Active watchlist summary
        _create_active_summary(id_prefix),

        # Hidden stores
        dcc.Store(id=f"{id_prefix}-enabled-list", data=[]),
        dcc.Store(id=f"{id_prefix}-config-store", data={}),
    ], className="watchlist-manager")


def _create_watchlist_category(
    title: str,
    watchlists: List[Dict[str, Any]],
    source: str,
    id_prefix: str,
    collapsible: bool = True,
    show_import: bool = False
) -> html.Div:
    """Create a category section for watchlists."""
    if not watchlists and not show_import:
        return html.Div()

    watchlist_items = []
    for wl in watchlists:
        watchlist_items.append(
            _create_watchlist_item(wl, id_prefix)
        )

    content = html.Div([
        *watchlist_items,
        _create_import_section(id_prefix) if show_import else html.Div()
    ])

    if collapsible:
        return dbc.Card([
            dbc.CardHeader(
                dbc.Row([
                    dbc.Col(html.H6(title, className="mb-0"), width=8),
                    dbc.Col(
                        dbc.Badge(
                            f"{len(watchlists)} lists",
                            color="secondary"
                        ),
                        width=4,
                        className="text-end"
                    ),
                ], align="center"),
                style={"cursor": "pointer"},
                id=f"{id_prefix}-{source}-header"
            ),
            dbc.Collapse(
                dbc.CardBody(content),
                id=f"{id_prefix}-{source}-collapse",
                is_open=True
            ),
        ], className="mb-2")
    else:
        return dbc.Card([
            dbc.CardHeader(
                dbc.Row([
                    dbc.Col(html.H6(title, className="mb-0"), width=8),
                    dbc.Col(
                        dbc.Badge(
                            f"{len(watchlists)} lists",
                            color="secondary"
                        ),
                        width=4,
                        className="text-end"
                    ),
                ], align="center"),
            ),
            dbc.CardBody(content),
        ], className="mb-2")


def _create_watchlist_item(wl: Dict[str, Any], id_prefix: str) -> html.Div:
    """Create a single watchlist item row."""
    wl_id = wl.get("id", "")
    name = wl.get("name", "Unknown")
    description = wl.get("description", "")
    pathogen_count = wl.get("pathogen_count", 0)
    enabled = wl.get("enabled", False)
    source = wl.get("source", "builtin")

    # Source badge color
    source_colors = {
        "builtin": "primary",
        "user": "success",
        "project": "warning"
    }

    return html.Div([
        dbc.Row([
            # Checkbox and name
            dbc.Col([
                dbc.Checkbox(
                    id={"type": f"{id_prefix}-wl-toggle", "index": wl_id},
                    value=enabled,
                    className="d-inline-block me-2"
                ),
                html.Span(name, className="fw-bold"),
                dbc.Badge(
                    source.title(),
                    color=source_colors.get(source, "secondary"),
                    pill=True,
                    className="ms-2 small"
                ),
            ], width=6),

            # Pathogen count
            dbc.Col([
                html.Small(
                    f"{pathogen_count} pathogens",
                    className="text-muted"
                ),
            ], width=3, className="text-center"),

            # Actions
            dbc.Col([
                dbc.ButtonGroup([
                    dbc.Button(
                        html.I(className="bi bi-eye"),
                        id={"type": f"{id_prefix}-wl-view", "index": wl_id},
                        size="sm",
                        color="secondary",
                        outline=True,
                        title="View pathogens"
                    ),
                    dbc.Button(
                        html.I(className="bi bi-sliders"),
                        id={"type": f"{id_prefix}-wl-configure", "index": wl_id},
                        size="sm",
                        color="secondary",
                        outline=True,
                        title="Configure"
                    ),
                ], size="sm"),
            ], width=3, className="text-end"),
        ], align="center", className="py-2"),

        # Description tooltip
        html.Small(
            description,
            className="text-muted d-block ms-4"
        ) if description else html.Div(),

    ], className="watchlist-item border-bottom py-1")


def _create_import_section(id_prefix: str) -> html.Div:
    """Create the import/upload section for custom watchlists."""
    return html.Div([
        dcc.Upload(
            id=f"{id_prefix}-upload",
            children=html.Div([
                html.I(className="bi bi-upload me-2"),
                "Import Watchlist File"
            ]),
            style={
                "border": "1px dashed var(--bs-secondary)",
                "borderRadius": "5px",
                "padding": "10px 15px",
                "textAlign": "center",
                "cursor": "pointer",
                "backgroundColor": "var(--bs-light)"
            },
            multiple=False,
            accept=".yaml,.yml"
        ),
        html.Small(
            "Accepts YAML watchlist files",
            className="text-muted d-block text-center mt-1"
        ),
        html.Div(
            id=f"{id_prefix}-upload-feedback",
            className="mt-2"
        ),
    ], className="mt-2")


def _create_quick_add_section(id_prefix: str) -> html.Div:
    """Create the quick-add species section."""
    return dbc.Card([
        dbc.CardHeader(
            html.H6("Quick Add Species", className="mb-0")
        ),
        dbc.CardBody([
            dbc.InputGroup([
                dbc.Input(
                    id=f"{id_prefix}-quick-input",
                    type="text",
                    placeholder="Species name or taxid...",
                    debounce=True
                ),
                dbc.Button(
                    [html.I(className="bi bi-plus-lg me-1"), "Add"],
                    id=f"{id_prefix}-quick-add-btn",
                    color="primary",
                    n_clicks=0
                ),
            ]),
            html.Div(
                id=f"{id_prefix}-quick-feedback",
                className="mt-2"
            ),
        ]),
    ], className="mt-3")


def _create_active_summary(id_prefix: str) -> html.Div:
    """Create the active watchlist summary section."""
    return dbc.Card([
        dbc.CardHeader([
            dbc.Row([
                dbc.Col([
                    html.H6("Currently Active", className="mb-0 d-inline"),
                    dbc.Badge(
                        "0",
                        id=f"{id_prefix}-active-count",
                        color="primary",
                        className="ms-2"
                    ),
                ], width=8),
                dbc.Col([
                    dbc.Button(
                        "Manage All",
                        id=f"{id_prefix}-manage-all-btn",
                        size="sm",
                        color="link",
                        className="p-0"
                    ),
                ], width=4, className="text-end"),
            ], align="center"),
        ]),
        dbc.CardBody([
            html.Div(
                id=f"{id_prefix}-active-list",
                className="active-species-list"
            ),
        ], style={"maxHeight": "300px", "overflowY": "auto"}),
    ], className="mt-3")


def create_active_species_list(
    entries: List[Dict[str, Any]],
    id_prefix: str = "watchlist"
) -> html.Div:
    """
    Create the list of active species with toggle controls.

    Args:
        entries: List of watchlist entry dicts
        id_prefix: Prefix for component IDs

    Returns:
        html.Div containing the active species list
    """
    if not entries:
        return html.Div(
            "No species in watchlist. Enable watchlists or add species above.",
            className="text-muted fst-italic py-2 text-center"
        )

    # Group by threat level
    threat_groups = {
        "critical": [],
        "high": [],
        "moderate": [],
        "low": []
    }

    for entry in entries:
        level = entry.get("threat_level", "moderate")
        if level in threat_groups:
            threat_groups[level].append(entry)

    sections = []
    threat_colors = {
        "critical": "danger",
        "high": "warning",
        "moderate": "info",
        "low": "secondary"
    }

    for level, level_entries in threat_groups.items():
        if not level_entries:
            continue

        # Level header
        sections.append(
            html.Div([
                dbc.Badge(
                    f"{level.title()} ({len(level_entries)})",
                    color=threat_colors.get(level, "secondary"),
                    className="mb-2"
                ),
            ])
        )

        # Entries
        for entry in level_entries[:10]:  # Limit display
            sections.append(
                _create_species_row(entry, id_prefix)
            )

        if len(level_entries) > 10:
            sections.append(
                html.Small(
                    f"...and {len(level_entries) - 10} more",
                    className="text-muted d-block text-center my-2"
                )
            )

    return html.Div(sections)


def _create_species_row(entry: Dict[str, Any], id_prefix: str) -> html.Div:
    """Create a single species row in the active list."""
    taxid = entry.get("taxid", 0)
    name = entry.get("name", "Unknown")
    threat_level = entry.get("threat_level", "moderate")
    enabled = entry.get("enabled", True)
    threshold = entry.get("alert_threshold", 10)

    threat_colors = {
        "critical": "danger",
        "high": "warning",
        "moderate": "info",
        "low": "secondary"
    }

    return html.Div([
        dbc.Row([
            # Toggle and name
            dbc.Col([
                dbc.Checkbox(
                    id={"type": f"{id_prefix}-entry-toggle", "index": taxid},
                    value=enabled,
                    className="d-inline-block me-2"
                ),
                html.Span(
                    name,
                    className="small" + (" text-decoration-line-through text-muted" if not enabled else "")
                ),
            ], width=7),

            # Threshold
            dbc.Col([
                dbc.Badge(
                    f"T:{threshold}",
                    color=threat_colors.get(threat_level, "secondary"),
                    pill=True,
                    className="small",
                    id={"type": f"{id_prefix}-threshold-badge", "index": taxid}
                ),
            ], width=2, className="text-center"),

            # Actions
            dbc.Col([
                dbc.Button(
                    html.I(className="bi bi-pencil"),
                    id={"type": f"{id_prefix}-entry-edit", "index": taxid},
                    size="sm",
                    color="link",
                    className="p-0",
                    title="Edit threshold"
                ),
            ], width=3, className="text-end"),
        ], align="center", className="py-1 border-bottom"),
    ], className="species-row")


def create_taxonomy_selector(
    current_mode: str = "auto",
    id_prefix: str = "watchlist"
) -> html.Div:
    """
    Create a taxonomy mode selector.

    Args:
        current_mode: Current taxonomy mode
        id_prefix: Prefix for component IDs

    Returns:
        html.Div containing the taxonomy selector
    """
    return html.Div([
        html.Label("Taxonomy Mode:", className="small fw-bold mb-1"),
        dbc.RadioItems(
            id=f"{id_prefix}-taxonomy-mode",
            options=[
                {"label": "Auto-detect", "value": "auto"},
                {"label": "NCBI", "value": "ncbi"},
                {"label": "GTDB", "value": "gtdb"},
            ],
            value=current_mode,
            inline=True,
            className="small"
        ),
    ], className="taxonomy-selector mb-3")


def create_watchlist_stats_card(
    stats: Dict[str, Any],
    id_prefix: str = "watchlist"
) -> dbc.Card:
    """
    Create a card displaying watchlist statistics.

    Args:
        stats: Statistics dict from WatchlistManager.get_statistics()
        id_prefix: Prefix for component IDs

    Returns:
        dbc.Card with statistics display
    """
    by_level = stats.get("by_threat_level", {})

    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Span(
                            str(stats.get("active_entries", 0)),
                            className="h3 mb-0"
                        ),
                        html.Small(" active", className="text-muted"),
                    ]),
                ], width=3),
                dbc.Col([
                    html.Div([
                        dbc.Badge(
                            f"{by_level.get('critical', 0)} Critical",
                            color="danger",
                            className="me-1"
                        ),
                        dbc.Badge(
                            f"{by_level.get('high', 0)} High",
                            color="warning",
                            className="me-1"
                        ),
                    ]),
                ], width=6),
                dbc.Col([
                    dbc.Badge(
                        stats.get("taxonomy_indicator", "Auto"),
                        color="info"
                    ),
                ], width=3, className="text-end"),
            ], align="center"),
        ]),
    ], className="mb-3", id=f"{id_prefix}-stats-card")
