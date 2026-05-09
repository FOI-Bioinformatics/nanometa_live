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

from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.qc_loaders import (
    get_qc_stats,
    load_nanoplot_stats,
    load_seqkit_stats,
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
from nanometa_live.app.utils.throughput import (
    BUFFER_LIMIT,
    append_tick,
    classify_state,
    compute_rates,
    format_age_seconds,
    last_nonzero_delta_ts,
)
from nanometa_live.app.layouts.dashboard_layout import create_alerts_list
from nanometa_live.app.components.modern_components import (
    LastUpdatedBadge,
)
from nanometa_live.app.components.pathogen_alert import (
    CriticalPathogenAlert,
    HighRiskPathogenAlert,
    WatchedSpeciesAlert,
)
from nanometa_live.app.tabs.dashboard_helpers import (
    _species_df_to_organisms,
    _load_per_sample_organisms,
    _get_active_watchlist_entries,
    _check_pathogens_with_mapping,
    _count_input_files,
    _make_banner_content,
    _verdict_banner_style,
    _get_idle_alerts,
    _get_error_alerts,
    _calculate_overall_status,
    _estimate_quality_score,
    _count_processed_samples,
    _generate_status_display,
    _format_time_elapsed,
    _collect_samples_data,
    _generate_alerts,
    _estimate_pass_rate_from_quality,
    _estimate_classified_rate,
    _get_alerts_badge_color,
    _create_pathogen_alert_panel,
)

logger = logging.getLogger(__name__)
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
            Input("results-fingerprint", "data"),
            Input("update-interval", "n_intervals"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("available-samples", "data"),
        ]
    )
    def compute_overall_status_cache(_fingerprint, _n_intervals, config, status, available_samples):
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
            Input("results-fingerprint", "data"),
            Input("watchlist-tab-state", "data"),
            Input("update-interval", "n_intervals"),
        ],
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("dashboard-overall-status-cache", "data"),
            State("validation-data-store", "data"),
            State("available-samples", "data"),
        ]
    )
    def update_verdict_banner(_fingerprint, watchlist_state, _n_intervals,
                              config, status, overall_status, validation_data,
                              available_samples):
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
                            # n_found counts only entries above each
                            # pathogen's alert_threshold. The Organisms
                            # tab lists every watchlist hit (any reads)
                            # without that gate, so the two counters
                            # legitimately differ. The wording below
                            # makes the threshold gate explicit.
                            action_sub = (
                                f"{n_found} of {n_watched} watched pathogens above alert threshold"
                            )
                            if not validation_has_results:
                                action_sub += " — pending confirmatory validation"

                            # Per-sample attribution for the banner subhead
                            # (closes P0-T02 from
                            # docs/audit-2026-04-28-throughput-ux.md).
                            # The per-sample IO is shared via the loader
                            # cache + per-key parse lock, so this adds
                            # minimal cost on top of the main aggregation.
                            triggering_samples: List[str] = []
                            total_real_samples = 0
                            try:
                                resolved_samples = _resolve_samples(
                                    main_dir, available_samples or []
                                )
                                total_real_samples = len(
                                    [s for s in resolved_samples
                                     if s != "All Samples"]
                                )
                                taxid_to_samples = _load_per_sample_organisms(
                                    main_dir, resolved_samples
                                )
                                # Union the samples that triggered any critical
                                # or high-risk pathogen, preserving descending-
                                # by-reads order via a stable accumulator.
                                seen = set()
                                for d in critical + high_risk:
                                    taxid = d.get("taxid") or d.get("kraken_taxid")
                                    if taxid is None:
                                        continue
                                    for entry in taxid_to_samples.get(int(taxid), []):
                                        name = entry.get("sample")
                                        if name and name not in seen:
                                            seen.add(name)
                                            triggering_samples.append(name)
                            except Exception as exc:
                                logger.warning(
                                    "Verdict-banner attribution unavailable: %s",
                                    exc,
                                    exc_info=True,
                                )

                            return (
                                _make_banner_content(
                                    "exclamation-octagon-fill", "#8b0000",
                                    "ACTION REQUIRED",
                                    action_sub,
                                    run_state, time_elapsed,
                                    sub_color="#721c24",
                                    show_icon_mobile=True,
                                    last_updated_str=last_updated_str,
                                    triggering_samples=triggering_samples or None,
                                    total_sample_count=total_real_samples or None,
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
                            f"0 of {n_watched} watched pathogens above alert threshold",
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
        Input("results-fingerprint", "data"),
        State("app-config", "data"),
        State("backend-status", "data"),
    )
    def update_quality_card(_fingerprint, config, status):
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
                # Same root.cumul_reads + unclassified accounting as the
                # All-Samples branch; sum(reads) misses anything parked
                # at root level (degenerate small-input case).
                sample_classified, sample_unclassified, _ = get_classification_stats(
                    sample_kraken_df
                )
                sample_reads = sample_classified + sample_unclassified
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
        Input("results-fingerprint", "data"),
        [
            State("app-config", "data"),
            State("backend-status", "data"),
            State("available-samples", "data"),
        ],
        prevent_initial_call=False
    )
    def update_pathogen_alert_panel(
        _fingerprint: Dict[str, Any],
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

            # Create alert panel with per-sample attribution +
            # validation badges. main_dir lets the panel load
            # validation_results.json so each card can show whether the
            # detection has been validated and at what confidence.
            return _create_pathogen_alert_panel(
                detected_organisms, watched_species, config, taxid_to_samples,
                main_dir=main_dir,
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
        from nanometa_live.core.utils.classification_loaders import load_kraken_data
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


    @app.callback(
        [
            Output("dashboard-last-updated", "data"),
            Output("dashboard-last-updated-badge", "children")
        ],
        Input("results-fingerprint", "data"),
        [
            State("app-config", "data"),
            State("dashboard-last-updated", "data")
        ]
    )
    def update_data_freshness(fingerprint, config, last_updated):
        """
        Update data freshness timestamp and badge.

        Driven by ``results-fingerprint`` rather than the polling tick
        so the badge reflects when results actually changed on disk.
        Wall-clock-driven updates made the badge wobble forward on
        every tick and the stale check could not fire.
        """
        if not config:
            return None, LastUpdatedBadge(timestamp=None)
        if not fingerprint:
            # Fingerprint store has not produced a value yet; preserve any
            # existing badge instead of stamping a wall-clock time.
            raise PreventUpdate

        now = datetime.now().isoformat()
        update_interval = config.get("update_interval_seconds", 10)
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
        Input("dashboard-export-btn", "n_clicks"),
        Input("export-cancel-btn", "n_clicks"),
        Input("export-generate-btn", "n_clicks"),
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
        State("export-output-dir", "value"),
        State("export-include-raw", "value"),
        State("app-config", "data"),
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

    # ========================================================================
    # U1 — Throughput tile (header)
    # ========================================================================

    @app.callback(
        [
            Output("throughput-tile", "children"),
            Output("throughput-tile", "className"),
            Output("throughput-buffer", "data"),
        ],
        [
            Input("results-fingerprint", "data"),
            Input("update-interval", "n_intervals"),
        ],
        [
            State("throughput-buffer", "data"),
            State("backend-status", "data"),
            State("dashboard-overall-status-cache", "data"),
            State("app-config", "data"),
        ],
    )
    def update_throughput_tile(_fp, _n, buffer, status, overall_status, config):
        """Update the header throughput tile and rolling buffer.

        Pulls cumulative reads from dashboard-overall-status-cache (already
        computed elsewhere) and the count of nanometanf input files from
        backend-status. The buffer keeps the last few ticks so reads/min
        and files/min can be derived from the deltas; state classification
        flips between idle, normal, and stalled.
        """
        import time as _time

        ticks = list((buffer or {}).get("ticks", []) or [])
        running = bool(status and status.get("running"))

        total_reads = 0
        if overall_status:
            try:
                total_reads = int(overall_status.get("total_reads", 0) or 0)
            except (TypeError, ValueError):
                total_reads = 0

        total_files = 0
        if status:
            try:
                total_files = int(status.get("files_processed", 0) or 0)
            except (TypeError, ValueError):
                total_files = 0

        now = _time.time()
        new_ticks = append_tick(ticks, now, total_reads, total_files)
        rpm, fpm = compute_rates(new_ticks)
        state = classify_state(new_ticks, now, running)

        new_buffer = {
            "ticks": new_ticks,
            "reads_per_min": rpm,
            "files_per_min": fpm,
            "stalled_since": (
                last_nonzero_delta_ts(new_ticks) if state == "stalled" else None
            ),
        }

        if state == "idle":
            children = [
                html.I(className="bi bi-speedometer2 me-2"),
                html.Span("--- reads/min", className="me-2"),
                html.Span("--- files/min"),
            ]
            class_name = "throughput-tile ms-3 small text-muted"

        elif state == "stalled":
            last_progress = last_nonzero_delta_ts(new_ticks)
            age = (now - last_progress) if last_progress else (
                now - float(new_ticks[0]["ts"]) if new_ticks else 0
            )
            children = [
                html.I(className="bi bi-exclamation-triangle me-2 text-warning"),
                html.Span("Throughput stalled ", className="fw-semibold"),
                html.Span(
                    f"  0 reads/min   last data {format_age_seconds(age)}",
                    className="ms-2",
                ),
            ]
            # Amber tokens reused from _verdict_banner_style call sites.
            class_name = (
                "throughput-tile ms-3 small fw-semibold "
                "throughput-tile-stalled"
            )

        else:
            rpm_text = f"{int(round(rpm or 0)):,} reads/min"
            fpm_text = f"{int(round(fpm or 0))} files/min"
            children = [
                html.I(className="bi bi-speedometer2 me-2 text-primary"),
                html.Span(rpm_text, className="fw-semibold me-2"),
                html.Span(fpm_text, className="text-muted"),
            ]
            class_name = "throughput-tile ms-3 small"

        return children, class_name, new_buffer

# Helper functions

