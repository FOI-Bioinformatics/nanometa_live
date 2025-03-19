"""
Main Dash application module for Nanometa Live.

This module initializes the Dash application and sets up the core layout and callbacks.
"""

import os
import logging
import importlib.resources as pkg_resources
from typing import Dict, Any

import dash
from dash import Dash, html, dcc
import dash_bootstrap_components as dbc

from nanometa_live import __version__
from nanometa_live.app.layouts.main_layout import create_main_layout
from nanometa_live.app.layouts.qc_layout import create_qc_layout
from nanometa_live.app.layouts.sankey_layout import create_sankey_layout
from nanometa_live.app.layouts.sunburst_layout import create_sunburst_layout
from nanometa_live.app.layouts.config_layout import create_config_layout
from nanometa_live.app.components.header import create_header
from nanometa_live.core.workflow.backend_manager import BackendManager


def create_app(config: Dict[str, Any], data_dir: str, backend_manager: BackendManager) -> Dash:
    """
    Create and configure the Dash application.

    Args:
        config: Application configuration
        data_dir: Directory for application data
        backend_manager: Backend manager instance

    Returns:
        Configured Dash application
    """
    # Ensure assets directory exists
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # Create default CSS file if it doesn't exist
    css_file = os.path.join(assets_dir, "styles.css")
    if not os.path.exists(css_file):
        with open(css_file, 'w') as f:
            f.write("""
/* Default Nanometa Live styles */
.header {
    background-color: #f8f9fa;
    padding: 1rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.footer {
    background-color: #f8f9fa;
    padding: 1rem;
    text-align: center;
    margin-top: 2rem;
    border-top: 1px solid #dee2e6;
}

.footer-content {
    color: #6c757d;
}

/* Fix for bootstrap 5 classes */
.ms-2 {
    margin-left: 0.5rem;
}

.me-2 {
    margin-right: 0.5rem;
}

.float-end {
    float: right;
}
""")

    # Create default logo file if it doesn't exist
    logo_file = os.path.join(assets_dir, "logo.png")
    if not os.path.exists(logo_file):
        # Try to copy from package resources if available
        try:
            from importlib.resources import files
            logo_data = files('nanometa_live').joinpath('app/assets/logo.png').read_bytes()
            with open(logo_file, 'wb') as f:
                f.write(logo_data)
        except (ImportError, FileNotFoundError):
            # Create a simple placeholder logo
            import base64
            # 1x1 transparent pixel
            empty_pixel = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
            with open(logo_file, 'wb') as f:
                f.write(base64.b64decode(empty_pixel))

    # Initialize the Dash app
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        suppress_callback_exceptions=True,
        assets_folder=assets_dir,
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"}
        ]
    )

    # Create app layout with tabs
    app.layout = html.Div([
        # Store components for app state
        dcc.Store(id='app-config', data=config),
        dcc.Store(id='backend-status', data={"running": False}),
        dcc.Store(id='app-data-dir', data=data_dir),

        # Interval for updating data
        dcc.Interval(
            id='update-interval',
            interval=config.get('update_interval_seconds', 30) * 1000,  # in milliseconds
            n_intervals=0,
            disabled=False
        ),

        # Header with title, controls, and status
        create_header(config.get('analysis_name', 'Nanometa Live Analysis')),

        # Main tabs container
        dbc.Tabs([
            dbc.Tab(
                label="Configuration",
                tab_id="config-tab",
                children=create_config_layout()
            ),
            dbc.Tab(
                label="Main Results",
                tab_id="main-tab",
                children=create_main_layout()
            ),
            dbc.Tab(
                label="QC",
                tab_id="qc-tab",
                children=create_qc_layout()
            ),
            dbc.Tab(
                label="Sankey Plot",
                tab_id="sankey-tab",
                children=create_sankey_layout()
            ),
            dbc.Tab(
                label="Sunburst Chart",
                tab_id="sunburst-tab",
                children=create_sunburst_layout()
            )
        ], id="tabs", active_tab="config-tab"),
        # Data preparation modal
        dbc.Modal([
            dbc.ModalHeader([
                html.H4("Data Preparation", className="mb-0"),
                html.Span(id="prepare-step-indicator", className="text-muted ms-3")
            ], className="d-flex align-items-center"),
            dbc.ModalBody([
                # Step progress
                html.Div([
                    html.H5(id="prepare-current-step", children="Initializing..."),
                    html.Div(id="prepare-step-details", className="text-muted mb-2"),
                    dbc.Progress(id="prepare-step-progress", value=0, className="mb-1", striped=True, animated=True),
                ], className="mb-3"),

                # Overall progress
                html.Div([
                    html.H5("Overall Progress"),
                    dbc.Progress(id="prepare-overall-progress", value=0, className="mb-1", striped=True, animated=True),
                    html.Div(id="prepare-status", className="mt-2")
                ]),

                # Error message area
                html.Div(id="prepare-error-container", className="mt-3")
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="cancel-prepare-button", color="secondary", className="me-2"),
                dbc.Button("Close", id="close-prepare-modal", disabled=True)
            ])
        ], id="prepare-data-modal", is_open=False, backdrop="static", centered=True, size="lg"),

        # Footer
        html.Footer(
            html.Div([
                html.Span(f"Nanometa Live v{__version__}"),
                html.Span(" | "),
                html.A("Documentation", href="https://github.com/FOI-Bioinformatics/nanometa_live", target="_blank"),
                html.Span(" | "),
                html.A("Report Issue", href="https://github.com/FOI-Bioinformatics/nanometa_live/issues", target="_blank")
            ], className="footer-content"),
            className="footer"
        )
    ])

    # Register all callbacks
    register_callbacks(app, backend_manager)

    return app


def register_callbacks(app: Dash, backend_manager: BackendManager):
    """
    Register all callbacks for the application.

    Args:
        app: Dash application
        backend_manager: Backend manager instance
    """
    # Import callbacks here to avoid circular imports
    from nanometa_live.app.tabs.config_tab import register_config_callbacks
    from nanometa_live.app.tabs.main_tab import register_main_callbacks
    from nanometa_live.app.tabs.qc_tab import register_qc_callbacks
    from nanometa_live.app.tabs.sankey_tab import register_sankey_callbacks
    from nanometa_live.app.tabs.sunburst_tab import register_sunburst_callbacks
    from nanometa_live.app.callbacks import register_core_callbacks

    # Register callbacks for each tab
    register_core_callbacks(app, backend_manager)
    register_config_callbacks(app, backend_manager)
    register_main_callbacks(app)
    register_qc_callbacks(app)
    register_sankey_callbacks(app)
    register_sunburst_callbacks(app)