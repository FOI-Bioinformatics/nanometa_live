"""Regression test for audit item #6 (docs/audit/threading-2026-05-10.md):
``update_readiness_state`` must run in a DiskcacheManager worker.

The readiness check shells out to ``docker info`` and ``nextflow -version``
(15-20 s total on a cold path) and was holding the Werkzeug request thread
for that entire duration on the first poll after every app-config change.
Backgrounding the callback isolates the subprocess wait from the main
process. The request thread stays responsive -- which is what the audit
asked for. (Renamed from ``update_readiness_indicator`` to
``update_readiness_state`` when it became the single writer of the shared
readiness-state Store; the header pill and Preparation checklist are now pure
renderers of that Store.)
"""

from __future__ import annotations

import re
from pathlib import Path


# Callbacks were split from a single module into a callbacks/ package; read
# every submodule so these static assertions are agnostic to which submodule
# a given callback now lives in.
CALLBACKS_SRC = "\n".join(
    p.read_text() for p in sorted(Path("nanometa_live/app/callbacks").glob("*.py"))
)


def test_import_present():
    assert (
        "from nanometa_live.app.app import background_callback_manager"
        in CALLBACKS_SRC
    )


def test_update_readiness_state_is_background():
    decorator_pattern = re.compile(
        r"@app\.callback\((?P<dec>.*?)\)\s*\n\s*def update_readiness_state\(",
        re.DOTALL,
    )
    match = decorator_pattern.search(CALLBACKS_SRC)
    assert match, "update_readiness_state decorator not found"
    dec = match.group("dec")
    assert "background=True" in dec, (
        "update_readiness_state must be decorated background=True "
        "(audit item #6); the subprocess probes (docker info, nextflow "
        "-version) hold the Werkzeug request thread for up to ~15 s "
        "without it."
    )
    assert "manager=background_callback_manager" in dec
