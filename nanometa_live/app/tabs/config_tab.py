"""
Configuration tab callbacks for Nanometa Live.

This module defines the callbacks for the configuration tab, which allows
users to configure the application before starting the analysis.
"""

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

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.core.config.config_loader import ConfigLoader


def register_config_callbacks(app: Dash, backend_manager: BackendManager):
    """
    Register callbacks for the configuration tab.

    Args:
        app: Dash application
        backend_manager: Backend manager instance
    """

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
        except:
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
            except:
                pass

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
        ],
        Input({"type": "load-config-item", "index": dash.ALL}, "n_clicks"),
        State("available-configs", "children"),
        State("app-data-dir", "data"),
        prevent_initial_call=True,
    )
    def load_selected_config(n_clicks, available_configs_json, data_dir):
        """Load the selected configuration."""
        if not any(n_clicks) or not ctx.triggered:
            return no_update, no_update, no_update

        # Find which button was clicked
        triggered_id = ctx.triggered[0]["prop_id"]
        if "index" not in triggered_id:
            return no_update, no_update, no_update

        trigger_idx = json.loads(triggered_id.split(".")[0])["index"]

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
            )

    @app.callback(
        Output("save-config-modal", "is_open"),
        [
            Input("save-config-button", "n_clicks"),
            Input("confirm-save-config", "n_clicks"),
            Input("cancel-save-config", "n_clicks"),
        ],
        State("save-config-modal", "is_open"),
    )
    def toggle_save_config_modal(save_clicks, confirm_clicks, cancel_clicks, is_open):
        """Toggle the save configuration modal."""
        if save_clicks or confirm_clicks or cancel_clicks:
            return not is_open
        return is_open

    @app.callback(
        Output("notification-trigger", "data", allow_duplicate=True),
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
            return no_update

        if not config_name:
            config_name = f"Config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        try:
            # Update the config with the name
            config["analysis_name"] = config_name

            # Save the config
            config_loader = ConfigLoader(os.path.join(data_dir, "configs"))
            filename = f"{config_name.replace(' ', '_').lower()}.yaml"
            config_path = config_loader.save_config(config, filename)

            return {
                "title": "Configuration Saved",
                "message": f"Successfully saved configuration as: {config_name}",
                "color": "success",
            }
        except Exception as e:
            return {
                "title": "Error",
                "message": f"Failed to save configuration: {str(e)}",
                "color": "danger",
            }

    @app.callback(
        [
            Output("app-config", "data", allow_duplicate=True),
            Output("notification-trigger", "data", allow_duplicate=True),
        ],
        Input("reset-config-button", "n_clicks"),
        State("app-data-dir", "data"),
        prevent_initial_call=True,
    )
    def reset_config(n_clicks, data_dir):
        """Reset the configuration to defaults."""
        if not n_clicks:
            return no_update, no_update

        try:
            config_loader = ConfigLoader(os.path.join(data_dir, "configs"))
            default_config = config_loader.create_default_config()

            return default_config, {
                "title": "Configuration Reset",
                "message": "Configuration has been reset to defaults",
                "color": "info",
            }
        except Exception as e:
            return no_update, {
                "title": "Error",
                "message": f"Failed to reset configuration: {str(e)}",
                "color": "danger",
            }

    # Form field updates
    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        [
            Input("analysis-name-input", "value"),
            Input("nanopore-dir-input", "value"),
            Input("kraken-db-input", "value"),
            Input("update-interval-input", "value"),
            Input("danger-threshold-input", "value"),
            Input("kraken-taxonomy-input", "value"),
            Input("external-kraken-input", "value"),
            Input("check-interval-input", "value"),
            Input("memory-mapping-input", "value"),
            Input("blast-validation-input", "value"),
            Input("min-identity-input", "value"),
            Input("cores-input", "value"),
            Input("clean-temp-input", "value"),
        ],
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def update_config_from_form(
        analysis_name,
        nanopore_dir,
        kraken_db,
        update_interval,
        danger_threshold,
        taxonomy,
        external_kraken,
        check_interval,
        memory_mapping,
        blast_validation,
        min_identity,
        cores,
        clean_temp,
        current_config,
    ):
        """Update the configuration from form inputs."""
        if not current_config:
            return no_update

        # Create a copy of the current config
        config = dict(current_config)

        # Update fields if they have valid values
        if analysis_name is not None:
            config["analysis_name"] = analysis_name

        if nanopore_dir is not None:
            config["nanopore_output_directory"] = nanopore_dir

        if kraken_db is not None:
            config["kraken_db"] = kraken_db

        if update_interval is not None:
            config["update_interval_seconds"] = update_interval

        if danger_threshold is not None:
            config["danger_lower_limit"] = danger_threshold

        if taxonomy is not None:
            config["kraken_taxonomy"] = taxonomy

        if external_kraken is not None:
            config["external_kraken2_db"] = external_kraken

        if check_interval is not None:
            config["check_intervals_seconds"] = check_interval

        # Handle boolean/list values
        if memory_mapping is not None:
            config["kraken_memory_mapping"] = (
                "--memory-mapping" if memory_mapping and "true" in memory_mapping else ""
            )

        if blast_validation is not None:
            config["blast_validation"] = blast_validation and "true" in blast_validation

        if min_identity is not None:
            config["min_perc_identity"] = min_identity

        if cores is not None:
            # Set all core counts to the same value for simplicity
            config["snakemake_cores"] = cores
            config["kraken_cores"] = cores
            config["validation_cores"] = cores
            config["blast_cores"] = cores

        if clean_temp is not None:
            config["remove_temp_files"] = (
                "yes" if clean_temp and "true" in clean_temp else "no"
            )

        return config

    # Initialize form from config
    @app.callback(
        [
            Output("analysis-name-input", "value"),
            Output("nanopore-dir-input", "value"),
            Output("kraken-db-input", "value"),
            Output("update-interval-input", "value"),
            Output("danger-threshold-input", "value"),
            Output("kraken-taxonomy-input", "value"),
            Output("external-kraken-input", "value"),
            Output("check-interval-input", "value"),
            Output("memory-mapping-input", "value"),
            Output("blast-validation-input", "value"),
            Output("min-identity-input", "value"),
            Output("cores-input", "value"),
            Output("clean-temp-input", "value"),
        ],
        Input("app-config", "data"),
    )
    def initialize_form_from_config(config):
        """Initialize form fields from the current configuration."""
        if not config:
            return [no_update] * 13

        # Extract values from config
        analysis_name = config.get("analysis_name", "")
        nanopore_dir = config.get("nanopore_output_directory", "")
        kraken_db = config.get("kraken_db", "")
        update_interval = config.get("update_interval_seconds", 30)
        danger_threshold = config.get("danger_lower_limit", 100)
        taxonomy = config.get("kraken_taxonomy", "gtdb")
        external_kraken = config.get("external_kraken2_db", "")
        check_interval = config.get("check_intervals_seconds", 15)

        # Handle boolean/list values
        memory_mapping = (
            ["true"]
            if config.get("kraken_memory_mapping", "") == "--memory-mapping"
            else []
        )
        blast_validation = ["true"] if config.get("blast_validation", True) else []

        min_identity = config.get("min_perc_identity", 90)
        cores = config.get("snakemake_cores", 1)
        clean_temp = ["true"] if config.get("remove_temp_files", "yes") == "yes" else []

        return [
            analysis_name,
            nanopore_dir,
            kraken_db,
            update_interval,
            danger_threshold,
            taxonomy,
            external_kraken,
            check_interval,
            memory_mapping,
            blast_validation,
            min_identity,
            cores,
            clean_temp,
        ]

    # Species list handling
    @app.callback(
        [
            Output("species-list-container", "children"),
            Output("app-config", "data", allow_duplicate=True),
        ],
        [
            Input("species-file-input", "contents"),
            Input("add-species-button", "n_clicks"),
            Input({"type": "remove-species", "index": dash.ALL}, "n_clicks"),
        ],
        [
            State("species-file-input", "filename"),
            State("app-config", "data"),
            State("species-list-container", "children"),
        ],
        prevent_initial_call=True,
    )
    def update_species_list(
        contents, add_clicks, remove_clicks, filename, config, current_list
    ):
        """Update the species list based on file upload or user actions."""
        if not config:
            return no_update, no_update

        # Create a copy of the current config
        new_config = dict(config)
        species_list = new_config.get("species_of_interest", [])

        # Handle file upload
        if contents and filename:
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string).decode("utf-8")

            # Parse the file content
            new_species = []
            for line in decoded.splitlines():
                species_name = line.strip()
                if species_name:
                    new_species.append({"name": species_name, "taxid": ""})

            # Replace the existing species list
            species_list = new_species

        # Handle add species button
        elif ctx.triggered_id == "add-species-button":
            species_list.append({"name": "", "taxid": ""})

        # Handle remove species button
        elif (
            ctx.triggered_id
            and isinstance(ctx.triggered_id, dict)
            and ctx.triggered_id.get("type") == "remove-species"
        ):
            index = ctx.triggered_id.get("index")
            if index is not None and 0 <= index < len(species_list):
                species_list.pop(index)

        # Update the config
        new_config["species_of_interest"] = species_list

        # Create the species list UI
        species_items = []
        for i, species in enumerate(species_list):
            species_items.append(
                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Input(
                                id={"type": "species-name", "index": i},
                                value=species.get("name", ""),
                                placeholder="Enter species name",
                                className="mb-2",
                            ),
                            width=10,
                        ),
                        dbc.Col(
                            dbc.Button(
                                "✕",
                                id={"type": "remove-species", "index": i},
                                color="danger",
                                size="sm",
                                className="mb-2",
                            ),
                            width=2,
                        ),
                    ]
                )
            )

        if not species_items:
            species_items = [
                html.P(
                    "No species of interest defined. Click 'Add Species' to add one."
                )
            ]

        return species_items, new_config

    # Update species names in config
    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Input({"type": "species-name", "index": dash.ALL}, "value"),
        State({"type": "species-name", "index": dash.ALL}, "id"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def update_species_names(values, ids, config):
        """Update species names in the configuration."""
        if not values or not ids or not config:
            return no_update

        # Create a copy of the current config
        new_config = dict(config)
        species_list = new_config.get("species_of_interest", [])

        # Update the species names
        for i, (value, id_dict) in enumerate(zip(values, ids)):
            if value is not None:
                index = id_dict.get("index")
                if 0 <= index < len(species_list):
                    species_list[index]["name"] = value

        # Update the config
        new_config["species_of_interest"] = species_list

        return new_config