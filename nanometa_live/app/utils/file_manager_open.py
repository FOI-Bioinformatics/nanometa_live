"""Open a path in the operator's native file manager.

Used by the Storage Locations panel in the Configuration tab to give
operators a one-click bridge from a documented path to the Finder /
Explorer / file-manager window where they can inspect the contents,
back up data, or copy a genome cache between machines.

Calls the platform-native handler via subprocess. We never elevate
privileges and we never fall back to opening the file's contents (so
clicking the row for kraken2_databases.local.yaml opens the parent
directory, not a text editor). All errors are returned as a string
rather than raised so the caller can surface them as a toast without
dealing with exception types.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional


def open_in_file_manager(path: str) -> Optional[str]:
    """Open *path* (or its parent if it is a regular file) in the
    OS-native file manager. Returns ``None`` on success or a short
    human-readable error message on failure.

    The Dash app runs locally, so subprocess.Popen against the user's
    own ``open``/``xdg-open``/``explorer`` is the simplest reliable
    bridge. We do NOT shell out to ``open <file>`` for a regular file
    because that would launch the registered viewer for the file
    type (text editor for YAML, etc.); the contract here is "show me
    where this lives", which means a directory view.
    """
    if not path:
        return "Empty path"

    target = path
    if os.path.isfile(target):
        target = os.path.dirname(target) or target
    if not os.path.exists(target):
        return f"Path does not exist: {target}"

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", target])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", target])
        else:
            return f"Unsupported platform: {sys.platform}"
    except FileNotFoundError as exc:
        return f"File-manager helper not found: {exc}"
    except OSError as exc:
        return f"Could not open {target}: {exc}"

    return None
