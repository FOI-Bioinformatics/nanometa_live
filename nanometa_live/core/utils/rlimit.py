"""File-descriptor soft-limit helper.

Long-running Dash GUIs under DiskcacheManager + Werkzeug + heavy
fingerprint walking blow through Linux's default ``ulimit -n``
(typically 1024 or 4096) within a few hours of continuous polling.
The symptom is a cascade of ``OSError: [Errno 24] Too many open
files`` in werkzeug's selector, psutil's ``/proc`` scan, and
importlib's module loader.

The standard production mitigation is to raise the soft fd limit
toward the hard limit at process startup. The hard limit is set by
the OS / systemd / pam_limits; the soft limit is just an advisory
ceiling the running process inherits and is free to raise.

This helper does that lift once on application start. Operators on a
kernel-restricted host can still set the hard limit via
``/etc/security/limits.conf`` or a systemd ``LimitNOFILE=`` directive
before launching nanometa-live; this helper raises the soft limit to
whatever the hard limit allows.

Non-Linux platforms (macOS, Windows) are no-ops -- the ``resource``
module is Linux/Unix only, and macOS dev laptops do not typically
hit the limit during local development.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


# Target soft limit if the hard limit allows it. 65536 covers the
# observed worst case (~30k fds during a fingerprint walk + a dozen
# background-callback workers each holding a hundred diskcache
# handles). Operators on a host with a higher hard limit will get
# raised to whatever the hard limit allows.
_TARGET_SOFT_LIMIT = 65536


def raise_fd_soft_limit(target: int = _TARGET_SOFT_LIMIT) -> tuple[int, int]:
    """Raise the soft fd limit toward the hard limit.

    Returns ``(soft_before, soft_after)`` so the caller can log the
    change. On platforms without the ``resource`` module (Windows)
    this is a no-op and returns ``(-1, -1)``.

    The function never raises -- a kernel that refuses the lift logs
    a warning and leaves the limit as the OS provided. The GUI will
    still start; it may just trip the fd ceiling under heavy load.
    """
    try:
        import resource
    except ImportError:
        # Windows -- no rlimit API. Treat as a no-op.
        return (-1, -1)

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (ValueError, OSError) as e:
        logger.warning("Could not read RLIMIT_NOFILE: %s", e)
        return (-1, -1)

    # Resolve the target: clamp to the hard limit. On macOS the hard
    # limit is often reported as a large but capped value
    # (e.g. 524288 or RLIM_INFINITY); the kernel may still refuse
    # values above ~10240 unless ``launchctl limit maxfiles`` was
    # bumped. Try the target first, then fall back to hard.
    desired = min(target, hard) if hard != resource.RLIM_INFINITY else target

    if soft >= desired:
        # Already at or above where we wanted; nothing to do.
        return (soft, soft)

    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (desired, hard))
        new_soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        return (soft, new_soft)
    except (ValueError, OSError) as e:
        # macOS-specific: setrlimit can return EINVAL when crossing
        # the ``launchctl limit maxfiles`` ceiling even though
        # getrlimit reports a higher hard limit. Try a smaller
        # intermediate value as a courtesy.
        for fallback in (10240, 4096, max(soft, 1024)):
            if fallback <= soft:
                break
            try:
                resource.setrlimit(
                    resource.RLIMIT_NOFILE, (fallback, hard)
                )
                new_soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
                logger.warning(
                    "RLIMIT_NOFILE: kernel refused %d, raised to %d "
                    "instead (was %d). Initial error: %s",
                    desired, new_soft, soft, e,
                )
                return (soft, new_soft)
            except (ValueError, OSError):
                continue

        logger.warning(
            "RLIMIT_NOFILE: could not raise soft limit from %d (hard=%d). "
            "Error: %s. The GUI may hit 'Too many open files' under load. "
            "Raise the hard limit in /etc/security/limits.conf or a "
            "systemd LimitNOFILE= directive and re-launch.",
            soft, hard, e,
        )
        return (soft, soft)
