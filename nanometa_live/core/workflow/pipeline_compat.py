"""Compatibility floor between this GUI and the nanometanf it launches.

The GUI sends parameters that only a sufficiently recent nanometanf declares
(0.18.0 added the assembly parameters that v1.10.0 introduced). nf-schema
rejects unknown parameters, so an older checkout fails at Start with a
message naming a parameter rather than a version. This module reads the
version of the checkout the launch would use and compares it with the floor.

A ``remote:<branch>`` source runs the checkout under the launch's Nextflow
assets directory; the run command carries no ``-latest``, so that checkout is
only as new as the last ``nextflow pull``. Reading it is therefore reading
what will run. Which assets directory that is depends on the launch: a GUI
Start anchors ``NXF_HOME`` at ``<results_output_directory>/.nextflow``
(``NextflowManager._build_nextflow_env``) unless the environment already sets
``NXF_HOME`` or ``NXF_ASSETS``, in which case that wins. Only a bare CLI
invocation with none of those set falls back to the Nextflow default,
``~/.nextflow/assets``. ``nextflow_assets_root`` resolves this in the same
order the launcher does.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

#: The oldest nanometanf whose schema declares every parameter this GUI sends.
NANOMETANF_MIN_VERSION = "1.10.0"

#: Where a resolved Nextflow assets root keeps the default remote
#: repository's checkout (NextflowManager.DEFAULT_REMOTE_REPO).
REMOTE_CHECKOUT_RELPATH = Path("foi-bioinformatics/nanometanf")


def nextflow_assets_root(config: Optional[Mapping[str, Any]] = None) -> Path:
    """Directory Nextflow resolves its assets checkouts under, for THIS launch.

    Order of precedence, matching ``NextflowManager._build_nextflow_env`` and
    Nextflow's own environment handling:

    1. ``NXF_ASSETS``, when set in the environment.
    2. ``NXF_HOME``, when set in the environment (Nextflow keeps assets at
       ``$NXF_HOME/assets``).
    3. ``<results_output_directory>/.nextflow/assets``, when ``config``
       carries a non-empty ``results_output_directory`` -- this is exactly
       what a GUI Start injects as ``NXF_HOME`` before the operator's own
       environment is consulted (``nextflow_manager.py:876-900``).
    4. ``~/.nextflow/assets``, Nextflow's own default, when none of the above
       apply (a bare CLI invocation with no results directory yet).
    """
    env_assets = os.environ.get("NXF_ASSETS")
    if env_assets:
        return Path(env_assets)
    env_home = os.environ.get("NXF_HOME")
    if env_home:
        return Path(env_home) / "assets"
    if config:
        results_dir = config.get("results_output_directory")
        if results_dir:
            return Path(os.path.abspath(results_dir)) / ".nextflow" / "assets"
    return Path("~/.nextflow/assets").expanduser()


_MANIFEST_VERSION_RE = re.compile(
    r"manifest\s*\{[^}]*?\bversion\s*=\s*['\"]([^'\"]+)['\"]", re.S
)


def parse_manifest_version(config_text: str) -> Optional[str]:
    """Return ``manifest.version`` from ``nextflow.config`` text, or None.

    The search is anchored on the ``manifest {`` block so the
    ``params.version = false`` that nf-core pipelines carry is not matched.
    """
    match = _MANIFEST_VERSION_RE.search(config_text)
    return match.group(1).strip() if match else None


def version_key(version: str) -> Tuple[int, int, int, int]:
    """Sortable key for a pipeline version string.

    A ``dev`` suffix marks a pre-release of that number, so
    ``1.10.0dev < 1.10.0 < 1.10.1dev``. Missing components read as zero.
    """
    text = version.strip().lstrip("vV")
    is_dev = text.endswith("dev")
    if is_dev:
        text = text[: -len("dev")].rstrip(".-")
    parts = []
    for piece in text.split("."):
        digits = re.match(r"\d+", piece)
        parts.append(int(digits.group(0)) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts[:3]
    return (major, minor, patch, 0 if is_dev else 1)


def resolve_pipeline_checkout(
    pipeline_source: str, config: Optional[Mapping[str, Any]] = None,
) -> Optional[Path]:
    """Directory a launch of ``pipeline_source`` would run from, or None.

    Mirrors ``NextflowManager._parse_pipeline_source``: ``remote:<rev>`` and
    the bare ``master`` / ``dev`` forms run from the Nextflow assets
    checkout under ``nextflow_assets_root(config)``; ``local:<path>`` and
    bare paths run from that path. URL forms are not resolved (the launcher
    refuses them in offline mode and Nextflow clones them under a name this
    module does not predict).
    """
    source = (pipeline_source or "").strip()
    if not source:
        return None
    if source.startswith("remote:") or source in ("master", "dev"):
        return nextflow_assets_root(config) / REMOTE_CHECKOUT_RELPATH
    if source.startswith("local:"):
        source = source.split(":", 1)[1]
    if source.startswith(("http://", "https://", "git@")):
        return None
    return Path(source).expanduser()


@dataclass(frozen=True)
class CompatVerdict:
    """Outcome of the compatibility check.

    ``status`` is ``"ok"``, ``"too_old"`` or ``"unknown"``. ``unknown`` means
    the version could not be read (no checkout yet, no ``nextflow.config``,
    or no manifest version in it); it is a warning, not a refusal, because
    a first ``remote:`` launch legitimately has no checkout until Nextflow
    pulls one.
    """

    status: str
    found_version: Optional[str]
    checkout: Optional[Path]
    message: str


def _fix_for(
    pipeline_source: str,
    checkout: Optional[Path],
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    source = (pipeline_source or "").strip()
    revision: Optional[str] = None
    if source.startswith("remote:"):
        revision = source.split(":", 1)[1] or "master"
    elif source in ("master", "dev"):
        revision = source
    if revision is not None:
        pull_cmd = f"nextflow pull foi-bioinformatics/nanometanf -r {revision}"
        assets_root = nextflow_assets_root(config)
        default_root = Path("~/.nextflow/assets").expanduser()
        if assets_root != default_root:
            nxf_home = assets_root.parent
            return f"run 'NXF_HOME={nxf_home} {pull_cmd}'"
        return f"run '{pull_cmd}'"
    return f"update the checkout at {checkout}"


def check_pipeline_compatibility(
    pipeline_source: str,
    floor: str = NANOMETANF_MIN_VERSION,
    config: Optional[Mapping[str, Any]] = None,
) -> CompatVerdict:
    """Compare the version of the checkout ``pipeline_source`` runs with ``floor``.

    ``config``, when given, is the loaded application configuration; it is
    consulted only to resolve the Nextflow assets root a ``remote:`` source
    runs from (see ``nextflow_assets_root``) and is otherwise not read.
    """
    checkout = resolve_pipeline_checkout(pipeline_source, config)
    config_path = (checkout / "nextflow.config") if checkout else None
    if config_path is None or not config_path.is_file():
        where = f" at {checkout}" if checkout else ""
        return CompatVerdict(
            "unknown", None, checkout,
            f"Could not read the pipeline version{where}; nanometanf >= {floor} "
            f"is required. If the run fails at parameter validation, update the pipeline.",
        )
    try:
        text = config_path.read_text(errors="replace")
    except OSError as exc:
        return CompatVerdict(
            "unknown", None, checkout,
            f"Could not read {config_path} ({exc}); nanometanf >= {floor} is required.",
        )
    found = parse_manifest_version(text)
    if found is None:
        return CompatVerdict(
            "unknown", None, checkout,
            f"{config_path} carries no manifest version; nanometanf >= {floor} is required.",
        )
    if version_key(found) >= version_key(floor):
        return CompatVerdict(
            "ok", found, checkout, f"nanometanf {found} at {checkout} (>= {floor})",
        )
    return CompatVerdict(
        "too_old", found, checkout,
        f"nanometanf {found} found at {checkout}, but this Nanometa Live release "
        f"requires >= {floor}: the run would reject the parameters it sends. "
        f"To fix, {_fix_for(pipeline_source, checkout, config)}.",
    )
