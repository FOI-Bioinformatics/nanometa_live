#!/usr/bin/env python3
"""Flag end-of-life core dependencies (the numpy-1.26 slip, caught early).

For a small curated set of load-bearing packages, look up the installed
version's release cycle on endoflife.date and report any series that is past
(or near) end of life. Intended to run on a quarterly CI schedule so an EOL
series surfaces as a red build long before it becomes a security problem.

Design choices:
- Standard library only (urllib); no extra dependency just to run the check.
- Network/lookup failures are advisory: they print a warning and exit 0 so a
  transient endoflife.date outage never fails the scheduled run.
- A genuinely EOL series exits 1, so the scheduled job goes red and notifies.

Usage:
    python scripts/check_dependency_eol.py
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.error
import urllib.request
from importlib import metadata

# Distribution name -> endoflife.date product slug. Keep this list short and
# load-bearing; it is a tripwire, not an inventory, and every entry must be a
# product endoflife.date actually tracks (numpy is; pandas/dash/plotly are
# not, as of 2026-06). numpy is here because its 1.26 EOL is what prompted the
# check. The Python floor is already guarded by setup.py + the CI matrix.
MONITORED = {
    "numpy": "numpy",
}

# Warn this many days ahead of a series' EOL date.
NEAR_EOL_DAYS = 120
API = "https://endoflife.date/api/{product}.json"
TIMEOUT = 10


def _installed_version(dist: str) -> str | None:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def _fetch_cycles(product: str):
    url = API.format(product=product)
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:  # noqa: S310 (https only)
        return json.loads(resp.read().decode("utf-8"))


def _match_cycle(version: str, cycles: list[dict]) -> dict | None:
    """Pick the cycle whose ``cycle`` string best matches the version."""
    best = None
    best_len = -1
    for entry in cycles:
        cyc = str(entry.get("cycle", ""))
        if version == cyc or version.startswith(cyc + "."):
            if len(cyc) > best_len:
                best, best_len = entry, len(cyc)
    return best


def _eol_state(entry: dict, today: datetime.date):
    """Return ('eol'|'near'|'ok', detail) for a cycle entry."""
    eol = entry.get("eol")
    if eol is True:
        return "eol", "marked end-of-life"
    if eol is False or eol is None:
        return "ok", "supported"
    try:
        eol_date = datetime.date.fromisoformat(str(eol))
    except ValueError:
        return "ok", f"eol={eol!r}"
    if eol_date <= today:
        return "eol", f"end-of-life since {eol_date.isoformat()}"
    if (eol_date - today).days <= NEAR_EOL_DAYS:
        return "near", f"end-of-life on {eol_date.isoformat()}"
    return "ok", f"supported until {eol_date.isoformat()}"


def main() -> int:
    today = datetime.date.today()
    had_eol = False
    print(f"Dependency EOL check ({today.isoformat()}):")

    for dist, product in sorted(MONITORED.items()):
        version = _installed_version(dist)
        if version is None:
            print(f"  ? {dist}: not installed, skipping")
            continue
        try:
            cycles = _fetch_cycles(product)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  ~ {dist} {version}: lookup failed ({exc}); skipping (advisory)")
            continue

        entry = _match_cycle(version, cycles)
        if entry is None:
            print(f"  ~ {dist} {version}: no matching release cycle on endoflife.date")
            continue

        state, detail = _eol_state(entry, today)
        marker = {"eol": "X", "near": "!", "ok": "."}[state]
        print(f"  {marker} {dist} {version} (cycle {entry.get('cycle')}): {detail}")
        if state == "eol":
            had_eol = True

    if had_eol:
        print()
        print("FAIL: a monitored dependency series is end-of-life. Plan an upgrade "
              "and bump its floor in requirements.txt.")
        return 1

    print("OK: no monitored dependency series is end-of-life.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
