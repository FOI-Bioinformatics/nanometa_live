"""
Waiting-for-first-batch banner (U4, 2026-05-09 UX spec).

A subordinate INFO-blue banner that sits below the verdict banner while
the pipeline is running but no output has yet been written. The visual
treatment intentionally stays lighter than the verdict banner; the spec
calls out that this is informational, not a verdict.
"""

from __future__ import annotations

from dash import html
import dash_bootstrap_components as dbc


def waiting_for_first_batch_banner() -> html.Div:
    """Build the waiting banner (initially hidden via container style)."""
    return html.Div(
        [
            dbc.Spinner(
                size="sm",
                color="primary",
                type="border",
                spinner_class_name="me-3",
            ),
            html.Div(
                [
                    html.Div(
                        "Pipeline running. Waiting for first batch.",
                        className="fw-semibold",
                    ),
                    html.Div(
                        "Typically 30 to 90 seconds; depends on input "
                        "throughput and Kraken2 database load.",
                        className="small text-muted",
                    ),
                ]
            ),
            html.Div(
                id="waiting-banner-elapsed",
                className="ms-auto small text-muted",
            ),
        ],
        className="d-flex align-items-center",
        style={
            "backgroundColor": "#cfe2ff",
            "borderLeft": "6px solid #0d6efd",
            "border": "1px solid rgba(0, 0, 0, 0.08)",
            "borderRadius": "8px",
            "padding": "16px 24px",
            "marginTop": "12px",
            "minHeight": "64px",
        },
    )
