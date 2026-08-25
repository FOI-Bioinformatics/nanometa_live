"""Registry of samples whose data is being served from a stale fallback.

The classification loader deliberately serves the last successfully parsed
frame when a report cannot be parsed (a transiently mid-write file heals on
the next poll, and a backwards-counting dashboard is worse than a briefly
frozen one). What it could not do before round 3 was SAY so: a permanently
corrupt report -- the signature of a full disk truncating writes -- kept
rendering live-looking numbers indefinitely, logged only at debug level.

This module is the honesty side of that trade. The loader records every
last-good fallback and every successful parse; the verdict banner asks
``stale_sample_count`` and appends "N samples serving stale data" once a
sample has been on fallback longer than a grace window (transient
mid-write misses never surface). Registered with the loader-cache reset so
a new run starts clean.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: A sample must be on last-good fallback for this long before it is called
#: stale -- roughly three poll intervals, so one mid-write miss never flags.
DEFAULT_GRACE_SECONDS = 30.0

#: Minimum spacing of the per-sample warning log, so a 10 s poll loop over a
#: permanently corrupt report does not flood the log.
_WARN_INTERVAL_SECONDS = 300.0

_lock = threading.Lock()
# (scope, sample) -> timestamp of the FIRST fallback in the current stretch.
_serving_since: Dict[Tuple[str, str], float] = {}
_last_warned: Dict[Tuple[str, str], float] = {}


@dataclass(frozen=True)
class StaleEntry:
    scope: str
    sample: str
    since: float


def _key(scope: str, sample: str) -> Tuple[str, str]:
    # realpath, not abspath: report discovery realpaths every file, so the
    # loader records under e.g. /private/tmp/... while the banner queries
    # the config's /tmp/... -- abspath does not resolve the symlink and
    # the flag was invisible to the query (live drill, 2026-08-24).
    return (os.path.realpath(scope), str(sample))


def record_parse_ok(scope: str, sample: str,
                    when: Optional[float] = None) -> None:
    """A parse succeeded: the sample is current again."""
    key = _key(scope, sample)
    with _lock:
        _serving_since.pop(key, None)
        _last_warned.pop(key, None)


def record_last_good_served(scope: str, sample: str,
                            when: Optional[float] = None) -> None:
    """A parse failed and the last-good fallback was served.

    Keeps the FIRST fallback timestamp of the stretch -- staleness is
    measured from when the data stopped updating, not from the latest
    retry. Emits a throttled warning so a permanently corrupt report is
    visible in the log without flooding it.
    """
    now = time.time() if when is None else when
    key = _key(scope, sample)
    with _lock:
        _serving_since.setdefault(key, now)
        last = _last_warned.get(key, 0.0)
        should_warn = (time.time() - last) >= _WARN_INTERVAL_SECONDS
        if should_warn:
            _last_warned[key] = time.time()
    if should_warn:
        logger.warning(
            "Serving last-good (stale) data for sample %r in %s -- the "
            "current report cannot be parsed. If this persists, check disk "
            "space and the pipeline log.", sample, scope,
        )


def stale_entries(scope: str,
                  grace_seconds: float = DEFAULT_GRACE_SECONDS
                  ) -> List[StaleEntry]:
    """Samples under ``scope`` on last-good fallback beyond the grace window."""
    scope_abs = os.path.realpath(scope) if scope else scope
    now = time.time()
    with _lock:
        return [
            StaleEntry(scope=s, sample=sample, since=since)
            for (s, sample), since in _serving_since.items()
            if s == scope_abs and (now - since) >= grace_seconds
        ]


def stale_sample_count(scope: str,
                       grace_seconds: float = DEFAULT_GRACE_SECONDS) -> int:
    """Number of distinct stale samples under ``scope``."""
    if not scope:
        return 0
    return len({e.sample for e in stale_entries(scope, grace_seconds)})


def clear(scope: Optional[str] = None) -> None:
    """Forget recorded state -- for run switches and tests."""
    with _lock:
        if scope is None:
            _serving_since.clear()
            _last_warned.clear()
            return
        scope_abs = os.path.realpath(scope)
        for d in (_serving_since, _last_warned):
            for key in [k for k in d if k[0] == scope_abs]:
                del d[key]
