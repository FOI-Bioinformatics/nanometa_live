"""
Merged "Watchlist & Preparation" tab layout.

Combines what used to be two separate setup tabs -- Watchlist (pick the
organisms to watch for) and Preparation (download their genomes, build search
indexes, generate mappings, run the readiness checklist) -- into a single
top-to-bottom flow so the operator no longer bounces between them. The offline
bundle tooling moved out to its own Deployment tab.

This module only *composes* existing section builders; the component IDs and
callback wiring are unchanged (see watchlist_layout.py and preparation_layout.py
for the builders).
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

from nanometa_live.app.components.modern_components import WorkflowStepper, ActionRow
from nanometa_live.app.layouts.watchlist_layout import (
    _create_stats_bar,
    _create_quick_start_section,
    _create_pathogens_table_section,
    _create_collapsible_watchlist_files,
    _create_collapsible_add_species,
    _create_entry_edit_modal,
    _create_api_details_modal,
    _create_validation_progress_modal,
)
from nanometa_live.app.layouts.preparation_layout import (
    build_genome_import_store,
    build_readiness_checklist_card,
    build_run_preparation_card,
    build_advanced_stages_accordion,
    build_prep_modals,
)


def _watchlist_block():
    """Organism-selection section (stats, presets, table, files, add-custom)."""
    return [
        _create_stats_bar(),
        html.Div([
            html.P([
                html.I(className="bi bi-lightbulb me-2 text-info"),
                "Choose which organisms to watch for. Select a pre-built list below, "
                "or add individual species. Enabled organisms will trigger alerts "
                "when detected during analysis.",
            ], className="text-muted small mb-1"),
        ], className="mb-2"),
        _create_quick_start_section(),
        _create_pathogens_table_section(),
        _create_collapsible_watchlist_files(),
        _create_collapsible_add_species(),
    ]


def _preparation_block():
    """Readiness + one-shot preparation + advanced individual stages."""
    return [
        html.Hr(className="my-4"),
        html.Div([
            html.I(className="bi bi-box-seam me-2", style={"fontSize": "1.3rem"}),
            html.H4("Prepare for Analysis", className="mb-0 d-inline"),
        ], className="d-flex align-items-center mb-1"),
        html.P(
            "Verify everything is ready, then run preparation: it checks the "
            "database, generates organism mappings, downloads reference genomes, "
            "and builds search indexes for the organisms selected above.",
            className="text-muted mb-3 small",
        ),
        build_readiness_checklist_card(),
        build_run_preparation_card(),
        build_advanced_stages_accordion(),
    ]


def _bottom_ctas():
    """Bottom action row: Start Analysis is the chain's next step (sole primary).

    Deployment is independent of the Configure -> Prepare -> Analyse chain, so it
    is a quiet link here rather than a peer next-step button.
    """
    return html.Div([
        html.Hr(className="my-4"),
        ActionRow([
            dbc.Button(
                [html.I(className="bi bi-play-fill me-2"), "Start Analysis"],
                id="preparation-start-analysis-btn",
                color="primary",
                size="lg",
                n_clicks=0,
            ),
        ]),
        html.Div(
            dbc.Button(
                [
                    "Moving to another computer or cloning this setup? "
                    "Open Deployment ",
                    html.I(className="bi bi-arrow-right ms-1"),
                ],
                id="merged-next-deployment-btn",
                color="link",
                size="sm",
                className="text-muted p-0",
            ),
            className="d-flex justify-content-end mt-2",
        ),
    ], className="mt-3 mb-4")


def create_watchlist_preparation_layout() -> html.Div:
    """Assemble the merged Watchlist & Preparation tab."""
    return html.Div([
        WorkflowStepper(active_step=2),
        # Shared state stores (watchlist + the prep genome-import store). Keeping
        # watchlist-table-refresh here is what keeps watchlist-entries-snapshot
        # hydrated for the background prep/rescan workers.
        dcc.Store(id="watchlist-tab-state", data={}),
        dcc.Store(id="watchlist-table-refresh", data=0),
        dcc.Store(id="api-lookup-result", data=None),
        build_genome_import_store(),

        dbc.Container(
            _watchlist_block() + _preparation_block(),
            fluid=True,
            className="p-3",
        ),

        # Modals (watchlist + preparation)
        _create_entry_edit_modal(),
        _create_api_details_modal(),
        _create_validation_progress_modal(),
        *build_prep_modals(),

        _bottom_ctas(),
    ], id="watchlist-preparation-tab-content", className="p-4")
