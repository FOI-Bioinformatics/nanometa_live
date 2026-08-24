"""The exported report must not call an absence a negative result.

``select_verdict`` gained an INSUFFICIENT_READS state on 2026-07-29, alongside
NOT_SCREENED, because an absence measured over almost no reads is not evidence
of absence. Only NOT_SCREENED was ported to the report template. So a run of a
single read, with a full watchlist loaded, rendered:

    NO WATCHED ORGANISMS DETECTED - 35 organisms screened

on a green banner, in the artifact that leaves the building.

The template's own comment explains why that matters more here than on the
dashboard: the report "is the artifact handed to someone else, and it outlives
the session that produced it". A green all-clear over one read is the same
clinical claim the dashboard fix exists to prevent, in a document someone may
act on days later without the session that produced it.

Precedence follows the dashboard exactly: a detection always outranks shallow
depth, and unknown depth is never treated as zero.
"""

from __future__ import annotations

import pytest

from nanometa_live.app.tabs.dashboard_helpers import DEFAULT_LOW_READ_FLOOR

pytestmark = pytest.mark.unit


def _render(watched_results, total_reads, low_read_floor=DEFAULT_LOW_READ_FLOOR):
    """Render just the decision banner from the real template."""
    import pathlib

    import jinja2

    template_dir = (
        pathlib.Path(__import__(
            "nanometa_live.core.export.report_generator",
            fromlist=["report_generator"],
        ).__file__).parent / "templates"
    )
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        autoescape=True,
    )
    source = (template_dir / "report.html").read_text()
    start = source.index("<!-- DECISION BANNER -->")
    # Matching endif (the banner divs carry inline {% if %} clauses now).
    import re as _re
    depth = 0
    end = None
    for m in _re.finditer(r"{%-?\s*(if|endif)\b.*?%}", source[start:]):
        if m.group(1) == "if":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = start + m.end()
                break
    assert end is not None
    banner = env.from_string(source[start:end])
    return banner.render(data={
        "watched_results": watched_results,
        "total_reads": total_reads,
        "low_read_floor": low_read_floor,
    })


CLEAN = [
    {"name": "Bacillus anthracis", "detected": False, "threat_level": "critical"},
    {"name": "Yersinia pestis", "detected": False, "threat_level": "critical"},
]
DETECTED = [
    {"name": "Bacillus anthracis", "detected": True, "threat_level": "critical"},
]


class TestShallowDepthIsNotAllClear:
    def test_a_single_read_does_not_render_a_green_all_clear(self):
        html = _render(CLEAN, total_reads=1)

        assert "banner-safe" not in html, (
            "a run of one read rendered the green all-clear banner; an "
            "absence measured over one read is not evidence of absence"
        )
        assert "NO WATCHED ORGANISMS DETECTED" not in html

    def test_it_says_why_rather_than_just_withholding_the_verdict(self):
        html = _render(CLEAN, total_reads=1)

        assert "INSUFFICIENT" in html.upper(), (
            "the banner must name the reason; a blank or merely-amber banner "
            "leaves the reader to guess whether screening happened"
        )
        assert "1" in html, "the actual read count belongs in the message"

    @pytest.mark.parametrize("depth", [0, 1, DEFAULT_LOW_READ_FLOOR - 1])
    def test_every_depth_below_the_floor_is_gated(self, depth):
        assert "banner-safe" not in _render(CLEAN, total_reads=depth)

    def test_at_and_above_the_floor_a_genuine_all_clear_still_renders(self):
        """The gate must not swallow real negative results."""
        html = _render(CLEAN, total_reads=DEFAULT_LOW_READ_FLOOR)

        assert "banner-safe" in html
        assert "NO WATCHED ORGANISMS DETECTED" in html


class TestPrecedenceMatchesTheDashboard:
    def test_a_detection_outranks_shallow_depth(self):
        """Never suppress a detection because the run was shallow."""
        html = _render(DETECTED, total_reads=1)

        assert "ACTION REQUIRED" in html, (
            "a critical organism was detected and the banner reported depth "
            "instead; a detection always wins"
        )

    def test_an_empty_watchlist_still_reports_not_screened(self):
        """NOT_SCREENED outranks depth: nothing was checked at all."""
        html = _render([], total_reads=1)

        assert "NOT SCREENED" in html
        assert "INSUFFICIENT" not in html.upper()

    def test_unknown_depth_is_not_treated_as_zero(self):
        """None means "not determined" and must preserve prior behaviour.

        Treating unknown as zero would turn every caller that cannot compute
        depth into a false INSUFFICIENT READS.
        """
        html = _render(CLEAN, total_reads=None)

        assert "banner-safe" in html
