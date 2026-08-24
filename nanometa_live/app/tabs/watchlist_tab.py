"""
Watchlist Tab Callbacks for Nanometa Live.

Handles all callback logic for the Watchlist management tab:
- Watchlist file toggles
- Pathogens table updates
- Individual pathogen toggle/edit
- API validation (manual button)
- Add custom species with API lookup
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from dash import Dash, Input, Output, State, ctx, ALL, MATCH, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from dash import html

from nanometa_live.core.watchlist.watchlist_manager import (
    get_watchlist_manager,
    WatchlistEntry,
    ThreatLevel,
    normalize_organism_type,
)
from nanometa_live.app.layouts.watchlist_layout import (
    _create_watchlist_pathogen_list,
    create_pathogen_row,
    create_watchlist_file_item,
    create_api_lookup_result,
    create_api_details_content,
    create_missing_genome_item,
)
from nanometa_live.app.app import background_callback_manager

logger = logging.getLogger(__name__)


def _save_last_session(config: Dict[str, Any]) -> None:
    """Persist the WATCHLIST block to last-session.yaml, nothing else.

    A watchlist toggle owns the ``watchlist`` key and no other setting, so
    the rest of the file is taken from what is already persisted rather than
    from this callback's in-memory ``app-config``. That store re-seeds from
    the BOOT config on every page load (boot is fresh by design), so writing
    it wholesale silently reverted settings the operator had applied:
    Apply min_reads_for_validation=50, reload, toggle a watchlist, and the
    file said 1 again (2026-08-19 config audit). This is the mirror of the
    protection ``autosave_session_config`` already gives the watchlist when
    a config write runs with an empty singleton.

    Falls back to the supplied config when nothing is persisted yet (first
    write) or the file is unreadable -- the toggle must never be lost.

    The persisted block's ``custom`` entries are re-fattened from the live
    singleton: the app-config Store carries the slim six-field form
    (round-2 audit, 2026-08-22), and persisting it verbatim would strip
    action_required/notes/lineage from the file that session restore
    rebuilds entries from. The rest of the block (enabled/builtin/
    overrides) stays authoritative from the caller -- it is the toggle
    that just happened. Fallback rule: with an empty singleton
    (fresh-boot edge), keep the file's existing custom entries -- never
    overwrite full data with slim data.
    """
    try:
        from nanometa_live.core.config.config_loader import ConfigLoader
        from nanometa_live.core.utils.paths import NanometaPaths
        paths = NanometaPaths.from_config(config)
        session_path = Path(paths.configs) / "last-session.yaml"

        persisted = None
        if session_path.is_file():
            try:
                import yaml
                with open(session_path) as fh:
                    persisted = yaml.safe_load(fh)
            except (OSError, yaml.YAMLError):
                logger.debug(
                    "last-session.yaml unreadable; writing the in-memory "
                    "config so the watchlist change is not lost",
                    exc_info=True,
                )

        persisted_block = (persisted or {}).get("watchlist") \
            if isinstance(persisted, dict) else None
        watchlist_block = _full_watchlist_block(
            config.get("watchlist"), persisted_block)

        if isinstance(persisted, dict):
            persisted["watchlist"] = (
                watchlist_block if watchlist_block is not None
                else persisted.get("watchlist")
            )
            save_config = persisted
        else:
            save_config = dict(config)
            if watchlist_block is not None:
                save_config["watchlist"] = watchlist_block

        loader = ConfigLoader(str(paths.configs))
        loader.save_config(save_config, "last-session.yaml")
    except Exception:
        logger.debug("Could not save last-session.yaml", exc_info=True)


def _full_watchlist_block(store_block, persisted_block):
    """The block to persist: caller's structure, full-form custom entries.

    ``store_block`` is what the callback holds (slim custom entries);
    ``persisted_block`` is what last-session.yaml already carries. The
    singleton is the source of full custom data; when it is empty, the
    persisted full entries win over the caller's slim ones.
    """
    if not isinstance(store_block, dict):
        return store_block if store_block is not None else persisted_block
    block = dict(store_block)
    entries_available = False
    try:
        manager = get_watchlist_manager()
        if manager._entries:
            block["custom"] = manager.export_config(slim=False)["custom"]
            entries_available = True
    except Exception:
        logger.debug("full watchlist export unavailable", exc_info=True)
    if (not entries_available
            and isinstance(persisted_block, dict)
            and persisted_block.get("custom")):
        block["custom"] = persisted_block["custom"]
    return block


# Rows per page in the pathogens table. Row action ids are keyed by taxid,
# so pattern-matching callbacks work regardless of which page is shown.
WATCHLIST_TABLE_PAGE_SIZE = 25


def register_watchlist_callbacks(app: Dash) -> None:
    """
    Register all watchlist tab callbacks.

    Args:
        app: Dash application instance
    """
    # Sweep decoded uploads a previous session left in .pending/ (a worker
    # crash or restart between upload and finalize strands the file there).
    # Registration runs once per app boot, in the main process. Resolved via
    # the pure env resolver, NOT get_watchlist_loader(): instantiating the
    # loader singleton here freezes it to registration-time environment,
    # which leaks across tests and precedes the app's own configuration.
    try:
        from nanometa_live.core.utils.paths import get_watchlists_dir_from_env

        pending_dir = Path(get_watchlists_dir_from_env()) / ".pending"
        if pending_dir.is_dir():
            for stale in pending_dir.iterdir():
                stale.unlink(missing_ok=True)
    except Exception:
        logger.debug("Pending-upload sweep skipped", exc_info=True)

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
            Output("watchlist-stat-moderate", "children"),
            Output("watchlist-stat-low", "children"),
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
        # Count validated against the ENABLED set so un-ticking a watchlist
        # lowers the denominator instead of leaving a stale total.
        validation_status = manager.get_validation_status(enabled_only=True)

        by_threat = stats.get("by_threat_level", {})

        return (
            str(stats.get("total_entries", 0)),
            str(stats.get("active_entries", 0)),
            str(validation_status.get("validated", 0)),
            f"Critical: {by_threat.get('critical', 0)}",
            f"High: {by_threat.get('high', 0)}",
            f"Moderate: {by_threat.get('moderate', 0)}",
            f"Low: {by_threat.get('low', 0)}",
        )

    # ---------------------------------------------------------------------
    # Quick Start Section
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
            Output("quick-start-feedback", "children"),
            Output("app-config", "data", allow_duplicate=True),
        ],
        [
            Input("quick-start-clinical", "n_clicks"),
            Input("quick-start-foodborne", "n_clicks"),
            Input("quick-start-water", "n_clicks"),
            Input("quick-start-respiratory", "n_clicks"),
            Input("quick-start-cdc", "n_clicks"),
            Input("quick-start-who", "n_clicks"),
            Input("quick-start-nosocomial", "n_clicks"),
            Input("quick-start-wastewater", "n_clicks"),
            Input("quick-start-zoonotic", "n_clicks"),
        ],
        [
            State("watchlist-table-refresh", "data"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def quick_start_watchlist(clinical, foodborne, water, respiratory, cdc, who, nosocomial, wastewater, zoonotic, current_refresh, current_config):
        """Toggle a predefined watchlist on/off with one click."""
        if not ctx.triggered_id:
            raise PreventUpdate

        button_id = ctx.triggered_id
        watchlist_map = {
            "quick-start-clinical": "clinical_pathogens",
            "quick-start-foodborne": "foodborne",
            "quick-start-water": "who_drinking_water",
            "quick-start-respiratory": "respiratory",
            "quick-start-cdc": "cdc_bioterrorism",
            "quick-start-who": "who_priority",
            "quick-start-nosocomial": "nosocomial_eskape",
            "quick-start-wastewater": "wastewater_surveillance",
            "quick-start-zoonotic": "zoonotic_one_health",
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
                else:
                    # Enable the watchlist
                    manager.enable_watchlist(wl_id)
                    pathogens = manager.get_watchlist_pathogens_preview(wl_id)
                    count = len(pathogens)
                    feedback = html.Span([
                        html.I(className="bi bi-check-circle text-success me-1"),
                        f"Enabled {wl_id.replace('_', ' ').title()} ({count} pathogens)"
                    ], className="text-success")

                # Sync watchlist state to app-config and save to disk
                updated_config = dict(current_config) if current_config else {}
                # Slim store form; _save_last_session persists the full
                # form from the singleton (round-2 audit, 2026-08-22).
                updated_config["watchlist"] = manager.export_config(slim=True)
                _save_last_session(updated_config)

                action = "disable" if is_enabled else "enable"
                return {"last_update": f"{action}-{wl_id}"}, new_refresh, feedback, updated_config

            except Exception as e:
                logger.warning(f"Failed to toggle watchlist {wl_id}: {e}")
                feedback = html.Span([
                    html.I(className="bi bi-exclamation-triangle text-warning me-1"),
                    f"Error toggling watchlist: {str(e)}"
                ], className="text-warning")
                return no_update, no_update, feedback, no_update

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
            Output("quick-start-nosocomial", "color"),
            Output("quick-start-nosocomial", "outline"),
            Output("quick-start-wastewater", "color"),
            Output("quick-start-wastewater", "outline"),
            Output("quick-start-zoonotic", "color"),
            Output("quick-start-zoonotic", "outline"),
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
            ("nosocomial_eskape", "danger"),
            ("wastewater_surveillance", "info"),
            ("zoonotic_one_health", "success"),
        ]

        results = []
        for wl_id, base_color in buttons:
            if wl_id in enabled_ids:
                results.extend([base_color, False])  # Solid filled button
            else:
                results.extend([base_color, True])  # Outlined in original color
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
            "nosocomial_eskape",
            "wastewater_surveillance",
            "zoonotic_one_health",
        ]
        _order_map = {wl_id: i for i, wl_id in enumerate(_BUILTIN_ORDER)}
        builtin.sort(key=lambda wl: _order_map.get(wl.get("id", ""), 999))

        # Headers only: the per-watchlist pathogen rows render on expand
        # (toggle_watchlist_expand), not up front. Pre-rendering every
        # list's rows here cost ~4,400 components per update and a YAML
        # preview load per watchlist.
        builtin_items = [create_watchlist_file_item(wl) for wl in builtin]
        custom_items = [create_watchlist_file_item(wl) for wl in custom]

        if not builtin_items:
            builtin_items = [html.P("No built-in watchlists available.", className="text-muted")]
        if not custom_items:
            custom_items = [html.P("No custom watchlists loaded.", className="text-muted")]

        # Files that fail validation used to vanish from this list with only
        # a terminal log line -- name them so the operator knows a list they
        # placed here is not (fully) active (finding W4).
        from nanometa_live.core.watchlist.watchlist_loader import (
            get_watchlist_loader,
        )
        invalid_files = get_watchlist_loader().find_invalid_watchlist_files()
        if invalid_files:
            custom_items.insert(0, dbc.Alert(
                [
                    html.Div([
                        html.I(className="bi bi-exclamation-triangle-fill me-2"),
                        html.Strong(
                            f"{len(invalid_files)} watchlist file(s) failed "
                            f"validation and may be skipped or load "
                            f"incompletely:"
                        ),
                    ], className="mb-1"),
                    html.Ul([
                        html.Li([html.Code(name), f" — {problem}"])
                        for name, problem in invalid_files[:5]
                    ], className="mb-0 small"),
                ],
                color="warning", className="py-2",
            ))

        return builtin_items, custom_items

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
            Output("app-config", "data", allow_duplicate=True),
        ],
        Input({"type": "watchlist-file-toggle", "index": ALL}, "value"),
        [
            State({"type": "watchlist-file-toggle", "index": ALL}, "id"),
            State("watchlist-table-refresh", "data"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_watchlist_file(values: List[bool], ids: List[Dict], current_refresh: int, current_config: Optional[Dict]) -> Tuple[Dict, int, Dict]:
        """Handle watchlist file enable/disable toggles."""
        if not ctx.triggered_id:
            raise PreventUpdate

        manager = get_watchlist_manager()

        # Apply only the toggle that actually changed (ctx.triggered_id),
        # not every toggle in the group. The previous loop re-applied all n
        # enable/disable calls on every single toggle -- correct, but O(n)
        # wasted work (and any per-call side effects fired n times).
        if not isinstance(ctx.triggered_id, dict):
            raise PreventUpdate
        changed_id = ctx.triggered_id.get("index")
        changed_value = None
        for value, id_dict in zip(values, ids):
            if id_dict.get("index") == changed_id:
                changed_value = value
                break
        if changed_id:
            if changed_value:
                manager.enable_watchlist(changed_id)
            else:
                manager.disable_watchlist(changed_id)

        # Sync watchlist state to app-config and save to disk
        updated_config = dict(current_config) if current_config else {}
        # Slim store form; _save_last_session persists the full form
        # from the singleton (round-2 audit, 2026-08-22).
        updated_config["watchlist"] = manager.export_config(slim=True)
        _save_last_session(updated_config)

        # Return updated state and increment refresh counter
        new_refresh = (current_refresh or 0) + 1
        return {"last_update": str(ctx.triggered_id)}, new_refresh, updated_config

    # ---------------------------------------------------------------------
    # Watchlist Expand/Collapse
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output({"type": "watchlist-pathogen-collapse", "index": MATCH}, "is_open"),
            Output({"type": "watchlist-expand-icon", "index": MATCH}, "style"),
            Output({"type": "watchlist-pathogen-collapse-content", "index": MATCH}, "children"),
        ],
        Input({"type": "watchlist-expand-trigger", "index": MATCH}, "n_clicks"),
        State({"type": "watchlist-pathogen-collapse", "index": MATCH}, "is_open"),
        prevent_initial_call=True,
    )
    def toggle_watchlist_expand(n_clicks: int, is_open: bool) -> Tuple[bool, Dict, Any]:
        """Toggle expand/collapse of watchlist pathogen list.

        The rows are rendered here, on open, and cleared on close: a
        collapsed dbc.Collapse still mounts its children, so embedding
        every watchlist's rows up front kept ~311 rows permanently in the
        DOM (audit 2026-08-21).
        """
        if not n_clicks:
            raise PreventUpdate

        new_is_open = not is_open

        # Rotate chevron icon
        icon_style = {
            "transition": "transform 0.2s",
            "fontSize": "16px",
            "transform": "rotate(90deg)" if new_is_open else "rotate(0deg)"
        }

        if not new_is_open:
            return new_is_open, icon_style, []

        wl_id = None
        if isinstance(ctx.triggered_id, dict):
            wl_id = ctx.triggered_id.get("index")
        if not wl_id:
            raise PreventUpdate
        pathogens = get_watchlist_manager().get_watchlist_pathogens_preview(wl_id)
        content = _create_watchlist_pathogen_list(pathogens, wl_id)
        return new_is_open, icon_style, content

    # ---------------------------------------------------------------------
    # Nested Pathogen Toggle
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("app-config", "data", allow_duplicate=True),
        ],
        Input({"type": "watchlist-nested-pathogen-toggle", "index": ALL, "watchlist": ALL}, "value"),
        [
            State({"type": "watchlist-nested-pathogen-toggle", "index": ALL, "watchlist": ALL}, "id"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_nested_pathogen(values: List[bool], ids: List[Dict], current_config: Optional[Dict]) -> Tuple[Dict, Dict]:
        """Handle individual pathogen enable/disable toggles within watchlist sections."""
        if not ctx.triggered_id:
            raise PreventUpdate

        # ctx.triggered_id is already the dict ID for pattern-matching callbacks
        triggered_id = ctx.triggered_id
        if not isinstance(triggered_id, dict):
            raise PreventUpdate

        taxid = triggered_id.get("index")
        watchlist_id = triggered_id.get("watchlist")

        if taxid is None:
            raise PreventUpdate

        # Find the new value for this specific checkbox
        for value, id_info in zip(values, ids):
            if id_info.get("index") == taxid and id_info.get("watchlist") == watchlist_id:
                manager = get_watchlist_manager()
                # Spurious-fire guard: expanding a watchlist ADDS its nested
                # checkboxes to the layout, and Dash re-fires this ALL
                # callback for newly added components with their current
                # values. Treating that as an edit bumped tab-state, which
                # re-rendered the file list and wiped the just-expanded
                # content. A value equal to the entry's current state is not
                # an operator action.
                entry = manager.get_entry_by_taxid(taxid)
                if entry is not None and bool(entry.enabled) == bool(value):
                    raise PreventUpdate
                if not manager.toggle_entry(taxid, value):
                    # The manager cannot resolve this taxid (entries from a
                    # db_taxid-keyed watchlist are stored under the database
                    # node, not the NCBI taxid the row carries). Nothing
                    # changed, so writing config/tab-state here would only
                    # feed the re-render cascade.
                    raise PreventUpdate

                # Sync watchlist state to app-config and save to disk
                updated_config = dict(current_config) if current_config else {}
                # Slim store form; _save_last_session persists the full
                # form from the singleton (round-2 audit, 2026-08-22).
                updated_config["watchlist"] = manager.export_config(slim=True)
                _save_last_session(updated_config)

                return {"last_update": f"nested-toggle-{taxid}"}, updated_config

        raise PreventUpdate

    # ---------------------------------------------------------------------
    # Pathogens Table
    # ---------------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-pathogens-table", "children"),
            Output("watchlist-pathogen-count", "children"),
            Output("watchlist-pathogen-count", "style"),
            Output("watchlist-table-pagination", "max_value"),
            Output("watchlist-table-pagination", "active_page"),
        ],
        [
            Input("watchlist-tab-state", "data"),
            Input("watchlist-table-refresh", "data"),  # Counter to force refresh
            Input("watchlist-search-input", "value"),
            Input("taxmap-rescan-complete", "data"),  # Refresh after mapping rescan
            Input("taxmap-collection", "data"),  # Mapping data from background rescan
            Input("watchlist-table-pagination", "active_page"),
        ],
        State("app-config", "data"),
        prevent_initial_call=False,
    )
    def update_pathogens_table(
        tab_state: Dict, table_refresh: int, search_term: str, rescan_complete: Any,
        taxmap_collection: Dict, active_page: Optional[int], config: Dict
    ) -> Tuple[List, str, Dict, int, Any]:
        """Update the pathogens table with Kraken2 mapping status.

        Renders one page (WATCHLIST_TABLE_PAGE_SIZE rows): a large
        watchlist rendered whole put ~3,800 components / 645 pattern ids
        into the DOM and re-serialized them on every edit. Row action ids
        are keyed by taxid, so the pattern-matching callbacks are
        page-agnostic.
        """
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
                1,
                1 if (active_page or 1) != 1 else no_update,
            )

        # Resolve the page BEFORE any per-entry work. A new search starts
        # from page 1; a page past the end (entries removed, filter
        # narrowed) clamps to the last page.
        requested_page = active_page or 1
        if ctx.triggered_id == "watchlist-search-input":
            requested_page = 1
        total_pages = max(
            1, -(-len(entries) // WATCHLIST_TABLE_PAGE_SIZE))
        page = min(requested_page, total_pages)
        page_start = (page - 1) * WATCHLIST_TABLE_PAGE_SIZE
        page_entries = entries[page_start:page_start + WATCHLIST_TABLE_PAGE_SIZE]

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
                            "match_method": mapping_data.get("match_method", ""),
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
                            "match_method": mapping_data.get("match_method", ""),
                        }

        # Fallback: try global collection if store is empty
        if not mapping_dict:
            try:
                from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
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
                                    "match_method": mapping.match_method,
                                }
            except Exception as e:
                logger.debug(f"Could not load mapping collection: {e}")

        # Index-missing banner: if the taxonomy index has not been built
        # (taxmap-collection store empty AND the global collection has no
        # entries either), the "In Database" column cannot be answered
        # yet. Say so in a banner ABOVE the table -- but still render the
        # table: the rows fall back to a neutral "Not Scanned" badge for
        # that one column, and every other control (search, toggles,
        # edit, genome status) works without the index. The earlier
        # version returned the banner INSTEAD of the table, so enabling a
        # watchlist before configuring a database hid all of its entries
        # (2026-08-17 audit, finding W9; screening itself never needed
        # the index, so the hidden entries were being screened all along).
        index_appears_empty = not mapping_dict
        index_banner = None
        if index_appears_empty:
            index_banner = dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(
                            [
                                html.I(
                                    className="bi bi-database-exclamation me-2",
                                    style={"fontSize": "1.5rem"},
                                ),
                                html.Strong("Taxonomy index is empty or stale."),
                            ],
                            className="mb-2",
                        ),
                        html.P(
                            [
                                "The 'In Database' column cannot be checked "
                                "against the Kraken2 database until the "
                                "taxonomy index has been built. Click ",
                                html.Strong("Scan Database"),
                                " in the 'Verify Watchlist Against Database' "
                                "card on this tab to (re)build the index. "
                                "Enabled organisms are still screened by "
                                "name in the meantime.",
                            ],
                            className="mb-0 text-muted small",
                        ),
                    ]
                ),
                color="warning",
                outline=True,
                className="mb-3",
            )

        # Get genome status for the visible page only: has_genome /
        # has_blast_db are stat() calls, and running them for every entry
        # cost ~500 syscalls per refresh at 129 entries.
        try:
            from nanometa_live.core.utils.genome_manager import get_genome_manager
            genome_mgr = get_genome_manager()
        except Exception:
            # Degrade to no genome status rather than failing the whole table,
            # but log it: a broken genome manager silently drops every entry's
            # download/BLAST annotation, which looks identical to "no genomes".
            logger.warning("Could not load genome manager for watchlist status; "
                           "genome annotations will be omitted", exc_info=True)
            genome_mgr = None

        # Create rows with mapping info and genome status
        rows = []
        for i, entry in enumerate(page_entries, start=page_start):
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

            # An operator-declared db_taxid is a mapping in its own right --
            # show it even before any Scan Database has run, instead of
            # "Not Scanned" (2026-08-17 reaudit, G1). The next scan
            # validates it against the loaded database.
            if mapping_info is None and entry.get("db_taxid"):
                mapping_info = {
                    "confidence": "manual",
                    "db_taxid": entry.get("db_taxid"),
                    "db_name": "",
                    "match_score": 1.0,
                    "match_method": "operator_db_taxid",
                }

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
        children = ([index_banner] if index_banner is not None else []) + rows
        # Only emit active_page when it actually moved (search reset or
        # end-clamp); echoing the incoming value re-fires this callback.
        page_out = page if page != (active_page or 1) else no_update
        return (
            children,
            str(count),
            {"display": "inline-block"},  # Show badge when there are pathogens
            total_pages,
            page_out,
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
        if not ctx.triggered_id:
            raise PreventUpdate

        manager = get_watchlist_manager()
        entries = manager.get_entries_with_toggle_state()

        if not entries:
            raise PreventUpdate

        enable = "enable-all" in ctx.triggered_id

        # One batched save: per-entry toggle_entry fsynced the toggle-state
        # YAML once PER ENTRY, tens of seconds on a large watchlist.
        # Addressed by manager_key, not the dict's NCBI taxid: fork entries
        # (one NCBI taxid, two db nodes) are stored under their db_taxid, so
        # toggling by "taxid" left them untouched -- Disable All on the
        # Bioshield list kept 4 of 129 active (verified live, 2026-08-24).
        manager.set_entries_enabled(
            [
                entry.get("manager_key") or entry.get("taxid")
                for entry in entries
                if entry.get("manager_key") or entry.get("taxid")
            ],
            enable,
        )

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
        if not ctx.triggered_id or not any(n_clicks):
            raise PreventUpdate

        # ctx.triggered_id is the dict ID for pattern-matching callbacks
        triggered_id = ctx.triggered_id
        if not isinstance(triggered_id, dict):
            raise PreventUpdate

        taxid = triggered_id.get("index")
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
            Output("watchlist-edit-organism-type", "value"),
            Output("watchlist-edit-annotation", "value"),
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
            State("watchlist-edit-organism-type", "value"),
            State("watchlist-edit-annotation", "value"),
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
        organism_type: Optional[str],
        annotation: Optional[str],
        taxmap_collection: Dict,
    ) -> Tuple:
        """Handle the edit modal open/close and save."""
        if not ctx.triggered_id:
            raise PreventUpdate

        trigger = str(ctx.triggered_id)

        # Default return values (15 outputs)
        default_return = (no_update, False, None, "", "", "moderate", "", 10, True, "", "", "", "-", "-", "-")

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
                entry.organism_type = normalize_organism_type(organism_type)
                entry.annotation = (annotation or "").strip()
            # Return tab state update to trigger table refresh
            return ({"last_update": f"edit-{edit_taxid}"}, False, None, "", "", "moderate", "", 10, True, "", "", "", "-", "-", "-")

        # Open modal for edit
        if any(edit_clicks):
            # ctx.triggered_id is already the dict for pattern-matching callbacks
            triggered_id = ctx.triggered_id
            if not isinstance(triggered_id, dict):
                raise PreventUpdate
            taxid = triggered_id.get("index")

            manager = get_watchlist_manager()
            entry = manager.get_entry_by_taxid(taxid)
            if entry:
                # The row index is the manager's storage key; NCBI-scoped
                # lookups (taxmap, the displayed NCBI id) use the entry's own
                # taxid, which differs from the key for fork entries.
                ncbi_taxid = entry.taxid

                # Get Kraken2 mapping info
                kraken_taxid = "-"
                kraken_name = "-"
                if taxmap_collection and isinstance(taxmap_collection, dict):
                    mappings = taxmap_collection.get("mappings", {})
                    if isinstance(mappings, dict):
                        mapping_data = mappings.get(str(ncbi_taxid), {})
                    elif isinstance(mappings, list):
                        mapping_data = next(
                            (m for m in mappings if m.get("ncbi_taxid") == ncbi_taxid),
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
                    entry.organism_type or "",
                    entry.annotation or "",
                    str(ncbi_taxid),
                    kraken_taxid,
                    kraken_name,
                )

        raise PreventUpdate

    # ---------------------------------------------------------------------
    # API Validation
    # ---------------------------------------------------------------------

    @app.callback(
        Output("watchlist-validation-results", "data"),
        [
            Input("watchlist-validate-all-btn", "n_clicks"),
            Input({"type": "watchlist-row-validate", "index": ALL}, "n_clicks"),
        ],
        [
            State("watchlist-api-options", "value"),
            State({"type": "watchlist-row-validate", "index": ALL}, "id"),
            State("app-config", "data"),
        ],
        background=True,
        manager=background_callback_manager,
        progress=[
            Output("watchlist-progress-bar", "value"),
            Output("watchlist-progress-text", "children"),
            Output("watchlist-progress-detail", "children"),
        ],
        running=[
            (Output("watchlist-progress-modal", "is_open"), True, False),
            (Output("watchlist-validate-all-btn", "disabled"), True, False),
        ],
        prevent_initial_call=True,
    )
    def validate_entries(
        set_progress,
        validate_all: int,
        validate_row_clicks: List[int],
        api_options: List[str],
        row_ids: List[Dict],
        config: Optional[Dict],
    ):
        """Validate watchlist entries against NCBI/GTDB in a background worker.

        Runs in a DiskcacheManager worker so the (potentially multi-minute)
        NCBI/GTDB probes never hold the Werkzeug request thread. The
        WatchlistManager singleton is empty in this worker, so it is loaded
        from config here; the per-entry results are returned as
        WatchlistEntry.to_dict() payloads via the watchlist-validation-results
        store, and apply_background_validation_results (main process) copies
        them onto the singleton the table reads. set_progress drives the
        modal progress bar; the modal open/close and button-disable are
        handled by the running= clause.
        """
        if not ctx.triggered_id:
            raise PreventUpdate

        # Guard against a spurious trigger. The per-row ``watchlist-row-validate``
        # buttons are pattern-matching inputs (index=ALL); selecting a watchlist
        # re-renders the table, ADDING those buttons, which fires this callback
        # even with prevent_initial_call=True -- and ctx.triggered_id points at a
        # freshly-added (never-clicked) button, so the guard above passed and one
        # entry validated, surfacing a bogus "Validating 1/1". A real click
        # carries a positive n_clicks as the triggered value; a component-add
        # render carries None (or 0). Bail unless it was a genuine click.
        triggered_value = ctx.triggered[0].get("value") if ctx.triggered else None
        if not triggered_value:
            raise PreventUpdate

        trigger = str(ctx.triggered_id)
        use_ncbi = "ncbi" in (api_options or [])
        use_gtdb = "gtdb" in (api_options or [])
        offline_mode = bool((config or {}).get("offline_mode", False))

        # The operator's checkboxes are honoured as given. This used to be
        # narrowed to the loaded database's detected nomenclature, which was
        # the wrong question: validate_entry_via_api looks up the WATCHLIST
        # ENTRY's own name and taxid, never a database node name, so the
        # Kraken2 database's nomenclature says nothing about which service
        # can answer. On a GTDB-nomenclature build the narrowing disabled
        # NCBI -- while 76 of 129 bioshield_agents entries are name-only and
        # NCBI's search_by_name is exactly what resolves them (2026-08-19).
        # The stall it guarded against is handled where it belongs: the
        # per-host circuit breaker, and the pseudo-taxid refusal inside
        # NCBIClient.get_by_taxid that keeps graft ids out of esummary.
        if not use_ncbi and not use_gtdb:
            return {"error": "no_databases"}

        # The singleton is empty in this worker process; load it from config.
        manager = get_watchlist_manager()
        if not manager._loaded:
            manager.load_config(config or {})

        if "validate-all" in trigger:
            entries = manager.get_entries_with_toggle_state()
            # manager_key, not the dict taxid: a fork pair shares the NCBI
            # taxid, so validating by "taxid" hit one entry twice and the
            # other never. The API call itself uses the resolved entry's own
            # NCBI taxid/name (validate_entry_via_api).
            taxids_to_validate = [
                e.get("manager_key") or e.get("taxid") for e in entries
            ]
        elif (
            isinstance(ctx.triggered_id, dict)
            and ctx.triggered_id.get("type") == "watchlist-row-validate"
        ):
            taxid = ctx.triggered_id.get("index")
            taxids_to_validate = [taxid] if taxid else []
        else:
            taxids_to_validate = []

        taxids_to_validate = [t for t in taxids_to_validate if t is not None]
        if not taxids_to_validate:
            return {"error": "no_entries"}

        total = len(taxids_to_validate)
        apis_used = [a for a, on in (("NCBI", use_ncbi), ("GTDB", use_gtdb)) if on]
        api_label = f"APIs: {', '.join(apis_used)}"
        set_progress((0, f"Validating 0/{total}", api_label))

        def _progress(current: int, total_: int) -> None:
            pct = int(current / total_ * 100) if total_ else 100
            set_progress((pct, f"Validating {current}/{total_}", api_label))

        summary = manager.bulk_validate_entries(
            taxids=taxids_to_validate,
            use_ncbi=use_ncbi,
            use_gtdb=use_gtdb,
            progress_callback=_progress,
            offline_mode=offline_mode,
        )

        # Serialize the entries we just validated for the main process.
        payloads = []
        for taxid in taxids_to_validate:
            try:
                entry = manager._entries.get(int(taxid))
            except (TypeError, ValueError):
                entry = None
            if entry is not None:
                payloads.append(entry.to_dict())

        validated = summary.get("validated", 0)
        set_progress((100, f"Validated {validated} of {total} entries", api_label))

        return {
            "results": payloads,
            "validated": validated,
            "failed": summary.get("failed", 0),
            "total": total,
            "apis": apis_used,
            "offline": offline_mode,
            # {host: human reason} when an API host failed -- lets the toast
            # explain a partial result instead of a silent count.
            "api_failures": summary.get("api_failures") or {},
        }

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-table-refresh", "data", allow_duplicate=True),
            Output("toast-message", "data", allow_duplicate=True),
        ],
        Input("watchlist-validation-results", "data"),
        [
            State("watchlist-table-refresh", "data"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def apply_background_validation_results(payload, current_refresh, config):
        """Apply background-validation results onto the main-process
        WatchlistManager singleton and refresh the table."""
        if not payload:
            raise PreventUpdate

        if payload.get("error") == "no_databases":
            return no_update, no_update, {
                "type": "warning",
                "title": "No databases selected",
                "message": "Tick NCBI and/or GTDB in the Databases section before verifying.",
            }
        if payload.get("error") == "no_entries":
            raise PreventUpdate

        manager = get_watchlist_manager()
        if not manager._loaded:
            manager.load_config(config or {})
        applied = manager.apply_validation_results(payload.get("results", []))

        validated = payload.get("validated", 0)
        total = payload.get("total", 0)
        failed = payload.get("failed", 0)
        apis = payload.get("apis", [])
        api_failures = payload.get("api_failures") or {}
        detail = f"APIs: {', '.join(apis) if apis else 'none'}"
        if payload.get("offline"):
            detail += " | offline mode: cached data only"
        elif failed:
            detail += f" | {failed} failed"
        # Name the failing host(s) and cause so a partial result is explained
        # (e.g. "GTDB: SSL certificate verification failed") rather than a
        # silent low count from a tripped circuit breaker.
        if api_failures:
            reasons = "; ".join(f"{host} {reason}" for host, reason in api_failures.items())
            detail += f" | {reasons}"

        new_refresh = (current_refresh or 0) + 1
        toast = {
            "type": "success" if validated and not failed else "warning" if failed else "info",
            "title": "Validation complete",
            "message": f"Validated {validated} of {total} entries. {detail}",
        }
        return {"last_update": f"validate-{validated}-{applied}"}, new_refresh, toast

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
        if not ctx.triggered_id:
            raise PreventUpdate

        triggered_id = ctx.triggered_id

        if triggered_id == "watchlist-api-modal-close-btn":
            return False, "", html.Div()

        if any(validated_clicks):
            if not isinstance(triggered_id, dict):
                raise PreventUpdate
            taxid = triggered_id.get("index")

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
            State("app-config", "data"),
        ],
        # Live NCBI + GTDB HTTP with 5 s timeouts and rate-limit sleeps --
        # up to ~20 s. It ran synchronously on the request thread with no
        # feedback (flagged in round 1, fixed in round 2); pure I/O, no
        # singleton writes, so plain background with a spinner suffices.
        background=True,
        manager=background_callback_manager,
        progress=[
            Output("watchlist-lookup-section", "style", allow_duplicate=True),
            Output("watchlist-lookup-results", "children", allow_duplicate=True),
        ],
        running=[(Output("watchlist-lookup-btn", "disabled"), True, False)],
        prevent_initial_call=True,
    )
    def lookup_species(
        set_progress,
        n_clicks: int,
        name: str,
        taxid: Optional[int],
        api_options: list,
        config: Optional[Dict],
    ) -> Tuple:
        """Look up species in NCBI/GTDB APIs (background worker)."""
        if not n_clicks or not name:
            raise PreventUpdate

        use_ncbi = "ncbi" in (api_options or [])
        use_gtdb = "gtdb" in (api_options or [])
        offline_mode = bool((config or {}).get("offline_mode", False))

        # No narrowing by database profile; see the note in validate_entries.
        if not use_ncbi and not use_gtdb:
            return (
                {"display": "block"},
                html.P(
                    "Select at least one database (NCBI or GTDB).",
                    className="text-warning",
                ),
                None,
            )

        try:
            sources = " and ".join(
                s for s, on in (("NCBI", use_ncbi), ("GTDB", use_gtdb)) if on)
            set_progress((
                {"display": "block"},
                dbc.Alert([
                    dbc.Spinner(size="sm", spinner_class_name="me-2"),
                    f"Querying {sources} for '{name}'...",
                ], color="info", className="py-2"),
            ))
            from nanometa_live.core.taxonomy.taxonomy_api import lookup_species as api_lookup
            result = api_lookup(name, use_ncbi=use_ncbi, use_gtdb=use_gtdb, offline_mode=offline_mode)

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
        if not ctx.triggered_id or not lookup_result:
            raise PreventUpdate

        trigger = str(ctx.triggered_id)

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
            Output("watchlist-add-organism-type", "value", allow_duplicate=True),
            Output("watchlist-add-annotation", "value", allow_duplicate=True),
            Output("watchlist-lookup-section", "style", allow_duplicate=True),
        ],
        Input("watchlist-add-btn", "n_clicks"),
        [
            State("watchlist-add-name", "value"),
            State("watchlist-add-taxid", "value"),
            State("watchlist-add-db-taxid", "value"),
            State("watchlist-add-threat", "value"),
            State("watchlist-add-threshold", "value"),
            State("watchlist-add-organism-type", "value"),
            State("watchlist-add-annotation", "value"),
            State("api-lookup-result", "data"),
        ],
        prevent_initial_call=True,
    )
    def add_custom_species(
        n_clicks: int,
        name: str,
        taxid: Optional[int],
        db_taxid: Optional[int],
        threat: str,
        threshold: int,
        organism_type: Optional[str],
        annotation: Optional[str],
        lookup_result: Dict,
    ) -> Tuple:
        """Add a custom species to the watchlist."""
        if not n_clicks or not name:
            raise PreventUpdate

        manager = get_watchlist_manager()

        entry_data = {
            "name": name.strip(),
            "taxid": int(taxid) if taxid else 0,
            "db_taxid": int(db_taxid) if db_taxid else None,  # GTDB/custom DB taxid
            "threat_level": threat or "moderate",
            "alert_threshold": int(threshold) if threshold else 10,
            "organism_type": organism_type or None,
            "annotation": (annotation or "").strip(),
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
                from datetime import datetime, timezone
                entry_data["validation_date"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"

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
                    "",  # Reset organism type
                    "",  # Clear annotation
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
                no_update,
                no_update,
            )

    # ---------------------------------------------------------------------
    # File Upload
    # ---------------------------------------------------------------------

    def _render_import_result(result):
        """Pure renderer: the finished import's result dict -> feedback alert.

        No I/O and no singleton access, so the finalize callback can reuse
        it and it is unit-testable on its own.
        """
        if result.get("invalid_errors"):
            return dbc.Alert([
                html.Strong("Invalid watchlist file"),
                html.Ul(
                    [html.Li(e, className="small")
                     for e in result["invalid_errors"]],
                    className="mb-0 ps-3",
                ),
            ], color="danger", duration=10000)

        if not result.get("success"):
            return dbc.Alert(
                f"Import failed: {result.get('message', 'see logs')}",
                color="danger", duration=8000,
            )

        filename = result.get("filename", "")
        no_taxid = result.get("no_taxid") or []
        verb = "Replaced" if result.get("overwrite") else "Imported"
        body = [
            html.Div([
                html.I(className="bi bi-check-circle me-2"),
                html.Strong(f"{verb}: {filename}"),
            ]),
            html.Small(
                f"{result.get('count', 0)} pathogens added. "
                f"Saved to {result.get('dest_dir', '')}",
                className="text-muted d-block mt-1",
            ),
        ]
        if no_taxid:
            shown = ", ".join(no_taxid[:5])
            if len(no_taxid) > 5:
                shown += f", and {len(no_taxid) - 5} more"
            body.append(html.Small(
                [
                    html.I(className="bi bi-exclamation-triangle me-2"),
                    html.Strong(
                        f"{len(no_taxid)} entr"
                        f"{'y has' if len(no_taxid) == 1 else 'ies have'} "
                        "no taxonomy ID: "
                    ),
                    f"{shown}. These are shown and counted but cannot match "
                    "a Kraken2 report. Add taxid_ncbi (or db_taxid) to each, "
                    "or resolve them with Verify Taxonomy IDs.",
                ],
                className="d-block mt-2 text-warning-emphasis",
            ))

        return dbc.Alert(
            body,
            color="warning" if no_taxid else "success",
            duration=12000 if no_taxid else 8000,
        )

    def _pending_upload_dir(loader) -> Path:
        """Directory holding decoded uploads awaiting import/confirmation.

        Lives beside the user watchlists (dot-prefixed, so discovery's
        ``*.yaml`` iteration of the parent never sees it) instead of round-
        tripping the ~120 KB base64 blob through the browser via the
        pending Store, which is what the confirm-replace flow used to do.
        """
        return Path(loader.user_watchlist_dir) / ".pending"

    def _write_pending_upload(loader, contents, dest_name) -> Path:
        """Base64-decode a dcc.Upload payload into the pending directory."""
        import base64

        _content_type, content_string = contents.split(",")
        decoded = base64.b64decode(content_string)
        pending_dir = _pending_upload_dir(loader)
        pending_dir.mkdir(parents=True, exist_ok=True)
        pending_path = pending_dir / dest_name
        pending_path.write_bytes(decoded)
        return pending_path

    def _discard_pending_upload(path_str) -> None:
        if path_str:
            Path(path_str).unlink(missing_ok=True)

    def _replace_offer_alert(message: str) -> dbc.Alert:
        """The confirm-or-cancel offer shown on a replaceable collision."""
        return dbc.Alert([
            html.Div([
                html.I(className="bi bi-exclamation-triangle me-2"),
                html.Strong("File already exists. "),
                message,
            ], className="mb-2"),
            dbc.Button(
                "Replace existing", id="watchlist-upload-replace-btn",
                color="warning", size="sm", className="me-2",
            ),
            dbc.Button(
                "Cancel", id="watchlist-upload-cancel-btn",
                color="secondary", size="sm", outline=True,
            ),
        ], color="warning")

    @app.callback(
        [
            Output("watchlist-upload-feedback", "children"),
            Output("watchlist-upload-pending", "data"),
            Output("watchlist-import-request", "data"),
        ],
        Input("watchlist-upload", "contents"),
        State("watchlist-upload", "filename"),
        running=[(Output("watchlist-upload", "disabled"), True, False)],
        prevent_initial_call=True,
    )
    def handle_upload(contents: str, filename: str) -> Tuple:
        """Accept a watchlist upload and hand it to the background importer.

        Thin on purpose: decode the payload to a pending file, classify
        collisions, and write the import request Store. The parsing,
        per-entry validation and copy happen in import_watchlist_worker
        (background, with the progress modal); session side effects happen
        in finalize_watchlist_import (main process). The synchronous
        predecessor parsed a 129-entry file 5-6 times on the request
        thread with no feedback -- a frozen screen.
        """
        if not contents or not filename:
            raise PreventUpdate

        from nanometa_live.core.watchlist.watchlist_loader import get_watchlist_loader

        pending_path = None
        try:
            loader = get_watchlist_loader()
            dest_name = loader.sanitize_upload_name(filename)
            if dest_name is None:
                return (
                    dbc.Alert(f"'{filename}' is not a usable watchlist "
                              f"file name.", color="danger", duration=8000),
                    None,
                    no_update,
                )

            pending_path = _write_pending_upload(loader, contents, dest_name)

            # A collision with the operator's OWN earlier file is offered as
            # a confirmed replacement; shadowing a built-in list stays
            # refused (finding W2 -- the refusal used to promise "confirm
            # the replacement" while no confirm control existed).
            collision = loader.classify_upload_collision(filename)
            if collision is not None:
                kind, message = collision
                if kind == "builtin":
                    _discard_pending_upload(str(pending_path))
                    return (
                        dbc.Alert(f"Import failed: {message}", color="danger",
                                  duration=10000),
                        None,
                        no_update,
                    )
                # Only the file's location crosses the browser now; the
                # decoded bytes used to round-trip as a ~120 KB base64 blob.
                return (
                    _replace_offer_alert(message),
                    {"path": str(pending_path), "filename": filename},
                    no_update,
                )

            return (
                dbc.Alert([
                    dbc.Spinner(size="sm", spinner_class_name="me-2"),
                    f"Importing {filename}...",
                ], color="info", className="py-2"),
                None,
                {"path": str(pending_path), "filename": filename,
                 "overwrite": False, "nonce": os.urandom(4).hex()},
            )

        except Exception as e:
            if pending_path is not None:
                _discard_pending_upload(str(pending_path))
            return (
                dbc.Alert(f"Upload failed: {e}", color="danger", duration=8000),
                None,
                no_update,
            )

    @app.callback(
        Output("watchlist-import-result", "data"),
        Input("watchlist-import-request", "data"),
        background=True,
        manager=background_callback_manager,
        progress=[
            Output("watchlist-progress-bar", "value", allow_duplicate=True),
            Output("watchlist-progress-text", "children", allow_duplicate=True),
            Output("watchlist-progress-detail", "children", allow_duplicate=True),
        ],
        running=[
            (Output("watchlist-progress-modal", "is_open", allow_duplicate=True),
             True, False),
            (Output("watchlist-upload", "disabled", allow_duplicate=True),
             True, False),
        ],
        prevent_initial_call=True,
    )
    def import_watchlist_worker(set_progress, request: Dict):
        """Background half of the watchlist import: file I/O only.

        Runs in a DiskcacheManager worker process, so it must not touch
        the WatchlistManager singleton, the loader caches the live app
        reads, or any dcc.Store the finalize callback owns -- none of
        those mutations would reach the main process. The file on disk is
        its only product; finalize_watchlist_import applies the session
        side effects.
        """
        if not request or not request.get("path"):
            raise PreventUpdate

        from nanometa_live.core.watchlist.watchlist_loader import get_watchlist_loader

        filename = request.get("filename", "")
        pending_path = Path(request["path"])
        result = {
            "nonce": request.get("nonce"),
            "filename": filename,
            "path": str(pending_path),
            "overwrite": bool(request.get("overwrite")),
            "success": False,
        }
        try:
            if not pending_path.exists():
                result["message"] = (
                    "The uploaded file is no longer available (the server "
                    "may have restarted). Upload it again."
                )
                return result

            loader = get_watchlist_loader()
            set_progress((5, "Validating watchlist...", filename))

            def _entry_progress(done, total):
                set_progress((
                    5 + int(75 * done / max(total, 1)),
                    f"Validating entries ({done}/{total})...",
                    filename,
                ))

            is_valid, errors, parsed = loader.validate_and_parse(
                pending_path, progress_cb=_entry_progress)
            if not is_valid:
                result["invalid_errors"] = errors
                return result

            set_progress((85, "Checking taxonomy IDs...", filename))
            no_taxid = loader.entries_without_taxid(parsed)

            set_progress((92, "Saving watchlist...", filename))
            success, message = loader.import_watchlist(
                pending_path, destination="user", file_name=filename,
                overwrite=result["overwrite"], parsed=parsed,
            )
            result["success"] = success
            result["message"] = message
            if success:
                dest_name = loader.sanitize_upload_name(filename)
                result["dest_name"] = dest_name
                result["watchlist_id"] = Path(dest_name).stem
                result["dest_dir"] = str(loader.user_watchlist_dir)
                result["count"] = len((parsed or {}).get("pathogens") or [])
                result["no_taxid"] = no_taxid
            set_progress((100, "Activating...", filename))
            return result
        except Exception as e:
            logger.error(f"Watchlist import failed: {e}", exc_info=True)
            result["message"] = str(e)
            return result

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-upload-feedback", "children", allow_duplicate=True),
        ],
        Input("watchlist-import-result", "data"),
        prevent_initial_call=True,
    )
    def finalize_watchlist_import(result: Dict) -> Tuple:
        """Main-process half of the import: session side effects + render.

        The worker ran in a separate OS process, so its loader cache clears
        and any manager state died with it. Everything the live app must
        see happens here: cache invalidation, loading the imported file
        into the WatchlistManager singleton, and the tab-state bump that
        re-renders the watchlist views.
        """
        if not result:
            raise PreventUpdate

        from nanometa_live.core.watchlist.watchlist_loader import get_watchlist_loader

        _discard_pending_upload(result.get("path"))

        if not result.get("success"):
            return no_update, _render_import_result(result)

        loader = get_watchlist_loader()
        loader.invalidate_cache()

        # Load into active session. The destination name must come from
        # the same sanitizer import_watchlist used -- deriving it from
        # the raw browser filename made the two disagree for any name
        # the sanitizer changed, so the file was imported but never
        # activated while the alert still claimed success (finding W1).
        manager = get_watchlist_manager()
        dest_file = Path(result.get("dest_dir", "")) / result.get("dest_name", "")
        if dest_file.exists():
            manager._load_custom_yaml_file(str(dest_file))

        filename = result.get("filename", "")
        return {"last_update": f"upload-{filename}"}, _render_import_result(result)

    @app.callback(
        [
            Output("watchlist-upload-feedback", "children", allow_duplicate=True),
            Output("watchlist-upload-pending", "data", allow_duplicate=True),
            Output("watchlist-import-request", "data", allow_duplicate=True),
        ],
        Input("watchlist-upload-replace-btn", "n_clicks"),
        State("watchlist-upload-pending", "data"),
        prevent_initial_call=True,
    )
    def handle_replace_upload(n_clicks: int, pending: Dict) -> Tuple:
        """Operator confirmed replacing their existing watchlist file."""
        if not n_clicks or not pending:
            raise PreventUpdate

        filename = pending.get("filename", "")
        return (
            dbc.Alert([
                dbc.Spinner(size="sm", spinner_class_name="me-2"),
                f"Replacing {filename}...",
            ], color="info", className="py-2"),
            None,
            {"path": pending.get("path"), "filename": filename,
             "overwrite": True, "nonce": os.urandom(4).hex()},
        )

    @app.callback(
        [
            Output("watchlist-upload-feedback", "children", allow_duplicate=True),
            Output("watchlist-upload-pending", "data", allow_duplicate=True),
        ],
        Input("watchlist-upload-cancel-btn", "n_clicks"),
        State("watchlist-upload-pending", "data"),
        prevent_initial_call=True,
    )
    def handle_cancel_replace(n_clicks: int, pending: Optional[Dict]) -> Tuple:
        """Operator declined the replacement; drop the pending upload."""
        if not n_clicks:
            raise PreventUpdate
        if pending:
            _discard_pending_upload(pending.get("path"))
        return (
            dbc.Alert("Upload cancelled; the existing file was kept.",
                      color="secondary", duration=5000),
            None,
        )

    # ---------------------------------------------------------------------
    # Download the current watchlist as YAML
    # ---------------------------------------------------------------------

    @app.callback(
        Output("watchlist-download", "data"),
        Input("watchlist-download-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_download_watchlist(n_clicks):
        """Serialise the active watchlist selection to a shareable YAML file.

        Species added through "Add custom species" exist only in the session
        (they reach disk only indirectly, inside last-session.yaml), so this
        is the only way to turn a curated selection into a file that can be
        re-imported or handed to another operator.
        """
        if not n_clicks:
            raise PreventUpdate

        import yaml as _yaml
        from nanometa_live.core.watchlist.watchlist_loader import (
            build_watchlist_yaml,
        )

        manager = get_watchlist_manager()
        entries = [e.to_dict() for e in manager.get_active_entries().values()]
        doc = build_watchlist_yaml(
            entries,
            name="Nanometa Live watchlist export",
            description=(
                f"{len(entries)} active organisms, exported "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M')}."
            ),
        )
        text = _yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return dict(content=text, filename=f"watchlist-{stamp}.yaml")

    # -----------------------------------------------------------------
    # Delete custom watchlist
    # -----------------------------------------------------------------

    @app.callback(
        [
            Output("watchlist-tab-state", "data", allow_duplicate=True),
            Output("watchlist-upload-feedback", "children", allow_duplicate=True),
        ],
        Input({"type": "watchlist-file-delete", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_delete_watchlist(n_clicks_list):
        """Delete a custom (user) watchlist file and remove from session."""
        if not n_clicks_list or not any(n_clicks_list):
            raise PreventUpdate

        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            raise PreventUpdate

        watchlist_id = triggered.get("index", "")
        if not watchlist_id:
            raise PreventUpdate

        from pathlib import Path
        from nanometa_live.core.watchlist.watchlist_loader import get_watchlist_loader

        # Only allow deleting user watchlists
        loader = get_watchlist_loader()
        watchlists = loader.discover_watchlists()
        target = None
        for wl in watchlists:
            if wl.id == watchlist_id and wl.source == "user":
                target = wl
                break

        if not target:
            return (
                no_update,
                dbc.Alert("Only custom watchlists can be deleted.", color="warning", duration=5000),
            )

        try:
            # Disable in manager first
            manager = get_watchlist_manager()
            manager.disable_watchlist(watchlist_id)

            # Delete the file
            target.file_path.unlink(missing_ok=True)

            # Clear loader cache so it's no longer discovered
            loader._cached_watchlists.pop(watchlist_id, None)
            loader._loaded_pathogens.pop(watchlist_id, None)

            return (
                {"last_update": f"delete-{watchlist_id}"},
                dbc.Alert([
                    html.I(className="bi bi-trash me-2"),
                    f"Removed: {target.name}",
                ], color="info", duration=5000),
            )
        except Exception as e:
            return (
                no_update,
                dbc.Alert(f"Delete failed: {e}", color="danger", duration=5000),
            )

    logger.info("Watchlist tab callbacks registered")
