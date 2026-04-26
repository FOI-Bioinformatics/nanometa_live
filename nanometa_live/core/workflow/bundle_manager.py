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
import re
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

# Placeholder token for absolute paths in exported metadata
_HOME_PLACEHOLDER = "${NANOMETA_HOME}"

# Default location inside the bundle staging area for the pre-warmed
# Nextflow conda cache. Operators set NXF_CONDA_CACHEDIR to the
# extracted location of this directory on the field machine.
_BUNDLED_CONDA_CACHE_DIRNAME = "conda_cache"

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
    },
    {
        "name": "realtime_multiplex",
        "params": {
            "processing_mode": "realtime",
            "sample_handling": "by_barcode",
        },
    },
    {
        "name": "realtime_per_file",
        "params": {
            "processing_mode": "realtime",
            "sample_handling": "per_file",
        },
    },
    {
        "name": "realtime_single_sample",
        "params": {
            "processing_mode": "realtime",
            "sample_handling": "single_sample",
        },
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

To make Nextflow use it, export ``NXF_CONDA_CACHEDIR`` before
launching Nanometa Live::

    export NXF_CONDA_CACHEDIR=$HOME/.nanometa/{conda_cache_dirname}

The helper script ``scripts/activate_offline_envs.sh`` (if
present) does this for you. Pre-warmed scenarios cover:
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
    ) -> Path:
        """
        Export a portable bundle containing all prepared data.

        The bundle includes genomes, BLAST databases, taxid mappings,
        taxonomy cache, watchlists, containers, and a manifest with checksums.
        The Kraken2 database is excluded (transferred separately).

        Args:
            output_path: Path for the output tar.gz file.
            config: Current application configuration.
            nanometa_home: Path to ~/.nanometa directory.
            pre_warm_conda_envs: If True, run nanometanf in stub mode
                under ``-profile conda`` so Nextflow resolves and creates
                every per-process env. The populated cache directory is
                then included in the bundle. Adds roughly 30 minutes and
                ~5 GB to the build. Default False so existing flows are
                unaffected.
            pipeline_path: Optional explicit path to the nanometanf
                checkout. Required when ``pre_warm_conda_envs`` is True
                and ``config['pipeline_source']`` does not resolve to a
                local directory. The path must contain ``main.nf``.

        Returns:
            Path to the created bundle file.
        """
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

            # Save config (with kraken_db as placeholder)
            from nanometa_live.core.config.config_loader import ConfigLoader
            bundle_config = dict(config)
            bundle_config["kraken_db"] = "${KRAKEN_DB}"
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
            if pre_warm_conda_envs:
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
            manifest["pre_warm_conda_envs"] = pre_warm_result

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

            # Copy directories to home (handle partial imports gracefully)
            for dirname in [
                "genomes", "blast", "mappings", "cache",
                "watchlists", "containers",
                _BUNDLED_CONDA_CACHE_DIRNAME,
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
                    import_loader.save_config(cfg, "config.yaml")
                    logger.info("Set offline_mode=True in config")
                except (ImportError, AttributeError, OSError, ValueError) as e:
                    result["warnings"].append(f"Could not update config: {e}")

        logger.info(f"Bundle imported to {home}")
        return result

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

        # Nextflow
        versions["nextflow"] = _get_command_version("nextflow", ["-version"])

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
