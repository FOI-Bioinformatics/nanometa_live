"""
Container image discovery, caching, and loading for offline deployment.

Parses nanometanf module files to discover container directives, then
pulls and saves images for Docker or Singularity runtimes. For conda
environments, exports dependency specs instead of caching images.
"""

import gzip
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Patterns for extracting container image URLs from .nf files
# Docker images: 'biocontainers/...', 'quay.io/...', 'community.wave.seqera.io/...'
_DOCKER_IMAGE_RE = re.compile(
    r"'((?:biocontainers|quay\.io/biocontainers|community\.wave\.seqera\.io/library)/[^']+)'"
)
# Singularity images: 'https://depot.galaxyproject.org/singularity/...'
# or 'https://community-cr-prod.seqera.io/docker/registry/...'
# or 'oras://community.wave.seqera.io/...'
_SINGULARITY_IMAGE_RE = re.compile(
    r"'((?:https://depot\.galaxyproject\.org/singularity/[^']+|"
    r"https://community-cr-prod\.seqera\.io/docker/registry/[^']+|"
    r"oras://community\.wave\.seqera\.io/[^']+))'"
)


def _safe_name(image: str) -> str:
    """Convert an image URL to a filesystem-safe filename."""
    name = image.split("/")[-1] if "/" in image else image
    # Replace problematic characters
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a subprocess command and return the result."""
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )


class ContainerCacher:
    """Discover, cache, and load container images for offline use."""

    def __init__(self, cache_dir: str = "~/.nanometa/containers"):
        self.cache_dir = Path(os.path.expanduser(cache_dir))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def detect_runtime(self) -> str:
        """Detect available container runtime.

        Returns:
            One of 'docker', 'singularity', 'conda', or 'none'.
        """
        for runtime, cmd in [
            ("docker", ["docker", "info"]),
            ("singularity", ["singularity", "--version"]),
            ("conda", ["conda", "--version"]),
        ]:
            try:
                result = _run(cmd, timeout=15)
                if result.returncode == 0:
                    logger.info("Detected runtime: %s", runtime)
                    return runtime
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        logger.warning("No container runtime detected")
        return "none"

    def discover_images(self, pipeline_dir: str) -> List[Dict]:
        """Parse nanometanf modules for container directives.

        Args:
            pipeline_dir: Root directory of the nanometanf pipeline.

        Returns:
            Deduplicated list of dicts with keys: name, docker_image,
            singularity_image, module.
        """
        modules_dir = Path(pipeline_dir) / "modules"
        if not modules_dir.exists():
            logger.error("Modules directory not found: %s", modules_dir)
            return []

        # Collect all .nf files
        nf_files = sorted(modules_dir.rglob("*.nf"))
        seen_docker = set()
        images = []

        for nf_file in nf_files:
            try:
                content = nf_file.read_text(encoding="utf-8")
            except OSError:
                logger.warning("Could not read %s", nf_file)
                continue

            # Only process files with container directives
            if "container " not in content:
                continue

            docker_matches = _DOCKER_IMAGE_RE.findall(content)
            singularity_matches = _SINGULARITY_IMAGE_RE.findall(content)

            # Take the first docker and singularity match per file
            docker_image = docker_matches[0] if docker_matches else None
            singularity_image = singularity_matches[0] if singularity_matches else None

            if not docker_image:
                continue

            # Deduplicate by docker image
            if docker_image in seen_docker:
                continue
            seen_docker.add(docker_image)

            # Derive a short name from the docker image
            # e.g. 'biocontainers/kraken2:2.1.3--...' -> 'kraken2'
            name_part = docker_image.split("/")[-1]
            name = name_part.split(":")[0] if ":" in name_part else name_part

            # Module path relative to modules/
            try:
                module_rel = str(nf_file.relative_to(modules_dir))
            except ValueError:
                module_rel = str(nf_file)

            images.append({
                "name": name,
                "docker_image": docker_image,
                "singularity_image": singularity_image,
                "module": module_rel,
            })

        logger.info("Discovered %d unique container images", len(images))
        return images

    def cache_images(
        self,
        images: List[Dict],
        runtime: str,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Dict[str, str]:
        """Pull and save container images to the cache directory.

        Args:
            images: List from discover_images().
            runtime: 'docker', 'singularity', or 'conda'.
            progress_callback: Optional callback(image_name, current, total).

        Returns:
            Mapping of image identifier to cached file path.
        """
        if runtime == "conda":
            return self._cache_conda_specs()

        cached = {}
        total = len(images)

        for i, img in enumerate(images, 1):
            image_key = img["docker_image"]
            name = _safe_name(img["docker_image"])

            if progress_callback:
                progress_callback(img["name"], i, total)

            try:
                if runtime == "docker":
                    path = self._cache_docker_image(image_key, name)
                elif runtime == "singularity":
                    sing_url = img.get("singularity_image") or f"docker://{image_key}"
                    path = self._cache_singularity_image(sing_url, name)
                else:
                    logger.warning("Unsupported runtime: %s", runtime)
                    continue

                if path:
                    cached[image_key] = str(path)
                    logger.info("Cached %s -> %s", img["name"], path)

            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
                logger.error("Failed to cache %s: %s", img["name"], exc)

        logger.info("Cached %d / %d images", len(cached), total)
        return cached

    def _cache_docker_image(self, image: str, safe_name: str) -> Optional[Path]:
        """Pull a Docker image and save as a gzipped tar archive."""
        out_path = self.cache_dir / f"{safe_name}.tar.gz"
        if out_path.exists():
            logger.info("Already cached: %s", out_path)
            return out_path

        # Pull
        result = _run(["docker", "pull", image], timeout=900)
        if result.returncode != 0:
            logger.error("docker pull failed: %s", result.stderr.strip())
            return None

        # Save and compress
        tar_path = self.cache_dir / f"{safe_name}.tar"
        result = _run(["docker", "save", "-o", str(tar_path), image], timeout=600)
        if result.returncode != 0:
            logger.error("docker save failed: %s", result.stderr.strip())
            tar_path.unlink(missing_ok=True)
            return None

        # Gzip the tar
        with open(tar_path, "rb") as f_in, gzip.open(out_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        tar_path.unlink(missing_ok=True)

        return out_path

    def _cache_singularity_image(self, image_url: str, safe_name: str) -> Optional[Path]:
        """Pull a Singularity image to a .sif file."""
        out_path = self.cache_dir / f"{safe_name}.sif"
        if out_path.exists():
            logger.info("Already cached: %s", out_path)
            return out_path

        # For https URLs, singularity pull can use them directly
        # For docker:// URLs, pass as-is
        result = _run(
            ["singularity", "pull", str(out_path), image_url],
            timeout=900,
        )
        if result.returncode != 0:
            logger.error("singularity pull failed: %s", result.stderr.strip())
            out_path.unlink(missing_ok=True)
            return None

        return out_path

    def _cache_conda_specs(self) -> Dict[str, str]:
        """Export current conda environment spec for offline reference."""
        spec_path = self.cache_dir / "conda_env_spec.txt"
        result = _run(["conda", "list", "--export"], timeout=60)
        if result.returncode == 0:
            spec_path.write_text(result.stdout, encoding="utf-8")
            logger.info("Exported conda spec to %s", spec_path)
            return {"conda_spec": str(spec_path)}
        logger.error("conda list --export failed: %s", result.stderr.strip())
        return {}

    def load_images(self, cache_dir: Optional[str] = None, runtime: str = "docker") -> int:
        """Load cached images into the local container runtime.

        Args:
            cache_dir: Directory containing cached images. Defaults to self.cache_dir.
            runtime: 'docker' or 'singularity'.

        Returns:
            Number of images loaded.
        """
        source = Path(cache_dir) if cache_dir else self.cache_dir
        if not source.exists():
            logger.warning("Cache directory does not exist: %s", source)
            return 0

        loaded = 0

        if runtime == "docker":
            for archive in sorted(source.glob("*.tar.gz")):
                result = _run(
                    ["docker", "load", "-i", str(archive)],
                    timeout=600,
                )
                if result.returncode == 0:
                    loaded += 1
                    logger.info("Loaded: %s", archive.name)
                else:
                    logger.error("Failed to load %s: %s", archive.name, result.stderr.strip())

        elif runtime == "singularity":
            # For singularity, copy .sif files to the NXF cache dir
            nxf_cache = os.environ.get(
                "NXF_SINGULARITY_CACHEDIR",
                os.path.expanduser("~/.singularity/cache"),
            )
            nxf_cache_path = Path(nxf_cache)
            nxf_cache_path.mkdir(parents=True, exist_ok=True)

            for sif in sorted(source.glob("*.sif")):
                dest = nxf_cache_path / sif.name
                if not dest.exists():
                    shutil.copy2(sif, dest)
                    loaded += 1
                    logger.info("Copied %s to %s", sif.name, nxf_cache_path)
                else:
                    logger.info("Already present: %s", dest)
                    loaded += 1
        else:
            logger.info("No image loading needed for runtime: %s", runtime)

        logger.info("Loaded %d images for %s", loaded, runtime)
        return loaded

    def get_cache_status(self) -> Dict:
        """Return a summary of the container cache state.

        Returns:
            Dict with keys: total_images, cached_docker, cached_singularity,
            cached_conda, total_size_mb.
        """
        docker_files = list(self.cache_dir.glob("*.tar.gz"))
        singularity_files = list(self.cache_dir.glob("*.sif"))
        conda_spec = self.cache_dir / "conda_env_spec.txt"

        total_size = sum(f.stat().st_size for f in docker_files + singularity_files)
        if conda_spec.exists():
            total_size += conda_spec.stat().st_size

        return {
            "cache_dir": str(self.cache_dir),
            "cached_docker": len(docker_files),
            "cached_singularity": len(singularity_files),
            "cached_conda": 1 if conda_spec.exists() else 0,
            "total_images": len(docker_files) + len(singularity_files),
            "total_size_mb": round(total_size / (1024 * 1024), 1),
        }


# Singleton instance
_cacher_instance: Optional[ContainerCacher] = None


def get_container_cacher(cache_dir: str = "~/.nanometa/containers") -> ContainerCacher:
    """Return or create the singleton ContainerCacher instance."""
    global _cacher_instance
    if _cacher_instance is None:
        _cacher_instance = ContainerCacher(cache_dir=cache_dir)
    return _cacher_instance
