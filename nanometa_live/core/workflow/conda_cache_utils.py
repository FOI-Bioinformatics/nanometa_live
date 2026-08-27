"""Shared helpers for the pre-warmed Nextflow conda cache.

Conda environments are not relocatable by default: the absolute install
prefix is embedded in console-script shebangs, ``conda-meta/*.json`` and
NUL-terminated strings inside compiled binaries. The bundle export builds
the cache under a deliberately padded prefix (see ``PREFIX_PAD_TARGET``)
and records it in the manifest; ``relocate_conda_cache`` rewrites that
prefix to the restored location at import time. The padding is what makes
the binary rewrite safe -- the replacement is NUL-padded in place, so it
must never be longer than the original.

``is_complete_conda_env`` is the single definition of "this env finished
building" shared by the export-side pruning and the launch-time purge in
``NextflowManager`` (a SIGTERM-killed build leaves a stub directory that
activates fine and then fails exit-127 on first use).
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum length of the build prefix the pre-warm step embeds into the
# envs. Any realistic destination (`~/.nanometa/conda_cache`, a mounted
# data dir) is far shorter, so the in-place binary rewrite always fits.
PREFIX_PAD_TARGET = 180


def is_complete_conda_env(env_dir: Path) -> bool:
    """True when the env finished building.

    Predicate (do not simplify -- see NextflowManager._purge_broken_conda_envs):
    ``conda-meta/history`` exists (the marker conda writes last on success)
    AND ``bin/`` exists non-empty (a build aborted mid-link can leave the
    history marker with an empty bin/, which activates and then every tool
    is "command not found").
    """
    history = env_dir / "conda-meta" / "history"
    if not history.is_file():
        return False
    bin_dir = env_dir / "bin"
    try:
        if not bin_dir.is_dir() or not any(bin_dir.iterdir()):
            return False
    except OSError:
        return False
    return True


def list_complete_env_dirs(cache_root: Path) -> List[Path]:
    """Directories under ``cache_root`` that are complete conda envs.

    Matches any directory name, not just ``env-*``: Nextflow names an env
    from the environment.yml's ``name:`` key when one is declared (four
    nanometanf local modules do), so an ``env-`` filter under-counts.
    """
    if not cache_root.is_dir():
        return []
    return [
        d
        for d in sorted(cache_root.iterdir())
        if d.is_dir() and is_complete_conda_env(d)
    ]


def prune_incomplete_env_dirs(cache_root: Path) -> List[str]:
    """Remove env directories that fail the completeness predicate.

    Returns the removed directory names. Non-directory entries and the
    cache's own bookkeeping files are left alone.
    """
    import shutil

    removed: List[str] = []
    if not cache_root.is_dir():
        return removed
    for d in sorted(cache_root.iterdir()):
        if not d.is_dir() or d.is_symlink():
            continue
        if not is_complete_conda_env(d):
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    return removed


def _patch_binary(data: bytes, old: bytes, new: bytes) -> Optional[bytes]:
    """Rewrite ``old`` -> ``new`` inside NUL-terminated strings, preserving
    total length by NUL-padding. Returns None when an occurrence cannot be
    patched safely (no terminating NUL, or no room)."""
    if len(new) > len(old):
        return None
    out = bytearray(data)
    idx = 0
    while True:
        i = out.find(old, idx)
        if i == -1:
            break
        end = out.find(b"\x00", i)
        if end == -1:
            return None
        segment = bytes(out[i:end])
        replaced = segment.replace(old, new)
        if len(replaced) > end - i:
            return None
        out[i:end] = replaced.ljust(end - i, b"\x00")
        idx = i + 1
    return bytes(out)


def relocate_conda_cache(cache_dir: Path, old_prefix: str) -> Dict[str, Any]:
    """Rewrite every embedded ``old_prefix`` under ``cache_dir`` to the
    cache's current location.

    Text files (no NUL byte) get a plain byte replace; binaries get the
    length-preserving NUL-padded rewrite; symlinks whose target starts with
    the old prefix are retargeted. Returns a stats dict with a ``failures``
    list of relative paths that could not be patched (the caller should
    surface those -- the affected env is not usable).
    """
    stats: Dict[str, Any] = {
        "files_scanned": 0,
        "text_rewritten": 0,
        "binary_patched": 0,
        "symlinks_retargeted": 0,
        "failures": [],
    }
    new_prefix = str(cache_dir)
    if not old_prefix or old_prefix == new_prefix:
        return stats
    old_b = old_prefix.encode()
    new_b = new_prefix.encode()

    for path in sorted(cache_dir.rglob("*")):
        if path.is_symlink():
            try:
                target = os.readlink(str(path))
            except OSError:
                continue
            if target.startswith(old_prefix):
                new_target = new_prefix + target[len(old_prefix):]
                try:
                    path.unlink()
                    os.symlink(new_target, str(path))
                    stats["symlinks_retargeted"] += 1
                except OSError as exc:
                    logger.warning(
                        "Could not retarget symlink %s: %s", path, exc
                    )
                    stats["failures"].append(
                        str(path.relative_to(cache_dir))
                    )
            continue
        if not path.is_file():
            continue
        stats["files_scanned"] += 1
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("Could not read %s during relocation: %s", path, exc)
            stats["failures"].append(str(path.relative_to(cache_dir)))
            continue
        if old_b not in data:
            continue
        if b"\x00" in data:
            patched = _patch_binary(data, old_b, new_b)
            if patched is None:
                stats["failures"].append(str(path.relative_to(cache_dir)))
                continue
            _rewrite_in_place(path, patched)
            stats["binary_patched"] += 1
        else:
            _rewrite_in_place(path, data.replace(old_b, new_b))
            stats["text_rewritten"] += 1
    return stats


def make_symlinks_relative(root: Path) -> Dict[str, Any]:
    """Convert absolute symlinks under ``root`` whose target lies inside
    ``root`` into relative links; drop links escaping the tree.

    Run BEFORE the cache directory is renamed into its bundle name --
    afterwards the absolute targets no longer resolve. Absolute link
    targets also make tarfile's 'data' extraction filter abort the whole
    import (AbsoluteLinkError), so none may survive into the tar.
    """
    result: Dict[str, Any] = {"converted": 0, "dropped": []}
    root_str = str(root)
    for path in list(root.rglob("*")):
        if not path.is_symlink():
            continue
        try:
            target = os.readlink(str(path))
        except OSError:
            continue
        if not os.path.isabs(target):
            continue
        if target == root_str or target.startswith(root_str + os.sep):
            rel = os.path.relpath(target, start=str(path.parent))
            path.unlink()
            os.symlink(rel, str(path))
            result["converted"] += 1
        else:
            path.unlink()
            result["dropped"].append(str(path.relative_to(root)))
    return result


def _rewrite_in_place(path: Path, data: bytes) -> None:
    """Overwrite file contents keeping mode; opens the existing inode so
    permissions and (broken-by-copy) hardlink groups behave predictably."""
    mode = path.stat().st_mode
    with open(path, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)
