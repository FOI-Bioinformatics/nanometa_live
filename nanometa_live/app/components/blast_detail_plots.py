"""Per-read BLAST detail figures and renderers for the validation tab.

Companions to ``coverage_plots.py``: histograms of the per-read distributions
(identity, alignment length, bitscore) that the per-species summary discards,
plus a top-subject breakdown and a classification-confidence badge. All inputs
come from ``parse_blast_per_read`` / ``classification_confidence``; these
functions are pure figure/markup builders.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import plotly.graph_objects as go
from dash import html
import dash_bootstrap_components as dbc

import nanometa_live.app.utils.plotly_theme  # noqa: F401  (registers template)


def _histogram(values: List[float], title: str, x_title: str,
               color: str) -> go.Figure:
    fig = go.Figure()
    if values:
        fig.add_trace(go.Histogram(x=values, marker_color=color, nbinsx=30))
    fig.update_layout(
        template="nanometa",
        title=title,
        xaxis_title=x_title,
        yaxis_title="Reads",
        margin=dict(l=40, r=20, t=40, b=40),
        showlegend=False,
    )
    return fig


def create_identity_histogram_figure(distributions: Dict[str, List]) -> go.Figure:
    """Per-read percent-identity distribution."""
    return _histogram(
        distributions.get("pident", []),
        "Per-read identity", "Identity (%)", "#2c7fb8",
    )


def create_length_histogram_figure(distributions: Dict[str, List]) -> go.Figure:
    """Per-read alignment-length distribution."""
    return _histogram(
        distributions.get("length", []),
        "Per-read alignment length", "Alignment length (bp)", "#41b6c4",
    )


def create_bitscore_histogram_figure(distributions: Dict[str, List]) -> go.Figure:
    """Per-read bitscore distribution."""
    return _histogram(
        distributions.get("bitscore", []),
        "Per-read bitscore", "Bitscore", "#7fcdbb",
    )


_CONFIDENCE_COLORS = {"high": "success", "moderate": "warning", "low": "danger"}


def render_confidence(confidence: Optional[Dict[str, Any]]) -> Any:
    """Render the classification-confidence verdict as a badge + reason list."""
    if not confidence:
        return ""
    level = confidence.get("level", "low")
    color = _CONFIDENCE_COLORS.get(level, "secondary")
    score = confidence.get("score", 0.0)
    reasons = confidence.get("reasons", [])
    return dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Span("Classification confidence: ", className="fw-bold"),
                dbc.Badge(level.upper(), color=color, className="ms-1"),
                html.Span(f"  (score {score:.2f})", className="text-muted ms-2"),
            ], className="mb-2"),
            html.Ul([html.Li(r, className="small") for r in reasons],
                    className="mb-0"),
        ]),
        className="border mb-3",
    )


def top_subjects_columns() -> List[Dict[str, Any]]:
    """AG-Grid column defs for the top-subject breakdown table."""
    return [
        {"field": "sseqid", "headerName": "Reference subject", "flex": 2,
         "headerTooltip": "Reference accession the reads aligned to."},
        {"field": "reads", "headerName": "Reads", "flex": 1,
         "headerTooltip": "Number of reads whose best hit was this subject."},
        {"field": "mean_pident", "headerName": "Mean identity (%)", "flex": 1},
    ]


def per_read_columns() -> List[Dict[str, Any]]:
    """AG-Grid column defs for the per-read detail table."""
    return [
        {"field": "qseqid", "headerName": "Read", "flex": 2},
        {"field": "sseqid", "headerName": "Best hit", "flex": 2},
        {"field": "pident", "headerName": "Identity (%)", "flex": 1},
        {"field": "length", "headerName": "Aln length", "flex": 1},
        {"field": "bitscore", "headerName": "Bitscore", "flex": 1},
        {"field": "evalue", "headerName": "E-value", "flex": 1},
        {"field": "qcovs", "headerName": "Query cov (%)", "flex": 1},
    ]
