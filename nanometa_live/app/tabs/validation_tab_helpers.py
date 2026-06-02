"""
Pure helpers for the Validation tab.

Extracted from validation_tab.py so the registration function there stays focused
on Dash callback declarations. These filter/format/summarise validation result
lists and build the dropdown/pagination/placeholder components from plain data,
with no Dash ``app`` capture, so they are unit-testable in isolation.
validation_tab.py re-exports these names.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from dash import html
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from nanometa_live.core.parsers.paf_coverage_parser import (
    parse_paf_coverage,
    aggregate_contig_coverage,
    CoverageData,
)

logger = logging.getLogger(__name__)


# Cards rendered before the "Show all N" expander kicks in.
_CARD_LIST_INITIAL_LIMIT = 30


def _build_coverage_selector_options(
    data: Optional[Dict[str, Any]],
    current_value: Optional[str],
):
    """Group minimap2 validation results into per-sample sections.

    Closes P1-T06 from docs/audit-2026-04-28-throughput-ux.md: a
    24-barcode x 5-species run produces ~120 flat entries; grouping
    by sample turns the dropdown into 24 small sections separated by
    disabled header rows that the dcc.Dropdown's type-to-filter still
    matches against. ``__header__:`` sentinel values guard the
    selection logic from accidentally picking a header row.

    Returns:
        Tuple of (options list, default value or None).
    """
    if not data or not data.get("results"):
        return [], None

    per_sample: Dict[str, List[Dict[str, Any]]] = {}
    sample_order: List[str] = []
    seen = set()
    for r in data["results"]:
        method = r.get("validation_method", "blast")
        if method not in ("minimap2", "both"):
            continue
        sample_id = r.get("sample_id", "")
        taxid = r.get("taxid", "")
        key = f"{sample_id}_{taxid}"
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "label": f"{r.get('species', 'Unknown')} (taxid {taxid})",
            "value": key,
        }
        if sample_id not in per_sample:
            per_sample[sample_id] = []
            sample_order.append(sample_id)
        per_sample[sample_id].append(entry)

    options: List[Dict[str, Any]] = []
    for sample_id in sample_order:
        options.append({
            "label": f"-- {sample_id} ({len(per_sample[sample_id])} species) --",
            "value": f"__header__:{sample_id}",
            "disabled": True,
        })
        options.extend(per_sample[sample_id])

    valid_values = {o["value"] for o in options if not o.get("disabled")}
    if current_value and current_value in valid_values:
        return options, current_value

    first_value = next(
        (o["value"] for o in options if not o.get("disabled")),
        None,
    )
    return options, first_value


def _build_paginated_card_list(
    cards: List[Any],
    show_all: bool,
    show_all_button_id: str,
) -> html.Div:
    """Wrap a list of result cards with a "showing N of M" footer + button.

    When ``show_all`` is False, only the first ``_CARD_LIST_INITIAL_LIMIT``
    cards are rendered with a button below offering to expand. When True
    (or when the list fits under the cap), every card is rendered with
    just the count footer. Empty lists return an empty Div.
    """
    total = len(cards)
    if total == 0:
        return html.Div([])

    visible_cards = cards if show_all or total <= _CARD_LIST_INITIAL_LIMIT \
        else cards[:_CARD_LIST_INITIAL_LIMIT]
    truncated = total - len(visible_cards)

    footer = []
    if truncated > 0:
        footer.append(
            html.Div(
                [
                    html.Span(
                        f"Showing {len(visible_cards)} of {total} results.",
                        className="text-muted me-2",
                    ),
                    dbc.Button(
                        f"Show all {total}",
                        id=show_all_button_id,
                        color="link",
                        size="sm",
                        n_clicks=0,
                        className="p-0",
                    ),
                ],
                className="text-center small mt-3 pt-2 border-top",
            )
        )
    elif total > _CARD_LIST_INITIAL_LIMIT:
        footer.append(
            html.Div(
                f"Showing all {total} results.",
                className="text-center small text-muted mt-3 pt-2 border-top",
            )
        )

    return html.Div(visible_cards + footer)


def _filter_by_method(results, method):
    """Filter validation results by method.

    Args:
        results: List of result dicts from validation-data-store.
        method: 'blast' or 'minimap2'.

    Returns:
        Filtered list of result dicts.
    """
    if method == "blast":
        return [r for r in results if r.get("validation_method", "blast") != "minimap2"]
    else:  # minimap2
        return [r for r in results if r.get("validation_method") in ("minimap2", "both")]


def _filter_results_by_sample(results, selected_sample):
    """Filter validation results to a single sample.

    Treats ``"All Samples"`` and any falsy value as "no filter applied"
    -- matches the convention used by ``load_kraken_data`` on the
    Dashboard and Organism tabs.

    Args:
        results: List of result dicts (each with ``sample_id``).
        selected_sample: The current value of the ``selected-sample``
            store, or None / ``"All Samples"``.

    Returns:
        Filtered list of result dicts.
    """
    if not selected_sample or selected_sample == "All Samples":
        return list(results)
    return [r for r in results if r.get("sample_id") == selected_sample]


def _format_scope_text(selected_sample):
    """Build the scope line for the validation tab's intro banner."""
    if selected_sample and selected_sample != "All Samples":
        return f"Currently showing: {selected_sample}"
    return (
        "Currently showing: all samples (use the sample selector at "
        "the top of the dashboard to narrow to one)."
    )


def _format_criteria_text(config):
    """Build the criteria line for the validation tab's intro banner.

    Pulls the active thresholds from config so the operator always
    sees the live cutoffs, not the documented defaults.
    """
    cfg = config or {}
    identity = cfg.get("validation_identity_threshold", 90)
    hit_rate = cfg.get("validation_hit_rate_threshold", 0.5)
    mapq = cfg.get("minimap2_min_mapq", 10)
    try:
        identity_str = f"{float(identity):.0f}%"
    except (TypeError, ValueError):
        identity_str = "90%"
    try:
        hit_rate_str = f"{float(hit_rate):.0%}"
    except (TypeError, ValueError):
        hit_rate_str = "50%"
    try:
        mapq_str = str(int(mapq))
    except (TypeError, ValueError):
        mapq_str = "10"
    return (
        f"Confirmed: hit rate >= {hit_rate_str} of classified reads "
        f"AND mean identity >= {identity_str}. "
        f"Partial: at least half the hit-rate threshold OR within 90% "
        f"of the identity floor. "
        f"Low Confidence: below both. "
        f"Minimap2 also requires alignment MAPQ >= {mapq_str}."
    )


def _compute_summary(results):
    """Compute summary stats from a validation result list.

    Returns the four per-status species counts AND the aggregate
    read totals across all results so the Validation Summary card
    can show "X of Y reads validated" in addition to the species
    bucket counts.

    Returns:
        ``{
            "confirmed": int,
            "partial": int,
            "low_confidence": int,
            "no_data": int,
            "reads_validated": int,
            "reads_total": int,
        }``
    """
    counts = {
        "confirmed": 0,
        "partial": 0,
        "low_confidence": 0,
        "no_data": 0,
        "reads_validated": 0,
        "reads_total": 0,
    }
    for r in results:
        status = r.get("status", "no_data")
        if status == "confirmed":
            counts["confirmed"] += 1
        elif status == "partial":
            counts["partial"] += 1
        elif status in ("low", "uncertain", "rejected"):
            counts["low_confidence"] += 1
        else:
            counts["no_data"] += 1
        try:
            counts["reads_validated"] += int(r.get("validated_reads", 0) or 0)
            counts["reads_total"] += int(r.get("total_reads", 0) or 0)
        except (TypeError, ValueError):
            continue
    return counts


def _load_real_coverage(
    selected_key: str,
    config: Optional[dict],
    min_mapq: int,
    batch_id: Optional[str] = None,
) -> Optional[CoverageData]:
    """Load coverage from a real PAF file.

    ``batch_id`` selects which PAF to read:

    - ``None`` (default, "cumulative" view) -> the canonical flat PAF
      ``validation/minimap2/<sample>_taxid<tid>.paf``, which the realtime
      cumulative aggregator keeps current (falling back to the on-demand PAF).
    - a batch id -> the preserved per-batch PAF
      ``validation/minimap2/batch/<sample>_taxid<tid>_<batch_id>.paf``.

    Returns None if no PAF file exists or if the file has no alignments
    passing the min_mapq filter.
    """
    if not config:
        return None

    results_dir = config.get("results_output_directory") or config.get("main_dir", "")
    if not results_dir:
        return None

    # selected_key format: "{sample_id}_{taxid}" where taxid is numeric
    parts = selected_key.rsplit("_", 1)
    if len(parts) != 2:
        return None
    sample_id, taxid_str = parts

    mm2 = Path(results_dir) / "validation" / "minimap2"
    if batch_id:
        candidates = [mm2 / "batch" / f"{sample_id}_taxid{taxid_str}_{batch_id}.paf"]
    else:
        candidates = [
            mm2 / f"{sample_id}_taxid{taxid_str}.paf",
            Path(results_dir) / "on_demand_validation" / f"{sample_id}_{taxid_str}_ondemand.paf",
        ]

    for paf_path in candidates:
        if paf_path.exists():
            cov_dict = parse_paf_coverage(paf_path, min_mapq=min_mapq)
            if cov_dict:
                return aggregate_contig_coverage(cov_dict)
            logger.info(
                "PAF file found but has no alignments passing min_mapq=%d: %s",
                min_mapq, paf_path,
            )
            return None

    return None


def _batch_selector_state(config: Optional[dict], view_mode: Optional[str],
                          current_value: Optional[str]):
    """Compute the view-controls visibility, batch-dropdown column visibility,
    options, and value from the available per-batch outputs.

    Returns ``(controls_style, col_style, options, value)``. The whole control
    row is hidden when no per-batch data exists (batch-mode run / pre-realtime),
    so default behaviour is unchanged; the batch dropdown shows only in
    single-batch view.
    """
    hidden = {"display": "none"}
    batch_ids = _enumerate_batch_ids(config)
    if not batch_ids:
        return hidden, hidden, [], None
    # Label numeric batch ids as "Batch N" for clarity; keep raw label otherwise.
    options = [
        {"label": (f"Batch {b}" if b.isdigit() else b), "value": b}
        for b in batch_ids
    ]
    value = current_value if current_value in batch_ids else batch_ids[0]
    col_style = {} if view_mode == "batch" else hidden
    return {}, col_style, options, value


def _enumerate_batch_ids(config: Optional[dict]) -> List[str]:
    """List batch ids that have preserved per-batch validation outputs.

    Scans ``validation/minimap2/batch`` and ``validation/blast/batch`` for the
    realtime per-batch files named ``<sample>_taxid<tid>_<batch_id>.<ext>`` and
    returns the distinct ``<batch_id>`` values, most recent first. Empty when no
    per-batch data exists (e.g. a batch-mode run), so the UI can hide the
    per-batch option.
    """
    if not config:
        return []
    results_dir = config.get("results_output_directory") or config.get("main_dir", "")
    if not results_dir:
        return []

    # <sample>_taxid<digits>_<batch_id>.<ext>  -> capture <batch_id>
    pattern = re.compile(r"_taxid\d+_(?P<batch>.+?)\.(?:paf|blast\.tsv|minimap2_stats\.json|blast_stats\.json)$")
    batch_ids: set = set()
    for tool in ("minimap2", "blast"):
        batch_dir = Path(results_dir) / "validation" / tool / "batch"
        if not batch_dir.is_dir():
            continue
        for f in batch_dir.iterdir():
            m = pattern.search(f.name)
            if m:
                batch_ids.add(m.group("batch"))
    # batch_id is the per-sample batch sequence number assigned by nanometanf's
    # taxonomic_classification (an integer counter, 0,1,2,... incremented as each
    # batch arrives; a given organism appears only in the batches its reads
    # landed in, so the set is sparse). Sort numerically so the most recent batch
    # is first; fall back to lexical for any non-numeric id scheme.
    if batch_ids and all(b.isdigit() for b in batch_ids):
        return sorted(batch_ids, key=int, reverse=True)
    return sorted(batch_ids, reverse=True)


def _create_empty_identity_plot() -> go.Figure:
    """Create an empty placeholder identity plot."""
    fig = go.Figure()
    fig.add_annotation(
        text="No identity data available",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="#9CA3AF"),
    )
    fig.update_layout(
        title=dict(
            text="Match Quality by Species",
            font=dict(size=14, color="#374151"),
        ),
        xaxis_title="Species",
        yaxis_title="Match Quality (%)",
        template="plotly_white",
        height=350,
        margin=dict(l=50, r=30, t=50, b=60),
        font=dict(family="Arial, sans-serif", size=12),
    )
    return fig
