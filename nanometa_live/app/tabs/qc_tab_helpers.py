"""
Pure helpers for the QC tab.

Extracted from qc_tab.py so the registration function there stays focused on Dash
callback declarations. These build the Stage Strip components and the amplicon-
mode heuristic from plain inputs (counts, config) with no Dash ``app`` capture,
so they are unit-testable in isolation. qc_tab.py re-exports these names.
"""

import os
import re

from dash import html
import pandas as pd
import plotly.express as px


# Trailing per-batch marker on a Kraken2 report basename, e.g.
# "barcode01_batch3.kraken2.report.txt" -> sample "barcode01".
_BATCH_SUFFIX_RE = re.compile(r"_batch\d+$")


def _kreport_sample_name(path: str) -> str:
    """Sample name for a Kraken2 report path.

    Strips the report suffix (cumulative or plain) and any trailing ``_batchN``
    marker. Without the batch strip, ``barcode01`` and ``barcode01_batch2``
    became two different "samples" in the QC charts -- phantom bars for reads
    that were already counted under the real barcode.
    """
    base = os.path.basename(path)
    for suffix in (".cumulative.kraken2.report.txt", ".kraken2.report.txt"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return _BATCH_SUFFIX_RE.sub("", base)


def aggregate_fastp_read_stats(summaries: list) -> dict:
    """Weighted read statistics over a list of fastp ``summary`` dicts.

    Each summary has ``before_filtering`` / ``after_filtering`` blocks with
    ``total_reads``, ``total_bases``, a mean read length and ``gc_content``.
    Mean length is total bases over total reads (exact); when a block lacks
    ``total_bases`` it is estimated from the block's mean length
    (``read1_mean_length``, or ``read_length_mean`` as some writers name it).
    GC is a per-base figure and is weighted by bases; a simple mean of the
    per-file values let a 10-read file count as much as a 10,000-read one.

    Returns ``{"mean_length", "mean_length_before", "gc_content"}`` where the
    "before" and GC values are ``None`` when unavailable.
    """
    def _bases(block):
        bases = block.get("total_bases")
        if bases:
            return float(bases)
        mean_len = block.get("read1_mean_length", block.get("read_length_mean", 0)) or 0
        return float(mean_len) * float(block.get("total_reads", 0) or 0)

    reads_after = reads_before = 0
    bases_after = bases_before = 0.0
    gc_weighted = gc_weight = 0.0

    for summary in summaries:
        before = summary.get("before_filtering", {})
        after = summary.get("after_filtering", {})

        reads_before += before.get("total_reads", 0) or 0
        reads_after += after.get("total_reads", 0) or 0
        b_before = _bases(before)
        b_after = _bases(after)
        bases_before += b_before
        bases_after += b_after

        gc = after.get("gc_content", 0) or 0
        if gc > 0 and b_after > 0:
            gc_weighted += gc * 100 * b_after  # fraction -> percentage
            gc_weight += b_after

    return {
        "mean_length": (bases_after / reads_after) if reads_after > 0 else 0.0,
        "mean_length_before": (bases_before / reads_before) if reads_before > 0 else None,
        "gc_content": (gc_weighted / gc_weight) if gc_weight > 0 else None,
    }


def build_qc_figures(sample_data: list) -> list:
    """Build the four QC figures from gathered per-sample data.

    Pure given ``sample_data`` (a list of ``{"Sample", "Time", "Reads", "Bp"}``
    dicts, Time being a datetime). Returns
    ``[cumulative_sequences, cumulative_bp, sequences_per_sample, bp_per_sample]``.
    An empty list yields four annotated empty-state figures.
    """
    if not sample_data:
        message = (
            "No processed data available.<br>"
            "Plots will appear once fastp, seqkit, or Kraken2 outputs land in the results directory."
        )
        return [
            px.line(title="Cumulative Sequences").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
            px.line(title="Cumulative Base Pairs").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
            px.bar(title="Sequences per Sample").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
            px.bar(title="Base Pairs per Sample").add_annotation(text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5),
        ]

    # Create DataFrame and sort by time
    qc_df = pd.DataFrame(sample_data)
    qc_df = qc_df.sort_values("Time")

    # Calculate cumulative values
    qc_df["Cumulative Reads"] = qc_df["Reads"].cumsum()
    qc_df["Cumulative Bp"] = qc_df["Bp"].cumsum()

    # Format time for display
    time_for_display = qc_df["Time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    # Shared Plotly layout for consistent QC chart styling
    _qc_layout = dict(
        template="nanometa",
        height=350,
        margin=dict(l=50, r=30, t=50, b=60),
        font=dict(family="Arial, sans-serif", size=12),
        title_font=dict(size=14, color="#374151"),
        hovermode="x unified",
    )

    # Cumulative reads line chart
    cumul_reads_fig = px.line(
        qc_df,
        x=time_for_display,
        y="Cumulative Reads",
        title="Cumulative Processed Sequences",
    )
    cumul_reads_fig.update_traces(
        line=dict(color="#0d6efd", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(13, 110, 253, 0.08)",
        hovertemplate="Sequences: %{y:,.0f}<extra></extra>",
    )
    cumul_reads_fig.update_layout(
        **_qc_layout,
        xaxis_title="Processing Time",
        yaxis_title="Cumulative Sequences",
        yaxis_tickformat=",",
    )

    # Cumulative base pairs line chart
    cumul_bp_fig = px.line(
        qc_df,
        x=time_for_display,
        y="Cumulative Bp",
        title="Cumulative Processed Base Pairs",
    )
    cumul_bp_fig.update_traces(
        line=dict(color="#198754", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(25, 135, 84, 0.08)",
        hovertemplate="Bases: %{y:,.0f}<extra></extra>",
    )
    cumul_bp_fig.update_layout(
        **_qc_layout,
        xaxis_title="Processing Time",
        yaxis_title="Cumulative Base Pairs",
        yaxis_tickformat=",",
    )

    # Reads per sample bar chart
    reads_fig = px.bar(
        qc_df, x="Sample", y="Reads", title="Sequences per Sample"
    )
    reads_fig.update_traces(
        marker_color="#0d6efd",
        marker_line_width=0,
        hovertemplate="<b>%{x}</b><br>Sequences: %{y:,.0f}<extra></extra>",
    )
    reads_fig.update_layout(
        **_qc_layout,
        xaxis_title="Sample",
        yaxis_title="Sequences",
        yaxis_tickformat=",",
        xaxis_type="category",
        bargap=0.3,
    )

    # Base pairs per sample bar chart
    bp_fig = px.bar(
        qc_df, x="Sample", y="Bp", title="Processed Base Pairs per Sample"
    )
    bp_fig.update_traces(
        marker_color="#198754",
        marker_line_width=0,
        hovertemplate="<b>%{x}</b><br>Base pairs: %{y:,.0f}<extra></extra>",
    )
    bp_fig.update_layout(
        **_qc_layout,
        xaxis_title="Sample",
        yaxis_title="Base Pairs",
        yaxis_tickformat=",",
        xaxis_type="category",
        bargap=0.3,
    )

    return [cumul_reads_fig, cumul_bp_fig, reads_fig, bp_fig]


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
                       amplicon_mode: bool = False, kept_reads=None):
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
        # Chopper/seqkit QC does not record a pre-filter read count, so a "Raw
        # reads" box would always read N/A. Repurpose it to a metric that IS
        # available -- the number of reads that passed filtering and entered
        # classification (seqkit num_seqs / Kraken2 total) -- so the first box
        # carries real information instead of an empty placeholder.
        if filtered_reads:
            raw_slot = _build_stage_strip_slot(
                heading="READS PROCESSED",
                count_text=f"{filtered_reads:,}",
                subtitle=f"({filter_tool})",
                count_extra="Pre-filter count not recorded by this QC tool",
                slot_class="stage-strip-slot stage-strip-slot--raw",
            )
        else:
            raw_slot = _build_stage_strip_slot(
                heading="READS PROCESSED",
                count_text="—",
                subtitle=f"({filter_tool})",
                count_extra="Awaiting QC output",
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
        # kept_reads is the filter's own output count (chopper's "Kept K of
        # N"); pairing its input with Kraken2's total mixes two read sets,
        # which differ whenever classification lags the filter.
        passed = kept_reads if kept_reads is not None else filtered_reads
        if passed and raw_reads >= passed:
            removed_pct = (raw_reads - passed) / raw_reads * 100
            filter_delta_text = f"{removed_pct:.1f}% removed"
        else:
            # Covers both "no filtered count yet" and raw < filtered --
            # the latter means the two sources disagree (raw is the QC
            # tool's pre-filter count, filtered is the Kraken2 total),
            # and clamping it to "0.0% removed" reported an impossible
            # measurement as a reassuring one (2026-08-17 audit, Q1).
            filter_delta_text = "N/A"
        filter_delta_cls = "stage-strip-delta stage-strip-delta--muted"

    # --- Filtered slot ---
    # Subtitle names the actual source: the count is the Kraken2 total
    # (reads that passed filtering and entered classification), not a
    # number reported by the QC tool -- labelling it with the QC tool's
    # name misattributed it (finding Q1).
    filtered_str = f"{filtered_reads:,}" if filtered_reads is not None else "—"
    filtered_slot = _build_stage_strip_slot(
        heading="QUALITY-FILTERED",
        count_text=filtered_str,
        subtitle="(entered classification)",
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


def read_set_note(seqkit_reads, kraken_reads):
    """(caption, mismatch) naming the reads the SeqKit cards describe.

    SeqKit's merged statistics and the Kraken2 report are written by
    different processes on different cadences, so on a live or interrupted
    run they can describe different sets of reads: at the Barcelona exercise
    63.9 Mb of bases sat beside 76,642 classified reads (834 bp a read) and a
    mean length of 1,282 bp. ``mismatch`` is None when either count is zero
    or the two agree within 1% (at least 10 reads).
    """
    caption = f"Based on {seqkit_reads:,} reads measured by SeqKit"
    if not seqkit_reads or not kraken_reads:
        return caption, None
    if abs(seqkit_reads - kraken_reads) <= max(10, 0.01 * kraken_reads):
        return caption, None
    return caption, (
        f"Kraken2 processed {kraken_reads:,} reads (classified and "
        "unclassified). The two counts come from different files and do not "
        "describe the same set of reads."
    )


def with_read_set_note(card, seqkit_reads, kraken_reads):
    """``card`` followed by its read-set caption and any mismatch line."""
    caption, mismatch = read_set_note(seqkit_reads, kraken_reads)
    lines = [html.Small(caption, className="text-muted d-block mt-1")]
    if mismatch:
        lines.append(html.Small(mismatch, className="text-warning d-block"))
    return html.Div([card, *lines])


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
    breakdown_recorded: bool = True,
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

    # Format output strings. Without a pre-filter count (chopper and
    # filtlong record none) there is no pass rate and no removal breakdown:
    # the callback used to take the Kraken2 total as the "raw" count --
    # Kraken2 sees reads AFTER filtering, so every run read "passed 100%" --
    # and split the removed reads 60/30/10 by a fixed rule.
    if tot_reads_pre_filt > 0:
        reads_pre_filtering = f"Raw reads (before filtering): {tot_reads_pre_filt:,}"
        reads_passed = f"Reads that passed filtering: {tot_passed_reads:,} ({percentage_passed}%)"
        reads_removed = (
            f"Total reads removed: {tot_removed_reads:,} ({percentage_removed}%)"
        )
        est = " (est.)" if chopper_estimated else ""
        if breakdown_recorded:
            low_quality = f"Too low quality{est}: {tot_low_quality_reads:,} ({percentage_low_quality}%)"
            too_short = f"Too short{est}: {tot_too_short_reads:,} ({percentage_too_short}%)"
            low_complexity = f"Too low complexity{est}: {tot_too_many_N_reads:,} ({percentage_too_many_N}%)"
        else:
            # chopper reports how many reads it kept, not why it dropped the
            # rest, so the per-reason lines have nothing to show.
            low_quality = "Too low quality: not recorded by the read filter"
            too_short = "Too short: not recorded by the read filter"
            low_complexity = "Too low complexity: not recorded by the read filter"
    else:
        reads_pre_filtering = ("Raw reads (before filtering): not recorded "
                               "(the read filter reports no input count)")
        reads_passed = f"Reads that passed filtering: {tot_passed_reads:,}"
        reads_removed = "Total reads removed: not recorded"
        low_quality = "Too low quality: not recorded"
        too_short = "Too short: not recorded"
        low_complexity = "Too low complexity: not recorded"

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


def qc_guidance_issues(pre_filter, passed, classified, total_classified_input):
    """The QC guidance banner's issues and whether they need action.

    ``pre_filter`` is the read count BEFORE filtering, or None when the read
    filter records none (chopper, filtlong): a pass rate is judged only when
    it was measured. The callback used to divide filtered counts by each
    other, or by nothing, and told every sample of a NanoPlot-only run to
    re-sequence (live test 2026-11-24). Returns ``(issues, is_action)``.
    """
    issues = []
    is_action = False
    if pre_filter:
        pass_rate = min(passed / pre_filter * 100, 100.0)
        if pass_rate < 60:
            issues.append(
                "Pass rate is below 60% - consider checking flow cell health "
                "and sample quality. Re-sequencing may be needed for reliable results."
            )
            is_action = True
        elif pass_rate < 75:
            issues.append(
                "Pass rate is moderate. Results are usable but quality could be improved."
            )

    classification_rate = (
        classified / total_classified_input * 100 if total_classified_input else 0
    )
    if classification_rate < 40 and total_classified_input > 100:
        issues.append(
            "Less than 40% of sequences could be identified. This may indicate "
            "the sample contains organisms not in the database, or that sequencing "
            "quality is limiting identification."
        )
        is_action = True

    sequenced = pre_filter or passed or total_classified_input
    if 0 < sequenced < 1000:
        issues.append(
            "Fewer than 1,000 total sequences. Continue sequencing for "
            "more reliable results, especially for low-abundance organisms."
        )
    return issues, is_action


def seqkit_plot_rows(seqkit_df, seqkit_dir):
    """QC plot rows from seqkit stats: one per sample with reads.

    The sample name comes from the loader's ``sample`` column (a name with
    dots, "run.2", was cut to "run" by splitting the file name), and the
    time is the sample's seqkit file mtime -- ``datetime.now()`` put every
    sample at one instant on the cumulative-over-time plots. Falls back to
    the sample's batch_stats directory, then to now.
    """
    import os
    from datetime import datetime

    rows = []
    for rec in seqkit_df.to_dict("records"):
        sample = rec.get("sample")
        if not isinstance(sample, str) or not sample:
            sample = os.path.basename(str(rec.get("file", "unknown")))
            for suffix in (".fastq.gz", ".fq.gz", ".fastq", ".fq", ".tsv"):
                if sample.endswith(suffix):
                    sample = sample[: -len(suffix)]
                    break
        reads = int(rec.get("num_seqs", 0) or 0)
        if reads <= 0:
            continue
        when = None
        for candidate in (os.path.join(seqkit_dir, f"{sample}.tsv"),
                          os.path.join(seqkit_dir, sample, "batch_stats")):
            try:
                when = datetime.fromtimestamp(os.stat(candidate).st_mtime)
                break
            except OSError:
                continue
        rows.append({
            "Sample": sample,
            "Time": when or datetime.now(),
            "Reads": reads,
            "Bp": int(rec.get("sum_len", 0) or 0),
        })
    return rows


def fastp_quality_rates(payloads):
    """Base-weighted Q20 %, Q30 % and GC % over fastp payloads (after filtering).

    One computation for the Base Quality card and the QC export: the export
    read keys the loader does not produce and wrote "N/A" beside the card's
    values. A rate is None when no payload records its fields.
    """
    total_bases = q20 = q30 = gc_weighted = gc_weight = 0.0
    saw_q = False
    for payload in payloads or []:
        after = (payload or {}).get("summary", {}).get("after_filtering", {})
        bases = float(after.get("total_bases", 0) or 0)
        total_bases += bases
        if "q20_bases" in after or "q30_bases" in after:
            saw_q = True
        q20 += float(after.get("q20_bases", 0) or 0)
        q30 += float(after.get("q30_bases", 0) or 0)
        gc = after.get("gc_content")
        if gc and bases:
            gc_weighted += float(gc) * bases
            gc_weight += bases
    return {
        "total_bases": int(total_bases),
        "q20": q20 / total_bases * 100 if total_bases and saw_q else None,
        "q30": q30 / total_bases * 100 if total_bases and saw_q else None,
        "gc": gc_weighted / gc_weight * 100 if gc_weight else None,
    }
