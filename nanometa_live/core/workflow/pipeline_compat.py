"""Compatibility floor between this GUI and the nanometanf it launches.

The GUI sends parameters that only a sufficiently recent nanometanf declares
(0.18.0 added the assembly parameters that v1.10.0 introduced). nf-schema
rejects unknown parameters, so an older checkout fails at Start with a
message naming a parameter rather than a version. This module reads the
version of the checkout the launch would use and compares it with the floor.

A ``remote:<branch>`` source runs the checkout under
``~/.nextflow/assets/foi-bioinformatics/nanometanf``; the run command carries
no ``-latest``, so that checkout is only as new as the last ``nextflow pull``.
Reading it is therefore reading what will run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

#: The oldest nanometanf whose schema declares every parameter this GUI sends.
NANOMETANF_MIN_VERSION = "1.10.0"

#: Where Nextflow keeps the checkout for the default remote repository
#: (NextflowManager.DEFAULT_REMOTE_REPO). Module-level so tests can point it
#: at a temporary directory.
NEXTFLOW_ASSETS_CHECKOUT = Path("~/.nextflow/assets/foi-bioinformatics/nanometanf")

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


def resolve_pipeline_checkout(pipeline_source: str) -> Optional[Path]:
    """Directory a launch of ``pipeline_source`` would run from, or None.

    Mirrors ``NextflowManager._parse_pipeline_source``: ``remote:<rev>`` and
    the bare ``master`` / ``dev`` forms run from the Nextflow assets
    checkout; ``local:<path>`` and bare paths run from that path. URL forms
    are not resolved (the launcher refuses them in offline mode and
    Nextflow clones them under a name this module does not predict).
    """
    source = (pipeline_source or "").strip()
    if not source:
        return None
    if source.startswith("remote:") or source in ("master", "dev"):
        return NEXTFLOW_ASSETS_CHECKOUT.expanduser()
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


def _fix_for(pipeline_source: str, checkout: Optional[Path]) -> str:
    source = (pipeline_source or "").strip()
    if source.startswith("remote:"):
        revision = source.split(":", 1)[1] or "master"
        return f"run 'nextflow pull foi-bioinformatics/nanometanf -r {revision}'"
    if source in ("master", "dev"):
        return f"run 'nextflow pull foi-bioinformatics/nanometanf -r {source}'"
    return f"update the checkout at {checkout}"


def check_pipeline_compatibility(
    pipeline_source: str,
    floor: str = NANOMETANF_MIN_VERSION,
) -> CompatVerdict:
    """Compare the version of the checkout ``pipeline_source`` runs with ``floor``."""
    checkout = resolve_pipeline_checkout(pipeline_source)
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
        f"To fix, {_fix_for(pipeline_source, checkout)}.",
    )
