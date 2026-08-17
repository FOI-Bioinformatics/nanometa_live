"""Every built-in watchlist entry must carry its own action_required text.

2026-08-17 audit, finding W5: all 28 who_drinking_water entries shipped
without action_required, so the pathogen report rendered the generic
"Follow laboratory biosafety protocols" fallback for every waterborne
detection -- indistinguishable from an entry whose guidance was actually
considered. The texts were filled in per organism; this guard keeps any
future built-in entry from shipping without one.

Scope is deliberately the shipped top-level lists only: files under
examples/ are templates (see examples/README.md), and operator uploads
are free to omit the field.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

BUILTIN_DIR = (
    Path(__file__).resolve().parents[1]
    / "nanometa_live" / "core" / "config" / "data" / "watchlists"
)

BUILTIN_FILES = sorted(BUILTIN_DIR.glob("*.yaml"))


def test_builtin_watchlists_were_found():
    assert len(BUILTIN_FILES) >= 9, (
        f"expected the shipped watchlists under {BUILTIN_DIR}; a guard that "
        f"scans nothing guards nothing"
    )


@pytest.mark.parametrize(
    "path", BUILTIN_FILES, ids=[p.stem for p in BUILTIN_FILES]
)
def test_every_entry_has_action_required(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = [
        p.get("name", f"entry {i + 1}")
        for i, p in enumerate(data.get("pathogens", []))
        if not str(p.get("action_required", "")).strip()
    ]
    assert not missing, (
        f"{path.name}: entries without action_required render the generic "
        f"biosafety fallback in the pathogen report: {missing}"
    )
