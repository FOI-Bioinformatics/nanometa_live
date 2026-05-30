"""
Pure helpers for the Configuration tab.

Extracted from config_tab.py so the registration function there stays focused on
Dash callback declarations. config_tab.py re-exports these names.
"""

from datetime import datetime

from dash import html
import dash_bootstrap_components as dbc


def _build_config_list_items(configs):
    """Build ListGroupItem components for a list of config metadata dicts."""
    items = []
    for i, config in enumerate(configs):
        timestamp = config.get("timestamp", "Unknown")
        try:
            dt = datetime.fromisoformat(timestamp)
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass

        filename = config.get("filename", "Unknown")
        is_autosave = filename == "last-session.yaml"

        buttons = [
            dbc.Button(
                "Load",
                id={"type": "load-config-item", "index": i},
                color="primary",
                size="sm",
                className="me-1",
            ),
        ]
        if not is_autosave:
            buttons.append(
                dbc.Button(
                    html.I(className="bi bi-trash"),
                    id={"type": "delete-config-item", "index": i},
                    color="danger",
                    outline=True,
                    size="sm",
                    title="Delete this preset",
                )
            )

        display_name = config.get("name", "Unnamed Configuration")
        if is_autosave:
            display_name = "Last Session (auto-saved)"

        items.append(dbc.ListGroupItem(
            [
                html.Div([
                    html.H5(display_name, className="mb-1"),
                    html.Small(f"Created: {timestamp}", className="text-muted"),
                ]),
                html.Div(buttons, className="d-flex align-items-center"),
            ],
            className="d-flex justify-content-between align-items-center",
        ))
    return items
