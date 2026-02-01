"""
Sample selector component for Nanometa Live v2.0.

This module provides a reusable sample selection dropdown that can be
used across all tabs to filter data by sample (barcode).
"""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_sample_selector(include_label: bool = True, width_md: int = 6) -> dbc.Row:
    """
    Create a sample selector dropdown component.

    Args:
        include_label: Whether to include "Select Sample:" label
        width_md: Bootstrap column width (1-12)

    Returns:
        dbc.Row containing the sample selector dropdown

    Example:
        >>> # In a layout file
        >>> from nanometa_live.app.components.sample_selector import create_sample_selector
        >>>
        >>> layout = dbc.Container([
        >>>     create_sample_selector(),
        >>>     # ... rest of layout
        >>> ])
    """
    components = []

    if include_label:
        components.append(
            html.Label(
                "Select Sample:",
                className="fw-bold mb-2",
                htmlFor="sample-selector"
            )
        )

    components.append(
        dcc.Dropdown(
            id='sample-selector',
            options=[{'label': 'All Samples', 'value': 'All Samples'}],
            value='All Samples',
            clearable=False,
            className="mb-3",
            placeholder="Select a sample...",
            persistence=True,  # Remember selection across page reloads
            persistence_type='session'
        )
    )

    return dbc.Row([
        dbc.Col(components, md=width_md)
    ])


def create_compact_sample_selector(selector_id: str = "sample-selector-compact") -> html.Div:
    """
    Create a compact inline sample selector (no label, smaller width).

    Args:
        selector_id: Unique ID for this selector (default: "sample-selector-compact").
                     Use a unique ID if multiple selectors are needed on the same page.

    Returns:
        html.Div containing compact sample selector

    Example:
        >>> # For use in toolbar or compact spaces
        >>> toolbar = html.Div([
        >>>     html.Span("Sample: ", className="me-2"),
        >>>     create_compact_sample_selector(),
        >>> ], className="d-flex align-items-center")
    """
    return html.Div([
        dcc.Dropdown(
            id=selector_id,
            options=[{'label': 'All Samples', 'value': 'All Samples'}],
            value='All Samples',
            clearable=False,
            className="sample-selector-compact",
            persistence=True,
            persistence_type='session'
        )
    ], className="sample-selector-compact", style={'display': 'inline-block'})


def create_sample_info_badge(sample_count: int = 0) -> dbc.Badge:
    """
    Create an informational badge showing number of samples detected.

    Args:
        sample_count: Number of samples (excluding "All Samples")

    Returns:
        dbc.Badge component

    Example:
        >>> badge = create_sample_info_badge(5)
        >>> # Displays: "5 samples detected"
    """
    if sample_count == 0:
        text = "No samples detected"
        color = "secondary"
    elif sample_count == 1:
        text = "1 sample"
        color = "info"
    else:
        text = f"{sample_count} samples"
        color = "success"

    return dbc.Badge(
        text,
        color=color,
        className="ms-2",
        pill=True
    )
