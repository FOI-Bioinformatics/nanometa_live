"""
Pure helpers for the QC tab.

Extracted from qc_tab.py so the registration function there stays focused on Dash
callback declarations. These build the Stage Strip components and the amplicon-
mode heuristic from plain inputs (counts, config) with no Dash ``app`` capture,
so they are unit-testable in isolation. qc_tab.py re-exports these names.
"""

from dash import html
import plotly.express as px


def _build_stage_strip_slot(heading, count_text, subtitle, count_extra=None, slot_class="stage-strip-slot"):
    """Build a single slot div for the Stage Strip."""
    children = [
        html.Div(heading, className="stage-strip-slot-heading"),
        html.Div(count_text, className="stage-strip-count" + (
            " stage-strip-count--unavailable" if count_text == "—" else ""
        )),
    ]
    if count_extra:
        children.append(html.Div(count_extra, className="stage-strip-unavailable-note"))
    children.append(html.Div(subtitle, className="stage-strip-subtitle"))
    return html.Div(children, className=slot_class)


def _is_amplicon_mode(config) -> bool:
    """Detect whether the operator has configured amplicon-friendly filters.

    Heuristic: when ``chopper_minlength`` or ``filtlong_min_length`` is
    set to an explicit numeric value below 500 bp, the run targets
    short amplicons (V3-V4 ~460 bp, ITS, custom designs). Long-read
    defaults are 1000. The QC bands relax to match -- short ONT reads
    carry proportionally more end-of-read low-quality bases, so
    legitimate amplicon runs show Q30 and classification rates lower
    than long-read runs.

    Conservative on missing or garbage values: only returns True when
    a numeric value below 500 is present in the config. ``None`` and
    invalid strings keep long-read mode on.

    See docs/audit-2026-04-29-short-amplicons.md for the full audit and
    the recommended config preset.
    """
    if not config:
        return False
    for key in ("chopper_minlength", "filtlong_min_length"):
        raw = config.get(key)
        if raw is None or raw == "":
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value < 500:
            return True
    return False


def _build_stage_strip(raw_reads, filtered_reads, classified_reads, unclassified_reads,
                       is_chopper, filter_tool, timestamp_str,
                       amplicon_mode: bool = False):
    """Build the complete Stage Strip component.

    All counts are cumulative-since-run-start, matching the time horizon used
    by the Organism, Dashboard, and Sample Breakdown cards.

    Args:
        raw_reads: Raw read count before filtering (None if unavailable)
        filtered_reads: Cumulative quality-filtered read count
        classified_reads: Cumulative classified read count (Kraken2 root)
        unclassified_reads: Cumulative unclassified read count (Kraken2)
        is_chopper: True when raw counts are unavailable (Chopper pipeline)
        filter_tool: Label for the quality-filter tool (e.g. "Chopper", "FASTP")
        timestamp_str: Display timestamp string
    """
    # --- Raw slot ---
    if is_chopper or raw_reads is None:
        raw_slot = _build_stage_strip_slot(
            heading="RAW READS",
            count_text="—",
            subtitle=f"({filter_tool})",
            count_extra="Not available (Chopper pipeline)",
            slot_class="stage-strip-slot stage-strip-slot--raw",
        )
        filter_delta_text = "N/A"
        filter_delta_cls = "stage-strip-delta stage-strip-delta--muted"
    else:
        raw_slot = _build_stage_strip_slot(
            heading="RAW READS",
            count_text=f"{raw_reads:,}",
            subtitle=f"({filter_tool})",
            slot_class="stage-strip-slot",
        )
        if filtered_reads and raw_reads > 0:
            removed_pct = max(0.0, (raw_reads - filtered_reads) / raw_reads * 100)
            filter_delta_text = f"{removed_pct:.1f}% removed"
        else:
            filter_delta_text = "N/A"
        filter_delta_cls = "stage-strip-delta stage-strip-delta--muted"

    # --- Filtered slot ---
    filtered_str = f"{filtered_reads:,}" if filtered_reads is not None else "—"
    filtered_slot = _build_stage_strip_slot(
        heading="QUALITY-FILTERED",
        count_text=filtered_str,
        subtitle=f"({filter_tool})",
        slot_class="stage-strip-slot stage-strip-slot--filtered",
    )

    # --- Classified slot ---
    total_kraken = classified_reads + unclassified_reads
    classif_rate = (classified_reads / total_kraken * 100) if total_kraken > 0 else None
    classified_str = f"{classified_reads:,}" if total_kraken > 0 else "—"
    classified_slot = _build_stage_strip_slot(
        heading="CLASSIFIED",
        count_text=classified_str,
        subtitle="(Kraken2)",
        slot_class="stage-strip-slot stage-strip-slot--classified",
    )

    # Classification rate delta color. Amplicon mode uses relaxed
    # bands because short reads classify at lower rates -- a 100%
    # bacterial 16S amplicon run typically clears 50-70% in
    # long-read-tuned terms but is operationally fine.
    if amplicon_mode:
        _green_floor, _amber_floor = 50, 25
    else:
        _green_floor, _amber_floor = 80, 50
    if classif_rate is None:
        classif_delta_text = "—"
        classif_delta_cls = "stage-strip-delta stage-strip-delta--muted"
    elif classif_rate >= _green_floor:
        classif_delta_text = f"{classif_rate:.1f}%"
        classif_delta_cls = "stage-strip-delta stage-strip-delta--green"
    elif classif_rate >= _amber_floor:
        classif_delta_text = f"{classif_rate:.1f}%"
        classif_delta_cls = "stage-strip-delta stage-strip-delta--amber"
    else:
        classif_delta_text = f"{classif_rate:.1f}%"
        classif_delta_cls = "stage-strip-delta stage-strip-delta--red"

    arrow1 = html.Div([
        html.I(className="bi bi-arrow-right stage-strip-arrow-icon"),
        html.Div(filter_delta_text, className=filter_delta_cls),
    ], className="stage-strip-arrow-col")

    arrow2 = html.Div([
        html.I(className="bi bi-arrow-right stage-strip-arrow-icon"),
        html.Div(classif_delta_text, className=classif_delta_cls),
    ], className="stage-strip-arrow-col")

    body_children = [
        html.Div(
            f"Last updated {timestamp_str}",
            className="stage-strip-timestamp",
        ),
        html.Div(
            [raw_slot, arrow1, filtered_slot, arrow2, classified_slot],
            className="stage-strip-slots",
        ),
    ]

    return html.Div(body_children, className="stage-strip-container")


def compute_qc_stat_lines(
    *,
    tot_reads_pre_filt: int,
    tot_passed_reads: int,
    tot_removed_reads: int,
    tot_low_quality_reads: int,
    tot_too_short_reads: int,
    tot_too_many_N_reads: int,
    classified_reads: int,
    unclassified_reads: int,
    processed_files: int,
    waiting_files: int,
    chopper_estimated: bool = False,
) -> list:
    """Turn the raw QC read counts into the ten formatted stat-tile strings.

    Pure: takes the counts the update_qc_stats callback gathers from disk and
    returns the display strings (percentages + thousands separators), including
    the pre-filter baseline adjustment for the seqkit-over-counts-kraken2 case.
    """
    # When post-filter count exceeds pre-filter baseline (seqkit may count
    # slightly more reads than kraken2 processed), adjust to avoid impossible %
    if tot_passed_reads > tot_reads_pre_filt and tot_reads_pre_filt > 0:
        tot_reads_pre_filt = tot_passed_reads
        tot_removed_reads = 0
    percentage_passed = 0
    percentage_removed = 0
    if tot_reads_pre_filt > 0:
        percentage_passed = min(round(
            (tot_passed_reads * 100) / tot_reads_pre_filt, 1
        ), 100.0)
        percentage_removed = max(round(
            (tot_removed_reads * 100) / tot_reads_pre_filt, 1
        ), 0.0)

    percentage_low_quality = 0
    percentage_too_many_N = 0
    percentage_too_short = 0
    if tot_removed_reads > 0:
        percentage_low_quality = round(
            (tot_low_quality_reads * 100) / tot_removed_reads, 1
        )
        percentage_too_many_N = round(
            (tot_too_many_N_reads * 100) / tot_removed_reads, 1
        )
        percentage_too_short = round(
            (tot_too_short_reads * 100) / tot_removed_reads, 1
        )

    percentage_classified = 0
    percentage_unclassified = 0
    total_kraken_reads = classified_reads + unclassified_reads
    if total_kraken_reads > 0:
        percentage_classified = round(
            (classified_reads * 100) / total_kraken_reads, 1
        )
        percentage_unclassified = round(
            (unclassified_reads * 100) / total_kraken_reads, 1
        )

    # Format output strings
    if tot_reads_pre_filt > 0:
        reads_pre_filtering = f"Raw reads (pre-Chopper): {tot_reads_pre_filt:,}"
    else:
        reads_pre_filtering = "Raw reads (pre-Chopper): — (not available for Chopper pipeline)"
    reads_passed = f"Reads that passed filtering: {tot_passed_reads:,} ({percentage_passed}%)"
    reads_removed = (
        f"Total reads removed: {tot_removed_reads:,} ({percentage_removed}%)"
    )

    # When chopper is used, the per-category breakdown is an
    # approximation (chopper does not report these individually).
    est = " (est.)" if chopper_estimated else ""
    low_quality = f"Too low quality{est}: {tot_low_quality_reads:,} ({percentage_low_quality}%)"
    too_short = f"Too short{est}: {tot_too_short_reads:,} ({percentage_too_short}%)"
    low_complexity = f"Too low complexity{est}: {tot_too_many_N_reads:,} ({percentage_too_many_N}%)"

    classified = (
        f"Classified reads: {classified_reads:,} ({percentage_classified}%)"
    )
    unclassified = f"Unclassified reads: {unclassified_reads:,} ({percentage_unclassified}%)"

    processed = f"Files processed: {processed_files:,}"
    waiting = f"Files awaiting processing: {waiting_files:,}"

    return [
        reads_pre_filtering,
        reads_passed,
        reads_removed,
        low_quality,
        too_short,
        low_complexity,
        classified,
        unclassified,
        processed,
        waiting,
    ]


def _build_stage_strip_empty():
    """Return a minimal Stage Strip placeholder when no data is available."""
    return html.Div([
        html.Div("Waiting for data...", className="stage-strip-slot-heading text-center py-3"),
    ], className="stage-strip-container")


def _get_empty_qc_figures():
    """Return fresh empty QC figures for placeholder display.

    Creates new figure objects on each call to prevent mutable state
    from being shared across callback invocations or browser sessions.
    """
    return [
        px.line(title="Cumulative Sequences"),
        px.line(title="Cumulative Base Pairs"),
        px.bar(title="Sequences per Sample"),
        px.bar(title="Base Pairs per Sample"),
    ]
