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
    for m in order:
        for r in results:
            if getattr(r, "validation_method", None) == m:
                return r
    return results[0]
