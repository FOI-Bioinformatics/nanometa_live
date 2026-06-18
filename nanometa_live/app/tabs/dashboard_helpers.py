"""
Helper functions for the Dashboard tab.

Extracted from dashboard_tab.py to keep the callback registration file
focused on Dash callback definitions. These helpers are pure-ish data
transformations (status computation, banner content building, sample
data collection, alert generation, etc.) called from within the
register_dashboard_callbacks() block.
"""

import os
import glob
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
import logging

from dash import html
import dash_bootstrap_components as dbc

from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.qc_loaders import (
    get_qc_stats,
    load_nanoplot_stats,
    load_seqkit_stats,
)
from nanometa_live.core.utils.alert_engine import get_alert_engine
from nanometa_live.core.utils.pathogen_database import check_for_dangerous_pathogens
from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
from nanometa_live.app.utils.callback_helpers import (
    safe_load_kraken_data,
    get_classification_stats,
    format_bp,
)
from nanometa_live.app.layouts.dashboard_layout import create_alerts_list
from nanometa_live.app.components.modern_components import (
    LastUpdatedBadge,
)
from nanometa_live.app.components.pathogen_alert import (
    CriticalPathogenAlert,
    HighRiskPathogenAlert,
    WatchedSpeciesAlert,
)

logger = logging.getLogger(__name__)


def _count_input_files(nanopore_dir: str) -> int:
    """
    Count input FASTQ files in the nanopore output directory.

    Supports both flat directories and barcoded subdirectories.

    Args:
        nanopore_dir: Path to nanopore output directory

    Returns:
        Total count of FASTQ files (.fastq, .fastq.gz, .fq, .fq.gz)
    """
    if not nanopore_dir or not os.path.exists(nanopore_dir):
        return 0

    count = 0
    extensions = ('.fastq', '.fastq.gz', '.fq', '.fq.gz')

    # Check for files in main directory
    for f in os.listdir(nanopore_dir):
        if f.lower().endswith(extensions):
            count += 1

    # Also check for barcoded subdirectories (barcode01, barcode02, etc.)
    for subdir in os.listdir(nanopore_dir):
        subdir_path = os.path.join(nanopore_dir, subdir)
        if os.path.isdir(subdir_path) and subdir.startswith('barcode'):
            for f in os.listdir(subdir_path):
                if f.lower().endswith(extensions):
                    count += 1

    return count


def _make_banner_content(
    icon_name: str,
    icon_color: str,
    heading: str,
    sub: str,
    run_state: str,
    time_elapsed: str,
    sub_color: str = "inherit",
    show_icon_mobile: bool = False,
    last_updated_str: Optional[str] = None,
    icon_extra_class: str = "",
    triggering_samples: Optional[List[str]] = None,
    total_sample_count: Optional[int] = None,
    auto_stop_remaining_s: Optional[int] = None,
    triggering_pathogens: Optional[List[str]] = None,
) -> dbc.Row:
    """
    Build the inner content for the Zone 1 clinical verdict banner.

    Args:
        icon_name: Bootstrap icon name (without 'bi-' prefix, e.g. 'shield-check')
        icon_color: CSS hex color for the icon
        heading: H3 verdict text
        sub: Subtitle text below the heading
        run_state: Run state badge text (ACTIVE/STANDBY/COMPLETE)
        time_elapsed: Formatted elapsed time string
        sub_color: Explicit text color for subtitle (WCAG AA compliance)
        show_icon_mobile: If True, icon is always visible; if False, hidden below 768px
        last_updated_str: Formatted "Last updated HH:MM:SS" string for right column
        icon_extra_class: Extra CSS class(es) appended to icon element (e.g. 'spin')

    Returns:
        dbc.Row with left verdict column and right run-state column
    """
    run_state_color = (
        "success" if run_state == "ACTIVE"
        else "info" if run_state == "COMPLETE"
        else "secondary"
    )
    # Icon visibility: ACTION REQUIRED always shows; others hide on mobile
    icon_visibility = "" if show_icon_mobile else "d-none d-sm-inline"
    icon_class = f"bi bi-{icon_name} {icon_visibility} {icon_extra_class}".strip()

    right_children = [
        dbc.Badge(run_state, color=run_state_color,
                  style={"borderRadius": "8px"}),
        html.Div(time_elapsed, className="small text-muted mt-1"),
    ]
    if last_updated_str:
        right_children.append(
            html.Div(last_updated_str,
                     style={"fontSize": "12px", "color": "#6c757d", "marginTop": "2px"})
        )

    # U3: realtime-timeout countdown. Only renders when the backend
    # surfaced a positive remaining-seconds value; class escalates as
    # the deadline approaches. No new colour tokens -- text utility
    # classes only.
    if auto_stop_remaining_s is not None and auto_stop_remaining_s > 0:
        from nanometa_live.app.utils.countdown import (
            countdown_classes,
            format_countdown,
        )
        text_class, icon_class = countdown_classes(auto_stop_remaining_s)
        formatted = format_countdown(auto_stop_remaining_s)
        right_children.append(
            html.Div(
                [
                    html.I(className=f"bi {icon_class} me-1"),
                    html.Span(f"Auto-stop in {formatted}"),
                ],
                className=f"small {text_class} mt-1",
                role="status",
                **{"aria-live": "polite"},
            )
        )

    # Triggering-sample attribution subhead (closes P0-T02 from
    # docs/audit-2026-04-28-throughput-ux.md). Only renders when the
    # caller passed a non-empty triggering_samples list, which is
    # restricted to ACTION REQUIRED today since that is the only state
    # where the operator needs to know which barcode is contaminated.
    verdict_text_children = [
        html.H3(heading, className="dashboard-verdict-h3 mb-0"),
        html.P(sub, className="dashboard-verdict-sub mb-0",
               style={"color": sub_color}),
    ]
    # Name the pathogens that crossed their alert threshold -- the operator's
    # first question on ACTION REQUIRED is "which ones?". Up to 5 inline, the
    # rest summarized; the full list is on the Organisms tab.
    if triggering_pathogens:
        shown_p = triggering_pathogens[:5]
        overflow_p = max(0, len(triggering_pathogens) - len(shown_p))
        listed = ", ".join(shown_p)
        if overflow_p > 0:
            listed += f" (+{overflow_p} more)"
        verdict_text_children.append(
            html.P(
                [html.Strong("Above threshold: "), listed],
                className="dashboard-verdict-pathogens mb-0 mt-1",
                style={"color": sub_color, "fontSize": "14px", "fontWeight": "600"},
            )
        )
    if triggering_samples:
        # Top 3 named inline; tail summarized as "(+N more)"
        shown = triggering_samples[:3]
        overflow = max(0, len(triggering_samples) - len(shown))
        names = ", ".join(shown)
        if overflow > 0:
            attribution = f"Triggered by: {names} (+{overflow} more"
            if total_sample_count:
                attribution += f" of {total_sample_count} samples"
            attribution += ")"
        else:
            n_total = total_sample_count or len(triggering_samples)
            attribution = (
                f"Triggered by: {names} ({len(triggering_samples)} of "
                f"{n_total} samples)"
            )
        verdict_text_children.append(
            html.P(
                attribution,
                className="dashboard-verdict-attribution mb-0 mt-1",
                style={
                    "color": sub_color,
                    "fontSize": "13px",
                    "fontWeight": "500",
                    "opacity": "0.85",
                },
            )
        )

    return dbc.Row([
        dbc.Col([
            html.Div([
                html.I(
                    className=icon_class,
                    style={"fontSize": "40px", "color": icon_color, "flexShrink": "0"}
                ),
                html.Div(verdict_text_children, className="ms-0 ms-sm-3")
            ], className="d-flex align-items-center")
        ], md=9),
        dbc.Col([
            html.Div(right_children, className="text-end")
        ], md=3, className="d-flex align-items-center justify-content-end")
    ], className="align-items-center g-0")


def _verdict_banner_style(bg_color: str, border_color: str) -> dict:
    """
    Return inline style dict for the Zone 1 verdict banner container.

    Args:
        bg_color: Background color hex
        border_color: Border color hex

    Returns:
        CSS style dict
    """
    return {
        # CLAUDE.md Zone 1 spec: background colour is the answer, the
        # 6px LEFT border is the accent. A full border (every side)
        # competes with the bg colour for visual weight; the left-only
        # accent keeps the hero treatment on the colour while the
        # subtle 1px outline gives the card edge definition.
        "backgroundColor": bg_color,
        "borderLeft": f"6px solid {border_color}",
        "border": "1px solid rgba(0, 0, 0, 0.08)",
        "borderLeftWidth": "6px",
        "borderLeftColor": border_color,
        "borderRadius": "8px",
        "padding": "24px 32px",
        "minHeight": "120px",
    }


# ----------------------------------------------------------------------------
# Pathogen Report modal: reference links, confidence, and detection metadata.
#
# Kept as pure builders so the report's external links and derived fields can
# be unit-tested without a running app. The guiding rule is honesty: never
# render a link that resolves to a wrong or nonexistent record, and never imply
# a confidence the read support does not back.
# ----------------------------------------------------------------------------

# Federal Select Agent Program list -- the authoritative, maintained successor
# to CDC's retired bioterrorism A/B/C category page. The old CDC NIOSH
# chemical-agent URL was both dead (404) and topically wrong for a microbial
# tool.
SELECT_AGENTS_URL = "https://www.selectagents.gov/sat/list.htm"
_NCBI_TAX_URL = "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={taxid}"


def _ref_button(label: str, href: str) -> html.A:
    return html.A(
        [html.I(className="bi bi-box-arrow-up-right me-1"), label],
        href=href,
        target="_blank",
        rel="noopener noreferrer",
        className="btn btn-outline-secondary btn-sm me-2 mb-1",
    )


def build_reference_links(
    ncbi_taxid: Optional[int] = None,
    ncbi_link: Optional[str] = None,
    gtdb_link: Optional[str] = None,
) -> List[Any]:
    """Build the report's external-reference buttons, omitting any link that
    would send the operator to a wrong or nonexistent record.

    - NCBI Taxonomy: shown only when a resolved NCBI link is known, or the
      taxid is a real NCBI taxid (not a GTDB/custom pseudo-taxid). A link to
      the wrong taxon is worse than no link.
    - GTDB: shown only when a resolved GTDB link exists (from taxonomy-ID
      validation); never reconstructed from a name, to avoid inventing a dead
      link.
    - Select Agents (FSAP): always shown -- a live, authoritative reference.
    """
    from nanometa_live.core.utils.genome_manager import _is_real_ncbi_taxid

    buttons: List[Any] = []
    ncbi_href = ncbi_link or (
        _NCBI_TAX_URL.format(taxid=int(ncbi_taxid))
        if _is_real_ncbi_taxid(ncbi_taxid) else None
    )
    if ncbi_href:
        buttons.append(_ref_button("NCBI Taxonomy", ncbi_href))
    if gtdb_link:
        buttons.append(_ref_button("GTDB", gtdb_link))
    buttons.append(_ref_button("Select Agents (FSAP)", SELECT_AGENTS_URL))
    return [
        html.Label("References", className="text-muted small d-block mb-2"),
        html.Div(buttons),
    ]


def compute_detection_confidence(reads, abundance_pct=None) -> str:
    """Detection confidence derived from read support -- NOT a statistical
    confidence interval. More reads backing a classification means a more
    trustworthy call. Returns 'N/A' when no read count is available so the
    report never implies confidence it cannot support.
    """
    try:
        r = int(reads)
    except (TypeError, ValueError):
        return "N/A"
    if r >= 100:
        return "High"
    if r >= 20:
        return "Moderate"
    if r >= 1:
        return "Low"
    return "N/A"


def _meta_row(label: str, value: Any, badge: Optional[str] = None) -> html.Div:
    val = (
        dbc.Badge(value, color=badge, className="ms-1")
        if badge else html.Span(value)
    )
    return html.Div(
        [html.Span(f"{label}: ", className="text-muted"), val],
        className="mb-1",
    )


def build_detection_meta(
    detected_at: Optional[str] = None,
    taxonomy_validated: bool = False,
    validation_date: Optional[str] = None,
    lineage: Optional[List[str]] = None,
    gtdb_taxonomy: Optional[str] = None,
    on_watchlist: bool = True,
) -> Any:
    """Compact detection-metadata block for the report modal.

    Covers the report's information gaps: a reported-at timestamp, the
    taxonomy-ID validation status (deliberately labelled "Taxonomy ID" so it
    is not confused with the confirmatory BLAST/minimap2 results on the
    Validation tab), and the organism lineage when known. Returns "" when
    there is nothing to show.
    """
    items: List[Any] = []
    if detected_at:
        items.append(_meta_row("Reported", detected_at))
    if taxonomy_validated:
        txt = "Validated"
        if validation_date:
            txt += f" ({str(validation_date)[:10]})"
        items.append(_meta_row("Taxonomy ID", txt, badge="success"))
    elif on_watchlist:
        items.append(_meta_row("Taxonomy ID", "Not yet validated", badge="secondary"))
    if lineage:
        items.append(_meta_row("Lineage", " > ".join(lineage)))
    elif gtdb_taxonomy:
        items.append(_meta_row("GTDB lineage", gtdb_taxonomy))
    if not items:
        return ""
    return html.Div(items, className="small")


def _report_error_payload(taxid: Any, err: Exception) -> List[Any]:
    """Modal payload shown when the report body could not be assembled.

    The View Report modal must still open on a genuine click; a silent
    callback exception would leave the operator looking at an unchanged page,
    indistinguishable from a hung app. This returns an open modal that names
    the organism and states the failure instead of raising.
    """
    return [
        True,                                   # is_open
        f"TaxID {taxid}",                       # name
        "",                                     # common_name
        "",                                     # annotation
        "Unknown",                              # category
        "Unknown",                              # bsl
        "N/A",                                  # reads
        "N/A",                                  # abundance
        "Unknown",                              # confidence
        str(taxid),                             # taxid
        "Review classification results manually.",  # action
        "secondary",                            # alert color
        f"The full pathogen report could not be built: {err}",  # notes
        "",                                     # references
        html.Div([
            html.I(className="bi bi-exclamation-triangle me-2"),
            "Report unavailable",
        ], className="alert alert-warning text-center py-2"),    # threat banner
        "",                                     # detection meta
        {"taxid": taxid},                       # store data
    ]


def build_report_payload(taxid: Any, config: Dict[str, Any],
                         selected_sample: Optional[str]) -> List[Any]:
    """Assemble the 17 outputs for the pathogen View Report modal.

    Pure data/component assembly extracted from the ``handle_view_report``
    callback so the build path is unit-testable and wrapped in a single
    ``try/except``: a genuine click always opens the modal with either the
    full report or a legible error body, never a silent 500.
    """
    try:
        return _build_report_payload_inner(taxid, config, selected_sample)
    except Exception as err:  # noqa: BLE001 - last-resort UI guard
        logger.exception("build_report_payload failed for taxid %s", taxid)
        return _report_error_payload(taxid, err)


def _lookup_organism_reads(taxid: Any, config: Dict[str, Any],
                           selected_sample: Optional[str]) -> Dict[str, Any]:
    """Read count / abundance / name / rank for ``taxid`` from Kraken2 data."""
    out = {"reads": "N/A", "reads_int": None, "abundance": "N/A",
           "name": None, "rank": None}
    try:
        main_dir = (config.get("results_output_directory", "")
                    or config.get("main_dir", "")) if config else ""
        if main_dir:
            kraken_df = load_kraken_data(main_dir, selected_sample)
            if not kraken_df.empty and taxid:
                match = kraken_df[kraken_df["taxid"] == int(taxid)]
                if not match.empty:
                    row = match.iloc[0]
                    out["reads_int"] = int(row.get('reads', 0))
                    out["reads"] = f"{out['reads_int']:,}"
                    out["abundance"] = f"{row.get('%', 0):.1f}%"
                    out["name"] = str(row.get("name", "")).strip()
                    out["rank"] = str(row.get("rank", ""))
    except Exception as e:
        logger.debug("Kraken2 lookup for taxid %s: %s", taxid, e)
    return out


def _resolve_report_pathogen(taxid: Any):
    """Resolve ``taxid`` to a pathogen record, NCBI taxid, and watchlist entry.

    Returns ``(pathogen, ncbi_taxid, wl_entry)``; ``pathogen`` may be a built-in
    record, a watchlist-derived pseudo-record, or None.
    """
    from nanometa_live.core.utils.pathogen_database import get_pathogen_by_taxid
    from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection

    pathogen = get_pathogen_by_taxid(taxid) if taxid else None
    ncbi_taxid = taxid

    if not pathogen and taxid:
        mapping_collection = get_mapping_collection()
        if mapping_collection:
            for mapped_ncbi_taxid, mapping in mapping_collection.mappings.items():
                if mapping.db_taxid == taxid:
                    ncbi_taxid = mapped_ncbi_taxid
                    pathogen = get_pathogen_by_taxid(ncbi_taxid)
                    if pathogen:
                        break

    wl_entry = None
    try:
        active_entries = get_watchlist_manager().get_active_entries()
        wl_entry = active_entries.get(ncbi_taxid) or active_entries.get(taxid)
        if wl_entry is None and isinstance(taxid, int):
            for e in active_entries.values():
                if getattr(e, "db_taxid", None) == taxid:
                    wl_entry = e
                    break
    except Exception as e:
        logger.debug("Watchlist enrichment lookup failed: %s", e)

    if not pathogen and wl_entry is not None:
        from types import SimpleNamespace
        pathogen = SimpleNamespace(
            name=wl_entry.name,
            common_name=wl_entry.common_name or "",
            threat_level=wl_entry.threat_level,
            bsl=wl_entry.bsl_level,
            category=wl_entry.category or "Watchlist",
            notes=wl_entry.notes or "",
            action_required=wl_entry.action_required or "Follow laboratory protocols",
            organism_type=wl_entry.organism_type,
            annotation=wl_entry.annotation or "",
        )
    return pathogen, ncbi_taxid, wl_entry


def _unwatched_payload(taxid, ncbi_taxid, reads, detected_at) -> List[Any]:
    """Modal payload for an organism that is not on any active watchlist."""
    display_name = reads["name"] or f"TaxID: {taxid}"
    return [
        True, display_name, "Not in pathogen watchlist", "",
        reads["rank"] or "Unknown", "Unknown", reads["reads"], reads["abundance"],
        compute_detection_confidence(reads["reads_int"]), str(taxid),
        "Follow standard laboratory biosafety protocols", "secondary",
        "This organism is not in any active watchlist. Review classification results for context.",
        build_reference_links(ncbi_taxid=ncbi_taxid),
        html.Div([
            html.I(className="bi bi-info-circle me-2"), "Not on watchlist",
        ], className="alert alert-secondary text-center py-2"),
        build_detection_meta(detected_at=detected_at, on_watchlist=False),
        {"taxid": taxid, "ncbi_taxid": ncbi_taxid},
    ]


def _pathogen_payload(pathogen, taxid, ncbi_taxid, wl_entry, reads, detected_at) -> List[Any]:
    """Modal payload for a watchlist/known pathogen, with threat styling."""
    threat_level = pathogen.threat_level
    if hasattr(threat_level, 'value'):
        threat_level = threat_level.value
    threat_colors = {
        "critical": ("danger", "#8b0000", "bi-exclamation-octagon-fill"),
        "high": ("warning", "#dc3545", "bi-exclamation-triangle-fill"),
        "moderate": ("info", "#fd7e14", "bi-eye-fill"),
        "low": ("secondary", "#17a2b8", "bi-info-circle"),
    }
    alert_color, banner_color, banner_icon = threat_colors.get(
        threat_level, ("secondary", "#6c757d", "bi-question-circle")
    )
    icon_el = html.I(className=f"bi {banner_icon} me-2", style={"fontSize": "20px"})
    threat_banner = html.Div([
        icon_el,
        html.Strong(f"{threat_level.upper()} THREAT LEVEL", style={"fontSize": "16px"}),
    ], className=f"alert alert-{alert_color} text-center py-2 mb-0",
       style={"borderLeft": f"5px solid {banner_color}"})

    bsl_val = pathogen.bsl
    if hasattr(bsl_val, 'value'):
        bsl_val = bsl_val.value
    bsl_text = f"BSL-{bsl_val}" if bsl_val else "BSL Unknown"

    references = build_reference_links(
        ncbi_taxid=ncbi_taxid,
        ncbi_link=getattr(wl_entry, "ncbi_link", None),
        gtdb_link=getattr(wl_entry, "gtdb_link", None),
    )
    detection_meta = build_detection_meta(
        detected_at=detected_at,
        taxonomy_validated=bool(getattr(wl_entry, "validated", False)),
        validation_date=getattr(wl_entry, "validation_date", None),
        lineage=getattr(wl_entry, "lineage", None),
        gtdb_taxonomy=getattr(wl_entry, "gtdb_taxonomy", None),
        on_watchlist=wl_entry is not None,
    )
    annotation = (getattr(wl_entry, "annotation", "")
                  or getattr(pathogen, "annotation", "") or "")
    return [
        True, pathogen.name, pathogen.common_name or "No common name",
        annotation,
        pathogen.category or "Uncategorized", bsl_text, reads["reads"],
        reads["abundance"], compute_detection_confidence(reads["reads_int"]),
        str(ncbi_taxid), pathogen.action_required, alert_color,
        pathogen.notes or "No additional notes available.", references,
        threat_banner, detection_meta,
        {"taxid": taxid, "name": pathogen.name, "threat_level": threat_level},
    ]


def _build_report_payload_inner(taxid: Any, config: Dict[str, Any],
                                selected_sample: Optional[str]) -> List[Any]:
    """Inner builder for :func:`build_report_payload` (may raise)."""
    reads = _lookup_organism_reads(taxid, config, selected_sample)
    pathogen, ncbi_taxid, wl_entry = _resolve_report_pathogen(taxid)
    detected_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not pathogen:
        return _unwatched_payload(taxid, ncbi_taxid, reads, detected_at)
    return _pathogen_payload(pathogen, taxid, ncbi_taxid, wl_entry, reads, detected_at)


# ----------------------------------------------------------------------------
# Clinical verdict-banner decision logic (Zone 1).
#
# The state machine below is the safety-critical core of the dashboard: it
# decides whether the operator sees ACTION REQUIRED, MONITORING, ALL CLEAR,
# SCREENING IN PROGRESS, or STANDBY. It is kept as a pure function so the
# decision can be unit-tested exhaustively in isolation from the Dash callback,
# the file I/O (Kraken load, per-sample attribution), and the component build.
# The callback computes the input booleans and the `dangerous` hit list, calls
# select_verdict(), then renders the returned descriptor.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictDescriptor:
    """Describes which verdict banner to render, without building components.

    Carries every argument needed by _make_banner_content and
    _verdict_banner_style. ``needs_attribution`` signals to the callback that
    the per-sample triggering attribution I/O should run for this state (only
    ACTION REQUIRED today).
    """
    state: str
    icon: str
    icon_color: str
    title: str
    subtitle: str
    sub_color: str
    bg_color: str
    border_color: str
    icon_extra_class: str = ""
    show_icon_mobile: bool = False
    needs_attribution: bool = False


def _screening_descriptor() -> VerdictDescriptor:
    """SCREENING IN PROGRESS: pipeline running, first results pending."""
    return VerdictDescriptor(
        state="SCREENING",
        icon="arrow-repeat", icon_color="#084298",
        title="SCREENING IN PROGRESS", subtitle="First results pending",
        sub_color="#084298", bg_color="#cfe2ff", border_color="#0d6efd",
        icon_extra_class="spin",
    )


def _standby_descriptor() -> VerdictDescriptor:
    """STANDBY: no analysis active and no data to summarise."""
    return VerdictDescriptor(
        state="STANDBY",
        icon="pause-circle", icon_color="#6c757d",
        title="STANDBY", subtitle="Start an analysis to begin",
        sub_color="#6c757d", bg_color="#f8f9fa", border_color="#6c757d",
    )


def _classify_dangerous(dangerous: List[Dict[str, Any]]) -> Tuple[list, list]:
    """Split watchlist hits into (critical, high_risk) buckets.

    ``high`` and ``high_risk`` are treated as the same escalation tier; both,
    along with ``critical``, drive the ACTION REQUIRED verdict.
    """
    critical = [d for d in dangerous if d.get("threat_level") == "critical"]
    high_risk = [d for d in dangerous
                 if d.get("threat_level") in ("high", "high_risk")]
    return critical, high_risk


def _action_required_subtitle(n_found: int, n_watched: int,
                              validation_has_results: bool) -> str:
    """Subtitle for ACTION REQUIRED.

    n_found counts only entries above each pathogen's alert_threshold; the
    Organisms tab lists every watchlist hit without that gate, so the two
    counters legitimately differ. The wording makes the threshold gate
    explicit and flags when confirmatory validation has not yet run.
    """
    sub = f"{n_found} of {n_watched} watched pathogens above alert threshold"
    if not validation_has_results:
        sub += " — pending confirmatory validation"
    return sub


def select_verdict(
    *,
    has_config: bool,
    pipeline_running: bool,
    overall_status_starting: bool,
    main_dir_available: bool,
    kraken_has_data: bool,
    dangerous: List[Dict[str, Any]],
    n_watched: int,
    validation_has_results: bool,
) -> VerdictDescriptor:
    """Pure decision: pick the verdict banner state from the analysis inputs.

    Mirrors the original update_verdict_banner control flow exactly:

    1. No config -> SCREENING when running, otherwise STANDBY.
    2. overall_status == "starting" -> SCREENING (takes priority over data).
    3. Results directory present with Kraken data -> classify the watchlist
       hits: any critical/high-risk hit -> ACTION REQUIRED; other hits ->
       MONITORING; no hits -> ALL CLEAR.
    4. Results directory present but no data yet and still running -> SCREENING.
    5. Everything else (no results dir, idle with no data, load failure) ->
       STANDBY.
    """
    if not has_config:
        return _screening_descriptor() if pipeline_running else _standby_descriptor()

    if overall_status_starting:
        return _screening_descriptor()

    if main_dir_available and kraken_has_data:
        if dangerous:
            critical, high_risk = _classify_dangerous(dangerous)
            if critical or high_risk:
                return VerdictDescriptor(
                    state="ACTION_REQUIRED",
                    icon="exclamation-octagon-fill", icon_color="#8b0000",
                    title="ACTION REQUIRED",
                    subtitle=_action_required_subtitle(
                        len(dangerous), n_watched, validation_has_results),
                    sub_color="#721c24", bg_color="#f8d7da",
                    border_color="#8b0000",
                    show_icon_mobile=True, needs_attribution=True,
                )
            return VerdictDescriptor(
                state="MONITORING",
                icon="eye-fill", icon_color="#fd7e14",
                title="MONITORING", subtitle="Moderate-risk species found",
                sub_color="#664d03", bg_color="#fff3cd", border_color="#fd7e14",
            )
        return VerdictDescriptor(
            state="ALL_CLEAR",
            icon="shield-check", icon_color="#28a745",
            title="ALL CLEAR",
            subtitle=f"0 of {n_watched} watched pathogens above alert threshold",
            sub_color="#155724", bg_color="#d4edda", border_color="#28a745",
        )

    # Results directory present but no rows yet, pipeline still producing them.
    if main_dir_available and pipeline_running:
        return _screening_descriptor()

    return _standby_descriptor()


def _get_idle_alerts() -> Tuple:
    """Return idle state for the alerts callback (D3d, 3 outputs)."""
    empty_alerts = html.Div([
        html.I(className="bi bi-check-circle text-success", style={"fontSize": "48px"}),
        html.H5("No Active Alerts", className="mt-3 mb-2"),
        html.P("System is operating normally", className="text-muted mb-0")
    ], className="text-center py-4")
    return (empty_alerts, "0", "secondary")


def _get_error_alerts(error_msg: str) -> Tuple:
    """Return error state for the alerts callback (D3d, 3 outputs)."""
    error_alert = [{
        "message": f"Error loading dashboard data: {error_msg}",
        "severity": "danger",
        "timestamp": "Just now"
    }]
    return (create_alerts_list(error_alert), "1", "danger")


def _calculate_overall_status(
    main_dir: str,
    config: Dict[str, Any],
    available_samples: List[str],
    pipeline_running: bool = False
) -> Dict[str, Any]:
    """
    Calculate overall analysis status from available data.

    Args:
        main_dir: Main analysis directory
        config: Application configuration
        available_samples: List of sample names
        pipeline_running: Whether the pipeline is actively running

    Returns:
        Dict with overall status metrics
    """
    visualization_only = config.get("visualization_only", False)

    # Filter out "All Samples" pseudo-sample
    real_samples = [s for s in available_samples if s != "All Samples"]
    total_samples = len(real_samples)

    # Load Kraken data for all samples (with safe error handling)
    kraken_df = safe_load_kraken_data(main_dir, "All Samples")

    # Calculate metrics. Use root.cumul_reads + unclassified.cumul_reads
    # (i.e. the total number of reads classified plus those rejected),
    # not sum(reads) which only counts per-rank assignments and
    # collapses to 0 when every read is parked at root level (the
    # degenerate-input case caught by the 2026-05-06 audit).
    classified, unclassified, _ = get_classification_stats(kraken_df)
    total_reads = classified + unclassified

    # Estimate quality score from data (simplified)
    quality_score = _estimate_quality_score(main_dir, kraken_df)

    # Count organisms (species + genus level, >= 1 read, matching Organisms tab)
    organisms_detected = 0
    if not kraken_df.empty:
        org_df = kraken_df[kraken_df["rank"].isin(["S", "G"])]
        org_df = org_df[org_df["taxid"] > 1]
        organisms_detected = len(org_df[org_df["reads"] >= 1])

    # Determine overall status
    if visualization_only and not pipeline_running:
        overall_status = "viewing"
    elif pipeline_running and total_reads == 0:
        overall_status = "starting"  # Pipeline running but no data processed yet
    elif quality_score is not None and quality_score < 60:
        overall_status = "warning"
    elif organisms_detected > 100:
        overall_status = "warning"  # Too many species might indicate contamination
    else:
        overall_status = "success"

    # Count samples processed (have Kraken output)
    samples_processed = _count_processed_samples(main_dir, real_samples)

    return {
        "status": overall_status,
        "total_reads": total_reads,
        "quality_score": quality_score,
        "organisms_detected": organisms_detected,
        "active_alerts": 0,  # Calculated later in _generate_alerts
        "samples_processed": samples_processed,
        "total_samples": total_samples
    }


def _estimate_quality_score(main_dir: str, kraken_df: pd.DataFrame) -> Optional[int]:
    """
    Estimate a simplified 0-100 quality score for nanopore data.

    Uses appropriate scaling for nanopore sequencing where Q10-15 is typical.
    Prioritizes seqkit Q20% metric when available as it's more meaningful.

    Args:
        main_dir: Main analysis directory
        kraken_df: Kraken classification dataframe

    Returns:
        Quality score 0-100, or None if cannot be calculated
    """
    try:
        score = None

        # Try seqkit first - Q20% is a meaningful quality metric
        qc_stats = get_qc_stats(main_dir)
        if qc_stats.get('source') == 'seqkit':
            q20_pct = qc_stats.get('q20_percent', 0)
            if q20_pct > 0:
                # Q20% directly maps to quality score (66% Q20 = 66 score)
                score = int(q20_pct)
                logger.debug(f"Quality score from seqkit Q20%: {score}")

        # Fallback to NanoPlot if seqkit not available
        if score is None:
            nanoplot_stats = load_nanoplot_stats(main_dir)
            if nanoplot_stats.get('mean_read_quality', 0) > 0:
                # For nanopore, Q10 is passing, Q15 is good, Q20+ is excellent
                # Scale: Q10 = 70%, Q15 = 85%, Q20 = 100%
                q_score = nanoplot_stats['mean_read_quality']
                if q_score >= 20:
                    score = 100
                elif q_score >= 15:
                    score = 85 + int((q_score - 15) * 3)  # 85-100 for Q15-20
                elif q_score >= 10:
                    score = 70 + int((q_score - 10) * 3)  # 70-85 for Q10-15
                else:
                    score = max(30, int(q_score * 7))  # Below Q10 is concerning
                logger.debug(f"Quality score from NanoPlot Q{q_score}: {score}")

        # Still no score? Use read length as proxy
        if score is None:
            if qc_stats.get('source') != 'none':
                avg_len = qc_stats.get('avg_read_length', 0)
                if avg_len > 3000:
                    score = 85
                elif avg_len > 2000:
                    score = 75
                elif avg_len > 1000:
                    score = 65
                else:
                    score = 50

        if score is None:
            return None

        # Adjust based on N50 (bonus for good read lengths)
        nanoplot_stats = load_nanoplot_stats(main_dir)
        n50 = nanoplot_stats.get('read_length_n50', 0)
        if n50 > 5000:
            score = min(100, score + 5)  # Bonus for long reads
        elif n50 < 1000:
            score -= 10  # Penalty for very short reads

        # Minor adjustment for classification rate (but don't over-penalize)
        if not kraken_df.empty and "reads" in kraken_df.columns:
            total_reads = kraken_df["reads"].sum()
            if total_reads > 0:
                unclassified = kraken_df[kraken_df["name"].str.contains("unclassified", case=False, na=False)]
                if not unclassified.empty:
                    unclassified_pct = (unclassified["reads"].sum() / total_reads) * 100
                    # Only penalize extremely high unclassified rates
                    if unclassified_pct > 70:
                        score -= 10
                    elif unclassified_pct > 50:
                        score -= 5

        return max(0, min(100, score))

    except Exception as e:
        logger.warning(f"Error estimating quality score: {e}")
        return None


def _count_processed_samples(main_dir: str, samples: List[str]) -> int:
    """Count how many samples have been processed (have Kraken output)."""
    kraken_dir = os.path.join(main_dir, "kraken2")
    if not os.path.exists(kraken_dir):
        return 0

    count = 0
    for sample in samples:
        # Check for sample-specific Kraken output
        sample_kraken = glob.glob(os.path.join(kraken_dir, f"*{sample}*.txt"))
        if sample_kraken:
            count += 1

    return count


def _generate_status_display(status: str) -> Tuple[Dict, str, str, str, str, str, str]:
    """
    Generate status indicator style, icon, text, subtitle, label text, label icon, and CSS class.

    Args:
        status: "starting", "success", "viewing", "warning", or "danger"

    Returns:
        Tuple of (style_dict, icon_class, status_text, subtitle_text,
                  label_text, label_icon, css_class)
    """
    status_config = {
        "starting": {
            "color": "#0d6efd",  # Blue
            "icon": "bi bi-hourglass-split",
            "text": "ACTIVE - Waiting for first results",
            "subtitle": "Pipeline is running, waiting for first results...",
            "label": "ACTIVE",
            "label_icon": "bi bi-hourglass-split ms-1",
            "css_class": "status-running"
        },
        "success": {
            "color": "#28a745",  # Green
            "icon": "bi bi-check-circle",
            "text": "ACTIVE - Analyzing samples",
            "subtitle": "All systems operating normally",
            "label": "ACTIVE",
            "label_icon": "bi bi-check-circle-fill ms-1",
            "css_class": "status-good"
        },
        "viewing": {
            "color": "#17a2b8",  # Teal/Info
            "icon": "bi bi-eye",
            "text": "COMPLETE - Results available",
            "subtitle": "Viewing existing results",
            "label": "COMPLETE",
            "label_icon": "bi bi-eye-fill ms-1",
            "css_class": "status-good"
        },
        "warning": {
            "color": "#ffc107",  # Amber
            "icon": "bi bi-exclamation-circle",
            "text": "ACTIVE - Review alerts below",
            "subtitle": "Review alerts below",
            "label": "ATTENTION",
            "label_icon": "bi bi-exclamation-triangle-fill ms-1",
            "css_class": "status-warning"
        },
        "danger": {
            "color": "#dc3545",  # Red
            "icon": "bi bi-x-circle",
            "text": "ERROR - Check setup",
            "subtitle": "Immediate action required - check settings",
            "label": "ERROR",
            "label_icon": "bi bi-x-circle-fill ms-1",
            "css_class": "status-danger"
        }
    }

    config = status_config.get(status, status_config["success"])

    # Background color is handled by CSS classes (status-good, status-warning, etc.)
    # Only set layout properties here to avoid inline vs CSS conflicts
    style = {
        "width": "80px",
        "height": "80px",
        "borderRadius": "50%",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
    }

    return (
        style,
        config["icon"],
        config["text"],
        config["subtitle"],
        config["label"],
        config["label_icon"],
        config["css_class"]
    )


def _format_time_elapsed(start_time: Optional[str]) -> str:
    """
    Format elapsed time since analysis start.

    Args:
        start_time: ISO format timestamp string

    Returns:
        Formatted time string (HH:MM:SS)
    """
    if not start_time:
        return "00:00:00"

    try:
        start_dt = datetime.fromisoformat(start_time)
        elapsed = datetime.now() - start_dt
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "00:00:00"


def _collect_samples_data(main_dir: str, available_samples: List[str]) -> List[Dict[str, Any]]:
    """
    Collect detailed sample data from analysis results.

    Args:
        main_dir: Main data directory
        available_samples: List of available sample names

    Returns:
        List of dictionaries containing sample information with enhanced columns
    """
    # Filter out "All Samples"
    real_samples = [s for s in available_samples if s != "All Samples"]

    if not real_samples:
        return []

    samples_data = []
    for sample in real_samples:
        try:
            # Load sample-specific Kraken data
            kraken_df = load_kraken_data(main_dir, sample)

            # Initialize default values
            reads = 0
            organisms = 0
            quality = "Pending"
            status = "Processing"
            total_bases = 0
            mean_q = 0.0
            n50 = 0
            class_rate = 0.0
            pass_rate = 100.0

            if not kraken_df.empty:
                # Calculate sample metrics from Kraken
                reads = int(kraken_df["reads"].sum())
                org_df = kraken_df[kraken_df["rank"].isin(["S", "G"])]
                org_df = org_df[org_df["taxid"] > 1]
                organisms = len(org_df[org_df["reads"] >= 1])

                # Classification rate calculation
                unclassified = kraken_df[kraken_df["name"].str.contains("unclassified", case=False, na=False)]
                if not unclassified.empty and reads > 0:
                    unclassified_pct = (unclassified["reads"].sum() / reads) * 100
                    class_rate = 100.0 - unclassified_pct

                    if unclassified_pct < 30:
                        quality = "Good"
                        status = "Complete"
                    elif unclassified_pct < 50:
                        quality = "Fair"
                        status = "Needs Review"
                    else:
                        quality = "Poor"
                        status = "Issue Detected"
                else:
                    quality = "Excellent"
                    status = "Complete"
                    class_rate = 100.0

            # Try seqkit stats FIRST (per-sample data from chopper QC)
            seqkit_df = load_seqkit_stats(main_dir, sample)
            if not seqkit_df.empty:
                # seqkit provides per-sample stats: sum_len, N50, AvgQual
                total_bases = int(seqkit_df['sum_len'].sum()) if 'sum_len' in seqkit_df.columns else 0
                n50 = int(seqkit_df['N50'].iloc[0]) if 'N50' in seqkit_df.columns and len(seqkit_df) > 0 else 0
                mean_q = float(seqkit_df['AvgQual'].iloc[0]) if 'AvgQual' in seqkit_df.columns and len(seqkit_df) > 0 else 0.0
                logger.debug(f"Sample {sample}: Using seqkit stats - bases={total_bases}, n50={n50}, mean_q={mean_q}")
            else:
                # Fall back to NanoPlot stats (may be per-sample or aggregated)
                nanoplot_stats = load_nanoplot_stats(main_dir, sample) if sample else {}
                if nanoplot_stats and nanoplot_stats.get("number_of_reads", 0) > 0:
                    total_bases = nanoplot_stats.get("total_bases", 0)
                    mean_q = nanoplot_stats.get("mean_read_quality", 0.0)
                    n50 = nanoplot_stats.get("read_length_n50", 0)
                    logger.debug(f"Sample {sample}: Using NanoPlot stats - bases={total_bases}, n50={n50}, mean_q={mean_q}")

            # Format bases for display
            if total_bases >= 1_000_000_000:
                bases_str = f"{total_bases / 1_000_000_000:.1f} Gb"
            elif total_bases >= 1_000_000:
                bases_str = f"{total_bases / 1_000_000:.1f} Mb"
            elif total_bases >= 1_000:
                bases_str = f"{total_bases / 1_000:.1f} kb"
            elif total_bases > 0:
                bases_str = f"{total_bases} bp"
            else:
                bases_str = "--"

            # Format N50 for display
            if n50 >= 1_000:
                n50_str = f"{n50 / 1_000:.1f}k"
            elif n50 > 0:
                n50_str = str(n50)
            else:
                n50_str = "--"

            samples_data.append({
                "sample": sample,
                "status": status,
                "quality": quality,
                "organisms": organisms,
                "reads": f"{reads:,}",
                "bases": bases_str,
                "mean_q": f"{mean_q:.1f}" if mean_q > 0 else "--",
                "n50": n50_str,
                "class_rate": f"{class_rate:.1f}%" if class_rate > 0 else "--",
                "pass_rate": f"{pass_rate:.1f}%",
            })

        except Exception as e:
            logger.error(f"Error processing sample {sample}: {e}")
            samples_data.append({
                "sample": sample,
                "status": "Error",
                "quality": "Error",
                "organisms": 0,
                "reads": "0",
                "bases": "--",
                "mean_q": "--",
                "n50": "--",
                "class_rate": "--",
                "pass_rate": "--",
            })

    return samples_data


def _generate_alerts(
    overall_status: Dict[str, Any],
    main_dir: str,
    config: Dict[str, Any],
    samples_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Generate alerts using the AlertEngine.

    Args:
        overall_status: Overall system status
        main_dir: Main data directory
        config: Application configuration
        samples_data: List of sample information

    Returns:
        List of alert dictionaries
    """
    # Get global alert engine instance
    alert_engine = get_alert_engine()

    # Prepare status dictionary for alert engine
    status = {
        "running": overall_status.get("running", False),
        "completed": overall_status.get("completed", False),
        "error_count": overall_status.get("error_count", 0),
        "pending_files": overall_status.get("pending_files", 0),
        "processed_files": overall_status.get("processed_files", 0)
    }

    # Prepare samples list for alert engine
    samples = []
    for sample in samples_data:
        # Convert sample data to format expected by alert engine
        reads_str = sample.get("reads", "0")
        reads = int(reads_str.replace(",", "")) if isinstance(reads_str, str) else reads_str

        # Estimate pass rate from quality label (e.g. "Good", "Fair")
        quality = sample.get("quality", "--")
        if "Excellent" in quality:
            pass_rate = 95
        elif "Good" in quality:
            pass_rate = 80
        elif "Fair" in quality:
            pass_rate = 65
        elif "Poor" in quality:
            pass_rate = 40
        else:
            pass_rate = 100  # Unknown, assume ok

        samples.append({
            "name": sample.get("sample", "Unknown"),
            "reads": reads,
            "pass_rate": pass_rate,
            "status": sample.get("status", "unknown")
        })

    # Prepare QC stats - use actual classification data from Kraken2
    # instead of the crude heuristic _estimate_classified_rate
    actual_classified_rate = 0.0
    try:
        kraken_df = load_kraken_data(main_dir, "All Samples")
        if not kraken_df.empty:
            classified_reads, unclassified_reads, _ = get_classification_stats(kraken_df)
            total_kr = classified_reads + unclassified_reads
            if total_kr > 0:
                actual_classified_rate = (classified_reads / total_kr) * 100
    except Exception:
        # Falling back to an organism-count estimator means the operator
        # sees a plausible but synthetic Zone 3 number. Log the fallback
        # so it surfaces in the terminal; the dashboard itself remains
        # responsive rather than crashing on a transient kraken read.
        logger.warning(
            "compute_qc_stats_for_zone3: kraken load failed; using estimator",
            exc_info=True,
        )
        actual_classified_rate = _estimate_classified_rate(overall_status.get("organisms_detected", 0))

    qc_stats = {
        "total_reads": overall_status.get("total_reads", 0),
        "pass_rate": _estimate_pass_rate_from_quality(overall_status.get("quality_score")),
        "classified_rate": actual_classified_rate
    }

    # Load detected organisms for pathogen checking
    detected_organisms = []
    # Get only ENABLED watchlist entries for alerting
    species_of_interest = _get_active_watchlist_entries(config)

    try:
        kraken_df = load_kraken_data(main_dir, "All Samples")
        if not kraken_df.empty:
            # Filter to species level with meaningful read counts (vectorized)
            species_df = kraken_df[
                (kraken_df["rank"] == "S") &
                (kraken_df["reads"] >= 5)
            ]
            detected_organisms = _species_df_to_organisms(species_df)
    except Exception as e:
        logger.error(f"Error loading organisms for pathogen check: {e}")

    # Generate alerts using alert engine (now includes pathogen detection)
    alerts = alert_engine.generate_alerts(
        status,
        samples,
        qc_stats,
        detected_organisms=detected_organisms,
        watched_species=species_of_interest
    )

    return alerts


def _estimate_pass_rate_from_quality(quality_score: Optional[int]) -> float:
    """
    Map quality score to pass rate for alerts.

    The quality_score is now already a meaningful 0-100 value based on
    nanopore-appropriate metrics (Q20% from seqkit or scaled Q-score).

    Args:
        quality_score: Quality score from _estimate_quality_score (0-100)

    Returns:
        Pass rate percentage for alert thresholds
    """
    if quality_score is None:
        return 100.0
    # Quality score is already a 0-100 value, use directly
    return float(max(0, min(100, quality_score)))


def _estimate_classified_rate(organisms: int) -> float:
    """Estimate classification rate from organism count."""
    if organisms == 0:
        return 0.0
    # Rough heuristic: more organisms = better classification
    # This is simplified - real calculation needs actual classified/unclassified counts
    return min(100, 30 + (organisms * 0.5))


def _get_alerts_badge_color(alerts_data: List[Dict[str, Any]]) -> str:
    """Determine badge color based on highest alert severity."""
    if not alerts_data:
        return "secondary"

    severities = [alert.get("severity", "info") for alert in alerts_data]

    if "critical" in severities or "danger" in severities:
        return "danger"
    elif "warning" in severities:
        return "warning"
    elif "info" in severities:
        return "info"
    else:
        return "success"


def _create_pathogen_alert_panel(
    detected_organisms: List[Dict[str, Any]],
    watched_species: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
    taxid_to_samples: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    main_dir: Optional[str] = None,
) -> Tuple[html.Div, Dict[str, str]]:
    """
    Create pathogen alert panel based on detected dangerous organisms.

    Args:
        detected_organisms: List of organisms from Kraken2 classification
        watched_species: Optional user-configured watchlist (legacy, kept for compatibility)
        config: Application configuration dict (used for taxid mapping)
        taxid_to_samples: Per-taxid sample attribution dict built by
            _load_per_sample_organisms (keyed by Kraken2 db taxid)
        main_dir: Pipeline results directory; used to load
            ``validation_results.json`` so each pathogen-alert card can
            render a "Validated 95%" / "Partial" / "Not validated" /
            "Pending" badge. Falls through to no badge when main_dir
            is empty or no validation entry exists for the
            (sample, taxid) pair (the case for runs where validation
            has not been enabled).

    Returns:
        Tuple of (alert_panel_component, container_style)
    """
    if not detected_organisms:
        return html.Div(), {"display": "none"}

    taxid_to_samples = taxid_to_samples or {}
    # Load validation lookup once per call. Cheap (single JSON read +
    # in-memory dict build) and avoids re-parsing inside the per-detection
    # loop below. Returns {} when validation has not run.
    validation_lookup = _load_validation_lookup(main_dir or "")

    try:
        # Check for dangerous pathogens using proper taxid mapping
        # This handles GTDB databases where Kraken2 taxids differ from NCBI taxids
        dangerous_detections = _check_pathogens_with_mapping(detected_organisms, config)

        if not dangerous_detections:
            return html.Div(), {"display": "none"}

        # Build alert components
        alert_components = []
        watch_components = []
        critical_count = 0
        high_count = 0
        watch_count = 0

        for detection in dangerous_detections:
            threat_level = detection.get("threat_level", "moderate")
            pathogen_name = detection.get("name", "Unknown organism")
            common_name = detection.get("common_name", "")
            reads = detection.get("reads", 0)
            abundance = detection.get("abundance", 0.0)
            action = detection.get("action_required", "Follow biosafety protocols")
            taxid = detection.get("taxid")

            # Resolve per-sample attribution: prefer the Kraken2 db taxid used during
            # detection, fall back to the NCBI taxid stored on the watchlist entry.
            kraken_taxid = detection.get("detected_taxid") or taxid
            samples_for_detection = taxid_to_samples.get(kraken_taxid, [])
            if not samples_for_detection and kraken_taxid != taxid:
                samples_for_detection = taxid_to_samples.get(taxid, [])

            # Cross-sample validation summary for this watchlist hit. Returns
            # None when no sample in the detection has a validation entry --
            # the alert components treat None as "validation not run" and
            # render "Pending" only when validation_lookup is non-empty (i.e.
            # validation has run for OTHER taxids), suppressing the badge
            # entirely otherwise.
            validation = _summarise_validation_for_taxid(
                samples_for_detection, taxid, validation_lookup
            )
            if validation is None and validation_lookup:
                # Validation has run elsewhere but produced no result for
                # this (sample, taxid). Surface as "Pending" so the operator
                # sees the gap rather than a silent omission.
                validation = {
                    "status": "pending",
                    "identity": 0.0,
                    "method": "",
                    "n_validated": 0,
                    "n_samples": len(samples_for_detection),
                }

            if threat_level == "critical":
                critical_count += 1
                alert_components.append(
                    CriticalPathogenAlert(
                        pathogen_name=pathogen_name,
                        common_name=common_name,
                        read_count=reads,
                        abundance_pct=abundance,
                        confidence="HIGH" if reads >= 100 else "MODERATE",
                        taxid=taxid,
                        recommendation=action,
                        samples=samples_for_detection,
                        validation=validation,
                    )
                )
            elif threat_level in ["high", "high_risk"]:
                high_count += 1
                alert_components.append(
                    HighRiskPathogenAlert(
                        pathogen_name=pathogen_name,
                        common_name=common_name,
                        read_count=reads,
                        abundance_pct=abundance,
                        taxid=taxid,
                        recommendation=action,
                        samples=samples_for_detection,
                        validation=validation,
                    )
                )
            else:
                # Moderate / watched species
                watch_count += 1
                watch_components.append(
                    WatchedSpeciesAlert(
                        pathogen_name=pathogen_name,
                        read_count=reads,
                        abundance_pct=abundance,
                        taxid=taxid,
                        samples=samples_for_detection,
                        validation=validation,
                    )
                )

        if not alert_components and not watch_components:
            return html.Div(), {"display": "none"}

        # Create summary header if multiple threats
        total_count = critical_count + high_count + watch_count
        header = None
        if total_count > 1:
            header = html.Div([
                html.H4([
                    html.I(className="bi bi-exclamation-triangle-fill me-2"),
                    f"{total_count} WATCHED ORGANISMS DETECTED"
                ], className="text-danger mb-0 fw-bold")
            ], className="mb-3")

        # Add watched species section with header if present
        if watch_components:
            alert_components.append(
                html.Div([
                    html.H6([
                        html.I(className="bi bi-eye me-2"),
                        f"Watched Species ({watch_count})"
                    ], className="text-muted mb-2 mt-3")
                ])
            )
            alert_components.extend(watch_components)

        # Combine into panel
        panel = html.Div([
            header,
            *alert_components
        ] if header else alert_components)

        return panel, {"display": "block"}

    except Exception as e:
        logger.error(f"Error creating pathogen alert panel: {e}")
        return html.Div(), {"display": "none"}


def _species_df_to_organisms(species_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Convert species DataFrame to list of organism dicts (vectorized).

    Args:
        species_df: DataFrame with species-level classifications

    Returns:
        List of organism dicts with taxid, name, reads, abundance
    """
    if species_df.empty:
        return []

    # Vectorized extraction - much faster than iterrows
    # Use '%' column if available (kraken report standard), otherwise try 'fraction_total_reads'
    if '%' in species_df.columns:
        abundance_col = species_df['%'].fillna(0).astype(float)
    elif 'fraction_total_reads' in species_df.columns:
        abundance_col = species_df['fraction_total_reads'].fillna(0).astype(float) * 100
    else:
        abundance_col = pd.Series([0.0] * len(species_df))

    result_df = pd.DataFrame({
        'taxid': species_df['taxid'].fillna(0).astype(int),
        'name': species_df['name'].fillna('Unknown'),
        'reads': species_df['reads'].fillna(0).astype(int),
        'abundance': abundance_col
    })
    return result_df.to_dict('records')

def _load_per_sample_organisms(
    main_dir: str,
    available_samples: List[str]
) -> Dict[int, List[Dict[str, Any]]]:
    """
    Load species-level organisms from each sample and return a per-taxid attribution dict.

    Keyed by the Kraken2 database taxid (as it appears in reports), each value is a
    list of sample-level dicts sorted descending by reads. A sample is flagged as
    negative control when its name contains "negative" (case-insensitive) — the
    codebase has no explicit manifest NC flag at this stage.

    Args:
        main_dir: Results output directory
        available_samples: All sample names including "All Samples"

    Returns:
        Dict[int, List[{sample, reads, abundance, is_negative_control}]]
    """
    real_samples = [s for s in available_samples if s != "All Samples"]
    if not real_samples:
        return {}

    taxid_to_samples: Dict[int, List[Dict[str, Any]]] = {}

    for sample in real_samples:
        is_nc = "negative" in sample.lower()
        try:
            kraken_df = load_kraken_data(main_dir, sample)
            if kraken_df.empty:
                continue
            species_df = kraken_df[
                (kraken_df["rank"] == "S") & (kraken_df["reads"] >= 5)
            ]
            if species_df.empty:
                continue
            for org in _species_df_to_organisms(species_df):
                taxid = org["taxid"]
                if taxid not in taxid_to_samples:
                    taxid_to_samples[taxid] = []
                taxid_to_samples[taxid].append({
                    "sample": sample,
                    "reads": org["reads"],
                    "abundance": org["abundance"],
                    "is_negative_control": is_nc,
                })
        except Exception as exc:
            logger.debug(f"Per-sample organism load failed for {sample}: {exc}")

    # Sort each sample list descending by reads
    for taxid in taxid_to_samples:
        taxid_to_samples[taxid].sort(key=lambda x: x["reads"], reverse=True)

    return taxid_to_samples

def _get_active_watchlist_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get only ENABLED watchlist entries for alerting.

    Returns active entries from WatchlistManager.

    Args:
        config: Application configuration dict

    Returns:
        List of enabled watchlist entries with 'enabled': True
    """
    active_entries = []

    # Get active entries from WatchlistManager
    try:
        manager = get_watchlist_manager()
        # Load watchlist manager if not already loaded
        if not manager._loaded and config:
            manager.load_config(config)
            logger.debug(f"Dashboard: Loaded WatchlistManager with {len(manager.get_active_entries())} active entries")
        if manager._loaded:
            for entry in manager.get_active_entries().values():
                active_entries.append({
                    "name": entry.name,
                    "taxid": entry.taxid,  # WatchlistEntry uses 'taxid', not 'taxid_ncbi'
                    # Explicit GTDB/custom DB taxid (when set) so detection can
                    # match the report's DB taxid exactly.
                    "db_taxid": entry.db_taxid,
                    "common_name": entry.common_name,
                    "threat_level": entry.threat_level.value if entry.threat_level else "moderate",
                    "alert_threshold": entry.alert_threshold,
                    "enabled": True,  # Already filtered to active
                })
    except Exception as e:
        logger.debug(f"Could not get WatchlistManager entries: {e}")

    # Also include legacy species_of_interest (but only enabled ones)
    legacy_species = config.get("species_of_interest", [])
    for species in legacy_species:
        if species.get("enabled", True):  # Default to enabled if not specified
            # Avoid duplicates by taxid
            taxid = species.get("taxid")
            if taxid and any(e.get("taxid") == taxid for e in active_entries):
                continue
            active_entries.append({
                **species,
                "enabled": True,
            })

    return active_entries

def _check_pathogens_with_mapping(
    detected_organisms: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Check detected organisms against pathogen database using proper taxid mapping.

    This function uses the WatchlistManager's check_organisms_with_mapping() method
    which properly handles GTDB and custom Kraken2 databases where taxids differ
    from NCBI taxids.

    Args:
        detected_organisms: List of dicts with 'taxid', 'name', 'reads', 'abundance'
        config: Optional config dict (for loading watchlist if needed)

    Returns:
        List of detected dangerous pathogens with full information
    """
    if not detected_organisms:
        return []

    try:
        # Get WatchlistManager
        manager = get_watchlist_manager()

        # Ensure manager is loaded
        if not manager._loaded and config:
            manager.load_config(config)

        # Get taxid mapping collection for proper db_taxid -> ncbi_taxid lookup
        from nanometa_live.core.taxonomy.taxid_mapping import get_mapping_collection
        mapping_collection = get_mapping_collection()

        # Use the proper mapping-aware check function
        if mapping_collection:
            # WatchlistManager.check_organisms_with_mapping() properly handles:
            # 1. Direct NCBI taxid match
            # 2. Reverse mapping from Kraken2 db_taxid to NCBI taxid
            # 3. Name-based matching as fallback
            return manager.check_organisms_with_mapping(
                detected_organisms,
                mapping_collection
            )
        else:
            # Fall back to standard method if no mapping available
            # This still uses name matching as backup
            logger.debug("No taxid mapping available, falling back to standard organism check")
            return manager.check_organisms(detected_organisms)

    except Exception as e:
        logger.warning(f"Error in pathogen check with mapping: {e}")
        # Fall back to old method on error
        watched_species = _get_active_watchlist_entries(config) if config else []
        return check_for_dangerous_pathogens(detected_organisms, watched_species)


# ---------------------------------------------------------------------------
# Validation overlay for pathogen alert cards (2026-05-01)
# ---------------------------------------------------------------------------
#
# When the operator has enabled validation, every (sample, taxid) pair that
# was classified above the read-count floor should have a corresponding
# validation_results.json entry. The helpers below load that file once per
# alerts-callback tick and summarise validation across the samples a
# single watchlist hit was detected in. The summary is then attached to
# each alert dict so the pathogen-alert components (CriticalPathogenAlert,
# HighRiskPathogenAlert, WatchedSpeciesAlert) can render a small badge:
#
#   green  "Validated 95.2%"   -- all samples confirmed; high confidence
#   amber  "Partial 78.4%"     -- some samples partial / mixed
#   red    "Not validated"     -- no sample reached confirmed status
#   grey   "Pending"           -- validation enabled but no result for this
#                                 (sample, taxid) yet
#
# The intent is to let operators distinguish a real ACTION REQUIRED detection
# from a Kraken2 false-positive that validation already rejected -- the
# original feature ask was "to avoid false alarms".


def _load_validation_lookup(main_dir: str) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """Build a per-(sample, taxid) validation-status lookup.

    Reads ``<main_dir>/validation/validation_results.json`` via the canonical
    ``BlastValidationParser``. Returns an empty dict when validation has not
    run, the file is missing, or any parse error occurs -- the caller treats
    "no entry" as "not validated yet" rather than "rejected".

    Args:
        main_dir: Pipeline results directory.

    Returns:
        ``{(sample_id, taxid): {"status": str, "identity": float,
                                "method": str, "validated_reads": int,
                                "total_reads": int}}``
    """
    if not main_dir:
        return {}
    try:
        from nanometa_live.core.parsers.blast_validation_parser import (
            BlastValidationParser,
        )
        parser = BlastValidationParser(main_dir)
        if not parser.has_validation_data():
            return {}
        results = parser.get_validation_results()
    except Exception as e:
        logger.debug(f"Could not load validation_results.json: {e}")
        return {}

    lookup: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in results:
        try:
            sample_id = getattr(r, "sample_id", "")
            raw_taxid = getattr(r, "taxid", None)
            if not sample_id or raw_taxid is None:
                continue
            taxid = int(raw_taxid)
            # status_display normalises ValidationStatus.UNCERTAIN to "low" and
            # ValidationStatus.CONFIRMED to "validated"; fall back to .status.value
            # if the parser version still returns the enum directly.
            status_attr = getattr(r, "status_display", None) or getattr(r, "status", None)
            if hasattr(status_attr, "value"):
                status = str(status_attr.value)
            else:
                status = str(status_attr) if status_attr is not None else "no_data"
            lookup[(sample_id, taxid)] = {
                "status": status,
                "identity": float(getattr(r, "percent_identity_mean", 0.0) or 0.0),
                "method": str(getattr(r, "validation_method", "blast") or "blast"),
                "validated_reads": int(getattr(r, "validated_reads", 0) or 0),
                "total_reads": int(getattr(r, "total_reads", 0) or 0),
                "percent_validated": float(getattr(r, "percent_validated", 0.0) or 0.0),
            }
        except (AttributeError, ValueError, TypeError) as exc:
            logger.debug(f"Skipping malformed validation result: {exc}")
            continue
    return lookup


# Status priority for cross-sample summary. Higher value = stronger signal.
# We pick the BEST status across samples so a pathogen confirmed in one
# sample is not under-reported as "partial" on the dashboard just because
# another sample has fewer reads.
_VALIDATION_RANK = {
    "confirmed": 4,
    "validated": 4,
    "partial": 3,
    "uncertain": 2,
    "low": 1,
    "no_data": 0,
    "failed": 0,
}


def _summarise_validation_for_taxid(
    samples: List[Dict[str, Any]],
    taxid: Optional[int],
    lookup: Dict[Tuple[str, int], Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Summarise validation status across a list of samples for one taxid.

    Args:
        samples: Per-sample attribution list (dicts with at least ``sample``).
        taxid: NCBI / Kraken2 db taxid for the watchlist hit.
        lookup: Output of ``_load_validation_lookup``.

    Returns:
        ``{"status", "identity", "method", "n_validated", "n_samples"}`` or
        ``None`` when no sample in this detection has a validation entry.
    """
    if not lookup or taxid is None or not samples:
        return None
    try:
        taxid_int = int(taxid)
    except (TypeError, ValueError):
        return None

    rows = []
    for s in samples:
        sample_id = s.get("sample") if isinstance(s, dict) else None
        if not sample_id:
            continue
        entry = lookup.get((sample_id, taxid_int))
        if entry is not None:
            rows.append(entry)

    if not rows:
        return None

    best = max(rows, key=lambda e: _VALIDATION_RANK.get(e.get("status", "no_data"), 0))
    avg_identity = sum(r["identity"] for r in rows) / len(rows)
    method = best.get("method", "blast")
    return {
        "status": best.get("status", "no_data"),
        "identity": avg_identity,
        "method": method,
        "n_validated": len(rows),
        "n_samples": len(samples),
    }
