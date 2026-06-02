"""
Main Dash application module for Nanometa Live.

This module initializes the Dash application and sets up the core layout and callbacks.
"""

import os
import logging
from typing import Any, Dict, Optional

import yaml
import dash
from dash import Dash, html, dcc, Input, Output, State, ClientsideFunction, DiskcacheManager
from flask import request
import dash_bootstrap_components as dbc
import diskcache
import multiprocess

# Use 'spawn' instead of 'fork' to avoid BrokenPipeError on macOS/Python 3.13
# when DiskcacheManager forks a process with a closed stderr pipe.
multiprocess.set_start_method("spawn", force=True)

# Module-level placeholder; populated lazily by ``create_app`` once the
# operator's ``data_dir`` is known. Constructing the FanoutCache at
# import time would force the cache to live under ``~/.nanometa/cache``
# regardless of ``--data-dir``, which is the leak this refactor closes.
# See docs/audit-2026-04-28-throughput-gui.md for FanoutCache
# motivation: 8 shards so concurrent background callbacks do not
# serialize behind a single writer-mutex.
background_callback_manager: Optional[DiskcacheManager] = None
_cache: Optional[diskcache.FanoutCache] = None
_cache_dir_for_atexit: Optional[str] = None


def _per_run_cache_dir(base_cache_dir: str) -> str:
    """Return a per-process subdirectory under *base_cache_dir*.

    Each ``nanometa-live`` process owns ``cache/run-<pid>-<unix-ts>/``.
    Two concurrent instances on the same data_dir get isolated
    Diskcache trees; a restart of the same instance gets a fresh tree
    with no carry-over of stale callback results.
    """
    import time as _time
    return os.path.join(base_cache_dir, f"run-{os.getpid()}-{int(_time.time())}")


def _sweep_dead_run_caches(base_cache_dir: str) -> None:
    """Remove ``run-<pid>-*`` directories whose PID is no longer alive.

    Runs once per startup so ungraceful exits do not leave the cache
    tree bloating indefinitely. Only matches the exact ``run-<int>-<int>``
    pattern so unrelated operator content under ``cache/`` is left
    untouched -- this is intentionally conservative.
    """
    if not os.path.isdir(base_cache_dir):
        return
    import re as _re
    import shutil as _shutil
    pattern = _re.compile(r"^run-(\d+)-\d+$")
    for entry in os.listdir(base_cache_dir):
        match = pattern.match(entry)
        if not match:
            continue
        pid = int(match.group(1))
        if pid == os.getpid():
            continue
        # Probe whether the PID is alive. ``os.kill(pid, 0)`` raises
        # ProcessLookupError for dead PIDs, PermissionError for live
        # PIDs owned by another user (treat as alive -- do not delete).
        try:
            os.kill(pid, 0)
            continue  # PID is alive; leave its cache alone
        except ProcessLookupError:
            pass
        except (PermissionError, OSError):
            continue  # cannot probe -- be safe, leave alone
        target = os.path.join(base_cache_dir, entry)
        try:
            _shutil.rmtree(target)
            logging.debug("Removed stale background-cache dir %s", target)
        except OSError as exc:
            logging.debug("Could not remove stale cache dir %s: %s", target, exc)


def _ensure_background_callback_manager(base_cache_dir: str) -> DiskcacheManager:
    """Construct the Diskcache-backed background callback manager.

    The on-disk path is per-process (``run-<pid>-<ts>/``) so concurrent
    instances on the same ``data_dir`` do not see each other's callback
    results, and a restart starts with an empty cache. Stale ``run-*``
    directories from prior crashes are swept on first call.
    Idempotent for a given base directory.
    """
    global background_callback_manager, _cache, _cache_dir_for_atexit
    if (
        background_callback_manager is not None
        and _cache is not None
        and str(_cache.directory).startswith(base_cache_dir)
    ):
        return background_callback_manager
    os.makedirs(base_cache_dir, exist_ok=True)
    _sweep_dead_run_caches(base_cache_dir)
    run_dir = _per_run_cache_dir(base_cache_dir)
    os.makedirs(run_dir, exist_ok=True)
    _cache = diskcache.FanoutCache(run_dir, shards=8, timeout=1.0)
    background_callback_manager = DiskcacheManager(_cache, expire=3600)

    # Tear down the per-process cache on graceful exit so the typical
    # ``Ctrl-C`` flow does not leave stale shards around. Crashes are
    # handled by the next startup's _sweep_dead_run_caches.
    if _cache_dir_for_atexit != run_dir:
        import atexit
        import shutil as _shutil

        def _cleanup() -> None:
            try:
                if _cache is not None:
                    _cache.close()
            except Exception:
                pass
            try:
                _shutil.rmtree(run_dir, ignore_errors=True)
            except Exception:
                pass

        atexit.register(_cleanup)
        _cache_dir_for_atexit = run_dir

    return background_callback_manager

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
from nanometa_live.app.components.collision_modal import create_collision_modal
from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.config.config_loader import ConfigLoader


def _tab_label(icon_class: str, text: str):
    """Create a tab label string. Icons are not supported by dbc.Tab label prop in dbc 2.0.4."""
    return text


def _init_offline_mode(offline: bool, genome_cache_dir: Optional[str] = None) -> None:
    """Propagate offline_mode to all API client singletons.

    Must be called before any callback fires so that lazily-created
    singletons inherit the correct mode. ``genome_cache_dir`` is
    threaded into the GenomeManager so first-time creation lands at
    the operator-configured path instead of the legacy default.
    """
    from nanometa_live.core.taxonomy.taxonomy_api import get_ncbi_client, get_gtdb_client
    from nanometa_live.core.utils.offline_cache import get_cache
    from nanometa_live.core.utils.genome_manager import get_genome_manager

    get_cache(offline_mode=offline)
    get_ncbi_client(offline_mode=offline)
    get_gtdb_client(offline_mode=offline)
    get_genome_manager(cache_dir=genome_cache_dir, offline_mode=offline)


def create_app(
    config: Dict[str, Any],
    data_dir: str,
    backend_manager: BackendManager,
) -> Dash:
    """
    Create and configure the Dash application.

    Boot is always fresh: there is no automatic session restore. A prior
    configuration can be restored deliberately from Configuration > Load,
    and a finished run's data can be viewed via the "Open Results" control
    in the secondary bar.

    Args:
        config: Application configuration
        data_dir: Per-installation data directory (e.g. ~/.nanometa)
        backend_manager: BackendManager instance

    Returns:
        Configured Dash application
    """
    # Resolve the per-installation directory layout once and pass it
    # into every subsystem that needs it. NanometaPaths reads
    # ``config["data_dir"]`` (seeded by nanometa_live.py from
    # ``--data-dir``) and falls back to ``~/.nanometa`` for legacy
    # operators.
    from nanometa_live.core.utils.paths import NanometaPaths
    paths = NanometaPaths.from_config(config)
    paths.ensure_dirs()

    # Initialise the background-callback Diskcache lazily so its shards
    # land under ``data_dir/cache`` instead of ``~/.nanometa/cache``.
    _ensure_background_callback_manager(str(paths.cache))

    # Load Kraken2 database registry. The package ships a download
    # manifest of public DBs (genome-idx URLs); operators can also
    # drop a "kraken2_databases.local.yaml" under data_dir with
    # the same schema to register additional entries (e.g. private
    # mirrors, in-house custom builds). Keys defined locally win over
    # the bundled defaults so a deployment can override an entry.
    # Closes DB-7.
    kraken_databases: dict = {}
    bundled = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "kraken2_databases.yaml"
    )
    local = str(paths.kraken2_local_registry)
    for source in (bundled, local):
        if not os.path.isfile(source):
            continue
        try:
            with open(source, "r") as f:
                data = yaml.safe_load(f) or {}
            entries = data.get("kraken2_databases", {})
            if isinstance(entries, dict):
                kraken_databases.update(entries)
        except Exception as e:
            logging.error("Error loading Kraken database registry %s: %s", source, e)

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

    # Prevent stale browser cache from breaking callbacks after Dash version upgrades.
    # Dash 4 changed the callback output key format (hash suffixes for allow_duplicate),
    # so cached Dash 3.x JS will send the wrong output keys, causing 500 errors.
    # Must cover ALL responses including async JS chunks that lack version fingerprints.
    @app.server.after_request
    def add_cache_headers(response):
        if ('javascript' in response.content_type or
                request.path.startswith('/_dash-component-suites/') or
                request.path.startswith('/assets/')):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

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
        # Rolling buffer for the header throughput tile (U1, 2026-05-09 UX
        # spec). Keeps at most BUFFER_LIMIT (5) ticks of cumulative reads
        # and file counts; rates and stall detection derive from this.
        dcc.Store(id='throughput-buffer', data={
            "ticks": [],
            "reads_per_min": None,
            "files_per_min": None,
            "stalled_since": None,
        }),
        # Per-sample freshness map (U2). Wall-clock seconds-since-last-
        # data is computed in update_sample_freshness; consumers map it to
        # the green/amber/red pill via freshness_pill().
        dcc.Store(id='sample-freshness', data={}),
        dcc.Store(id='notification-trigger', data={}),
        dcc.Store(id='last-update-time', data=None),
        dcc.Store(id='toast-message', data=None),
        # Dedicated channel for the background internet-reachability check so
        # it never shares the initial_duplicate toast-message output (which
        # crashed the dash-renderer when a background callback wrote it). A
        # tiny relay callback mirrors this into toast-message.
        dcc.Store(id='internet-check-toast', data=None),
        # Carries WatchlistEntry.to_dict() payloads from the background
        # validation worker back to the main process, which applies them to
        # the singleton (see apply_validation_results).
        dcc.Store(id='watchlist-validation-results', data=None),
        dcc.Store(id='theme-preference', data='auto'),  # auto, light, dark
        dcc.Store(id='previous-running-state', data=False),  # For detecting analysis completion
        dcc.Store(id='readiness-state', data={"ready": False, "checks": []}),

        # Per-list "show all" toggles for the BLAST + minimap2 result-
        # card containers. Default False renders only the top 30; the
        # "Show all" button each container ships flips this to True.
        # Closes P1-T07 from
        # docs/audit-2026-04-28-throughput-ux.md.
        dcc.Store(id='blast-show-all', data=False),
        dcc.Store(id='coverage-show-all', data=False),

        # Event-driven refresh gate. compute_results_fingerprint scans the
        # nanometanf output dirs once per update-interval tick; data-bound
        # callbacks that switched their Input from update-interval to
        # results-fingerprint only fire when the fingerprint actually
        # advances (i.e. when nanometanf wrote a new file).
        dcc.Store(id='results-fingerprint', data={"fp": "", "ts": 0}),

        # Shared stores for cross-tab communication (Watchlist <-> Preparation)
        dcc.Store(id='taxmap-collection', data=None),
        dcc.Store(id='taxmap-database-info', data=None),
        dcc.Store(id='taxmap-rescan-complete', data=None),
        # Snapshot of current watchlist entries, hydrated in the main
        # process whenever watchlist-table-refresh ticks. Background
        # callbacks read this as State instead of the WatchlistManager
        # singleton, which is empty in worker processes.
        dcc.Store(id='watchlist-entries-snapshot', data=[]),
        dcc.Store(id='genome-status-data', data={}),
        dcc.Store(id='genome-download-complete', data=None),
        dcc.Store(id='blast-build-complete', data=None),

        # Interval for updating data
        dcc.Interval(
            id='update-interval',
            interval=config.get('update_interval_seconds', 10) * 1000,  # in milliseconds
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

        # Init sink for the tab-visibility watcher (see the clientside callback
        # in register_callbacks): pauses update-interval while the tab is hidden.
        dcc.Store(id='visibility-watch-init'),

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
                                persistence=True,
                                persistence_type='session'
                            ),
                            # Explicit "view a results folder" control. Loading
                            # a folder here is a transient view action (sets the
                            # results dir in the in-memory app-config only); it
                            # does not restore or persist a configuration.
                            dbc.Button(
                                [html.I(className="bi bi-folder2-open me-1"), "Open Results..."],
                                id="open-results-btn",
                                color="primary",
                                outline=True,
                                size="sm",
                                className="ms-3",
                                n_clicks=0,
                            ),
                        ], className="d-flex align-items-center flex-wrap")
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
                            # Current results folder being viewed. Populated by
                            # update_current_results_display; "(no results loaded)"
                            # on a fresh boot until Open Results or Start Analysis
                            # points the dashboard at a folder.
                            html.Span(
                                [
                                    html.I(className="bi bi-eye me-1"),
                                    html.Span("Viewing: ", className="fw-semibold"),
                                    html.Span(id="current-results-display",
                                              children="(no results loaded)"),
                                ],
                                className="text-muted small me-3",
                                title="The results folder currently shown in the dashboard",
                                style={"maxWidth": "420px", "overflow": "hidden",
                                       "textOverflow": "ellipsis", "whiteSpace": "nowrap"},
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
            ], id="tabs", active_tab="dashboard-tab",
               persistence=True, persistence_type="session"),
        ], id="main-content", role="main"),

        # Pathogen report modal and data store - placed at root level so the
        # modal is accessible from any tab (Dashboard, Organisms, etc.)
        dcc.Store(id='pathogen-report-data', data={}),
        dbc.Modal([
            dbc.ModalHeader([
                dbc.ModalTitle([
                    html.I(className="bi bi-file-medical me-2"),
                    html.Span(id="pathogen-modal-title", children="Pathogen Report")
                ]),
            ], close_button=True),
            dbc.ModalBody([
                # Threat level banner
                html.Div(id="pathogen-modal-threat-banner", className="mb-3"),

                # Main pathogen info
                dbc.Row([
                    dbc.Col([
                        html.H4(id="pathogen-modal-name", className="mb-1"),
                        html.P(id="pathogen-modal-common-name", className="text-muted mb-2"),
                        dbc.Badge(id="pathogen-modal-category", color="secondary", className="me-2"),
                        dbc.Badge(id="pathogen-modal-bsl", color="info"),
                    ], md=8),
                    dbc.Col([
                        html.Div([
                            html.H2(id="pathogen-modal-reads", className="mb-0 text-primary"),
                            html.Small("sequences detected", className="text-muted")
                        ], className="text-center")
                    ], md=4)
                ], className="mb-4"),

                # Detection details
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-bar-chart me-2"),
                        html.Strong("Detection Details")
                    ]),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("Abundance", className="text-muted small"),
                                html.H5(id="pathogen-modal-abundance")
                            ], md=4),
                            dbc.Col([
                                html.Label("Confidence", className="text-muted small"),
                                html.H5(id="pathogen-modal-confidence")
                            ], md=4),
                            dbc.Col([
                                html.Label("Taxonomy ID", className="text-muted small"),
                                html.H5(id="pathogen-modal-taxid")
                            ], md=4),
                        ])
                    ])
                ], className="mb-3"),

                # Action required
                dbc.Alert([
                    html.H5([
                        html.I(className="bi bi-exclamation-diamond me-2"),
                        "Recommended Action"
                    ], className="alert-heading"),
                    html.P(id="pathogen-modal-action", className="mb-0")
                ], id="pathogen-modal-action-alert", color="warning", className="mb-3"),

                # Notes
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-journal-text me-2"),
                        html.Strong("Additional Information")
                    ]),
                    dbc.CardBody([
                        html.P(id="pathogen-modal-notes", className="mb-0")
                    ])
                ], className="mb-3"),

                # Reference links
                html.Div([
                    html.Label("References", className="text-muted small d-block mb-2"),
                    html.A(
                        [html.I(className="bi bi-box-arrow-up-right me-1"), "NCBI Taxonomy"],
                        id="pathogen-modal-ncbi-link",
                        href="#",
                        target="_blank",
                        className="btn btn-outline-secondary btn-sm me-2"
                    ),
                    html.A(
                        [html.I(className="bi bi-box-arrow-up-right me-1"), "CDC Information"],
                        href="https://www.cdc.gov/niosh/topics/emres/chemagent.html",
                        target="_blank",
                        className="btn btn-outline-secondary btn-sm"
                    )
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button(
                    [html.I(className="bi bi-check-lg me-2"), "Acknowledge Alert"],
                    id="pathogen-modal-acknowledge",
                    color="success",
                    className="me-2"
                ),
                dbc.Button(
                    [html.I(className="bi bi-printer me-2"), "Print Report"],
                    id="pathogen-modal-print",
                    color="secondary",
                    outline=True,
                    className="me-2"
                ),
                dbc.Button("Close", id="pathogen-modal-close", color="secondary")
            ])
        ], id="pathogen-report-modal", size="lg", is_open=False),

        # Toast notification container (for non-blocking feedback)
        html.Div(id="toast-container", className="toast-container"),

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
                        html.P("Go to the Configuration tab and set your input directory and Kraken2 database. Settings are saved automatically between sessions.",
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
                dbc.Button([
                    "Go to Configuration ",
                    html.I(className="bi bi-arrow-right ms-1"),
                ], id="close-welcome-modal", color="primary")
            )
        ], id="welcome-modal", is_open=False, centered=True, size="lg"),
        dcc.Store(id="welcome-shown", storage_type="local", data=False),

        # Output-directory collision modal: warns the operator when the
        # results-output dir already contains nanometanf result subdirs
        # so a new run does not silently mix data from different inputs.
        # The collision-decision-pending Store carries the detected outdir
        # and subdir list while the operator picks an action.
        dcc.Store(
            id='collision-decision-pending',
            data={"outdir": "", "found": []},
        ),
        create_collision_modal(),

        # Open Results: a run picker scoped to the current project. The body
        # is populated by populate_open_results_list with the run folders
        # found under <project>/results/. "Browse another folder" falls back
        # to the generic folder browser for results outside the project.
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle([
                    html.I(className="bi bi-folder2-open me-2"),
                    "Open Results",
                ])),
                dbc.ModalBody(id="open-results-list"),
                dbc.ModalFooter([
                    dbc.Button(
                        [html.I(className="bi bi-search me-1"), "Browse another folder..."],
                        id="open-results-browse-btn",
                        color="secondary",
                        outline=True,
                        className="me-2",
                        n_clicks=0,
                    ),
                    dbc.Button("Close", id="open-results-close-btn", color="light", n_clicks=0),
                ]),
            ],
            id="open-results-modal",
            is_open=False,
            centered=True,
            size="lg",
            scrollable=True,
        ),
    ])

    # Initialize offline mode on all API clients and managers if configured
    offline = config.get("offline_mode", False)
    if offline:
        logging.info("Offline mode enabled — API clients will use cached data only")
    _init_offline_mode(offline, genome_cache_dir=config.get("genome_cache_dir"))

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

    # Clientside callback: watchlist collapse toggle (pure UI, no server needed)
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

    # Clientside elapsed-time display. Replaces the former server-side
    # update_elapsed_time callback that ran once per second per session.
    # The browser computes HH:MM:SS from backend_status.start_time using
    # its local clock, so no round-trip is needed.
    app.clientside_callback(
        """
        function(n_intervals, backend_status) {
            if (!backend_status || !backend_status.running) {
                return ["00:00:00", {"display": "none"}];
            }
            var start = backend_status.start_time;
            if (!start) {
                return ["00:00:00", {"display": "none"}];
            }
            var start_ms = Date.parse(start);
            if (isNaN(start_ms)) {
                return ["00:00:00", {"display": "none"}];
            }
            var elapsed_sec = Math.max(0, Math.floor((Date.now() - start_ms) / 1000));
            var h = Math.floor(elapsed_sec / 3600);
            var m = Math.floor((elapsed_sec % 3600) / 60);
            var s = elapsed_sec % 60;
            var pad = function(n) { return n < 10 ? "0" + n : "" + n; };
            return [
                pad(h) + ":" + pad(m) + ":" + pad(s),
                {"display": "flex", "alignItems": "center"}
            ];
        }
        """,
        [
            Output("elapsed-time-display", "children"),
            Output("elapsed-time-container", "style"),
        ],
        [
            Input("countdown-tick", "n_intervals"),
            Input("backend-status", "data"),
        ],
    )

    # Clientside disable for countdown-tick. The 1 Hz interval only
    # exists to advance the elapsed-time display and the next-update
    # countdown. When no run is active neither needs ticking, so we
    # disable the interval and stop the per-second server-bound
    # backend-status query that follows the (re-enabled) tick.
    app.clientside_callback(
        """
        function(backend_status) {
            return !(backend_status && backend_status.running);
        }
        """,
        Output("countdown-tick", "disabled"),
        Input("backend-status", "data"),
    )

    # Pause the data-refresh interval while the browser tab is hidden, so a
    # backgrounded dashboard does no polling, fingerprint scans, or re-renders.
    # Event-driven (visibilitychange), not polled: the listener is bound once
    # on load and flips update-interval.disabled via set_props; the interval
    # resumes the moment the tab is shown again.
    app.clientside_callback(
        """
        function(_) {
            if (!window.__nmVisibilityBound) {
                window.__nmVisibilityBound = true;
                var apply = function() {
                    window.dash_clientside.set_props(
                        'update-interval', {disabled: document.hidden === true});
                };
                document.addEventListener('visibilitychange', apply);
                apply();  // apply current state on load
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("visibility-watch-init", "data"),
        Input("app-config", "data"),
    )