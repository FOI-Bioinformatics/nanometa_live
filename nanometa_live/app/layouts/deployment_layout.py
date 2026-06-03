"""
Deployment tab layout.

Offline field deployment, split out of the old Preparation tab into its own tab
because it is logically independent of the readiness/preparation flow (it only
uses BundleManager). Provides the deploy wizard plus bundle export/import. The
content is surfaced directly (not collapsed) since it now owns a whole tab.

Composes section builders from preparation_layout.py; component IDs and callback
wiring are unchanged.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

from nanometa_live.app.components.modern_components import WorkflowStepper
from nanometa_live.app.layouts.preparation_layout import (
    build_wizard_stores,
    build_offline_deployment_content,
)


def create_deployment_layout() -> html.Div:
    """Assemble the Deployment tab (offline wizard + bundle export/import)."""
    return html.Div([
        WorkflowStepper(active_step=3),
        *build_wizard_stores(),

        dbc.Container([
            html.Div([
                html.I(className="bi bi-rocket-takeoff me-2",
                       style={"fontSize": "1.3rem"}),
                html.H4("Offline Deployment", className="mb-0 d-inline"),
            ], className="d-flex align-items-center mb-1"),
            html.P(
                "Build a portable bundle for a field machine with no internet "
                "access. Use the wizard to step through each stage, or the "
                "Export / Import controls if you already have a prepared bundle. "
                "This step is optional -- skip it for online analysis.",
                className="text-muted mb-3 small",
            ),
            build_offline_deployment_content(),
        ], fluid=True, className="p-3"),
    ], id="deployment-tab-content", className="p-4")
