"""Reports tab layout.

Surfaces run-level pipeline artifacts the dashboard did not previously expose:
the MultiQC + Nextflow execution reports (links/embed), the realtime performance
panel, and the assembly summary. Content is filled by the Reports-tab callback
(``register_reports_callbacks``) from the operator's current results directory.
"""

from __future__ import annotations

from dash import html
import dash_bootstrap_components as dbc


def create_reports_layout() -> html.Div:
    return html.Div([
        html.Div([
            html.H4([
                html.I(className="bi bi-journal-text me-2"),
                "Reports & Run Provenance",
            ], className="mb-1"),
            html.P(
                "Aggregated and run-level outputs produced by the pipeline: the "
                "MultiQC quality report, the Nextflow execution report/timeline, "
                "realtime throughput, and assembly summaries. These complement the "
                "operator views on the other tabs.",
                className="text-muted",
            ),
        ], className="mb-3"),
        # Filled by render_reports_content from the current results directory.
        dbc.Spinner(html.Div(id="reports-content"), color="primary", size="sm"),
    ], className="p-3")
