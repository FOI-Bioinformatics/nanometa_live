"""
Main Dash application module for Nanometa Live.

This module initializes the Dash application and sets up the core layout and callbacks.
"""

import os
import logging
from typing import Dict, Any

import yaml
import dash
from dash import Dash, html, dcc, Input, Output, State, ClientsideFunction, DiskcacheManager
import dash_bootstrap_components as dbc
import diskcache
import multiprocess

# Use 'spawn' instead of 'fork' to avoid BrokenPipeError on macOS/Python 3.13
# when DiskcacheManager forks a process with a closed stderr pipe.
multiprocess.set_start_method("spawn", force=True)

# Initialize cache for background callbacks (enables async progress reporting)
_cache_dir = os.path.join(os.path.expanduser("~"), ".nanometa", "cache")
os.makedirs(_cache_dir, exist_ok=True)
_cache = diskcache.Cache(_cache_dir)
background_callback_manager = DiskcacheManager(_cache)

from nanometa_live import __version__
from nanometa_live.app.layouts.main_layout import create_main_layout
from nanometa_live.app.layouts.qc_layout import create_qc_layout
from nanometa_live.app.layouts.classification_layout import create_classification_layout
from nanometa_live.app.layouts.config_layout import create_config_layout
from nanometa_live.app.layouts.dashboard_layout import create_dashboard_layout
from nanometa_live.app.layouts.watchlist_layout import create_watchlist_layout
from nanometa_live.app.layouts.validation_layout import create_validation_layout
from nanometa_live.app.layouts.preparation_layout import create_preparation_layout
from nanometa_live.app.components.header import create_header
from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.config.config_loader import ConfigLoader


def _tab_label(icon_class: str, text: str):
    """Create a tab label string. Icons are not supported by dbc.Tab label prop in dbc 2.0.4."""
    return text


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
    # Load kraken databases directly
    try:
        kraken_db_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kraken2_databases.yaml")
        with open(kraken_db_file, 'r') as f:
            kraken_databases = yaml.safe_load(f).get("kraken2_databases", {})
    except Exception as e:
        logging.error(f"Error loading Kraken databases: {e}")
        kraken_databases = {}

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

    # Determine if running in debug mode (show errors during development)
    debug_mode = os.environ.get('DASH_DEBUG', '').lower() in ('1', 'true', 'yes')

    # Initialize the Dash app with background callback support
    # Note: suppress_callback_exceptions=True is always enabled because:
    # 1. Dynamic layouts may reference components that don't exist yet
    # 2. Browser cache can reference removed components causing false errors
    # 3. Collapsible sections create/destroy components dynamically
    app = Dash(
        __name__,
        external_stylesheets=[
            dbc.themes.BOOTSTRAP,
            dbc.icons.BOOTSTRAP,  # Bootstrap Icons for bi-* classes
        ],
        suppress_callback_exceptions=True,  # Always suppress - dynamic layouts + cache issues
        assets_folder=assets_dir,
        background_callback_manager=background_callback_manager,  # Enable async progress
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"},
            {"http-equiv": "Cache-Control", "content": "no-cache, no-store, must-revalidate"},
            {"http-equiv": "Pragma", "content": "no-cache"},
            {"http-equiv": "Expires", "content": "0"}
        ]
    )

    # Create app layout with tabs
    app.layout = html.Div([
        # Accessibility: Skip to main content link
        html.A(
            "Skip to main content",
            href="#main-content",
            className="skip-to-main"
        ),

        # Store components for app state
        dcc.Store(id='app-config', data=config),
        dcc.Store(id='backend-status', data={"running": False}),
        dcc.Store(id='app-data-dir', data=data_dir),
        dcc.Store(id='kraken-databases', data=kraken_databases),

        # Configuration state tracking stores
        dcc.Store(id='config-source', data={
            "type": "file",  # "file", "default", or "unsaved"
            "path": None,    # File path if loaded from file
            "name": "Default Configuration"  # Display name
        }),
        dcc.Store(id='saved-config-snapshot', data=config),  # Snapshot of last saved state
        dcc.Store(id='config-modified', data=False),  # True if current config differs from saved

        # Sample management stores (for multi-sample/barcode support)
        dcc.Store(id='selected-sample', data='All Samples'),
        dcc.Store(id='available-samples', data=['All Samples']),
        dcc.Store(id='sample-file-mapping', data={}),
        dcc.Store(id='notification-trigger', data={}),
        dcc.Store(id='last-update-time', data=None),
        dcc.Store(id='toast-message', data=None),
        dcc.Store(id='theme-preference', data='auto'),  # auto, light, dark
        dcc.Store(id='previous-running-state', data=False),  # For detecting analysis completion

        # Shared stores for cross-tab communication (Watchlist <-> Preparation)
        dcc.Store(id='taxmap-collection', data=None),
        dcc.Store(id='taxmap-database-info', data=None),
        dcc.Store(id='taxmap-rescan-complete', data=None),
        dcc.Download(id='taxmap-export-download'),
        dcc.Store(id='genome-status-data', data={}),
        dcc.Store(id='genome-download-complete', data=None),
        dcc.Store(id='blast-build-complete', data=None),

        # Interval for updating data
        dcc.Interval(
            id='update-interval',
            interval=config.get('update_interval_seconds', 30) * 1000,  # in milliseconds
            n_intervals=0,
            disabled=False
        ),

        # Fast interval for countdown timer (1 second ticks)
        dcc.Interval(
            id='countdown-tick',
            interval=1000,  # 1 second
            n_intervals=0,
            disabled=False
        ),

        # Header with title, controls, and status
        create_header(config.get('analysis_name', 'Nanometa Live Analysis')),

        # Sample selector bar with live indicator
        html.Div([
            dbc.Container([
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.I(className="bi bi-collection me-2",
                                   style={"fontSize": "18px", "color": "#007bff"}),
                            html.Label(
                                "Sample:",
                                className="fw-semibold me-2 mb-0",
                                htmlFor="sample-selector",
                                style={"whiteSpace": "nowrap"}
                            ),
                            dcc.Dropdown(
                                id='sample-selector',
                                options=[{'label': 'All Samples (Aggregated)', 'value': 'All Samples'}],
                                value='All Samples',
                                clearable=False,
                                style={"minWidth": "250px", "maxWidth": "400px"},
                                placeholder="Select sample or barcode...",
                                persistence=False,
                                persistence_type='session'
                            ),
                        ], className="d-flex align-items-center")
                    ], md=6),

                    dbc.Col([
                        # Live data indicator with theme toggle
                        html.Div([
                            # Stale data warning (hidden by default)
                            html.Div(
                                id="stale-data-warning",
                                children=[
                                    html.I(className="bi bi-exclamation-triangle me-1"),
                                    html.Span("Data may be stale", className="small")
                                ],
                                className="stale-data-warning me-3",
                                style={"display": "none"}
                            ),
                            # Live indicator
                            html.Span(id="live-indicator-dot", className="live-indicator-dot offline", **{"aria-hidden": "true"}),
                            html.Span(id="live-indicator-text", children="Idle", className="fw-medium"),
                            html.Span(" | ", className="text-muted mx-2"),
                            html.I(className="bi bi-clock-history me-1"),
                            html.Span(id="last-update-display", children="--", className="text-muted small"),
                            # Theme toggle button
                            html.Button(
                                id="theme-toggle",
                                children=[html.I(id="theme-icon", className="bi bi-moon-stars")],
                                className="theme-toggle ms-3",
                                title="Toggle dark mode",
                                **{"aria-label": "Toggle dark mode"}
                            )
                        ], className="live-indicator d-flex align-items-center justify-content-end")
                    ], md=6, className="d-flex align-items-center justify-content-end")
                ])
            ], fluid=True)
        ], className="py-3 border-bottom bg-light"),

        # Main content area with accessibility landmark
        html.Main([
            # Main tabs container - Dashboard first for monitoring workflow
            dbc.Tabs([
                # Overview group
                dbc.Tab(
                    label=_tab_label("bi-grid", "Dashboard"),
                    tab_id="dashboard-tab",
                    children=create_dashboard_layout(),
                    tabClassName="fw-semibold tab-dashboard"
                ),
                # Analysis group
                dbc.Tab(
                    label=_tab_label("bi-bug", "Organisms"),
                    tab_id="main-tab",
                    children=create_main_layout(),
                    tabClassName="tab-organisms tab-group-start"
                ),
                dbc.Tab(
                    label=_tab_label("bi-clipboard-check", "Quality Control"),
                    tab_id="qc-tab",
                    children=create_qc_layout(),
                    tabClassName="tab-qc"
                ),
                dbc.Tab(
                    label=_tab_label("bi-diagram-3", "Taxonomy"),
                    tab_id="classification-tab",
                    children=create_classification_layout(),
                    tabClassName="tab-taxonomy"
                ),
                dbc.Tab(
                    label=_tab_label("bi-shield-check", "Validation"),
                    tab_id="validation-tab",
                    children=create_validation_layout(),
                    tabClassName="tab-validation"
                ),
                # Setup group (ordered by workflow: configure -> watchlist -> prepare)
                dbc.Tab(
                    label=_tab_label("bi-gear", "Configuration"),
                    tab_id="config-tab",
                    children=create_config_layout(),
                    tabClassName="tab-config tab-group-start"
                ),
                dbc.Tab(
                    label=_tab_label("bi-star", "Watchlist"),
                    tab_id="watchlist-tab",
                    children=create_watchlist_layout(),
                    tabClassName="tab-watchlist"
                ),
                dbc.Tab(
                    label=_tab_label("bi-box-seam", "Preparation"),
                    tab_id="preparation-tab",
                    children=create_preparation_layout(),
                    tabClassName="tab-preparation"
                )
            ], id="tabs", active_tab="dashboard-tab"),
        ], id="main-content", role="main"),

        # Toast notification container (for non-blocking feedback)
        html.Div(id="toast-container", className="toast-container"),
        # Data preparation modal
        dbc.Modal([
            dbc.ModalHeader([
                html.H4("Validation Setup", className="mb-0"),
                html.Span(id="prepare-step-indicator", className="text-muted ms-3")
            ], className="d-flex align-items-center"),
            dbc.ModalBody([
                # Step progress - Update this section
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
        ),

        # Welcome modal for first-time users
        dbc.Modal([
            dbc.ModalHeader(
                html.H4([html.I(className="bi bi-rocket-takeoff me-2"), "Welcome to Nanometa Live"], className="mb-0"),
                close_button=True
            ),
            dbc.ModalBody([
                html.P(
                    "Nanometa Live provides real-time visualization of Oxford Nanopore "
                    "sequencing analysis. Follow these steps to get started:",
                    className="mb-3"
                ),
                html.Div([
                    html.Div([
                        html.Div([
                            dbc.Badge("1", color="primary", className="me-2",
                                      style={"fontSize": "1rem", "borderRadius": "50%", "width": "28px", "height": "28px",
                                             "display": "inline-flex", "alignItems": "center", "justifyContent": "center"}),
                            html.Strong("Configure"),
                        ], className="d-flex align-items-center mb-1"),
                        html.P("Go to the Configuration tab and set your input directory and Kraken2 database.",
                               className="text-muted small ms-4 mb-3"),
                    ]),
                    html.Div([
                        html.Div([
                            dbc.Badge("2", color="primary", className="me-2",
                                      style={"fontSize": "1rem", "borderRadius": "50%", "width": "28px", "height": "28px",
                                             "display": "inline-flex", "alignItems": "center", "justifyContent": "center"}),
                            html.Strong("Set up Watchlist"),
                        ], className="d-flex align-items-center mb-1"),
                        html.P("Go to the Watchlist tab to select which organisms to monitor for alerts.",
                               className="text-muted small ms-4 mb-3"),
                    ]),
                    html.Div([
                        html.Div([
                            dbc.Badge("3", color="primary", className="me-2",
                                      style={"fontSize": "1rem", "borderRadius": "50%", "width": "28px", "height": "28px",
                                             "display": "inline-flex", "alignItems": "center", "justifyContent": "center"}),
                            html.Strong("Prepare Databases"),
                        ], className="d-flex align-items-center mb-1"),
                        html.P("Go to the Preparation tab to download reference genomes and build validation databases.",
                               className="text-muted small ms-4 mb-3"),
                    ]),
                    html.Div([
                        html.Div([
                            dbc.Badge("4", color="primary", className="me-2",
                                      style={"fontSize": "1rem", "borderRadius": "50%", "width": "28px", "height": "28px",
                                             "display": "inline-flex", "alignItems": "center", "justifyContent": "center"}),
                            html.Strong("Start Analysis"),
                        ], className="d-flex align-items-center mb-1"),
                        html.P("Click 'Start Analysis' in the header. The Dashboard and Organisms tabs update automatically as data becomes available.",
                               className="text-muted small ms-4 mb-0"),
                    ]),
                ]),
                dbc.Alert([
                    html.I(className="bi bi-lightbulb me-2"),
                    "If you already have results, use ",
                    html.Code("--main_dir /path/to/results"),
                    " to visualize existing data without running the pipeline.",
                ], color="info", className="mt-3 mb-0"),
            ]),
            dbc.ModalFooter(
                dbc.Button("Get Started", id="close-welcome-modal", color="primary")
            )
        ], id="welcome-modal", is_open=False, centered=True, size="lg"),
        dcc.Store(id="welcome-shown", storage_type="local", data=False),
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
    from nanometa_live.app.tabs.classification_tab import register_classification_callbacks
    from nanometa_live.app.tabs.dashboard_tab import register_dashboard_callbacks
    from nanometa_live.app.tabs.watchlist_tab import register_watchlist_callbacks
    from nanometa_live.app.tabs.validation_tab import register_validation_callbacks
    from nanometa_live.app.tabs.preparation_tab import register_preparation_callbacks
    from nanometa_live.app.callbacks import register_core_callbacks

    # Register callbacks for each tab
    register_core_callbacks(app, backend_manager)
    register_dashboard_callbacks(app)
    register_config_callbacks(app, backend_manager)
    register_main_callbacks(app)
    register_qc_callbacks(app)
    register_classification_callbacks(app)
    register_watchlist_callbacks(app)
    register_validation_callbacks(app)
    register_preparation_callbacks(app)

    # Clientside callback for countdown timer (smooth, no server round-trips)
    app.clientside_callback(
        """
        function(n_intervals, interval_ms, backend_status, last_data_update) {
            // Calculate time since last data update
            var interval_sec = interval_ms / 1000;
            var now = Date.now();

            // Check if backend is running
            var is_running = backend_status && backend_status.running;

            if (!is_running) {
                return "Paused";
            }

            // Calculate time remaining based on last update timestamp
            // Using a simple countdown from interval_sec
            var time_remaining = Math.ceil(interval_sec - ((now / 1000) % interval_sec));

            if (time_remaining <= 0 || time_remaining > interval_sec) {
                return "Updating...";
            }

            return "Next: " + time_remaining + "s";
        }
        """,
        Output("update-countdown", "children"),
        [
            Input("countdown-tick", "n_intervals"),
            Input("update-interval", "interval"),
            Input("backend-status", "data"),
            Input("last-update-time", "data")
        ]
    )