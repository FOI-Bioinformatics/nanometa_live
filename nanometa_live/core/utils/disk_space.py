"""Free space on a volume, and the floor below which a run is at risk.

One definition for the readiness check (before a run) and the backend's
per-tick poll (during one). ENOSPC inside chopper, kraken2 or blast exits
1, which nanometanf's error isolation absorbs, so a run on a full disk ends
COMPLETE over truncated reports with nothing on screen saying why (field
audit 2026-10-28, M3).
"""

from __future__ import annotations

import os
import shutil
from typing import Optional

#: Below this many GB free on the results volume, a run is refused by the
#: readiness checklist and a running one is flagged in the header and the
#: verdict subtitle.
LOW_DISK_FLOOR_GB = 5


def free_gb(path: Optional[str]) -> Optional[float]:
    """Free space in GB on the volume holding ``path`` (or its nearest
    existing parent), None when it cannot be determined."""
    if not path:
        return None
    check = os.path.abspath(path)
    while not os.path.exists(check):
        parent = os.path.dirname(check)
        if parent == check:
            return None
        check = parent
    try:
        return shutil.disk_usage(check).free / (1024 ** 3)
    except OSError:
        return None


def low_disk_message(free: Optional[float], floor_gb: float = LOW_DISK_FLOOR_GB) -> Optional[str]:
    """The clause the header and verdict carry, or None when space is fine."""
    if free is None or free >= floor_gb:
        return None
    return (f"only {free:.1f} GB free on the results volume - new output may "
            "be truncated or lost")
