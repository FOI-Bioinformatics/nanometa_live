"""Walk a nanometanf checkout and inventory each module's container
sources (Singularity URL, Docker reference, conda spec).

Used by both the W6 container-URL audit and the W7 BundleManager
docker/singularity export flows so both consult one parser. The
parser is purely textual -- it reads ``main.nf`` and
``environment.yml`` files, never invokes Nextflow or Conda.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)


# Singularity URLs are matched at depot.galaxyproject.org. Other
# registries (e.g. quay.io) are not in scope for the Singularity-image
# bundle path.
_SINGULARITY_URL_RE = re.compile(
    r"https://depot\.galaxyproject\.org/singularity/[^'\"\s]+"
)
# Docker references covered: biocontainers (legacy quay.io path),
# community.wave.seqera.io (modern nf-core default), and bare quay.io
# refs. The reference is captured between the surrounding quotes.
_DOCKER_REF_RE = re.compile(
    r"['\"]"
    r"(?:biocontainers|community\.wave\.seqera\.io|quay\.io/biocontainers)"
    r"/[^'\"]+"
    r"['\"]"
)


@dataclass(frozen=True)
class ContainerInventoryEntry:
    """One module's container sourcing summary.

    All three fields are independently optional: a local module that
    runs plain bash will have ``conda_spec=None`` and no container
    references; an nf-core module with only a Wave Docker image will
    have ``singularity_url=None`` but a non-empty ``docker_ref``.
    """

    module_name: str
    main_nf_path: Path
    singularity_url: Optional[str] = None
    docker_ref: Optional[str] = None
    conda_spec: Optional[str] = None

    @property
    def has_container(self) -> bool:
        """Module ships at least one container reference."""
        return bool(self.singularity_url or self.docker_ref)


def _parse_main_nf(path: Path) -> tuple[Optional[str], Optional[str]]:
    """Return ``(singularity_url, docker_ref)`` for a module's main.nf."""
    try:
        text = path.read_text()
    except OSError as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return None, None

    sing_match = _SINGULARITY_URL_RE.search(text)
    doc_match = _DOCKER_REF_RE.search(text)
    sing_url = sing_match.group(0) if sing_match else None
    doc_ref = doc_match.group(0).strip("'\"") if doc_match else None
    return sing_url, doc_ref


def _parse_env_yml(path: Path) -> Optional[str]:
    """Return the bioconda dependency string from an environment.yml,
    or ``None`` if the file does not exist or lacks a recognized dep.
    """
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except (yaml.YAMLError, OSError) as exc:
        logger.debug("Could not parse %s: %s", path, exc)
        return None
    if not data:
        return None
    deps = data.get("dependencies", []) or []
    for dep in deps:
        if isinstance(dep, str) and dep.startswith("bioconda::"):
            return dep[len("bioconda::"):]
    # Some modules omit the ``bioconda::`` prefix; accept any
    # ``name=version`` style spec as a fallback.
    for dep in deps:
        if isinstance(dep, str) and "=" in dep:
            return dep
    return None


def _audit_module_dir(module_dir: Path) -> Optional[ContainerInventoryEntry]:
    """Inventory a module that lives in its own directory."""
    main_nf = module_dir / "main.nf"
    if not main_nf.exists():
        return None
    sing_url, doc_ref = _parse_main_nf(main_nf)
    conda_spec = _parse_env_yml(module_dir / "environment.yml")
    # Local modules that live two levels deep (e.g.
    # modules/local/foo/) get just their leaf directory name; nf-core
    # nested modules (e.g. modules/nf-core/blast/blastn/) get the
    # toolname/subname form so the two blast variants stay distinct.
    if module_dir.parent.name == "local":
        name = module_dir.name
    elif module_dir.parent.name == "nf-core":
        name = module_dir.name
    else:
        name = f"{module_dir.parent.name}/{module_dir.name}"
    return ContainerInventoryEntry(
        module_name=name,
        main_nf_path=main_nf,
        singularity_url=sing_url,
        docker_ref=doc_ref,
        conda_spec=conda_spec,
    )


def _audit_flat_module(main_nf_path: Path) -> ContainerInventoryEntry:
    """Inventory a module shipped as a flat ``modules/local/foo.nf`` file.

    Flat-file modules have no sibling ``environment.yml`` so
    ``conda_spec`` is always ``None``.
    """
    sing_url, doc_ref = _parse_main_nf(main_nf_path)
    return ContainerInventoryEntry(
        module_name=main_nf_path.stem,
        main_nf_path=main_nf_path,
        singularity_url=sing_url,
        docker_ref=doc_ref,
        conda_spec=None,
    )


def inventory_pipeline(pipeline_path: Path) -> List[ContainerInventoryEntry]:
    """Walk a nanometanf checkout's ``modules/`` tree and return one
    inventory entry per module discovered.

    Args:
        pipeline_path: Path to the nanometanf repo root (the directory
            containing ``main.nf``, ``modules/``, etc.).

    Returns:
        One entry per module, sorted by ``module_name``. Empty list if
        ``pipeline_path/modules`` does not exist.
    """
    modules_root = Path(pipeline_path) / "modules"
    if not modules_root.is_dir():
        return []

    entries: List[ContainerInventoryEntry] = []

    local_dir = modules_root / "local"
    if local_dir.is_dir():
        for entry in sorted(local_dir.iterdir()):
            if entry.is_dir():
                row = _audit_module_dir(entry)
                if row is not None:
                    entries.append(row)
            elif entry.suffix == ".nf":
                entries.append(_audit_flat_module(entry))

    nfcore_dir = modules_root / "nf-core"
    if nfcore_dir.is_dir():
        for tool_dir in sorted(nfcore_dir.iterdir()):
            if not tool_dir.is_dir():
                continue
            if (tool_dir / "main.nf").exists():
                row = _audit_module_dir(tool_dir)
                if row is not None:
                    entries.append(row)
            else:
                for sub in sorted(tool_dir.iterdir()):
                    if sub.is_dir() and (sub / "main.nf").exists():
                        row = _audit_module_dir(sub)
                        if row is not None:
                            entries.append(row)

    return entries


def unique_container_refs(
    entries: List[ContainerInventoryEntry],
    engine: str,
) -> List[str]:
    """Return the unique container references the given engine needs to pull.

    Two modules sharing the same container image (common -- e.g. multiple
    nf-core modules using the same biocontainer) only need to be pulled
    once. ``engine`` selects which field of each entry to read:
    ``singularity`` reads ``singularity_url``, ``docker`` reads
    ``docker_ref``.

    Args:
        entries: Inventory output from ``inventory_pipeline``.
        engine: Either ``"singularity"`` or ``"docker"``.

    Returns:
        Sorted list of unique reference strings.

    Raises:
        ValueError: If ``engine`` is not one of the supported values.
    """
    if engine == "singularity":
        attr = "singularity_url"
    elif engine == "docker":
        attr = "docker_ref"
    else:
        raise ValueError(
            f"unique_container_refs: unsupported engine {engine!r} "
            "(expected 'singularity' or 'docker')"
        )
    seen = set()
    for e in entries:
        ref = getattr(e, attr)
        if ref:
            seen.add(ref)
    return sorted(seen)
