"""Path normalisation helpers for config-managed filesystem paths.

The "Kraken2 database directory not found" class of error has historically
been caused by paths that were stored verbatim from the input field. A
literal "~/data/kraken_db" string fails every os.path.exists check; a
relative path stored to last-session.yaml resolves against whatever
working directory the app is launched from next time, producing
intermittent failures that look random.

normalise_path is the canonical fix: strip whitespace, expand ~, resolve
to an absolute path. Apply at write time (config save) and again at load
time (last-session reload) so a stale YAML self-heals on first load.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)


# Config keys whose values are filesystem paths and therefore eligible for
# normalisation. Listed explicitly rather than inferred so a future
# string-typed but non-path config key (e.g. an analysis label that
# happens to start with "/") does not get silently rewritten.
PATH_CONFIG_KEYS: tuple[str, ...] = (
    "nanopore_output_directory",
    "results_output_directory",
    "main_dir",
    "kraken_db",
    "external_kraken2_db",
    "blast_db_dir",
    "kraken_taxonomy",
    "genome_cache_dir",
    "data_dir",
    "pipeline_source",  # only when the value is a local checkout path
)


def normalise_path(value: Optional[str]) -> str:
    """Return a canonical absolute path string for a user-supplied value.

    Behaviour:
        empty or whitespace-only -> ""
        starts with "remote:" or a URL scheme -> returned stripped, NOT resolved
            (these are pipeline-source identifiers, not filesystem paths)
        otherwise -> stripped, expanduser, abspath

    Returns the empty string for None or empty input so the result is
    always a str and callers can blindly write it back to a config dict.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""

    # Pipeline-source identifiers are stored in the same string-typed
    # config key as filesystem checkout paths. Recognise the prefixes
    # used elsewhere in the codebase (see CLAUDE.md, pipeline_source).
    lowered = s.lower()
    if (
        lowered.startswith("remote:")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("git@")
    ):
        return s

    # Bundle export/import uses sentinel relative paths like
    # "./pipeline_source" and "./nextflow_plugins" inside the
    # bundle's config.yaml; the import-side rebase logic in
    # core.workflow.bundle_manager checks for those exact strings to
    # decide whether to rewrite them to absolute paths on the field
    # machine. Resolving them here would silently disable that
    # rebase. Leave any "./" / "../" prefixed value alone -- the few
    # legitimate relative paths in normal configs are caught by the
    # existence check at the boundary, not by accidental absolutising.
    if s.startswith("./") or s.startswith("../"):
        return s

    return os.path.abspath(os.path.expanduser(s))


def normalise_config_paths(
    config: MutableMapping[str, object],
    keys: Iterable[str] = PATH_CONFIG_KEYS,
) -> list[str]:
    """Normalise every path-bearing key in *config* in place.

    Returns the list of keys that were rewritten so the caller can log
    or surface them. Keys that are absent or whose normalised value
    matches the original are skipped. Non-string values are left
    untouched (a numeric or list-typed value is not a path; this keeps
    the helper safe against schema drift).
    """
    rewritten: list[str] = []
    for key in keys:
        if key not in config:
            continue
        original = config[key]
        if not isinstance(original, str):
            continue
        canonical = normalise_path(original)
        if canonical != original:
            config[key] = canonical
            rewritten.append(key)
    return rewritten


def report_missing_paths(
    config: Mapping[str, object],
    keys: Iterable[str] = PATH_CONFIG_KEYS,
) -> dict[str, str]:
    """Return {key: path} for every path-bearing key whose value is set
    and refers to a missing filesystem location.

    Empty values, "remote:..."/URL identifiers, and non-string values
    are excluded. Callers (config-load, readiness panel) use this to
    surface "the YAML you loaded points at directories that have moved"
    without having to clear the field automatically.
    """
    missing: dict[str, str] = {}
    for key in keys:
        if key not in config:
            continue
        value = config[key]
        if not isinstance(value, str) or not value:
            continue
        lowered = value.lower()
        if (
            lowered.startswith("remote:")
            or lowered.startswith("http://")
            or lowered.startswith("https://")
            or lowered.startswith("git@")
        ):
            continue
        if not os.path.exists(value):
            missing[key] = value
    return missing
