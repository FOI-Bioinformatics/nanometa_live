"""Per-sample attribution for watchlist detections.

``_load_per_sample_organisms`` (dashboard helpers) returns a dict keyed by the
taxid as it appears in the Kraken2 report. A watchlist detection carries TWO
taxids: ``taxid`` (the NCBI taxid on the watchlist entry) and
``detected_taxid`` (the report taxid it matched). On an NCBI database the two
coincide; on a GTDB or custom database they do not, and looking a detection up
under the wrong one misses every sample -- silently, since a missing sample
list is indistinguishable from a detection with no samples.

Every surface that attributes a detection to samples (verdict banner, pathogen
alert panel, alert engine, exported report) resolves through the helpers here
so they cannot drift apart again. The module is deliberately free of Dash and
pandas imports so it can be used from ``core`` as well as ``app``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

#: Read floor for a taxon to be considered present in a sample at all. This is
#: a discovery floor only -- whether a sample counts as *triggering* is decided
#: against the pathogen's own ``alert_threshold``.
PER_SAMPLE_DISCOVERY_FLOOR = 5

#: Sample-name tokens that identify a negative control on their own.
_NC_EXACT_TOKENS = frozenset({
    "ntc", "nc", "blank", "negctrl", "negcontrol", "negativecontrol", "negcon",
})
_NC_NEGATIVE_TOKENS = frozenset({"negative", "neg"})
_NC_CONTROL_TOKENS = frozenset({"control", "ctrl", "ctl"})

#: Words that name a sample rather than describe biology. "negative" beside
#: one of these means a control; beside anything else it is a descriptor, so
#: ``negative_strand_test`` stays a real sample.
_NC_SAMPLE_WORDS = frozenset({
    "sample", "barcode", "bc", "rep", "replicate", "run", "lib", "library",
})
#: A bare sample identifier: barcode16, bc12, s3, 01.
_NC_SAMPLE_ID_RE = re.compile(r"^(?:barcode|bc|sample|smpl|rep|run|s|r)?\d+$")
def is_negative_control(
    sample: str, config: Optional[Dict[str, Any]] = None
) -> bool:
    """Whether a sample name identifies a negative control.

    An explicit ``negative_control_samples`` list in the config is
    authoritative; the token patterns below are the fallback for runs where
    the operator has not declared one. Substring matching on "negative" alone
    is deliberately avoided -- it misses ``NTC`` / ``neg_ctrl`` / ``blank``
    and falsely flags a sample such as ``negative_strand_test``.
    """
    if not sample:
        return False

    name = str(sample).strip()
    for declared in (config or {}).get("negative_control_samples", []) or []:
        if name.lower() == str(declared).strip().lower():
            return True

    tokens = [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]
    if not tokens:
        return False
    token_set = set(tokens)
    if token_set & _NC_EXACT_TOKENS:
        return True
    if "".join(tokens) in _NC_EXACT_TOKENS:
        return True
    if token_set & _NC_NEGATIVE_TOKENS:
        # "negative" needs a control word beside it (or to stand alone);
        # otherwise "negative_strand_test" reads as a control.
        if token_set & _NC_CONTROL_TOKENS or len(tokens) == 1:
            return True
        # ...or nothing beside it but a sample identifier. This is how
        # operators actually name the control -- a real Bioshield run used
        # "negative_barcode16", which has no control word and so was read as a
        # clinical sample, then carried 6 F. tularensis reads out of 11 past
        # that entry's alert threshold of 5.
        #
        # The distinction is what sits next to "negative": "barcode16" names a
        # sample, "strand" describes a molecule. Only the first makes this a
        # control, so negative_strand_test is still excluded.
        others = token_set - _NC_NEGATIVE_TOKENS
        if others and all(
            t in _NC_SAMPLE_WORDS or _NC_SAMPLE_ID_RE.match(t) for t in others
        ):
            return True
    if "template" in token_set and token_set & {"no", "non"}:
        return True
    return False


@dataclass
class PathogenAttribution:
    """Which samples a single watchlist detection is attributable to.

    ``samples`` are the samples that cleared the pathogen's own
    ``alert_threshold`` on their own. ``below_threshold_samples`` carry the
    taxon above the discovery floor but below that threshold -- they are the
    reason an aggregate can be positive while no individual sample is.
    """

    pathogen: str
    samples: List[str]
    below_threshold_samples: List[str]
    top_reads: int

    @property
    def resolved(self) -> bool:
        """True when at least one sample was found for this detection."""
        return bool(self.samples or self.below_threshold_samples)


def resolve_attribution_taxids(detection: Dict[str, Any]) -> List[int]:
    """Candidate taxids to look a detection up by, most specific first.

    ``detected_taxid`` is the Kraken2 report taxid the detection actually
    matched, so it is tried first; ``taxid`` (NCBI) is the fallback for
    detections produced by the non-mapping ``check_organisms`` path.
    """
    candidates: List[int] = []
    for key in ("detected_taxid", "taxid"):
        raw = detection.get(key)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value not in candidates:
            candidates.append(value)
    return candidates


def samples_for_detection(
    detection: Dict[str, Any],
    taxid_to_samples: Dict[int, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Per-sample rows for one detection, or [] when none can be resolved."""
    for taxid in resolve_attribution_taxids(detection):
        found = taxid_to_samples.get(taxid)
        if found:
            return found
    return []


def _detection_label(detection: Dict[str, Any]) -> str:
    name = detection.get("name") or detection.get("common_name") or "Unknown organism"
    annotation = detection.get("annotation")
    return f"{name} ({annotation})" if annotation else str(name)


def build_pathogen_attribution(
    detections: List[Dict[str, Any]],
    taxid_to_samples: Dict[int, List[Dict[str, Any]]],
) -> List[PathogenAttribution]:
    """Pair each detection with the samples that carry it, sorted by reads.

    A sample is listed as triggering only when its own read count reaches the
    pathogen's ``alert_threshold``; the verdict is decided on the aggregate,
    so without this gate ten barcodes at 50 reads each would all be named for
    a pathogen with a threshold of 100 though none is individually positive.
    """
    attributions: List[PathogenAttribution] = []
    seen_labels: set = set()

    for detection in detections:
        label = _detection_label(detection)
        if label in seen_labels:
            continue
        seen_labels.add(label)

        rows = samples_for_detection(detection, taxid_to_samples)
        try:
            threshold = int(detection.get("threshold") or 0)
        except (TypeError, ValueError):
            threshold = 0

        above, below = [], []
        for row in rows:
            name = row.get("sample")
            if not name:
                continue
            reads = row.get("reads", 0) or 0
            (above if reads >= threshold else below).append(name)

        sample_reads = [r.get("reads", 0) or 0 for r in rows]
        top_reads = max(sample_reads) if sample_reads else (
            detection.get("reads", 0) or 0
        )
        attributions.append(
            PathogenAttribution(
                pathogen=label,
                samples=above,
                below_threshold_samples=below,
                top_reads=int(top_reads),
            )
        )

    attributions.sort(key=lambda a: a.top_reads, reverse=True)
    return attributions


def _attribution_phrase(attribution: PathogenAttribution) -> Optional[str]:
    """One "Pathogen (barcode…)" clause, or None when nothing is known."""
    if attribution.samples:
        shown = attribution.samples[:3]
        overflow = len(attribution.samples) - len(shown)
        names = ", ".join(shown)
        if overflow > 0:
            names += f", +{overflow} more"
        return f"{attribution.pathogen} ({names})"
    if attribution.below_threshold_samples:
        n = len(attribution.below_threshold_samples)
        return (
            f"{attribution.pathogen} (aggregate across {n} "
            f"sample{'s' if n != 1 else ''})"
        )
    return None


def format_attribution_text(
    attributions: List[PathogenAttribution],
    max_pathogens: int = 4,
) -> Optional[str]:
    """Render the pathogen-to-sample pairing as a single subhead string."""
    phrases = [
        phrase for phrase in (_attribution_phrase(a) for a in attributions)
        if phrase
    ]
    if not phrases:
        return None
    shown = phrases[:max_pathogens]
    overflow = len(phrases) - len(shown)
    text = "Triggered by: " + "; ".join(shown)
    if overflow > 0:
        text += f" (+{overflow} more)"
    return text


