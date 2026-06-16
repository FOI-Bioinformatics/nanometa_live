"""Classification-confidence verdict for BLAST read validation.

A pure, side-effect-free derivation so it is fully unit-testable and shared by
the validation UI. It combines the signals already on disk -- mean identity,
coverage breadth, how many distinct reference subjects the reads hit, and read
support -- into a single operator-facing verdict.

This is a heuristic confidence in the *classification* (is this really the
organism the reads were assigned to?), NOT a statistical confidence interval.
The amplicon/concentrated case is handled explicitly: a short conserved locus
legitimately shows low genome-wide breadth, so breadth is not held against it
and a caveat is attached instead.
"""

from __future__ import annotations

from typing import Dict, List


def classification_confidence(
    mean_identity: float,
    coverage_breadth: float,
    subject_agreement: float,
    n_reads: int,
    is_concentrated: bool = False,
) -> Dict[str, object]:
    """Return a confidence verdict for a BLAST-validated (sample, taxid).

    Args:
        mean_identity: Mean percent identity of the read hits (0-100).
        coverage_breadth: Fraction of the reference covered (0-1).
        subject_agreement: Fraction of reads hitting the single most-common
            reference subject (0-1); low values mean reads split across many
            accessions, a sign of ambiguous or mixed classification.
        n_reads: Number of validated reads supporting the call.
        is_concentrated: True for an amplicon / concentrated-coverage locus,
            where low genome-wide breadth is expected and not penalised.

    Returns:
        ``{"level": "high"|"moderate"|"low", "score": float, "reasons": [str]}``
    """
    reasons: List[str] = []

    if n_reads <= 0:
        return {"level": "low", "score": 0.0,
                "reasons": ["No validated reads support this call."]}

    # Identity component (dominant): how well reads match the reference.
    if mean_identity >= 97:
        id_score = 1.0
        reasons.append(f"High sequence identity ({mean_identity:.1f}%).")
    elif mean_identity >= 90:
        id_score = 0.6
        reasons.append(f"Moderate sequence identity ({mean_identity:.1f}%).")
    else:
        id_score = 0.2
        reasons.append(f"Low sequence identity ({mean_identity:.1f}%).")

    # Subject-agreement component: reads concentrated on one accession.
    if subject_agreement >= 0.8:
        subj_score = 1.0
        reasons.append("Reads agree on a single reference subject.")
    elif subject_agreement >= 0.5:
        subj_score = 0.6
        reasons.append("Reads split across a few reference subjects.")
    else:
        subj_score = 0.2
        reasons.append("Reads spread across many reference subjects "
                       "(possible mixed or ambiguous classification).")

    # Breadth component: only meaningful for whole-genome coverage. For an
    # amplicon, low breadth is expected, so it is excluded and noted.
    if is_concentrated:
        breadth_score = None
        reasons.append("Concentrated (amplicon-like) coverage: genome-wide "
                       "breadth is expectedly low and not penalised. A short "
                       "conserved region may match close relatives too.")
    elif coverage_breadth >= 0.5:
        breadth_score = 1.0
        reasons.append(f"Broad reference coverage ({coverage_breadth * 100:.0f}%).")
    elif coverage_breadth >= 0.1:
        breadth_score = 0.6
        reasons.append(f"Partial reference coverage ({coverage_breadth * 100:.0f}%).")
    else:
        breadth_score = 0.3
        reasons.append(f"Narrow reference coverage ({coverage_breadth * 100:.0f}%).")

    # Read-support floor: a handful of reads cannot be high confidence.
    if n_reads < 10:
        reasons.append(f"Limited read support ({n_reads} reads).")

    components = [id_score, subj_score]
    if breadth_score is not None:
        components.append(breadth_score)
    score = sum(components) / len(components)

    if score >= 0.8 and n_reads >= 10:
        level = "high"
    elif score >= 0.5:
        level = "moderate"
    else:
        level = "low"

    # Cap at moderate when read support is thin, regardless of score.
    if n_reads < 10 and level == "high":
        level = "moderate"

    return {"level": level, "score": round(score, 3), "reasons": reasons}
