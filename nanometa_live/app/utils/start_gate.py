"""The server-side readiness gate on Start Analysis.

The readiness checklist looked like a gate and was not one (field audit
2026-10-28, H5). The header's Start button was disabled in the browser while
``readiness-state.ready`` was False, but a disabled attribute is a courtesy,
not a check: the Preparation tab's own Start button proxied a click into the
same callback with no gate at all, a stale Store let a click through, and
``start_or_prompt_stop`` never read the readiness Store. Two comments
claimed otherwise (the proxy "triggers exactly the same readiness check";
the disk-space floor "gates Start"), and the operator saw "Not Ready, 10/25
checks passed" above an enabled Start Analysis button.

``readiness_blocks_start`` is the one decision, kept pure so every launch
path (header, Preparation tab, the collision modal's Archive and Continue)
asks the same question. It names the failing CRITICAL rows so the refusal
tells the operator what to fix. The override exists for the operator who
knows their machine: ``start_without_readiness: true`` in the config, or
``NANOMETA_ALLOW_NOT_READY=1`` in the environment that launched the app.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

START_WITHOUT_READINESS_KEY = "start_without_readiness"
START_WITHOUT_READINESS_ENV = "NANOMETA_ALLOW_NOT_READY"

NOT_CHECKED_MESSAGE = (
    "Readiness has not been checked yet. Open Watchlist & Preparation and "
    "click Check Everything, then start."
)


def readiness_overridden(config: Optional[Dict[str, Any]]) -> bool:
    """True when the operator has explicitly chosen to start regardless."""
    if config and config.get(START_WITHOUT_READINESS_KEY):
        return True
    return os.environ.get(START_WITHOUT_READINESS_ENV) == "1"


def readiness_blocks_start(
    readiness: Optional[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """The reasons a launch is refused, or an empty list to proceed.

    Each reason is ``"<check name>: <message>"`` for a CRITICAL check that
    did not pass, as the readiness Store serialises it. A Store that has
    never been computed, or whose computation errored, refuses with
    ``NOT_CHECKED_MESSAGE``: a run that has not been checked is not a run
    that passed.
    """
    if readiness_overridden(config):
        return []
    if not readiness:
        return [NOT_CHECKED_MESSAGE]
    checks = readiness.get("checks") or []
    if not checks:
        error = readiness.get("error")
        return [f"Readiness check failed: {error}" if error else NOT_CHECKED_MESSAGE]
    return [
        f"{c.get('name', 'check')}: {c.get('message', '')}".rstrip(": ")
        for c in checks
        if c.get("severity") == "critical" and not c.get("passed")
    ]


def refusal_message(reasons: List[str]) -> str:
    """The toast body for a refused launch."""
    lines = "\n".join(f"- {r}" for r in reasons)
    return (
        "The readiness checklist has failures that would stop the run. "
        "Fix them in Watchlist & Preparation, then start:\n" + lines +
        "\n\nTo start anyway, set start_without_readiness: true in the "
        "configuration."
    )
