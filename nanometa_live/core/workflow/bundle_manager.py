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

## Contents

- genomes/       Reference genome FASTA files
- blast/         Pre-built BLAST databases
- mappings/      Taxid mapping files
- cache/         Taxonomy cache (GTDB + NCBI snapshots)
- watchlists/    Watchlist YAML configurations
- containers/    Container images (if included)
- config.yaml    Application configuration snapshot
- manifest.json  Bundle manifest with checksums

## Notes

- The Kraken2 database is NOT included due to its size.
  Transfer it separately (e.g. via USB drive).
- Container images ({container_runtime}) are included if they were
  cached during preparation.
- Tool versions used during preparation are recorded in manifest.json.
"""


class BundleManager:
    """Export and import portable mobile lab bundles."""

    def export_bundle(
        self,
        output_path: str,
        config: Dict[str, Any],
        nanometa_home: Optional[str] = None,
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

            # Save config (with kraken_db as placeholder)
            from nanometa_live.core.config.config_loader import ConfigLoader
            bundle_config = dict(config)
            bundle_config["kraken_db"] = "${KRAKEN_DB}"
            bundle_loader = ConfigLoader(str(staging))
            bundle_loader.save_config(bundle_config, "config.yaml")

            # Generate README
            readme_content = _README_TEMPLATE.format(
                creation_date=manifest["creation_date"],
                creator=manifest["creator"],
                version=manifest["version"],
                container_runtime=manifest["container_runtime"] or "none cached",
            )
            readme_path = staging / "README_FIELD.md"
            readme_path.write_text(readme_content)

            # Save manifest
            with open(staging / "manifest.json", "w") as f:
                json.dump(manifest, f, indent=2)

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
            for dirname in ["genomes", "blast", "mappings", "cache", "watchlists", "containers"]:
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
                    import_loader.save_config(cfg, "config.yaml")
                    logger.info("Set offline_mode=True in config")
                except (ImportError, AttributeError, OSError, ValueError) as e:
                    result["warnings"].append(f"Could not update config: {e}")

        logger.info(f"Bundle imported to {home}")
        return result

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


def _check_version_compatibility(
    bundle_versions: Dict[str, str],
    local_versions: Dict[str, str],
) -> List[str]:
    """Compare bundle tool versions against local installations.

    Returns a list of warning strings for major version mismatches.
    """
    warnings = []
    for tool, bundle_ver in bundle_versions.items():
        local_ver = local_versions.get(tool, "not found")

        # Skip tools that are not found or had errors
        if bundle_ver in ("not found", "unknown", "error"):
            continue
        if local_ver in ("not found", "unknown", "error"):
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
