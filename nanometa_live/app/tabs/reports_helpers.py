"""Pure builders for the Reports tab (no Dash app capture; unit-testable).

Renders the run-level artifacts the pipeline produces but the GUI did not
previously surface: links to the MultiQC + Nextflow execution reports (gap 2),
the realtime performance panel (gap 3), and the assembly summary (gap 4).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go


def _kpi_tile(value: str, label: str, icon: str) -> dbc.Col:
    return dbc.Col(html.Div([
        html.I(className=f"bi {icon} text-primary"),
        html.H4(value, className="mb-0 mt-1"),
        html.Small(label, className="text-muted"),
    ], className="text-center"), md=True)


def _fmt(value: Any, suffix: str = "", nd: int = 1) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "--"
    if v >= 1000:
        return f"{v:,.0f}{suffix}"
    return f"{v:.{nd}f}{suffix}"


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


def build_realtime_performance_panel(stats: Optional[Dict[str, Any]]) -> Any:
    """Realtime throughput / trends / alerts panel, or empty in batch mode.

    ``stats`` is the output of ``realtime_stats_loader.load_realtime_stats``
    (None => batch run, render nothing). Shows throughput KPIs, a per-batch read
    trend, and any alerts.
    """
    if not stats:
        return ""
    perf = stats.get("performance", {})
    totals = stats.get("totals", {})
    session = stats.get("session", {})
    trends = stats.get("trends", {})
    alerts = stats.get("alerts", [])

    kpis = dbc.Row([
        _kpi_tile(_fmt(perf.get("reads_per_second"), "/s"), "Reads/sec", "bi-speedometer2"),
        _kpi_tile(_fmt(perf.get("files_per_second"), "/s"), "Files/sec", "bi-files"),
        _kpi_tile(_fmt(perf.get("batches_per_minute"), "/min"), "Batches/min", "bi-collection"),
        _kpi_tile(_fmt(totals.get("total_estimated_reads"), nd=0), "Total reads", "bi-bar-chart"),
        _kpi_tile(_fmt(session.get("total_batches"), nd=0), "Batches", "bi-stack"),
    ], className="g-2 mb-3")

    # Per-batch read trend (if available).
    reads = trends.get("batch_read_counts") or []
    trend = ""
    if reads:
        fig = go.Figure(go.Scatter(
            y=reads, x=list(range(1, len(reads) + 1)),
            mode="lines+markers", line=dict(color="#0d6efd"),
        ))
        fig.update_layout(
            height=220, margin=dict(l=40, r=10, t=10, b=30),
            xaxis_title="Batch", yaxis_title="Reads", paper_bgcolor="white",
            plot_bgcolor="white",
        )
        trend = dcc.Graph(figure=fig, config={"displayModeBar": False})

    # Alerts.
    alert_items = []
    _level_color = {"error": "danger", "warning": "warning", "info": "info"}
    for a in alerts[:25]:
        lvl = str(a.get("level", "info"))
        alert_items.append(dbc.ListGroupItem(
            [dbc.Badge(lvl.upper(), color=_level_color.get(lvl, "secondary"), className="me-2"),
             a.get("message", "")],
            className="py-1",
        ))
    alerts_block = (
        html.Div([html.Strong("Alerts", className="d-block mt-2 mb-1"),
                  dbc.ListGroup(alert_items, flush=True)])
        if alert_items else ""
    )

    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-activity me-2"),
            html.Strong("Live Performance"),
            html.Small(" (realtime run)", className="text-muted ms-1"),
        ]),
        dbc.CardBody([kpis, trend, alerts_block]),
    ], className="mb-4")


# A usable draft assembly of a bacterial genome needs roughly this depth;
# below LOW_COVERAGE_ASSEMBLY the contigs are fragments and the panel says so.
# Measured on the demo corpus: nothing in it reaches 2x (assembly audit,
# 2026-09-03), so this threshold is what makes the output honest rather than
# a tuning knob.
USABLE_ASSEMBLY_DEPTH = 30.0
LOW_COVERAGE_ASSEMBLY = 10.0


def _assembly_coverage(a: Dict[str, Any]) -> Optional[float]:
    """Median per-contig coverage, the number that says whether the rest mean
    anything.

    Flye states its mean coverage plainly in its own log and
    ``assembly_to_canonical.py`` keeps it per contig, but the summary block
    carries only contigs/length/N50/L50/circular/GC -- so the KPI row, which
    renders exactly the summary, never showed it. Measured on a real run: 63
    contigs at an N50 of 12,368 looked like a draft genome and was built at a
    median coverage of 4 (assembly audit, 2026-09-03).
    """
    values = [c.get("coverage") for c in (a.get("contigs") or [])
              if isinstance(c.get("coverage"), (int, float))]
    if not values:
        return None
    values.sort()
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


def _assembly_absent_card(body: Any) -> Any:
    """The Assembly card with an explanation instead of statistics."""
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-diagram-3 me-2"),
            html.Strong("Assembly"),
        ]),
        dbc.CardBody(body),
    ], className="mb-4")


def _assembly_absent_panel(enabled: Optional[bool],
                           failed_samples: Optional[List[str]]) -> Any:
    """Why there is no assembly, as a card rather than a blank space."""
    failed = [str(s) for s in (failed_samples or [])]
    if enabled is False:
        return _assembly_absent_card(
            dbc.Badge("Assembly not enabled", color="light",
                      text_color="muted", className="border"))
    if failed:
        more = f" +{len(failed) - 3} more" if len(failed) > 3 else ""
        return _assembly_absent_card([
            dbc.Badge("Assembly failed", color="danger", className="me-2"),
            html.Span(
                f"No assembly was produced. The pipeline isolated "
                f"{len(failed)} assembly task{'s' if len(failed) != 1 else ''} "
                f"({', '.join(failed[:3])}{more}), so the run continued "
                "without it. See the run log.",
                className="small"),
        ])
    if enabled:
        return _assembly_absent_card(
            html.Span("Assembly is enabled; no results yet.",
                      className="small text-muted"))
    return _assembly_absent_card(
        dbc.Badge("Not produced", color="light", text_color="muted",
                  className="border"))


def build_assembly_panel(assemblies: List[Dict[str, Any]],
                         enabled: Optional[bool] = None,
                         failed_samples: Optional[List[str]] = None) -> Any:
    """Per-sample assembly summary and contigs, or why there are none.

    ``assemblies`` is the output of ``assembly_loader.load_assembly_stats``.

    This used to return the empty string for an empty list, with the docstring
    "assembly not run, render nothing" -- so a run with assembly off, a run
    whose assemblies all failed, and a run still assembling were the same
    blank space. A failed assembly reached no surface at all (assembly audit,
    2026-09-03, A4). ``enabled`` and ``failed_samples`` separate those cases;
    ``enabled=None`` means the caller could not tell, and the panel says only
    that nothing was produced.
    """
    if not assemblies:
        return _assembly_absent_panel(enabled, failed_samples)
    blocks = []
    for a in assemblies:
        s = a.get("summary", {})
        coverage = _assembly_coverage(a)
        kpis = dbc.Row([
            _kpi_tile(_fmt(s.get("total_contigs"), nd=0), "Contigs", "bi-diagram-2"),
            _kpi_tile(_fmt(s.get("total_length"), nd=0), "Total bp", "bi-rulers"),
            _kpi_tile(_fmt(s.get("largest_contig"), nd=0), "Largest bp", "bi-arrows-expand"),
            _kpi_tile(_fmt(s.get("n50"), nd=0), "N50", "bi-bullseye"),
            _kpi_tile(_fmt(s.get("circular_contigs"), nd=0), "Circular", "bi-arrow-repeat"),
            _kpi_tile(f"{coverage:.0f}x" if coverage is not None else "--",
                      "Median depth", "bi-layers"),
        ], className="g-2 mb-2")
        # Top contigs by length.
        contigs = sorted(a.get("contigs", []), key=lambda c: c.get("length", 0), reverse=True)[:10]
        rows = [
            html.Tr([
                html.Td(c.get("name", "")),
                html.Td(f"{c.get('length', 0):,}"),
                html.Td(f"{c.get('coverage', 0):.1f}x" if c.get("coverage") else "--"),
                html.Td("yes" if c.get("is_circular") else "no"),
            ]) for c in contigs
        ]
        table = (
            dbc.Table([
                html.Thead(html.Tr([html.Th("Contig"), html.Th("Length"),
                                    html.Th("Depth"), html.Th("Circular")])),
                html.Tbody(rows),
            ], size="sm", striped=True, className="mb-0")
            if rows else html.Small("No contig detail.", className="text-muted")
        )
        # An assembly built at low coverage is a set of fragments, not a
        # genome, and the contig count and N50 read as though it were one.
        depth_note = None
        if coverage is not None and coverage < LOW_COVERAGE_ASSEMBLY:
            depth_note = dbc.Alert(
                f"Median contig depth {coverage:.0f}x. A usable draft of a "
                f"bacterial genome needs roughly "
                f"{USABLE_ASSEMBLY_DEPTH:.0f}x, so these contigs are "
                "fragments rather than a genome.",
                color="warning", className="py-2 px-3 small mb-2")
        blocks.append(html.Div([
            html.Strong(a.get("sample", ""), className="d-block mb-2"),
            kpis,
        ] + ([depth_note] if depth_note else []) + [table], className="mb-3"))

    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-diagram-3 me-2"),
            html.Strong("Assembly"),
        ]),
        dbc.CardBody(blocks),
    ], className="mb-4")


def build_taxpasta_panel(rows: List[Dict[str, Any]],
                         name_by_taxid: Optional[Dict[int, str]] = None,
                         top_n: int = 25) -> Any:
    """Cross-sample standardized abundance (taxpasta), or empty when none.

    ``rows`` are ``{sample, taxid, count}`` from ``taxpasta_loader``. Pivots to a
    taxon x sample matrix (top ``top_n`` taxa by total count) and labels taxa with
    ``name_by_taxid`` (from the Kraken2 data) since the taxpasta TSV has no names.
    """
    if not rows:
        return ""
    name_by_taxid = name_by_taxid or {}
    samples = sorted({r["sample"] for r in rows})

    by_taxid: Dict[int, Dict[str, int]] = {}
    totals: Dict[int, int] = {}
    for r in rows:
        tid, s, c = r["taxid"], r["sample"], r["count"]
        by_taxid.setdefault(tid, {})[s] = by_taxid.setdefault(tid, {}).get(s, 0) + c
        totals[tid] = totals.get(tid, 0) + c

    top = sorted(totals, key=totals.get, reverse=True)[:top_n]
    header = html.Thead(html.Tr(
        [html.Th("Taxon"), html.Th("Total")] + [html.Th(s) for s in samples]
    ))
    body_rows = []
    for tid in top:
        label = name_by_taxid.get(tid) or f"taxid {tid}"
        cells = [html.Td(f"{by_taxid[tid].get(s, 0):,}") for s in samples]
        body_rows.append(html.Tr(
            [html.Td(label), html.Td(f"{totals[tid]:,}")] + cells
        ))
    table = dbc.Table([header, html.Tbody(body_rows)],
                      size="sm", striped=True, hover=True, responsive=True,
                      className="mb-0")

    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-table me-2"),
            html.Strong("Standardized abundance (taxpasta)"),
            html.Small(f" - top {len(top)} taxa across {len(samples)} sample(s)",
                       className="text-muted ms-1"),
        ]),
        dbc.CardBody(table),
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
