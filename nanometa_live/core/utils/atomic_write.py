"""Atomic file writes for shared state under ``data_dir``.

When two ``nanometa-live`` processes run on the same machine and share
a ``data_dir``, both may write to the same JSON or YAML state file
(genome metadata, watchlist toggle state, last-session). A naive
``open(path, "w")`` truncates the file before writing; if the second
process opens it while the first is mid-write, the second reader sees
either a half-written file or, on a crash, an empty one.

The standard fix is write-temp-then-rename: write to a sibling temp
file, fsync, then ``os.replace`` onto the target. ``os.replace`` is
atomic on POSIX (the inode swap is a single VFS operation) and on
Windows (Python wraps ReplaceFileW). Readers always observe either
the old or the new file, never a partial write.

This module also exposes a fcntl-based context manager for the rare
read-modify-write case where the operator wants stronger consistency
than rename-on-write provides.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator


def atomic_write_text(path: Path | str, text: str) -> None:
    """Write *text* to *path* atomically.

    Creates a temp file in the same directory (so ``os.replace`` does
    not cross filesystems), writes the contents, fsyncs, then renames
    onto the target. On any error the temp file is removed.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def atomic_write_json(path: Path | str, data: Any, *, indent: int = 2) -> None:
    """Serialise *data* as JSON and atomically write to *path*."""
    atomic_write_text(path, json.dumps(data, indent=indent))


@contextlib.contextmanager
def file_lock(path: Path | str) -> Iterator[None]:
    """Acquire a fcntl exclusive lock on *path* for the duration of the block.

    Use when read-modify-write must be serialised across processes
    (e.g. the genome metadata file when two preparation runs may be
    downloading different taxids). Released automatically on
    block exit.

    On non-POSIX platforms this is a best-effort no-op (the typical
    deployment is Linux/macOS; the Windows visualisation-only mode
    does not run concurrent state writers).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lockfile = target.with_suffix(target.suffix + ".lock")
    try:
        import fcntl  # noqa: PLC0415  POSIX-only
    except ImportError:
        yield
        return
    fd = os.open(str(lockfile), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
