"""Verdict-banner failure states and the descriptor dataclass.

Round-3 hardening (2026-08-24): the pure ``select_verdict`` state machine in
``dashboard_helpers`` gained inputs for conditions where the run itself -- not
the screening result -- is the message. The descriptor dataclass lives here
(rather than in ``dashboard_helpers``) so this module has no imports back
into the tab helpers, and the failure-state builders sit beside it.

The honesty rules these states encode:

- A dead pipeline must never render as a clean result. ``PIPELINE_ERROR``
  outranks every non-detection data state; a detection still wins, with the
  failure noted in its subtitle, because a verdict must never suppress a hit.
- A results directory that vanishes mid-run is ``RESULTS_UNAVAILABLE``,
  never STANDBY -- grey "start an analysis" over a run whose volume was
  unplugged reads as "no run ever happened".
- Samples serving last-good fallback data are named in the subtitle
  ("N samples stale"), so frozen numbers cannot present as live ones.
"""

from dataclasses import dataclass, replace
from typing import Optional


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


def pipeline_error_descriptor(
    detail: Optional[str] = None, has_partial_data: bool = False
) -> VerdictDescriptor:
    """PIPELINE ERROR: the run terminated abnormally.

    Red-bordered amber, never green or grey: the operator must read this as
    "the measurement stopped", not "nothing found" and not "never started".
    When partial data exists the subtitle says exactly what the numbers on
    screen mean -- classification up to the failure, nothing after it.
    """
    if has_partial_data:
        base = ("Results reflect only data classified before the failure -- "
                "screening is incomplete")
    else:
        base = "The run produced no results"
    if detail:
        base += f". {detail}"
    return VerdictDescriptor(
        state="PIPELINE_ERROR",
        icon="exclamation-octagon-fill", icon_color="#dc3545",
        title="PIPELINE ERROR",
        subtitle=base,
        sub_color="#664d03", bg_color="#fff3cd", border_color="#dc3545",
    )


def results_unavailable_descriptor() -> VerdictDescriptor:
    """RESULTS UNAVAILABLE: a previously seen results directory is gone.

    Distinct from STANDBY on purpose -- the directory held data earlier in
    this session, so its absence is an event (unmounted volume, deleted
    folder), not an idle state.
    """
    return VerdictDescriptor(
        state="RESULTS_UNAVAILABLE",
        icon="hdd-fill", icon_color="#dc3545",
        title="RESULTS UNAVAILABLE",
        subtitle=(
            "The results directory can no longer be read -- check that the "
            "volume is still mounted. Screening verdicts are suspended until "
            "it returns"
        ),
        sub_color="#664d03", bg_color="#fff3cd", border_color="#dc3545",
    )


def with_failure_clauses(
    descriptor: VerdictDescriptor,
    *,
    pipeline_error: bool = False,
    pipeline_error_detail: Optional[str] = None,
    stale_samples: int = 0,
    run_stopped: bool = False,
    stop_reason: Optional[str] = None,
    failed_tasks: int = 0,
    input_layout_mismatch: Optional[str] = None,
) -> VerdictDescriptor:
    """Append run-health clauses to a data-state descriptor's subtitle.

    Used on the states that outrank the failure states (detections,
    sub-threshold hits, all-clear): the verdict keeps its identity, and the
    subtitle carries what the operator must also know about the run.

    ``run_stopped`` names a run ended by the operator or by the inactivity
    backstop before its input was exhausted (round-4 audit, H2): an ALL
    CLEAR over such a run is a partial screen, and the banner must not read
    like one over a finished run.
    """
    clauses = []
    if pipeline_error:
        clause = "pipeline error - coverage is partial"
        if pipeline_error_detail:
            clause += f" ({pipeline_error_detail})"
        clauses.append(clause)
    if run_stopped:
        clause = "run stopped before its input was exhausted"
        if stop_reason:
            clause += f" ({stop_reason})"
        clauses.append(clause + " - counts are partial")
    if failed_tasks:
        # nanometanf isolates per-sample failures (errorStrategy ignore) and
        # the run carries on; the reads of a failed batch are simply absent
        # from every count. Round-4 audit, H20: a corrupt input chunk failed
        # in QC and no surface said so while the run was active.
        clauses.append(
            f"{failed_tasks} pipeline task{'s' if failed_tasks != 1 else ''} "
            "failed and were skipped - their reads are not in these counts"
        )
    if stale_samples:
        clauses.append(
            f"{stale_samples} sample{'s' if stale_samples != 1 else ''} "
            "serving stale data"
        )
    if input_layout_mismatch:
        # The sample names this verdict attributes to are the pipeline's
        # grouping of what it found, not the grouping the operator declared
        # (round-5 drills, C13).
        clauses.append(input_layout_mismatch)
    if not clauses:
        return descriptor
    return replace(
        descriptor,
        subtitle=f"{descriptor.subtitle} -- {'; '.join(clauses)}",
    )
