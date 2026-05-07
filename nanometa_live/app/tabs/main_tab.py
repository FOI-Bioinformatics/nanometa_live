"""
Main results tab callbacks for Nanometa Live v2.0.

This module defines the callbacks for the main results tab, which displays
organism results with visual cards, watched species alerts, and a summary
for operator-friendly viewing.

MODERNIZED: Uses OrganismCard, OrganismSummaryCard components, watched species
detection, alert banners, and matches the layout in main_layout.py.

Includes on-demand BLAST validation for unexpected organisms discovered during
analysis that are not on the pre-configured watchlist.
"""

import json
import logging
import os
import pandas as pd
from datetime import datetime
from typing import List

import dash
from dash import Dash, Input, Output, State, ctx, no_update, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.validation_loaders import load_blast_validation_data
from nanometa_live.app.components.organism_components import (
    OrganismCard,
    OrganismSummaryCard,
)
from nanometa_live.app.components.modern_components import EmptyStateMessage
# Chart functionality moved to Taxonomy tab - no chart builders needed here
from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
from nanometa_live.app.utils.callback_helpers import (
    validate_config_and_get_main_dir,
    log_callback_error,
    create_empty_alert,
    create_error_alert,
)


# =============================================================================
# Watchlist utility functions (use WatchlistManager)
# =============================================================================

def species_in_watchlist(taxid: int, watchlist: list) -> bool:
    """Check if a species is in the watchlist by taxid."""
    if not watchlist:
        return False
    return any(s.get("taxid") == taxid for s in watchlist)


def add_species_to_watchlist(species: dict, watchlist: list) -> list:
    """Add a species to the watchlist."""
    if not watchlist:
        watchlist = []
    # Avoid duplicates by taxid
    if species.get("taxid") and species_in_watchlist(species["taxid"], watchlist):
        return watchlist
    return watchlist + [species]


def remove_species_from_watchlist(taxid: int, watchlist: list) -> list:
    """Remove a species from the watchlist by taxid."""
    if not watchlist:
        return []
    return [s for s in watchlist if s.get("taxid") != taxid]


def filter_detected_species(kraken_df, watchlist: list) -> list:
    """
    Filter detected species from kraken data that are in the watchlist.

    Uses proper taxid mapping to handle GTDB and custom Kraken2 databases
    where taxids differ from NCBI taxids.

    Returns only SPECIES-level entries that are DETECTED (have reads > 0).
    Filters out higher taxonomic ranks (class, order, family, etc.) to avoid
    false positives from parent taxa.
    """
    if kraken_df is None or kraken_df.empty or not watchlist:
        return []

    # Get WatchlistManager and active entries
    manager = get_watchlist_manager()
    active_entries = manager.get_active_entries()

    # Get taxid mapping collection for proper db_taxid -> ncbi_taxid lookup
    from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
    mapping_collection = get_mapping_collection()

    # Build reverse mapping: Kraken2 db_taxid -> NCBI taxid
    # This is critical for GTDB databases where taxids are different
    db_to_ncbi = {}
    if mapping_collection:
        for ncbi_taxid, mapping in mapping_collection.mappings.items():
            if mapping.db_taxid:
                db_to_ncbi[mapping.db_taxid] = ncbi_taxid

    # Collect NCBI taxids from active watchlist entries
    ncbi_taxids = {e.taxid for e in active_entries.values() if e.taxid}
    active_names = {e.name.lower().strip() for e in active_entries.values()}

    # Also include legacy watchlist taxids/names
    legacy_taxids = {s.get("taxid") for s in watchlist if s.get("taxid")}
    legacy_names = {s.get("name", "").lower().strip() for s in watchlist if s.get("name")}

    all_ncbi_taxids = ncbi_taxids | legacy_taxids
    all_names = active_names | legacy_names

    # Prepare kraken data for matching
    kraken_df = kraken_df.copy()
    kraken_df['taxid_int'] = kraken_df['taxid'].fillna(0).astype(int)
    kraken_df['name_lower'] = kraken_df['name'].fillna('').str.lower().str.strip()
    kraken_df['rank_clean'] = kraken_df['rank'].fillna('').str.strip()

    # Filter to species-level only (S = species, S1/S2 = subspecies)
    # Exclude higher ranks like C (class), O (order), F (family), G (genus)
    species_ranks = {'S', 'S1', 'S2'}
    species_mask = kraken_df['rank_clean'].isin(species_ranks)
    species_df = kraken_df[species_mask]

    if species_df.empty:
        return []

    # Map Kraken2 taxids to NCBI taxids for comparison
    # This handles GTDB databases where db_taxid != ncbi_taxid
    species_df = species_df.copy()
    species_df['mapped_ncbi_taxid'] = species_df['taxid_int'].map(
        lambda x: db_to_ncbi.get(x, x)  # Use mapped taxid if available, else original
    )

    # Match by:
    # 1. Mapped NCBI taxid (handles GTDB -> NCBI mapping)
    # 2. Direct Kraken2 taxid (for NCBI databases where taxid matches)
    # 3. Name matching (fallback, less reliable)
    mask = (
        species_df['mapped_ncbi_taxid'].isin(all_ncbi_taxids) |
        species_df['taxid_int'].isin(all_ncbi_taxids) |
        species_df['name_lower'].isin(all_names)
    )
    matched_df = species_df[mask]

    if matched_df.empty:
        return []

    # Convert to list of dicts, preserving the original Kraken2 taxid
    result_df = pd.DataFrame({
        'taxid': matched_df['taxid_int'],  # Original Kraken2 taxid for display
        'ncbi_taxid': matched_df['mapped_ncbi_taxid'],  # Mapped NCBI taxid
        'name': matched_df['name'].fillna('Unknown'),
        'reads': matched_df['reads'].fillna(0).astype(int),
        'abundance': matched_df['%'].fillna(0.0).astype(float),
        'rank': matched_df['rank_clean']
    })
    return result_df.to_dict('records')


def get_all_watchlist_with_detection(kraken_df, watchlist: list) -> list:
    """
    Get ALL watchlist entries with their detection status from Kraken2 data.

    Unlike filter_detected_species, this returns ALL watchlist entries
    regardless of detection status. Undetected entries have reads=0.

    This provides complete visibility into what's being monitored.
    """
    # Get WatchlistManager and active entries
    manager = get_watchlist_manager()
    active_entries = manager.get_active_entries()

    if not active_entries and not watchlist:
        return []

    # Get taxid mapping collection for proper db_taxid -> ncbi_taxid lookup
    from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
    mapping_collection = get_mapping_collection()

    # Build mapping: NCBI taxid -> Kraken2 db_taxid
    ncbi_to_db = {}
    if mapping_collection:
        for ncbi_taxid, mapping in mapping_collection.mappings.items():
            if mapping.db_taxid:
                ncbi_to_db[ncbi_taxid] = mapping.db_taxid

    # Also build reverse mapping for lookups
    db_to_ncbi = {v: k for k, v in ncbi_to_db.items()}

    # Prepare kraken data for matching (if available)
    kraken_lookup = {}
    if kraken_df is not None and not kraken_df.empty:
        kraken_df = kraken_df.copy()
        kraken_df['taxid_int'] = kraken_df['taxid'].fillna(0).astype(int)

        # Build lookup vectorized (avoid iterrows for performance with large dataframes)
        valid_mask = kraken_df['taxid_int'] > 0
        for taxid, reads, abundance, name in zip(
            kraken_df.loc[valid_mask, 'taxid_int'],
            kraken_df.loc[valid_mask, 'reads'].fillna(0).astype(int),
            kraken_df.loc[valid_mask, '%'].fillna(0.0).astype(float),
            kraken_df.loc[valid_mask, 'name'].fillna(''),
        ):
            entry = {'reads': int(reads), 'abundance': float(abundance), 'name': name}
            kraken_lookup[int(taxid)] = entry
            # Also store by mapped NCBI taxid if different
            ncbi_taxid = db_to_ncbi.get(int(taxid), int(taxid))
            if ncbi_taxid != int(taxid):
                kraken_lookup[ncbi_taxid] = entry

    # Build result list from ALL active watchlist entries
    result = []
    seen_taxids = set()

    for entry_id, entry in active_entries.items():
        if entry.taxid in seen_taxids:
            continue
        seen_taxids.add(entry.taxid)

        # Try to find detection in Kraken2 data
        # 1. Check by NCBI taxid directly
        # 2. Check by mapped Kraken2 db_taxid
        detection = None
        db_taxid = ncbi_to_db.get(entry.taxid, entry.taxid)

        if entry.taxid in kraken_lookup:
            detection = kraken_lookup[entry.taxid]
        elif db_taxid in kraken_lookup:
            detection = kraken_lookup[db_taxid]

        result.append({
            'taxid': db_taxid,  # Use Kraken2 db_taxid for display
            'ncbi_taxid': entry.taxid,
            'name': entry.name,
            'reads': detection['reads'] if detection else 0,
            'abundance': detection['abundance'] if detection else 0.0,
            'detected': detection is not None and detection['reads'] > 0,
            'category': entry.category,
            'threat_level': entry.threat_level.value if entry.threat_level else 'unknown'
        })

    # Also include legacy watchlist entries not in WatchlistManager
    for s in watchlist:
        taxid = s.get("taxid")
        if taxid and taxid not in seen_taxids:
            seen_taxids.add(taxid)
            db_taxid = ncbi_to_db.get(taxid, taxid)
            detection = kraken_lookup.get(taxid) or kraken_lookup.get(db_taxid)

            result.append({
                'taxid': db_taxid,
                'ncbi_taxid': taxid,
                'name': s.get("name", "Unknown"),
                'reads': detection['reads'] if detection else 0,
                'abundance': detection['abundance'] if detection else 0.0,
                'detected': detection is not None and detection['reads'] > 0,
                'category': 'custom',
                'threat_level': 'unknown'
            })

    # Sort by: detected first (desc), then by reads (desc), then by name
    result.sort(key=lambda x: (-int(x['detected']), -x['reads'], x['name'].lower()))

    return result


def create_species_alert_banner(detected_species: list) -> html.Div:
    """Create an alert banner for detected watched species."""
    if not detected_species:
        return None

    species_names = [s["name"] for s in detected_species[:5]]
    count = len(detected_species)

    if count == 1:
        message = f"Watched species detected: {species_names[0]}"
    elif count <= 5:
        message = f"Watched species detected: {', '.join(species_names)}"
    else:
        message = f"Watched species detected: {', '.join(species_names)} (+{count - 5} more)"

    return dbc.Alert([
        html.I(className="bi bi-exclamation-triangle-fill me-2"),
        html.Strong("Alert: "),
        message,
    ], color="warning", className="mb-3")


def register_main_callbacks(app: Dash):
    """
    Register callbacks for the main results tab.

    Args:
        app: Dash application
    """

    @app.callback(
        [
            Output("organism-summary-container", "children"),
            Output("organism-cards-container", "children"),
            Output("detailed-organism-table", "rowData"),
            Output("total-organisms-count", "children"),
            Output("organism-results-count", "children"),
            Output("watched-species-alert-container", "children"),
            Output("watched-organisms-section", "style"),
            Output("watched-organisms-cards", "children"),
            Output("watched-organisms-count", "children"),
        ],
        [
            Input("results-fingerprint", "data"),
            Input("apply-organism-filters", "n_clicks"),
            Input("selected-sample", "data"),
            Input("main-watchlist-store", "data"),  # React to watchlist changes
        ],
        [
            State("top-organisms-count", "value"),
            State("min-abundance", "value"),
            State("tax-rank-filter", "value"),
            State("app-config", "data"),
            State("backend-status", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_main_results(
        _fingerprint, apply_clicks, selected_sample, watchlist_store,
        top_count, min_abundance, tax_ranks, config, status,
    ):
        """
        Update the main results tab with organism summary, cards, table,
        and watched species alerts.

        This callback populates:
        - organism-summary-container: OrganismSummaryCard with overview stats
        - organism-cards-container: List of OrganismCard components
        - detailed-organism-table: DataTable with full organism data
        - total-organisms-count: Badge showing number of organisms
        - watched-species-alert-container: Alert banner for watched species
        - watched-organisms-section: Show/hide based on detection
        - watched-organisms-cards: Cards for detected watched species
        - watched-organisms-count: Badge showing count

        Note: Charts have been moved to Taxonomy tab to reduce redundancy.
        """

        # Default empty returns
        empty_summary = EmptyStateMessage(
            title="No Organism Data",
            message="Select a sample or start an analysis to view organism results",
            icon="bi-bug"
        )
        empty_cards = EmptyStateMessage(
            title="Awaiting Results",
            message="Organism cards will appear here once analysis is complete",
            icon="bi-hourglass"
        )
        empty_table = []
        empty_count = "0"
        no_alert = None
        hidden_style = {"display": "none"}
        empty_watched = EmptyStateMessage(
            title="No Watched Organisms",
            message="No watched organisms detected in this sample.",
            icon="bi-star"
        )
        watched_count = "0"

        # Validate config and get output directory using centralized helper
        main_dir = validate_config_and_get_main_dir(config)
        if not main_dir:
            return (empty_summary, empty_cards, empty_table, empty_count,
                    empty_count, no_alert, hidden_style, empty_watched, watched_count)

        # Set filter defaults
        top_count = top_count or 10
        min_abundance = min_abundance or 0.1
        tax_ranks = tax_ranks or ["S", "G"]

        # Get watchlist from WatchlistManager (single source of truth)
        # The store input (watchlist_store) acts as a change trigger only
        manager = get_watchlist_manager()
        watchlist = [
            {"taxid": e.taxid, "name": e.name}
            for e in manager.get_active_entries().values()
        ]

        try:
            # Load Kraken2 data using data loader (supports per-sample filtering)
            kraken_df = load_kraken_data(main_dir, selected_sample)

            if kraken_df.empty:
                logging.debug("Main Results: No Kraken2 data found")
                return (empty_summary, empty_cards, empty_table, empty_count,
                        empty_count, no_alert, hidden_style, empty_watched, watched_count)

            logging.debug(f"Main Results: Loaded {len(kraken_df)} rows from Kraken2 data")

            # Calculate summary statistics
            total_reads = int(kraken_df['reads'].sum())
            unclassified_row = kraken_df[kraken_df['taxid'] == 0]
            unclassified_reads = int(unclassified_row.iloc[0]['reads']) if not unclassified_row.empty else 0
            classified_reads = total_reads - unclassified_reads
            classification_rate = (classified_reads / total_reads * 100) if total_reads > 0 else 0

            # Filter to selected taxonomic ranks
            filtered_df = kraken_df[kraken_df['rank'].isin(tax_ranks)]

            # Filter by minimum abundance
            filtered_df = filtered_df[filtered_df['%'] >= min_abundance]

            # Exclude unclassified and root
            filtered_df = filtered_df[filtered_df['taxid'] > 1]

            # Sort by cumulative reads (node + all descendants) and take top N.
            # For genus-level entries cumul_reads captures all species underneath,
            # which is consistent with the abundance percentage shown on each card.
            filtered_df = filtered_df.sort_values('cumul_reads', ascending=False).head(top_count)

            # Count unique organisms at species/genus level
            species_df = kraken_df[kraken_df['rank'].isin(['S', 'G'])]
            species_df = species_df[species_df['taxid'] > 1]
            species_df = species_df[species_df['reads'] > 0]
            total_organisms = len(species_df)

            # Find most abundant organism
            most_abundant = None
            if not filtered_df.empty:
                top_row = filtered_df.iloc[0]
                most_abundant = {
                    "name": top_row['name'].strip(),
                    "abundance": float(top_row['%'])
                }

            # Create summary card
            summary_card = OrganismSummaryCard(
                total_organisms=total_organisms,
                total_reads=total_reads,
                classification_rate=classification_rate,
                most_abundant=most_abundant
            )

            # Check for watched species in the data (detected only - for alert)
            detected_watched = filter_detected_species(kraken_df, watchlist)

            # Get ALL watchlist entries with detection status (for display)
            all_watchlist_species = get_all_watchlist_with_detection(kraken_df, watchlist)

            # Create alert banner if watched species detected
            alert_banner = None
            if detected_watched:
                alert_banner = create_species_alert_banner(detected_watched)

            # Load BLAST validation data if enabled
            blast_validation_data = {}
            blast_validation_enabled = config.get('blast_validation', False)
            if blast_validation_enabled and watchlist:
                blast_validation_data = load_blast_validation_data(
                    main_dir, watchlist, selected_sample
                )
                logging.debug(f"Loaded BLAST validation for {len(blast_validation_data)} species")

            # Get confidence thresholds from config (with defaults)
            high_confidence_threshold = config.get('high_confidence_reads', 1000)
            medium_confidence_threshold = config.get('medium_confidence_reads', 100)

            # Split watchlist species into detected and not detected
            detected_cards = []
            not_detected_cards = []
            watched_style = hidden_style

            if all_watchlist_species:
                watched_style = {"display": "block"}

                for species in all_watchlist_species:
                    is_detected = species.get('detected', False)

                    # Determine confidence based on detection and read count
                    if not is_detected:
                        confidence = "none"  # Not detected
                    elif species['reads'] >= high_confidence_threshold:
                        confidence = "high"
                    elif species['reads'] >= medium_confidence_threshold:
                        confidence = "medium"
                    else:
                        confidence = "low"

                    # Get BLAST validation data for this species (if available)
                    species_taxid = int(species['taxid'])
                    blast_data = blast_validation_data.get(species_taxid, None)

                    card = OrganismCard(
                        name=species['name'],
                        abundance=species['abundance'],
                        read_count=species['reads'],
                        confidence=confidence,
                        taxid=species['taxid'],
                        rank="S",
                        is_watched=True,
                        blast_validation=blast_data
                    )
                    col = dbc.Col(card, md=6, lg=4, className="mb-3")

                    if is_detected:
                        detected_cards.append(col)
                    else:
                        not_detected_cards.append(col)

            # Build the watched organisms section with detected/not-detected split
            watched_cards_content = []

            # Detected section (always visible if there are detected species)
            if detected_cards:
                watched_cards_content.append(
                    html.Div([
                        html.H6([
                            html.I(className="bi bi-exclamation-triangle-fill text-danger me-2"),
                            f"Detected ({len(detected_cards)})"
                        ], className="mb-3 text-danger"),
                        dbc.Row(detected_cards)
                    ], className="mb-4")
                )

            # Not detected section (collapsible, collapsed by default)
            if not_detected_cards:
                watched_cards_content.append(
                    html.Div([
                        dbc.Button(
                            [
                                html.I(className="bi bi-check-circle text-secondary me-2"),
                                f"Not Detected ({len(not_detected_cards)})",
                                html.I(className="bi bi-chevron-down ms-2", id="not-detected-chevron")
                            ],
                            id="not-detected-collapse-btn",
                            color="light",
                            className="mb-3 w-100 text-start",
                            style={"border": "1px solid #dee2e6"}
                        ),
                        dbc.Collapse(
                            dbc.Row(not_detected_cards),
                            id="not-detected-collapse",
                            is_open=False  # Collapsed by default
                        )
                    ])
                )

            # If no detected and no not-detected, show empty message
            if not watched_cards_content:
                watched_cards = empty_watched
            else:
                watched_cards = html.Div(watched_cards_content)

            # Exclude ALL watchlist species from main organism cards (they're shown separately)
            watched_taxids = {s['taxid'] for s in all_watchlist_species}

            # Create organism cards - vectorized approach
            # First filter out watched taxids
            non_watched_df = filtered_df[~filtered_df['taxid'].astype(int).isin(watched_taxids)]

            # Extract columns as lists for fast iteration
            names = non_watched_df['name'].str.strip().tolist()
            abundances = non_watched_df['%'].astype(float).tolist()
            read_counts = non_watched_df['cumul_reads'].astype(int).tolist()
            taxids = non_watched_df['taxid'].astype(int).tolist()
            ranks = non_watched_df['rank'].tolist()

            # Check if BLAST validation is enabled for showing validate buttons
            blast_validation_enabled = config.get('blast_validation', False)

            # Minimum reads to show validate button (avoid noise)
            min_reads_for_validation = config.get('min_reads_for_validation', 50)

            organism_cards = []
            for name, abundance, read_count, taxid, rank in zip(names, abundances, read_counts, taxids, ranks):
                # Determine confidence based on read count (using configurable thresholds)
                if read_count >= high_confidence_threshold:
                    confidence = "high"
                elif read_count >= medium_confidence_threshold:
                    confidence = "medium"
                else:
                    confidence = "low"

                # Show validate button for non-watched organisms with sufficient reads
                # when BLAST validation is enabled
                show_validate = (
                    blast_validation_enabled and
                    read_count >= min_reads_for_validation and
                    rank == "S"  # Only species-level
                )

                card = OrganismCard(
                    name=name,
                    abundance=abundance,
                    read_count=read_count,
                    confidence=confidence,
                    taxid=taxid,
                    rank=rank,
                    show_validate_button=show_validate
                )
                organism_cards.append(dbc.Col(card, md=6, lg=4, className="mb-3"))

            # Wrap cards in a Row with "Show more" if > 20
            MAX_VISIBLE_CARDS = 20
            if organism_cards:
                if len(organism_cards) > MAX_VISIBLE_CARDS:
                    visible = organism_cards[:MAX_VISIBLE_CARDS]
                    hidden = organism_cards[MAX_VISIBLE_CARDS:]
                    cards_container = html.Div([
                        dbc.Row(visible),
                        dbc.Collapse(
                            dbc.Row(hidden),
                            id="organism-cards-overflow",
                            is_open=False,
                        ),
                        html.Div(
                            dbc.Button(
                                f"Show {len(hidden)} more organisms",
                                id="show-more-organisms-btn",
                                color="secondary",
                                outline=True,
                                size="sm",
                                className="mt-2",
                            ),
                            className="text-center",
                        ),
                    ])
                else:
                    cards_container = dbc.Row(organism_cards)
            else:
                cards_container = EmptyStateMessage(
                    title="No Matches",
                    message="No additional organisms found matching the current filters. "
                            "Try adjusting the minimum abundance or taxonomic rank filters.",
                    icon="bi-funnel"
                )

            # Create table data (vectorized)
            # Use cumul_reads for consistency with the organism cards and
            # the abundance percentage, which both reflect cumulative counts.
            table_df = pd.DataFrame({
                'name': filtered_df['name'].str.strip(),
                'taxid': filtered_df['taxid'].astype(int),
                'rank': filtered_df['rank'],
                'reads': filtered_df['cumul_reads'].astype(int),
                'abundance': filtered_df['%'].astype(float).round(2)
            })
            table_data = table_df.to_dict('records')

            # Count detected vs total watchlist entries
            detected_count = len(detected_watched)
            total_watchlist = len(all_watchlist_species)
            watched_count_str = f"{detected_count}/{total_watchlist}" if total_watchlist > 0 else "0"

            logging.debug(f"Main Results: Returning {len(organism_cards)} organism cards, {detected_count}/{total_watchlist} watched")

            return (
                summary_card,
                cards_container,
                table_data,
                str(len(filtered_df)),
                str(len(filtered_df)),
                alert_banner,
                watched_style,
                watched_cards if all_watchlist_species else empty_watched,
                watched_count_str,
            )

        except Exception as e:
            logging.error(f"Error updating main results: {e}")
            import traceback
            traceback.print_exc()

            error_alert = dbc.Alert(
                f"Error loading organism data: {str(e)}",
                color="danger",
                className="text-center"
            )
            return (error_alert, error_alert, [], "0", "0", None, hidden_style, empty_watched, "0")

    # Sync watchlist from config to main tab store
    @app.callback(
        [
            Output("main-watchlist-store", "data"),
            Output("notification-trigger", "data", allow_duplicate=True),
        ],
        Input("app-config", "data"),
        prevent_initial_call=True,
    )
    def sync_watchlist(config):
        """Sync watchlist entries from WatchlistManager to main tab store.

        On the failure path the store is set to the empty list (so
        downstream callbacks fail closed rather than crashing), AND a
        toast is fired so the operator sees that something went wrong.
        Without the toast, the Organisms tab and the watched-species
        alert silently look like the watchlist is empty -- exactly the
        symptom the 2026-05-02 audit followup F1 flagged.
        """
        if not config:
            return [], no_update
        try:
            manager = get_watchlist_manager()
            if not manager._loaded:
                manager.load_config(config)
            entries = manager.get_active_entries()
            return (
                [{"name": e.name, "taxid": e.taxid} for e in entries.values()],
                no_update,
            )
        except Exception as e:
            logging.exception(
                "sync_watchlist failed; main-watchlist-store will be empty"
            )
            return [], {
                "title": "Watchlist failed to load",
                "message": (
                    "Could not read the active watchlist. The Organisms "
                    "tab and watched-species alert will look empty until "
                    "this is fixed. Check the terminal log for details. "
                    f"({type(e).__name__}: {e})"
                ),
                "color": "danger",
            }

    # Show more organisms toggle
    @app.callback(
        [
            Output("organism-cards-overflow", "is_open"),
            Output("show-more-organisms-btn", "children"),
        ],
        Input("show-more-organisms-btn", "n_clicks"),
        State("organism-cards-overflow", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_show_more_organisms(n_clicks, is_open):
        """Toggle visibility of overflow organism cards."""
        if not n_clicks:
            return no_update, no_update
        new_state = not is_open
        label = "Show fewer organisms" if new_state else "Show more organisms"
        return new_state, label

    # Export modal callbacks - open modal and pre-select format
    @app.callback(
        [
            Output("export-modal", "is_open"),
            Output("export-format-select", "value"),
        ],
        [
            Input("export-all-txt", "n_clicks"),
            Input("export-all-csv", "n_clicks"),
            Input("export-all-xlsx", "n_clicks"),
            Input("confirm-export", "n_clicks"),
            Input("cancel-export", "n_clicks"),
        ],
        [
            State("export-modal", "is_open"),
            State("export-format-select", "value"),
        ],
        prevent_initial_call=True,
    )
    def toggle_export_modal(txt_clicks, csv_clicks, xlsx_clicks, confirm_clicks, cancel_clicks, is_open, current_format):
        """Toggle the export modal and pre-select format based on button clicked."""
        if not ctx.triggered:
            return is_open, current_format

        trigger_id = ctx.triggered_id

        if trigger_id == "export-all-txt":
            return True, "txt"
        elif trigger_id == "export-all-csv":
            return True, "csv"
        elif trigger_id == "export-all-xlsx":
            return True, "xlsx"
        elif trigger_id in ["confirm-export", "cancel-export"]:
            return False, current_format

        return is_open, current_format

    @app.callback(
        Output("download-organism-data", "data"),
        Input("confirm-export", "n_clicks"),
        [
            State("export-format-select", "value"),
            State("export-filename", "value"),
            State("detailed-organism-table", "rowData"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def export_organism_data(n_clicks, export_format, filename, table_data, config):
        """Export organism data to file."""
        if not n_clicks or not table_data:
            return no_update

        try:
            # Default filename
            if not filename:
                filename = "organism_results"

            df = pd.DataFrame(table_data)

            if export_format == "csv":
                return {
                    "content": df.to_csv(index=False),
                    "filename": f"{filename}.csv",
                    "type": "text/csv"
                }
            elif export_format == "xlsx":
                # For Excel, try to use openpyxl, fall back to CSV if not available
                try:
                    import io
                    import openpyxl  # Check if available
                    buffer = io.BytesIO()
                    df.to_excel(buffer, index=False, engine='openpyxl')
                    buffer.seek(0)
                    import base64
                    return {
                        "content": base64.b64encode(buffer.getvalue()).decode(),
                        "filename": f"{filename}.xlsx",
                        "base64": True
                    }
                except ImportError:
                    logging.warning("openpyxl not installed, falling back to CSV export")
                    # Fall back to CSV
                    return {
                        "content": df.to_csv(index=False),
                        "filename": f"{filename}.csv",
                        "type": "text/csv"
                    }
            elif export_format == "txt":
                # Generate a formatted text report
                from datetime import datetime

                report_lines = [
                    "=" * 60,
                    "           ORGANISM ANALYSIS REPORT",
                    "=" * 60,
                    "",
                    f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"  Total Organisms: {len(df)}",
                    f"  Total DNA Sequences: {df['reads'].sum():,}",
                    "",
                    "-" * 60,
                    "  TOP ORGANISMS BY ABUNDANCE",
                    "-" * 60,
                    "",
                ]

                # Table header
                report_lines.append(f"  {'Rank':<6} {'Organism Name':<35} {'Reads':>10} {'%':>8}")
                report_lines.append("  " + "-" * 56)

                # Vectorized report line building
                rank_map = {'S': 'Sp.', 'G': 'Gen.', 'F': 'Fam.', 'O': 'Ord.', 'C': 'Cls.', 'P': 'Phy.', 'D': 'Dom.'}
                ranks = df['rank'].map(lambda r: rank_map.get(r, r)).tolist()
                names = df['name'].apply(lambda n: n[:33] + '..' if len(n) > 35 else n).tolist()
                reads_vals = df['reads'].tolist()
                abundances = df['abundance'].tolist()

                for rank_display, name, reads_val, abundance in zip(ranks, names, reads_vals, abundances):
                    report_lines.append(
                        f"  {rank_display:<6} {name:<35} {reads_val:>10,} {abundance:>7.1f}%"
                    )

                report_lines.extend([
                    "",
                    "-" * 60,
                    "",
                    "  NOTES:",
                    "  - Sp. = Species, Gen. = Genus, Fam. = Family",
                    "  - Reads = Number of DNA sequences classified",
                    "  - % = Percentage of total classified sequences",
                    "",
                    "=" * 60,
                    "                    END OF REPORT",
                    "=" * 60,
                ])

                report_content = "\n".join(report_lines)

                return {
                    "content": report_content,
                    "filename": f"{filename}_report.txt",
                    "type": "text/plain"
                }
            else:
                # Fallback to CSV
                return {
                    "content": df.to_csv(index=False),
                    "filename": f"{filename}.csv",
                    "type": "text/csv"
                }

        except Exception as e:
            logging.error(f"Error exporting data: {e}")
            import traceback
            traceback.print_exc()
            # Return error message as downloadable file
            return {
                "content": f"Export failed: {str(e)}",
                "filename": "export_error.txt",
                "type": "text/plain"
            }

    # Toggle watch button on organism cards - connects to WatchlistManager
    @app.callback(
        Output("main-watchlist-store", "data", allow_duplicate=True),
        Input({"type": "toggle-watch", "taxid": dash.ALL}, "n_clicks"),
        [
            State({"type": "toggle-watch", "taxid": dash.ALL}, "id"),
            State("main-watchlist-store", "data"),
            State("app-config", "data"),
            State("selected-sample", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_watch_species(n_clicks_list, button_ids, watchlist, config, selected_sample):
        """Toggle a species in/out of the watchlist using WatchlistManager."""
        if not any(n_clicks_list) or not ctx.triggered:
            return no_update

        # Get the triggered button's taxid
        triggered_id = ctx.triggered_id
        if not isinstance(triggered_id, dict):
            return no_update

        taxid = triggered_id.get("taxid")
        if taxid is None:
            return no_update

        # Get WatchlistManager and ensure it's loaded
        manager = get_watchlist_manager()
        if not manager._loaded and config:
            manager.load_config(config)

        # Check if species is already in WatchlistManager
        is_in_manager = taxid in manager._entries

        if is_in_manager:
            # Toggle the entry (disable if enabled, enable if disabled)
            entry = manager._entries[taxid]
            new_state = not entry.enabled
            manager.toggle_entry(taxid, new_state)
            logging.info(f"Toggled watchlist entry {entry.name} (taxid: {taxid}) to enabled={new_state}")
        else:
            # Add new custom entry to watchlist
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
            species_name = f"Species (taxid: {taxid})"  # Default name

            # Try to get name from Kraken data
            try:
                kraken_df = load_kraken_data(main_dir, selected_sample)
                if not kraken_df.empty:
                    match = kraken_df[kraken_df['taxid'] == taxid]
                    if not match.empty:
                        species_name = match.iloc[0]['name'].strip()
            except Exception as e:
                logging.warning(f"Could not load species name for taxid {taxid}: {e}")

            # Add as custom entry to WatchlistManager
            entry_data = {
                "name": species_name,
                "taxid": taxid,
                "threat_level": "moderate",  # Default for user-added species
                "alert_threshold": 10,
                "enabled": True,
            }
            manager.add_custom_entry(entry_data)
            logging.info(f"Added custom watchlist entry: {species_name} (taxid: {taxid})")

        # Return updated store data (for UI sync)
        # Convert active entries to store format
        updated_watchlist = []
        for entry in manager.get_active_entries().values():
            updated_watchlist.append({
                "name": entry.name,
                "taxid": entry.taxid,
                "enabled": entry.enabled,
            })

        return updated_watchlist

    # Toggle collapse for "Not Detected" watchlist section
    @app.callback(
        Output("not-detected-collapse", "is_open"),
        Input("not-detected-collapse-btn", "n_clicks"),
        State("not-detected-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_not_detected_collapse(n_clicks, is_open):
        """Toggle the Not Detected watchlist section collapse."""
        if n_clicks:
            return not is_open
        return is_open

    # Note: View toggle callback removed - charts moved to Taxonomy tab

    # Operator guide modal callback
    @app.callback(
        Output("operator-guide-modal", "is_open"),
        [
            Input("view-operator-guide", "n_clicks"),
            Input("close-operator-guide", "n_clicks"),
        ],
        State("operator-guide-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_operator_guide_modal(view_clicks, close_clicks, is_open):
        """Toggle the operator guide modal."""
        from dash import ctx
        if ctx.triggered_id == "view-operator-guide":
            return True
        elif ctx.triggered_id == "close-operator-guide":
            return False
        return is_open

    # =========================================================================
    # On-Demand BLAST Validation Callbacks
    # =========================================================================

    @app.callback(
        [
            Output("on-demand-validation-results", "data"),
            Output("notification-trigger", "data", allow_duplicate=True),
        ],
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
        State("on-demand-validation-results", "data"),
        prevent_initial_call=True,
    )
    def reload_on_demand_results(n_intervals, config, existing_results):
        """Load existing on-demand validation results from disk on initial page load.

        On a per-file failure (malformed JSON, file-system error) we
        skip the file but record its name and surface a single warning
        toast naming the offending files. Without the toast a
        partially-corrupt on_demand_validation directory looked exactly
        like a clean empty one (audit followup F1).
        """
        if existing_results:
            raise PreventUpdate

        results_dir = config.get("main_dir", "") if config else ""
        if not results_dir:
            raise PreventUpdate

        od_dir = os.path.join(results_dir, "on_demand_validation")
        if not os.path.isdir(od_dir):
            raise PreventUpdate

        results = {}
        skipped_files: list[str] = []
        for f in os.listdir(od_dir):
            if f.endswith("_validation.json"):
                try:
                    with open(os.path.join(od_dir, f)) as fh:
                        data = json.load(fh)
                    taxid = str(data.get("taxid", ""))
                    if taxid:
                        results[taxid] = data
                except Exception:
                    logging.warning(
                        f"reload_on_demand_results: skipped malformed file {f}",
                        exc_info=True,
                    )
                    skipped_files.append(f)
                    continue

        if skipped_files:
            sample = ", ".join(skipped_files[:5])
            extra = (
                f" (and {len(skipped_files) - 5} more)"
                if len(skipped_files) > 5
                else ""
            )
            notification = {
                "title": "Some on-demand results were skipped",
                "message": (
                    f"{len(skipped_files)} validation result file(s) in "
                    f"{od_dir} could not be parsed: {sample}{extra}. "
                    "Check the terminal log for details."
                ),
                "color": "warning",
            }
        else:
            notification = no_update

        if results:
            return results, notification
        # No new results to deliver, but still surface the warning if
        # any files were skipped this tick.
        return no_update, notification

    @app.callback(
        [
            Output("on-demand-validation-modal", "is_open"),
            Output("on-demand-validation-target", "data"),
            Output("validation-target-info", "children"),
            Output("validation-progress-bar", "value"),
            Output("validation-status-text", "children"),
            Output("validation-progress-log", "children"),
            Output("validation-results-section", "children"),
            Output("validation-results-section", "style"),
            Output("start-on-demand-validation", "style"),
            Output("cancel-on-demand-validation", "style"),
            Output("close-on-demand-validation", "style"),
        ],
        [
            Input({"type": "on-demand-validate", "taxid": dash.ALL, "name": dash.ALL}, "n_clicks"),
            Input("cancel-on-demand-validation", "n_clicks"),
            Input("close-on-demand-validation", "n_clicks"),
        ],
        [
            State("on-demand-validation-modal", "is_open"),
            State("selected-sample", "data"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_validation_modal(validate_clicks, cancel_clicks, close_clicks, is_open, selected_sample, config):
        """Open the on-demand validation modal when Validate button is clicked."""
        if not ctx.triggered:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

        trigger_id = ctx.triggered_id

        # Handle close/cancel
        if trigger_id in ["cancel-on-demand-validation", "close-on-demand-validation"]:
            return (
                False, None,
                dbc.Alert("Select an organism to validate", color="info"),
                0, "Ready to start validation", [],
                [], {"display": "none"},
                {"display": "inline-block"}, {"display": "inline-block"}, {"display": "none"}
            )

        # Handle validate button click
        if isinstance(trigger_id, dict) and trigger_id.get("type") == "on-demand-validate":
            # Guard against false triggers: when new organism cards are created,
            # Dash pattern-matching callbacks can fire with n_clicks=0 or None.
            # Only open the modal if a button was actually clicked.
            if validate_clicks and any(c and c > 0 for c in validate_clicks):
                pass  # Proceed with modal opening
            else:
                return (no_update,) * 11

            taxid = trigger_id.get("taxid")
            name = trigger_id.get("name", f"Taxid {taxid}")

            if not taxid:
                return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

            # Get read count for this organism
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
            read_count = 0
            try:
                kraken_df = load_kraken_data(main_dir, selected_sample)
                if not kraken_df.empty:
                    match = kraken_df[kraken_df['taxid'] == taxid]
                    if not match.empty:
                        read_count = int(match.iloc[0]['reads'])
                        name = match.iloc[0]['name'].strip()
            except Exception as e:
                logging.warning(f"Could not load read count for taxid {taxid}: {e}")

            # Create target info display
            target_info = dbc.Card([
                dbc.CardBody([
                    html.H5(name, className="mb-2"),
                    html.Div([
                        dbc.Badge(f"Taxid: {taxid}", color="secondary", className="me-2"),
                        dbc.Badge(f"{read_count:,} reads", color="primary", className="me-2"),
                        dbc.Badge(f"Sample: {selected_sample or 'All'}", color="info")
                    ])
                ])
            ], className="mb-3")

            return (
                True,
                {"taxid": taxid, "name": name, "sample": selected_sample, "read_count": read_count},
                target_info,
                0, "Ready to start validation. Click 'Start Validation' to begin.", [],
                [], {"display": "none"},
                {"display": "inline-block"}, {"display": "inline-block"}, {"display": "none"}
            )

        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

    @app.callback(
        [
            Output("validation-progress-bar", "value", allow_duplicate=True),
            Output("validation-status-text", "children", allow_duplicate=True),
            Output("validation-progress-log", "children", allow_duplicate=True),
            Output("validation-results-section", "children", allow_duplicate=True),
            Output("validation-results-section", "style", allow_duplicate=True),
            Output("start-on-demand-validation", "style", allow_duplicate=True),
            Output("cancel-on-demand-validation", "style", allow_duplicate=True),
            Output("close-on-demand-validation", "style", allow_duplicate=True),
            Output("on-demand-validation-results", "data", allow_duplicate=True),
        ],
        Input("start-on-demand-validation", "n_clicks"),
        [
            State("on-demand-validation-target", "data"),
            State("app-config", "data"),
            State("on-demand-validation-results", "data"),
            State("on-demand-method-select", "value"),
        ],
        prevent_initial_call=True,
    )
    def run_on_demand_validation(n_clicks, target, config, existing_results, validation_method):
        """Run on-demand BLAST validation for the selected organism."""
        if not n_clicks or not target:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

        taxid = target.get("taxid")
        name = target.get("name")
        sample = target.get("sample")

        if not taxid:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

        log_entries = []

        def add_log(message: str, level: str = "info"):
            timestamp = datetime.now().strftime("%H:%M:%S")
            color_class = {
                "info": "text-info",
                "success": "text-success",
                "warning": "text-warning",
                "error": "text-danger"
            }.get(level, "text-muted")
            log_entries.append(html.Div([
                html.Span(f"[{timestamp}] ", className="text-muted"),
                html.Span(message, className=color_class)
            ]))
            return log_entries[-20:]  # Keep last 20 entries

        try:
            # Get config paths
            main_dir = config.get("results_output_directory", "") or config.get("main_dir", "") if config else ""
            input_dir = config.get("nanopore_output_directory", "") if config else ""

            if not main_dir:
                add_log("Error: Results directory not configured", "error")
                return (
                    0, "Validation failed - no results directory",
                    log_entries, [], {"display": "none"},
                    {"display": "inline-block"}, {"display": "inline-block"}, {"display": "none"},
                    existing_results or {}
                )

            # Check that Kraken2 per-read output files exist before attempting validation
            kraken2_dir = os.path.join(main_dir, "kraken2")
            has_output_files = False
            if os.path.isdir(kraken2_dir):
                for f in os.listdir(kraken2_dir):
                    if ".output" in f or f.endswith(".kraken2"):
                        has_output_files = True
                        break

            if not has_output_files:
                add_log("Kraken2 per-read output files not found", "error")
                return (
                    0,
                    "Kraken2 per-read output files not found. Enable 'Save read assignments' in the configuration and re-run the pipeline.",
                    log_entries, [], {"display": "none"},
                    {"display": "inline-block"}, {"display": "inline-block"}, {"display": "none"},
                    existing_results or {}
                )

            add_log(f"Starting validation for {name} (taxid: {taxid})", "info")

            # Import the validator
            from nanometa_live.core.workflow.on_demand_validator import OnDemandValidator

            # Create validator instance
            validator = OnDemandValidator(
                results_dir=main_dir,
                input_dir=input_dir if input_dir else None
            )

            add_log("Checking reference genome...", "info")

            # Run validation (synchronous for now - could be made async with background callback)
            # Note: For production, this should use Dash background callbacks
            method = validation_method if validation_method in ("blast", "minimap2", "both") else "blast"
            # Passing ``config`` routes through the nanometanf
            # validation_only entry point (with -resume) when a
            # pipeline_source is configured. The legacy subprocess
            # path is now a fallback for the no-Nextflow case.
            result = validator.validate_organism(
                taxid=taxid,
                name=name,
                sample=sample or "all",
                method=method,
                config=config,
            )

            if result.success:
                add_log(f"Validation complete: {result.validated_reads}/{result.extracted_reads} reads validated", "success")

                # Create results display
                results_display = dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-check-circle-fill text-success me-2"),
                        html.Strong("Validation Results")
                    ]),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.H4(f"{result.validation_rate:.1f}%", className="text-success mb-0"),
                                html.Small("Validation Rate", className="text-muted")
                            ], className="text-center"),
                            dbc.Col([
                                html.H4(f"{result.validated_reads:,}", className="text-primary mb-0"),
                                html.Small("Validated Reads", className="text-muted")
                            ], className="text-center"),
                            dbc.Col([
                                html.H4(f"{result.avg_identity:.1f}%", className="text-info mb-0"),
                                html.Small("Avg Identity", className="text-muted")
                            ], className="text-center"),
                        ], className="mb-3"),
                        html.Div([
                            dbc.Badge(
                                "BLAST Verified" if result.validation_rate >= 80 else
                                "Partial Match" if result.validation_rate >= 50 else "Low Match",
                                color="success" if result.validation_rate >= 80 else
                                      "warning" if result.validation_rate >= 50 else "danger",
                                className="me-2"
                            ),
                            html.Small(
                                f"{result.extracted_reads:,} reads extracted from {result.total_classified_reads:,} classified",
                                className="text-muted"
                            )
                        ])
                    ])
                ])

                # Update stored results
                updated_results = existing_results or {}
                updated_results[str(taxid)] = {
                    "taxid": taxid,
                    "name": name,
                    "validation_rate": result.validation_rate,
                    "validated_reads": result.validated_reads,
                    "extracted_reads": result.extracted_reads,
                    "avg_identity": result.avg_identity,
                    "success": True
                }

                return (
                    100, "Validation complete!",
                    log_entries, results_display, {"display": "block"},
                    {"display": "none"}, {"display": "none"}, {"display": "inline-block"},
                    updated_results
                )
            else:
                add_log(f"Validation failed: {result.error_message}", "error")
                return (
                    0, f"Validation failed: {result.error_message}",
                    log_entries, [], {"display": "none"},
                    {"display": "inline-block"}, {"display": "inline-block"}, {"display": "none"},
                    existing_results or {}
                )

        except ImportError as e:
            add_log(f"Import error: {e}", "error")
            return (
                0, "Validation module not available",
                log_entries, [], {"display": "none"},
                {"display": "inline-block"}, {"display": "inline-block"}, {"display": "none"},
                existing_results or {}
            )
        except Exception as e:
            logging.error(f"On-demand validation error: {e}")
            import traceback
            traceback.print_exc()
            add_log(f"Error: {str(e)}", "error")
            return (
                0, f"Error: {str(e)}",
                log_entries, [], {"display": "none"},
                {"display": "inline-block"}, {"display": "inline-block"}, {"display": "none"},
                existing_results or {}
            )
