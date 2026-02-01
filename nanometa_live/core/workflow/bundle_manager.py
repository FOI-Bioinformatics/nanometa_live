"""
Bundle manager for exporting and importing mobile lab preparation bundles.

Handles packaging all cached data (genomes, BLAST DBs, mappings, taxonomy cache)
into a portable tar.gz archive with path rebasing for cross-machine transfers.
The Kraken2 database itself is never included due to its size.
"""

import hashlib
import json
import logging
import os
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Placeholder token for absolute paths in exported metadata
_HOME_PLACEHOLDER = "${NANOMETA_HOME}"


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
        taxonomy cache, watchlists, and a manifest with checksums.
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
                "version": "1.0",
                "created": datetime.now().isoformat(),
                "nanometa_home": str(home),
                "checksums": {},
                "tool_versions": {},
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
                    # Compute checksums
                    for f in dst.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(staging)
                            manifest["checksums"][str(rel)] = _file_md5(f)

            # Copy watchlists
            watchlist_dir = home / "watchlists"
            if watchlist_dir.exists():
                shutil.copytree(watchlist_dir, staging / "watchlists")

            # Template genome_metadata.json paths
            meta_src = home / "genome_metadata.json"
            if meta_src.exists():
                meta_dst = staging / "genome_metadata.json"
                _template_paths(meta_src, meta_dst, str(home), _HOME_PLACEHOLDER)
                manifest["checksums"]["genome_metadata.json"] = _file_md5(meta_dst)

            # Save config (with kraken_db as placeholder)
            bundle_config = dict(config)
            bundle_config["kraken_db"] = "${KRAKEN_DB}"
            with open(staging / "config.yaml", "w") as f:
                import yaml
                yaml.safe_dump(bundle_config, f, default_flow_style=False)

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
    ) -> Dict[str, Any]:
        """
        Import a bundle and set up for offline operation.

        Extracts bundle contents to nanometa_home, rebases templated
        paths, and verifies checksums.

        Args:
            bundle_path: Path to the bundle tar.gz.
            kraken_db_path: Path to the Kraken2 database on this machine.
            nanometa_home: Target ~/.nanometa directory.

        Returns:
            Dict with import results (success, warnings, manifest).
        """
        if nanometa_home is None:
            nanometa_home = os.path.expanduser("~/.nanometa")
        home = Path(nanometa_home)
        home.mkdir(parents=True, exist_ok=True)

        result = {"success": True, "warnings": [], "manifest": {}}

        with tempfile.TemporaryDirectory() as tmpdir:
            # Extract bundle
            with tarfile.open(bundle_path, "r:gz") as tar:
                tar.extractall(path=tmpdir)

            tmp = Path(tmpdir)

            # Load manifest
            manifest_path = tmp / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    manifest = json.load(f)
                result["manifest"] = manifest
            else:
                result["warnings"].append("No manifest found in bundle")
                manifest = {}

            # Verify DB hash compatibility
            if kraken_db_path and manifest.get("db_hash"):
                from nanometa_live.core.taxonomy.taxid_mapping import get_database_hash
                local_hash = get_database_hash(kraken_db_path)
                if local_hash != manifest["db_hash"]:
                    result["warnings"].append(
                        f"Database hash mismatch: bundle={manifest['db_hash']}, "
                        f"local={local_hash}. Mappings may need regeneration."
                    )

            # Copy directories to home
            for dirname in ["genomes", "blast", "mappings", "cache", "watchlists"]:
                src = tmp / dirname
                if src.exists():
                    dst = home / dirname
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)

            # Rebase genome_metadata.json
            meta_src = tmp / "genome_metadata.json"
            if meta_src.exists():
                meta_dst = home / "genome_metadata.json"
                _template_paths(
                    meta_src, meta_dst,
                    _HOME_PLACEHOLDER, str(home)
                )

            # Verify checksums
            checksums = manifest.get("checksums", {})
            mismatches = 0
            for rel_path, expected_md5 in checksums.items():
                full_path = home / rel_path
                if full_path.exists():
                    actual = _file_md5(full_path)
                    if actual != expected_md5:
                        mismatches += 1
                else:
                    mismatches += 1

            if mismatches:
                result["warnings"].append(
                    f"{mismatches} file(s) failed checksum verification"
                )

        logger.info(f"Bundle imported to {home}")
        return result


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
