"""Multi-sample / barcode selection and freshness callbacks."""

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


def register_samples(app, backend_manager):
    @app.callback(
        [
            Output("available-samples", "data"),
            Output("sample-file-mapping", "data"),
        ],
        Input("results-fingerprint", "data"),
        Input("update-interval", "n_intervals"),
        State("app-config", "data"),
        State("available-samples", "data"),
        State("sample-file-mapping", "data"),
    )
    def update_available_samples(fingerprint, n_intervals, config, prev_samples, prev_mapping):
        """
        Detect and update available samples from nanometanf output.

        Scans the output directory for Kraken2, FASTP, and BLAST files
        to automatically detect all available samples/barcodes.

        Driven primarily by ``results-fingerprint`` so the filesystem scan
        (70+ scandir calls at 24-barcode scale) only runs when the outdir
        actually changed. ``update-interval`` is kept as a backstop -- a tab
        visited on a quiet outdir after the first fingerprint tick still
        needs one refresh -- but interval ticks are debounced so they are a
        microsecond short-circuit rather than a full scan.

        Short-circuits with PreventUpdate when the detected sample list and
        file mapping have not changed since the previous tick, so identical
        content never re-renders downstream subscribers.
        """
        if get_trigger_type(dash.ctx) == "interval" and interval_render_is_redundant("available_samples", fingerprint):
            raise PreventUpdate
        mark_rendered("available_samples", fingerprint)

        if not config:
            new_samples, new_mapping = ["All Samples"], {}
        else:
            try:
                # Use results_output_directory for pipeline output (where kraken2/, fastp/ are)
                main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")

                if not main_dir or not os.path.exists(main_dir):
                    new_samples, new_mapping = ["All Samples"], {}
                else:
                    # Get available samples from output files
                    new_samples = get_available_samples(main_dir)
                    new_mapping = get_sample_file_mapping(main_dir)
                    logging.debug(f"Detected {len(new_samples)-1} samples: {new_samples}")
            except Exception as e:
                log_callback_error("update_available_samples", e, level=logging.WARNING)
                new_samples, new_mapping = ["All Samples"], {}

        # Skip the store overwrite when nothing meaningful changed. The
        # comparison is intentionally on the wire-format dicts/lists Dash
        # sees; identical content means subscribers will not re-render.
        if new_samples == (prev_samples or []) and new_mapping == (prev_mapping or {}):
            raise PreventUpdate

        return new_samples, new_mapping

    @app.callback(
        [
            Output("sample-selector", "options"),
            Output("sample-selector", "value"),
        ],
        Input("available-samples", "data"),
        Input("sample-freshness", "data"),
        State("sample-selector", "value"),
    )
    def update_sample_selector_options(available_samples, freshness, current_value):
        """
        Update sample selector dropdown options.

        Converts the list of available samples into Dash dropdown options
        and renders a per-barcode freshness pill (U2) next to each
        non-aggregated sample. Resets the selected value to 'All Samples'
        if the current selection is no longer available.
        """
        from nanometa_live.app.components.freshness_pill import freshness_pill
        from nanometa_live.app.utils.freshness import age_seconds_for

        if not available_samples:
            available_samples = ["All Samples"]
        freshness = freshness or {}
        now = time.time()

        options = []
        for sample in available_samples:
            if sample == "All Samples":
                options.append({"label": "All Samples (Aggregated)", "value": sample})
                continue
            last_ts = freshness.get(sample)
            age = age_seconds_for(last_ts, now)
            label = html.Span(
                [html.Span(sample, className="text-truncate"),
                 freshness_pill(sample, age, class_name="ms-2")],
                className="d-inline-flex align-items-center",
            )
            options.append({"label": label, "value": sample})

        # Reset to 'All Samples' if current selection is no longer valid
        if current_value and current_value not in available_samples:
            return options, "All Samples"

        return options, no_update

    @app.callback(
        Output("sample-freshness", "data"),
        Input("results-fingerprint", "data"),
        Input("update-interval", "n_intervals"),
        State("available-samples", "data"),
        State("app-config", "data"),
    )
    def update_sample_freshness(_fp, _n, available_samples, config):
        """Refresh the per-sample last_data_ts map.

        Driven by ``results-fingerprint`` so the map advances when new
        files land on disk; the interval input is a backstop to keep the
        age field current even on quiet outdirs.
        """
        from nanometa_live.app.utils.freshness import freshness_map

        if not config or not available_samples:
            return {}
        main_dir = (
            config.get("results_output_directory", "")
            or config.get("main_dir", "")
        )
        if not main_dir or not os.path.isdir(main_dir):
            return {}
        try:
            return freshness_map(main_dir, available_samples)
        except Exception as exc:
            log_callback_error("update_sample_freshness", exc, level=logging.WARNING)
            return {}

    @app.callback(
        Output("selected-sample", "data"),
        Input("sample-selector", "value"),
    )
    def update_selected_sample(selected_value):
        """
        Update the selected-sample store when user changes selection.

        This store is used by all tabs to filter data by sample.
        """
        return selected_value if selected_value else "All Samples"

    # ========================================================================
    # Live Indicator Callbacks (Real-time Status Display)
    # ========================================================================
