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

import re
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


# Characters that are unsafe or awkward in a folder name. Whitespace and
# anything outside [A-Za-z0-9._-] collapses to a single underscore. Path
# separators are therefore stripped, so a run name can never escape the
# project's results/ container.
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_run_name(name: Any) -> str:
    """Turn an operator-supplied run/analysis name into a folder-safe slug.

    Collapses runs of unsafe characters (incl. path separators and
    whitespace) to ``_``, trims leading/trailing ``_.-``, and never returns
    an empty string (falls back to ``"run"``). Examples::

        "Patient 0042 blood"  -> "Patient_0042_blood"
        "../etc/passwd"       -> "etc_passwd"
        ""                    -> "run"
    """
    text = str(name or "").strip()
    slug = _SLUG_UNSAFE.sub("_", text).strip("_.-")
    return slug or "run"


def resolve_run_outdir(config: Mapping[str, Any] | None) -> str:
    """Resolve the concrete output directory for a run.

    Precedence:
      1. An explicit, non-empty ``results_output_directory`` is an operator
         override and is returned verbatim.
      2. Otherwise derive ``<project>/results/<run-slug>`` from the project
         dir (or the legacy ``~/nanometa_results/<run-slug>`` when no project
         is configured), where the slug comes from ``analysis_name``.
    """
    if not config:
        return ""
    explicit = (config.get("results_output_directory") or "").strip()
    if explicit:
        return explicit
    from nanometa_live.core.utils.paths import NanometaPaths
    run_slug = slugify_run_name(config.get("analysis_name"))
    return str(NanometaPaths.from_config(config).run_dir(run_slug))
