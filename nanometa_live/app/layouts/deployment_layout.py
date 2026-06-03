"""
Deployment tab layout.

An independent tool for moving or cloning a prepared system between computers
(e.g. to a field machine with no internet access) -- NOT a step in the
Configure -> Prepare -> Analyse chain, so it intentionally shows no workflow
stepper. Provides the deploy wizard plus bundle export/import via BundleManager.
The content is surfaced directly (not collapsed) since it owns a whole tab.

Composes section builders from preparation_layout.py; component IDs and callback
wiring are unchanged.
"""

from dash import html
import dash_bootstrap_components as dbc

from nanometa_live.app.layouts.preparation_layout import (
    build_wizard_stores,
    build_offline_deployment_content,
)


def create_deployment_layout() -> html.Div:
    """Assemble the Deployment tab (offline wizard + bundle export/import)."""
    return html.Div([
        *build_wizard_stores(),

        dbc.Container([
            html.Div([
                html.I(className="bi bi-rocket-takeoff me-2",
                       style={"fontSize": "1.3rem"}),
                html.H4("Deployment", className="mb-0 d-inline"),
            ], className="d-flex align-items-center mb-1"),
            html.P(
                "Move or clone a prepared system to another computer -- for "
                "example a field machine with no internet access. Independent of "
                "the Configure -> Prepare -> Analyse chain: export a portable "
                "bundle here, then import it on the target machine. Use the "
                "wizard to step through each stage, or the Export / Import "
                "controls if you already have a prepared bundle.",
                className="text-muted mb-3 small",
            ),
            build_offline_deployment_content(),
        ], fluid=True, className="p-3"),
    ], id="deployment-tab-content", className="p-4")
