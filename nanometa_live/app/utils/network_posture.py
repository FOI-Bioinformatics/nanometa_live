"""What binding a given host exposes.

The dashboard has no authentication. Bound to a loopback address it is
reachable only from the machine it runs on, which is the posture the design
assumes (a field laptop, one operator). Bound to anything else it is a
control surface -- Start, Stop, configuration -- for everyone who can reach
the port. The warning states that at the moment the operator chooses it.
"""

from __future__ import annotations

from typing import Optional

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def exposure_warning(host: str) -> Optional[str]:
    """Return the warning text for a reachable ``host``, or None for loopback."""
    if (host or "").strip().lower() in LOOPBACK_HOSTS:
        return None
    return (
        f"Nanometa Live is listening on {host}. The dashboard has no "
        "authentication: anyone who can reach this port can start and stop "
        "pipeline runs, change the configuration and read every result. Use "
        "this only on a trusted network, or place an authenticating reverse "
        "proxy in front of it. Bind to 127.0.0.1 (the default) for use on "
        "this machine alone."
    )
