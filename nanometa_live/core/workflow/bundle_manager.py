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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple


@dataclass
class ExportResult:
    """Outcome of ``BundleManager.export_bundle``.

    ``warnings`` mirrors the manifest's ``export_warnings`` -- the same
    list ``verify_bundle``/``import_bundle`` replay on the field machine.
    Callers MUST surface it: a bundle can be produced successfully while
    still being incomplete (skipped container pull, failed pre-warm),
    and a caller that only checks for an exception reports green over
    exactly the problems the export recorded (2026-08-27 audit).
    """

    path: Path
    warnings: List[str] = field(default_factory=list)
    manifest: Dict[str, Any] = field(default_factory=dict)

    def __fspath__(self) -> str:
        return str(self.path)


logger = logging.getLogger(__name__)

# Supported offline-deployment engines. The choice is made at bundle
# build time; the field machine consumes whatever artefacts the
# selected engine produced. See docs/plan-2026-04-28-throughput-fixes.md
# Wave 7 for the design rationale.
ContainerizationMode = Literal["conda", "docker", "singularity"]
SUPPORTED_CONTAINERIZATION_MODES = ("conda", "docker", "singularity")

# Placeholder token for absolute paths in exported metadata
_HOME_PLACEHOLDER = "${NANOMETA_HOME}"

# Placeholder the export writes for the Kraken2 DB path (the DB is moved
# separately, so the operator supplies its path at import time).
_KRAKEN_DB_PLACEHOLDER = "${KRAKEN_DB}"

# Minimum Nextflow the bundled pipeline requires (mirrors the nanometanf
# manifest floor ``nextflowVersion = '>=26.04.0'``). Recorded in the manifest
# at export and warned about on import when the field machine is older.
_NEXTFLOW_MIN_VERSION = "26.04.0"

# Recognised Nextflow plugin name prefixes. Used both when selecting plugins to
# bundle and when checking the restored plugins directory is non-empty on import.
_PLUGIN_PREFIXES = ("nf-schema", "nf-validation", "nf-wave", "nf-console")

# Where we stage pulled Docker tar archives and Singularity .sif files
# during build. This is distinct from the existing ``containers/``
# staging directory which holds operator-managed BLAST containers
# copied from ``~/.nanometa/containers``.
_BUNDLED_PIPELINE_CONTAINERS_DIRNAME = "pipeline_containers"

# Default container registry for refs that omit one. nanometanf sets
# `docker.registry = 'quay.io'` (nextflow.config), so a bare ref like
# `biocontainers/seqkit:2.9.0--h9ee0642_0` resolves to
# `quay.io/biocontainers/...` at runtime -- it does NOT exist on Docker Hub.
# A docker/singularity-mode export must apply the same default, or every
# bare biocontainers pull fails and the bundle ships an incomplete image set.
_DEFAULT_DOCKER_REGISTRY = "quay.io"

# Per-engine docker/apptainer command timeout in seconds. A 1 GB
# container image typically pulls in 30-90 s on a fast link; 600 s
# leaves headroom for slow connections without hanging an aborted
# build.
_CONTAINER_PULL_TIMEOUT_S = 600

# Architecture the bundled container images are built for. This is a property
# of the FIELD machine, not of the build machine: an operator routinely builds
# on a macOS arm64 laptop for a Linux x86_64 field machine.
#
# Both `docker pull` and `apptainer pull` default to the *host* platform, so
# without this an Apple Silicon build silently produced arm64 images that
# checksum cleanly, verify cleanly, import cleanly, and then fail at the first
# pipeline process on a machine with no network to re-pull from. linux/amd64
# is the default because it is what biocontainers publish and what field
# hardware runs; override per export when that is not true.
_DEFAULT_TARGET_PLATFORM = "linux/amd64"

# platform.machine() spellings mapped to the OCI architecture names used in
# a "os/arch" platform string. Both spellings of each architecture appear in
# the wild depending on OS and Python build.
_OCI_ARCH_ALIASES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}


def _sif_architecture(image: Path) -> Optional[str]:
    """Read the architecture recorded in a SIF image's global header.

    ``apptainer sif header`` prints ``Primary Architecture: amd64``. Returns
    None when apptainer is unavailable or the file is not a readable SIF --
    the caller treats "unknown" as "cannot verify", never as "fine".
    """
    cli = shutil.which("apptainer") or shutil.which("singularity")
    if not cli:
        return None
    try:
        r = subprocess.run(
            [cli, "sif", "header", str(image)],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    m = re.search(r"Primary Architecture:\s*(\S+)", r.stdout or "")
    return m.group(1) if m else None


def _oci_arch(platform_str: str) -> str:
    """Take the architecture out of an ``os/arch`` platform string.

    ``linux/amd64`` -> ``amd64``. Apptainer takes a bare architecture via
    ``--arch``; only Docker understands the full ``os/arch`` form.
    """
    return platform_str.split("/")[-1] if platform_str else platform_str


def _local_container_platform() -> str:
    """This machine as an OCI ``os/arch`` string, e.g. ``linux/amd64``.

    Containers always run Linux regardless of the host OS -- on macOS via the
    Docker Desktop or Apptainer VM -- so only the architecture varies. An
    unrecognised machine string is passed through rather than guessed, so a
    mismatch is reported honestly instead of being silently normalised away.
    """
    machine = platform.machine().lower()
    return f"linux/{_OCI_ARCH_ALIASES.get(machine, machine)}"

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

# Manifest formats this build can import. Bump when the bundle layout changes;
# import_bundle refuses unknown versions (unless forced) so a newer bundle does
# not import "successfully" while silently dropping required data.
_SUPPORTED_MANIFEST_VERSIONS = {"1.0", "1.1"}

# Home subdirectories copied into a bundle, used by estimate_bundle_size for the
# pre-export disk-space preflight. The big ones are genomes and blast.
_BUNDLE_SOURCE_DIRS = ("genomes", "blast", "mappings", "cache",
                       "watchlists", "containers")


def human_size(num_bytes: int) -> str:
    """Format a byte count as a short human string (e.g. '4.2 GB')."""
    size = float(max(num_bytes, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _dir_size(path: Path) -> int:
    """Total size of regular files under *path* (symlinks not followed)."""
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _local_pipeline_dir_for_estimate(config, pipeline_path):
    """Resolve the local pipeline checkout the bundle would ship, or None.

    Mirrors the export-side resolution: an explicit ``pipeline_path`` wins;
    otherwise a ``pipeline_source`` config value that names a local directory
    (not a ``remote:`` / URL / bundle-relative ``./`` sentinel) is used.
    """
    if pipeline_path:
        p = Path(pipeline_path)
        if p.is_dir():
            return p
    ps = (config or {}).get("pipeline_source", "") if config else ""
    if isinstance(ps, str) and ps and not ps.startswith(
        ("remote:", "http://", "https://", "git@", "./", "../")
    ):
        p = Path(ps).expanduser()
        if p.is_dir():
            return p
    return None


# Flat headroom estimates for artefacts that cannot be sized before the
# export actually builds them. Measured: a full singularity/docker pull is
# ~1.6-2.5 GB of archives; a full conda pre-warm cache is ~5 GB.
_PREWARM_SIZE_ESTIMATE = 5 * 1024**3
_CONTAINER_PULL_SIZE_ESTIMATE = 3 * 1024**3


def estimate_bundle_size(
    nanometa_home: str,
    *,
    pre_warm: bool = False,
    config=None,
    pipeline_path=None,
    containerization=None,
) -> int:
    """Rough pre-gzip size estimate (bytes) of the data a bundle would stage.

    Sums the home subdirectories that export copies; includes the pre-warmed
    conda cache only when *pre_warm* is set. When *config*/*pipeline_path* name
    a local pipeline checkout, its size is added (it is bundled too), along
    with the ``~/.nextflow/plugins`` cache. Intended for a disk-space
    preflight, not exact accounting -- gzip shrinks the final tar, but staging
    needs the raw size, so this is a conservative bound (it deliberately
    over-counts, e.g. the checkout's ``.git``, since under-counting lets an
    export run out of disk mid-write).

    Artefacts that only exist after the export builds them get flat
    headroom estimates: the pre-warm cache is built in STAGING (an existing
    ``<home>/conda_cache`` exists only on a machine that already imported a
    bundle, so on a build machine it contributes nothing), and a
    docker/singularity pull's size is unknown before it runs. Both used to
    contribute 0, which under-counted exactly the expensive modes
    (2026-08-27 audit, conda finding 10).
    """
    home = Path(nanometa_home)
    total = sum(_dir_size(home / d) for d in _BUNDLE_SOURCE_DIRS)
    if pre_warm:
        existing_cache = _dir_size(home / _BUNDLED_CONDA_CACHE_DIRNAME)
        total += max(existing_cache, _PREWARM_SIZE_ESTIMATE)
    if containerization in ("docker", "singularity"):
        total += _CONTAINER_PULL_SIZE_ESTIMATE
    pipeline_dir = _local_pipeline_dir_for_estimate(config, pipeline_path)
    if pipeline_dir:
        total += _dir_size(pipeline_dir)
    total += _dir_size(_nextflow_plugins_home())
    return total


def _nextflow_plugins_home() -> Path:
    """The directory Nextflow caches plugins in on this machine.

    Honors ``NXF_HOME`` (and the more specific ``NXF_PLUGINS_DIR``) before
    falling back to ``~/.nextflow/plugins`` -- a build machine that sets
    NXF_HOME caches its plugins there, and reading only the home-dir default
    silently produced bundles with zero plugins (2026-08-17 audit, finding
    G8).
    """
    plugins_dir = os.environ.get("NXF_PLUGINS_DIR")
    if plugins_dir:
        return Path(plugins_dir)
    nxf_home = os.environ.get("NXF_HOME")
    if nxf_home:
        return Path(nxf_home) / "plugins"
    return Path.home() / ".nextflow" / "plugins"

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

# Sentinel: the runner replaces this with a locally built tar.gz of the
# stub Kraken2 DB, so the UNTAR env is exercised without any network
# dependency at export time.
_LOCAL_STUB_DB_ARCHIVE = "@local_stub_db_archive"


def _prepare_scenario_inputs(
    scenario_dir: Path, scenario_params: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str]]:
    """Materialise a scenario's on-disk inputs and return the completed
    param dict plus the input CLI args.

    - Every scenario gets a Kraken2 database: nanometanf nests the whole
      classification block -- and the VALIDATION subworkflow inside it --
      under ``if (params.kraken2_db && !skip_kraken2)``, so without one
      those envs are never resolved. A stub directory with the three .k2d
      files satisfies the existence check; ``-stub`` never reads contents.
    - The ``_LOCAL_STUB_DB_ARCHIVE`` sentinel becomes a locally built
      tar.gz of that stub DB (exercises UNTAR without network).
    - Validation scenarios get a placeholder pathogen_genomes JSON.
    - Realtime scenarios get a pre-seeded watch dir and NO ``input``;
      batch scenarios get a one-row samplesheet as ``input``.

    Values keep their Python types: the runner hands them to Nextflow via a
    ``-params-file`` JSON, because under the strict parser (26.04+) CLI
    ``--flag value`` params arrive as strings and nf-schema type-validation
    rejects a string where the schema says boolean/integer (verified live:
    ``--realtime_mode true`` failed validation as ``[string]``).
    """
    realtime = bool(scenario_params.get("realtime_mode"))

    stub_db = scenario_dir / "stub_kraken2_db"
    if "kraken2_db" not in scenario_params:
        scenario_params["kraken2_db"] = str(_write_stub_kraken2_db(stub_db))
    elif scenario_params["kraken2_db"] == _LOCAL_STUB_DB_ARCHIVE:
        db = _write_stub_kraken2_db(stub_db)
        archive = scenario_dir / "stub_kraken2_db.tar.gz"
        with tarfile.open(str(archive), "w:gz") as tar:
            tar.add(str(db), arcname=db.name)
        scenario_params["kraken2_db"] = str(archive)

    if (
        bool(scenario_params.get("run_validation"))
        and "pathogen_genomes" not in scenario_params
    ):
        # nanometanf validates this file maps taxid -> genome path string
        # (subworkflows/local/validation/main.nf) and aborts otherwise --
        # BEFORE any task runs, so the wrong shape kills the scenario's env
        # builds. One stub taxid with a real (tiny) fasta satisfies it;
        # -stub never aligns against the sequence.
        stub_fasta = scenario_dir / "stub_genome.fasta"
        stub_fasta.write_text(">stub\nACGTACGTACGTACGT\n")
        placeholder = scenario_dir / "pathogen_genomes.json"
        placeholder.write_text(json.dumps({"632": str(stub_fasta)}))
        scenario_params["pathogen_genomes"] = str(placeholder)

    if realtime:
        # Realtime discovers files from nanopore_output_dir; a samplesheet
        # contradicts it. Pre-seed the watch dir so the max_files=1 bound
        # fires immediately instead of watching for the whole timeout.
        watch_dir = scenario_dir / "watch"
        watch_dir.mkdir(exist_ok=True)
        (watch_dir / "stub.fastq.gz").write_bytes(b"")
        scenario_params.setdefault("nanopore_output_dir", str(watch_dir))
        scenario_params.setdefault("max_files", 1)
        return scenario_params, []

    samplesheet = scenario_dir / "samplesheet.csv"
    fastq_stub = scenario_dir / "stub.fastq.gz"
    fastq_stub.write_bytes(b"")  # zero-byte placeholder is fine for stub mode
    samplesheet.write_text(
        "sample,fastq\n"
        f"stub_sample,{fastq_stub}\n"
    )
    scenario_params["input"] = str(samplesheet)
    return scenario_params, []


def _env_materialise_workflow_text(env_files: List[Path]) -> str:
    """One trivial val-input stub process per environment.yml.

    val inputs mean no file can be filtered away, so every process fires
    and Nextflow builds every env with the hash the runtime will look up.
    """
    blocks: List[str] = []
    calls: List[str] = []
    for i, env_file in enumerate(env_files):
        blocks.append(
            f"process ENV_{i} {{\n"
            f"  conda '{env_file}'\n"
            "  input:\n"
            "  val x\n"
            "  output:\n"
            "  stdout\n"
            "  script:\n"
            "  \"\"\"\n"
            "  echo ok\n"
            "  \"\"\"\n"
            "  stub:\n"
            "  \"\"\"\n"
            "  echo ok\n"
            "  \"\"\"\n"
            "}\n"
        )
        calls.append(f"    ENV_{i}(channel.of({i}))")
    return "\n".join(blocks) + "\nworkflow {\n" + "\n".join(calls) + "\n}\n"


def _write_stub_kraken2_db(db_dir: Path) -> Path:
    """Write an empty-but-shaped Kraken2 DB directory.

    ``-stub`` never reads the database contents; the files only need to
    exist so nanometanf's ``file(db_path, checkIfExists: true)`` and the
    classification gate pass.
    """
    from nanometa_live.core.utils.kraken_utils import KRAKEN_REQUIRED_FILES

    db_dir.mkdir(parents=True, exist_ok=True)
    for name in KRAKEN_REQUIRED_FILES:
        (db_dir / name).write_bytes(b"")
    return db_dir

# Pipeline scenarios used to drive Nextflow's stub mode during the
# pre-warm step. Together they cover every per-process environment.yml in
# nanometanf at the time of writing.
#
# Every key here must be a REAL nanometanf parameter (nextflow_schema.json).
# nf-schema only WARNS on unknown params, so a config-vocabulary key
# (processing_mode, sample_handling -- the pre-2026-08-27 registry) makes
# the scenario silently degenerate to the default path while still
# exiting 0 and being recorded as covered.
#
# The runner supplies, unless the scenario overrides them:
# - ``--kraken2_db`` pointing at a locally written stub DB directory, so
#   the classification branch (and the VALIDATION subworkflow nested
#   inside it) instantiates under -stub;
# - ``--input <samplesheet>`` for batch scenarios, or a pre-seeded
#   ``--nanopore_output_dir`` (and NO --input) when ``realtime_mode`` is
#   set -- realtime discovers files, it does not take a samplesheet.
_PRE_WARM_SCENARIOS = [
    {
        "name": "batch_default",
        "params": {},
        "comment": (
            "Default batch path with chopper QC. Covers chopper, seqkit, "
            "nanoplot, kraken2, taxpasta, multiqc, manifest writers."
        ),
    },
    {
        "name": "realtime",
        "params": {
            "realtime_mode": True,
            "max_files": 1,
        },
        "comment": (
            "Realtime watchPath mode, bounded by max_files=1 so the watch "
            "terminates. Adds the realtime-only envs (kraken2 incremental "
            "classifier, cumulative stats, realtime report). The barcode/"
            "per-file/single-sample layouts share this env set, so one "
            "realtime scenario suffices."
        ),
    },
    {
        "name": "validation_blast",
        "params": {
            "run_validation": True,
            "validation_method": "blast",
            # nanometanf refuses validation without read-level Kraken2
            # output (verified live: the guard aborts before -stub fires).
            "save_reads_assignment": True,
            "save_output_fastqs": True,
        },
        "comment": (
            "Triggers BLASTN_VALIDATION, BLAST_MAKEBLASTDB, and "
            "EXTRACT_READS_BY_TAXID envs; required for offline pathogen "
            "confirmation. Depends on the runner-supplied stub kraken2_db: "
            "VALIDATION is nested inside the classification branch."
        ),
    },
    {
        "name": "validation_minimap2",
        "params": {
            "run_validation": True,
            "validation_method": "minimap2",
            "save_reads_assignment": True,
            "save_output_fastqs": True,
        },
        "comment": (
            "Triggers MINIMAP2_ALIGNMENT_VALIDATION and the samtools env "
            "used for alignment post-processing."
        ),
    },
    {
        "name": "fastp_qc",
        "params": {
            "qc_tool": "fastp",
        },
        "comment": (
            "Switches QC tool from chopper to fastp; covers FASTP and "
            "FASTP_STREAMING envs that the default chopper path skips."
        ),
    },
    {
        "name": "filtlong_qc",
        "params": {
            "qc_tool": "filtlong",
        },
        "comment": (
            "Covers the filtlong env. The nf-core filtlong module ships no "
            "stub block, so under -stub its real script runs on the "
            "zero-byte input and may fail AFTER the env is built; a "
            "failure warning from this scenario with the env present in "
            "the cache is expected."
        ),
    },
    {
        "name": "assembly_flye",
        "params": {
            "enable_assembly": True,
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
            "kraken2_db": _LOCAL_STUB_DB_ARCHIVE,
        },
        "comment": (
            "Triggers UNTAR on a tar.gz Kraken2 DB so the untar conda "
            "env is cached. The archive is built locally from the stub DB "
            "at run time -- no network fetch on the build machine."
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
2. Open the Deployment tab in Nanometa Live.
3. In the Import Bundle card, click "Import Bundle" and provide:
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
- pipeline_containers/           Pipeline module images pulled at export
                                 (docker .tar / singularity .img), for
                                 docker/singularity bundles
- watchlist_toggle_state.yaml    Per-entry enable/disable selections
- config.yaml                    Application configuration snapshot
- manifest.json                  Bundle manifest with checksums

## Notes

- The Kraken2 database is NOT included due to its size.
  Transfer it separately (e.g. via USB drive).
- Container images ({container_runtime}) are included if they were
  cached during preparation. For a docker or singularity bundle the
  import step restores ``pipeline_containers/`` under the field-machine
  home, loads docker images via ``docker load``, and points Nextflow at
  the singularity images automatically via ``NXF_SINGULARITY_CACHEDIR``
  (recorded as ``nxf_singularity_cachedir`` in config.yaml); no manual
  step is required.
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
        target_platform: Optional[str] = None,
        progress_cb=None,
    ) -> "ExportResult":
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
            ExportResult with the bundle path, the export warnings the
            caller must surface, and the manifest.
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
            from nanometa_live.core.utils.paths import NanometaPaths
            nanometa_home = str(NanometaPaths.from_config(config or {}).data_dir)
        home = Path(nanometa_home)
        output = Path(output_path)

        def _progress(message: str) -> None:
            # Stage feedback for the GUI/CLI; never let a progress sink's
            # own failure break the export.
            if progress_cb is None:
                return
            try:
                progress_cb(message)
            except Exception:
                logger.debug("progress_cb failed", exc_info=True)

        _progress("Staging data directories (genomes, BLAST DBs, mappings, "
                  "watchlists)...")

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
                # Minimum runtime versions the bundle requires; import warns
                # when the field machine is older.
                "min_versions": {"nextflow": _NEXTFLOW_MIN_VERSION},
                # Non-fatal issues found while staging (e.g. a genome_metadata
                # path outside the data home); surfaced to the operator.
                "export_warnings": [],
            }

            # Record DB hash for compatibility check on import
            db_path = config.get("kraken_db", "")
            if db_path:
                # Check the database is real before hashing it. The hash is
                # what import compares against, so one derived from a path
                # that does not resolve makes the compatibility check
                # meaningless -- and the operator does not find out until the
                # first run, on the air-gapped machine. Symmetric with the
                # import-side check; both go through check_kraken_db.
                from nanometa_live.core.utils.kraken_utils import check_kraken_db

                db_ok, db_missing = check_kraken_db(db_path)
                if not db_ok:
                    detail = (
                        f"missing {', '.join(db_missing)}"
                        if db_missing else "not a readable directory"
                    )
                    manifest["export_warnings"].append(
                        f"Kraken2 database '{db_path}' is not a usable database "
                        f"({detail}). The database is transferred separately, "
                        "but the compatibility hash recorded here was derived "
                        "from this path -- correct it and re-export, or the "
                        "check on import means nothing."
                    )

                from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
                manifest["db_hash"] = get_database_hash(db_path)

            # Copy directories
            dirs_to_copy = ["genomes", "blast", "mappings", "cache"]
            for dirname in dirs_to_copy:
                src = home / dirname
                if src.exists():
                    dst = staging / dirname
                    shutil.copytree(src, dst)

            # Copy watchlists (include actual YAML files, not just references).
            # Under --project-dir the GUI writes uploads to
            # <project_dir>/.nanometa/watchlists, which is NOT under `home`;
            # reading only home/watchlists shipped a bundle with the
            # operator's own lists silently missing. Take both, with the
            # project-scoped directory winning on a name collision since that
            # is the one the running app is reading.
            watchlist_sources = [home / "watchlists"]
            if (config or {}).get("project_dir"):
                from nanometa_live.core.utils.paths import NanometaPaths
                project_watchlists = NanometaPaths.from_config(config).watchlists
                if project_watchlists != watchlist_sources[0]:
                    watchlist_sources.append(project_watchlists)

            staged_watchlists = staging / "watchlists"
            for src_dir in watchlist_sources:
                if not src_dir.is_dir():
                    continue
                staged_watchlists.mkdir(parents=True, exist_ok=True)
                for wl_file in src_dir.rglob("*"):
                    if not wl_file.is_file():
                        continue
                    dst = staged_watchlists / wl_file.relative_to(src_dir)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(wl_file, dst)

            # Also include built-in watchlists from the package
            self._copy_builtin_watchlists(staging / "watchlists", manifest)

            # Copy containers if available
            containers_dir = home / "containers"
            if containers_dir.exists() and any(containers_dir.iterdir()):
                shutil.copytree(containers_dir, staging / "containers")

            # Export taxonomy snapshot
            try:
                from nanometa_live.core.utils.offline_cache import OfflineTaxonomyCache
                cache = OfflineTaxonomyCache()
                snapshot_path = staging / "cache" / "taxonomy_snapshot.json"
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                exported = cache.export_snapshot(str(snapshot_path))
                if exported > 0:
                    logger.info(f"Exported {exported} taxonomy cache entries to bundle")
            except (ImportError, AttributeError, OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not export taxonomy snapshot: {e}")

            # Template genome_metadata.json paths. Path-aware: any absolute
            # path that is NOT under the data home cannot be made portable and
            # is recorded as an export warning for the operator.
            meta_src = home / "genome_metadata.json"
            if meta_src.exists():
                meta_dst = staging / "genome_metadata.json"
                meta_warnings = _template_genome_metadata(
                    meta_src, meta_dst, str(home), _HOME_PLACEHOLDER
                )
                manifest["export_warnings"].extend(meta_warnings)

            # Copy per-entry watchlist toggle state so the field machine
            # restores the operator's enable/disable selections instead of
            # falling back to defaults. Older bundles may lack this file.
            toggle_src = home / "watchlist_toggle_state.yaml"
            if toggle_src.exists():
                toggle_dst = staging / "watchlist_toggle_state.yaml"
                shutil.copy2(toggle_src, toggle_dst)

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
                _progress(
                    "Pre-warming conda environments (this is the long part; "
                    "up to ~30 minutes)..."
                )
                pre_warm_result = self._pre_warm_conda_envs(
                    staging=staging,
                    config=config,
                    pipeline_path=pipeline_path,
                    progress_cb=_progress,
                )
                if pre_warm_result["success"]:
                    # Embed the operator activation script next to the
                    # cache so the imported bundle is self-contained.
                    script_path = staging / _ACTIVATE_SCRIPT_FILENAME
                    script_path.write_text(
                        _ACTIVATE_SCRIPT_TEMPLATE.format(
                            cache_dirname=_BUNDLED_CONDA_CACHE_DIRNAME,
                        )
                    )
                    script_path.chmod(0o755)
            manifest["pre_warm_conda_envs"] = pre_warm_result
            # Fold pre-warm problems into export_warnings: that key is what
            # verify_bundle/import replay to the operator, so a warning kept
            # only under pre_warm_conda_envs is one nobody ever sees
            # (2026-08-27 audit, conda finding 4).
            for w in pre_warm_result.get("warnings", []):
                manifest["export_warnings"].append(f"[conda pre-warm] {w}")
            if pre_warm_result.get("attempted") and not pre_warm_result.get(
                "success"
            ):
                manifest["export_warnings"].append(
                    "[conda pre-warm] Pre-warm did not produce a usable env "
                    "cache; the bundle ships WITHOUT per-process conda envs "
                    "and the field machine will need network access on "
                    "first run."
                )

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
            resolved_target_platform = target_platform or _DEFAULT_TARGET_PLATFORM
            if containerization in ("docker", "singularity"):
                _progress(
                    f"Pulling pipeline container images ({containerization}, "
                    f"{resolved_target_platform})..."
                )
                container_pull_result = self._pull_pipeline_containers(
                    engine=containerization,
                    staging=staging,
                    config=config,
                    pipeline_path=pipeline_path,
                    target_platform=resolved_target_platform,
                    progress_cb=_progress,
                )
            manifest["containerization"] = {
                "engine": containerization,
                "pull_result": container_pull_result,
                # Recorded so the import side can compare the images against
                # the FIELD machine. Comparing build_platform instead is wrong
                # once pulls are pinned: a macOS arm64 host building
                # linux/amd64 images for a Linux x86_64 field machine is
                # correct, and must not be flagged.
                "target_platform": (
                    resolved_target_platform
                    if containerization in ("docker", "singularity")
                    else None
                ),
                # What the images actually are, as read from their headers.
                # The import side checks this in preference to the declared
                # target, because `--arch` is a request the registry may not
                # honour.
                "observed_architectures": container_pull_result.get(
                    "observed_architectures"
                ),
            }
            # Same folding for the container pull: a skipped or partial pull
            # otherwise leaves its warnings buried in
            # manifest.containerization.pull_result where no surface reads
            # them (2026-08-27 audit, GUI finding 1).
            for w in container_pull_result.get("warnings", []):
                manifest["export_warnings"].append(f"[container pull] {w}")

            observed = container_pull_result.get("observed_architectures") or []
            requested_arch = _oci_arch(resolved_target_platform)
            if observed and any(a != requested_arch for a in observed):
                manifest["export_warnings"].append(
                    f"Requested {resolved_target_platform} but the pulled "
                    f"images are {', '.join(sorted(observed))}. Those refs do "
                    "not publish the requested architecture, so the registry "
                    "served what it had. The bundle will not run on a "
                    f"{requested_arch} machine."
                )

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

            # Drop the staging-only ``_pre_warm`` working directory
            # (dummy samplesheets, scratch ``work/``) before checksumming and
            # tarring -- it is not part of the bundle.
            scratch = staging / "_pre_warm"
            if scratch.exists():
                shutil.rmtree(scratch, ignore_errors=True)

            # Normalise symlinks so extraction with tarfile's 'data' filter
            # cannot abort: an absolute link target raises AbsoluteLinkError
            # on import regardless of where it points. Links inside the
            # staging tree become relative; links escaping the tree are
            # dropped with a warning (they would dangle on the field machine
            # anyway).
            self._normalise_staging_symlinks(staging, manifest)

            # Checksum EVERY staged file, in one pass, as the last thing
            # before the manifest is written.
            #
            # This deliberately replaces per-tree checksum loops. Those only
            # covered the trees whose copy code happened to include one, so
            # pipeline_source/ and nextflow_plugins/ -- the workflow itself
            # and the plugins without which Nextflow cannot even parse it --
            # shipped unverified, as did the built-in watchlists, which are
            # copied after the watchlist loop ran. On a real bundle that was
            # 8 files of 1151, and `verify` reported "safe to import" for a
            # bundle whose pipeline source had been replaced with garbage.
            #
            # A single trailing pass is what makes the coverage a property of
            # the bundle rather than of each copy site, so a future staged
            # directory cannot silently reintroduce the gap.
            _progress("Checksumming bundle files...")
            _checksum_staging_tree(staging, manifest)

            # Save manifest (excluded from its own checksums above).
            with open(staging / "manifest.json", "w") as f:
                json.dump(manifest, f, indent=2)

            # Create tar.gz. Exclude macOS AppleDouble sidecars (._*) and
            # .DS_Store -- they ride along when a bundle is built on macOS onto
            # a non-HFS+ volume and confuse Nextflow / extraction on the target.
            def _tar_filter(tarinfo):
                base = Path(tarinfo.name).name
                if base.startswith("._") or base == ".DS_Store":
                    return None
                return tarinfo

            _progress("Writing the compressed archive (large bundles take a "
                      "few minutes)...")
            with tarfile.open(str(output), "w:gz") as tar:
                for item in staging.iterdir():
                    tar.add(str(item), arcname=item.name, filter=_tar_filter)

        if manifest["export_warnings"]:
            logger.warning(
                "Bundle exported to %s with %d warning(s); the bundle may "
                "be incomplete -- review before shipping.",
                output,
                len(manifest["export_warnings"]),
            )
        else:
            logger.info(f"Bundle exported to {output}")
        return ExportResult(
            path=output,
            warnings=list(manifest["export_warnings"]),
            manifest=manifest,
        )

    def verify_bundle(
        self,
        bundle_path: str,
        kraken_db_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify a bundle without writing anything to this machine.

        Runs exactly the checks ``import_bundle`` runs before it starts
        copying -- archive validity, manifest version, recorded export
        warnings, per-file checksums, Kraken2 DB hash, tool and Nextflow
        versions, build platform -- so an operator can check a USB copy
        before committing to an import. Nothing outside the temporary
        extraction directory is touched.

        Args:
            bundle_path: Path to the bundle tar.gz.
            kraken_db_path: Optional Kraken2 DB to check the manifest hash
                against.

        Returns:
            Dict with ``success``, ``warnings``, ``blockers``, ``manifest``
            and the per-check flags described in
            ``_verify_extracted_bundle``.
        """
        result: Dict[str, Any] = {
            "success": True,
            "warnings": [],
            "blockers": [],
            "manifest": {},
        }

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
            try:
                with tarfile.open(bundle_path, "r:gz") as tar:
                    tar.extractall(path=tmpdir, filter="data")
            except (tarfile.TarError, OSError) as e:
                result["success"] = False
                result["warnings"].append(f"Could not extract bundle: {e}")
                return result

            report = self._verify_extracted_bundle(
                Path(tmpdir), kraken_db_path=kraken_db_path
            )

        result["manifest"] = report["manifest"]
        result["warnings"].extend(report["warnings"])
        result["blockers"] = [b["message"] for b in report["blockers"]]
        for key in (
            "export_warnings", "checksum_mismatches",
            "db_hash_mismatch", "platform_mismatch",
        ):
            if key in report:
                result[key] = report[key]
        if report["blockers"]:
            result["success"] = False
            result["warnings"].extend(result["blockers"])
        return result

    def _verify_extracted_bundle(
        self,
        tmp: Path,
        kraken_db_path: Optional[str] = None,
        stop_on_blocker: bool = False,
    ) -> Dict[str, Any]:
        """Run the read-only bundle checks against an extracted bundle tree.

        Shared by ``verify_bundle`` (which extracts to a throwaway dir and
        stops there) and ``import_bundle`` (which continues on to copy).
        Keeping one implementation is the point: a check that only lived in
        the import path could not be offered as a dry run.

        A *blocker* is a problem that aborts an import unless it is forced;
        a *warning* never aborts. ``stop_on_blocker`` reproduces the import's
        short-circuit ordering, so an unforced import does not spend time on
        later checks after it has already decided to abort.
        """
        report: Dict[str, Any] = {
            "manifest": {},
            "warnings": [],
            "blockers": [],
            "export_warnings": [],
            "checksum_mismatches": [],
            "db_hash_mismatch": False,
            "platform_mismatch": False,
        }

        def _blocked() -> bool:
            return stop_on_blocker and bool(report["blockers"])

        manifest = self._verify_load_manifest(tmp, report)
        if manifest is None or _blocked():
            return report

        self._verify_replay_export_warnings(manifest, report)

        self._verify_checksums(tmp, manifest, report)
        if _blocked():
            return report

        self._verify_db_hash(manifest, kraken_db_path, report)
        self._verify_tool_versions(manifest, report)
        self._verify_build_platform(manifest, report)
        self._verify_runnable_offline(tmp, report)

        return report

    @staticmethod
    def _verify_runnable_offline(tmp: Path, report: Dict[str, Any]) -> None:
        """Check the extracted bundle can actually run a pipeline offline.

        These two conditions were previously checked only during import
        (missing ``main.nf`` fails it; missing plugins warn), so
        ``verify_bundle`` -- explicitly offered as the dry run that predicts
        the import -- printed a clean bill for a bundle that could not run a
        single process offline (2026-08-17 audit, finding G2). Severities
        mirror the import path: truncated pipeline source is a blocker,
        absent plugins a warning.
        """
        pipeline_dir = tmp / _BUNDLED_PIPELINE_DIRNAME
        if pipeline_dir.is_dir():
            if not (pipeline_dir / "main.nf").exists():
                report["blockers"].append({
                    "code": "pipeline_main_missing",
                    "fatal": False,
                    "message": (
                        "Bundled pipeline source is missing main.nf; the "
                        "bundle is incomplete or was truncated in transfer. "
                        "Re-export and re-transfer the bundle."
                    ),
                })
        else:
            report["warnings"].append(
                "The bundle contains no pipeline_source/ directory. The "
                "field machine will need the nanometanf checkout supplied "
                "separately; with offline_mode enabled a remote "
                "pipeline_source is refused at launch."
            )

        plugins_dir = tmp / _BUNDLED_NXF_PLUGINS_DIRNAME
        has_plugin = plugins_dir.is_dir() and any(
            p.is_dir() and p.name.startswith(_PLUGIN_PREFIXES)
            for p in plugins_dir.iterdir()
        )
        if not has_plugin:
            detail = (
                f"is empty or missing expected plugin folders"
                if plugins_dir.is_dir()
                else "was not included in this bundle at all"
            )
            report["warnings"].append(
                f"Nextflow plugins: the plugin directory {detail}. Offline, "
                "Nextflow falls back to the online plugin registry and the "
                "run fails before its first process. Re-export from a "
                "machine where Nextflow has run at least once (the plugins "
                "are cached in ~/.nextflow/plugins), or install the plugins "
                "on the field machine."
            )

    def _verify_load_manifest(
        self, tmp: Path, report: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Load and version-check manifest.json.

        Returns None when the manifest is missing or corrupt, which are both
        fatal. An unsupported format version is recorded as a non-fatal
        blocker (forceable) but the manifest is still returned, so refusing
        the import stays the caller's decision.
        """
        manifest_path = tmp / "manifest.json"
        if not manifest_path.exists():
            report["blockers"].append({
                "code": "manifest_missing",
                "fatal": True,
                "message": (
                    "No manifest.json found in bundle. "
                    "This may not be a valid Nanometa Live bundle."
                ),
            })
            return None

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            report["manifest"] = manifest
        except (json.JSONDecodeError, IOError) as e:
            report["blockers"].append({
                "code": "manifest_corrupt",
                "fatal": True,
                "message": f"Corrupted manifest.json: {e}",
            })
            return None

        # Refuse bundles written by an incompatible (newer) format so
        # missing required fields surface here, not as a cryptic runtime
        # error after a "successful" import.
        manifest_version = str(manifest.get("version", ""))
        if manifest_version and manifest_version not in _SUPPORTED_MANIFEST_VERSIONS:
            report["blockers"].append({
                "code": "unsupported_manifest_version",
                "fatal": False,
                "message": (
                    f"Unsupported bundle format (manifest version "
                    f"{manifest_version!r}; this build understands "
                    f"{sorted(_SUPPORTED_MANIFEST_VERSIONS)}). Update Nanometa "
                    "Live on this machine, or force the import."
                ),
                "force_message": (
                    f"Unsupported manifest version {manifest_version!r}; "
                    "continuing anyway (force=True)."
                ),
            })
        return manifest

    def _verify_replay_export_warnings(self, manifest: Dict[str, Any], report: Dict[str, Any]) -> None:
        """Replay non-fatal problems the export recorded.

        They are otherwise visible only on the build machine, and the
        operator running the import is usually not the one who built the
        bundle.
        """
        export_warnings = [str(w) for w in (manifest.get("export_warnings") or [])]
        if export_warnings:
            report["export_warnings"] = export_warnings
            for w in export_warnings:
                logger.warning(f"Export-time warning: {w}")
                report["warnings"].append(f"Recorded at export: {w}")


    def _verify_checksums(self, tmp: Path, manifest: Dict[str, Any], report: Dict[str, Any]) -> None:
        """Check every manifest checksum against the extracted tree."""
        mismatches = []
        for rel_path, expected_md5 in manifest.get("checksums", {}).items():
            full_path = tmp / rel_path
            if full_path.exists():
                if _file_md5(full_path) != expected_md5:
                    mismatches.append(rel_path)
            else:
                mismatches.append(f"{rel_path} (missing)")

        if mismatches:
            report["checksum_mismatches"] = mismatches
            for f_path in mismatches:
                logger.warning(f"Checksum mismatch: {f_path}")
            mismatch_msg = (
                f"{len(mismatches)} file(s) failed checksum verification: "
                f"{', '.join(mismatches[:5])}"
                + ("..." if len(mismatches) > 5 else "")
            )
            report["blockers"].append({
                "code": "checksum_mismatch",
                "fatal": False,
                "message": (
                    f"{mismatch_msg}. Blocking issue. "
                    "Use force=True to import despite mismatches."
                ),
                "force_message": (
                    f"{mismatch_msg}. Continuing anyway (force=True)."
                ),
            })


    def _verify_db_hash(self, manifest: Dict[str, Any], kraken_db_path: Optional[str], report: Dict[str, Any]) -> None:
        """Flag a Kraken2 database that does not match the bundled artefacts.

        The bundled taxid mappings and taxonomy index are keyed off the DB
        hash, so a mismatch imports cleanly and then trips readiness checks
        as CRITICAL with no obvious link back to the import.
        """
        if kraken_db_path and manifest.get("db_hash"):
            from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
            local_hash = get_database_hash(kraken_db_path)
            if local_hash != manifest["db_hash"]:
                report["db_hash_mismatch"] = True
                report["warnings"].append(
                    "Kraken2 database mismatch: the bundled taxid mappings "
                    "and taxonomy index were built for a different database "
                    f"(bundle hash {manifest['db_hash']}, this database "
                    f"{local_hash}). Readiness and the pipeline look up the "
                    "mappings by this database's hash, so they will not be "
                    "found and the 'Database index' / 'Taxid mappings' "
                    "readiness checks will fail. Point the Kraken2 database "
                    "at the exact one the bundle was built for, or re-run the "
                    "'Taxonomy index + mappings' step on the Watchlist & "
                    "Preparation tab to regenerate them for this database."
                )


    def _verify_tool_versions(self, manifest: Dict[str, Any], report: Dict[str, Any]) -> None:
        """Compare bundled tool versions with local ones; warnings only."""
        bundle_versions = manifest.get("tool_versions", {})
        if bundle_versions:
            local_versions = self._collect_tool_versions()
            report["warnings"].extend(
                _check_version_compatibility(bundle_versions, local_versions)
            )

        # Enforce the bundle's minimum runtime versions (warn, do not fail).
        nf_floor = manifest.get("min_versions", {}).get("nextflow")
        if nf_floor:
            local_nf = _get_nextflow_version()
            floor_t = _parse_semver(nf_floor)
            local_t = _parse_semver(local_nf)
            if local_nf in ("not found", "error", "unknown") or local_t is None:
                report["warnings"].append(
                    f"Could not determine the field machine's Nextflow version "
                    f"({local_nf}); the bundled pipeline requires Nextflow "
                    f">={nf_floor}. Confirm Nextflow is installed and current."
                )
            elif floor_t and local_t < floor_t:
                report["warnings"].append(
                    f"Field machine Nextflow {local_nf} is older than the bundle's "
                    f"required minimum {nf_floor}. Update Nextflow before launching "
                    "the pipeline."
                )


    def _verify_build_platform(self, manifest: Dict[str, Any], report: Dict[str, Any]) -> None:
        """Warn on an OS/architecture mismatch.

        Conda environments and compiled binaries are not portable across
        platform boundaries, so pre-warmed envs make it a blocker.
        """
        build_plat = manifest.get("build_platform", {})
        if build_plat:
            local_system = platform.system()
            local_machine = platform.machine()
            bundle_system = build_plat.get("system", "")
            bundle_machine = build_plat.get("machine", "")
            if (bundle_system and bundle_machine) and (
                local_system != bundle_system or local_machine != bundle_machine
            ):
                report["platform_mismatch"] = True
                msg = (
                    f"Bundle was built on {bundle_system}/{bundle_machine} "
                    f"but field machine is {local_system}/{local_machine}. "
                    "Pre-warmed conda envs and bundled binaries will likely "
                    "not work. Plan to rebuild conda envs from "
                    "environment.yml on the field machine."
                )
                logger.warning(msg)
                report["warnings"].append(msg)

                # Pre-warmed conda envs embed absolute build-host paths and
                # per-arch binaries; on a platform mismatch they cannot run
                # at all. Refuse the import (unless forced) so the operator
                # learns now instead of at the first pipeline process.
                prewarm = manifest.get("pre_warm_conda_envs", {})
                if prewarm.get("success"):
                    report["blockers"].append({
                        "code": "platform_prewarm_conda",
                        "fatal": False,
                        "message": (
                            "Blocking issue: the bundle ships pre-warmed conda "
                            "environments that cannot run on this OS/architecture. "
                            "Rebuild the bundle on a matching machine, use Docker "
                            "mode, or force the import and rebuild conda envs here."
                        ),
                    })

        self._verify_container_architecture(manifest, report)

    def _verify_container_architecture(
        self, manifest: Dict[str, Any], report: Dict[str, Any]
    ) -> None:
        """Refuse a bundle whose container images cannot run on this machine.

        Separate from the build-platform check above because it asks a
        different question. That one is about pre-warmed conda envs, which are
        tied to the machine that built them. This one is about the images, and
        a cross-platform build is *correct*: macOS arm64 producing linux/amd64
        images for an x86_64 field machine is the normal case.
        """
        # Prefer what the images ARE over what the export asked for, independently
        # of where the bundle was built. Once pulls are pinned, a macOS arm64
        # host producing linux/amd64 images for a Linux x86_64 field machine is
        # correct and must not be flagged -- while an arm64 image set arriving
        # on an x86_64 machine is fatal in practice and has to stop the import.
        #
        # It was previously only a warning, and only via the build_platform
        # comparison above: the images checksum cleanly, verify cleanly and
        # import cleanly, so the operator's single dismissible advisory was
        # followed by every pipeline process failing on a machine with no
        # network to re-pull from.
        containerization = manifest.get("containerization") or {}
        bundle_platform = containerization.get("target_platform")
        image_count = (containerization.get("pull_result") or {}).get("image_count", 0)

        # Prefer what the images *are* over what the export asked for. `--arch`
        # is a request, not a guarantee: exporting with --target-platform
        # linux/arm64 in an apptainer 1.5.3 rig produced 23 amd64 images (the
        # only architecture those refs publish, served silently) and one hard
        # failure. The manifest then declared arm64 over 24 amd64 images, and
        # comparing the declaration against an arm64 field machine reported no
        # mismatch for a bundle in which nothing could execute.
        observed = containerization.get("observed_architectures") or []
        if observed and image_count:
            local_arch = _oci_arch(_local_container_platform())
            wrong = sorted(a for a in observed if a != local_arch)
            if wrong:
                report["platform_mismatch"] = True
                spread = (
                    f"architectures {', '.join(sorted(observed))}"
                    if len(observed) > 1
                    else f"architecture {wrong[0]}"
                )
                report["blockers"].append({
                    "code": "container_platform_mismatch",
                    "fatal": False,
                    "message": (
                        f"Blocking issue: the bundle's container images have "
                        f"{spread}, but this machine is {local_arch}. Images "
                        "that do not match cannot execute here and an "
                        "air-gapped machine cannot re-pull them. Rebuild the "
                        f"bundle on a machine that can produce {local_arch} "
                        "images, or force the import if you will supply them "
                        "separately."
                    ),
                })
        elif bundle_platform and image_count:
            # Older bundles carry no observed data; fall back to the
            # declaration so they still import.
            local_platform = _local_container_platform()
            if bundle_platform != local_platform:
                report["platform_mismatch"] = True
                report["blockers"].append({
                    "code": "container_platform_mismatch",
                    "fatal": False,
                    "message": (
                        f"Blocking issue: the bundle's {image_count} container "
                        f"image(s) were built for {bundle_platform} but this "
                        f"machine is {local_platform}. They cannot execute here, "
                        "and an air-gapped machine cannot re-pull them. Rebuild "
                        f"the bundle with --target-platform {local_platform}, or "
                        "force the import if you will supply images separately."
                    ),
                })



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
            # import_bundle has no config in scope (it runs before
            # the bundle's own config.yaml is rebased onto the field
            # machine), so fall back to NANOMETA_DATA_DIR.
            from nanometa_live.core.utils.paths import get_data_dir_from_env
            nanometa_home = get_data_dir_from_env()
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
            # Extract bundle. The 'data' filter rejects absolute or
            # escaping link targets and special files; exports normalise
            # symlinks so a compliant bundle never trips it, but a
            # hand-built or pre-fix bundle can -- turn that into an
            # actionable refusal instead of an uncaught traceback.
            try:
                with tarfile.open(bundle_path, "r:gz") as tar:
                    tar.extractall(path=tmpdir, filter='data')
            except tarfile.FilterError as exc:
                result["success"] = False
                result["warnings"].append(
                    "The bundle contains an entry the safe extraction "
                    f"filter refuses ({exc}). This usually means an "
                    "absolute symlink inside the archive; re-export the "
                    "bundle with the current version, which normalises "
                    "symlinks at export time."
                )
                return result
            except (tarfile.TarError, OSError, EOFError) as exc:
                result["success"] = False
                result["warnings"].append(
                    f"Could not extract the bundle: {exc}. The archive is "
                    "likely truncated or corrupted in transfer; re-transfer "
                    "it and retry."
                )
                return result

            tmp = Path(tmpdir)

            # Read-only verification, shared with verify_bundle so the
            # dry run and the real import cannot drift apart.
            verify = self._verify_extracted_bundle(
                tmp, kraken_db_path=kraken_db_path, stop_on_blocker=not force
            )
            manifest = verify["manifest"]
            result["manifest"] = manifest
            result["warnings"].extend(verify["warnings"])
            for _key in ("export_warnings", "checksum_mismatches"):
                if verify[_key]:
                    result[_key] = verify[_key]
            if verify["db_hash_mismatch"]:
                result["db_hash_mismatch"] = True

            for blocker in verify["blockers"]:
                if force and not blocker.get("fatal"):
                    result["warnings"].append(
                        blocker.get("force_message", blocker["message"])
                    )
                    continue
                result["success"] = False
                result["warnings"].append(blocker["message"])
                return result

            # Copy directories to home (handle partial imports gracefully)
            for dirname in [
                "genomes", "blast", "mappings", "cache",
                "watchlists", "containers",
                _BUNDLED_CONDA_CACHE_DIRNAME,
                _BUNDLED_PIPELINE_DIRNAME,
                _BUNDLED_NXF_PLUGINS_DIRNAME,
                _BUNDLED_PIPELINE_CONTAINERS_DIRNAME,
            ]:
                src = tmp / dirname
                if src.exists():
                    dst = home / dirname
                    if dst.exists():
                        # Merge: copy new files, skip existing. Symlinks are
                        # recreated as symlinks -- copy2 would dereference
                        # them (multi-GB expansion in a conda cache) and
                        # raise on a dangling one.
                        for src_file in src.rglob("*"):
                            rel = src_file.relative_to(src)
                            dst_file = dst / rel
                            if src_file.is_symlink():
                                dst_file.parent.mkdir(parents=True, exist_ok=True)
                                target = os.readlink(str(src_file))
                                if dst_file.is_symlink() or dst_file.exists():
                                    if (
                                        dst_file.is_symlink()
                                        and os.readlink(str(dst_file)) == target
                                    ):
                                        continue
                                    if dst_file.is_dir() and not dst_file.is_symlink():
                                        continue
                                    dst_file.unlink()
                                os.symlink(target, str(dst_file))
                            elif src_file.is_file():
                                dst_file.parent.mkdir(parents=True, exist_ok=True)
                                if not dst_file.exists():
                                    shutil.copy2(src_file, dst_file)
                                else:
                                    # Overwrite if checksums differ
                                    if _file_md5(src_file) != _file_md5(dst_file):
                                        shutil.copy2(src_file, dst_file)
                    else:
                        # symlinks=True: preserve links as links. A conda
                        # cache holds thousands of (possibly dangling)
                        # symlinks; dereferencing balloons the install and a
                        # dangling link raises shutil.Error mid-import.
                        shutil.copytree(src, dst, symlinks=True)

            # Re-verify checksums AFTER the copy to home. The tempdir pass
            # above proves the bundle arrived intact; this pass catches a copy
            # that failed midway (disk full, interrupted) and left an
            # incomplete install. genome_metadata.json and config.yaml are
            # templated/mutated on copy, so their on-disk hash legitimately
            # differs from the bundle checksum -- exclude them here.
            # NOTE: pipeline_containers/ holds the largest artefacts in a
            # docker/singularity bundle (multi-hundred-MB image archives), so
            # it is exactly what an interrupted copy truncates first. It must
            # stay in this tuple.
            _copied_roots = (
                "genomes/", "blast/", "mappings/", "cache/", "watchlists/",
                "containers/", f"{_BUNDLED_CONDA_CACHE_DIRNAME}/",
                f"{_BUNDLED_PIPELINE_DIRNAME}/", f"{_BUNDLED_NXF_PLUGINS_DIRNAME}/",
                f"{_BUNDLED_PIPELINE_CONTAINERS_DIRNAME}/",
            )
            _mutated = {"genome_metadata.json", "config.yaml"}
            post_copy_mismatches = []
            for rel_path, expected_md5 in manifest.get("checksums", {}).items():
                if rel_path in _mutated:
                    continue
                if not rel_path.startswith(_copied_roots):
                    continue
                dst_file = home / rel_path
                if not dst_file.exists():
                    post_copy_mismatches.append(f"{rel_path} (missing)")
                elif _file_md5(dst_file) != expected_md5:
                    post_copy_mismatches.append(rel_path)
            if post_copy_mismatches:
                msg = (
                    f"{len(post_copy_mismatches)} file(s) failed checksum "
                    f"verification AFTER copy to {home} (likely a full disk or an "
                    f"interrupted copy): {', '.join(post_copy_mismatches[:5])}"
                    + ("..." if len(post_copy_mismatches) > 5 else "")
                )
                if not force:
                    result["success"] = False
                    result["warnings"].append(msg + ". The install is incomplete.")
                    return result
                result["warnings"].append(msg + ". Continuing anyway (force=True).")

            # Relocate the pre-warmed conda cache: rewrite the recorded
            # build prefix (embedded in shebangs, conda-meta and binaries)
            # to the restored location. Must run AFTER the post-copy
            # checksum pass -- relocation legitimately changes file
            # contents. Without this every env ships dead-on-arrival, even
            # re-imported on the build machine (2026-08-27 audit, finding 1).
            pwc_manifest = manifest.get("pre_warm_conda_envs") or {}
            restored_cache = home / _BUNDLED_CONDA_CACHE_DIRNAME
            if pwc_manifest.get("build_prefix") and restored_cache.is_dir():
                from nanometa_live.core.workflow.conda_cache_utils import (
                    list_complete_env_dirs,
                    relocate_conda_cache,
                )

                stats = relocate_conda_cache(
                    restored_cache, pwc_manifest["build_prefix"]
                )
                result["conda_relocation"] = stats
                if stats["failures"]:
                    result["warnings"].append(
                        f"{len(stats['failures'])} file(s) in the conda cache "
                        "could not be relocated to this machine (e.g. "
                        f"{stats['failures'][0]}); the affected env(s) will "
                        "fail at run time. Re-export the bundle."
                    )
                logger.info(
                    "Relocated conda cache to %s: %d text, %d binary, "
                    "%d symlink rewrites",
                    restored_cache,
                    stats["text_rewritten"],
                    stats["binary_patched"],
                    stats["symlinks_retargeted"],
                )

                # Cross-check the restored env count against what the
                # export recorded -- mirror of the container-image
                # incomplete_image_set guard.
                expected_envs = pwc_manifest.get("env_count") or 0
                restored_envs = len(list_complete_env_dirs(restored_cache))
                if expected_envs and restored_envs < expected_envs:
                    result["incomplete_conda_cache"] = True
                    result["warnings"].append(
                        f"Only {restored_envs} of {expected_envs} pre-warmed "
                        "conda env(s) survived the transfer; missing envs "
                        "will be re-built at run time, which fails on an "
                        "air-gapped machine. Re-transfer or re-export the "
                        "bundle."
                    )

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

            # Load container images if present (operator-managed BLAST
            # validation containers, distinct from the pipeline's own pulled
            # images under pipeline_containers/ below).
            containers_dir = home / "containers"
            if containers_dir.exists() and any(containers_dir.iterdir()):
                op_report = self._load_container_images(containers_dir)
                if op_report["loaded"] > 0:
                    logger.info(
                        f"Loaded {op_report['loaded']} container images from bundle"
                    )
                # Surface a load failure instead of reporting success over
                # it. Mirrors the pipeline_containers/ handling below (the
                # 2026-08-14 fix) -- this simpler operator-container path
                # was missed by that pass and previously only logged on
                # success, so importing a bundle with BLAST validation
                # containers onto a field machine where Docker is not
                # running reported success:True with no mention of the
                # containers, and validation then failed opaquely at run
                # time with no link back to the import step that caused it.
                op_docker_broken = (
                    op_report["tar_count"] > 0
                    and op_report["tar_loaded"] == 0
                    and not op_report["docker_usable"]
                )
                if op_docker_broken:
                    result["container_runtime_unavailable"] = True
                    if not op_report["docker_available"]:
                        cause = (
                            "the 'docker' command was not found on this machine"
                        )
                    else:
                        cause = (
                            "the Docker daemon did not respond ('docker info' failed)"
                        )
                    msg = (
                        f"The bundle ships {op_report['tar_count']} operator "
                        "container image archive(s) under containers/ (e.g. "
                        f"BLAST validation containers) but none could be "
                        f"loaded: {cause}. Install Docker (or start the "
                        "Docker daemon) on this machine and re-run the import."
                    )
                    logger.warning(msg)
                    result["warnings"].append(msg)
                elif op_report["tar_count"] > op_report["tar_loaded"]:
                    msg = (
                        f"Only {op_report['tar_loaded']} of "
                        f"{op_report['tar_count']} operator container "
                        "image(s) under containers/ could be loaded: "
                        f"{'; '.join(op_report['failures']) or 'see log for details'}."
                    )
                    logger.warning(msg)
                    result["warnings"].append(msg)

            # Restore pipeline-pulled container images shipped in
            # ``pipeline_containers/``. The export side pulls every module
            # image here (docker ``.tar`` / singularity ``.img``); without
            # this they ride in the tarball but are never wired to the
            # runtime, so an air-gapped run re-pulls and fails. Docker tars
            # are ``docker load``-ed; singularity images are used in place and
            # surfaced via ``singularity_cache_path`` so the config below can
            # point NXF_SINGULARITY_CACHEDIR at them.
            pipeline_images = home / _BUNDLED_PIPELINE_CONTAINERS_DIRNAME
            if pipeline_images.is_dir() and any(pipeline_images.iterdir()):
                load_report = self._load_container_images(pipeline_images)
                loaded_count = load_report["loaded"]
                if loaded_count > 0:
                    logger.info(
                        f"Restored {loaded_count} pipeline container images "
                        "from bundle"
                    )
                # Cross-check against the count the export side recorded. A
                # partial pull (a single failed docker save / apptainer pull)
                # is caught and warned about at export, not aborted, so a
                # bundle can ship fewer images than the pipeline needs. Without
                # this check the shortfall imports as a silent success and only
                # surfaces as a cryptic "image not found" at the first run.
                expected = (
                    manifest.get("containerization", {})
                    .get("pull_result", {})
                    .get("image_count", 0)
                )
                # Separate the two causes of a low count. If the bundle
                # carries Docker archives but this machine has no working
                # Docker, nothing could have been loaded regardless of how
                # complete the bundle is -- the fix is here, not on the
                # build machine.
                docker_broken = (
                    load_report["tar_count"] > 0
                    and load_report["tar_loaded"] == 0
                    and not load_report["docker_usable"]
                )
                if docker_broken:
                    result["container_runtime_unavailable"] = True
                    if not load_report["docker_available"]:
                        cause = (
                            "the 'docker' command was not found on this machine"
                        )
                    else:
                        cause = (
                            "the Docker daemon did not respond ('docker info' failed)"
                        )
                    msg = (
                        f"The bundle ships {load_report['tar_count']} Docker image "
                        f"archive(s) but none could be loaded: {cause}. The bundle "
                        "itself is intact. Install Docker (or start the Docker "
                        "daemon) on this machine and re-run the import, or use a "
                        "bundle built in singularity or conda mode."
                    )
                    logger.warning(msg)
                    result["warnings"].append(msg)
                elif expected and loaded_count < expected:
                    result["incomplete_image_set"] = True
                    msg = (
                        f"Only {loaded_count} of {expected} pipeline container "
                        "images are present in the bundle; the export pulled an "
                        "incomplete set (see the export-time warnings). Missing "
                        "images will be re-pulled at run time, which fails on an "
                        "air-gapped machine. Re-export from a machine that can "
                        "reach the container registry."
                    )
                    logger.warning(msg)
                    result["warnings"].append(msg)
                has_sif = any(pipeline_images.glob("*.img")) or any(
                    pipeline_images.glob("*.sif")
                )
                if has_sif:
                    result["singularity_cache_path"] = str(pipeline_images)
                    logger.info(
                        "Bundled Singularity images restored to "
                        f"{pipeline_images}; NXF_SINGULARITY_CACHEDIR will be "
                        "set to this directory."
                    )

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
                    # No DB path supplied: config still carries the export-time
                    # placeholder (or is empty). The run will fail cryptically
                    # later, so flag it now -- but do not abort, since
                    # importing first and pointing the DB later is a valid flow.
                    # ConfigLoader normalises path keys, so the export-time
                    # "${KRAKEN_DB}" placeholder arrives here as
                    # "<cwd>/${KRAKEN_DB}" -- match the token as a substring.
                    eff_db = str(cfg.get("kraken_db", ""))
                    if not kraken_db_path and (
                        not eff_db or _KRAKEN_DB_PLACEHOLDER in eff_db
                    ):
                        result["kraken_db_unset"] = True
                        result["warnings"].append(
                            "Kraken2 database path was not provided. The Kraken2 "
                            "database is transferred separately from the bundle; set "
                            "its path on the Watchlist & Preparation tab (or kraken_db "
                            "in config.yaml) before starting analysis, or the run will "
                            "fail."
                        )
                    elif kraken_db_path:
                        # A path that was supplied but is wrong fails the run
                        # exactly like one that was never supplied, so it
                        # deserves the same warning. This branch used to be
                        # absent entirely: the guard above fires only on an
                        # EMPTY path, so a typo, an unmounted drive or a moved
                        # directory imported in silence.
                        from nanometa_live.core.utils.kraken_utils import (
                            check_kraken_db,
                        )

                        db_ok, db_missing = check_kraken_db(kraken_db_path)
                        if not db_ok:
                            result["kraken_db_invalid"] = True
                            detail = (
                                f"missing {', '.join(db_missing)}"
                                if db_missing else "not a readable directory"
                            )
                            result["warnings"].append(
                                f"Kraken2 database path '{kraken_db_path}' is not "
                                f"a usable database ({detail}). The database is "
                                "transferred separately from the bundle; correct "
                                "the path on the Watchlist & Preparation tab (or "
                                "kraken_db in config.yaml) before starting "
                                "analysis, or the run will fail."
                            )
                    if "conda_cache_path" in result:
                        cfg["nxf_conda_cachedir"] = result["conda_cache_path"]
                    if "singularity_cache_path" in result:
                        cfg["nxf_singularity_cachedir"] = result[
                            "singularity_cache_path"
                        ]
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
                            # A truncated transfer can leave the directory
                            # present but missing main.nf; that only surfaces as
                            # a cryptic error at launch, so fail the import now.
                            if not (abs_pipeline / "main.nf").exists():
                                result["success"] = False
                                result["pipeline_main_missing"] = True
                                result["warnings"].append(
                                    "Bundled pipeline source at "
                                    f"{abs_pipeline} is missing main.nf; the bundle "
                                    "is incomplete or was truncated in transfer. "
                                    "Re-export and re-transfer the bundle."
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
                    # Plugin completeness is checked unconditionally below,
                    # outside this branch -- see _check_bundled_plugins.
                    import_loader.save_config(cfg, "config.yaml")
                    logger.info("Set offline_mode=True in config")
                    # Hand the rebased config back so the GUI's finalize can
                    # push it into the live app-config store -- without this
                    # the running app keeps the pre-import config until a
                    # restart (2026-08-27 audit, GUI finding 5).
                    result["imported_config"] = dict(cfg)
                    result["config_path"] = str(config_path)
                except (ImportError, AttributeError, OSError, ValueError) as e:
                    # Fail the import. Without the rebased config the
                    # installation still carries the export-time placeholders
                    # ("${KRAKEN_DB}", "./pipeline_source"), so every path in
                    # it points nowhere and offline_mode was never set -- an
                    # unusable install, previously reported as a successful
                    # import because this branch only appended a warning.
                    # The missing-main.nf branch above already fails the
                    # import for the same class of problem.
                    result["success"] = False
                    result["config_write_failed"] = True
                    result["warnings"].append(
                        f"Could not update config: {e}. The imported "
                        "configuration still contains unresolved bundle "
                        "placeholders, so this installation will not run. "
                        "Re-run the import once the cause is fixed."
                    )

        # Outside the config-rebase block on purpose: it must also run when the
        # bundle carried no plugins (so no key to rebase) and when the rebase
        # itself failed above -- both are cases where an offline run cannot
        # resolve nf-schema.
        self._check_bundled_plugins(home, result)

        logger.info(f"Bundle imported to {home}")
        return result

    def _pull_pipeline_containers(
        self,
        engine: str,
        staging: Path,
        config: Dict[str, Any],
        pipeline_path: Optional[str],
        target_platform: Optional[str] = None,
        progress_cb=None,
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

        for i, ref in enumerate(refs, start=1):
            # Apply the pipeline's default registry to bare refs (quay.io),
            # mirroring Nextflow's docker.registry; otherwise biocontainers
            # images are pulled from Docker Hub where they do not exist.
            pull_ref = self._apply_default_registry(ref)
            if progress_cb is not None:
                try:
                    progress_cb(
                        f"Pulling container image {i}/{len(refs)}: {pull_ref}"
                    )
                except Exception:
                    logger.debug("progress_cb failed", exc_info=True)
            try:
                if engine == "docker":
                    self._pull_one_docker_image(
                        pull_ref, images_dir, platform=target_platform
                    )
                else:
                    self._pull_one_singularity_image(
                        pull_ref, images_dir, cli, platform=target_platform
                    )
                    # Record what actually landed. `--arch` is a request:
                    # apptainer serves the only published architecture when
                    # the requested one does not exist, so the bundle can
                    # disagree with its own target_platform.
                    arch = _sif_architecture(
                        images_dir / self._singularity_cache_name(pull_ref)
                    )
                    if arch:
                        result.setdefault("observed_architectures", [])
                        if arch not in result["observed_architectures"]:
                            result["observed_architectures"].append(arch)
                    else:
                        result.setdefault("arch_unverified", []).append(pull_ref)
                result["pulled"].append(pull_ref)
                result["image_count"] += 1
            except subprocess.SubprocessError as exc:
                result["warnings"].append(
                    f"Failed to pull {pull_ref}: {exc}"
                )
                logger.warning(f"{engine} pull failed for {pull_ref}: {exc}")
            except OSError as exc:
                result["warnings"].append(f"OSError pulling {pull_ref}: {exc}")
                logger.warning(f"{engine} pull OSError for {pull_ref}: {exc}")

        return result

    @staticmethod
    def _apply_default_registry(ref: str, registry: str = _DEFAULT_DOCKER_REGISTRY) -> str:
        """Prepend the default registry to a ref that omits one.

        Mirrors Nextflow's ``docker.registry`` resolution: a ref whose first
        path component has no ``.``/``:`` (and is not ``localhost``) is a Docker
        Hub shorthand and, for nanometanf, must resolve under ``quay.io`` (where
        the biocontainers images live). Refs that already name a registry
        (``community.wave.seqera.io/...``, ``quay.io/...``) are returned
        unchanged. A ``docker://`` scheme prefix is preserved.
        """
        prefix = ""
        body = ref
        if body.startswith("docker://"):
            prefix, body = "docker://", body[len("docker://"):]
        if body.startswith(("http://", "https://", "oras://")):
            return ref  # explicit URL (e.g. Galaxy singularity image)
        first = body.split("/", 1)[0]
        if "." in first or ":" in first or first == "localhost":
            return ref  # already has an explicit registry host
        return f"{prefix}{registry}/{body}"

    @staticmethod
    def _ref_to_safe_filename(ref: str) -> str:
        """Convert a container reference to a filename-safe slug."""
        # Strip docker:// prefix for filename purposes; keep tag info.
        if ref.startswith("docker://"):
            ref = ref[len("docker://"):]
        if ref.startswith("https://"):
            ref = ref[len("https://"):]
        return re.sub(r"[^a-zA-Z0-9._-]", "_", ref)[:200]

    def _check_bundled_plugins(self, home: Path, result: Dict[str, Any]) -> None:
        """Report a bundle that cannot resolve Nextflow plugins offline.

        nanometanf declares ``plugins { id 'nf-schema@...' }``, so a run
        resolves a plugin before it does anything else. Offline that can only
        come from the bundle, via ``NXF_PLUGINS_PATH``.

        Called unconditionally, because the interesting case is the one where
        *nothing* was bundled. ``_bundle_nextflow_plugins`` reads
        ``Path.home()/".nextflow"/"plugins"``, so a build machine that has
        never run Nextflow -- a CI runner, a container, a laptop that only
        exports -- bundles no plugins and never writes ``nxf_plugins_dir``.
        The previous check lived inside ``if npd == "./nextflow_plugins"``, so
        it only ran when plugins *had* been bundled: empty warned, absent was
        silent. Verified end to end in an air-gapped rig, where export,
        transfer, verify and import all reported success on a bundle that
        could not have run one pipeline process.
        """
        plugins_dir = home / _BUNDLED_NXF_PLUGINS_DIRNAME
        has_plugin = plugins_dir.is_dir() and any(
            p.is_dir() and p.name.startswith(_PLUGIN_PREFIXES)
            for p in plugins_dir.iterdir()
        )
        if has_plugin:
            return

        result["plugins_empty"] = True
        detail = (
            f"is empty or missing expected plugin folders ({plugins_dir})"
            if plugins_dir.is_dir()
            else "was not included in this bundle at all"
        )
        result.setdefault("warnings", []).append(
            f"Nextflow plugins: the plugin directory {detail}. Offline, "
            "Nextflow falls back to the online plugin registry and the run "
            "fails before its first process. Re-export from a machine where "
            "Nextflow has run at least once (the plugins are cached in "
            "~/.nextflow/plugins), or install the plugins on the field "
            "machine."
        )

    def _pull_one_docker_image(
        self, ref: str, target_dir: Path, platform: Optional[str] = None
    ) -> None:
        """``docker pull`` then ``docker save`` one image to a tar.

        ``platform`` pins which entry of a multi-arch manifest list is
        fetched. Without it Docker resolves to the build host, so an arm64
        laptop shipped arm64 images to an x86_64 field machine.
        """
        pull_cmd = ["docker", "pull"]
        if platform:
            pull_cmd += ["--platform", platform]
        pull_cmd.append(ref)
        subprocess.run(
            pull_cmd,
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

    @staticmethod
    def _singularity_cache_name(ref: str) -> str:
        """Return the on-disk filename Nextflow expects for a pre-pulled image.

        Mirrors Nextflow's ``SingularityCache.simpleName(url) + '.img'``:
        strip the URL scheme at ``://``, then replace ``:`` and ``/`` with
        ``-`` and append ``.img``. Nextflow reuses an image only when it is
        cached under this exact name in ``NXF_SINGULARITY_CACHEDIR``; any
        other name makes it re-pull, which fails on an air-gapped machine.
        The convention has been stable across Nextflow 22.x-26.x -- keep this
        in lock-step with it (verified against the SingularityCache class in
        the bundled Nextflow jar).
        """
        p = ref.find("://")
        name = ref[p + 3:] if p != -1 else ref
        name = name.replace(":", "-").replace("/", "-")
        return f"{name}.img"

    def _pull_one_singularity_image(
        self,
        ref: str,
        target_dir: Path,
        cli: str,
        platform: Optional[str] = None,
    ) -> None:
        """``apptainer pull`` (or ``singularity pull``) one image.

        The output is named per Nextflow's cache convention (see
        ``_singularity_cache_name``) so the field machine reuses it via
        ``NXF_SINGULARITY_CACHEDIR`` instead of re-pulling.

        ``platform`` is passed only for OCI sources (``docker://``, ``oras://``
        or a bare registry ref), where there is a manifest list to choose from.
        A ``https://depot.galaxyproject.org/...`` reference is a direct .sif
        download -- there is no choice to make, the file is whatever Galaxy
        built (amd64) -- and passing an architecture there is meaningless at
        best and an error at worst.

        Note the flag is ``--arch <arch>``, not ``--platform <os/arch>``:
        apptainer has no ``--platform`` and rejects it outright (verified
        against apptainer 1.5.3). Its ``--arch`` help text says "architecture
        to pull from library", but it does apply to ``docker://`` sources --
        confirmed empirically: pulling alpine with ``--arch amd64`` on an arm64
        host yields an amd64 image, which apptainer then refuses to exec with
        "the image's architecture (amd64) could not run on the host's (arm64)".
        Docker, by contrast, does take ``--platform linux/amd64``.
        """
        out = target_dir / self._singularity_cache_name(ref)
        cmd = [cli, "pull", "--force"]
        if platform and not ref.startswith(("http://", "https://")):
            cmd += ["--arch", _oci_arch(platform)]
        cmd += [str(out), ref]
        subprocess.run(
            cmd,
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
        progress_cb=None,
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

        # Build the cache under a deliberately PADDED directory name. Conda
        # envs embed this absolute prefix in shebangs, conda-meta JSON and
        # NUL-terminated strings inside binaries; import relocates it to the
        # field machine's cache path with a length-preserving in-place
        # rewrite, which only works while the destination is SHORTER than
        # the build prefix. Padding to PREFIX_PAD_TARGET makes that hold for
        # any realistic destination. The directory is renamed to the
        # canonical conda_cache/ before checksumming and tarring; the padded
        # path is recorded as ``build_prefix`` for the import-side rewrite.
        from nanometa_live.core.workflow.conda_cache_utils import (
            PREFIX_PAD_TARGET,
            list_complete_env_dirs,
            prune_incomplete_env_dirs,
        )

        pad_name = _BUNDLED_CONDA_CACHE_DIRNAME + "_build"
        deficit = PREFIX_PAD_TARGET - len(str(staging / pad_name))
        if deficit > 0:
            pad_name += "_" * deficit
        cache_root = staging / pad_name
        cache_root.mkdir(parents=True, exist_ok=True)
        outcome["build_prefix"] = str(cache_root)

        env = os.environ.copy()
        env["NXF_CONDA_CACHEDIR"] = str(cache_root)
        # Discourage Nextflow from auto-updating itself mid-run on the
        # build machine; that would defeat reproducibility of the
        # pinned envs we are about to bake into the bundle.
        env.setdefault("NXF_OFFLINE", "false")

        for scenario_no, scenario in enumerate(_PRE_WARM_SCENARIOS, start=1):
            if progress_cb is not None:
                try:
                    progress_cb(
                        f"Pre-warm scenario {scenario_no}/"
                        f"{len(_PRE_WARM_SCENARIOS)}: {scenario['name']} "
                        "(conda may be solving environments; be patient)"
                    )
                except Exception:
                    logger.debug("progress_cb failed", exc_info=True)
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

        # Completing sweep: guarantee an env for EVERY module, including
        # processes the scenarios cannot reach (nanometanf filters empty
        # stub outputs, so e.g. KRAKEN2/NANOPLOT never fire under -stub
        # and their envs were missing from the cache -- caught live in the
        # 2026-08-27 field rehearsal).
        if progress_cb is not None:
            try:
                progress_cb(
                    "Materialising remaining module envs (one stub process "
                    "per environment.yml)..."
                )
            except Exception:
                logger.debug("progress_cb failed", exc_info=True)
        mat_ok, mat_msg, mat_count = self._materialise_all_module_envs(
            pipeline_dir=resolved_pipeline,
            staging=staging,
            env=env,
        )
        outcome["module_env_files"] = mat_count
        if not mat_ok:
            outcome["warnings"].append(
                f"Module-env materialisation failed: {mat_msg}. Envs the "
                "scenarios did not reach may be missing from the bundle."
            )
            logger.warning(outcome["warnings"][-1])

        final_root = staging / _BUNDLED_CONDA_CACHE_DIRNAME
        # A scenario runner that ignored NXF_CONDA_CACHEDIR and wrote the
        # canonical directory name directly (older mocks) still yields a
        # usable cache; prefer the padded root when it holds anything.
        effective_root = cache_root
        if not any(cache_root.iterdir()) and final_root.is_dir():
            effective_root = final_root
            outcome["build_prefix"] = str(final_root)

        # Prune envs that did not finish building (a timed-out or killed
        # scenario leaves a stub directory Nextflow's cache would treat as
        # ready; shipped, it fails exit-127 on the air-gapped machine).
        pruned = prune_incomplete_env_dirs(effective_root)
        for name in pruned:
            outcome["warnings"].append(
                f"Pruned incomplete conda env '{name}' from the bundle "
                "(build did not finish; the owning scenario likely failed "
                "or timed out)."
            )
            logger.warning(outcome["warnings"][-1])

        # Count COMPLETE envs, matching any directory name -- Nextflow
        # names an env from environment.yml's ``name:`` key when declared,
        # so an ``env-`` prefix filter under-counts.
        env_dirs = list_complete_env_dirs(effective_root)
        outcome["env_count"] = len(env_dirs)
        outcome["success"] = bool(outcome["scenarios"]) and outcome["env_count"] > 0

        if not outcome["success"]:
            # Drop the half-populated cache directory so the bundle
            # does not silently ship a broken cache.
            shutil.rmtree(cache_root, ignore_errors=True)
            shutil.rmtree(final_root, ignore_errors=True)
            return outcome

        # Absolute internal symlinks must become relative BEFORE the rename
        # below invalidates their targets; an absolute link would also make
        # the import-side tar 'data' filter abort the whole extraction.
        from nanometa_live.core.workflow.conda_cache_utils import (
            make_symlinks_relative,
        )

        link_result = make_symlinks_relative(effective_root)
        for dropped in link_result["dropped"]:
            outcome["warnings"].append(
                f"Dropped symlink '{dropped}' pointing outside the conda "
                "cache; it would dangle on the field machine."
            )

        if effective_root is cache_root and cache_root != final_root:
            cache_root.rename(final_root)
        elif effective_root is final_root:
            shutil.rmtree(cache_root, ignore_errors=True)

        return outcome

    @staticmethod
    def _normalise_staging_symlinks(staging: Path, manifest: Dict[str, Any]) -> None:
        """Backstop pass over the WHOLE staging tree: no absolute symlink
        may reach the tar. tarfile's 'data' extraction filter raises
        AbsoluteLinkError for any absolute link target, which would abort
        the entire import with no actionable message. In-tree targets are
        rewritten relative; out-of-tree targets are dropped with an
        export warning (they would dangle on the field machine anyway).
        The conda cache gets its own earlier pass (before its rename); this
        one covers every other staged tree, e.g. a pipeline checkout or a
        plugin cache that happens to carry an absolute link.
        """
        staging_str = str(staging)
        for path in list(staging.rglob("*")):
            if not path.is_symlink():
                continue
            try:
                target = os.readlink(str(path))
            except OSError:
                continue
            if not os.path.isabs(target):
                continue
            if target == staging_str or target.startswith(staging_str + os.sep):
                rel = os.path.relpath(target, start=str(path.parent))
                path.unlink()
                os.symlink(rel, str(path))
            else:
                path.unlink()
                manifest["export_warnings"].append(
                    f"Dropped symlink '{path.relative_to(staging)}' pointing "
                    f"outside the bundle ({target}); it would dangle on the "
                    "field machine."
                )

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

        plugins_home = _nextflow_plugins_home()
        if not plugins_home.is_dir():
            logger.info(
                f"{plugins_home} not found; skipping plugin bundling."
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

        # Always include the common Nextflow helper plugins (module constant
        # _PLUGIN_PREFIXES, shared with the import-side empty-dir check).
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
    def _materialise_all_module_envs(
        pipeline_dir: Path,
        staging: Path,
        env: Dict[str, str],
    ) -> Tuple[bool, str, int]:
        """Build EVERY module env into the cache via a generated stub run.

        The scenario runs cannot guarantee coverage: nanometanf filters
        empty files between steps, and a stub block's touched outputs are
        empty -- so a process downstream of such a filter (KRAKEN2 and
        NANOPLOT in the 2026-08-27 field rehearsal) never fires and its
        env never lands in the cache; the field machine then attempts a
        network solve. This generates a workflow with one trivial
        val-input process per ``modules/**/environment.yml`` (no files,
        so nothing can be filtered) and runs it ``-stub`` against the
        same NXF_CONDA_CACHEDIR: Nextflow computes its own cache hash
        from the same environment.yml content the field run will hash,
        so every env lands exactly where the runtime looks.

        Returns ``(ok, message, env_file_count)``.
        """
        import subprocess

        env_files = sorted((pipeline_dir / "modules").rglob("environment.yml"))
        if not env_files:
            return True, "no module environment files", 0

        run_dir = staging / "_pre_warm" / "_env_materialise"
        run_dir.mkdir(parents=True, exist_ok=True)

        (run_dir / "main.nf").write_text(
            _env_materialise_workflow_text(env_files)
        )
        (run_dir / "nextflow.config").write_text("conda.enabled = true\n")

        cmd = [
            "nextflow", "run", str(run_dir / "main.nf"),
            "-stub",
            "-work-dir", str(run_dir / "work"),
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(run_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return False, f"subprocess error: {exc}", len(env_files)

        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").splitlines()[-5:]
            return False, "; ".join(tail) or f"exit {result.returncode}", len(env_files)
        return True, "ok", len(env_files)

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

        scenario_params, _ = _prepare_scenario_inputs(
            scenario_dir, dict(scenario.get("params", {}))
        )

        # Params travel as a typed JSON file: under the strict parser
        # (Nextflow 26.04+) CLI ``--flag value`` params arrive as strings
        # and nf-schema rejects a string where the schema says
        # boolean/integer, so ``--realtime_mode true`` fails validation.
        scenario_params["outdir"] = str(scenario_dir / "results")
        params_file = scenario_dir / "params.json"
        params_file.write_text(json.dumps(scenario_params, indent=2))

        cmd = [
            "nextflow", "run", str(pipeline_dir / "main.nf"),
            "-stub",
            "-profile", "conda",
            "-work-dir", str(scenario_dir / "work"),
            "-params-file", str(params_file),
        ]

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

    def _copy_builtin_watchlists(
        self, dst_dir: Path, manifest: Dict[str, Any]
    ) -> None:
        """Copy built-in watchlist YAMLs to the bundle.

        Resolves the source directory via importlib.resources so the lookup
        works under both regular and editable installs. Editable installs
        produce a namespace package whose __file__ attribute is None, which
        breaks the legacy Path(wl_pkg.__file__).parent approach.

        A failure here is recorded in the manifest's ``export_warnings``:
        the built-in watchlists are what makes a fresh field install able to
        screen anything at all, so a bundle silently shipping without them
        is a bundle that reports NOT SCREENED on the rig (2026-08-17 audit,
        finding W7 -- the earlier version swallowed OSError at debug level).
        """
        try:
            wl_path = _resolve_builtin_watchlist_dir()
            if wl_path is None or not wl_path.is_dir():
                msg = (
                    "Built-in watchlist directory could not be resolved; "
                    "the bundle ships without the built-in watchlists."
                )
                logger.warning(msg)
                manifest["export_warnings"].append(msg)
                return

            dst_dir.mkdir(parents=True, exist_ok=True)

            for yaml_file in wl_path.glob("*.yaml"):
                dst_file = dst_dir / yaml_file.name
                if not dst_file.exists():
                    shutil.copy2(yaml_file, dst_file)
        except (ImportError, AttributeError, OSError) as e:
            msg = (
                f"Could not copy built-in watchlists into the bundle: {e}"
            )
            logger.warning(msg)
            manifest["export_warnings"].append(msg)

    def _load_container_images(self, containers_dir: Path) -> Dict[str, Any]:
        """Load container images from a restored bundle directory.

        Returns a report rather than a bare count so the caller can tell
        apart the two very different reasons ``loaded`` can come out low:
        the bundle shipped fewer images than the pipeline needs (a
        build-machine problem), or the field machine cannot run Docker at
        all (a field-machine problem). Blaming the former for the latter
        sends the operator back to re-export a bundle that is fine.

        Report keys:
            loaded: images now usable (docker-loaded tars + in-place images)
            tar_count / tar_loaded: Docker archives found / loaded
            image_count: Singularity/Apptainer images found (used in place)
            docker_available: the ``docker`` client is on PATH
            docker_usable: the client is present and the daemon responded
            failures: per-file load failure messages
        """
        import subprocess

        report: Dict[str, Any] = {
            "loaded": 0,
            "tar_count": 0,
            "tar_loaded": 0,
            "image_count": 0,
            "docker_available": True,
            "docker_usable": True,
            "failures": [],
        }

        try:
            tar_files = sorted(containers_dir.glob("*.tar"))
            report["tar_count"] = len(tar_files)

            if tar_files:
                report["docker_available"] = shutil.which("docker") is not None
                report["docker_usable"] = report["docker_available"] and _docker_daemon_ok()

            for tar_file in tar_files:
                try:
                    subprocess.run(
                        ["docker", "load", "-i", str(tar_file)],
                        capture_output=True, check=True, timeout=300,
                    )
                    report["tar_loaded"] += 1
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                        FileNotFoundError, PermissionError, OSError) as e:
                    logger.warning(f"Failed to load container image {tar_file.name}: {e}")
                    report["failures"].append(f"{tar_file.name}: {e}")

            # Singularity/Apptainer images are used in-place, no loading
            # needed. Bundle-pulled images use the Nextflow-convention ``.img``
            # extension (see _singularity_cache_name); ``.sif`` is also
            # accepted for images staged by other means.
            sif_count = len(list(containers_dir.glob("*.sif"))) + len(
                list(containers_dir.glob("*.img"))
            )
            report["image_count"] = sif_count
            if sif_count > 0:
                logger.info(f"Found {sif_count} Singularity/Apptainer images (used in-place)")

        except OSError as e:
            logger.warning(f"Error loading container images: {e}")

        report["loaded"] = report["tar_loaded"] + report["image_count"]
        return report


def _docker_daemon_ok() -> bool:
    """Return True when a Docker client is present and its daemon responds.

    ``docker load`` fails identically whether the daemon is stopped or the
    archive is corrupt, so probe the daemon once before attributing the
    failure to the bundle.
    """
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=30
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
        return False


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


def _template_genome_metadata(
    src: Path, dst: Path, home: str, placeholder: str,
) -> List[str]:
    """Template absolute paths in genome_metadata.json to ``placeholder``.

    Parses the JSON and replaces the ``home`` prefix with ``placeholder`` in
    every string value that is an absolute path under ``home``. An absolute
    path that is NOT under ``home`` cannot be made portable; it is left as-is
    and reported in the returned warning list so the operator can fix it on the
    field machine. On a JSON parse error, falls back to the whole-file replace
    (a path-bearing-but-unparseable file is rare) and returns no warnings.

    Returns the list of warning strings (empty in the common all-under-home
    case).
    """
    warnings: List[str] = []
    home_norm = home.rstrip("/")
    try:
        with open(src) as f:
            data = json.load(f)
    except (OSError, ValueError):
        _template_paths(src, dst, home, placeholder)
        return warnings

    def _walk(obj, path_keys):
        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = _walk(v, path_keys + [str(k)])
            return obj
        if isinstance(obj, list):
            return [_walk(v, path_keys + [str(i)]) for i, v in enumerate(obj)]
        if isinstance(obj, str) and os.path.isabs(obj):
            if obj == home_norm or obj.startswith(home_norm + os.sep):
                return placeholder + obj[len(home_norm):]
            warnings.append(
                f"genome_metadata.json: {'/'.join(path_keys) or 'value'} points "
                f"outside the data home ({obj}); it is not portable and must be "
                "corrected on the field machine."
            )
        return obj

    data = _walk(data, [])
    with open(dst, "w") as f:
        json.dump(data, f, indent=2)
    return warnings


#: Strips ANSI SGR sequences. A colour-coded error message contains digits
#: (\x1b[31m) that an unanchored version regex will happily match.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _is_tar_excluded(name: str) -> bool:
    """Whether the tar filter drops this basename.

    macOS writes AppleDouble sidecars (``._*``) and ``.DS_Store`` when staging
    onto a non-HFS+ volume. The export tar filter strips them, so checksumming
    them would record entries that are absent after extraction and every
    verify would report a spurious "missing file".
    """
    return name.startswith("._") or name == ".DS_Store"


def _checksum_staging_tree(staging: Path, manifest: Dict[str, Any]) -> None:
    """Record an md5 for every file that will be shipped in the bundle.

    Called once, after all staging is complete and immediately before the
    manifest is written, so coverage cannot drift as trees are added. Keys are
    staging-relative POSIX paths, matching what ``verify``/``import`` resolve
    against the extracted tree.

    ``manifest.json`` is excluded because it is written after this runs and
    cannot contain its own hash.
    """
    checksums: Dict[str, str] = {}
    for path in sorted(staging.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if _is_tar_excluded(path.name):
            continue
        rel = path.relative_to(staging).as_posix()
        if rel == "manifest.json":
            continue
        checksums[rel] = _file_md5(path)
    manifest["checksums"] = checksums
    logger.info("Bundle manifest covers %d files", len(checksums))


def _parse_semver(version_str: str):
    r"""Return a (major, minor, patch) int tuple from a version string, or None.

    Tolerant of build suffixes ('26.04.0 build 12031', 'v2.1.0', '0.12.0b').
    Missing minor/patch default to 0.

    The match is ANCHORED to the start of the string, and ANSI escapes are
    stripped first. Both matter: the previous unanchored ``(\d+)`` searched
    anywhere in the input, so ``nextflow -version`` on a machine with no Java
    Runtime -- which prints ``\x1b[31mUnable to locate a Java Runtime`` --
    parsed as version **31**.0.0 from the colour code and cleared the 26.4.0
    floor. ``doctor`` then reported the machine as ready to run analyses.

    Anything that is not a version at the start of the string returns None,
    which every caller already treats as "could not determine".
    """
    cleaned = _ANSI_ESCAPE_RE.sub("", version_str or "").strip()
    # Optional leading 'v', then the version must begin the string. A trailing
    # build/qualifier suffix is still allowed ('26.04.0 build 12031', '0.12.0b').
    match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?![\d.])", cleaned)
    if not match:
        return None
    return (
        int(match.group(1)),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
    )


def _get_nextflow_version() -> str:
    """Return the Nextflow version string in 'X.Y.Z build N' form.

    ``nextflow -version`` prints a multi-line banner whose useful line matches
    ``version X.Y.Z build N``.

    When that pattern is absent the output is an error, not a version -- most
    often "Unable to locate a Java Runtime", since Nextflow is a JVM
    application. Returning such a line verbatim let it be mistaken for a
    version downstream, so the fallback only returns a line that actually
    contains a version-shaped token; otherwise "unknown".
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
        # Fallback: only a line that genuinely looks like a version. Prose
        # (a Java error, "command not found") must not be passed off as one.
        for line in output.split("\n"):
            stripped = _ANSI_ESCAPE_RE.sub("", line).strip()
            if not stripped:
                continue
            if re.match(r"v?\d+(\.\d+)+", stripped):
                return stripped[:100]
        if output:
            logger.warning(
                "nextflow -version produced no recognisable version; "
                "output was: %s", output.splitlines()[0][:200] if output else "",
            )
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
