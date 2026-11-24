"""Threat badges must render in their level's colour.

``threat_badge`` set the level colour as an inline background, but
dbc.Badge's default ``color="secondary"`` adds Bootstrap's ``bg-secondary``,
whose background is ``!important`` and wins over the inline style: every
threat badge rendered grey, and Moderate's dark-brown text on grey was
barely legible (2026-11-23 live walk). The colour goes in ``color``.
"""

import pytest

from nanometa_live.app.utils.threat_display import threat_badge
from nanometa_live.core.config.threat_levels import threat_level_info

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("level", ["critical", "high", "moderate", "low"])
def test_badge_carries_its_level_colour(level):
    badge = threat_badge(level)
    assert badge.color == threat_level_info(level)["hex"]
