"""
Dashboard tab callbacks for non-technical operators.

This module implements the callback logic for the overview dashboard,
translating technical bioinformatics data into plain language status
information for first responders and laboratory personnel.
"""

import os
import glob
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
import logging

from dash import Dash, Input, Output, State, ctx, no_update, html, ALL
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from nanometa_live.core.utils.data_loaders import (
    load_kraken_data,
    load_nanoplot_stats,
    load_seqkit_stats,
    get_qc_stats
)
from nanometa_live.core.utils.alert_engine import get_alert_engine
from nanometa_live.core.utils.pathogen_database import check_for_dangerous_pathogens
from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
from nanometa_live.app.utils.callback_helpers import (
    safe_load_kraken_data,
    get_classification_stats,
    format_bp,
    validate_config_and_get_main_dir,
    log_callback_error,
)
from nanometa_live.app.utils.debounce import should_skip_update, get_trigger_type
from nanometa_live.app.layouts.dashboard_layout import create_alerts_list
from nanometa_live.app.components.modern_components import (
    LastUpdatedBadge,
)
from nanometa_live.app.components.pathogen_alert import (
    CriticalPathogenAlert,
    HighRiskPathogenAlert,
    WatchedSpeciesAlert,
)

logger = logging.getLogger(__name__)


def _species_df_to_organisms(species_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Convert species DataFrame to list of organism dicts (vectorized).

    Args:
        species_df: DataFrame with species-level classifications

    Returns:
        List of organism dicts with taxid, name, reads, abundance
    """
    if species_df.empty:
        return []

    # Vectorized extraction - much faster than iterrows
    # Use '%' column if available (kraken report standard), otherwise try 'fraction_total_reads'
    if '%' in species_df.columns:
        abundance_col = species_df['%'].fillna(0).astype(float)
    elif 'fraction_total_reads' in species_df.columns:
        abundance_col = species_df['fraction_total_reads'].fillna(0).astype(float) * 100
    else:
        abundance_col = pd.Series([0.0] * len(species_df))

    result_df = pd.DataFrame({
        'taxid': species_df['taxid'].fillna(0).astype(int),
        'name': species_df['name'].fillna('Unknown'),
        'reads': species_df['reads'].fillna(0).astype(int),
        'abundance': abundance_col
    })
    return result_df.to_dict('records')


def _load_per_sample_organisms(
    main_dir: str,
    available_samples: List[str]
) -> Dict[int, List[Dict[str, Any]]]:
    """
    Load species-level organisms from each sample and return a per-taxid attribution dict.

    Keyed by the Kraken2 database taxid (as it appears in reports), each value is a
    list of sample-level dicts sorted descending by reads. A sample is flagged as
    negative control when its name contains "negative" (case-insensitive) — the
    codebase has no explicit manifest NC flag at this stage.

    Args:
        main_dir: Results output directory
        available_samples: All sample names including "All Samples"

    Returns:
        Dict[int, List[{sample, reads, abundance, is_negative_control}]]
    """
    real_samples = [s for s in available_samples if s != "All Samples"]
    if not real_samples:
        return {}

    taxid_to_samples: Dict[int, List[Dict[str, Any]]] = {}

    for sample in real_samples:
        is_nc = "negative" in sample.lower()
        try:
            kraken_df = load_kraken_data(main_dir, sample)
            if kraken_df.empty:
                continue
            species_df = kraken_df[
                (kraken_df["rank"] == "S") & (kraken_df["reads"] >= 5)
            ]
            if species_df.empty:
                continue
            for org in _species_df_to_organisms(species_df):
                taxid = org["taxid"]
                if taxid not in taxid_to_samples:
                    taxid_to_samples[taxid] = []
                taxid_to_samples[taxid].append({
                    "sample": sample,
                    "reads": org["reads"],
                    "abundance": org["abundance"],
                    "is_negative_control": is_nc,
                })
        except Exception as exc:
            logger.debug(f"Per-sample organism load failed for {sample}: {exc}")

    # Sort each sample list descending by reads
    for taxid in taxid_to_samples:
        taxid_to_samples[taxid].sort(key=lambda x: x["reads"], reverse=True)

    return taxid_to_samples


def _get_active_watchlist_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get only ENABLED watchlist entries for alerting.

    Returns active entries from WatchlistManager.

    Args:
        config: Application configuration dict

    Returns:
        List of enabled watchlist entries with 'enabled': True
    """
    active_entries = []

    # Get active entries from WatchlistManager
    try:
        manager = get_watchlist_manager()
        # Load watchlist manager if not already loaded
        if not manager._loaded and config:
            manager.load_config(config)
            logger.debug(f"Dashboard: Loaded WatchlistManager with {len(manager.get_active_entries())} active entries")
        if manager._loaded:
            for entry in manager.get_active_entries().values():
                active_entries.append({
                    "name": entry.name,
                    "taxid": entry.taxid,  # WatchlistEntry uses 'taxid', not 'taxid_ncbi'
                    "common_name": entry.common_name,
                    "threat_level": entry.threat_level.value if entry.threat_level else "moderate",
                    "alert_threshold": entry.alert_threshold,
                    "enabled": True,  # Already filtered to active
                })
    except Exception as e:
        logger.debug(f"Could not get WatchlistManager entries: {e}")

    # Also include legacy species_of_interest (but only enabled ones)
    legacy_species = config.get("species_of_interest", [])
    for species in legacy_species:
        if species.get("enabled", True):  # Default to enabled if not specified
            # Avoid duplicates by taxid
            taxid = species.get("taxid")
            if taxid and any(e.get("taxid") == taxid for e in active_entries):
                continue
            active_entries.append({
                **species,
                "enabled": True,
            })

    return active_entries


def _check_pathogens_with_mapping(
    detected_organisms: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Check detected organisms against pathogen database using proper taxid mapping.

    This function uses the WatchlistManager's check_organisms_with_mapping() method
    which properly handles GTDB and custom Kraken2 databases where taxids differ
    from NCBI taxids.

    Args:
        detected_organisms: List of dicts with 'taxid', 'name', 'reads', 'abundance'
        config: Optional config dict (for loading watchlist if needed)

    Returns:
        List of detected dangerous pathogens with full information
    """
    if not detected_organisms:
        return []

    try:
        # Get WatchlistManager
        manager = get_watchlist_manager()

        # Ensure manager is loaded
        if not manager._loaded and config:
            manager.load_config(config)

        # Get taxid mapping collection for proper db_taxid -> ncbi_taxid lookup
        from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
        mapping_collection = get_mapping_collection()

        # Use the proper mapping-aware check function
        if mapping_collection:
            # WatchlistManager.check_organisms_with_mapping() properly handles:
            # 1. Direct NCBI taxid match
            # 2. Reverse mapping from Kraken2 db_taxid to NCBI taxid
            # 3. Name-based matching as fallback
            return manager.check_organisms_with_mapping(
                detected_organisms,
                mapping_collection
            )
        else:
            # Fall back to standard method if no mapping available
            # This still uses name matching as backup
            logger.debug("No taxid mapping available, falling back to standard organism check")
            return manager.check_organisms(detected_organisms)

    except Exception as e:
        logger.warning(f"Error in pathogen check with mapping: {e}")
        # Fall back to old method on error
        watched_species = _get_active_watchlist_entries(config) if config else []
        return check_for_dangerous_pathogens(detected_organisms, watched_species)


def register_dashboard_callbacks(app: Dash):
    """
    Register callbacks for the dashboard tab.

    Args:
        app: Dash application instance

    Callbacks registered:
        - update_dashboard: Main dashboard update (status, metrics, samples, alerts)
        - handle_sample_selection: Handle sample row selection for drill-down
    """

    # ---- Helper: check if dashboard should load data ----
    def _should_load_data(config, status, available_samples):
        """Check if conditions are met to load dashboard data."""
        if not config or not status:
            return False, ""
        visualization_mode = config.get("visualization_only", False)
        pipeline_running = status.get("running", False)
        pipeline_completed = status.get("completed", False)
        has_data = available_samples and len(available_samples) > 1
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
        has_results_dir = main_dir and os.path.isdir(os.path.join(main_dir, "kraken2"))
        should_load = visualization_mode or pipeline_running or pipeline_completed or has_data or has_results_dir
        return should_load, main_dir

    def _resolve_samples(main_dir, available_samples):
        """Resolve available_samples, detecting directly if needed."""
        if not available_samples or available_samples == ["All Samples"]:
            from nanometa_live.core.utils.sample_detector import get_available_samples as detect_samples
            if main_dir and os.path.isdir(main_dir):
                return detect_samples(main_dir)
        return available_samples

    # ================================================================
    # D3-pre: Compute overall status once, cache in dcc.Store
    # ================================================================
    @app.callback(
        Output("dashboard-overall-status-cache", "data"),
        [
            Input("update-interval", "n_intervals"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("available-samples", "data"),
        ]
    )
    def compute_overall_status_cache(n_intervals, config, status, available_samples):
        """Compute overall status once per interval and cache for other callbacks."""
        if should_skip_update("dashboard_overall_status", debounce_ms=2000):
            raise PreventUpdate

        should_load, main_dir = _should_load_data(config, status, available_samples)
        if not should_load:
            return None

        try:
            available_samples = _resolve_samples(main_dir, available_samples)
            pipeline_running = status.get("running", False)
            overall_status = _calculate_overall_status(main_dir, config, available_samples, pipeline_running)
            # Include main_dir and samples_data so downstream callbacks don't recompute
            overall_status["_main_dir"] = main_dir
            overall_status["_samples_data"] = _collect_samples_data(main_dir, available_samples)
            overall_status["_available_samples"] = available_samples
            return overall_status
        except Exception as e:
            logger.error(f"Error computing overall status cache: {e}", exc_info=True)
            return None

    # ================================================================
    # Zone 1: Verdict Banner callback
    # Merges previous D3a (status) and threat summary into one banner.
    # ================================================================
    @app.callback(
        [
            Output("dashboard-verdict-banner", "children"),
            Output("dashboard-verdict-banner", "style"),
            Output("dashboard-time-elapsed", "children"),
            Output("dashboard-run-state-badge", "children"),
            Output("dashboard-run-state-badge", "color"),
        ],
        [
            Input("update-interval", "n_intervals"),
            Input("watchlist-tab-state", "data"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("dashboard-overall-status-cache", "data"),
            State("validation-data-store", "data"),
        ]
    )
    def update_verdict_banner(n_intervals, watchlist_state, config, status,
                              overall_status, validation_data):
        """Update the clinical verdict banner based on analysis status and pathogen screening."""
        if get_trigger_type(ctx) == "interval":
            if should_skip_update("dashboard_verdict_banner", debounce_ms=2000):
                raise PreventUpdate

        pipeline_running = status.get("running", False) if status else False
        pipeline_completed = status.get("completed", False) if status else False
        start_time = status.get("start_time") if status else None
        time_elapsed = _format_time_elapsed(start_time)
        last_updated_str = "Last updated " + datetime.now().strftime("%H:%M:%S")

        # Check whether any validation results exist (used for confidence qualifier)
        validation_has_results = bool(
            validation_data and validation_data.get("results")
        )

        if pipeline_running:
            run_state = "ACTIVE"
            run_state_color = "success"
        elif pipeline_completed:
            run_state = "COMPLETE"
            run_state_color = "info"
        else:
            run_state = "STANDBY"
            run_state_color = "secondary"

        # No config or no data: STANDBY or SCREENING IN PROGRESS
        if not config:
            if pipeline_running:
                return (
                    _make_banner_content(
                        "arrow-repeat", "#084298",
                        "SCREENING IN PROGRESS", "First results pending",
                        run_state, time_elapsed,
                        sub_color="#084298",
                        last_updated_str=last_updated_str,
                        icon_extra_class="spin",
                    ),
                    _verdict_banner_style("#cfe2ff", "#0d6efd"),
                    time_elapsed, run_state, run_state_color
                )
            return (
                _make_banner_content(
                    "pause-circle", "#6c757d",
                    "STANDBY", "Start an analysis to begin",
                    run_state, time_elapsed,
                    sub_color="#6c757d",
                    last_updated_str=last_updated_str,
                ),
                _verdict_banner_style("#f8f9fa", "#6c757d"),
                time_elapsed, run_state, run_state_color
            )

        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")

        # Pipeline running but no data yet
        if overall_status and overall_status.get("status") == "starting":
            return (
                _make_banner_content(
                    "arrow-repeat", "#084298",
                    "SCREENING IN PROGRESS", "First results pending",
                    run_state, time_elapsed,
                    sub_color="#084298",
                    last_updated_str=last_updated_str,
                    icon_extra_class="spin",
                ),
                _verdict_banner_style("#cfe2ff", "#0d6efd"),
                time_elapsed, run_state, run_state_color
            )

        try:
            if main_dir and os.path.isdir(main_dir):
                kraken_df = load_kraken_data(main_dir, "All Samples")
                if not kraken_df.empty:
                    species_df = kraken_df[
                        (kraken_df["rank"] == "S") & (kraken_df["reads"] >= 5)
                    ]
                    detected_organisms = _species_df_to_organisms(species_df)
                    watched_species = _get_active_watchlist_entries(config)
                    n_watched = len(watched_species)
                    dangerous = _check_pathogens_with_mapping(detected_organisms, config)

                    if dangerous:
                        n_found = len(dangerous)
                        critical = [d for d in dangerous if d.get("threat_level") == "critical"]
                        high_risk = [d for d in dangerous
                                     if d.get("threat_level") in ["high", "high_risk"]]
                        if critical or high_risk:
                            action_sub = (
                                f"{n_found} of {n_watched} monitored pathogens found — act now"
                            )
                            if not validation_has_results:
                                action_sub += " — pending confirmatory validation"
                            return (
                                _make_banner_content(
                                    "exclamation-octagon-fill", "#8b0000",
                                    "ACTION REQUIRED",
                                    action_sub,
                                    run_state, time_elapsed,
                                    sub_color="#721c24",
                                    show_icon_mobile=True,
                                    last_updated_str=last_updated_str,
                                ),
                                _verdict_banner_style("#f8d7da", "#8b0000"),
                                time_elapsed, run_state, run_state_color
                            )
                        return (
                            _make_banner_content(
                                "eye-fill", "#fd7e14",
                                "MONITORING",
                                "Moderate-risk species found",
                                run_state, time_elapsed,
                                sub_color="#664d03",
                                last_updated_str=last_updated_str,
                            ),
                            _verdict_banner_style("#fff3cd", "#fd7e14"),
                            time_elapsed, run_state, run_state_color
                        )

                    # ALL CLEAR
                    return (
                        _make_banner_content(
                            "shield-check", "#28a745",
                            "ALL CLEAR",
                            f"0 of {n_watched} monitored pathogens found",
                            run_state, time_elapsed,
                            sub_color="#155724",
                            last_updated_str=last_updated_str,
                        ),
                        _verdict_banner_style("#d4edda", "#28a745"),
                        time_elapsed, run_state, run_state_color
                    )

                if pipeline_running:
                    return (
                        _make_banner_content(
                            "arrow-repeat", "#084298",
                            "SCREENING IN PROGRESS", "First results pending",
                            run_state, time_elapsed,
                            sub_color="#084298",
                            last_updated_str=last_updated_str,
                            icon_extra_class="spin",
                        ),
                        _verdict_banner_style("#cfe2ff", "#0d6efd"),
                        time_elapsed, run_state, run_state_color
                    )

        except Exception as e:
            logger.error(f"Error updating verdict banner: {e}", exc_info=True)

        # Default: STANDBY
        return (
            _make_banner_content(
                "pause-circle", "#6c757d",
                "STANDBY", "Start an analysis to begin",
                run_state, time_elapsed,
                sub_color="#6c757d",
                last_updated_str=last_updated_str,
            ),
            _verdict_banner_style("#f8f9fa", "#6c757d"),
            time_elapsed, run_state, run_state_color
        )

    # ================================================================
    # Zone 3: Quality card callback
    # Replaces the old update_nanoplot_badges callback.
    # ================================================================
    @app.callback(
        Output("dashboard-quality-card-content", "children"),
        [Input("update-interval", "n_intervals")],
        [State("app-config", "data"), State("backend-status", "data")]
    )
    def update_quality_card(n_intervals, config, status):
        """Update the Sample Quality card with Q-score level and value."""
        if should_skip_update("dashboard_quality_card", debounce_ms=2000):
            raise PreventUpdate

        default_content = [
            html.I(className="bi bi-shield-check",
                   style={"fontSize": "28px", "color": "#6c757d"}),
            html.H3("--", className="dashboard-metric-value mb-0"),
            html.P("Sample Quality", className="dashboard-metric-label text-muted mb-0")
        ]

        if not config:
            return default_content

        visualization_mode = config.get("visualization_only", False)
        pipeline_running = status.get("running", False) if status else False
        pipeline_completed = status.get("completed", False) if status else False
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
        has_main_dir = bool(main_dir and os.path.isdir(main_dir))

        if not (visualization_mode or pipeline_running or pipeline_completed or has_main_dir):
            return default_content

        try:
            nanoplot_stats = load_nanoplot_stats(main_dir)
            mean_quality = nanoplot_stats.get("mean_read_quality", 0)

            if not mean_quality:
                qc_stats = get_qc_stats(main_dir)
                mean_quality = qc_stats.get("mean_quality", 0) or qc_stats.get("q_score", 0)

            if mean_quality and mean_quality > 0:
                # Q-score thresholds matching QualityScoreBadge logic
                if mean_quality >= 20:
                    level = "Excellent"
                    icon_color = "#28a745"
                elif mean_quality >= 15:
                    level = "Good"
                    icon_color = "#0dcaf0"
                elif mean_quality >= 10:
                    level = "Fair"
                    icon_color = "#ffc107"
                else:
                    level = "Poor"
                    icon_color = "#dc3545"

                return [
                    html.I(className="bi bi-shield-check",
                           style={"fontSize": "28px", "color": icon_color}),
                    html.H3(level, className="dashboard-metric-value mb-0",
                            style={"color": icon_color}),
                    html.P(f"Q{mean_quality:.1f}", className="text-muted small mb-0"),
                    html.P("Sample Quality",
                           className="dashboard-metric-label text-muted mb-0")
                ]

        except Exception as e:
            logger.error(f"Error updating quality card: {e}")

        return default_content

    # ================================================================
    # D3b: Metrics callback (sequences + organisms counts)
    # ================================================================
    @app.callback(
        [
            Output("dashboard-sequences-count", "children"),
            Output("dashboard-organisms-count", "children"),
            Output("dashboard-data-cache", "data"),
        ],
        [
            Input("dashboard-overall-status-cache", "data"),
            Input("sample-selector", "value"),
        ],
        [
            State("app-config", "data"),
            State("available-samples", "data"),
            State("dashboard-data-cache", "data"),
        ]
    )
    def update_dashboard_metrics(overall_status, selected_dashboard_sample,
                                 config, available_samples, prev_cache):
        """Update sequences and organisms counts from cached overall status."""
        idle_metrics = ("0", "0", prev_cache or {})

        if not overall_status:
            return idle_metrics

        try:
            main_dir = overall_status.get("_main_dir", "")
            available_samples = _resolve_samples(main_dir, available_samples)
            metric_sample = selected_dashboard_sample if selected_dashboard_sample else "All Samples"

            if metric_sample and metric_sample != "All Samples":
                sample_kraken_df = load_kraken_data(main_dir, metric_sample)
                sample_reads = int(sample_kraken_df["reads"].sum()) if not sample_kraken_df.empty else 0
                sequences_count = f"{sample_reads:,}"
                if not sample_kraken_df.empty:
                    org_df = sample_kraken_df[sample_kraken_df["rank"].isin(["S", "G"])]
                    org_df = org_df[org_df["taxid"] > 1]
                    organisms_count = str(len(org_df[org_df["reads"] >= 1]))
                else:
                    organisms_count = "0"
            else:
                sequences_count = f"{overall_status['total_reads']:,}"
                organisms_count = str(overall_status['organisms_detected'])

            try:
                cur_reads = int(sequences_count.replace(",", ""))
            except (ValueError, AttributeError):
                cur_reads = 0
            try:
                cur_organisms = int(organisms_count)
            except (ValueError, TypeError):
                cur_organisms = 0

            new_cache = {"reads": cur_reads, "organisms": cur_organisms}
            return sequences_count, organisms_count, new_cache

        except Exception as e:
            logger.error(f"Error updating dashboard metrics: {e}", exc_info=True)
            return "0", "0", prev_cache or {}

    # ================================================================
    # D3c: Sample table callback
    # ================================================================
    @app.callback(
        [
            Output("dashboard-sample-table", "rowData"),
            Output("dashboard-sample-count", "children"),
        ],
        [
            Input("dashboard-overall-status-cache", "data"),
        ],
    )
    def update_dashboard_sample_table(overall_status):
        """Update the dashboard sample table using cached samples data."""
        if not overall_status:
            return [], "0 samples"

        try:
            samples_data = overall_status.get("_samples_data", [])
            return samples_data, f"{len(samples_data)} samples"
        except Exception as e:
            logger.error(f"Error updating dashboard sample table: {e}", exc_info=True)
            return [], "0 samples"

    # ================================================================
    # D3d: Alerts panel callback (reads cached overall status)
    # ================================================================
    @app.callback(
        [
            Output("dashboard-alerts-panel", "children"),
            Output("dashboard-alerts-count", "children"),
            Output("dashboard-alerts-count", "color"),
        ],
        [
            Input("dashboard-overall-status-cache", "data"),
        ],
        [
            State("app-config", "data"),
            State("available-samples", "data"),
        ]
    )
    def update_dashboard_alerts(overall_status, config, available_samples):
        """Update the dashboard alerts panel using cached overall status."""
        if not overall_status:
            return _get_idle_alerts()

        try:
            main_dir = overall_status.get("_main_dir", "")

            samples_data = overall_status.get("_samples_data", [])
            alerts_data = _generate_alerts(overall_status, main_dir, config, samples_data)

            alerts_panel = create_alerts_list(alerts_data)
            alerts_badge_color = _get_alerts_badge_color(alerts_data)

            return alerts_panel, str(len(alerts_data)), alerts_badge_color
        except Exception as e:
            logger.error(f"Error updating dashboard alerts: {e}", exc_info=True)
            return _get_error_alerts(str(e))

    @app.callback(
        Output("selected-sample", "data", allow_duplicate=True),
        Input("dashboard-sample-table", "selectedRows"),
        prevent_initial_call=True
    )
    def handle_sample_selection(selected_rows: List[Dict]) -> str:
        """
        Handle sample selection from the dashboard AG Grid table.

        When a user clicks a sample row, update the selected sample
        so other tabs can show sample-specific data.

        Args:
            selected_rows: List of selected row data dicts from AG Grid

        Returns:
            Selected sample name
        """
        if not selected_rows:
            return no_update

        try:
            selected_sample = selected_rows[0]["sample"]
            logger.info(f"Dashboard: User selected sample {selected_sample}")
            return selected_sample
        except (IndexError, KeyError) as e:
            logger.error(f"Error handling sample selection: {e}")
            return no_update

    @app.callback(
        [
            Output("dashboard-pathogen-alert-container", "children"),
            Output("dashboard-pathogen-alert-container", "style")
        ],
        [Input("update-interval", "n_intervals")],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("available-samples", "data"),
        ],
        prevent_initial_call=False
    )
    def update_pathogen_alert_panel(
        n_intervals: int,
        config: Dict[str, Any],
        status: Dict[str, Any],
        available_samples: Optional[List[str]]
    ) -> Tuple[html.Div, Dict[str, str]]:
        """
        Update the pathogen alert panel with detected dangerous organisms.

        This callback checks for CDC Category A/B/C agents, WHO priority
        pathogens, and user-configured watchlist species.  Per-sample
        attribution data (which barcodes carry each pathogen) is built from
        individual per-sample Kraken2 reports and passed to the alert components.

        Args:
            n_intervals: Interval counter
            config: Application configuration
            status: Backend status
            available_samples: List of detected sample names

        Returns:
            Tuple of (alert_panel_children, container_style)
        """
        if should_skip_update("dashboard_pathogen_alert", debounce_ms=2000):
            raise PreventUpdate

        if not config:
            return html.Div(), {"display": "none"}

        visualization_mode = config.get("visualization_only", False)
        pipeline_running = status.get("running", False) if status else False
        pipeline_completed = status.get("completed", False) if status else False
        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")

        # Only check when we have data
        if not (visualization_mode or pipeline_running or pipeline_completed):
            if not (main_dir and os.path.isdir(main_dir)):
                return html.Div(), {"display": "none"}

        try:
            # Load aggregated Kraken2 data for pathogen detection
            kraken_df = load_kraken_data(main_dir, "All Samples")

            if kraken_df.empty:
                return html.Div(), {"display": "none"}

            # Extract species-level detections (vectorized)
            species_df = kraken_df[
                (kraken_df["rank"] == "S") &
                (kraken_df["reads"] >= 5)
            ]
            detected_organisms = _species_df_to_organisms(species_df)

            # Build per-sample attribution: taxid -> [{sample, reads, abundance, is_nc}]
            resolved_samples = _resolve_samples(main_dir, available_samples)
            taxid_to_samples = _load_per_sample_organisms(main_dir, resolved_samples)

            # Get only ENABLED watchlist entries for alerting
            watched_species = _get_active_watchlist_entries(config)

            # Create alert panel with per-sample attribution
            return _create_pathogen_alert_panel(
                detected_organisms, watched_species, config, taxid_to_samples
            )

        except Exception as e:
            logger.error(f"Error updating pathogen alert panel: {e}")
            return html.Div(), {"display": "none"}

    # Pattern-matching callbacks for pathogen alert buttons
    @app.callback(
        [
            Output("pathogen-report-modal", "is_open"),
            Output("pathogen-modal-name", "children"),
            Output("pathogen-modal-common-name", "children"),
            Output("pathogen-modal-category", "children"),
            Output("pathogen-modal-bsl", "children"),
            Output("pathogen-modal-reads", "children"),
            Output("pathogen-modal-abundance", "children"),
            Output("pathogen-modal-confidence", "children"),
            Output("pathogen-modal-taxid", "children"),
            Output("pathogen-modal-action", "children"),
            Output("pathogen-modal-action-alert", "color"),
            Output("pathogen-modal-notes", "children"),
            Output("pathogen-modal-ncbi-link", "href"),
            Output("pathogen-modal-threat-banner", "children"),
            Output("pathogen-report-data", "data")
        ],
        [
            Input({"type": "pathogen-view-report", "taxid": ALL}, "n_clicks"),
            Input("pathogen-modal-close", "n_clicks"),
            Input("pathogen-modal-acknowledge", "n_clicks"),
        ],
        [
            State("pathogen-report-modal", "is_open"),
            State("pathogen-report-data", "data"),
            State("app-config", "data"),
            State("sample-selector", "value"),
        ],
        prevent_initial_call=True
    )
    def handle_view_report(
        view_clicks: List[Optional[int]],
        close_clicks: Optional[int],
        ack_clicks: Optional[int],
        is_open: bool,
        report_data: dict,
        config: dict,
        selected_sample: str,
    ):
        """
        Handle 'View Report' button clicks on pathogen alerts.

        Opens a modal with detailed pathogen information from the database.
        Also handles modal close and acknowledge actions.
        """
        triggered = ctx.triggered_id

        # Handle close button
        if triggered == "pathogen-modal-close":
            return [False] + [no_update] * 14

        # Handle acknowledge button - close modal and log acknowledgment
        if triggered == "pathogen-modal-acknowledge":
            taxid = report_data.get("taxid", "unknown") if report_data else "unknown"
            name = report_data.get("name", f"TaxID {taxid}") if report_data else f"TaxID {taxid}"
            logger.warning(
                f"PATHOGEN ALERT ACKNOWLEDGED (modal): {name} (TaxID {taxid}) "
                f"at {datetime.now().isoformat()}"
            )
            return [False] + [no_update] * 14

        # Handle view report buttons
        if not view_clicks or not any(view_clicks):
            return [no_update] * 15

        if not isinstance(triggered, dict):
            return [no_update] * 15

        taxid = triggered.get("taxid", 0)

        # Look up actual read count and abundance from Kraken2 data
        from nanometa_live.core.utils.data_loaders import load_kraken_data
        organism_reads = "N/A"
        organism_abundance = "N/A"
        organism_name = None
        organism_rank = None
        try:
            main_dir = (config.get("results_output_directory", "") or config.get("main_dir", "")) if config else ""
            if main_dir:
                kraken_df = load_kraken_data(main_dir, selected_sample)
                if not kraken_df.empty and taxid:
                    match = kraken_df[kraken_df["taxid"] == int(taxid)]
                    if not match.empty:
                        row = match.iloc[0]
                        organism_reads = f"{int(row.get('reads', 0)):,}"
                        pct = row.get("%", 0)
                        organism_abundance = f"{pct:.1f}%"
                        organism_name = str(row.get("name", "")).strip()
                        organism_rank = str(row.get("rank", ""))
        except Exception as e:
            logger.debug(f"Kraken2 lookup for taxid {taxid}: {e}")

        # Get pathogen details - try multiple lookup strategies
        from nanometa_live.core.utils.pathogen_database import get_pathogen_by_taxid
        from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection

        pathogen = None
        ncbi_taxid = taxid  # May be NCBI or Kraken2 taxid

        # Strategy 1: Direct lookup by taxid (works if taxid is NCBI taxid)
        if taxid:
            pathogen = get_pathogen_by_taxid(taxid)

        # Strategy 2: If not found, try mapping Kraken2 taxid -> NCBI taxid
        if not pathogen and taxid:
            mapping_collection = get_mapping_collection()
            if mapping_collection:
                # Build reverse mapping: db_taxid -> ncbi_taxid
                for mapped_ncbi_taxid, mapping in mapping_collection.mappings.items():
                    if mapping.db_taxid == taxid:
                        # Found the mapping - try to look up by NCBI taxid
                        ncbi_taxid = mapped_ncbi_taxid
                        pathogen = get_pathogen_by_taxid(ncbi_taxid)
                        if pathogen:
                            logger.debug(f"Found pathogen via taxid mapping: Kraken2 {taxid} -> NCBI {ncbi_taxid}")
                            break

        # Strategy 3: Try WatchlistManager for custom entries
        if not pathogen and taxid:
            try:
                manager = get_watchlist_manager()
                # Check if it's in the active watchlist entries
                active_entries = manager.get_active_entries()
                # Try by NCBI taxid first
                if ncbi_taxid in active_entries:
                    entry = active_entries[ncbi_taxid]
                    # Create a pseudo-pathogen object from watchlist entry
                    from types import SimpleNamespace
                    pathogen = SimpleNamespace(
                        name=entry.name,
                        common_name=entry.common_name or "",
                        threat_level=entry.threat_level,
                        bsl=entry.bsl_level,
                        category=entry.category or "Watchlist",
                        notes=entry.notes or "",
                        action_required=entry.action_required or "Follow laboratory protocols"
                    )
                    logger.debug(f"Found organism in watchlist: {entry.name}")
            except Exception as e:
                logger.debug(f"Watchlist lookup failed: {e}")

        if not pathogen:
            # Show modal with actual Kraken2 data when available
            display_name = organism_name or f"TaxID: {taxid}"
            return [
                True,  # is_open
                display_name,  # name
                "Not in pathogen watchlist",  # common_name
                organism_rank or "Unknown",  # category
                "Unknown",  # bsl
                organism_reads,  # reads
                organism_abundance,  # abundance
                "HIGH" if organism_reads != "N/A" else "N/A",  # confidence
                str(taxid),  # taxid
                "Follow standard laboratory biosafety protocols",  # action
                "secondary",  # alert color
                "This organism is not in any active watchlist. Review classification results for context.",  # notes
                f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={ncbi_taxid}",  # ncbi link
                html.Div([
                    html.I(className="bi bi-info-circle me-2"),
                    "Not on watchlist"
                ], className="alert alert-secondary text-center py-2"),  # threat banner
                {"taxid": taxid, "ncbi_taxid": ncbi_taxid}  # store data
            ]

        # Determine threat level styling
        threat_level = pathogen.threat_level
        if hasattr(threat_level, 'value'):
            threat_level = threat_level.value
        threat_colors = {
            "critical": ("danger", "#8b0000", "bi-exclamation-octagon-fill"),
            "high": ("warning", "#dc3545", "bi-exclamation-triangle-fill"),
            "moderate": ("info", "#fd7e14", "bi-eye-fill"),
            "low": ("secondary", "#17a2b8", "bi-info-circle")
        }
        alert_color, banner_color, banner_icon = threat_colors.get(
            threat_level, ("secondary", "#6c757d", "bi-question-circle")
        )

        # Create threat banner icon element
        if banner_icon.startswith("bi-"):
            icon_el = html.I(className=f"bi {banner_icon} me-2", style={"fontSize": "20px"})
        else:
            icon_el = html.Span(banner_icon, className="me-2", style={"fontSize": "1.5em"})

        # Create threat banner
        threat_banner = html.Div([
            icon_el,
            html.Strong(f"{threat_level.upper()} THREAT LEVEL", style={"fontSize": "16px"})
        ], className=f"alert alert-{alert_color} text-center py-2 mb-0",
           style={"borderLeft": f"5px solid {banner_color}"})

        # BSL badge text
        bsl_val = pathogen.bsl
        if hasattr(bsl_val, 'value'):
            bsl_val = bsl_val.value
        bsl_text = f"BSL-{bsl_val}" if bsl_val else "BSL Unknown"

        # Confidence based on typical detection (placeholder - would be populated from actual data)
        confidence = "HIGH" if taxid else "UNKNOWN"

        return [
            True,  # is_open
            pathogen.name,  # name (scientific)
            pathogen.common_name or "No common name",  # common_name
            pathogen.category or "Uncategorized",  # category
            bsl_text,  # bsl
            organism_reads,  # reads
            organism_abundance,  # abundance
            confidence,  # confidence
            str(ncbi_taxid),  # taxid
            pathogen.action_required,  # action
            alert_color,  # alert color
            pathogen.notes or "No additional notes available.",  # notes
            f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={ncbi_taxid}",  # ncbi link
            threat_banner,  # threat banner
            {"taxid": taxid, "name": pathogen.name, "threat_level": threat_level}  # store data
        ]

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        Input({"type": "pathogen-acknowledge", "taxid": ALL}, "n_clicks"),
        prevent_initial_call=True
    )
    def handle_acknowledge_pathogen(n_clicks_list: List[Optional[int]]):
        """
        Handle 'Acknowledge' button clicks on critical pathogen alerts.

        Logs the acknowledgment for audit purposes.
        """
        if not n_clicks_list or not any(n_clicks_list):
            return no_update

        triggered_id = ctx.triggered_id
        if not triggered_id:
            return no_update

        taxid = triggered_id.get("taxid", 0)

        # Log the acknowledgment
        logger.warning(f"PATHOGEN ALERT ACKNOWLEDGED: TaxID {taxid} at {datetime.now().isoformat()}")

        # Get pathogen details for the notification
        from nanometa_live.core.utils.pathogen_database import get_pathogen_by_taxid
        pathogen = get_pathogen_by_taxid(taxid) if taxid else None
        pathogen_name = pathogen.name if pathogen else f"TaxID {taxid}"

        return {
            "message": f"Alert acknowledged for {pathogen_name}. This action has been logged for audit purposes.",
            "type": "success",
            "timestamp": datetime.now().isoformat()
        }

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
        Input({"type": "pathogen-dismiss", "taxid": ALL}, "n_clicks"),
        prevent_initial_call=True
    )
    def handle_dismiss_pathogen(n_clicks_list: List[Optional[int]]):
        """
        Handle 'Dismiss' button clicks on high-risk pathogen alerts.

        Allows dismissing alerts for pathogens that have been reviewed.
        """
        if not n_clicks_list or not any(n_clicks_list):
            return no_update

        triggered_id = ctx.triggered_id
        if not triggered_id:
            return no_update

        taxid = triggered_id.get("taxid", 0)

        # Log the dismissal
        logger.info(f"Pathogen alert dismissed: TaxID {taxid} at {datetime.now().isoformat()}")

        return {
            "message": f"Alert for TaxID {taxid} dismissed. The pathogen will still appear in classification results.",
            "type": "info",
            "timestamp": datetime.now().isoformat()
        }

    # ========================================================================
    # Removed: Active Watchlist Panel (watchlist section removed in redesign)
    # ========================================================================

    def update_dashboard_watchlist_panel(n_intervals, watchlist_state, config):  # noqa: not registered
        """
        Update the Active Watchlist panel on the Dashboard tab.

        Shows summary statistics and list of enabled watchlist entries
        grouped by threat level.
        """
        if get_trigger_type(ctx) == "interval":
            if should_skip_update("dashboard_watchlist_panel", debounce_ms=2000):
                raise PreventUpdate

        try:
            manager = get_watchlist_manager()

            # Load watchlist if not already loaded
            if not manager._loaded and config:
                manager.load_config(config)

            # Get statistics
            stats = manager.get_statistics()
            active_entries = manager.get_active_entries()
            taxonomy_mode = manager.get_taxonomy_indicator()

            # Count by threat level
            threat_counts = stats.get("by_threat_level", {})
            critical_count = threat_counts.get("critical", 0)
            high_count = threat_counts.get("high", 0)
            moderate_count = threat_counts.get("moderate", 0)
            low_count = threat_counts.get("low", 0)

            total_active = len(active_entries)

            # Build species count text
            species_text = f"{total_active} species" if total_active != 1 else "1 species"

            # Build entries list grouped by threat level
            entries_by_threat = {
                "critical": [],
                "high": [],
                "moderate": [],
                "low": []
            }

            for entry in active_entries.values():
                threat = entry.threat_level.value if entry.threat_level else "moderate"
                if threat in entries_by_threat:
                    entries_by_threat[threat].append(entry)

            # Create entry components
            entry_components = []

            threat_colors = {
                "critical": "danger",
                "high": "warning",
                "moderate": "info",
                "low": "secondary"
            }

            threat_icons = {
                "critical": "bi-exclamation-octagon-fill",
                "high": "bi-exclamation-triangle-fill",
                "moderate": "bi-info-circle-fill",
                "low": "bi-dash-circle"
            }

            for threat_level in ["critical", "high", "moderate", "low"]:
                entries = entries_by_threat[threat_level]
                if entries:
                    # Add section header
                    ti = threat_icons[threat_level]
                    if ti.startswith("bi-"):
                        icon_el = html.I(className=f"bi {ti} me-1 text-{threat_colors[threat_level]}")
                    else:
                        icon_el = html.Span(ti, className=f"me-1 text-{threat_colors[threat_level]}", style={"fontSize": "1.4em"})
                    entry_components.append(
                        html.Div([
                            icon_el,
                            html.Strong(f"{threat_level.capitalize()} ({len(entries)})")
                        ], className="mt-2 mb-1")
                    )

                    # Add entries
                    for entry in sorted(entries, key=lambda e: e.name):
                        entry_components.append(
                            html.Div([
                                html.Span(entry.name, className="me-2"),
                                html.Small(
                                    f"(alert at {entry.alert_threshold} matches)",
                                    className="text-muted"
                                )
                            ], className="ps-3 py-1 border-start border-2",
                            style={"borderColor": f"var(--bs-{threat_colors[threat_level]})!important"})
                        )

            # If no entries, show prominent activation prompt
            if not entry_components:
                entry_components = [
                    html.Div([
                        html.I(className="bi bi-exclamation-circle text-warning", style={"fontSize": "28px"}),
                        html.P(
                            "No watchlist activated",
                            className="fw-bold mt-2 mb-1"
                        ),
                        html.P(
                            "Pathogen screening requires an active watchlist.",
                            className="text-muted small mb-2"
                        ),
                        dbc.Button(
                            [html.I(className="bi bi-eye me-1"), "Go to Watchlist tab"],
                            id="dashboard-goto-watchlist-btn",
                            color="warning",
                            size="sm",
                            outline=True,
                        ),
                    ], className="text-center py-3")
                ]

            return (
                species_text,
                taxonomy_mode,
                f"{critical_count} Critical",
                f"{high_count} High",
                f"{moderate_count} Moderate",
                f"{low_count} Low",
                html.Div(entry_components)
            )

        except Exception as e:
            logger.error(f"Error updating dashboard watchlist panel: {e}")
            return (
                "0 species",
                "Auto",
                "0 Critical",
                "0 High",
                "0 Moderate",
                "0 Low",
                html.Div([
                    html.I(className="bi bi-exclamation-circle text-warning me-2"),
                    html.Span(f"Error loading watchlist: {str(e)}", className="text-muted small")
                ], className="text-center py-3")
            )

    @app.callback(
        [
            Output("dashboard-last-updated", "data"),
            Output("dashboard-last-updated-badge", "children")
        ],
        [Input("update-interval", "n_intervals")],
        [
            State("app-config", "data"),
            State("dashboard-last-updated", "data")
        ]
    )
    def update_data_freshness(n_intervals, config, last_updated):
        """
        Update data freshness timestamp and badge.

        Stores the current time when data loads successfully,
        and shows a stale warning when data age exceeds 2x the polling interval.
        """
        if should_skip_update("dashboard_data_freshness", debounce_ms=2000):
            raise PreventUpdate

        if not config:
            return None, LastUpdatedBadge(timestamp=None)

        now = datetime.now().isoformat()
        update_interval = config.get("update_interval_seconds", 30)
        stale_threshold = update_interval * 2

        # Check staleness against previous timestamp
        stale = False
        if last_updated:
            try:
                last_dt = datetime.fromisoformat(last_updated)
                age_seconds = (datetime.now() - last_dt).total_seconds()
                if age_seconds > stale_threshold:
                    stale = True
            except (ValueError, TypeError):
                pass

        return now, LastUpdatedBadge(timestamp=now, stale=stale)

    # ---- Export Results callbacks ----
    @app.callback(
        Output("report-export-modal", "is_open"),
        [Input("dashboard-export-btn", "n_clicks"),
         Input("export-cancel-btn", "n_clicks"),
         Input("export-generate-btn", "n_clicks")],
        State("report-export-modal", "is_open"),
        prevent_initial_call=True
    )
    def toggle_export_modal(open_clicks, cancel_clicks, gen_clicks, is_open):
        trigger = ctx.triggered_id
        if trigger == "dashboard-export-btn":
            return True
        if trigger == "export-cancel-btn":
            return False
        if trigger == "export-generate-btn":
            return False  # Close after generation starts
        return is_open

    @app.callback(
        Output("export-status-message", "children"),
        Input("export-generate-btn", "n_clicks"),
        [State("export-output-dir", "value"),
         State("export-include-raw", "value"),
         State("app-config", "data")],
        prevent_initial_call=True
    )
    def generate_export(n_clicks, output_dir, include_raw, config):
        if not n_clicks or not config:
            raise PreventUpdate

        if not output_dir or not output_dir.strip():
            return html.Div(
                "Please specify an output directory.",
                className="text-danger"
            )

        main_dir = config.get("results_output_directory", "") or config.get("main_dir", "")
        if not main_dir:
            return html.Div(
                "No results directory configured.",
                className="text-danger"
            )

        try:
            from nanometa_live.core.export.report_generator import ReportGenerator

            generator = ReportGenerator(main_dir, config)
            report_path = generator.generate(
                output_dir=output_dir.strip(),
                include_raw=include_raw,
            )
            return html.Div([
                html.I(className="bi bi-check-circle-fill text-success me-2"),
                f"Report exported to: {report_path}"
            ], className="text-success mt-2")
        except Exception as e:
            logger.error("Export failed: %s", e)
            return html.Div(
                f"Export failed: {e}",
                className="text-danger mt-2"
            )

    # ========================================================================
    # Pathogen Modal Print (clientside)
    # ========================================================================

    app.clientside_callback(
        """
        function(n_clicks) {
            if (n_clicks) {
                window.print();
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("pathogen-report-data", "data", allow_duplicate=True),
        Input("pathogen-modal-print", "n_clicks"),
        prevent_initial_call=True
    )

    # ========================================================================
    # Dashboard Refresh Button
    # ========================================================================

    @app.callback(
        Output("update-interval", "n_intervals", allow_duplicate=True),
        Input("dashboard-refresh-btn", "n_clicks"),
        State("update-interval", "n_intervals"),
        prevent_initial_call=True,
    )
    def manual_dashboard_refresh(n_clicks, current_n):
        """Trigger an immediate data refresh by incrementing the interval counter."""
        if not n_clicks:
            return no_update
        return (current_n or 0) + 1

    # ========================================================================
    # Dashboard Help Modal
    # ========================================================================

    @app.callback(
        Output("dashboard-help-modal", "is_open"),
        [
            Input("dashboard-help-btn", "n_clicks"),
            Input("dashboard-help-close", "n_clicks"),
        ],
        State("dashboard-help-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_help_modal(open_clicks, close_clicks, is_open):
        """Open or close the dashboard help modal."""
        if ctx.triggered_id in ("dashboard-help-btn", "dashboard-help-close"):
            return not is_open
        return is_open

    # Pre-flight checklist removed — readiness checks are in the top bar


# Helper functions

def _count_input_files(nanopore_dir: str) -> int:
    """
    Count input FASTQ files in the nanopore output directory.

    Supports both flat directories and barcoded subdirectories.

    Args:
        nanopore_dir: Path to nanopore output directory

    Returns:
        Total count of FASTQ files (.fastq, .fastq.gz, .fq, .fq.gz)
    """
    if not nanopore_dir or not os.path.exists(nanopore_dir):
        return 0

    count = 0
    extensions = ('.fastq', '.fastq.gz', '.fq', '.fq.gz')

    # Check for files in main directory
    for f in os.listdir(nanopore_dir):
        if f.lower().endswith(extensions):
            count += 1

    # Also check for barcoded subdirectories (barcode01, barcode02, etc.)
    for subdir in os.listdir(nanopore_dir):
        subdir_path = os.path.join(nanopore_dir, subdir)
        if os.path.isdir(subdir_path) and subdir.startswith('barcode'):
            for f in os.listdir(subdir_path):
                if f.lower().endswith(extensions):
                    count += 1

    return count


def _make_banner_content(
    icon_name: str,
    icon_color: str,
    heading: str,
    sub: str,
    run_state: str,
    time_elapsed: str,
    sub_color: str = "inherit",
    show_icon_mobile: bool = False,
    last_updated_str: Optional[str] = None,
    icon_extra_class: str = "",
) -> dbc.Row:
    """
    Build the inner content for the Zone 1 clinical verdict banner.

    Args:
        icon_name: Bootstrap icon name (without 'bi-' prefix, e.g. 'shield-check')
        icon_color: CSS hex color for the icon
        heading: H3 verdict text
        sub: Subtitle text below the heading
        run_state: Run state badge text (ACTIVE/STANDBY/COMPLETE)
        time_elapsed: Formatted elapsed time string
        sub_color: Explicit text color for subtitle (WCAG AA compliance)
        show_icon_mobile: If True, icon is always visible; if False, hidden below 768px
        last_updated_str: Formatted "Last updated HH:MM:SS" string for right column
        icon_extra_class: Extra CSS class(es) appended to icon element (e.g. 'spin')

    Returns:
        dbc.Row with left verdict column and right run-state column
    """
    run_state_color = (
        "success" if run_state == "ACTIVE"
        else "info" if run_state == "COMPLETE"
        else "secondary"
    )
    # Icon visibility: ACTION REQUIRED always shows; others hide on mobile
    icon_visibility = "" if show_icon_mobile else "d-none d-sm-inline"
    icon_class = f"bi bi-{icon_name} {icon_visibility} {icon_extra_class}".strip()

    right_children = [
        dbc.Badge(run_state, color=run_state_color,
                  style={"borderRadius": "8px"}),
        html.Div(time_elapsed, className="small text-muted mt-1"),
    ]
    if last_updated_str:
        right_children.append(
            html.Div(last_updated_str,
                     style={"fontSize": "12px", "color": "#6c757d", "marginTop": "2px"})
        )

    return dbc.Row([
        dbc.Col([
            html.Div([
                html.I(
                    className=icon_class,
                    style={"fontSize": "40px", "color": icon_color, "flexShrink": "0"}
                ),
                html.Div([
                    html.H3(heading, className="dashboard-verdict-h3 mb-0"),
                    html.P(sub, className="dashboard-verdict-sub mb-0",
                           style={"color": sub_color})
                ], className="ms-0 ms-sm-3")
            ], className="d-flex align-items-center")
        ], md=9),
        dbc.Col([
            html.Div(right_children, className="text-end")
        ], md=3, className="d-flex align-items-center justify-content-end")
    ], className="align-items-center g-0")


def _verdict_banner_style(bg_color: str, border_color: str) -> dict:
    """
    Return inline style dict for the Zone 1 verdict banner container.

    Args:
        bg_color: Background color hex
        border_color: Border color hex

    Returns:
        CSS style dict
    """
    return {
        "backgroundColor": bg_color,
        "border": f"6px solid {border_color}",
        "borderRadius": "8px",
        "padding": "24px 32px",
        "minHeight": "120px",
    }


def _get_idle_alerts() -> Tuple:
    """Return idle state for the alerts callback (D3d, 3 outputs)."""
    empty_alerts = html.Div([
        html.I(className="bi bi-check-circle text-success", style={"fontSize": "48px"}),
        html.H5("No Active Alerts", className="mt-3 mb-2"),
        html.P("System is operating normally", className="text-muted mb-0")
    ], className="text-center py-4")
    return (empty_alerts, "0", "secondary")


def _get_error_alerts(error_msg: str) -> Tuple:
    """Return error state for the alerts callback (D3d, 3 outputs)."""
    error_alert = [{
        "message": f"Error loading dashboard data: {error_msg}",
        "severity": "danger",
        "timestamp": "Just now"
    }]
    return (create_alerts_list(error_alert), "1", "danger")


def _calculate_overall_status(
    main_dir: str,
    config: Dict[str, Any],
    available_samples: List[str],
    pipeline_running: bool = False
) -> Dict[str, Any]:
    """
    Calculate overall analysis status from available data.

    Args:
        main_dir: Main analysis directory
        config: Application configuration
        available_samples: List of sample names
        pipeline_running: Whether the pipeline is actively running

    Returns:
        Dict with overall status metrics
    """
    visualization_only = config.get("visualization_only", False)

    # Filter out "All Samples" pseudo-sample
    real_samples = [s for s in available_samples if s != "All Samples"]
    total_samples = len(real_samples)

    # Load Kraken data for all samples (with safe error handling)
    kraken_df = safe_load_kraken_data(main_dir, "All Samples")

    # Calculate metrics
    total_reads = int(kraken_df["reads"].sum()) if not kraken_df.empty else 0

    # Estimate quality score from data (simplified)
    quality_score = _estimate_quality_score(main_dir, kraken_df)

    # Count organisms (species + genus level, >= 1 read, matching Organisms tab)
    organisms_detected = 0
    if not kraken_df.empty:
        org_df = kraken_df[kraken_df["rank"].isin(["S", "G"])]
        org_df = org_df[org_df["taxid"] > 1]
        organisms_detected = len(org_df[org_df["reads"] >= 1])

    # Determine overall status
    if visualization_only and not pipeline_running:
        overall_status = "viewing"
    elif pipeline_running and total_reads == 0:
        overall_status = "starting"  # Pipeline running but no data processed yet
    elif quality_score is not None and quality_score < 60:
        overall_status = "warning"
    elif organisms_detected > 100:
        overall_status = "warning"  # Too many species might indicate contamination
    else:
        overall_status = "success"

    # Count samples processed (have Kraken output)
    samples_processed = _count_processed_samples(main_dir, real_samples)

    return {
        "status": overall_status,
        "total_reads": total_reads,
        "quality_score": quality_score,
        "organisms_detected": organisms_detected,
        "active_alerts": 0,  # Calculated later in _generate_alerts
        "samples_processed": samples_processed,
        "total_samples": total_samples
    }


def _estimate_quality_score(main_dir: str, kraken_df: pd.DataFrame) -> Optional[int]:
    """
    Estimate a simplified 0-100 quality score for nanopore data.

    Uses appropriate scaling for nanopore sequencing where Q10-15 is typical.
    Prioritizes seqkit Q20% metric when available as it's more meaningful.

    Args:
        main_dir: Main analysis directory
        kraken_df: Kraken classification dataframe

    Returns:
        Quality score 0-100, or None if cannot be calculated
    """
    try:
        score = None

        # Try seqkit first - Q20% is a meaningful quality metric
        qc_stats = get_qc_stats(main_dir)
        if qc_stats.get('source') == 'seqkit':
            q20_pct = qc_stats.get('q20_percent', 0)
            if q20_pct > 0:
                # Q20% directly maps to quality score (66% Q20 = 66 score)
                score = int(q20_pct)
                logger.debug(f"Quality score from seqkit Q20%: {score}")

        # Fallback to NanoPlot if seqkit not available
        if score is None:
            nanoplot_stats = load_nanoplot_stats(main_dir)
            if nanoplot_stats.get('mean_read_quality', 0) > 0:
                # For nanopore, Q10 is passing, Q15 is good, Q20+ is excellent
                # Scale: Q10 = 70%, Q15 = 85%, Q20 = 100%
                q_score = nanoplot_stats['mean_read_quality']
                if q_score >= 20:
                    score = 100
                elif q_score >= 15:
                    score = 85 + int((q_score - 15) * 3)  # 85-100 for Q15-20
                elif q_score >= 10:
                    score = 70 + int((q_score - 10) * 3)  # 70-85 for Q10-15
                else:
                    score = max(30, int(q_score * 7))  # Below Q10 is concerning
                logger.debug(f"Quality score from NanoPlot Q{q_score}: {score}")

        # Still no score? Use read length as proxy
        if score is None:
            if qc_stats.get('source') != 'none':
                avg_len = qc_stats.get('avg_read_length', 0)
                if avg_len > 3000:
                    score = 85
                elif avg_len > 2000:
                    score = 75
                elif avg_len > 1000:
                    score = 65
                else:
                    score = 50

        if score is None:
            return None

        # Adjust based on N50 (bonus for good read lengths)
        nanoplot_stats = load_nanoplot_stats(main_dir)
        n50 = nanoplot_stats.get('read_length_n50', 0)
        if n50 > 5000:
            score = min(100, score + 5)  # Bonus for long reads
        elif n50 < 1000:
            score -= 10  # Penalty for very short reads

        # Minor adjustment for classification rate (but don't over-penalize)
        if not kraken_df.empty and "reads" in kraken_df.columns:
            total_reads = kraken_df["reads"].sum()
            if total_reads > 0:
                unclassified = kraken_df[kraken_df["name"].str.contains("unclassified", case=False, na=False)]
                if not unclassified.empty:
                    unclassified_pct = (unclassified["reads"].sum() / total_reads) * 100
                    # Only penalize extremely high unclassified rates
                    if unclassified_pct > 70:
                        score -= 10
                    elif unclassified_pct > 50:
                        score -= 5

        return max(0, min(100, score))

    except Exception as e:
        logger.warning(f"Error estimating quality score: {e}")
        return None


def _count_processed_samples(main_dir: str, samples: List[str]) -> int:
    """Count how many samples have been processed (have Kraken output)."""
    kraken_dir = os.path.join(main_dir, "kraken2")
    if not os.path.exists(kraken_dir):
        return 0

    count = 0
    for sample in samples:
        # Check for sample-specific Kraken output
        sample_kraken = glob.glob(os.path.join(kraken_dir, f"*{sample}*.txt"))
        if sample_kraken:
            count += 1

    return count


def _generate_status_display(status: str) -> Tuple[Dict, str, str, str, str, str, str]:
    """
    Generate status indicator style, icon, text, subtitle, label text, label icon, and CSS class.

    Args:
        status: "starting", "success", "viewing", "warning", or "danger"

    Returns:
        Tuple of (style_dict, icon_class, status_text, subtitle_text,
                  label_text, label_icon, css_class)
    """
    status_config = {
        "starting": {
            "color": "#0d6efd",  # Blue
            "icon": "bi bi-hourglass-split",
            "text": "ACTIVE - Waiting for first results",
            "subtitle": "Pipeline is running, waiting for first results...",
            "label": "ACTIVE",
            "label_icon": "bi bi-hourglass-split ms-1",
            "css_class": "status-running"
        },
        "success": {
            "color": "#28a745",  # Green
            "icon": "bi bi-check-circle",
            "text": "ACTIVE - Analyzing samples",
            "subtitle": "All systems operating normally",
            "label": "ACTIVE",
            "label_icon": "bi bi-check-circle-fill ms-1",
            "css_class": "status-good"
        },
        "viewing": {
            "color": "#17a2b8",  # Teal/Info
            "icon": "bi bi-eye",
            "text": "COMPLETE - Results available",
            "subtitle": "Viewing existing results",
            "label": "COMPLETE",
            "label_icon": "bi bi-eye-fill ms-1",
            "css_class": "status-good"
        },
        "warning": {
            "color": "#ffc107",  # Amber
            "icon": "bi bi-exclamation-circle",
            "text": "ACTIVE - Review alerts below",
            "subtitle": "Review alerts below",
            "label": "ATTENTION",
            "label_icon": "bi bi-exclamation-triangle-fill ms-1",
            "css_class": "status-warning"
        },
        "danger": {
            "color": "#dc3545",  # Red
            "icon": "bi bi-x-circle",
            "text": "ERROR - Check setup",
            "subtitle": "Immediate action required - check settings",
            "label": "ERROR",
            "label_icon": "bi bi-x-circle-fill ms-1",
            "css_class": "status-danger"
        }
    }

    config = status_config.get(status, status_config["success"])

    # Background color is handled by CSS classes (status-good, status-warning, etc.)
    # Only set layout properties here to avoid inline vs CSS conflicts
    style = {
        "width": "80px",
        "height": "80px",
        "borderRadius": "50%",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
    }

    return (
        style,
        config["icon"],
        config["text"],
        config["subtitle"],
        config["label"],
        config["label_icon"],
        config["css_class"]
    )


def _format_time_elapsed(start_time: Optional[str]) -> str:
    """
    Format elapsed time since analysis start.

    Args:
        start_time: ISO format timestamp string

    Returns:
        Formatted time string (HH:MM:SS)
    """
    if not start_time:
        return "00:00:00"

    try:
        start_dt = datetime.fromisoformat(start_time)
        elapsed = datetime.now() - start_dt
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "00:00:00"


def _collect_samples_data(main_dir: str, available_samples: List[str]) -> List[Dict[str, Any]]:
    """
    Collect detailed sample data from analysis results.

    Args:
        main_dir: Main data directory
        available_samples: List of available sample names

    Returns:
        List of dictionaries containing sample information with enhanced columns
    """
    # Filter out "All Samples"
    real_samples = [s for s in available_samples if s != "All Samples"]

    if not real_samples:
        return []

    samples_data = []
    for sample in real_samples:
        try:
            # Load sample-specific Kraken data
            kraken_df = load_kraken_data(main_dir, sample)

            # Initialize default values
            reads = 0
            organisms = 0
            quality = "Pending"
            status = "Processing"
            total_bases = 0
            mean_q = 0.0
            n50 = 0
            class_rate = 0.0
            pass_rate = 100.0

            if not kraken_df.empty:
                # Calculate sample metrics from Kraken
                reads = int(kraken_df["reads"].sum())
                org_df = kraken_df[kraken_df["rank"].isin(["S", "G"])]
                org_df = org_df[org_df["taxid"] > 1]
                organisms = len(org_df[org_df["reads"] >= 1])

                # Classification rate calculation
                unclassified = kraken_df[kraken_df["name"].str.contains("unclassified", case=False, na=False)]
                if not unclassified.empty and reads > 0:
                    unclassified_pct = (unclassified["reads"].sum() / reads) * 100
                    class_rate = 100.0 - unclassified_pct

                    if unclassified_pct < 30:
                        quality = "Good"
                        status = "Complete"
                    elif unclassified_pct < 50:
                        quality = "Fair"
                        status = "Needs Review"
                    else:
                        quality = "Poor"
                        status = "Issue Detected"
                else:
                    quality = "Excellent"
                    status = "Complete"
                    class_rate = 100.0

            # Try seqkit stats FIRST (per-sample data from chopper QC)
            seqkit_df = load_seqkit_stats(main_dir, sample)
            if not seqkit_df.empty:
                # seqkit provides per-sample stats: sum_len, N50, AvgQual
                total_bases = int(seqkit_df['sum_len'].sum()) if 'sum_len' in seqkit_df.columns else 0
                n50 = int(seqkit_df['N50'].iloc[0]) if 'N50' in seqkit_df.columns and len(seqkit_df) > 0 else 0
                mean_q = float(seqkit_df['AvgQual'].iloc[0]) if 'AvgQual' in seqkit_df.columns and len(seqkit_df) > 0 else 0.0
                logger.debug(f"Sample {sample}: Using seqkit stats - bases={total_bases}, n50={n50}, mean_q={mean_q}")
            else:
                # Fall back to NanoPlot stats (may be per-sample or aggregated)
                nanoplot_stats = load_nanoplot_stats(main_dir, sample) if sample else {}
                if nanoplot_stats and nanoplot_stats.get("number_of_reads", 0) > 0:
                    total_bases = nanoplot_stats.get("total_bases", 0)
                    mean_q = nanoplot_stats.get("mean_read_quality", 0.0)
                    n50 = nanoplot_stats.get("read_length_n50", 0)
                    logger.debug(f"Sample {sample}: Using NanoPlot stats - bases={total_bases}, n50={n50}, mean_q={mean_q}")

            # Format bases for display
            if total_bases >= 1_000_000_000:
                bases_str = f"{total_bases / 1_000_000_000:.1f} Gb"
            elif total_bases >= 1_000_000:
                bases_str = f"{total_bases / 1_000_000:.1f} Mb"
            elif total_bases >= 1_000:
                bases_str = f"{total_bases / 1_000:.1f} kb"
            elif total_bases > 0:
                bases_str = f"{total_bases} bp"
            else:
                bases_str = "--"

            # Format N50 for display
            if n50 >= 1_000:
                n50_str = f"{n50 / 1_000:.1f}k"
            elif n50 > 0:
                n50_str = str(n50)
            else:
                n50_str = "--"

            samples_data.append({
                "sample": sample,
                "status": status,
                "quality": quality,
                "organisms": organisms,
                "reads": f"{reads:,}",
                "bases": bases_str,
                "mean_q": f"{mean_q:.1f}" if mean_q > 0 else "--",
                "n50": n50_str,
                "class_rate": f"{class_rate:.1f}%" if class_rate > 0 else "--",
                "pass_rate": f"{pass_rate:.1f}%",
            })

        except Exception as e:
            logger.error(f"Error processing sample {sample}: {e}")
            samples_data.append({
                "sample": sample,
                "status": "Error",
                "quality": "Error",
                "organisms": 0,
                "reads": "0",
                "bases": "--",
                "mean_q": "--",
                "n50": "--",
                "class_rate": "--",
                "pass_rate": "--",
            })

    return samples_data


def _generate_alerts(
    overall_status: Dict[str, Any],
    main_dir: str,
    config: Dict[str, Any],
    samples_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Generate alerts using the AlertEngine.

    Args:
        overall_status: Overall system status
        main_dir: Main data directory
        config: Application configuration
        samples_data: List of sample information

    Returns:
        List of alert dictionaries
    """
    # Get global alert engine instance
    alert_engine = get_alert_engine()

    # Prepare status dictionary for alert engine
    status = {
        "running": overall_status.get("running", False),
        "completed": overall_status.get("completed", False),
        "error_count": overall_status.get("error_count", 0),
        "pending_files": overall_status.get("pending_files", 0),
        "processed_files": overall_status.get("processed_files", 0)
    }

    # Prepare samples list for alert engine
    samples = []
    for sample in samples_data:
        # Convert sample data to format expected by alert engine
        reads_str = sample.get("reads", "0")
        reads = int(reads_str.replace(",", "")) if isinstance(reads_str, str) else reads_str

        # Estimate pass rate from quality label (e.g. "Good", "Fair")
        quality = sample.get("quality", "--")
        if "Excellent" in quality:
            pass_rate = 95
        elif "Good" in quality:
            pass_rate = 80
        elif "Fair" in quality:
            pass_rate = 65
        elif "Poor" in quality:
            pass_rate = 40
        else:
            pass_rate = 100  # Unknown, assume ok

        samples.append({
            "name": sample.get("sample", "Unknown"),
            "reads": reads,
            "pass_rate": pass_rate,
            "status": sample.get("status", "unknown")
        })

    # Prepare QC stats - use actual classification data from Kraken2
    # instead of the crude heuristic _estimate_classified_rate
    actual_classified_rate = 0.0
    try:
        kraken_df = load_kraken_data(main_dir, "All Samples")
        if not kraken_df.empty:
            classified_reads, unclassified_reads, _ = get_classification_stats(kraken_df)
            total_kr = classified_reads + unclassified_reads
            if total_kr > 0:
                actual_classified_rate = (classified_reads / total_kr) * 100
    except Exception:
        actual_classified_rate = _estimate_classified_rate(overall_status.get("organisms_detected", 0))

    qc_stats = {
        "total_reads": overall_status.get("total_reads", 0),
        "pass_rate": _estimate_pass_rate_from_quality(overall_status.get("quality_score")),
        "classified_rate": actual_classified_rate
    }

    # Load detected organisms for pathogen checking
    detected_organisms = []
    # Get only ENABLED watchlist entries for alerting
    species_of_interest = _get_active_watchlist_entries(config)

    try:
        kraken_df = load_kraken_data(main_dir, "All Samples")
        if not kraken_df.empty:
            # Filter to species level with meaningful read counts (vectorized)
            species_df = kraken_df[
                (kraken_df["rank"] == "S") &
                (kraken_df["reads"] >= 5)
            ]
            detected_organisms = _species_df_to_organisms(species_df)
    except Exception as e:
        logger.error(f"Error loading organisms for pathogen check: {e}")

    # Generate alerts using alert engine (now includes pathogen detection)
    alerts = alert_engine.generate_alerts(
        status,
        samples,
        qc_stats,
        detected_organisms=detected_organisms,
        watched_species=species_of_interest
    )

    return alerts


def _estimate_pass_rate_from_quality(quality_score: Optional[int]) -> float:
    """
    Map quality score to pass rate for alerts.

    The quality_score is now already a meaningful 0-100 value based on
    nanopore-appropriate metrics (Q20% from seqkit or scaled Q-score).

    Args:
        quality_score: Quality score from _estimate_quality_score (0-100)

    Returns:
        Pass rate percentage for alert thresholds
    """
    if quality_score is None:
        return 100.0
    # Quality score is already a 0-100 value, use directly
    return float(max(0, min(100, quality_score)))


def _estimate_classified_rate(organisms: int) -> float:
    """Estimate classification rate from organism count."""
    if organisms == 0:
        return 0.0
    # Rough heuristic: more organisms = better classification
    # This is simplified - real calculation needs actual classified/unclassified counts
    return min(100, 30 + (organisms * 0.5))


def _get_alerts_badge_color(alerts_data: List[Dict[str, Any]]) -> str:
    """Determine badge color based on highest alert severity."""
    if not alerts_data:
        return "secondary"

    severities = [alert.get("severity", "info") for alert in alerts_data]

    if "critical" in severities or "danger" in severities:
        return "danger"
    elif "warning" in severities:
        return "warning"
    elif "info" in severities:
        return "info"
    else:
        return "success"


def _create_pathogen_alert_panel(
    detected_organisms: List[Dict[str, Any]],
    watched_species: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
    taxid_to_samples: Optional[Dict[int, List[Dict[str, Any]]]] = None
) -> Tuple[html.Div, Dict[str, str]]:
    """
    Create pathogen alert panel based on detected dangerous organisms.

    Args:
        detected_organisms: List of organisms from Kraken2 classification
        watched_species: Optional user-configured watchlist (legacy, kept for compatibility)
        config: Application configuration dict (used for taxid mapping)
        taxid_to_samples: Per-taxid sample attribution dict built by
            _load_per_sample_organisms (keyed by Kraken2 db taxid)

    Returns:
        Tuple of (alert_panel_component, container_style)
    """
    if not detected_organisms:
        return html.Div(), {"display": "none"}

    taxid_to_samples = taxid_to_samples or {}

    try:
        # Check for dangerous pathogens using proper taxid mapping
        # This handles GTDB databases where Kraken2 taxids differ from NCBI taxids
        dangerous_detections = _check_pathogens_with_mapping(detected_organisms, config)

        if not dangerous_detections:
            return html.Div(), {"display": "none"}

        # Build alert components
        alert_components = []
        watch_components = []
        critical_count = 0
        high_count = 0
        watch_count = 0

        for detection in dangerous_detections:
            threat_level = detection.get("threat_level", "moderate")
            pathogen_name = detection.get("name", "Unknown organism")
            common_name = detection.get("common_name", "")
            reads = detection.get("reads", 0)
            abundance = detection.get("abundance", 0.0)
            action = detection.get("action_required", "Follow biosafety protocols")
            taxid = detection.get("taxid")

            # Resolve per-sample attribution: prefer the Kraken2 db taxid used during
            # detection, fall back to the NCBI taxid stored on the watchlist entry.
            kraken_taxid = detection.get("detected_taxid") or taxid
            samples_for_detection = taxid_to_samples.get(kraken_taxid, [])
            if not samples_for_detection and kraken_taxid != taxid:
                samples_for_detection = taxid_to_samples.get(taxid, [])

            if threat_level == "critical":
                critical_count += 1
                alert_components.append(
                    CriticalPathogenAlert(
                        pathogen_name=pathogen_name,
                        common_name=common_name,
                        read_count=reads,
                        abundance_pct=abundance,
                        confidence="HIGH" if reads >= 100 else "MODERATE",
                        taxid=taxid,
                        recommendation=action,
                        samples=samples_for_detection
                    )
                )
            elif threat_level in ["high", "high_risk"]:
                high_count += 1
                alert_components.append(
                    HighRiskPathogenAlert(
                        pathogen_name=pathogen_name,
                        common_name=common_name,
                        read_count=reads,
                        abundance_pct=abundance,
                        taxid=taxid,
                        recommendation=action,
                        samples=samples_for_detection
                    )
                )
            else:
                # Moderate / watched species
                watch_count += 1
                watch_components.append(
                    WatchedSpeciesAlert(
                        pathogen_name=pathogen_name,
                        read_count=reads,
                        abundance_pct=abundance,
                        taxid=taxid,
                        samples=samples_for_detection
                    )
                )

        if not alert_components and not watch_components:
            return html.Div(), {"display": "none"}

        # Create summary header if multiple threats
        total_count = critical_count + high_count + watch_count
        header = None
        if total_count > 1:
            header = html.Div([
                html.H4([
                    html.I(className="bi bi-exclamation-triangle-fill me-2"),
                    f"{total_count} WATCHED ORGANISMS DETECTED"
                ], className="text-danger mb-0 fw-bold")
            ], className="mb-3")

        # Add watched species section with header if present
        if watch_components:
            alert_components.append(
                html.Div([
                    html.H6([
                        html.I(className="bi bi-eye me-2"),
                        f"Watched Species ({watch_count})"
                    ], className="text-muted mb-2 mt-3")
                ])
            )
            alert_components.extend(watch_components)

        # Combine into panel
        panel = html.Div([
            header,
            *alert_components
        ] if header else alert_components)

        return panel, {"display": "block"}

    except Exception as e:
        logger.error(f"Error creating pathogen alert panel: {e}")
        return html.Div(), {"display": "none"}
