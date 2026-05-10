"""Outdir resolution for fingerprint and freshness callbacks.

A small helper extracted from ``app/callbacks.py:compute_results_fingerprint``
so the priority order can be unit-tested.

Priority order (results_output_directory before main_dir) exists because
``BackendManager._setup_project`` repurposes ``config["main_dir"]`` as
the Nextflow project directory (``~/.nanometa/data/analysis_*/``, where
it stores ``config.json`` and scratch). Pipeline outputs land at
``results_output_directory`` and are what the fingerprint must observe.
The fallback to ``main_dir`` keeps the existing-data view
(``--main_dir /path/to/results``) working when no
``results_output_directory`` is set.
"""

from __future__ import annotations

from typing import Any, Mapping


def resolve_outdir_for_fingerprint(config: Mapping[str, Any] | None) -> str:
    """Return the path the fingerprint should scan for data freshness.

    Returns ``results_output_directory`` if set, falling back to
    ``main_dir``. Returns an empty string when neither is set or
    ``config`` is falsy.
    """
    if not config:
        return ""
    return (
        config.get("results_output_directory")
        or config.get("main_dir")
        or ""
    )
