"""
Plotly chart builders for the HTML export report.

Split out of ``ReportGenerator`` (core/export/report_generator.py, 2026-08-16
code-size remediation): these are self-contained pure builders -- data in,
a Figure or JSON string out, no instance state touched -- and were the
largest single contributor to that file exceeding the code-size ratchet's
800-line file cap (scripts/check_code_size.py). ``ReportGenerator._build_charts``
keeps a thin delegating wrapper so the class's public surface (and its
existing monkeypatch-based tests) are unaffected.
"""

import logging
from typing import Any, Dict, List

import plotly.graph_objects as go
import plotly.io as pio

logger = logging.getLogger(__name__)


def fig_to_json(fig: go.Figure) -> str:
    """Serialize a Plotly figure to JSON for template embedding."""
    return pio.to_json(fig, validate=False)


def create_classification_donut(
    classified: int, unclassified: int,
    title: str = "", compact: bool = False,
) -> go.Figure:
    """Create classification donut chart for the report."""
    total = classified + unclassified
    if total == 0:
        fig = go.Figure()
        fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=200, margin=dict(l=10, r=10, t=30, b=10))
        return fig

    rate = classified / total * 100
    if rate >= 80:
        rate_color = "#28a745"
    elif rate >= 60:
        rate_color = "#ffc107"
    else:
        rate_color = "#dc3545"

    fig = go.Figure(go.Pie(
        labels=["Classified", "Unclassified"],
        values=[classified, unclassified],
        hole=0.6,
        marker=dict(
            colors=["#007bff", "#dee2e6"],
            line=dict(color="#ffffff", width=2)
        ),
        textinfo="percent",
        textposition="outside",
        hovertemplate="<b>%{label}</b><br>Count: %{value:,}<br>%{percent}<extra></extra>",
    ))

    fig.add_annotation(
        text=f"<b>{rate:.0f}%</b><br><span style='font-size:10px'>classified</span>",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=20, color=rate_color),
    )

    height = 220 if compact else 300
    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=14)),
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, x=0.5, xanchor="center"),
    )
    return fig


def create_organism_bar(
    organisms: List[Dict[str, Any]], title: str = "",
) -> go.Figure:
    """Create horizontal bar chart of organism abundance."""
    if not organisms:
        fig = go.Figure()
        fig.add_annotation(text="No organisms detected", x=0.5, y=0.5, showarrow=False)
        return fig

    names = [o["name"][:40] for o in reversed(organisms)]
    reads = [o["reads"] for o in reversed(organisms)]
    abundances = [o["abundance"] for o in reversed(organisms)]

    fig = go.Figure(go.Bar(
        y=names,
        x=reads,
        orientation="h",
        marker=dict(color="#007bff", line=dict(color="#343a40", width=0.5)),
        hovertemplate="<b>%{y}</b><br>Reads: %{x:,}<br>Abundance: %{customdata:.2f}%<extra></extra>",
        customdata=abundances,
    ))

    height = max(250, len(organisms) * 25 + 80)
    fig.update_layout(
        title=dict(text=f"Top Organisms - {title}", x=0.5, font=dict(size=14)),
        xaxis=dict(title="Read Count"),
        yaxis=dict(title=""),
        height=height,
        margin=dict(l=200, r=30, t=40, b=40),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return fig


def build_charts(data: Dict[str, Any]) -> Dict[str, str]:
    """Build all Plotly charts for the report and serialize each to JSON."""
    charts = {}

    # Classification donut (aggregated)
    charts["classification_donut"] = fig_to_json(
        create_classification_donut(
            data["classified_total"],
            data["unclassified_total"],
            title="Overall Classification"
        )
    )

    # Per-sample donuts
    for sample, sdata in data.get("per_sample", {}).items():
        key = f"donut_{sample}"
        charts[key] = fig_to_json(
            create_classification_donut(
                sdata["classified"],
                sdata["unclassified"],
                title=sample,
                compact=True,
            )
        )

        # Organism abundance bar chart
        if sdata.get("organisms"):
            bar_key = f"organisms_{sample}"
            charts[bar_key] = fig_to_json(
                create_organism_bar(sdata["organisms"], title=sample)
            )

    return charts


_PLOTLY_CDN_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def find_local_plotly_js(offline_mode: bool = False) -> str:
    """Plotly.js source for inline embedding, or "" when no local bundle.

    Moved from ReportGenerator._get_plotly_js (code-size gate); behavior
    unchanged. In offline mode a CDN reference is useless (and a dangling
    external request when the report is opened), so the caller must not
    emit one -- see _build_html_report. The degradation is surfaced loudly
    rather than silently shipping a chart-less "self-contained" report.
    """
    from pathlib import Path

    try:
        import dash
        dash_dir = Path(dash.__file__).parent
        # Dash bundles plotly.js in its package
        candidates = [
            dash_dir / "dcc" / "plotly.min.js",
            dash_dir / "dcc" / "async-plotlyjs.js",
        ]
        # Also check plotly's own bundled JS
        import plotly
        plotly_dir = Path(plotly.__file__).parent
        candidates.append(plotly_dir / "package_data" / "plotly.min.js")

        for candidate in candidates:
            if candidate.exists():
                logger.info("Using local plotly.js from %s", candidate)
                return candidate.read_text(encoding="utf-8")
    except (ImportError, AttributeError, FileNotFoundError, PermissionError,
            OSError, UnicodeDecodeError):
        pass

    if offline_mode:
        logger.error(
            "No local plotly.js bundle found and offline_mode is set: "
            "the exported report's charts will not render. Install plotly "
            "with its bundled package_data, or export with network access."
        )
    else:
        logger.warning(
            "Could not find local plotly.js bundle. "
            "Report will reference CDN: %s", _PLOTLY_CDN_URL
        )
    return ""
