"""Regression test for audit item #6 (docs/audit/threading-2026-05-10.md):
``update_readiness_indicator`` must run in a DiskcacheManager worker.

The readiness check shells out to ``docker info`` and ``nextflow -version``
(15-20 s total on a cold path) and was holding the Werkzeug request thread
for that entire duration on the first poll after every app-config change.
Backgrounding the callback isolates the subprocess wait from the main
process. The 60 s in-memory TTL cache no longer crosses the worker
boundary, but the request thread stays responsive -- which is what the
audit asked for.
"""

from __future__ import annotations

import re
from pathlib import Path


CALLBACKS_SRC = Path("nanometa_live/app/callbacks.py").read_text()


def test_import_present():
    assert (
        "from nanometa_live.app.app import background_callback_manager"
        in CALLBACKS_SRC
    )


def test_update_readiness_indicator_is_background():
    decorator_pattern = re.compile(
        r"@app\.callback\((?P<dec>.*?)\)\s*\n\s*def update_readiness_indicator\(",
        re.DOTALL,
    )
    match = decorator_pattern.search(CALLBACKS_SRC)
    assert match, "update_readiness_indicator decorator not found"
    dec = match.group("dec")
    assert "background=True" in dec, (
        "update_readiness_indicator must be decorated background=True "
        "(audit item #6); the subprocess probes (docker info, nextflow "
        "-version) hold the Werkzeug request thread for up to ~15 s "
        "without it."
    )
    assert "manager=background_callback_manager" in dec
