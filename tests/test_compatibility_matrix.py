"""The README states which nanometanf this GUI release pairs with.

The two are released in lock-step (0.18.0 sends parameters only nanometanf
1.10.0 declares) and the launcher refuses an older checkout by version
(pipeline_compat). The table an operator reads must name the same floor
the code enforces, and the prerequisites must not contradict pyproject.
"""

from pathlib import Path

import pytest

import nanometa_live
from nanometa_live.core.workflow.pipeline_compat import NANOMETANF_MIN_VERSION

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def _current_minor():
    major, minor, *_ = nanometa_live.__version__.split(".")
    return f"{major}.{minor}"


def test_readme_matrix_names_the_current_minor_and_the_floor():
    text = (ROOT / "README.md").read_text()
    assert "## Compatibility" in text
    section = text.split("## Compatibility", 1)[1].split("\n## ", 1)[0]
    row = [ln for ln in section.splitlines() if ln.startswith(f"| {_current_minor()}.x")]
    assert row, f"no matrix row for {_current_minor()}.x"
    assert NANOMETANF_MIN_VERSION in row[0]


def test_user_guide_prerequisites_match_pyproject():
    text = (ROOT / "docs" / "user-guide.md").read_text()
    assert "Python 3.9" not in text
    assert "Python 3.11" in text
    assert "26.04" in text
