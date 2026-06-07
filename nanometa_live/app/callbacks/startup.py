"""Startup callbacks: missing-path warning, internet auto-detect, taxid mappings."""

import hashlib
import json
import os
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

import dash
from dash import ALL, Dash, Input, Output, State, callback, dcc, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.utils.sample_detector import get_available_samples, get_sample_file_mapping
from nanometa_live.core.utils.loader_utils import check_data_freshness
from nanometa_live.app.utils.callback_helpers import log_callback_error
from nanometa_live.app.utils.outdir_resolution import resolve_outdir_for_fingerprint
from nanometa_live.app.utils.debounce import (
    should_skip_update, get_trigger_type,
    interval_render_is_redundant, mark_rendered,
)
from nanometa_live.app.app import background_callback_manager

# Tracks the kraken_db path the taxid mapping callback last initialised
# from. When the operator points the dashboard at a different Kraken2
# database mid-session, this lets the callback re-load mappings instead
# of being permanently gated by a boolean flag in the config dict.
_taxid_mapping_db_path: Optional[str] = None


def register_startup(app, backend_manager):

    # ========================================================================
    # Internet Auto-Detection (startup suggestion)
    # ========================================================================

    _internet_check_lock = threading.Lock()
    _internet_checked = {"done": False}
    _path_check_lock = threading.Lock()
    _paths_checked = {"done": False}

    @app.callback(
        Output("toast-message", "data", allow_duplicate=True),
        Input("app-config", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def warn_about_missing_paths_on_startup(config):
        """Surface stale path values from a loaded config as a toast.

        ConfigLoader.load_config already logs WARNING entries for path
        keys that point to missing locations, but operators rarely
        watch the terminal. This callback runs once per session and
        emits a single combined toast naming any path key whose value
        is set but does not exist on disk -- typically results from a
        last-session.yaml that was written when the kraken DB lived at
        a different mount point. We deliberately do NOT clear the
        field; the operator sees the stale value in Configuration and
        can re-point or remove it. Closes DB-5.
        """
        with _path_check_lock:
            if _paths_checked["done"]:
                return no_update
            _paths_checked["done"] = True

        if not config:
            return no_update

        try:
            from nanometa_live.core.utils.path_utils import report_missing_paths
            missing = report_missing_paths(config)
        except Exception:
            return no_update

        if not missing:
            return no_update

        lines = "\n".join(f"- {key}: {path}" for key, path in missing.items())
        return {
            "type": "warning",
            "title": "Configured paths not found",
            "message": (
                "The loaded configuration references paths that do not "
                "exist on this machine. Review them in the Configuration "
                "tab before launching:\n" + lines
            ),
        }

    @app.callback(
        Output("internet-check-toast", "data"),
        Input("app-config", "data"),
        background=True,
        manager=background_callback_manager,
    )
    def check_internet_on_startup(config):
        """On first load, check internet and suggest offline mode if unreachable.

        Runs in a DiskcacheManager worker so the up-to-3-second
        ``requests.get`` reachability probe never holds a Werkzeug request
        thread. Writes to the dedicated ``internet-check-toast`` store
        rather than the shared ``toast-message`` output: a background
        callback writing the initial_duplicate toast-message output crashed
        the dash-renderer at load. The relay callback below mirrors the
        result into toast-message. The module-level guard lives in the
        worker process, so the probe may run on more than one of the handful
        of startup app-config writes; that is harmless (advisory toast,
        suppressed once offline mode is on)."""
        with _internet_check_lock:
            if _internet_checked["done"]:
                return no_update
            _internet_checked["done"] = True

        if config and config.get("offline_mode"):
            return no_update
        try:
            import requests as req
            req.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi",
                timeout=3,
            ).raise_for_status()
            return no_update
        except Exception:
            return {
                "type": "warning",
                "title": "No Internet Detected",
                "message": "Consider enabling Offline Mode in Settings.",
            }

    @app.callback(
        Output("toast-message", "data", allow_duplicate=True),
        Input("internet-check-toast", "data"),
        prevent_initial_call=True,
    )
    def relay_internet_check_toast(toast):
        """Mirror the background internet-check result into the shared toast
        channel. Kept separate (and non-background) so the background
        callback never touches the initial_duplicate toast-message output."""
        if not toast:
            raise PreventUpdate
        return toast

    # ========================================================================
    # Taxid Mapping Initialization (for pathogen detection)
    # ========================================================================
    # This runs once on startup to load cached taxid mappings if they exist.
    # Required for proper pathogen detection with GTDB/custom Kraken2 databases.

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Output("taxmap-collection", "data", allow_duplicate=True),
        Output("taxmap-database-info", "data", allow_duplicate=True),
        Output("taxmap-rescan-complete", "data", allow_duplicate=True),
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def initialize_taxid_mappings(_n_intervals, config):
        """
        Load cached taxid mappings on startup for proper pathogen detection.

        This callback runs once when the app-config is first set and loads
        any cached mappings for the configured Kraken2 database. This enables
        proper pathogen detection with GTDB databases where taxids differ from
        NCBI taxids, and populates the Dash stores so the Watchlist &
        Preparation tab shows correct status on first visit.
        """
        from nanometa_live.app.utils.config_manager import atomic_config_update

        global _taxid_mapping_db_path

        if not config:
            return no_update, no_update, no_update, no_update

        kraken_db = config.get("kraken_db", "")
        if not kraken_db or not os.path.exists(kraken_db):
            return no_update, no_update, no_update, no_update

        # Only initialize when the configured Kraken2 database changes.
        # Keying on the path (rather than a one-shot boolean) means the
        # callback re-loads mappings if the operator switches databases
        # mid-session.
        if _taxid_mapping_db_path == kraken_db:
            return no_update, no_update, no_update, no_update

        try:
            from nanometa_live.core.taxonomy.taxid_mapping import (
                get_mapping_cache_path,
                TaxidMappingCollection,
                set_mapping_collection,
            )

            collection_data = no_update
            db_info = no_update
            rescan_time = no_update

            # Check if cached mappings exist for this database
            cache_path = get_mapping_cache_path(kraken_db)
            if cache_path.exists():
                collection = TaxidMappingCollection.load(str(cache_path))
                if collection:
                    set_mapping_collection(collection)
                    logging.info(
                        f"Loaded cached taxid mappings: {collection.total_entries} entries, "
                        f"{collection.mapped_exact} exact, {collection.mapped_fuzzy} fuzzy"
                    )

                    # Populate Dash stores for Watchlist & Preparation tab display
                    coll_dict = collection.to_dict()
                    collection_data = {
                        "mappings": {
                            str(m["ncbi_taxid"]): m
                            for m in coll_dict.get("mappings", [])
                        },
                        "statistics": coll_dict.get("statistics", {}),
                    }
                    db_info = {
                        "type": collection.database_type.value,
                        "hash": collection.database_hash,
                        "path": collection.database_path,
                    }
                    rescan_time = collection.updated_at.isoformat()

            # Record the db path we initialised from so the next tick
            # short-circuits unless the operator switches databases.
            _taxid_mapping_db_path = kraken_db

            # Use atomic update to properly track version
            updated_config = atomic_config_update(
                config,
                {"_taxid_mapping_initialized": True},
                source="initialize_taxid_mappings"
            )

            return updated_config, collection_data, db_info, rescan_time

        except Exception as e:
            logging.debug(f"Could not load taxid mappings: {e}")
            return no_update, no_update, no_update, no_update
