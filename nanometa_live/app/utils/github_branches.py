"""Fetch nanometanf branch list from GitHub for the Pipeline Source dropdown.

The Configuration tab's pipeline-branch-input was previously hardcoded to
``master``/``dev``. The live branch list at
``github.com/FOI-Bioinformatics/nanometanf`` evolves -- branches get
renamed, feature branches come and go -- so the static dropdown drifted
out of sync with reality. This helper hits the GitHub API once per
process (cached in module state) and returns the live list, with a
documented fallback when the call fails (e.g. offline deployment, API
rate limit, network drop).

Usage:
    from nanometa_live.app.utils.github_branches import (
        fetch_nanometanf_branches,
    )
    branches = fetch_nanometanf_branches()  # list[str]

The fallback is intentionally conservative: it includes ``dev`` (the
current default working branch) and ``main`` (the GitHub default for
new repos) so the operator has at least one selectable value even
when the network is down.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import List, Optional

logger = logging.getLogger(__name__)

NANOMETANF_BRANCHES_URL = (
    "https://api.github.com/repos/FOI-Bioinformatics/nanometanf/branches"
)
FETCH_TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 600  # 10 minutes
FALLBACK_BRANCHES = ["dev", "main"]
PRIORITY_BRANCHES = ("main", "master", "dev")  # sort to top in this order

_cache: dict = {"timestamp": 0.0, "branches": None}


def _sort_branches(branches: List[str]) -> List[str]:
    """Order branches so the operator's most-likely choices land at the top.

    Priority list first (main, master, dev in that order), then everything
    else alphabetically.
    """
    head = [b for b in PRIORITY_BRANCHES if b in branches]
    tail = sorted(b for b in branches if b not in PRIORITY_BRANCHES)
    return head + tail


def fetch_nanometanf_branches(
    *,
    use_cache: bool = True,
    offline_mode: bool = False,
) -> List[str]:
    """Return the current list of branches in the nanometanf repo.

    Args:
        use_cache: If True (default), serve from the in-process cache when
            it has not expired. Pass False to force a fresh fetch.
        offline_mode: If True, skip the network call entirely and return
            the fallback list. Wire this up from
            ``config['offline_mode']`` so cached field deployments do
            not hit the network at all.

    Returns:
        List of branch name strings in priority order. Always non-empty:
        on any error or in offline mode the fallback list is returned.
    """
    if offline_mode:
        return list(FALLBACK_BRANCHES)

    now = time.time()
    if (
        use_cache
        and _cache["branches"] is not None
        and now - _cache["timestamp"] < CACHE_TTL_SECONDS
    ):
        return list(_cache["branches"])

    try:
        # Use ``per_page=100`` so we get every branch in a single
        # request without paging. nanometanf has well under 100
        # branches in practice.
        url = f"{NANOMETANF_BRANCHES_URL}?per_page=100"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "nanometa-live",
            },
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            payload = json.load(resp)
        if not isinstance(payload, list):
            raise ValueError(f"unexpected payload type: {type(payload)}")
        names = [b["name"] for b in payload if isinstance(b, dict) and "name" in b]
        if not names:
            raise ValueError("empty branch list")
        result = _sort_branches(names)
        _cache["branches"] = result
        _cache["timestamp"] = now
        logger.info(f"Fetched {len(result)} nanometanf branches from GitHub")
        return list(result)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            ValueError, TimeoutError, OSError) as e:
        logger.warning(
            f"Could not fetch nanometanf branch list ({e!r}); "
            f"falling back to {FALLBACK_BRANCHES}"
        )
        return list(FALLBACK_BRANCHES)


def reset_cache() -> None:
    """Clear the in-process branch cache. Useful for tests."""
    _cache["timestamp"] = 0.0
    _cache["branches"] = None
