"""
Configuration tab callbacks for Nanometa Live.

This module defines the callbacks for the configuration tab, which allows
users to configure the application before starting the analysis.
"""

import logging
import os
import json
import base64
import tempfile
from typing import Dict, Any, List
from datetime import datetime

import dash
from dash import Dash, Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc
from dash import html
from ruamel.yaml import YAML

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.config.config_loader import ConfigLoader


def register_config_callbacks(app: Dash, backend_manager: BackendManager):
    """
    Register callbacks for the configuration tab.

    Args:
        app: Dash application
        backend_manager: Backend manager instance
    """

    # Trigger form initialization on app startup
    # This fires once when the config-tab first renders
    @app.callback(
        Output("refresh-form-trigger", "data"),
        Input("tabs", "active_tab"),
        State("refresh-form-trigger", "data"),
        prevent_initial_call=False,
    )
    def trigger_initial_form_load(active_tab, current_trigger):
        """Trigger form initialization when config tab is first shown or on initial load."""
        # Fire on initial load (current_trigger will be False initially)
        if current_trigger is False:
            return True
        # Also refresh when switching to config tab
        if active_tab == "config-tab":
            return not current_trigger  # Toggle to trigger callback
        return no_update

    @app.callback(
        Output("available-configs", "children"),
        Input("update-interval", "n_intervals"),
        State("app-data-dir", "data"),
    )
    def update_available_configs(_, data_dir):
        """Update the list of available configurations."""
        if not data_dir:
            return "[]"

        config_loader = ConfigLoader(os.path.join(data_dir, "configs"))
        configs = config_loader.get_available_configs()

        return json.dumps(configs)

    @app.callback(
        Output("load-config-modal", "is_open"),
        [
            Input("load-config-button", "n_clicks"),
            Input("close-load-config-modal", "n_clicks"),
        ],
        State("load-config-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_load_config_modal(load_clicks, close_clicks, is_open):
        """Toggle the load configuration modal."""
        if load_clicks or close_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("load-config-list", "children"),
        Input("load-config-modal", "is_open"),
        State("available-configs", "children"),
    )
    def populate_load_config_list(is_open, available_configs_json):
        """Populate the list of available configurations."""
        if not is_open:
            return no_update

        try:
            configs = json.loads(available_configs_json)
        except (json.JSONDecodeError, TypeError) as e:
            logging.debug(f"Could not parse configs JSON: {e}")
            configs = []

        if not configs:
            return [html.P("No saved configurations found.")]

        config_list = []
        for i, config in enumerate(configs):
            timestamp = config.get("timestamp", "Unknown")
            try:
                # Try to parse ISO format timestamp
                dt = datetime.fromisoformat(timestamp)
                timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass  # Keep original timestamp string if parsing fails

            config_item = dbc.ListGroupItem(
                [
                    html.Div(
                        [
                            html.H5(
                                config.get("name", "Unnamed Configuration"),
                                className="mb-1",
                            ),
                            html.Small(f"Created: {timestamp}", className="text-muted"),
                        ]
                    ),
                    html.P(
                        f"Filename: {config.get('filename', 'Unknown')}",
                        className="mb-1",
                    ),
                    dbc.Button(
                        "Load",
                        id={"type": "load-config-item", "index": i},
                        color="primary",
                        size="sm",
                    ),
                ],
                className="d-flex justify-content-between align-items-center",
            )
            config_list.append(config_item)

        return [dbc.ListGroup(config_list)]

    @app.callback(
        [
            Output("app-config", "data"),
            Output("load-config-modal", "is_open", allow_duplicate=True),
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("refresh-form-trigger", "data", allow_duplicate=True),
        ],
        Input({"type": "load-config-item", "index": dash.ALL}, "n_clicks"),
        State("available-configs", "children"),
        State("app-data-dir", "data"),
        prevent_initial_call=True,
    )
    def load_selected_config(n_clicks, available_configs_json, data_dir):
        """Load the selected configuration."""
        if not any(n_clicks) or not ctx.triggered_id:
            return no_update, no_update, no_update, no_update

        # Find which button was clicked (pattern-matching ID returns a dict)
        triggered_id = ctx.triggered_id
        if not isinstance(triggered_id, dict) or "index" not in triggered_id:
            return no_update, no_update, no_update, no_update

        trigger_idx = triggered_id["index"]

        try:
            configs = json.loads(available_configs_json)
            selected_config = configs[trigger_idx]

            config_loader = ConfigLoader(os.path.join(data_dir, "configs"))
            config = config_loader.load_config(selected_config["path"])

            return (
                config,
                False,
                {
                    "title": "Configuration Loaded",
                    "message": f"Successfully loaded configuration: {selected_config.get('name', 'Unnamed')}",
                    "color": "success",
                },
                True,  # Trigger form refresh
            )

        except Exception as e:
            return (
                no_update,
                no_update,
                {
                    "title": "Error",
                    "message": f"Failed to load configuration: {str(e)}",
                    "color": "danger",
                },
                no_update,
            )

    @app.callback(
        Output("save-config-modal", "is_open"),
        [
            Input("save-config-button", "n_clicks"),
            Input("confirm-save-config", "n_clicks"),
            Input("cancel-save-config", "n_clicks"),
        ],
        State("save-config-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_save_config_modal(save_clicks, confirm_clicks, cancel_clicks, is_open):
        """Toggle the save configuration modal."""
        if save_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("save-config-name", "value"),
        Input("save-config-modal", "is_open"),
        State("app-config", "data"),
    )
    def set_default_config_name(is_open, config):
        """Set the default configuration name based on current analysis name."""
        if not is_open:
            return no_update

        # If modal is opening, populate with current analysis name
        if config and "analysis_name" in config and config["analysis_name"]:
            return config["analysis_name"]
        else:
            return f"Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    @app.callback(
        [
            Output("app-config", "data", allow_duplicate=True),
            Output("notification-trigger", "data", allow_duplicate=True),
        ],
        Input("confirm-save-config", "n_clicks"),
        [
            State("save-config-name", "value"),
            State("app-config", "data"),
            State("app-data-dir", "data"),
        ],
        prevent_initial_call=True,
    )
    def save_config(n_clicks, config_name, config, data_dir):
        """Save the current configuration."""
        if not n_clicks or not config:
            return no_update, no_update

        if not config_name:
            config_name = f"Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        try:
            # Create a new config object with all current settings
            new_config = dict(config)  # Create a copy

            # Save the config using the ConfigLoader
            config_loader = ConfigLoader(os.path.join(data_dir, "configs"))
            filename = f"{config_name.replace(' ', '_').lower()}.yaml"
            config_path = config_loader.save_config(new_config, filename)

            return new_config, {
                "title": "Configuration Saved",
                "message": f"Successfully saved configuration as: {config_name}",
                "color": "success",
            }
        except Exception as e:
            return no_update, {
                "title": "Error",
                "message": f"Failed to save configuration: {str(e)}",
                "color": "danger",
            }

    @app.callback(
        [
            Output("app-config", "data", allow_duplicate=True),
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("refresh-form-trigger", "data", allow_duplicate=True),
        ],
        Input("reset-config-button", "n_clicks"),
        State("app-data-dir", "data"),
        prevent_initial_call=True,
    )
    def reset_config(n_clicks, data_dir):
        """Reset the configuration to defaults."""
        if not n_clicks:
            return no_update, no_update, no_update

        try:
            config_loader = ConfigLoader(os.path.join(data_dir, "configs"))
            default_config = config_loader.create_default_config()

            return default_config, {
                "title": "Configuration Reset",
                "message": "Configuration has been reset to defaults",
                "color": "info",
            }, True  # Trigger form refresh
        except Exception as e:
            return no_update, {
                "title": "Error",
                "message": f"Failed to reset configuration: {str(e)}",
                "color": "danger",
            }, no_update

    # Apply Config Changes Callback - THE SINGLE POINT OF CONFIG UPDATE
    # All form values (including species) are read here and committed to app-config
    @app.callback(
        [
            Output("app-config", "data", allow_duplicate=True),
            Output("apply-config-button", "children"),
            Output("notification-trigger", "data", allow_duplicate=True),
            Output("config-feedback-alert", "is_open"),
        ],
        Input("apply-config-button", "n_clicks"),
        [
            State("analysis-name-input", "value"),
            State("nanopore-dir-input", "value"),
            State("kraken-db-input", "value"),
            State("results-dir-input", "value"),
            State("update-interval-input", "value"),
            State("danger-threshold-input", "value"),
            State("kraken-taxonomy-input", "value"),
            State("check-interval-input", "value"),
            State("min-reads-per-level-input", "value"),
            State("memory-mapping-input", "value"),
            State("blast-validation-input", "value"),
            State("validation-method-input", "value"),
            State("min-identity-input", "value"),
            State("e-value-cutoff-input", "value"),
            State("genome-cache-dir-input", "value"),
            State("cores-input", "value"),
            State("gui-port-input", "value"),
            State("clean-temp-input", "value"),
            State("pipeline-profile-input", "value"),
            State("pipeline-source-type-input", "value"),
            State("pipeline-branch-input", "value"),
            State("minimap2-preset-input", "value"),
            State("minimap2-min-mapq-input", "value"),
            State("pipeline-local-path-input", "value"),
            State("processing-mode-input", "value"),
            State("sample-handling-input", "value"),
            State("sample-name-input", "value"),
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
    )
    def apply_config_changes(
        n_clicks,
        analysis_name,
        nanopore_dir,
        kraken_db,
        results_dir,
        update_interval,
        danger_threshold,
        taxonomy,
        check_interval,
        min_reads_per_level,
        memory_mapping,
        blast_validation,
        validation_method,
        min_identity,
        e_value_cutoff,
        genome_cache_dir,
        cores,
        gui_port,
        clean_temp,
        pipeline_profile,
        pipeline_source_type,
        pipeline_branch,
        minimap2_preset,
        minimap2_min_mapq,
        pipeline_local_path,
        processing_mode,
        sample_handling,
        sample_name,
        current_config,
    ):
        """Apply configuration changes with validation."""
        if not n_clicks:
            return no_update, no_update, no_update, no_update

        if not current_config:
            return no_update, no_update, {
                "title": "Error",
                "message": "No configuration to update",
                "color": "danger",
            }, False

        # Validation errors list
        errors = []

        # Validate required fields
        if not nanopore_dir or not nanopore_dir.strip():
            errors.append("Nanopore Output Directory is required")

        if not kraken_db or not kraken_db.strip():
            errors.append("Kraken2 Database is required")

        # Validate directories exist (if provided)
        if nanopore_dir and nanopore_dir.strip():
            if not os.path.exists(nanopore_dir):
                errors.append(f"Nanopore directory does not exist: {nanopore_dir}")
            elif not os.path.isdir(nanopore_dir):
                errors.append(f"Nanopore path is not a directory: {nanopore_dir}")
            else:
                # Validate directory structure matches sample handling mode
                import glob
                if sample_handling == "by_barcode":
                    barcode_dirs = glob.glob(os.path.join(nanopore_dir, "barcode*"))
                    if not barcode_dirs:
                        errors.append(
                            "By-barcode mode selected but no barcode directories found. "
                            "Directory should contain barcode01/, barcode02/, etc. "
                            "For flat file directories, use 'Single sample' or 'Per file' mode."
                        )
                elif sample_handling in ["single_sample", "per_file"] and processing_mode == "batch":
                    # Check for FASTQ files directly in directory
                    fastq_files = glob.glob(os.path.join(nanopore_dir, "*.fastq*"))
                    barcode_dirs = glob.glob(os.path.join(nanopore_dir, "barcode*"))
                    if not fastq_files and barcode_dirs:
                        errors.append(
                            f"No FASTQ files found directly in {nanopore_dir}, but barcode directories exist. "
                            "For barcoded samples, use 'By barcode' handling mode."
                        )

        if kraken_db and kraken_db.strip():
            if not os.path.exists(kraken_db):
                errors.append(f"Kraken2 database does not exist: {kraken_db}")
            elif not os.path.isdir(kraken_db):
                errors.append(f"Kraken2 database path is not a directory: {kraken_db}")
            else:
                # Validate Kraken2 database format - check for required files
                required_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]
                missing_files = []
                for req_file in required_files:
                    file_path = os.path.join(kraken_db, req_file)
                    if not os.path.exists(file_path):
                        missing_files.append(req_file)

                if missing_files:
                    errors.append(f"Invalid Kraken2 database format. Missing required files: {', '.join(missing_files)}")

        # Validate numeric ranges
        if update_interval is not None:
            if update_interval < 1 or update_interval > 300:
                errors.append("Update Interval must be between 1-300 seconds")

        if check_interval is not None:
            if check_interval < 1 or check_interval > 300:
                errors.append("Check Interval must be between 1-300 seconds")

        if min_reads_per_level is not None:
            if min_reads_per_level < 1:
                errors.append("Minimum Reads per Level must be at least 1")

        if min_identity is not None:
            if min_identity < 50 or min_identity > 100:
                errors.append("Validation Threshold must be between 50-100%")

        if e_value_cutoff is not None:
            if e_value_cutoff < 0 or e_value_cutoff > 1:
                errors.append("E-value Cutoff must be between 0-1")

        if cores is not None:
            if cores < 1:
                errors.append("CPU Cores must be at least 1")

        if gui_port is not None:
            if gui_port < 1024 or gui_port > 65535:
                errors.append("GUI Port must be between 1024-65535")

        # If there are validation errors, return them
        if errors:
            return no_update, no_update, {
                "title": "Validation Error",
                "message": " | ".join(errors),
                "color": "danger",
            }, True

        # Create a completely new config object to avoid reference issues
        config = dict(current_config)

        # Update fields if they have valid values
        if analysis_name is not None:
            config["analysis_name"] = analysis_name

        if nanopore_dir is not None:
            config["nanopore_output_directory"] = nanopore_dir

        if kraken_db is not None:
            config["kraken_db"] = kraken_db

        if results_dir is not None:
            # If empty, use the default
            if not results_dir.strip():
                results_dir = os.path.join(os.path.expanduser("~"), "nanometa_results")
            config["results_output_directory"] = results_dir

        if update_interval is not None:
            config["update_interval_seconds"] = update_interval

        if danger_threshold is not None:
            config["danger_lower_limit"] = danger_threshold

        if taxonomy is not None:
            config["kraken_taxonomy"] = taxonomy

        if check_interval is not None:
            config["check_intervals_seconds"] = check_interval

        if min_reads_per_level is not None:
            config["default_reads_per_level"] = min_reads_per_level

        # Handle boolean values consistently as true/false
        if memory_mapping is not None:
            config["kraken_memory_mapping"] = bool(memory_mapping)

        if blast_validation is not None:
            config["blast_validation"] = bool(blast_validation)

        if validation_method is not None:
            config["validation_method"] = validation_method

        if minimap2_preset is not None:
            config["minimap2_preset"] = minimap2_preset

        if minimap2_min_mapq is not None:
            config["minimap2_min_mapq"] = minimap2_min_mapq

        if min_identity is not None:
            config["min_perc_identity"] = min_identity

        if e_value_cutoff is not None:
            config["e_val_cutoff"] = e_value_cutoff

        if genome_cache_dir is not None and genome_cache_dir.strip():
            config["genome_cache_dir"] = genome_cache_dir.strip()

        if cores is not None:
            # Set all core counts to the same value for simplicity
            config["pipeline_cores"] = cores
            config["kraken_cores"] = cores
            config["validation_cores"] = cores
            config["blast_cores"] = cores

        if gui_port is not None:
            config["gui_port"] = gui_port

        if clean_temp is not None:
            config["remove_temp_files"] = bool(clean_temp)

        if pipeline_profile is not None:
            config["pipeline_profile"] = pipeline_profile

        # Build pipeline_source from source type, branch, and local path
        if pipeline_source_type == "remote":
            # Use remote repository with selected branch
            branch = pipeline_branch if pipeline_branch else "master"
            config["pipeline_source"] = f"remote:{branch}"
        elif pipeline_source_type == "local" and pipeline_local_path:
            # Validate local path exists
            if not os.path.isdir(pipeline_local_path):
                errors.append(f"Local pipeline path does not exist: {pipeline_local_path}")
            else:
                config["pipeline_source"] = pipeline_local_path

        # Input mode settings
        if processing_mode is not None:
            config["processing_mode"] = processing_mode

        if sample_handling is not None:
            config["sample_handling"] = sample_handling

        if sample_name is not None:
            config["sample_name"] = sample_name if sample_name.strip() else "sample"

        # Note: Species watchlist is now managed via the Watchlist tab
        # and WatchlistManager, not through this config form

        # If validation errors occurred during pipeline source setup, return them
        if errors:
            return no_update, no_update, {
                "title": "Validation Error",
                "message": " | ".join(errors),
                "color": "danger",
            }, True

        # Auto-save config to last-session.yaml for session persistence
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            save_config = dict(config)
            # Include current watchlist state if loaded
            manager = get_watchlist_manager()
            if manager._loaded:
                save_config["watchlist"] = manager.export_config()
            config_dir = os.path.expanduser("~/.nanometa/configs")
            loader = ConfigLoader(config_dir)
            loader.save_config(save_config, "last-session.yaml")
            logging.debug("Auto-saved configuration to last-session.yaml")
        except Exception as e:
            logging.warning(f"Failed to auto-save configuration: {e}")

        return config, "Apply Settings", {
            "title": "Changes Applied",
            "message": f"Configuration changes have been applied. Analysis name: {analysis_name}",
            "color": "success",
        }, True  # Show the feedback alert

    # Reset the Apply button text after a short delay
    app.clientside_callback(
        """
        function(n_clicks) {
            if (n_clicks) {
                setTimeout(function() {
                    dash_clientside.set_props("apply-config-button", {children: "Apply Settings"});
                }, 2000);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("apply-config-button", "children", allow_duplicate=True),
        Input("apply-config-button", "n_clicks"),
        prevent_initial_call=True,
    )

    # Hide the feedback alert after a short delay
    app.clientside_callback(
        """
        function(is_open) {
            if (is_open) {
                setTimeout(function() {
                    dash_clientside.set_props("config-feedback-alert", {is_open: false});
                }, 3000);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("config-feedback-alert", "is_open", allow_duplicate=True),
        Input("config-feedback-alert", "is_open"),
        prevent_initial_call=True,
    )

    # REMOVED: Auto-update callback that was causing duplicate updates
    # Now users must explicitly click "Apply Settings" to commit form changes to config
    # This provides better UX with explicit user control over when changes are applied

    # Toggle pipeline source fields based on source type selection
    @app.callback(
        [
            Output("pipeline-branch-col", "style"),
            Output("pipeline-local-path-col", "style"),
        ],
        Input("pipeline-source-type-input", "value"),
    )
    def toggle_pipeline_source_fields(source_type):
        """Show/hide branch selector or local path input based on source type."""
        if source_type == "remote":
            return {"display": "block"}, {"display": "none"}
        else:  # local
            return {"display": "none"}, {"display": "block"}

    # Toggle sample name field visibility based on sample handling mode
    @app.callback(
        Output("sample-name-col", "style"),
        Input("sample-handling-input", "value"),
    )
    def toggle_sample_name_field(sample_handling):
        """Show sample name input only for single_sample mode."""
        if sample_handling == "single_sample":
            return {"display": "block"}
        else:
            return {"display": "none"}

    # Initialize form from config - ONLY on explicit refresh trigger
    # Changed: app-config is now a State, not an Input, to prevent form resets
    # when other callbacks update the config store
    @app.callback(
        [
            Output("analysis-name-input", "value"),
            Output("nanopore-dir-input", "value"),
            Output("kraken-db-input", "value"),
            Output("results-dir-input", "value"),
            Output("update-interval-input", "value"),
            Output("danger-threshold-input", "value"),
            Output("kraken-taxonomy-input", "value"),
            Output("check-interval-input", "value"),
            Output("min-reads-per-level-input", "value"),
            Output("memory-mapping-input", "value"),
            Output("blast-validation-input", "value"),
            Output("validation-method-input", "value"),
            Output("min-identity-input", "value"),
            Output("e-value-cutoff-input", "value"),
            Output("minimap2-preset-input", "value"),
            Output("minimap2-min-mapq-input", "value"),
            Output("genome-cache-dir-input", "value"),
            Output("cores-input", "value"),
            Output("gui-port-input", "value"),
            Output("clean-temp-input", "value"),
            Output("pipeline-profile-input", "value"),
            Output("pipeline-source-type-input", "value"),
            Output("pipeline-branch-input", "value"),
            Output("pipeline-local-path-input", "value"),
            Output("processing-mode-input", "value"),
            Output("sample-handling-input", "value"),
            Output("sample-name-input", "value"),
            Output("config-form-initialized", "data"),
        ],
        Input("refresh-form-trigger", "data"),
        State("app-config", "data"),
    )
    def initialize_form_from_config(refresh_trigger, config):
        """Initialize form fields from the current configuration."""
        if not config:
            return [no_update] * 28

        # Extract values from config
        analysis_name = config.get("analysis_name", "")
        nanopore_dir = config.get("nanopore_output_directory", "")
        kraken_db = config.get("kraken_db", "")
        results_dir = config.get("results_output_directory", "")
        update_interval = config.get("update_interval_seconds", 30)
        danger_threshold = config.get("danger_lower_limit", 100)
        taxonomy = config.get("kraken_taxonomy", "gtdb")
        check_interval = config.get("check_intervals_seconds", 15)
        min_reads_per_level = config.get("default_reads_per_level", 10)

        # Handle boolean values
        memory_mapping = config.get("kraken_memory_mapping", True)
        # Ensure it's a boolean regardless of stored format
        if isinstance(memory_mapping, str):
            memory_mapping = memory_mapping == "--memory-mapping" or \
                memory_mapping.lower() in ["true", "yes", "y", "1"]
        memory_mapping = bool(memory_mapping)

        blast_validation = config.get("blast_validation", True)
        # Ensure it's a boolean regardless of stored format
        if isinstance(blast_validation, str):
            blast_validation = blast_validation.lower() in ["true", "yes", "y", "1"]
        blast_validation = bool(blast_validation)

        validation_method = config.get("validation_method", "blast")
        minimap2_preset = config.get("minimap2_preset", "map-ont")
        minimap2_min_mapq = config.get("minimap2_min_mapq", 30)

        min_identity = config.get("min_perc_identity", 90)
        e_value_cutoff = config.get("e_val_cutoff", 0.01)
        genome_cache_dir = config.get("genome_cache_dir", "~/.nanometa")
        cores = config.get("pipeline_cores", config.get("snakemake_cores", 1))  # Backward compatibility
        gui_port = config.get("gui_port", 8050)

        clean_temp = config.get("remove_temp_files", True)
        # Ensure it's a boolean regardless of stored format
        if isinstance(clean_temp, str):
            clean_temp = clean_temp == "yes" or clean_temp.lower() in ["true", "yes", "y", "1"]
        clean_temp = bool(clean_temp)

        # Pipeline profile
        pipeline_profile = config.get("pipeline_profile", "docker")

        # Parse pipeline_source to extract type, branch, and local path
        pipeline_source = config.get("pipeline_source", "remote:master")
        pipeline_source_type = "remote"
        pipeline_branch = "master"
        pipeline_local_path = ""

        if pipeline_source.startswith("remote:"):
            pipeline_source_type = "remote"
            pipeline_branch = pipeline_source.split(":", 1)[1] if ":" in pipeline_source else "master"
        elif pipeline_source in ("master", "main", "dev"):
            # Shorthand for remote branch
            pipeline_source_type = "remote"
            pipeline_branch = "master" if pipeline_source == "main" else pipeline_source
        elif pipeline_source.startswith("local:"):
            # Explicit local: prefix convention
            pipeline_source_type = "local"
            pipeline_local_path = pipeline_source[len("local:"):]
        elif os.path.isdir(pipeline_source):
            # Local path without prefix
            pipeline_source_type = "local"
            pipeline_local_path = pipeline_source
        else:
            # Assume local path even if it doesn't exist yet
            pipeline_source_type = "local"
            pipeline_local_path = pipeline_source

        # Input mode settings
        processing_mode = config.get("processing_mode", "batch")
        sample_handling = config.get("sample_handling", "single_sample")
        sample_name = config.get("sample_name", "sample")

        return [
            analysis_name,
            nanopore_dir,
            kraken_db,
            results_dir,
            update_interval,
            danger_threshold,
            taxonomy,
            check_interval,
            min_reads_per_level,
            memory_mapping,
            blast_validation,
            validation_method,
            minimap2_preset,
            minimap2_min_mapq,
            min_identity,
            e_value_cutoff,
            genome_cache_dir,
            cores,
            gui_port,
            clean_temp,
            pipeline_profile,
            pipeline_source_type,
            pipeline_branch,
            pipeline_local_path,
            processing_mode,
            sample_handling,
            sample_name,
            True,  # Mark form as initialized (suppresses first "Modified" badge)
        ]

    # Species watchlist management is now handled in the Watchlist tab
    # via WatchlistManager - all legacy species callbacks have been removed

    # NOTE: populate_kraken_database_options moved to preparation_tab.py

    # Folder browser callbacks
    @app.callback(
        [
            Output("folder-browser-modal", "is_open"),
            Output("browse-target-field", "data"),
            Output("current-browse-path", "data"),
        ],
        [
            Input("browse-nanopore-dir", "n_clicks"),
            Input("browse-kraken-db", "n_clicks"),
            Input("browse-results-dir", "n_clicks"),
            Input("browse-pipeline-path", "n_clicks"),
            Input("confirm-directory-select", "n_clicks"),
            Input("cancel-directory-select", "n_clicks"),
        ],
        [
            State("folder-browser-modal", "is_open"),
            State("current-browse-path", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_folder_browser(
        nanopore_clicks, kraken_clicks, results_clicks, pipeline_clicks, confirm_clicks, cancel_clicks, is_open, current_path
    ):
        """Toggle folder browser modal and track which field is being edited."""
        triggered_id = ctx.triggered_id if ctx.triggered else None

        # Open modal for nanopore directory
        if triggered_id == "browse-nanopore-dir":
            return True, "nanopore-dir-input", os.path.expanduser("~")

        # Open modal for kraken database
        if triggered_id == "browse-kraken-db":
            return True, "kraken-db-input", os.path.expanduser("~")

        # Open modal for results output directory
        if triggered_id == "browse-results-dir":
            return True, "results-dir-input", os.path.expanduser("~")

        # Open modal for local pipeline path
        if triggered_id == "browse-pipeline-path":
            return True, "pipeline-local-path-input", os.path.expanduser("~")

        # Close modal (confirm or cancel)
        if triggered_id in ["confirm-directory-select", "cancel-directory-select"]:
            return False, None, current_path

        return is_open, no_update, no_update

    @app.callback(
        [
            Output("directory-tree", "children"),
            Output("current-path-display", "value"),
        ],
        [
            Input("current-browse-path", "data"),
            Input({"type": "browse-dir", "path": dash.ALL}, "n_clicks"),
        ],
        State({"type": "browse-dir", "path": dash.ALL}, "id"),
        prevent_initial_call=True,
    )
    def update_directory_tree(current_path, dir_clicks, dir_ids):
        """Update the directory tree display with parent directory option."""
        triggered_id = ctx.triggered_id if ctx.triggered else None

        # If a directory was clicked, navigate to it
        if isinstance(triggered_id, dict) and triggered_id.get("type") == "browse-dir":
            current_path = triggered_id.get("path")

        if not current_path or not os.path.exists(current_path):
            current_path = os.path.expanduser("~")

        # Get directories in current path
        try:
            entries = []

            # Add parent directory option if not at root
            parent_path = os.path.dirname(current_path)
            if parent_path and parent_path != current_path:
                entries.append(
                    dbc.ListGroupItem(
                        [
                            html.I(className="fas fa-level-up-alt text-primary me-2"),
                            html.Span(".. (Parent Directory)", className="fw-bold"),
                        ],
                        id={"type": "browse-dir", "path": parent_path},
                        action=True,
                        className="d-flex align-items-center",
                        color="light",
                    )
                )

            # Add subdirectories
            for entry in sorted(os.listdir(current_path)):
                entry_path = os.path.join(current_path, entry)
                if os.path.isdir(entry_path):
                    # Don't show hidden directories (starting with .)
                    if not entry.startswith('.'):
                        entries.append(
                            dbc.ListGroupItem(
                                [
                                    html.I(className="fas fa-folder text-warning me-2"),
                                    html.Span(entry),
                                ],
                                id={"type": "browse-dir", "path": entry_path},
                                action=True,
                                className="d-flex align-items-center",
                            )
                        )

            if len(entries) == 0 or (len(entries) == 1 and parent_path):
                entries.append(
                    dbc.ListGroupItem(
                        [
                            html.I(className="fas fa-info-circle text-muted me-2"),
                            html.Span("No subdirectories", className="text-muted"),
                        ],
                        disabled=True,
                    )
                )

            directory_list = dbc.ListGroup(entries)

        except PermissionError:
            directory_list = dbc.Alert(
                "Permission denied. Cannot access this directory.",
                color="warning",
            )
        except Exception as e:
            directory_list = dbc.Alert(
                f"Error reading directory: {str(e)}",
                color="danger",
            )

        return directory_list, current_path

    @app.callback(
        Output("current-browse-path", "data", allow_duplicate=True),
        [
            Input("browse-parent-dir", "n_clicks"),
            Input("quick-home", "n_clicks"),
            Input("quick-desktop", "n_clicks"),
            Input("quick-documents", "n_clicks"),
            Input("quick-root", "n_clicks"),
            Input("current-path-display", "n_submit"),
        ],
        [
            State("current-browse-path", "data"),
            State("current-path-display", "value"),
        ],
        prevent_initial_call=True,
    )
    def navigate_directories(parent_clicks, home_clicks, desktop_clicks, docs_clicks, root_clicks, path_submit, current_path, typed_path):
        """Handle all directory navigation actions."""
        triggered_id = ctx.triggered_id if ctx.triggered else None

        # Navigate to parent directory
        if triggered_id == "browse-parent-dir":
            parent_path = os.path.dirname(current_path)
            if parent_path and parent_path != current_path:
                return parent_path

        # Quick access: Home
        elif triggered_id == "quick-home":
            return os.path.expanduser("~")

        # Quick access: Desktop
        elif triggered_id == "quick-desktop":
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            if os.path.exists(desktop_path):
                return desktop_path
            return os.path.expanduser("~")

        # Quick access: Documents
        elif triggered_id == "quick-documents":
            docs_path = os.path.join(os.path.expanduser("~"), "Documents")
            if os.path.exists(docs_path):
                return docs_path
            return os.path.expanduser("~")

        # Quick access: Root
        elif triggered_id == "quick-root":
            return "/"

        # Manual path entry
        elif triggered_id == "current-path-display" and typed_path:
            expanded_path = os.path.expanduser(typed_path)
            if os.path.exists(expanded_path) and os.path.isdir(expanded_path):
                return expanded_path

        return no_update

    @app.callback(
        [
            Output("nanopore-dir-input", "value", allow_duplicate=True),
            Output("kraken-db-input", "value", allow_duplicate=True),
            Output("results-dir-input", "value", allow_duplicate=True),
            Output("pipeline-local-path-input", "value", allow_duplicate=True),
            Output("folder-browser-modal", "is_open", allow_duplicate=True),
        ],
        [
            Input("confirm-directory-select", "n_clicks"),
            Input("use-current-dir", "n_clicks"),
        ],
        [
            State("current-browse-path", "data"),
            State("browse-target-field", "data"),
            State("folder-browser-modal", "is_open"),
        ],
        prevent_initial_call=True,
    )
    def confirm_directory_selection(confirm_clicks, use_clicks, selected_path, target_field, is_open):
        """Update the appropriate input field with selected directory."""
        triggered_id = ctx.triggered_id if ctx.triggered else None

        if not selected_path or not target_field:
            return no_update, no_update, no_update, no_update, no_update

        # Close modal on confirm button
        should_close = triggered_id == "confirm-directory-select"

        if target_field == "nanopore-dir-input":
            return selected_path, no_update, no_update, no_update, not is_open if should_close else no_update
        elif target_field == "kraken-db-input":
            return no_update, selected_path, no_update, no_update, not is_open if should_close else no_update
        elif target_field == "results-dir-input":
            return no_update, no_update, selected_path, no_update, not is_open if should_close else no_update
        elif target_field == "pipeline-local-path-input":
            return no_update, no_update, no_update, selected_path, not is_open if should_close else no_update

        return no_update, no_update, no_update, no_update, no_update

    # Real-time validation feedback
    @app.callback(
        [
            Output("nanopore-dir-status", "children"),
            Output("nanopore-dir-feedback", "children")
        ],
        Input("nanopore-dir-input", "value"),
        prevent_initial_call=True,
    )
    def validate_nanopore_directory(path):
        """Provide real-time validation feedback for nanopore directory."""
        if not path or not path.strip():
            return "", ""

        if not os.path.exists(path):
            return (
                html.I(className="bi bi-x-circle text-danger"),
                html.Small("Directory does not exist.", className="text-danger")
            )
        elif not os.path.isdir(path):
            return (
                html.I(className="bi bi-x-circle text-danger"),
                html.Small("Path is not a directory.", className="text-danger")
            )
        else:
            return (
                html.I(className="bi bi-check-circle text-success"),
                html.Small("Directory found.", className="text-success")
            )

    @app.callback(
        [
            Output("kraken-db-status", "children"),
            Output("kraken-db-feedback", "children")
        ],
        Input("kraken-db-input", "value"),
        prevent_initial_call=True,
    )
    def validate_kraken_database(path):
        """Provide real-time validation feedback for Kraken2 database."""
        if not path or not path.strip():
            return "", ""

        if not os.path.exists(path):
            return (
                html.I(className="bi bi-x-circle text-danger"),
                html.Small("Directory does not exist.", className="text-danger")
            )
        elif not os.path.isdir(path):
            return (
                html.I(className="bi bi-x-circle text-danger"),
                html.Small("Path is not a directory.", className="text-danger")
            )
        else:
            # Check for required Kraken2 database files
            required_files = ["hash.k2d", "opts.k2d", "taxo.k2d"]
            missing_files = []
            for req_file in required_files:
                file_path = os.path.join(path, req_file)
                if not os.path.exists(file_path):
                    missing_files.append(req_file)

            if missing_files:
                return (
                    html.I(className="bi bi-exclamation-triangle text-warning"),
                    html.Small(f"Missing database files: {', '.join(missing_files)}", className="text-warning")
                )
            else:
                return (
                    html.I(className="bi bi-check-circle text-success"),
                    html.Small("Valid Kraken2 database found.", className="text-success")
                )

    @app.callback(
        Output("results-dir-status", "children"),
        Input("results-dir-input", "value"),
        prevent_initial_call=True,
    )
    def validate_results_directory(path):
        """Provide real-time validation feedback for results output directory."""
        if not path or not path.strip():
            # Empty is OK - will use default ~/nanometa_results
            return html.I(className="bi bi-info-circle text-muted")

        expanded_path = os.path.expanduser(path)

        if os.path.exists(expanded_path):
            if os.path.isdir(expanded_path):
                # Directory exists - check if writable
                if os.access(expanded_path, os.W_OK):
                    return html.I(className="bi bi-check-circle text-success")
                else:
                    return html.I(className="bi bi-exclamation-triangle text-warning")
            else:
                # Path exists but is not a directory
                return html.I(className="bi bi-x-circle text-danger")
        else:
            # Directory doesn't exist - will be created (show info icon)
            parent = os.path.dirname(expanded_path)
            if parent and os.path.exists(parent) and os.access(parent, os.W_OK):
                return html.I(className="bi bi-plus-circle text-info")
            else:
                return html.I(className="bi bi-exclamation-triangle text-warning")

    @app.callback(
        Output("pipeline-path-status", "children"),
        Input("pipeline-local-path-input", "value"),
        prevent_initial_call=True,
    )
    def validate_pipeline_path(path):
        """Provide real-time validation feedback for local pipeline path."""
        if not path or not path.strip():
            return ""

        expanded_path = os.path.expanduser(path)

        if not os.path.exists(expanded_path):
            return html.I(className="bi bi-x-circle text-danger")
        elif not os.path.isdir(expanded_path):
            return html.I(className="bi bi-x-circle text-danger")
        else:
            # Check for main.nf file (required for Nextflow pipeline)
            main_nf = os.path.join(expanded_path, "main.nf")
            if not os.path.exists(main_nf):
                return html.I(className="bi bi-exclamation-triangle text-warning")
            else:
                return html.I(className="bi bi-check-circle text-success")

    # =========================================================================
    # Configuration State Management Callbacks (v2.0)
    # =========================================================================

    # Callback: Update config source and snapshot when config is loaded from file
    @app.callback(
        [
            Output("config-source", "data", allow_duplicate=True),
            Output("saved-config-snapshot", "data", allow_duplicate=True),
            Output("config-modified", "data", allow_duplicate=True),
        ],
        Input({"type": "load-config-item", "index": dash.ALL}, "n_clicks"),
        State("available-configs", "children"),
        prevent_initial_call=True,
    )
    def update_config_source_on_load(n_clicks, available_configs_json):
        """Update config source info when loading from file."""
        if not any(n_clicks) or not ctx.triggered_id:
            return no_update, no_update, no_update

        triggered_id = ctx.triggered_id
        if not isinstance(triggered_id, dict) or "index" not in triggered_id:
            return no_update, no_update, no_update

        try:
            trigger_idx = triggered_id["index"]
            configs = json.loads(available_configs_json)
            selected_config = configs[trigger_idx]

            # Update source info
            source_info = {
                "type": "file",
                "path": selected_config.get("path", ""),
                "name": selected_config.get("name", "Loaded Configuration")
            }

            # Load config for snapshot
            config_loader = ConfigLoader(os.path.join(
                os.path.dirname(selected_config.get("path", "")), ""
            ))
            config = config_loader.load_config(selected_config["path"])

            return source_info, config, False  # Not modified after loading

        except Exception:
            return no_update, no_update, no_update

    # Callback: Update config source after save
    @app.callback(
        [
            Output("config-source", "data", allow_duplicate=True),
            Output("saved-config-snapshot", "data", allow_duplicate=True),
            Output("config-modified", "data", allow_duplicate=True),
        ],
        Input("confirm-save-config", "n_clicks"),
        [
            State("save-config-name", "value"),
            State("app-config", "data"),
            State("app-data-dir", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_config_source_on_save(n_clicks, config_name, config, data_dir):
        """Update config source info after saving to file."""
        if not n_clicks or not config:
            return no_update, no_update, no_update

        if not config_name:
            config_name = f"Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Build expected file path
        filename = f"{config_name.replace(' ', '_').lower()}.yaml"
        config_path = os.path.join(data_dir or "", "configs", filename)

        # Update source info
        source_info = {
            "type": "file",
            "path": config_path,
            "name": config_name
        }

        return source_info, config, False  # Not modified after saving

    # Callback: Mark as modified after reset (resets to defaults)
    @app.callback(
        [
            Output("config-source", "data", allow_duplicate=True),
            Output("config-modified", "data", allow_duplicate=True),
        ],
        Input("reset-config-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def update_config_source_on_reset(n_clicks):
        """Update config source info after reset to defaults."""
        if not n_clicks:
            return no_update, no_update

        source_info = {
            "type": "default",
            "path": None,
            "name": "Default Configuration"
        }

        return source_info, False  # Not modified (it IS the defaults)

    # Callback: Update status banner display
    @app.callback(
        [
            Output("config-source-display", "children"),
            Output("config-path-display", "children"),
            Output("config-modified-badge", "style"),
            Output("config-saved-badge", "style"),
            Output("config-saved-badge", "children"),
            Output("config-saved-badge", "color"),
            Output("config-status-banner", "className"),
        ],
        [
            Input("config-source", "data"),
            Input("config-modified", "data"),
        ],
    )
    def update_config_status_display(source_info, is_modified):
        """Update the config status banner display."""
        if not source_info:
            source_info = {
                "type": "default",
                "path": None,
                "name": "Default Configuration"
            }

        # Determine source display text
        source_name = source_info.get("name", "Unknown")
        source_path = source_info.get("path", "")
        source_type = source_info.get("type", "default")

        # Truncate path for display
        if source_path:
            # Show just filename and parent directory
            path_parts = source_path.split(os.sep)
            if len(path_parts) > 2:
                display_path = os.sep.join(["...", path_parts[-2], path_parts[-1]])
            else:
                display_path = source_path
        else:
            display_path = ""

        # Badge visibility
        modified_style = {"display": "inline"} if is_modified else {"display": "none"}
        saved_style = {"display": "none"} if is_modified else {"display": "inline"}

        # Badge text and color depend on config source type
        if source_type == "file":
            saved_badge_text = "Saved"
            saved_badge_color = "success"
        else:
            saved_badge_text = "Default"
            saved_badge_color = "secondary"

        # Banner CSS class
        base_class = "config-status-banner mb-3"
        if is_modified:
            banner_class = f"{base_class} modified"
        elif source_type == "file":
            banner_class = f"{base_class} saved"
        else:
            banner_class = base_class

        return source_name, display_path, modified_style, saved_style, saved_badge_text, saved_badge_color, banner_class

    # Callback: Detect form changes and update modified state
    @app.callback(
        [
            Output("config-modified", "data", allow_duplicate=True),
            Output("config-form-initialized", "data", allow_duplicate=True),
        ],
        [
            Input("analysis-name-input", "value"),
            Input("nanopore-dir-input", "value"),
            Input("kraken-db-input", "value"),
            Input("results-dir-input", "value"),
            Input("update-interval-input", "value"),
            Input("danger-threshold-input", "value"),
            Input("kraken-taxonomy-input", "value"),
            Input("check-interval-input", "value"),
            Input("min-reads-per-level-input", "value"),
            Input("memory-mapping-input", "value"),
            Input("blast-validation-input", "value"),
            Input("validation-method-input", "value"),
            Input("min-identity-input", "value"),
            Input("e-value-cutoff-input", "value"),
            Input("minimap2-preset-input", "value"),
            Input("minimap2-min-mapq-input", "value"),
            Input("genome-cache-dir-input", "value"),
            Input("cores-input", "value"),
            Input("gui-port-input", "value"),
            Input("clean-temp-input", "value"),
        ],
        [
            State("saved-config-snapshot", "data"),
            State("config-modified", "data"),
            State("config-form-initialized", "data"),
        ],
        prevent_initial_call=True,
    )
    def detect_form_changes(
        analysis_name, nanopore_dir, kraken_db, results_dir, update_interval,
        danger_threshold, taxonomy, check_interval,
        min_reads_per_level, memory_mapping, blast_validation, validation_method,
        min_identity, e_value_cutoff, minimap2_preset, minimap2_min_mapq,
        genome_cache_dir, cores, gui_port, clean_temp,
        saved_snapshot, currently_modified, form_initialized
    ):
        """Detect when form values differ from saved snapshot."""
        # After form initialization, the cascading value changes trigger this
        # callback. Consume the initialized flag and skip the modification check.
        if form_initialized:
            return no_update, False

        if not saved_snapshot:
            return no_update, no_update

        # Build current form state for comparison
        current_values = {
            "analysis_name": analysis_name or "",
            "nanopore_output_directory": nanopore_dir or "",
            "kraken_db": kraken_db or "",
            "results_output_directory": results_dir or "",
            "update_interval_seconds": update_interval,
            "danger_lower_limit": danger_threshold,
            "kraken_taxonomy": taxonomy or "",
            "check_intervals_seconds": check_interval,
            "default_reads_per_level": min_reads_per_level,
            "kraken_memory_mapping": bool(memory_mapping),
            "blast_validation": bool(blast_validation),
            "validation_method": validation_method or "blast",
            "minimap2_preset": minimap2_preset or "map-ont",
            "minimap2_min_mapq": minimap2_min_mapq,
            "min_perc_identity": min_identity,
            "e_val_cutoff": e_value_cutoff,
            "genome_cache_dir": genome_cache_dir or "~/.nanometa",
            "pipeline_cores": cores,
            "gui_port": gui_port,
            "remove_temp_files": bool(clean_temp),
        }

        # Compare key fields with snapshot
        is_modified = False
        for key, current_val in current_values.items():
            snapshot_val = saved_snapshot.get(key)

            # Handle None values
            if current_val is None and snapshot_val is None:
                continue

            # Normalize values for comparison
            if isinstance(current_val, bool):
                # Convert snapshot value to bool for comparison
                if isinstance(snapshot_val, str):
                    snapshot_val = snapshot_val.lower() in ["true", "yes", "y", "1", "--memory-mapping"]
                else:
                    snapshot_val = bool(snapshot_val) if snapshot_val is not None else False

            # Compare normalized values
            if current_val != snapshot_val:
                is_modified = True
                break

        return is_modified, no_update

    # Callback: Mark as not modified after Apply (config matches current form)
    @app.callback(
        [
            Output("saved-config-snapshot", "data", allow_duplicate=True),
            Output("config-modified", "data", allow_duplicate=True),
        ],
        Input("apply-config-button", "n_clicks"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def update_snapshot_on_apply(n_clicks, config):
        """Update snapshot to match current config after Apply (session-only)."""
        if not n_clicks or not config:
            return no_update, no_update

        # Note: After Apply, the form matches the config, so it's "not modified"
        # relative to the applied state. However, it may still differ from
        # the saved-to-disk state. For clarity, we only update modified to False
        # when actually saving to file.
        #
        # Actually, let's keep modified=True if it differs from what's on disk,
        # so the user knows they need to save. We won't update snapshot here.
        return no_update, no_update