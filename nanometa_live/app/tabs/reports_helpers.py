"""Pure builders for the Reports tab (no Dash app capture; unit-testable).

Renders the run-level artifacts the pipeline produces but the GUI did not
previously surface: links to the MultiQC + Nextflow execution reports (gap 2),
the realtime performance panel (gap 3), and the assembly summary (gap 4).
"""

from __future__ import annotations

from typing import Any, Dict, List

from dash import html
import dash_bootstrap_components as dbc


def build_pipeline_reports_card(reports: List[Dict[str, Any]]) -> dbc.Card:
    """Card linking the MultiQC + Nextflow reports that exist for the run.

    ``reports`` is the output of ``reports_loader.detect_reports``. Present
    reports get an "Open" link (new tab); absent ones are shown muted so the
    operator knows the artifact was not produced (e.g. MultiQC skipped/failed,
    or a batch run with no pipeline_info).
    """
    items = []
    for r in reports:
        if r["exists"]:
            action = dbc.Button(
                [html.I(className="bi bi-box-arrow-up-right me-1"), "Open"],
                href=r["url"], target="_blank", external_link=True,
                color="primary", size="sm", outline=True,
            )
        else:
            action = dbc.Badge("Not produced", color="light", text_color="muted",
                                className="border")
        items.append(
            dbc.ListGroupItem([
                html.Div([
                    html.Strong(r["label"]),
                    html.Br(),
                    html.Small(r["desc"], className="text-muted"),
                ]),
                html.Div(action, className="ms-auto"),
            ], className="d-flex justify-content-between align-items-center")
        )

    any_present = any(r["exists"] for r in reports)
    body: List[Any] = [dbc.ListGroup(items, flush=True)]
    if not any_present:
        body.append(
            html.Small(
                "No pipeline reports found in this results directory. MultiQC and "
                "the Nextflow execution report appear here after a run completes.",
                className="text-muted d-block mt-2",
            )
        )

    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-file-earmark-text me-2"),
            html.Strong("Pipeline Reports"),
        ]),
        dbc.CardBody(body),
    ], className="mb-4")


def build_multiqc_embed(reports: List[Dict[str, Any]]) -> Any:
    """Inline iframe of the MultiQC report when present, else empty."""
    mqc = next((r for r in reports if r["key"] == "multiqc" and r["exists"]), None)
    if not mqc:
        return ""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-clipboard-data me-2"),
            html.Strong("MultiQC (embedded)"),
        ]),
        dbc.CardBody(
            html.Iframe(
                src=mqc["url"],
                style={"width": "100%", "height": "70vh", "border": "0"},
            ),
            className="p-0",
        ),
    ], className="mb-4")
