"""A custom watchlist entry with no alert_threshold screens at its threat
level's default, not a flat 10.

``check_for_dangerous_pathogens`` is the dashboard-alert path for entries that
live only in the operator's custom watchlist (not the built-in database). It
read ``alert_threshold`` with a hardcoded fallback of 10, so a custom
*critical* entry that named no threshold waited for 10 reads where the same
entry loaded as a WatchlistEntry alerts at 5 -- the bug the single-default
work (finding 33, 2026-11-06) closed everywhere else. This pins the custom
path to the one table.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.config.pathogen_loader import (
    ThreatLevel, default_alert_threshold,
)
from nanometa_live.core.utils import pathogen_database as pdb
from nanometa_live.core.utils.pathogen_database import check_for_dangerous_pathogens

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_memo():
    # The alert check memoizes on (organisms, watchlist); each case here uses
    # a distinct organism/threshold pair, but clear so order never matters.
    pdb._dangerous_check_memo.clear()
    yield
    pdb._dangerous_check_memo.clear()


def _custom(threat):
    # A custom entry (taxid absent from the built-in database) stating no
    # alert_threshold. A high custom taxid keeps it out of the real DB.
    return [{"taxid": 9_000_001, "name": "Madeupium horribilis",
             "threat_level": threat, "enabled": True}]


def _detected(reads):
    return [{"taxid": 9_000_001, "name": "Madeupium horribilis",
             "reads": reads, "abundance": 1.0}]


class TestCustomThresholdFollowsThreatLevel:
    @pytest.mark.parametrize("threat", ["critical", "high", "moderate", "low"])
    def test_alert_fires_at_the_threat_level_default(self, threat):
        floor = default_alert_threshold(ThreatLevel(threat))
        at = check_for_dangerous_pathogens(_detected(floor), _custom(threat))
        assert len(at) == 1, (
            f"a custom {threat} entry should alert at its default of {floor}")

    def test_critical_alerts_below_the_old_flat_ten(self):
        # critical defaults to 5; at 6 reads it must alert, where a flat 10
        # would have stayed silent.
        assert default_alert_threshold(ThreatLevel.CRITICAL) < 10
        at = check_for_dangerous_pathogens(_detected(6), _custom("critical"))
        assert len(at) == 1, "a critical custom entry at 6 reads must alert"

    def test_an_explicit_threshold_still_wins(self):
        custom = _custom("critical")
        custom[0]["alert_threshold"] = 100
        assert check_for_dangerous_pathogens(_detected(50), custom) == []
        assert len(check_for_dangerous_pathogens(_detected(100), custom)) == 1
