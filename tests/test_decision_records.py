"""Every decision record has the four sections and is listed in the index.

The records replace reading CLAUDE.md end to end for a new maintainer; a
record missing its Evidence section, or absent from the index, is one a
reader cannot find or cannot verify.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DECISIONS = Path(__file__).resolve().parents[1] / "docs" / "decisions"
REQUIRED = ("## Context", "## Decision", "## Consequences", "## Evidence")


def _records():
    return sorted(p for p in DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_there_are_records():
    assert len(_records()) >= 10


@pytest.mark.parametrize("path", _records(), ids=lambda p: p.stem)
def test_record_has_the_four_sections_in_order(path):
    text = path.read_text()
    positions = [text.find(h) for h in REQUIRED]
    assert all(p >= 0 for p in positions), f"{path.name} lacks {[h for h, p in zip(REQUIRED, positions) if p < 0]}"
    assert positions == sorted(positions), f"{path.name}: sections out of order"
    assert re.match(r"# \d{4}\. ", text), f"{path.name} must start with '# NNNN. Title'"
    assert "**Status:**" in text


def test_index_lists_every_record():
    index = (DECISIONS / "README.md").read_text()
    for path in _records():
        assert f"({path.name})" in index, f"{path.name} not linked from docs/decisions/README.md"


@pytest.mark.parametrize("path", _records(), ids=lambda p: p.stem)
def test_evidence_names_an_existing_test_file(path):
    root = DECISIONS.parents[1]
    evidence = path.read_text().split("## Evidence", 1)[1]
    named = re.findall(r"`(tests/[\w/.-]+\.py)`", evidence)
    assert named, f"{path.name}: Evidence must name at least one tests/ file"
    for rel in named:
        assert (root / rel).is_file(), f"{path.name}: {rel} does not exist"
