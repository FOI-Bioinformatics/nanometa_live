"""Pure helpers for on-demand validation.

Split out of ``on_demand_validator`` so that module carries the workflow
and these carry no state -- the same split used for ``*_tab.py`` /
``*_helpers.py`` elsewhere in the codebase. They are imported back under
their original names, so call sites are unchanged.
"""

from pathlib import Path
from typing import Any, Dict, Optional

# Default on-demand validation timeout (minutes) when config does not set one.
_DEFAULT_VALIDATION_TIMEOUT_MINUTES = 30


def _is_int_str(value: Any) -> bool:
    """True if ``value`` is a string (or value) that parses as an int."""
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _normalise_sample_filter(sample: Optional[str]) -> Optional[str]:
    """Map the GUI's aggregate-scope tokens to "no sample filter".

    The Organisms tab passes ``sample="all"`` (and older callers "All
    Samples") when a validation is requested at aggregate scope. Forwarding
    that token into ``ValidationParser.get_validation_results(sample=...)``
    treats it as a literal sample name that matches nothing, so a successful
    validation run was reported to the operator as "did not return a result"
    (2026-08-18). ``None`` means "all samples" to the parser.
    """
    if not sample:
        return None
    if sample.strip().lower() in ("all", "all samples"):
        return None
    return sample


def _genome_file_looks_valid(path: Path) -> bool:
    """Cheap sanity check that ``path`` is a non-empty FASTA file.

    has_genome() only tests existence; a zero-byte or truncated download
    passes it but fails opaquely once Nextflow tries to align against it.
    """
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            first = fh.readline().lstrip()
        return first.startswith(">")
    except OSError:
        return False


def _validation_timeout_seconds(config: Optional[Dict[str, Any]]) -> int:
    """Resolve the subprocess timeout (seconds) from config, floored at 60s."""
    minutes = (config or {}).get(
        "validation_timeout_minutes", _DEFAULT_VALIDATION_TIMEOUT_MINUTES
    )
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        minutes = _DEFAULT_VALIDATION_TIMEOUT_MINUTES
    return max(60, int(minutes * 60))


def _pick_result_for_method(results: list, method: str):
    """Return the parsed ValidationResult matching the requested method.

    ``ValidationParser.get_validation_results`` filters by (sample, taxid) but
    not by method, so for a pair that already carried a result of the other
    method, ``results[0]`` may be the wrong one. Pick the result whose
    ``validation_method`` matches the request; for ``"both"`` prefer the
    read-centric BLAST summary. Falls back to ``results[0]``.
    """
    order = ["blast", "minimap2"] if method == "both" else [method]
    # An aggregate-scope request can match one result per sample; prefer the
    # deepest one so the summary card reflects the sample that carries the
    # detection rather than filesystem enumeration order.
    ranked = sorted(
        results,
        key=lambda r: getattr(r, "total_reads", 0) or 0,
        reverse=True,
    )
    for m in order:
        for r in ranked:
            if getattr(r, "validation_method", None) == m:
                return r
    return ranked[0]
