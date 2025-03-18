"""
Species list component for Nanometa Live.

This module defines a reusable component for managing the list of species of interest
in the application.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc


def create_species_list(species_data=None):
    """
    Create a component for managing species of interest.

    Args:
        species_data: List of dictionaries with species information

    Returns:
        A dash component representing the species list management UI
    """
    if not species_data:
        species_data = []

    # Create the species table
    species_rows = []
    for i, species in enumerate(species_data):
        species_rows.append(
            dbc.Row(
                [
                    # Species name input
                    dbc.Col(
                        dbc.Input(
                            id={"type": "species-name", "index": i},
                            value=species.get("name", ""),
                            placeholder="Enter species name",
                            className="mb-2",
                        ),
                        width=7,
                    ),
                    # Tax ID input (now editable)
                    dbc.Col(
                        dbc.Input(
                            id={"type": "species-taxid", "index": i},
                            value=species.get("taxid", ""),
                            placeholder="Enter/auto Tax ID",
                            className="mb-2",
                        ),
                        width=3,
                    ),
                    # Remove button
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

    # If no species, show a message
    if not species_rows:
        species_rows = [
            html.P(
                "No species of interest defined. Use the buttons below to add species.",
                className="text-muted",
            )
        ]

    # Add the add species button
    species_rows.append(
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Button(
                            "Add Species",
                            id="add-species-button",
                            color="primary",
                            size="sm",
                            className="mr-2",
                        ),
                        dbc.Button(
                            "Upload List",
                            id="upload-species-button",
                            color="secondary",
                            size="sm",
                            className="mr-2",
                        ),
                        dcc.Upload(
                            id="species-file-upload",
                            children=html.Div([]),
                            style={"display": "none"},
                        ),
                    ],
                    width=12,
                )
            ]
        )
    )

    # Create the species list container
    species_list = html.Div(
        [
            html.H5("Species of Interest", className="mt-3"),
            html.P(
                "Define the species you want to track in the analysis. You can manually enter Tax IDs or they will be auto-filled from the database.",
                className="text-muted",
            ),
            html.Div(id="species-list-container", children=species_rows),
        ]
    )

    return species_list