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
            Output("refresh-form-trigger", "data", allow_duplicate=True),
        ],
        Input({"type": "load-config-item", "index": dash.ALL}, "n_clicks"),
        State("available-configs", "children"),
        State("app-data-dir", "data"),
        prevent_initial_call=True,
    )
    def load_selected_config(n_clicks, available_configs_json, data_dir):
        """Load the selected configuration."""
        if not any(n_clicks) or not ctx.triggered:
            return no_update, no_update, no_update, no_update

        # Find which button was clicked
        triggered_id = ctx.triggered[0]["prop_id"]
        if "index" not in triggered_id:
            return no_update, no_update, no_update, no_update

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

    # Apply Config Changes Callback
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
            State("update-interval-input", "value"),
            State("danger-threshold-input", "value"),
            State("kraken-taxonomy-input", "value"),
            State("external-kraken-input", "value"),
            State("check-interval-input", "value"),
            State("memory-mapping-input", "value"),  # Changed from "on" to "value"
            State("blast-validation-input", "value"),  # Changed from "on" to "value"
            State("min-identity-input", "value"),
            State("cores-input", "value"),
            State("clean-temp-input", "value"),  # Changed from "on" to "value"
            State("app-config", "data"),
        ],
        prevent_initial_call=True,
)
    def apply_config_changes(
        n_clicks,
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
        """Apply configuration changes without saving to a file."""
        if not n_clicks:
            return no_update, no_update, no_update, no_update

        if not current_config:
            return no_update, no_update, {
                "title": "Error",
                "message": "No configuration to update",
                "color": "danger",
            }, False

        # Create a completely new config object to avoid reference issues
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

        # Handle boolean values consistently as true/false
        if memory_mapping is not None:
            config["kraken_memory_mapping"] = bool(memory_mapping)

        if blast_validation is not None:
            config["blast_validation"] = bool(blast_validation)

        if min_identity is not None:
            config["min_perc_identity"] = min_identity

        if cores is not None:
            # Set all core counts to the same value for simplicity
            config["snakemake_cores"] = cores
            config["kraken_cores"] = cores
            config["validation_cores"] = cores
            config["blast_cores"] = cores

        if clean_temp is not None:
            config["remove_temp_files"] = bool(clean_temp)

        return config, "✓ Applied!", {
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
                    return "Apply Changes";
                }, 1000);
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
                    return false;
                }, 3000);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("config-feedback-alert", "is_open", allow_duplicate=True),
        Input("config-feedback-alert", "is_open"),
        prevent_initial_call=True,
    )

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
            Input("memory-mapping-input", "value"),  # Changed from "on" to "value"
            Input("blast-validation-input", "value"),  # Changed from "on" to "value"
            Input("min-identity-input", "value"),
            Input("cores-input", "value"),
            Input("clean-temp-input", "value"),  # Changed from "on" to "value"
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

        # Handle boolean values consistently as true Python booleans
        if memory_mapping is not None:
            config["kraken_memory_mapping"] = bool(memory_mapping)

        if blast_validation is not None:
            config["blast_validation"] = bool(blast_validation)

        if min_identity is not None:
            config["min_perc_identity"] = min_identity

        if cores is not None:
            # Set all core counts to the same value for simplicity
            config["snakemake_cores"] = cores
            config["kraken_cores"] = cores
            config["validation_cores"] = cores
            config["blast_cores"] = cores

        if clean_temp is not None:
            config["remove_temp_files"] = bool(clean_temp)

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
            Output("memory-mapping-input", "value"),  # Changed from "on" to "value"
            Output("blast-validation-input", "value"),  # Changed from "on" to "value"
            Output("min-identity-input", "value"),
            Output("cores-input", "value"),
            Output("clean-temp-input", "value"),  # Changed from "on" to "value"
        ],
        [Input("app-config", "data"), Input("refresh-form-trigger", "data")],
    )
    def initialize_form_from_config(config, refresh_trigger):
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

        min_identity = config.get("min_perc_identity", 90)
        cores = config.get("snakemake_cores", 1)

        clean_temp = config.get("remove_temp_files", True)
        # Ensure it's a boolean regardless of stored format
        if isinstance(clean_temp, str):
            clean_temp = clean_temp == "yes" or clean_temp.lower() in ["true", "yes", "y", "1"]
        clean_temp = bool(clean_temp)

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

    @app.callback(
        [
            Output("species-list-container", "children"),
            Output("app-config", "data", allow_duplicate=True),
        ],
        [
            Input("app-config", "data"),  # Listen for config changes
            Input("species-file-input", "contents"),
            Input("add-species-button", "n_clicks"),
            Input({"type": "remove-species", "index": dash.ALL}, "n_clicks"),
            Input("refresh-form-trigger", "data")
        ],
        [
            State("species-file-input", "filename"),
            State("species-list-container", "children"),
        ],
        prevent_initial_call=True
    )
    def manage_species_list(
        config, contents, add_clicks, remove_clicks, refresh_trigger, filename, current_list
    ):
        """
        Single callback to handle all species list operations:
        - Initial loading of species from config
        - Adding/removing species
        - Uploading species files
        - Refreshing after config changes
        """

        if not config:
            return [html.P("No species of interest defined. Click 'Add Species' to add one.")], no_update

        # Get triggered component
        triggered_id = ctx.triggered_id if ctx.triggered else None

        # If triggered by app-config changes, just update UI, don't modify config
        if triggered_id == "app-config" or triggered_id == "refresh-form-trigger":
            species_items = []
            for i, species in enumerate(config.get("species_of_interest", [])):
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
                                width=7,
                            ),
                            dbc.Col(
                                dbc.Input(
                                    id={"type": "species-taxid", "index": i},
                                    value=species.get("taxid", ""),
                                    placeholder="Enter/auto Tax ID",
                                    className="mb-2",
                                ),
                                width=3,
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
                    html.P("No species of interest defined. Click 'Add Species' to add one.")
                ]

            return species_items, no_update

        # Handle file upload
        if triggered_id == "species-file-input" and contents:
            # Parse uploaded file
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string).decode("utf-8")

            # Process file content into species list
            species_list = []

            # Detect format (CSV, TSV, or plain text)
            if "," in decoded:
                delimiter = ","
            elif "\t" in decoded:
                delimiter = "\t"
            else:
                delimiter = None

            # Parse the file content
            for line in decoded.splitlines():
                if line.strip() == "":
                    continue

                if delimiter:
                    parts = line.split(delimiter)
                    species_name = parts[0].strip()
                    taxid = parts[1].strip() if len(parts) > 1 else ""
                else:
                    species_name = line.strip()
                    taxid = ""

                if species_name:
                    species_list.append({"name": species_name, "taxid": taxid})

            # Update config with new species
            new_config = dict(config)
            new_config["species_of_interest"] = species_list

            # Create UI elements for species
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
                                width=7,
                            ),
                            dbc.Col(
                                dbc.Input(
                                    id={"type": "species-taxid", "index": i},
                                    value=species.get("taxid", ""),
                                    placeholder="Enter/auto Tax ID",
                                    className="mb-2",
                                ),
                                width=3,
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

            return species_items, new_config

        # Handle "Add Species" button click
        if triggered_id == "add-species-button" and add_clicks:
            # Create a copy of current config
            new_config = dict(config)
            species_list = new_config.get("species_of_interest", [])

            # Add a new empty species entry
            species_list.append({"name": "", "taxid": ""})
            new_config["species_of_interest"] = species_list

            # Create UI elements for species
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
                                width=7,
                            ),
                            dbc.Col(
                                dbc.Input(
                                    id={"type": "species-taxid", "index": i},
                                    value=species.get("taxid", ""),
                                    placeholder="Enter/auto Tax ID",
                                    className="mb-2",
                                ),
                                width=3,
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

            return species_items, new_config

        # Handle "Remove Species" button click
        if isinstance(triggered_id, dict) and triggered_id.get("type") == "remove-species":
            # Get index of species to remove
            remove_idx = triggered_id.get("index")

            # Create a copy of current config
            new_config = dict(config)
            species_list = new_config.get("species_of_interest", [])

            # Remove the species at the specified index
            if 0 <= remove_idx < len(species_list):
                del species_list[remove_idx]
                new_config["species_of_interest"] = species_list

                # Create UI elements for remaining species
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
                                    width=7,
                                ),
                                dbc.Col(
                                    dbc.Input(
                                        id={"type": "species-taxid", "index": i},
                                        value=species.get("taxid", ""),
                                        placeholder="Enter/auto Tax ID",
                                        className="mb-2",
                                    ),
                                    width=3,
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
                        html.P("No species of interest defined. Click 'Add Species' to add one.")
                    ]

                return species_items, new_config

        # Default return
        return no_update, no_update

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

    # Add a new callback to handle taxid input changes
    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Input({"type": "species-taxid", "index": dash.ALL}, "value"),
        State({"type": "species-taxid", "index": dash.ALL}, "id"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def update_species_taxids(values, ids, config):
        """Update species taxids in the configuration."""
        if not values or not ids or not config:
            return no_update

        # Create a copy of the current config
        new_config = dict(config)
        species_list = new_config.get("species_of_interest", [])

        # Update the species taxids
        for i, (value, id_dict) in enumerate(zip(values, ids)):
            if value is not None:
                index = id_dict.get("index")
                if 0 <= index < len(species_list):
                    species_list[index]["taxid"] = value

        # Update the config
        new_config["species_of_interest"] = species_list

        return new_config

    @app.callback(
        Output("app-config", "data", allow_duplicate=True),
        Input("species-file-upload", "contents"),
        State("species-file-upload", "filename"),
        State("app-config", "data"),
        prevent_initial_call=True,
    )
    def upload_species_file(contents, filename, config):
        """Handle uploading a file with species names and taxids."""
        if not contents or not config:
            return no_update

        content_type, content_string = contents.split(",")
        decoded = base64.b64decode(content_string).decode("utf-8")

        # Create a copy of the current config
        new_config = dict(config)
        species_list = []

        # Detect format (CSV, TSV, or plain text)
        if "," in decoded:
            delimiter = ","
        elif "\t" in decoded:
            delimiter = "\t"
        else:
            delimiter = None

        # Parse the file content
        for line in decoded.splitlines():
            if delimiter:
                parts = line.split(delimiter)
                species_name = parts[0].strip()
                taxid = parts[1].strip() if len(parts) > 1 else ""
            else:
                species_name = line.strip()
                taxid = ""

            if species_name:
                species_list.append({"name": species_name, "taxid": taxid})

        # Update the config
        new_config["species_of_interest"] = species_list

        return new_config

    @app.callback(
        Output("external-kraken-input", "options"),
        Input("kraken-databases", "data")
    )
    def populate_kraken_database_options(databases):
        options = [{"label": "None (use local)", "value": ""}]

        for db_id, db_info in databases.items():
            label = f"{db_id} ({db_info.get('description', '')})"
            options.append({"label": label, "value": db_id})

        return options