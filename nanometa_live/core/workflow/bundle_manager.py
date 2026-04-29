"""
Bundle manager for exporting and importing mobile lab preparation bundles.

Handles packaging all cached data (genomes, BLAST DBs, mappings, taxonomy cache,
containers, watchlists) into a portable tar.gz archive with path rebasing for
cross-machine transfers. The Kraken2 database itself is never included due to
its size.
"""

import getpass
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple


logger = logging.getLogger(__name__)

# Supported offline-deployment engines. The choice is made at bundle
# build time; the field machine consumes whatever artefacts the
# selected engine produced. See docs/plan-2026-04-28-throughput-fixes.md
# Wave 7 for the design rationale.
ContainerizationMode = Literal["conda", "docker", "singularity"]
SUPPORTED_CONTAINERIZATION_MODES = ("conda", "docker", "singularity")

# Placeholder token for absolute paths in exported metadata
_HOME_PLACEHOLDER = "${NANOMETA_HOME}"

# Where we stage pulled Docker tar archives and Singularity .sif files
# during build. This is distinct from the existing ``containers/``
# staging directory which holds operator-managed BLAST containers
# copied from ``~/.nanometa/containers``.
_BUNDLED_PIPELINE_CONTAINERS_DIRNAME = "pipeline_containers"

# Per-engine docker/apptainer command timeout in seconds. A 1 GB
# container image typically pulls in 30-90 s on a fast link; 600 s
# leaves headroom for slow connections without hanging an aborted
# build.
_CONTAINER_PULL_TIMEOUT_S = 600

# Default location inside the bundle staging area for the pre-warmed
# Nextflow conda cache. Operators set NXF_CONDA_CACHEDIR to the
# extracted location of this directory on the field machine.
_BUNDLED_CONDA_CACHE_DIRNAME = "conda_cache"

# Filename of the operator-sourced activation helper that exports
# NXF_CONDA_CACHEDIR. The same content is shipped both in the repo at
# scripts/activate_offline_envs.sh and embedded into every bundle that
# carries a pre-warmed cache, so the field machine never depends on the
# build-host repo layout.
_ACTIVATE_SCRIPT_FILENAME = "activate_offline_envs.sh"

_ACTIVATE_SCRIPT_TEMPLATE = """#!/usr/bin/env bash
# Activate Nextflow's pre-warmed per-process conda cache shipped with a
# Nanometa Live offline bundle.
#
# Usage:
#     source ./activate_offline_envs.sh
#
# The script auto-detects the bundle install directory from its own
# location, exports NXF_CONDA_CACHEDIR to the bundled cache directory,
# and prints a single-line ready message. Source this from the
# operator's shell before launching Nanometa Live.

set -euo pipefail

if [ -n "${{BASH_SOURCE[0]:-}}" ]; then
    _script_path="${{BASH_SOURCE[0]}}"
else
    _script_path="$0"
fi
_install_dir="$(cd "$(dirname "${{_script_path}}")" && pwd)"

if [ -d "${{_install_dir}}/{cache_dirname}" ]; then
    _cache_dir="${{_install_dir}}/{cache_dirname}"
elif [ -d "${{_install_dir}}/../{cache_dirname}" ]; then
    _cache_dir="$(cd "${{_install_dir}}/.." && pwd)/{cache_dirname}"
else
    echo "activate_offline_envs.sh: {cache_dirname} directory not found near ${{_install_dir}}" >&2
    return 1 2>/dev/null || exit 1
fi

export NXF_CONDA_CACHEDIR="${{_cache_dir}}"
export NXF_OFFLINE="${{NXF_OFFLINE:-true}}"

echo "Nanometa Live offline envs ready: NXF_CONDA_CACHEDIR=${{NXF_CONDA_CACHEDIR}}"
"""

# Subdirectory name inside the bundle for the bundled pipeline source checkout.
_BUNDLED_PIPELINE_DIRNAME = "pipeline_source"

# Subdirectory name inside the bundle for the bundled Nextflow plugin cache.
_BUNDLED_NXF_PLUGINS_DIRNAME = "nextflow_plugins"

# Patterns of files and directories to skip when copying the pipeline source
# to keep bundle size manageable.
_PIPELINE_IGNORE_PATTERNS = (
    ".git",
    "work",
    ".nextflow",
    ".nextflow.log*",
    "tests",
    ".nf-test",
    "*.pyc",
    "__pycache__",
)

# Pipeline scenarios used to drive Nextflow's stub mode during the
# pre-warm step. Each scenario corresponds to a sample-handling mode
# the field operator may run; together they cover every per-process
# environment.yml in nanometanf at the time of writing.
_PRE_WARM_SCENARIOS = [
    {
        "name": "batch_samplesheet",
        "params": {
            "processing_mode": "batch",
            "sample_handling": "single_sample",
        },
        "comment": (
            "Default batch path with chopper QC. Covers chopper, seqkit, "
            "nanoplot, kraken2, taxpasta, multiqc, manifest writers."
        ),
    },
    {
        "name": "realtime_multiplex",
        "params": {
            "processing_mode": "realtime",
            "sample_handling": "by_barcode",
        },
        "comment": (
            "Realtime watchPath barcode mode; same env set as batch "
            "plus the realtime-only kraken2 incremental classifier."
        ),
    },
    {
        "name": "realtime_per_file",
        "params": {
            "processing_mode": "realtime",
            "sample_handling": "per_file",
        },
        "comment": "Realtime per-file fan-out; reuses realtime envs.",
    },
    {
        "name": "realtime_single_sample",
        "params": {
            "processing_mode": "realtime",
            "sample_handling": "single_sample",
        },
        "comment": "Realtime single-sample aggregation path.",
    },
    {
        "name": "validation_blast",
        "params": {
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "run_validation": "true",
            "validation_method": "blast",
            "skip_kraken2": "false",
        },
        "comment": (
            "Triggers BLASTN_VALIDATION, BLAST_MAKEBLASTDB, and "
            "EXTRACT_READS_BY_TAXID envs; required for offline pathogen "
            "confirmation."
        ),
    },
    {
        "name": "validation_minimap2",
        "params": {
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "run_validation": "true",
            "validation_method": "minimap2",
        },
        "comment": (
            "Triggers MINIMAP2_ALIGNMENT_VALIDATION and the samtools env "
            "used for alignment post-processing."
        ),
    },
    {
        "name": "fastp_qc",
        "params": {
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "qc_tool": "fastp",
        },
        "comment": (
            "Switches QC tool from chopper to fastp; covers FASTP and "
            "FASTP_STREAMING envs that the default chopper path skips."
        ),
    },
    {
        "name": "assembly_flye",
        "params": {
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "enable_assembly": "true",
        },
        "comment": (
            "Enables the assembly subworkflow so flye and miniasm conda "
            "envs are pre-built. Assembly is opt-in via enable_assembly "
            "and stays off in default field deployments, but field labs "
            "running de novo assembly need these envs cached."
        ),
    },
    {
        "name": "untar_kraken2_db",
        "params": {
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "kraken2_db": (
                "https://raw.githubusercontent.com/nf-core/test-datasets/"
                "modules/data/genomics/sarscov2/genome/db/kraken2.tar.gz"
            ),
        },
        "comment": (
            "Triggers UNTAR on a tar.gz Kraken2 DB so the untar conda "
            "env is cached. Operators handing the field machine a "
            "tarred DB need this env to avoid a network fetch on first "
            "launch."
        ),
    },
]

# README sub-block describing the manual pre-warm workaround used when
# the bundle did NOT pre-warm conda envs at build time.
_README_CONDA_CACHE_MANUAL = """The bundle you received was built without ``pre_warm_conda_envs``,
so the per-process envs are NOT included. Recommended workflow:

1. On the build machine (online), run every scenario you intend to
   use on the field machine at least once with
   ``pipeline_profile: conda``. This populates
   ``~/.nanometa/work/conda/`` with all required envs.
2. Include that directory in the deployment package transferred to
   the field machine.
3. On the field machine, point Nextflow at the unpacked cache
   before launching Nanometa Live::

       export NXF_CONDA_CACHEDIR=/path/to/unpacked/conda_cache

Without this, the first realtime or validation run on a fresh
field machine will require network access to create the missing
envs."""

# README sub-block describing the auto pre-warmed conda cache that
# is included in the bundle when ``pre_warm_conda_envs=True`` was
# passed to ``export_bundle``.
_README_CONDA_CACHE_AUTO = """This bundle was built with ``pre_warm_conda_envs=True``, so a
populated ``conda_cache/`` directory is included alongside the
other bundle contents.

After ``import_bundle`` the cache lives at::

    {{NANOMETA_HOME}}/{conda_cache_dirname}

The helper script ``activate_offline_envs.sh`` (installed
alongside the cache by ``import_bundle``) does the export for
you. From the install directory, run::

    source ./activate_offline_envs.sh

That sets ``NXF_CONDA_CACHEDIR`` to the bundled cache and
``NXF_OFFLINE=true`` so Nextflow does not try to refresh itself
on a network-restricted field machine. As a manual fallback the
same effect is::

    export NXF_CONDA_CACHEDIR=$HOME/.nanometa/{conda_cache_dirname}

Pre-warmed scenarios cover:
{scenario_summary}

Note: the pre-warmed envs are pinned to the exact module
``environment.yml`` SHAs in the nanometanf checkout used at build
time. If the field machine is later upgraded to a newer
nanometanf release, missing envs will require a rebuild of the
bundle."""

# Field README template
_README_TEMPLATE = """# Nanometa Live - Offline Bundle

Created: {creation_date}
Creator: {creator}
Bundle version: {version}

## Quick-start

1. Transfer this bundle and the Kraken2 database to the field machine.
2. Open the Preparation tab in Nanometa Live.
3. In the Export/Import section, click "Import Bundle" and provide:
   - Path to this bundle file
   - Path to the Kraken2 database on this machine
4. The application will automatically enter offline mode.

## First-time machine setup (when an outer install bundle accompanies this archive)

If this archive is paired with a conda-packed environment tarball
(commonly named ``conda_envs/nf-core.tar.gz``), restore it on the field
machine before launching Nanometa Live. Note that the ``conda-unpack``
binary is not on PATH until the tarball is extracted, so it must be
invoked from the extracted prefix directly:

    mkdir -p ~/miniforge3/envs/nf-core
    tar -xzf conda_envs/nf-core.tar.gz -C ~/miniforge3/envs/nf-core
    ~/miniforge3/envs/nf-core/bin/conda-unpack

This relinks the environment to its new prefix and removes the
build-machine paths.

## NXF_CONDA_CACHEDIR (Nextflow per-process conda envs)

Nextflow's conda profile creates a separate environment for every
process module on first use. These environments are NOT the same as
the monolithic ``nf-core`` environment above; they are hashed from
each module's ``environment.yml`` and live under
``${{NXF_CONDA_CACHEDIR}}`` (default: ``work/conda``).

For an offline run the field machine must have these per-process envs
already present, otherwise Nextflow will try to resolve packages from
bioconda/conda-forge and fail.

{conda_cache_section}

## Contents

- genomes/                       Reference genome FASTA files
- blast/                         Pre-built BLAST databases
- mappings/                      Taxid mapping files
- cache/                         Taxonomy cache (GTDB + NCBI snapshots)
- watchlists/                    Watchlist YAML configurations
- containers/                    Container images (if included)
- watchlist_toggle_state.yaml    Per-entry enable/disable selections
- config.yaml                    Application configuration snapshot
- manifest.json                  Bundle manifest with checksums

## Notes

- The Kraken2 database is NOT included due to its size.
  Transfer it separately (e.g. via USB drive).
- Container images ({container_runtime}) are included if they were
  cached during preparation.
- Tool versions used during preparation are recorded in manifest.json.
- Build-time tools such as ``conda-pack`` and ``datasets`` are not
  required at runtime; if a version warning lists them as missing
  locally that is informational only.

## Platform restriction for pre-warmed conda envs

Conda environments built by Nextflow under ``NXF_CONDA_CACHEDIR`` embed
absolute build-machine paths and per-architecture binaries. They cannot
be relocated across operating systems or CPU architectures. **The build
machine and the field machine must share the same OS and CPU
architecture** (for example, both Linux x86_64, or both macOS arm64).

A bundle built on macOS arm64 will not run on Linux x86_64 even if the
Python and Nextflow versions match. ``import_bundle`` records the build
platform in ``manifest.json`` and emits a WARNING (not CRITICAL) at
import time when it detects a mismatch, so an operator who ignores the
warning will still hit a runtime failure once Nextflow tries to spawn a
process from the cached env.

If cross-platform deployment is required, do not pre-warm conda envs at
build time. Instead, ship the bundle without them and let the field
machine resolve envs from each module's ``environment.yml`` on first
run (this requires the field machine to have brief network access for
the bioconda fetches, or a private bioconda mirror reachable from the
field network).
"""


class BundleManager:
    """Export and import portable mobile lab bundles."""

    def export_bundle(
        self,
        output_path: str,
        config: Dict[str, Any],
        nanometa_home: Optional[str] = None,
        pre_warm_conda_envs: bool = False,
        pipeline_path: Optional[str] = None,
        containerization: Optional[ContainerizationMode] = None,
    ) -> Path:
        """
        Export a portable bundle containing all prepared data.

        The bundle includes genomes, BLAST databases, taxid mappings,
        taxonomy cache, watchlists, container artefacts (per
        ``containerization``), and a manifest with checksums. The
        Kraken2 database is excluded (transferred separately).

        Args:
            output_path: Path for the output tar.gz file.
            config: Current application configuration.
            nanometa_home: Path to ~/.nanometa directory.
            pre_warm_conda_envs: If True (and ``containerization`` is
                ``"conda"`` or ``None``), run nanometanf in stub mode
                under ``-profile conda`` so Nextflow resolves and creates
                every per-process env. The populated cache directory is
                then included in the bundle. Adds roughly 30 minutes and
                ~5 GB to the build. Ignored when ``containerization`` is
                ``"docker"`` or ``"singularity"`` (those modes ship
                pre-pulled images instead of conda envs).
            pipeline_path: Optional explicit path to the nanometanf
                checkout. Required when ``pre_warm_conda_envs`` is True
                or when ``containerization`` is ``"docker"`` /
                ``"singularity"`` (the inventory walker needs the
                ``modules/`` tree). Must contain ``main.nf``.
            containerization: Offline-deployment engine to target.
                ``"conda"`` (default when None) ships a pre-warmed
                conda cache; the field machine must match the build
                machine's OS+arch. ``"docker"`` runs ``docker pull`` +
                ``docker save`` per unique module image into
                ``pipeline_containers/`` and switches the bundle's
                ``pipeline_profile`` to ``docker``; the field machine
                runs unchanged on macOS / Windows / Linux with Docker
                installed. ``"singularity"`` runs ``apptainer pull``
                into the same staging dir as ``.sif`` files; field
                machine must be Linux with Apptainer installed.

        Returns:
            Path to the created bundle file.
        """
        # Default to conda when caller did not specify; preserves
        # backward compatibility with the pre-Wave-7 pre_warm_conda_envs
        # bool-only API.
        if containerization is None:
            containerization = "conda"
        if containerization not in SUPPORTED_CONTAINERIZATION_MODES:
            raise ValueError(
                f"containerization must be one of "
                f"{SUPPORTED_CONTAINERIZATION_MODES}; "
                f"got {containerization!r}"
            )
        if nanometa_home is None:
            nanometa_home = os.path.expanduser("~/.nanometa")
        home = Path(nanometa_home)
        output = Path(output_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            staging = Path(tmpdir) / "bundle"
            staging.mkdir()

            manifest = {
                "version": "1.1",
                "created": datetime.now().isoformat(),
                "creation_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "creator": getpass.getuser(),
                "nanometa_home": str(home),
                "checksums": {},
                "tool_versions": self._collect_tool_versions(),
                "container_runtime": self._detect_container_runtime(),
                "build_platform": {
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                },
            }

            # Record DB hash for compatibility check on import
            db_path = config.get("kraken_db", "")
            if db_path:
                from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
                manifest["db_hash"] = get_database_hash(db_path)

            # Copy directories
            dirs_to_copy = ["genomes", "blast", "mappings", "cache"]
            for dirname in dirs_to_copy:
                src = home / dirname
                if src.exists():
                    dst = staging / dirname
                    shutil.copytree(src, dst)
                    for f in dst.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(staging)
                            manifest["checksums"][str(rel)] = _file_md5(f)

            # Copy watchlists (include actual YAML files, not just references)
            watchlist_dir = home / "watchlists"
            if watchlist_dir.exists():
                shutil.copytree(watchlist_dir, staging / "watchlists")
                for f in (staging / "watchlists").rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(staging)
                        manifest["checksums"][str(rel)] = _file_md5(f)

            # Also include built-in watchlists from the package
            self._copy_builtin_watchlists(staging / "watchlists")

            # Copy containers if available
            containers_dir = home / "containers"
            if containers_dir.exists() and any(containers_dir.iterdir()):
                shutil.copytree(containers_dir, staging / "containers")
                for f in (staging / "containers").rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(staging)
                        manifest["checksums"][str(rel)] = _file_md5(f)

            # Export taxonomy snapshot
            try:
                from nanometa_live.core.utils.offline_cache import OfflineTaxonomyCache
                cache = OfflineTaxonomyCache()
                snapshot_path = staging / "cache" / "taxonomy_snapshot.json"
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                exported = cache.export_snapshot(str(snapshot_path))
                if exported > 0:
                    rel = snapshot_path.relative_to(staging)
                    manifest["checksums"][str(rel)] = _file_md5(snapshot_path)
                    logger.info(f"Exported {exported} taxonomy cache entries to bundle")
            except (ImportError, AttributeError, OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not export taxonomy snapshot: {e}")

            # Template genome_metadata.json paths
            meta_src = home / "genome_metadata.json"
            if meta_src.exists():
                meta_dst = staging / "genome_metadata.json"
                _template_paths(meta_src, meta_dst, str(home), _HOME_PLACEHOLDER)
                manifest["checksums"]["genome_metadata.json"] = _file_md5(meta_dst)

            # Copy per-entry watchlist toggle state so the field machine
            # restores the operator's enable/disable selections instead of
            # falling back to defaults. Older bundles may lack this file.
            toggle_src = home / "watchlist_toggle_state.yaml"
            if toggle_src.exists():
                toggle_dst = staging / "watchlist_toggle_state.yaml"
                shutil.copy2(toggle_src, toggle_dst)
                manifest["checksums"]["watchlist_toggle_state.yaml"] = _file_md5(
                    toggle_dst
                )

            # Bundle the pipeline source checkout so the field machine does
            # not depend on the build-machine's absolute path.
            pipeline_source_meta = self._bundle_pipeline_source(
                staging=staging,
                config=config,
                pipeline_path=pipeline_path,
            )
            manifest["pipeline_source"] = pipeline_source_meta

            # Bundle the Nextflow plugin cache so registry probes do not
            # fire on a network-restricted field machine.
            nxf_plugins_meta = self._bundle_nextflow_plugins(
                staging=staging,
                config=config,
            )
            manifest["nextflow_plugins"] = nxf_plugins_meta

            # Save config (with kraken_db as placeholder and relative
            # pipeline_source when the source was bundled). The
            # ``pipeline_profile`` is rewritten to match the chosen
            # containerization engine so the field launch picks up the
            # right Nextflow profile without operator intervention.
            from nanometa_live.core.config.config_loader import ConfigLoader
            bundle_config = dict(config)
            bundle_config["kraken_db"] = "${KRAKEN_DB}"
            if pipeline_source_meta.get("bundled"):
                bundle_config["pipeline_source"] = f"./{_BUNDLED_PIPELINE_DIRNAME}"
            if nxf_plugins_meta.get("bundled"):
                bundle_config["nxf_plugins_dir"] = f"./{_BUNDLED_NXF_PLUGINS_DIRNAME}"
            bundle_config["pipeline_profile"] = containerization
            bundle_loader = ConfigLoader(str(staging))
            bundle_loader.save_config(bundle_config, "config.yaml")

            # Optionally pre-warm Nextflow's per-process conda envs.
            # Failures fall back to the manual workaround so existing
            # flows are never blocked by a network or channel hiccup.
            pre_warm_result: Dict[str, Any] = {
                "attempted": False,
                "success": False,
                "scenarios": [],
                "env_count": 0,
                "warnings": [],
            }
            # Conda pre-warm only runs when conda is the chosen engine.
            # Docker / Singularity bundles ship pre-pulled images
            # instead, so re-running the conda solver would just waste
            # build time + 5 GB of disk for an unused artefact.
            if containerization == "conda" and pre_warm_conda_envs:
                pre_warm_result = self._pre_warm_conda_envs(
                    staging=staging,
                    config=config,
                    pipeline_path=pipeline_path,
                )
                if pre_warm_result["success"]:
                    cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
                    for f in cache_root.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(staging)
                            manifest["checksums"][str(rel)] = _file_md5(f)
                    # Embed the operator activation script next to the
                    # cache so the imported bundle is self-contained.
                    script_path = staging / _ACTIVATE_SCRIPT_FILENAME
                    script_path.write_text(
                        _ACTIVATE_SCRIPT_TEMPLATE.format(
                            cache_dirname=_BUNDLED_CONDA_CACHE_DIRNAME,
                        )
                    )
                    script_path.chmod(0o755)
                    manifest["checksums"][_ACTIVATE_SCRIPT_FILENAME] = _file_md5(
                        script_path
                    )
            manifest["pre_warm_conda_envs"] = pre_warm_result

            # Docker / Singularity image pull. Both engines walk the
            # pipeline source's ``modules/`` tree, dedupe references,
            # and pull each unique image into ``pipeline_containers/``.
            # The field machine loads them with ``docker load`` or runs
            # them directly with ``apptainer run``. See W7-B in
            # docs/plan-2026-04-28-throughput-fixes.md.
            container_pull_result: Dict[str, Any] = {
                "attempted": False,
                "engine": containerization,
                "image_count": 0,
                "warnings": [],
            }
            if containerization in ("docker", "singularity"):
                container_pull_result = self._pull_pipeline_containers(
                    engine=containerization,
                    staging=staging,
                    config=config,
                    pipeline_path=pipeline_path,
                )
                # Checksum every pulled artefact so the import side can
                # detect tampering or a partial transfer.
                images_dir = staging / _BUNDLED_PIPELINE_CONTAINERS_DIRNAME
                if images_dir.exists():
                    for f in images_dir.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(staging)
                            manifest["checksums"][str(rel)] = _file_md5(f)
            manifest["containerization"] = {
                "engine": containerization,
                "pull_result": container_pull_result,
            }

            # Generate README. The conda-cache section depends on
            # whether the pre-warm step actually populated the cache.
            if pre_warm_result.get("success"):
                scenario_summary = "\n".join(
                    f"   - {name}" for name in pre_warm_result["scenarios"]
                )
                conda_cache_section = _README_CONDA_CACHE_AUTO.format(
                    conda_cache_dirname=_BUNDLED_CONDA_CACHE_DIRNAME,
                    scenario_summary=scenario_summary,
                )
            else:
                conda_cache_section = _README_CONDA_CACHE_MANUAL

            readme_content = _README_TEMPLATE.format(
                creation_date=manifest["creation_date"],
                creator=manifest["creator"],
                version=manifest["version"],
                container_runtime=manifest["container_runtime"] or "none cached",
                conda_cache_section=conda_cache_section,
            )
            readme_path = staging / "README_FIELD.md"
            readme_path.write_text(readme_content)

            # Save manifest
            with open(staging / "manifest.json", "w") as f:
                json.dump(manifest, f, indent=2)

            # Drop the staging-only ``_pre_warm`` working directory
            # (dummy samplesheets, scratch ``work/``) before tarring.
            scratch = staging / "_pre_warm"
            if scratch.exists():
                shutil.rmtree(scratch, ignore_errors=True)

            # Create tar.gz
            with tarfile.open(str(output), "w:gz") as tar:
                for item in staging.iterdir():
                    tar.add(str(item), arcname=item.name)

        logger.info(f"Bundle exported to {output}")
        return output

    def import_bundle(
        self,
        bundle_path: str,
        kraken_db_path: str,
        nanometa_home: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Import a bundle and set up for offline operation.

        Extracts bundle contents to nanometa_home, rebases templated
        paths, verifies checksums, imports taxonomy snapshot, and
        auto-enables offline mode.

        Args:
            bundle_path: Path to the bundle tar.gz.
            kraken_db_path: Path to the Kraken2 database on this machine.
            nanometa_home: Target ~/.nanometa directory.
            force: If True, continue import despite checksum mismatches.

        Returns:
            Dict with import results (success, warnings, manifest).
        """
        if nanometa_home is None:
            nanometa_home = os.path.expanduser("~/.nanometa")
        home = Path(nanometa_home)
        home.mkdir(parents=True, exist_ok=True)

        result = {"success": True, "warnings": [], "manifest": {}}

        # Validate bundle file
        bundle = Path(bundle_path)
        if not bundle.exists():
            result["success"] = False
            result["warnings"].append(f"Bundle file not found: {bundle_path}")
            return result

        if not tarfile.is_tarfile(str(bundle)):
            result["success"] = False
            result["warnings"].append("File is not a valid tar archive")
            return result

        with tempfile.TemporaryDirectory() as tmpdir:
            # Extract bundle
            with tarfile.open(bundle_path, "r:gz") as tar:
                tar.extractall(path=tmpdir, filter='data')

            tmp = Path(tmpdir)

            # Load and validate manifest
            manifest_path = tmp / "manifest.json"
            if not manifest_path.exists():
                result["success"] = False
                result["warnings"].append(
                    "No manifest.json found in bundle. "
                    "This may not be a valid Nanometa Live bundle."
                )
                return result

            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
                result["manifest"] = manifest
            except (json.JSONDecodeError, IOError) as e:
                result["success"] = False
                result["warnings"].append(f"Corrupted manifest.json: {e}")
                return result

            # Validate checksums before extracting to home
            checksums = manifest.get("checksums", {})
            mismatches = []
            for rel_path, expected_md5 in checksums.items():
                full_path = tmp / rel_path
                if full_path.exists():
                    actual = _file_md5(full_path)
                    if actual != expected_md5:
                        mismatches.append(rel_path)
                else:
                    mismatches.append(f"{rel_path} (missing)")

            if mismatches:
                for f_path in mismatches:
                    logger.warning(f"Checksum mismatch: {f_path}")
                mismatch_msg = (
                    f"{len(mismatches)} file(s) failed checksum verification: "
                    f"{', '.join(mismatches[:5])}"
                    + ("..." if len(mismatches) > 5 else "")
                )
                if not force:
                    result["success"] = False
                    result["warnings"].append(
                        f"{mismatch_msg}. Import aborted. "
                        "Use force=True to import despite mismatches."
                    )
                    return result
                result["warnings"].append(
                    f"{mismatch_msg}. Continuing anyway (force=True)."
                )

            # Verify DB hash compatibility
            if kraken_db_path and manifest.get("db_hash"):
                from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
                local_hash = get_database_hash(kraken_db_path)
                if local_hash != manifest["db_hash"]:
                    result["warnings"].append(
                        f"Database hash mismatch: bundle={manifest['db_hash']}, "
                        f"local={local_hash}. Mappings may need regeneration."
                    )

            # Validate tool versions against local installations
            bundle_versions = manifest.get("tool_versions", {})
            if bundle_versions:
                local_versions = self._collect_tool_versions()
                version_warnings = _check_version_compatibility(
                    bundle_versions, local_versions
                )
                result["warnings"].extend(version_warnings)

            # Warn when the bundle was built on a different OS or CPU
            # architecture. Conda envs and compiled binaries are not
            # portable across platform boundaries.
            build_plat = manifest.get("build_platform", {})
            if build_plat:
                local_system = platform.system()
                local_machine = platform.machine()
                bundle_system = build_plat.get("system", "")
                bundle_machine = build_plat.get("machine", "")
                if (bundle_system and bundle_machine) and (
                    local_system != bundle_system or local_machine != bundle_machine
                ):
                    msg = (
                        f"Bundle was built on {bundle_system}/{bundle_machine} "
                        f"but field machine is {local_system}/{local_machine}. "
                        "Pre-warmed conda envs and bundled binaries will likely "
                        "not work. Plan to rebuild conda envs from "
                        "environment.yml on the field machine."
                    )
                    logger.warning(msg)
                    result["warnings"].append(msg)

            # Copy directories to home (handle partial imports gracefully)
            for dirname in [
                "genomes", "blast", "mappings", "cache",
                "watchlists", "containers",
                _BUNDLED_CONDA_CACHE_DIRNAME,
                _BUNDLED_PIPELINE_DIRNAME,
                _BUNDLED_NXF_PLUGINS_DIRNAME,
            ]:
                src = tmp / dirname
                if src.exists():
                    dst = home / dirname
                    if dst.exists():
                        # Merge: copy new files, skip existing
                        for src_file in src.rglob("*"):
                            if src_file.is_file():
                                rel = src_file.relative_to(src)
                                dst_file = dst / rel
                                dst_file.parent.mkdir(parents=True, exist_ok=True)
                                if not dst_file.exists():
                                    shutil.copy2(src_file, dst_file)
                                else:
                                    # Overwrite if checksums differ
                                    if _file_md5(src_file) != _file_md5(dst_file):
                                        shutil.copy2(src_file, dst_file)
                    else:
                        shutil.copytree(src, dst)

            # Rebase genome_metadata.json
            meta_src = tmp / "genome_metadata.json"
            if meta_src.exists():
                meta_dst = home / "genome_metadata.json"
                _template_paths(
                    meta_src, meta_dst,
                    _HOME_PLACEHOLDER, str(home)
                )

            # Copy bundle config.yaml to home so the block below can
            # update offline_mode and rebase paths. Without this step
            # the file would only exist at home if a prior import had
            # already placed it there.
            config_src = tmp / "config.yaml"
            if config_src.exists():
                shutil.copy2(config_src, home / "config.yaml")

            # Restore per-entry watchlist toggle state if the bundle
            # carries one. Older bundles predate this file, so absence
            # is silently tolerated.
            toggle_src = tmp / "watchlist_toggle_state.yaml"
            if toggle_src.exists():
                toggle_dst = home / "watchlist_toggle_state.yaml"
                shutil.copy2(toggle_src, toggle_dst)
                logger.info(
                    "Imported watchlist_toggle_state.yaml from bundle"
                )

            # Import taxonomy snapshot
            taxonomy_snapshot = tmp / "cache" / "taxonomy_snapshot.json"
            if not taxonomy_snapshot.exists():
                # Also check if it was extracted into the cache dir
                taxonomy_snapshot = home / "cache" / "taxonomy_snapshot.json"

            if taxonomy_snapshot.exists():
                try:
                    from nanometa_live.core.utils.offline_cache import OfflineTaxonomyCache
                    cache = OfflineTaxonomyCache()
                    loaded = cache.load_snapshot(str(taxonomy_snapshot))
                    logger.info(f"Loaded {loaded} taxonomy entries from bundle snapshot")
                except (ImportError, AttributeError, OSError, json.JSONDecodeError) as e:
                    result["warnings"].append(f"Failed to load taxonomy snapshot: {e}")

            # Load container images if present
            containers_dir = home / "containers"
            if containers_dir.exists() and any(containers_dir.iterdir()):
                loaded_count = self._load_container_images(containers_dir)
                if loaded_count > 0:
                    logger.info(f"Loaded {loaded_count} container images from bundle")

            # If the bundle ships a pre-warmed Nextflow conda cache,
            # surface its restored location so the operator can point
            # NXF_CONDA_CACHEDIR at it.
            restored_conda_cache = home / _BUNDLED_CONDA_CACHE_DIRNAME
            if restored_conda_cache.is_dir() and any(restored_conda_cache.iterdir()):
                result["conda_cache_path"] = str(restored_conda_cache)
                logger.info(
                    "Restored pre-warmed Nextflow conda cache to "
                    f"{restored_conda_cache}. Set "
                    f"NXF_CONDA_CACHEDIR={restored_conda_cache} before "
                    "launching Nanometa Live."
                )

            # Restore the operator activation script next to the cache
            # so the operator can ``source ./activate_offline_envs.sh``
            # without hunting for the build-host repo.
            script_src = tmp / _ACTIVATE_SCRIPT_FILENAME
            if script_src.exists():
                script_dst = home / _ACTIVATE_SCRIPT_FILENAME
                shutil.copy2(script_src, script_dst)
                script_dst.chmod(0o755)
                result["activation_script"] = str(script_dst)
                logger.info(
                    f"Wrote activation helper to {script_dst}; run "
                    f"`source {script_dst}` before launching Nanometa Live."
                )

            # Auto-set offline_mode in config
            config_path = home / "config.yaml"
            if config_path.exists():
                try:
                    from nanometa_live.core.config.config_loader import ConfigLoader
                    import_loader = ConfigLoader(str(home))
                    cfg = import_loader.load_config(str(config_path))
                    cfg["offline_mode"] = True
                    if kraken_db_path:
                        cfg["kraken_db"] = kraken_db_path
                    if "conda_cache_path" in result:
                        cfg["nxf_conda_cachedir"] = result["conda_cache_path"]
                    # Rebase pipeline_source from relative bundle path to
                    # absolute path on this machine.
                    ps = cfg.get("pipeline_source", "")
                    if isinstance(ps, str) and ps == f"./{_BUNDLED_PIPELINE_DIRNAME}":
                        abs_pipeline = home / _BUNDLED_PIPELINE_DIRNAME
                        if abs_pipeline.is_dir():
                            cfg["pipeline_source"] = str(abs_pipeline)
                            result["pipeline_source_path"] = str(abs_pipeline)
                            logger.info(
                                f"Rebased pipeline_source to {abs_pipeline}"
                            )
                    # Rebase nxf_plugins_dir similarly.
                    npd = cfg.get("nxf_plugins_dir", "")
                    if isinstance(npd, str) and npd == f"./{_BUNDLED_NXF_PLUGINS_DIRNAME}":
                        abs_plugins = home / _BUNDLED_NXF_PLUGINS_DIRNAME
                        if abs_plugins.is_dir():
                            cfg["nxf_plugins_dir"] = str(abs_plugins)
                            result["nxf_plugins_dir"] = str(abs_plugins)
                            logger.info(
                                f"Rebased nxf_plugins_dir to {abs_plugins}"
                            )
                    import_loader.save_config(cfg, "config.yaml")
                    logger.info("Set offline_mode=True in config")
                except (ImportError, AttributeError, OSError, ValueError) as e:
                    result["warnings"].append(f"Could not update config: {e}")

        logger.info(f"Bundle imported to {home}")
        return result

    def _pull_pipeline_containers(
        self,
        engine: str,
        staging: Path,
        config: Dict[str, Any],
        pipeline_path: Optional[str],
    ) -> Dict[str, Any]:
        """Pull every unique container image referenced by the pipeline.

        For ``docker``: ``docker pull <ref>`` followed by
        ``docker save -o <name>.tar <ref>`` so the field machine can
        ``docker load`` without network access.
        For ``singularity``: ``apptainer pull <name>.sif <ref>`` (with
        a ``docker://`` prefix added automatically when the inventory
        only carries the Docker reference; Apptainer pulls OCI
        registries directly).

        Args:
            engine: ``"docker"`` or ``"singularity"``.
            staging: Bundle staging root.
            config: App config (used to resolve pipeline source if
                pipeline_path is not provided).
            pipeline_path: Explicit local path to the nanometanf
                checkout. Required -- the inventory walker needs
                ``modules/`` to be present.

        Returns:
            Status dict with ``attempted``, ``engine``, ``image_count``,
            ``pulled`` (list of refs), and ``warnings``.
        """
        result: Dict[str, Any] = {
            "attempted": True,
            "engine": engine,
            "image_count": 0,
            "pulled": [],
            "warnings": [],
        }

        if engine not in ("docker", "singularity"):
            result["warnings"].append(
                f"_pull_pipeline_containers: unsupported engine {engine!r}"
            )
            return result

        # Resolve a local pipeline checkout. Without modules/ on disk
        # we cannot inventory the container references.
        resolved = self._resolve_local_pipeline_path(config, pipeline_path)
        if resolved is None:
            result["warnings"].append(
                "No local pipeline_source available to inventory; "
                f"{engine} container pull skipped"
            )
            return result

        # Verify the engine's CLI is reachable on the build machine
        # before doing any inventory work.
        cli = "docker" if engine == "docker" else "apptainer"
        if shutil.which(cli) is None and engine == "singularity":
            # Apptainer was renamed from Singularity in 2021; some
            # distributions still ship the old binary name.
            cli = "singularity" if shutil.which("singularity") else "apptainer"
        if shutil.which(cli) is None:
            result["warnings"].append(
                f"{cli} not found on PATH; cannot pull {engine} images. "
                f"Install {engine} on the build machine and retry."
            )
            return result

        from nanometa_live.core.workflow.container_inventory import (
            inventory_pipeline,
            unique_container_refs,
        )

        entries = inventory_pipeline(resolved)
        if not entries:
            result["warnings"].append(
                f"Inventory of {resolved} returned no modules"
            )
            return result

        # Singularity can pull from Docker references directly via the
        # ``docker://`` URL scheme, so we fall back to Docker refs when
        # a module has no depot.galaxyproject.org Singularity URL. This
        # matches the W6-A audit's finding that ~30% of nf-core modules
        # ship only a community.wave.seqera.io Docker tag.
        if engine == "docker":
            refs = unique_container_refs(entries, "docker")
        else:
            sing_refs = unique_container_refs(entries, "singularity")
            doc_refs = unique_container_refs(entries, "docker")
            sing_set = set(sing_refs)
            covered_docker_set = set()
            # Build a Docker -> Singularity-equivalent mapping by
            # checking which entries have BOTH; if a docker-only entry
            # exists, mark its docker_ref for fallback pull.
            for e in entries:
                if e.singularity_url:
                    sing_set.add(e.singularity_url)
                elif e.docker_ref:
                    covered_docker_set.add(e.docker_ref)
            refs = sorted(sing_set) + sorted(
                f"docker://{d}" for d in covered_docker_set
            )

        if not refs:
            result["warnings"].append(
                f"No {engine} references found in pipeline inventory"
            )
            return result

        images_dir = staging / _BUNDLED_PIPELINE_CONTAINERS_DIRNAME
        images_dir.mkdir(parents=True, exist_ok=True)

        for ref in refs:
            try:
                if engine == "docker":
                    self._pull_one_docker_image(ref, images_dir)
                else:
                    self._pull_one_singularity_image(ref, images_dir, cli)
                result["pulled"].append(ref)
                result["image_count"] += 1
            except subprocess.SubprocessError as exc:
                result["warnings"].append(
                    f"Failed to pull {ref}: {exc}"
                )
                logger.warning(f"{engine} pull failed for {ref}: {exc}")
            except OSError as exc:
                result["warnings"].append(f"OSError pulling {ref}: {exc}")
                logger.warning(f"{engine} pull OSError for {ref}: {exc}")

        return result

    @staticmethod
    def _ref_to_safe_filename(ref: str) -> str:
        """Convert a container reference to a filename-safe slug."""
        # Strip docker:// prefix for filename purposes; keep tag info.
        if ref.startswith("docker://"):
            ref = ref[len("docker://"):]
        if ref.startswith("https://"):
            ref = ref[len("https://"):]
        return re.sub(r"[^a-zA-Z0-9._-]", "_", ref)[:200]

    def _pull_one_docker_image(self, ref: str, target_dir: Path) -> None:
        """``docker pull`` then ``docker save`` one image to a tar."""
        subprocess.run(
            ["docker", "pull", ref],
            check=True,
            timeout=_CONTAINER_PULL_TIMEOUT_S,
            capture_output=True,
        )
        out = target_dir / f"{self._ref_to_safe_filename(ref)}.tar"
        subprocess.run(
            ["docker", "save", "-o", str(out), ref],
            check=True,
            timeout=_CONTAINER_PULL_TIMEOUT_S,
            capture_output=True,
        )

    def _pull_one_singularity_image(
        self, ref: str, target_dir: Path, cli: str
    ) -> None:
        """``apptainer pull`` (or ``singularity pull``) one image to .sif."""
        out = target_dir / f"{self._ref_to_safe_filename(ref)}.sif"
        subprocess.run(
            [cli, "pull", "--force", str(out), ref],
            check=True,
            timeout=_CONTAINER_PULL_TIMEOUT_S,
            capture_output=True,
        )

    def _resolve_local_pipeline_path(
        self,
        config: Dict[str, Any],
        pipeline_path: Optional[str],
    ) -> Optional[Path]:
        """Best-effort resolution of a local nanometanf checkout."""
        if pipeline_path:
            p = Path(pipeline_path)
            if p.is_dir() and (p / "main.nf").exists():
                return p
        ps = config.get("pipeline_source", "") if config else ""
        if isinstance(ps, str) and not ps.startswith(
            ("remote:", "https://", "git@")
        ):
            p = Path(ps)
            if p.is_dir() and (p / "main.nf").exists():
                return p
        return None

    def _pre_warm_conda_envs(
        self,
        staging: Path,
        config: Dict[str, Any],
        pipeline_path: Optional[str],
    ) -> Dict[str, Any]:
        """
        Populate ``staging/conda_cache`` with every per-process env
        nanometanf needs.

        Strategy: run ``nextflow run <pipeline> -stub -profile conda``
        once per scenario. Stub mode skips real work but still triggers
        Nextflow's ``CondaCache`` resolution for each process. The
        scenarios in ``_PRE_WARM_SCENARIOS`` together exercise every
        ``environment.yml`` shipped with the pipeline.

        Returns a dict describing the outcome that gets written into
        ``manifest.json`` so the field machine can verify which envs
        are pinned in the bundle.

        On failure (network outage, missing nextflow binary, missing
        pipeline checkout) the function logs a warning and returns
        ``success=False`` so the caller falls back to the manual
        workaround documented in the README.
        """
        outcome: Dict[str, Any] = {
            "attempted": True,
            "success": False,
            "scenarios": [],
            "env_count": 0,
            "warnings": [],
        }

        if not shutil.which("nextflow"):
            outcome["warnings"].append(
                "nextflow binary not found on PATH; skipping pre-warm."
            )
            logger.warning(outcome["warnings"][-1])
            return outcome

        resolved_pipeline = self._resolve_pipeline_checkout(
            config=config, override=pipeline_path
        )
        if resolved_pipeline is None:
            outcome["warnings"].append(
                "Could not resolve a local nanometanf checkout for "
                "pre-warm. Pass pipeline_path or set pipeline_source "
                "to a local directory."
            )
            logger.warning(outcome["warnings"][-1])
            return outcome

        cache_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
        cache_root.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["NXF_CONDA_CACHEDIR"] = str(cache_root)
        # Discourage Nextflow from auto-updating itself mid-run on the
        # build machine; that would defeat reproducibility of the
        # pinned envs we are about to bake into the bundle.
        env.setdefault("NXF_OFFLINE", "false")

        for scenario in _PRE_WARM_SCENARIOS:
            scenario_ok, scenario_msg = self._run_pre_warm_scenario(
                scenario=scenario,
                pipeline_dir=resolved_pipeline,
                staging=staging,
                env=env,
            )
            if scenario_ok:
                outcome["scenarios"].append(scenario["name"])
            else:
                outcome["warnings"].append(
                    f"Scenario '{scenario['name']}' pre-warm failed: "
                    f"{scenario_msg}"
                )
                logger.warning(outcome["warnings"][-1])

        env_dirs = [
            d for d in cache_root.iterdir()
            if d.is_dir() and d.name.startswith("env-")
        ]
        outcome["env_count"] = len(env_dirs)
        outcome["success"] = bool(outcome["scenarios"]) and outcome["env_count"] > 0

        if not outcome["success"]:
            # Drop the half-populated cache directory so the bundle
            # does not silently ship a broken cache.
            shutil.rmtree(cache_root, ignore_errors=True)

        return outcome

    @staticmethod
    def _resolve_pipeline_checkout(
        config: Dict[str, Any],
        override: Optional[str],
    ) -> Optional[Path]:
        """
        Locate a usable on-disk nanometanf checkout for the pre-warm
        step. Search order:

        1. Explicit ``override`` argument.
        2. ``config['pipeline_source']`` if it points to an existing
           directory containing ``main.nf``.
        3. ``~/.nextflow/assets/foi-bioinformatics/nanometanf`` (the
           default location Nextflow uses after a remote pull).

        Returns the resolved Path or None if no candidate qualifies.
        """
        candidates: List[Path] = []
        if override:
            candidates.append(Path(override).expanduser())

        source = config.get("pipeline_source")
        if isinstance(source, str) and source:
            stripped = source.split(":", 1)[1] if source.startswith("local:") else source
            if not stripped.startswith("remote:"):
                p = Path(stripped).expanduser()
                if p.is_dir():
                    candidates.append(p)

        candidates.append(
            Path("~/.nextflow/assets/foi-bioinformatics/nanometanf").expanduser()
        )

        for cand in candidates:
            if cand.is_dir() and (cand / "main.nf").exists():
                return cand
        return None

    def _bundle_pipeline_source(
        self,
        staging: Path,
        config: Dict[str, Any],
        pipeline_path: Optional[str],
    ) -> Dict[str, Any]:
        """Copy the pipeline source checkout into the bundle staging area.

        Resolves the source using the same strategy as
        ``_resolve_pipeline_checkout``. Skips large or build-specific
        artifacts to keep the bundle size manageable.

        Returns a metadata dict for the manifest:
        ``{bundled: bool, path: str | None}``.
        """
        meta: Dict[str, Any] = {"bundled": False, "path": None}

        pipeline_source_cfg = config.get("pipeline_source", "")
        if isinstance(pipeline_source_cfg, str) and pipeline_source_cfg.startswith("remote:"):
            logger.warning(
                "pipeline_source is '%s' (remote reference); no local "
                "checkout to bundle. The field machine will need network "
                "access or a pre-existing Nextflow assets cache to run "
                "the pipeline.",
                pipeline_source_cfg,
            )
            return meta

        resolved = self._resolve_pipeline_checkout(
            config=config, override=pipeline_path
        )
        if resolved is None:
            logger.info(
                "No local pipeline checkout found for bundling; "
                "pipeline_source will not be included in the bundle."
            )
            return meta

        dst = staging / _BUNDLED_PIPELINE_DIRNAME
        try:
            shutil.copytree(
                str(resolved),
                str(dst),
                ignore=shutil.ignore_patterns(*_PIPELINE_IGNORE_PATTERNS),
            )
            meta["bundled"] = True
            meta["path"] = f"./{_BUNDLED_PIPELINE_DIRNAME}"
            logger.info(
                "Bundled pipeline source from %s as %s",
                resolved,
                _BUNDLED_PIPELINE_DIRNAME,
            )
        except OSError as exc:
            logger.warning(
                "Could not bundle pipeline source from %s: %s",
                resolved,
                exc,
            )

        return meta

    def _bundle_nextflow_plugins(
        self,
        staging: Path,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Copy referenced Nextflow plugins into the bundle staging area.

        Copies ``~/.nextflow/plugins/`` entries that are referenced by
        the pipeline's ``nextflow.config`` (``id 'nf-schema@...'`` etc.)
        plus any cached plugin whose directory name starts with a
        recognised plugin prefix (nf-schema, nf-validation, nf-wave).

        With the plugins present on the field machine, setting
        ``NXF_OFFLINE=true`` (the literal string, lowercase) suppresses
        Nextflow's plugin registry probe and self-update curl, and
        ``NXF_PLUGINS_PATH`` points the JVM at the restored directory.
        Note: ``NXF_OFFLINE=1`` does not work -- Nextflow's bash launcher
        and JVM both check for string equality with ``true``. The
        verified offline launch env on Nextflow 25.10.4 is::

            NXF_OFFLINE=true
            NXF_DISABLE_CHECK_LATEST=true
            NXF_PLUGINS_PATH=<bundled-plugins-dir>

        Both env vars are injected automatically by ``NextflowManager``
        when ``config['offline_mode']`` is True.

        Returns a metadata dict for the manifest:
        ``{bundled: bool, plugin_count: int}``.
        """
        meta: Dict[str, Any] = {"bundled": False, "plugin_count": 0}

        plugins_home = Path.home() / ".nextflow" / "plugins"
        if not plugins_home.is_dir():
            logger.info(
                "~/.nextflow/plugins/ not found; skipping plugin bundling."
            )
            return meta

        # Determine which plugin names the pipeline references.
        referenced: List[str] = []
        pipeline_checkout = self._resolve_pipeline_checkout(
            config=config, override=None
        )
        if pipeline_checkout is not None:
            nxf_config = pipeline_checkout / "nextflow.config"
            if nxf_config.is_file():
                try:
                    cfg_text = nxf_config.read_text(errors="replace")
                    # Match: id 'nf-schema@2.4.2'
                    for m in re.finditer(r"id\s+['\"]([^'\"@]+)@[^'\"]+['\"]", cfg_text):
                        referenced.append(m.group(1))
                except OSError as exc:
                    logger.warning("Could not read nextflow.config: %s", exc)

        # Always include the common Nextflow helper plugins.
        _PLUGIN_PREFIXES = ("nf-schema", "nf-validation", "nf-wave", "nf-console")

        def _should_include(plugin_dir: Path) -> bool:
            name = plugin_dir.name  # e.g. nf-schema-2.4.2
            for prefix in _PLUGIN_PREFIXES:
                if name.startswith(prefix):
                    return True
            for ref in referenced:
                if name.startswith(ref):
                    return True
            return False

        dst_plugins = staging / _BUNDLED_NXF_PLUGINS_DIRNAME
        dst_plugins.mkdir(parents=True, exist_ok=True)
        count = 0
        for plugin_dir in sorted(plugins_home.iterdir()):
            if not plugin_dir.is_dir():
                continue
            if not _should_include(plugin_dir):
                continue
            dst = dst_plugins / plugin_dir.name
            if not dst.exists():
                try:
                    shutil.copytree(str(plugin_dir), str(dst))
                    count += 1
                except OSError as exc:
                    logger.warning(
                        "Could not copy plugin %s: %s", plugin_dir.name, exc
                    )

        if count > 0:
            meta["bundled"] = True
            meta["plugin_count"] = count
            logger.info(
                "Bundled %d Nextflow plugin(s) from %s", count, plugins_home
            )
        else:
            # Remove the empty directory so it is not tarred into the bundle.
            dst_plugins.rmdir()

        return meta

    @staticmethod
    def _run_pre_warm_scenario(
        scenario: Dict[str, Any],
        pipeline_dir: Path,
        staging: Path,
        env: Dict[str, str],
    ) -> tuple:
        """
        Run a single ``nextflow run -stub -profile conda`` invocation
        for one scenario. Returns ``(ok, message)``.
        """
        import subprocess

        scenario_dir = staging / "_pre_warm" / scenario["name"]
        scenario_dir.mkdir(parents=True, exist_ok=True)

        samplesheet = scenario_dir / "samplesheet.csv"
        fastq_stub = scenario_dir / "stub.fastq.gz"
        fastq_stub.write_bytes(b"")  # zero-byte placeholder is fine for stub mode
        samplesheet.write_text(
            "sample,fastq\n"
            f"stub_sample,{fastq_stub}\n"
        )

        scenario_params: Dict[str, Any] = dict(scenario.get("params", {}))

        # Validation scenarios trigger nanometanf's pathogen_genomes check
        # at pipeline startup. Stub mode still runs that check, so write a
        # minimal placeholder JSON if the scenario opts into validation
        # without supplying its own pathogen_genomes path.
        if (
            str(scenario_params.get("run_validation", "")).lower() == "true"
            and "pathogen_genomes" not in scenario_params
        ):
            placeholder = scenario_dir / "pathogen_genomes.json"
            placeholder.write_text(json.dumps({"pathogens": []}))
            scenario_params["pathogen_genomes"] = str(placeholder)

        cmd = [
            "nextflow", "run", str(pipeline_dir / "main.nf"),
            "-stub",
            "-profile", "conda",
            "-work-dir", str(scenario_dir / "work"),
            "--input", str(samplesheet),
            "--outdir", str(scenario_dir / "results"),
        ]
        for key, value in scenario_params.items():
            cmd += [f"--{key}", str(value)]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(scenario_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=1800,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return False, f"subprocess error: {exc}"

        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").splitlines()[-5:]
            return False, "; ".join(tail) or f"exit {result.returncode}"
        return True, "ok"

    def _collect_tool_versions(self) -> Dict[str, str]:
        """Collect versions of key tools for the manifest."""
        versions = {}

        # Nextflow: parse "version X.Y.Z build N" from ``nextflow -version``.
        versions["nextflow"] = _get_nextflow_version()

        # Kraken2
        versions["kraken2"] = _get_command_version("kraken2", ["--version"])

        # NCBI datasets
        versions["datasets"] = _get_command_version("datasets", ["--version"])

        # makeblastdb
        versions["makeblastdb"] = _get_command_version("makeblastdb", ["-version"])

        return versions

    def _detect_container_runtime(self) -> Optional[str]:
        """Detect which container runtime is available."""
        if shutil.which("singularity"):
            return "singularity"
        if shutil.which("apptainer"):
            return "apptainer"
        if shutil.which("docker"):
            return "docker"
        return None

    def _copy_builtin_watchlists(self, dst_dir: Path) -> None:
        """Copy built-in watchlist YAMLs to the bundle.

        Resolves the source directory via importlib.resources so the lookup
        works under both regular and editable installs. Editable installs
        produce a namespace package whose __file__ attribute is None, which
        breaks the legacy Path(wl_pkg.__file__).parent approach.
        """
        try:
            wl_path = _resolve_builtin_watchlist_dir()
            if wl_path is None or not wl_path.is_dir():
                logger.debug(
                    "Built-in watchlist directory not found; skipping copy."
                )
                return

            dst_dir.mkdir(parents=True, exist_ok=True)

            for yaml_file in wl_path.glob("*.yaml"):
                dst_file = dst_dir / yaml_file.name
                if not dst_file.exists():
                    shutil.copy2(yaml_file, dst_file)
        except (ImportError, AttributeError, OSError) as e:
            logger.debug(f"Could not copy built-in watchlists: {e}")

    def _load_container_images(self, containers_dir: Path) -> int:
        """Load container images from the bundle's containers directory."""
        import subprocess
        loaded = 0
        try:
            # Try Docker tar files
            for tar_file in containers_dir.glob("*.tar"):
                try:
                    subprocess.run(
                        ["docker", "load", "-i", str(tar_file)],
                        capture_output=True, check=True, timeout=300,
                    )
                    loaded += 1
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                        FileNotFoundError, PermissionError, OSError) as e:
                    logger.warning(f"Failed to load container image {tar_file.name}: {e}")

            # Singularity/Apptainer .sif files are used in-place, no loading needed
            sif_count = len(list(containers_dir.glob("*.sif")))
            if sif_count > 0:
                logger.info(f"Found {sif_count} Singularity/Apptainer images (used in-place)")
                loaded += sif_count

        except OSError as e:
            logger.warning(f"Error loading container images: {e}")

        return loaded


def _resolve_builtin_watchlist_dir() -> Optional[Path]:
    """Locate the built-in watchlist directory in a way that survives editable installs.

    Editable installs expose ``nanometa_live.core.config.data.watchlists`` as a
    namespace package whose ``__file__`` attribute is ``None``. The previous
    implementation called ``Path(pkg.__file__).parent`` and crashed with
    TypeError. The lookup now prefers ``importlib.resources.files`` and falls
    back to the package's ``__path__`` entries.
    """
    import importlib
    import importlib.resources as pkg_resources

    pkg_name = "nanometa_live.core.config.data.watchlists"

    try:
        ref = pkg_resources.files(pkg_name)
    except (ModuleNotFoundError, AttributeError, TypeError):
        ref = None

    if ref is not None:
        try:
            candidate = Path(str(ref))
            if candidate.is_dir():
                return candidate
        except (TypeError, OSError):
            pass

    try:
        wl_pkg = importlib.import_module(pkg_name)
    except ImportError:
        return None

    for raw_path in getattr(wl_pkg, "__path__", []) or []:
        candidate = Path(raw_path)
        if candidate.is_dir():
            return candidate

    file_attr = getattr(wl_pkg, "__file__", None)
    if file_attr:
        return Path(file_attr).parent

    return None


def _file_md5(path: Path) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _template_paths(src: Path, dst: Path, find: str, replace: str):
    """Read JSON file, replace path strings, write to destination."""
    with open(src) as f:
        content = f.read()
    content = content.replace(find, replace)
    with open(dst, "w") as f:
        f.write(content)


def _get_nextflow_version() -> str:
    """Return the Nextflow version string in 'X.Y.Z build N' form.

    ``nextflow -version`` prints a multi-line banner. The useful line
    matches ``version X.Y.Z build N``. Falls back to the first non-empty
    output line when the pattern is absent.
    """
    import subprocess

    if not shutil.which("nextflow"):
        return "not found"

    try:
        result = subprocess.run(
            ["nextflow", "-version"],
            capture_output=True, text=True, timeout=10,
        )
        output = (result.stdout + result.stderr).strip()
        # Look for the canonical version line in the banner.
        match = re.search(r"version\s+(\S+)\s+build\s+(\d+)", output)
        if match:
            return f"{match.group(1)} build {match.group(2)}"
        # Fallback: return the first non-empty, non-banner line.
        for line in output.split("\n"):
            stripped = line.strip()
            if stripped and not set(stripped).issubset({" ", "N", "E", "X", "T", "F", "L", "O", "W", "-"}):
                return stripped[:100]
        return "unknown"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, PermissionError, OSError):
        return "error"


def _get_command_version(command: str, args: List[str]) -> str:
    """Run a command to get its version string. Returns 'not found' on failure."""
    import subprocess

    if not shutil.which(command):
        return "not found"

    try:
        result = subprocess.run(
            [command] + args,
            capture_output=True, text=True, timeout=10,
        )
        output = (result.stdout + result.stderr).strip()
        # Extract version-like pattern from output
        for line in output.split("\n"):
            line = line.strip()
            if line:
                return line[:100]  # Truncate long output
        return "unknown"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, PermissionError, OSError):
        return "error"


def _extract_major_version(version_str: str) -> Optional[str]:
    """Extract the major version number from a version string.

    Handles common formats like '23.10.1', 'v2.1.0', 'BLAST 2.14.0+',
    'nextflow version 23.10.1.5891'.
    """
    match = re.search(r"(\d+)\.\d+", version_str)
    if match:
        return match.group(1)
    return None


# Tools that are only used during bundle preparation on the build machine.
# Their absence on the field machine is expected and is not a problem at
# runtime. Version-compatibility warnings for these tools are reported as
# informational rather than as a missing-tool warning.
_BUILD_ONLY_TOOLS = frozenset({"conda-pack", "datasets"})


def _check_version_compatibility(
    bundle_versions: Dict[str, str],
    local_versions: Dict[str, str],
) -> List[str]:
    """Compare bundle tool versions against local installations.

    Returns a list of warning strings for major version mismatches.
    Build-only tools (e.g. conda-pack, NCBI datasets) that are absent
    on the field machine produce an informational note instead of a
    missing-tool warning, since they are not used at runtime.
    """
    warnings = []
    for tool, bundle_ver in bundle_versions.items():
        local_ver = local_versions.get(tool, "not found")

        # Skip tools that are not found or had errors
        if bundle_ver in ("not found", "unknown", "error"):
            continue
        if local_ver in ("not found", "unknown", "error"):
            if tool in _BUILD_ONLY_TOOLS:
                warnings.append(
                    f"Note: build-only tool '{tool}' is not present "
                    "on this machine; this is expected for offline "
                    "deployments and is not a runtime requirement."
                )
            else:
                warnings.append(
                    f"Tool '{tool}' was {bundle_ver} in bundle but is "
                    f"{local_ver} locally."
                )
            continue

        bundle_major = _extract_major_version(bundle_ver)
        local_major = _extract_major_version(local_ver)

        if bundle_major and local_major and bundle_major != local_major:
            warnings.append(
                f"Major version mismatch for {tool}: "
                f"bundle={bundle_ver}, local={local_ver}. "
                "Results may differ."
            )
    return warnings
