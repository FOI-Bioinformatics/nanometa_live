"""
Watchlist Tab Callbacks for Nanometa Live.

Handles all callback logic for the Watchlist management tab:
- Watchlist file toggles
- Pathogens table updates
- Individual pathogen toggle/edit
- API validation (manual button)
- Taxid mapping for Kraken2 database compatibility
- Add custom species with API lookup
- Genome downloads with progress tracking (background callbacks)
- BLAST database building with progress tracking (background callbacks)
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dash import Dash, Input, Output, State, callback_context, ALL, MATCH, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from dash import html

# Import background callback manager for async progress reporting
from nanometa_live.app.app import background_callback_manager

from nanometa_live.core.watchlist.watchlist_manager import (
    get_watchlist_manager,
    WatchlistEntry,
    ThreatLevel,
)
from nanometa_live.app.layouts.watchlist_layout import (
    create_pathogen_row,
    create_watchlist_file_item,
    create_api_lookup_result,
    create_api_details_content,
    create_missing_genome_item,
)
from nanometa_live.app.components.taxid_mapping_ui import (
    create_mapping_row,
)

logger = logging.getLogger(__name__)


def _create_suggestion_card(
    suggestion: Dict[str, Any],
    id_prefix: str = "taxmap",
    is_current: bool = False
) -> dbc.Button:
    """
    Create a clickable suggestion button styled as a card for the mapping modal.

    Args:
        suggestion: Dict with db_taxid, db_name, score, match_method/rank
        id_prefix: Prefix for component IDs
        is_current: If True, style as currently selected

    Returns:
        dbc.Button component styled as a card
    """
    db_taxid = suggestion.get("db_taxid", 0)
    db_name = suggestion.get("db_name", "Unknown")
    score = suggestion.get("score", 0.0)
    method = suggestion.get("match_method", suggestion.get("confidence", ""))
    rank = suggestion.get("rank", "")

    # Score color
    if score >= 0.9:
        score_color = "text-success"
    elif score >= 0.7:
        score_color = "text-info"
    elif score >= 0.5:
        score_color = "text-warning"
    else:
        score_color = "text-muted"

    # Build content for the button
    content = dbc.Row([
        dbc.Col([
            html.Div([
                html.Strong(db_name, className="d-block"),
                html.Small([
                    html.Code(f"taxid: {db_taxid}", className="me-2"),
                    html.Span(f"({rank})" if rank else "", className="text-muted"),
                ]),
            ]),
        ], width=8),
        dbc.Col([
            html.Div([
                html.Span(
                    f"{score:.0%}" if isinstance(score, (int, float)) else str(score),
                    className=f"h5 mb-0 {score_color}"
                ),
                html.Small(f" {method}", className="text-muted d-block"),
                dbc.Badge(
                    "Current",
                    color="success",
                    className="mt-1"
                ) if is_current else None,
            ], className="text-end"),
        ], width=4),
    ], align="center")

    return dbc.Button(
        content,
        id={"type": f"{id_prefix}-suggestion", "index": f"{db_taxid}:{db_name}"},
        color="success" if is_current else "light",
        className=f"mb-2 w-100 text-start {'border-success border-2' if is_current else ''}",
        style={"padding": "0.75rem 1rem", "whiteSpace": "normal", "height": "auto"},
        n_clicks=0,
    )


def register_watchlist_callbacks(app: Dash) -> None:
    """
    Register all watchlist tab callbacks.

    Args:
        app: Dash application instance
    """
    # ---------------------------------------------------------------------
    # Stats Bar Update
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-stat-total", "children"),
            Output("watchlist-stat-active", "children"),
            Output("watchlist-stat-validated", "children"),
            Output("watchlist-stat-critical", "children"),
            Output("watchlist-stat-high", "children"),
        ],
        [
            Input("watchlist-tab-state", "data"),
            Input("tabs", "active_tab"),
        ],
        State("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_stats(tab_state: Dict, active_tab: str, config: Dict) -> Tuple:
        """Update statistics displays in the stats bar."""
        manager = get_watchlist_manager()

        # Initialize manager with config if not loaded
        if not manager._loaded and config:
            manager.load_config(config)

        stats = manager.get_statistics()
        validation_status = manager.get_validation_status()

        by_threat = stats.get("by_threat_level", {})
        critical = by_threat.get("critical", 0)
        high = by_threat.get("high", 0)

        return (
            str(stats.get("total_entries", 0)),
            str(stats.get("active_entries", 0)),
            str(validation_status.get("validated", 0)),
            f"Critical: {critical}",
            f"High: {high}",
        )

    # ---------------------------------------------------------------------
    # Quick Start Section
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
            Output("quick-start-feedback", "children"),
        ],
        [
            Input("quick-start-clinical", "n_clicks"),
            Input("quick-start-foodborne", "n_clicks"),
            Input("quick-start-water", "n_clicks"),
            Input("quick-start-respiratory", "n_clicks"),
            Input("quick-start-cdc", "n_clicks"),
            Input("quick-start-who", "n_clicks"),
        ],
        State("watchlist-table-refresh", "data"),
        prevent_initial_call=True,
    )
    def quick_start_watchlist(clinical, foodborne, water, respiratory, cdc, who, current_refresh):
        """Toggle a predefined watchlist on/off with one click."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        watchlist_map = {
            "quick-start-clinical": "clinical_pathogens",
            "quick-start-foodborne": "foodborne",
            "quick-start-water": "who_drinking_water",
            "quick-start-respiratory": "respiratory",
            "quick-start-cdc": "cdc_bioterrorism",
            "quick-start-who": "who_priority",
        }

        wl_id = watchlist_map.get(button_id)
        if wl_id:
            manager = get_watchlist_manager()
            try:
                # Check if watchlist is currently enabled
                watchlists = manager.get_available_watchlists()
                is_enabled = any(
                    wl["id"] == wl_id and wl.get("enabled", False)
                    for wl in watchlists
                )

                new_refresh = (current_refresh or 0) + 1

                if is_enabled:
                    # Disable the watchlist
                    count = manager.disable_watchlist(wl_id)
                    feedback = html.Span([
                        html.I(className="bi bi-x-circle text-secondary me-1"),
                        f"Disabled {wl_id.replace('_', ' ').title()} ({count} entries removed)"
                    ], className="text-secondary")
                    return {"last_update": f"disable-{wl_id}"}, new_refresh, feedback
                else:
                    # Enable the watchlist
                    manager.enable_watchlist(wl_id)
                    pathogens = manager.get_watchlist_pathogens_preview(wl_id)
                    count = len(pathogens)
                    feedback = html.Span([
                        html.I(className="bi bi-check-circle text-success me-1"),
                        f"Enabled {wl_id.replace('_', ' ').title()} ({count} pathogens)"
                    ], className="text-success")
                    return {"last_update": f"enable-{wl_id}"}, new_refresh, feedback

            except Exception as e:
                logger.warning(f"Failed to toggle watchlist {wl_id}: {e}")
                feedback = html.Span([
                    html.I(className="bi bi-exclamation-triangle text-warning me-1"),
                    f"Error toggling watchlist: {str(e)}"
                ], className="text-warning")
                return no_update, no_update, feedback

        raise PreventUpdate

    # ---------------------------------------------------------------------
    # Quick Start Button Styling
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("quick-start-clinical", "color"),
            Output("quick-start-clinical", "outline"),
            Output("quick-start-foodborne", "color"),
            Output("quick-start-foodborne", "outline"),
            Output("quick-start-water", "color"),
            Output("quick-start-water", "outline"),
            Output("quick-start-respiratory", "color"),
            Output("quick-start-respiratory", "outline"),
            Output("quick-start-cdc", "color"),
            Output("quick-start-cdc", "outline"),
            Output("quick-start-who", "color"),
            Output("quick-start-who", "outline"),
        ],
        [
            Input("watchlist-tab-state", "data"),
            Input("watchlist-table-refresh", "data"),
        ],
        State("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_quick_start_button_styles(tab_state, table_refresh, config):
        """Update quick-start button colors based on enabled watchlists."""
        manager = get_watchlist_manager()
        if not manager._loaded and config:
            manager.load_config(config)

        watchlists = manager.get_available_watchlists()
        enabled_ids = {wl["id"] for wl in watchlists if wl.get("enabled")}

        # (wl_id, base_color_when_enabled)
        buttons = [
            ("clinical_pathogens", "primary"),
            ("foodborne", "warning"),
            ("who_drinking_water", "info"),
            ("respiratory", "secondary"),
            ("cdc_bioterrorism", "danger"),
            ("who_priority", "dark"),
        ]

        results = []
        for wl_id, base_color in buttons:
            if wl_id in enabled_ids:
                results.extend([base_color, False])  # Solid filled button
            else:
                results.extend(["secondary", True])  # Gray outlined button
        return tuple(results)

    # ---------------------------------------------------------------------
    # Watchlist Files Section
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-builtin-list", "children"),
            Output("watchlist-custom-list", "children"),
        ],
        Input("watchlist-tab-state", "data"),
        State("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_watchlist_files(tab_state: Dict, config: Dict) -> Tuple:
        """Update the watchlist files lists with expandable items."""
        manager = get_watchlist_manager()

        # Initialize manager with config if not loaded
        if not manager._loaded and config:
            manager.load_config(config)

        watchlists = manager.get_available_watchlists()

        builtin = [wl for wl in watchlists if wl.get("source") == "builtin"]
        custom = [wl for wl in watchlists if wl.get("source") in ("user", "project")]

        # Sort built-in watchlists to match quick-start button order
        _BUILTIN_ORDER = [
            "clinical_pathogens",
            "foodborne",
            "who_drinking_water",
            "respiratory",
            "cdc_bioterrorism",
            "who_priority",
        ]
        _order_map = {wl_id: i for i, wl_id in enumerate(_BUILTIN_ORDER)}
        builtin.sort(key=lambda wl: _order_map.get(wl.get("id", ""), 999))

        # Create items with pathogens data for expandable view
        # Use get_watchlist_pathogens_preview() to load directly from YAML
        builtin_items = []
        for wl in builtin:
            # Load pathogens directly from YAML file for preview
            pathogen_dicts = manager.get_watchlist_pathogens_preview(wl["id"])
            builtin_items.append(create_watchlist_file_item(wl, pathogen_dicts))

        custom_items = []
        for wl in custom:
            pathogen_dicts = manager.get_watchlist_pathogens_preview(wl["id"])
            custom_items.append(create_watchlist_file_item(wl, pathogen_dicts))

        if not builtin_items:
            builtin_items = [html.P("No built-in watchlists available.", className="text-muted")]
        if not custom_items:
            custom_items = [html.P("No custom watchlists loaded.", className="text-muted")]

        return builtin_items, custom_items

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
        ],
        Input({"type": "watchlist-file-toggle", "index": ALL}, "value"),
        [
            State({"type": "watchlist-file-toggle", "index": ALL}, "id"),
            State("watchlist-table-refresh", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_watchlist_file(values: List[bool], ids: List[Dict], current_refresh: int) -> Tuple[Dict, int]:
        """Handle watchlist file enable/disable toggles."""
        if not callback_context.triggered:
            raise PreventUpdate

        manager = get_watchlist_manager()

        for i, (value, id_dict) in enumerate(zip(values, ids)):
            wl_id = id_dict.get("index")
            if wl_id:
                if value:
                    manager.enable_watchlist(wl_id)
                else:
                    manager.disable_watchlist(wl_id)

        # Return updated state and increment refresh counter
        new_refresh = (current_refresh or 0) + 1
        return {"last_update": str(callback_context.triggered_id)}, new_refresh

    # ---------------------------------------------------------------------
    # Watchlist Expand/Collapse
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output({"type": "watchlist-pathogen-collapse", "index": MATCH}, "is_open"),
            Output({"type": "watchlist-expand-icon", "index": MATCH}, "style"),
        ],
        Input({"type": "watchlist-expand-trigger", "index": MATCH}, "n_clicks"),
        State({"type": "watchlist-pathogen-collapse", "index": MATCH}, "is_open"),
        prevent_initial_call=True,
    )
    def toggle_watchlist_expand(n_clicks: int, is_open: bool) -> Tuple[bool, Dict]:
        """Toggle expand/collapse of watchlist pathogen list."""
        if not n_clicks:
            raise PreventUpdate

        new_is_open = not is_open

        # Rotate chevron icon
        icon_style = {
            "transition": "transform 0.2s",
            "fontSize": "16px",
            "transform": "rotate(90deg)" if new_is_open else "rotate(0deg)"
        }

        return new_is_open, icon_style

    # ---------------------------------------------------------------------
    # Nested Pathogen Toggle
    # ---------------------------------------------------------------------

    @app.callback(
        Output("watchlist-tab-state", "data", allow_duplicate=True),
        Input({"type": "watchlist-nested-pathogen-toggle", "index": ALL, "watchlist": ALL}, "value"),
        State({"type": "watchlist-nested-pathogen-toggle", "index": ALL, "watchlist": ALL}, "id"),
        prevent_initial_call=True,
    )
    def toggle_nested_pathogen(values: List[bool], ids: List[Dict]) -> Dict:
        """Handle individual pathogen enable/disable toggles within watchlist sections."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        # Find which checkbox was changed
        trigger = ctx.triggered[0]
        trigger_id = trigger["prop_id"]

        try:
            import json
            id_str = trigger_id.split(".")[0]
            id_dict = json.loads(id_str)
            taxid = id_dict.get("index")
            watchlist_id = id_dict.get("watchlist")
        except Exception:
            raise PreventUpdate

        if taxid is None:
            raise PreventUpdate

        # Find the new value for this specific checkbox
        for value, id_info in zip(values, ids):
            if id_info.get("index") == taxid and id_info.get("watchlist") == watchlist_id:
                manager = get_watchlist_manager()
                manager.toggle_entry(taxid, value)
                return {"last_update": f"nested-toggle-{taxid}"}

        raise PreventUpdate

    # ---------------------------------------------------------------------
    # Pathogens Table
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-pathogens-table", "children"),
            Output("watchlist-pathogen-count", "children"),
            Output("watchlist-pathogen-count", "style"),
        ],
        [
            Input("watchlist-tab-state", "data"),
            Input("watchlist-table-refresh", "data"),  # Counter to force refresh
            Input("watchlist-search-input", "value"),
            Input("taxmap-rescan-complete", "data"),  # Refresh after mapping rescan
            Input("taxmap-collection", "data"),  # Mapping data from background rescan
        ],
        State("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_pathogens_table(
        tab_state: Dict, table_refresh: int, search_term: str, rescan_complete: Any,
        taxmap_collection: Dict, config: Dict
    ) -> Tuple[List, str, Dict]:
        """Update the pathogens table with Kraken2 mapping status."""
        manager = get_watchlist_manager()

        # Initialize manager with config if not loaded
        if not manager._loaded and config:
            manager.load_config(config)

        entries = manager.get_entries_with_toggle_state()

        # Filter by search term
        if search_term:
            search_lower = search_term.lower()
            entries = [
                e for e in entries
                if search_lower in e.get("name", "").lower()
                or search_lower in (e.get("common_name") or "").lower()
                or search_lower in str(e.get("taxid", ""))
            ]

        if not entries:
            return (
                [html.P("No pathogens in watchlist.", className="text-muted text-center py-4")],
                "",
                {"display": "none"},
            )

        # Build mapping dict from taxmap-collection store data
        # This data comes from the background rescan callback
        mapping_dict = {}
        if taxmap_collection and isinstance(taxmap_collection, dict):
            mappings = taxmap_collection.get("mappings", {})
            if isinstance(mappings, dict):
                # mappings is a dict with ncbi_taxid as key
                for ncbi_taxid_str, mapping_data in mappings.items():
                    try:
                        ncbi_taxid = int(ncbi_taxid_str)
                        mapping_dict[ncbi_taxid] = {
                            "confidence": mapping_data.get("confidence", "unknown"),
                            "db_taxid": mapping_data.get("db_taxid"),
                            "match_score": mapping_data.get("match_score", 0),
                            "db_name": mapping_data.get("db_name", ""),
                        }
                    except (ValueError, TypeError):
                        pass
            elif isinstance(mappings, list):
                # mappings is a list of mapping dicts
                for mapping_data in mappings:
                    ncbi_taxid = mapping_data.get("ncbi_taxid")
                    if ncbi_taxid:
                        mapping_dict[ncbi_taxid] = {
                            "confidence": mapping_data.get("confidence", "unknown"),
                            "db_taxid": mapping_data.get("db_taxid"),
                            "match_score": mapping_data.get("match_score", 0),
                            "db_name": mapping_data.get("db_name", ""),
                        }

        # Fallback: try global collection if store is empty
        if not mapping_dict:
            try:
                from nanometa_live.core.taxonomy import get_mapping_collection
                collection = get_mapping_collection()
                if collection:
                    for entry in entries:
                        taxid = entry.get("taxid", 0)
                        if taxid:
                            mapping = collection.get_mapping(taxid)
                            if mapping:
                                mapping_dict[taxid] = {
                                    "confidence": mapping.confidence.value,
                                    "db_taxid": mapping.db_taxid,
                                    "match_score": mapping.match_score,
                                    "db_name": mapping.db_name,
                                }
            except Exception as e:
                logger.debug(f"Could not load mapping collection: {e}")

        # Get genome status for all entries
        try:
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            genome_mgr = get_genome_manager()
        except Exception:
            genome_mgr = None

        # Create rows with mapping info and genome status
        rows = []
        for i, entry in enumerate(entries):
            taxid = entry.get("taxid", 0)

            # Validate taxid before creating pattern-matching IDs
            try:
                taxid = int(taxid)
            except (ValueError, TypeError):
                logger.error(f"Invalid taxid for entry {entry.get('name', 'Unknown')}: {taxid}")
                continue
            if not taxid:
                logger.error(f"Zero taxid for entry {entry.get('name', 'Unknown')}, skipping")
                continue

            mapping_info = mapping_dict.get(taxid)

            # Get genome status
            genome_info = None
            if genome_mgr and taxid:
                genome_info = {
                    "has_genome": genome_mgr.has_genome(taxid),
                    "has_blast_db": genome_mgr.has_blast_db(taxid),
                }

            try:
                rows.append(create_pathogen_row(entry, i, mapping_info, genome_info))
            except Exception as e:
                logger.error(f"Failed to create row for taxid {taxid} ({entry.get('name', 'Unknown')}): {e}")

        count = len(entries)
        return (
            rows,
            str(count),
            {"display": "inline-block"},  # Show badge when there are pathogens
        )

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
        ],
        [
            Input("watchlist-enable-all-btn", "n_clicks"),
            Input("watchlist-disable-all-btn", "n_clicks"),
        ],
        State("watchlist-table-refresh", "data"),
        prevent_initial_call=True,
    )
    def toggle_all_pathogens(
        enable_clicks: int,
        disable_clicks: int,
        current_refresh: int,
    ) -> Tuple[Dict, int]:
        """Enable or disable ALL pathogens in the current watchlist."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"]

        manager = get_watchlist_manager()
        entries = manager.get_entries_with_toggle_state()

        if not entries:
            raise PreventUpdate

        enable = "enable-all" in trigger

        for entry in entries:
            taxid = entry.get("taxid")
            if taxid:
                manager.toggle_entry(taxid, enable)

        new_refresh = (current_refresh or 0) + 1
        action = "enable-all" if enable else "disable-all"
        return {"last_update": action}, new_refresh

    # ---------------------------------------------------------------------
    # Individual Pathogen Actions
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
        ],
        Input({"type": "watchlist-row-toggle", "index": ALL}, "n_clicks"),
        [
            State({"type": "watchlist-row-toggle", "index": ALL}, "id"),
            State("watchlist-table-refresh", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_pathogen_entry(n_clicks: List[int], ids: List[Dict], current_refresh: int) -> Tuple[Dict, int]:
        """Handle individual pathogen enable/disable toggles."""
        ctx = callback_context
        if not ctx.triggered or not any(n_clicks):
            raise PreventUpdate

        # Find which button was clicked
        trigger = ctx.triggered[0]
        trigger_id = trigger["prop_id"]

        # Parse the pattern-matching ID
        import json
        try:
            id_str = trigger_id.split(".")[0]
            id_dict = json.loads(id_str)
            taxid = id_dict.get("index")
        except Exception:
            raise PreventUpdate

        if taxid is None:
            raise PreventUpdate

        manager = get_watchlist_manager()
        entry = manager.get_entry_by_taxid(taxid)
        if entry:
            manager.toggle_entry(taxid, not entry.enabled)

        new_refresh = (current_refresh or 0) + 1
        return {"last_update": f"toggle-{taxid}"}, new_refresh

    # ---------------------------------------------------------------------
    # Edit Modal
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-edit-modal", "is_open"),
            Output("watchlist-edit-taxid", "data"),
            Output("watchlist-edit-name", "value"),
            Output("watchlist-edit-common", "value"),
            Output("watchlist-edit-threat", "value"),
            Output("watchlist-edit-bsl", "value"),
            Output("watchlist-edit-threshold", "value"),
            Output("watchlist-edit-enabled", "value"),
            Output("watchlist-edit-notes", "value"),
            Output("watchlist-edit-ncbi-taxid", "children"),
            Output("watchlist-edit-kraken-taxid", "children"),
            Output("watchlist-edit-kraken-name", "children"),
        ],
        [
            Input({"type": "watchlist-row-edit", "index": ALL}, "n_clicks"),
            Input("watchlist-edit-save-btn", "n_clicks"),
            Input("watchlist-edit-cancel-btn", "n_clicks"),
        ],
        [
            State({"type": "watchlist-row-edit", "index": ALL}, "id"),
            State("watchlist-edit-modal", "is_open"),
            State("watchlist-edit-taxid", "data"),
            State("watchlist-edit-common", "value"),
            State("watchlist-edit-threat", "value"),
            State("watchlist-edit-bsl", "value"),
            State("watchlist-edit-threshold", "value"),
            State("watchlist-edit-enabled", "value"),
            State("watchlist-edit-notes", "value"),
            State("taxmap-collection", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_edit_modal(
        edit_clicks: List[int],
        save_clicks: int,
        cancel_clicks: int,
        edit_ids: List[Dict],
        is_open: bool,
        edit_taxid: int,
        common: str,
        threat: str,
        bsl: str,
        threshold: int,
        enabled: bool,
        notes: str,
        taxmap_collection: Dict,
    ) -> Tuple:
        """Handle the edit modal open/close and save."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"]

        # Default return values (13 outputs)
        default_return = (no_update, False, None, "", "", "moderate", "", 10, True, "", "-", "-", "-")

        # Cancel or close
        if "cancel" in trigger:
            return default_return

        # Save
        if "save" in trigger and edit_taxid:
            from nanometa_live.core.config.pathogen_loader import BiosaftyLevel
            manager = get_watchlist_manager()
            entry = manager.get_entry_by_taxid(edit_taxid)
            if entry:
                entry.common_name = common
                threat_map = {
                    "critical": ThreatLevel.CRITICAL,
                    "high": ThreatLevel.HIGH,
                    "moderate": ThreatLevel.MODERATE,
                    "low": ThreatLevel.LOW,
                }
                entry.threat_level = threat_map.get(threat, ThreatLevel.MODERATE)
                # Save BSL level (convert string to BiosaftyLevel enum)
                bsl_map = {"1": BiosaftyLevel.BSL1, "2": BiosaftyLevel.BSL2,
                           "3": BiosaftyLevel.BSL3, "4": BiosaftyLevel.BSL4}
                entry.bsl_level = bsl_map.get(bsl) if bsl else None
                entry.alert_threshold = int(threshold) if threshold else 10
                entry.enabled = enabled
                entry.notes = notes or ""
            # Return tab state update to trigger table refresh
            return ({"last_update": f"edit-{edit_taxid}"}, False, None, "", "", "moderate", "", 10, True, "", "-", "-", "-")

        # Open modal for edit
        if any(edit_clicks):
            # Find which button was clicked
            import json
            try:
                trigger_id_str = trigger.split(".")[0]
                trigger_id = json.loads(trigger_id_str)
                taxid = trigger_id.get("index")
            except Exception:
                raise PreventUpdate

            manager = get_watchlist_manager()
            entry = manager.get_entry_by_taxid(taxid)
            if entry:
                # Get Kraken2 mapping info
                kraken_taxid = "-"
                kraken_name = "-"
                if taxmap_collection and isinstance(taxmap_collection, dict):
                    mappings = taxmap_collection.get("mappings", {})
                    if isinstance(mappings, dict):
                        mapping_data = mappings.get(str(taxid), {})
                    elif isinstance(mappings, list):
                        mapping_data = next(
                            (m for m in mappings if m.get("ncbi_taxid") == taxid),
                            {}
                        )
                    else:
                        mapping_data = {}

                    if mapping_data:
                        db_taxid = mapping_data.get("db_taxid")
                        db_name = mapping_data.get("db_name", "")
                        if db_taxid:
                            kraken_taxid = str(db_taxid)
                        if db_name:
                            kraken_name = db_name

                return (
                    no_update,
                    True,
                    taxid,
                    entry.name,
                    entry.common_name or "",
                    entry.threat_level.value,
                    str(entry.bsl_level.value) if entry.bsl_level else "",
                    entry.alert_threshold,
                    entry.enabled,
                    entry.notes or "",
                    str(taxid),
                    kraken_taxid,
                    kraken_name,
                )

        raise PreventUpdate

    # ---------------------------------------------------------------------
    # API Validation
    # ---------------------------------------------------------------------

    # NOTE: update_cache_badge callback removed - watchlist-cache-badge component
    # no longer exists in the active layout (was in legacy _create_api_validation_section)

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
            Output("watchlist-progress-modal", "is_open"),
            Output("watchlist-progress-bar", "value"),
            Output("watchlist-progress-text", "children"),
            Output("watchlist-progress-detail", "children"),
        ],
        [
            Input("watchlist-validate-all-btn", "n_clicks"),
            Input({"type": "watchlist-row-validate", "index": ALL}, "n_clicks"),
        ],
        [
            State("watchlist-api-options", "value"),
            State({"type": "watchlist-row-validate", "index": ALL}, "id"),
            State("watchlist-table-refresh", "data"),
        ],
        prevent_initial_call=True,
    )
    def validate_entries(
        validate_all: int,
        validate_row_clicks: List[int],
        api_options: List[str],
        row_ids: List[Dict],
        current_refresh: int,
    ) -> Tuple:
        """Handle API validation requests."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"]
        use_ncbi = "ncbi" in (api_options or [])
        use_gtdb = "gtdb" in (api_options or [])

        manager = get_watchlist_manager()
        taxids_to_validate = []

        if "validate-all" in trigger:
            # Validate ALL pathogens (from stats bar button)
            entries = manager.get_entries_with_toggle_state()
            taxids_to_validate = [e.get("taxid") for e in entries]
        elif "watchlist-row-validate" in trigger:
            # Single row validation
            import json
            try:
                trigger_id_str = trigger.split(".")[0]
                trigger_id = json.loads(trigger_id_str)
                taxid = trigger_id.get("index")
                if taxid:
                    taxids_to_validate = [taxid]
            except Exception:
                raise PreventUpdate

        if not taxids_to_validate:
            raise PreventUpdate

        # Perform validation
        results = manager.bulk_validate_entries(
            taxids=taxids_to_validate,
            use_ncbi=use_ncbi,
            use_gtdb=use_gtdb,
        )

        validated = results.get("validated", 0)
        failed = results.get("failed", 0)
        total = len(taxids_to_validate)

        # Build detail message
        apis_used = []
        if use_ncbi:
            apis_used.append("NCBI")
        if use_gtdb:
            apis_used.append("GTDB")
        detail = f"APIs: {', '.join(apis_used) if apis_used else 'None selected'}"
        if failed > 0:
            detail += f" | {failed} failed"

        new_refresh = (current_refresh or 0) + 1
        return (
            {"last_update": f"validate-{validated}"},
            new_refresh,  # Trigger table refresh
            False,  # Close progress modal
            100,
            f"Validated {validated} of {total} entries",
            detail,
        )

    # NOTE: clear_cache callback removed - watchlist-clear-cache-btn component
    # no longer exists in the active layout (was in legacy _create_api_validation_section)

    # ---------------------------------------------------------------------
    # API Details Modal
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-api-modal", "is_open"),
            Output("watchlist-api-modal-title", "children"),
            Output("watchlist-api-modal-content", "children"),
        ],
        [
            Input({"type": "watchlist-row-validated", "index": ALL}, "n_clicks"),
            Input("watchlist-api-modal-close-btn", "n_clicks"),
        ],
        State({"type": "watchlist-row-validated", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def show_api_details(
        validated_clicks: List[int],
        close_clicks: int,
        validated_ids: List[Dict],
    ) -> Tuple:
        """Show API validation details modal."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"]

        if "close" in trigger:
            return False, "", html.Div()

        if any(validated_clicks):
            import json
            try:
                trigger_id_str = trigger.split(".")[0]
                trigger_id = json.loads(trigger_id_str)
                taxid = trigger_id.get("index")
            except Exception:
                raise PreventUpdate

            manager = get_watchlist_manager()
            entry = manager.get_entry_by_taxid(taxid)
            if entry and entry.validated:
                entry_dict = entry.to_dict()
                return (
                    True,
                    f"Validation Details: {entry.name}",
                    create_api_details_content(entry_dict),
                )

        raise PreventUpdate

    # ---------------------------------------------------------------------
    # Add Custom Species
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-lookup-section", "style"),
            Output("watchlist-lookup-results", "children"),
            Output("api-lookup-result", "data"),
        ],
        Input("watchlist-lookup-btn", "n_clicks"),
        [
            State("watchlist-add-name", "value"),
            State("watchlist-add-taxid", "value"),
            State("watchlist-api-options", "value"),
        ],
        prevent_initial_call=True,
    )
    def lookup_species(
        n_clicks: int,
        name: str,
        taxid: Optional[int],
        api_options: list,
    ) -> Tuple:
        """Look up species in NCBI/GTDB APIs."""
        if not n_clicks or not name:
            raise PreventUpdate

        use_ncbi = "ncbi" in (api_options or [])
        use_gtdb = "gtdb" in (api_options or [])

        try:
            from nanometa_live.core.taxonomy.taxonomy_api import lookup_species as api_lookup
            result = api_lookup(name, use_ncbi=use_ncbi, use_gtdb=use_gtdb)

            ncbi_result = None
            gtdb_result = None

            if result.get("ncbi_result"):
                ncbi = result["ncbi_result"]
                ncbi_result = {
                    "taxid": ncbi.taxid,
                    "sciname": ncbi.sciname,
                    "commonname": ncbi.commonname,
                    "rank": ncbi.rank,
                    "ncbi_link": ncbi.ncbi_link,
                    "lineage": ncbi.lineage,
                }

            if result.get("gtdb_result"):
                gtdb = result["gtdb_result"]
                gtdb_result = {
                    "species": gtdb.species,
                    "gtdb_taxonomy": gtdb.gtdb_taxonomy,
                    "gtdb_link": gtdb.gtdb_link,
                }

            return (
                {"display": "block"},
                create_api_lookup_result(ncbi_result, gtdb_result),
                {"ncbi": ncbi_result, "gtdb": gtdb_result},
            )

        except ImportError:
            return (
                {"display": "block"},
                html.P("Taxonomy API not available.", className="text-danger"),
                None,
            )
        except Exception as e:
            return (
                {"display": "block"},
                html.P(f"Lookup failed: {e}", className="text-danger"),
                None,
            )

    @app.callback(
        [
            Output("watchlist-add-name", "value", allow_duplicate=True),
            Output("watchlist-add-taxid", "value", allow_duplicate=True),
        ],
        [
            Input("watchlist-use-ncbi-btn", "n_clicks"),
            Input("watchlist-use-gtdb-btn", "n_clicks"),
        ],
        State("api-lookup-result", "data"),
        prevent_initial_call=True,
    )
    def use_api_result(
        use_ncbi: int,
        use_gtdb: int,
        lookup_result: Dict,
    ) -> Tuple:
        """Use API lookup result to populate form."""
        ctx = callback_context
        if not ctx.triggered or not lookup_result:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"]

        if "ncbi" in trigger and lookup_result.get("ncbi"):
            ncbi = lookup_result["ncbi"]
            return ncbi.get("sciname", ""), ncbi.get("taxid", "")
        elif "gtdb" in trigger and lookup_result.get("gtdb"):
            gtdb = lookup_result["gtdb"]
            return gtdb.get("species", ""), ""

        raise PreventUpdate

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-add-feedback", "children"),
            Output("watchlist-add-name", "value", allow_duplicate=True),
            Output("watchlist-add-taxid", "value", allow_duplicate=True),
            Output("watchlist-add-threat", "value", allow_duplicate=True),
            Output("watchlist-add-threshold", "value", allow_duplicate=True),
            Output("watchlist-lookup-section", "style", allow_duplicate=True),
        ],
        Input("watchlist-add-btn", "n_clicks"),
        [
            State("watchlist-add-name", "value"),
            State("watchlist-add-taxid", "value"),
            State("watchlist-add-threat", "value"),
            State("watchlist-add-threshold", "value"),
            State("api-lookup-result", "data"),
        ],
        prevent_initial_call=True,
    )
    def add_custom_species(
        n_clicks: int,
        name: str,
        taxid: Optional[int],
        threat: str,
        threshold: int,
        lookup_result: Dict,
    ) -> Tuple:
        """Add a custom species to the watchlist."""
        if not n_clicks or not name:
            raise PreventUpdate

        manager = get_watchlist_manager()

        entry_data = {
            "name": name.strip(),
            "taxid": int(taxid) if taxid else 0,
            "threat_level": threat or "moderate",
            "alert_threshold": int(threshold) if threshold else 10,
        }

        # Add API data if available
        if lookup_result:
            ncbi = lookup_result.get("ncbi")
            gtdb = lookup_result.get("gtdb")

            if ncbi:
                entry_data["ncbi_link"] = ncbi.get("ncbi_link")
                entry_data["api_sciname"] = ncbi.get("sciname")
                entry_data["api_commonname"] = ncbi.get("commonname")
                entry_data["api_rank"] = ncbi.get("rank")
                entry_data["lineage"] = ncbi.get("lineage")
                entry_data["validated"] = True
                if not entry_data["taxid"] and ncbi.get("taxid"):
                    entry_data["taxid"] = ncbi["taxid"]

            if gtdb:
                entry_data["gtdb_link"] = gtdb.get("gtdb_link")
                entry_data["gtdb_taxonomy"] = gtdb.get("gtdb_taxonomy")
                entry_data["validated"] = True

            if entry_data.get("validated"):
                from datetime import datetime
                entry_data["validation_date"] = datetime.utcnow().isoformat() + "Z"

        try:
            entry = manager.add_custom_entry(entry_data)
            if entry:
                return (
                    {"last_update": f"add-{entry.taxid}"},
                    dbc.Alert(f"Added: {entry.name}", color="success", duration=3000),
                    "",  # Clear name
                    "",  # Clear taxid
                    "moderate",  # Reset threat
                    10,  # Reset threshold
                    {"display": "none"},  # Hide lookup section
                )
            else:
                return (
                    no_update,
                    dbc.Alert("Failed to add entry.", color="danger", duration=3000),
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
        except Exception as e:
            return (
                no_update,
                dbc.Alert(f"Error: {e}", color="danger", duration=3000),
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
            )

    # NOTE: set_taxonomy_mode callback removed - watchlist-taxonomy-mode component
    # no longer exists in the active layout (was in legacy _create_stats_row)

    # ---------------------------------------------------------------------
    # File Upload
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-upload-feedback", "children"),
        ],
        Input("watchlist-upload", "contents"),
        State("watchlist-upload", "filename"),
        prevent_initial_call=True,
    )
    def handle_upload(contents: str, filename: str) -> Tuple:
        """Handle watchlist file upload."""
        if not contents or not filename:
            raise PreventUpdate

        try:
            import base64
            import tempfile
            from pathlib import Path

            # Decode the file
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)

            # Save to temp file
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=Path(filename).suffix,
                delete=False,
            ) as f:
                f.write(decoded)
                temp_path = f.name

            # Load the watchlist
            manager = get_watchlist_manager()
            manager._load_custom_yaml_file(temp_path)

            # Clean up
            Path(temp_path).unlink(missing_ok=True)

            return (
                {"last_update": f"upload-{filename}"},
                dbc.Alert(f"Loaded: {filename}", color="success", duration=3000),
            )

        except Exception as e:
            return (
                no_update,
                dbc.Alert(f"Upload failed: {e}", color="danger", duration=5000),
            )

    # NOTE: handle_file_view callback removed - watchlist-filter-watchlist component
    # does not exist in the active layout (the feature was never fully implemented)

    # ---------------------------------------------------------------------
    # Taxid Mapping Section
    # ---------------------------------------------------------------------

    @app.callback(
        Output("taxmap-section-collapse", "is_open"),
        [
            Input("taxmap-open-section-btn", "n_clicks"),
            Input("taxmap-collapse-toggle-btn", "n_clicks"),
        ],
        State("taxmap-section-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_taxmap_section(
        open_clicks: int,
        collapse_clicks: int,
        is_open: bool
    ) -> bool:
        """Toggle the taxid mapping section visibility."""
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"]

        if "open-section" in trigger:
            return True
        elif "collapse-toggle" in trigger:
            return not is_open

        raise PreventUpdate

    # NOTE: Rescan callback has been moved to preparation_tab.py

    @app.callback(
        [
            Output("taxmap-mapping-modal", "is_open"),
            Output("taxmap-edit-ncbi-taxid", "data"),
            Output("taxmap-edit-ncbi-name", "children"),
            Output("taxmap-edit-ncbi-taxid-display", "children"),
            Output("taxmap-suggestions-list", "children"),
        ],
        [
            Input({"type": "watchlist-row-mapping", "index": ALL}, "n_clicks"),
        ],
        [
            State({"type": "watchlist-row-mapping", "index": ALL}, "id"),
            State("taxmap-mapping-modal", "is_open"),
            State("taxmap-collection", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_mapping_modal(
        badge_clicks: List[int],
        badge_ids: List[Dict],
        is_open: bool,
        taxmap_collection: Dict,
    ) -> Tuple:
        """Open manual mapping modal when clicking Kraken2 badge."""
        import json

        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        # CRITICAL: Check that an actual click happened, not just component creation
        # When table refreshes and new buttons are created with n_clicks=0,
        # the callback fires but we should ignore it
        trigger = ctx.triggered[0]
        trigger_value = trigger.get("value")
        trigger_prop_id = trigger.get("prop_id", "")

        # If no actual click (value is None, 0, or not a positive integer), don't open
        if not trigger_value or not isinstance(trigger_value, int) or trigger_value < 1:
            raise PreventUpdate

        # Only process if it's a mapping button click
        if "watchlist-row-mapping" not in trigger_prop_id:
            raise PreventUpdate

        # Parse the prop_id to get the specific badge that was clicked
        # Format: '{"index":1234,"type":"watchlist-row-mapping"}.n_clicks'
        try:
            prop_id_json = trigger_prop_id.rsplit(".", 1)[0]  # Remove ".n_clicks"
            trigger_id = json.loads(prop_id_json)
            ncbi_taxid = trigger_id.get("index")
        except (json.JSONDecodeError, IndexError, AttributeError):
            logger.warning(f"Failed to parse trigger prop_id: {trigger_prop_id}")
            raise PreventUpdate

        if ncbi_taxid:
            # Get entry name from WatchlistManager
            manager = get_watchlist_manager()
            entry = manager.get_entry_by_taxid(ncbi_taxid)
            # entry is a WatchlistEntry object, not a dict
            name = entry.name if entry else "Unknown"

            # Get suggestions from mapping collection
            suggestions_children = []
            if taxmap_collection and isinstance(taxmap_collection, dict):
                mappings_data = taxmap_collection.get("mappings", {})
                if isinstance(mappings_data, dict):
                    mapping_data = mappings_data.get(str(ncbi_taxid), {})
                elif isinstance(mappings_data, list):
                    mapping_data = next(
                        (m for m in mappings_data if m.get("ncbi_taxid") == ncbi_taxid),
                        {}
                    )
                else:
                    mapping_data = {}

                # Get alternative matches
                alternatives = mapping_data.get("alternative_matches", [])
                for alt in alternatives[:5]:
                    suggestions_children.append(
                        _create_suggestion_card(alt, "taxmap")
                    )

                # Add current mapping as first suggestion if exists
                if mapping_data.get("db_taxid"):
                    current = {
                        "db_taxid": mapping_data.get("db_taxid"),
                        "db_name": mapping_data.get("db_name", ""),
                        "score": mapping_data.get("match_score", 0),
                        "match_method": mapping_data.get("confidence", ""),
                    }
                    suggestions_children.insert(0, _create_suggestion_card(
                        current, "taxmap", is_current=True
                    ))

            if not suggestions_children:
                suggestions_children = [
                    html.P(
                        "No suggestions available. Use search to find matches.",
                        className="text-muted"
                    )
                ]

            return True, ncbi_taxid, name, str(ncbi_taxid), suggestions_children

        raise PreventUpdate

    @app.callback(
        Output("taxmap-mapping-modal", "is_open", allow_duplicate=True),
        Input("taxmap-cancel-mapping-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_mapping_modal(cancel_clicks: int) -> bool:
        """Close the mapping modal when cancel is clicked."""
        if cancel_clicks:
            return False
        raise PreventUpdate

    @app.callback(
        Output("taxmap-suggestions-list", "children", allow_duplicate=True),
        [
            Input("taxmap-kraken-search-btn", "n_clicks"),
            Input("taxmap-kraken-search", "n_submit"),
        ],
        [
            State("taxmap-kraken-search", "value"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def search_kraken_database(
        btn_clicks: int,
        search_submit: int,
        search_query: str,
        config: Dict,
    ) -> List:
        """Search Kraken2 database for matching taxa."""
        if not search_query or len(search_query) < 2:
            return [html.P("Enter at least 2 characters to search.", className="text-muted")]

        try:
            from nanometa_live.core.taxonomy import get_taxid_mapper
            mapper = get_taxid_mapper()

            # Try to load database from config if not already loaded
            if not mapper._index:
                kraken_db = config.get("kraken_db") if config else None
                if kraken_db:
                    logger.info(f"Loading Kraken2 database index from: {kraken_db}")
                    success = mapper.load_database(kraken_db)
                    if not success:
                        return [html.P("Failed to load database. Check kraken_db path in config.", className="text-warning")]
                else:
                    return [html.P("No kraken_db configured. Set kraken_db path in config.", className="text-warning")]

            if not mapper._index:
                return [html.P("Database index not available.", className="text-warning")]

            results = mapper.search_database(search_query, limit=10)

            if not results:
                return [html.P(f"No matches found for '{search_query}'", className="text-muted")]

            return [_create_suggestion_card(r, "taxmap") for r in results]

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return [html.P(f"Search error: {str(e)}", className="text-danger")]

    @app.callback(
        [
            Output("taxmap-selected-kraken-name", "children"),
            Output("taxmap-selected-kraken-taxid", "children"),
            Output("taxmap-selected-card", "style"),
        ],
        Input({"type": "taxmap-suggestion", "index": ALL}, "n_clicks"),
        State({"type": "taxmap-suggestion", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def select_suggestion(
        suggestion_clicks: List[int],
        suggestion_ids: List[Dict],
    ) -> Tuple[str, str, Dict]:
        """Handle selection of a suggestion in the mapping modal."""
        import json

        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        # Ensure an actual click happened (not just component creation)
        trigger_value = ctx.triggered[0].get("value")
        if not trigger_value or not isinstance(trigger_value, int) or trigger_value < 1:
            raise PreventUpdate

        trigger = ctx.triggered[0]["prop_id"]

        # Parse the prop_id to get the specific suggestion that was clicked
        # Format: '{"index":"123:Species name","type":"taxmap-suggestion"}.n_clicks'
        try:
            prop_id_json = trigger.rsplit(".", 1)[0]  # Remove ".n_clicks"
            trigger_id = json.loads(prop_id_json)
            suggestion_id = trigger_id.get("index", "")
        except (json.JSONDecodeError, IndexError, AttributeError):
            logger.warning(f"Failed to parse trigger prop_id: {trigger}")
            raise PreventUpdate

        # Parse the ID which is in format "taxid:name"
        if ":" in str(suggestion_id):
            parts = str(suggestion_id).split(":", 1)
            db_taxid = parts[0]
            db_name = parts[1] if len(parts) > 1 else ""
            return db_name, db_taxid, {"display": "block"}

        raise PreventUpdate

    @app.callback(
        [
            Output("taxmap-mapping-modal", "is_open", allow_duplicate=True),
            Output("taxmap-collection", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
        ],
        Input("taxmap-confirm-mapping-btn", "n_clicks"),
        [
            State("taxmap-edit-ncbi-taxid", "data"),
            State("taxmap-selected-kraken-taxid", "children"),
            State("taxmap-mapping-notes", "value"),
            State("app-config", "data"),
            State("taxmap-collection", "data"),
            State("watchlist-table-refresh", "data"),
        ],
        prevent_initial_call=True,
    )
    def confirm_manual_mapping(
        confirm_clicks: int,
        ncbi_taxid: int,
        db_taxid_str: str,
        notes: str,
        config: Dict,
        current_collection: Dict,
        current_refresh: int,
    ) -> Tuple[bool, Dict, int]:
        """Save the manual mapping selection."""
        if not ncbi_taxid or not db_taxid_str or db_taxid_str == "-":
            raise PreventUpdate

        try:
            db_taxid = int(db_taxid_str)
        except (ValueError, TypeError):
            raise PreventUpdate

        try:
            from nanometa_live.core.taxonomy import get_taxid_mapper
            mapper = get_taxid_mapper()

            if mapper:
                success = mapper.set_manual_mapping(
                    ncbi_taxid=ncbi_taxid,
                    db_taxid=db_taxid,
                    reason=notes or "Manual mapping via UI",
                    verified_by="user"
                )

                if success:
                    # Update the collection store with new data
                    collection = mapper._collection
                    if collection:
                        updated_collection = collection.to_dict()
                        # Reformat mappings as dict keyed by ncbi_taxid for easier lookup
                        mappings_dict = {}
                        for mapping in updated_collection.get("mappings", []):
                            ncbi_tid = mapping.get("ncbi_taxid")
                            if ncbi_tid:
                                mappings_dict[str(ncbi_tid)] = mapping
                        updated_collection["mappings"] = mappings_dict

                        return False, updated_collection, (current_refresh or 0) + 1

            return False, current_collection, current_refresh or 0

        except Exception as e:
            logger.error(f"Failed to save manual mapping: {e}")
            raise PreventUpdate

    @app.callback(
        [
            Output("taxmap-selected-kraken-name", "children", allow_duplicate=True),
            Output("taxmap-selected-kraken-taxid", "children", allow_duplicate=True),
            Output("taxmap-selected-card", "style", allow_duplicate=True),
        ],
        Input("taxmap-clear-selection-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_mapping_selection(clear_clicks: int) -> Tuple[str, str, Dict]:
        """Clear the current selection in the mapping modal."""
        return "None selected", "-", {"display": "none"}

    # NOTE: Genome download, BLAST build, and dependency check callbacks
    # have been moved to preparation_tab.py

    logger.info("Watchlist tab callbacks registered")
