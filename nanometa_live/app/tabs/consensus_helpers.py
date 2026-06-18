"""Pure helpers for the Consensus sub-tab.

Kept free of Dash callback wiring (mirrors the ``*_tab.py`` ->
``*_helpers.py`` split used across the dashboard) so the selector building and
the stats rendering are unit-testable without a running app.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from dash import html
import dash_bootstrap_components as dbc


def build_consensus_selector_options(
    results: Optional[List[Dict[str, Any]]],
    current_value: Optional[str],
    species_by_taxid: Optional[Dict[Any, str]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Group consensus results into per-sample sections for the dropdown.

    Mirrors ``_build_coverage_selector_options``: per-sample disabled header
    rows with a ``__header__:`` sentinel, keyed ``f"{sample_id}_{taxid}"``.
    Preserves the current selection when it is still valid.
    """
    if not results:
        return [], None

    name_map = species_by_taxid or {}
    per_sample: Dict[str, List[Dict[str, Any]]] = {}
    sample_order: List[str] = []
    seen = set()
    for r in results:
        sample_id = r.get("sample_id", "")
        taxid = r.get("taxid", "")
        key = f"{sample_id}_{taxid}"
        if key in seen:
            continue
        seen.add(key)
        species = (
            r.get("species")
            or name_map.get(taxid)
            or name_map.get(str(taxid))
        )
        label = f"{species} (taxid {taxid})" if species else f"taxid {taxid}"
        if not r.get("has_sequence", r.get("consensus_length", 0) > 0):
            label += " - no consensus"
        entry = {"label": label, "value": key}
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
    # Prefer a species that actually produced a consensus for the default
    # selection, so the panel does not open on a "no consensus" warning.
    with_seq = {
        f"{r.get('sample_id', '')}_{r.get('taxid', '')}"
        for r in results
        if r.get("has_sequence", r.get("consensus_length", 0) > 0)
    }
    default_value = next(
        (o["value"] for o in options
         if not o.get("disabled") and o["value"] in with_seq),
        None,
    )
    if default_value is None:
        default_value = next(
            (o["value"] for o in options if not o.get("disabled")),
            None,
        )
    return options, default_value


def find_consensus_result(
    results: Optional[List[Dict[str, Any]]],
    selected_key: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Return the consensus result dict whose ``sample_id_taxid`` matches."""
    if not results or not selected_key:
        return None
    for r in results:
        if f"{r.get('sample_id', '')}_{r.get('taxid', '')}" == selected_key:
            return r
    return None


def _badge(label: str, value: str, color: str = "secondary") -> Any:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.Div(value, className="h5 mb-0"),
                html.Small(label, className="text-muted"),
            ], className="py-2 text-center"),
            className="border",
        ),
        md="auto",
    )


def consensus_stats_badges(result: Optional[Dict[str, Any]]) -> Any:
    """Render the depth-window stats for the selected consensus.

    Returns an empty string when nothing is selected, an informational card
    when the organism produced no consensus, or a row of stat badges otherwise.
    """
    if not result:
        return ""

    span = int(result.get("span", 0) or 0)
    if span <= 0:
        return dbc.Alert(
            [
                html.I(className="bi bi-info-circle me-2"),
                "No consensus could be built for this organism - the read depth "
                "did not reach the threshold over any region.",
            ],
            color="warning",
            className="mb-0",
        )

    cons_len = int(result.get("consensus_length", 0) or 0)
    n_count = int(result.get("n_count", 0) or 0)
    n_pct = (n_count / cons_len * 100) if cons_len else 0.0
    mean_depth = float(result.get("mean_depth", 0.0) or 0.0)
    cov_start = int(result.get("covered_start", 0) or 0)
    cov_end = int(result.get("covered_end", 0) or 0)
    mapped = int(result.get("mapped_reads", 0) or 0)
    ref_name = result.get("ref_name", "") or "reference"

    return html.Div([
        dbc.Row([
            _badge("Consensus length", f"{cons_len:,} bp"),
            _badge("Covered region", f"{cov_start:,}-{cov_end:,}"),
            _badge("Mean depth", f"{mean_depth:.0f}x"),
            _badge("Masked (N)", f"{n_pct:.1f}%",
                   color="warning" if n_pct > 10 else "secondary"),
            _badge("Mapped reads", f"{mapped:,}"),
        ], className="g-2 mb-2"),
        html.Small(
            f"Aligned to {ref_name}. The consensus is trimmed to the covered "
            "span; interior positions below the depth threshold are masked N.",
            className="text-muted",
        ),
    ])
