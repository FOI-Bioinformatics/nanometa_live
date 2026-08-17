"""One builder for the ``taxmap-database-info`` store payload.

Three callbacks write this store (Scan Database, startup hydration, and the
profile-override editor), and when the first two were separate hand-built
dicts the same database read "custom" after a restart and "GTDB" after a
scan (2026-08-17 reaudit, G7). Every writer goes through this builder so
the key set cannot drift again.

The raw ``taxids_are_ncbi`` / ``nomenclature`` fields are included so the
override editor can seed its controls from the live profile rather than
re-deriving them from the display label.
"""

from typing import Any, Dict, Optional


def build_db_info(
    profile,
    *,
    db_hash: str = "",
    path: str = "",
    stats: Optional[Dict[str, Any]] = None,
    coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the store dict from a ``DatabaseProfile`` (or None).

    ``stats`` and ``coverage`` are carried through when the caller has them;
    a writer that lacks them (startup, the override editor) should pass the
    previous store's values so the G10 coverage panel is not blanked.
    """
    info: Dict[str, Any] = {
        "path": path,
        "type": profile.display_label if profile else "unknown",
        "detected_by": profile.detected_by if profile else "",
        "overridden": bool(profile.overridden) if profile else False,
        "taxids_are_ncbi": bool(profile.taxids_are_ncbi) if profile else False,
        "nomenclature": (profile.nomenclature.value
                         if profile else "unknown"),
        "hash": db_hash,
    }
    if stats is not None:
        info["stats"] = stats
    if coverage is not None:
        info["coverage"] = coverage
    return info
