"""One watchlist entry must get one alert threshold, whichever path loads it.

An entry with no explicit ``alert_threshold`` was defaulted twice, differently:

- ``WatchlistEntry.from_dict`` derived it from the threat level
  (critical 5 / high 10 / moderate 50 / low 100).
- ``WatchlistPathogenEntry`` and the loader's dict path used a flat 10.

Both paths load the same YAML at different moments -- roughly, the manager's
on the immediate post-upload load and the loader's on a later reload -- so an
entry's screening threshold changed depending on when it was read.

The direction is not uniform, which is what makes it worth fixing rather than
picking a winner by convenience:

- moderate 50 -> 10 and low 100 -> 10 make screening noisier (alert fatigue).
- critical 5 -> 10 makes it HALF as sensitive, for the highest-threat
  category. A critical pathogen that should raise an alert at 5 reads waits
  for 10.

The threat-derived table is the deliberate one, so it is the one that stays.
"""

from __future__ import annotations

import dataclasses

import pytest

from nanometa_live.core.config.pathogen_loader import (
    ThreatLevel, default_alert_threshold,
)
from nanometa_live.core.watchlist.watchlist_loader import WatchlistPathogenEntry
from nanometa_live.core.watchlist.watchlist_manager import WatchlistEntry

pytestmark = pytest.mark.unit

THREAT_LEVELS = ("critical", "high", "moderate", "low")


class TestBothPathsAgree:
    @pytest.mark.parametrize("threat", THREAT_LEVELS)
    def test_the_two_entry_types_default_identically(self, threat):
        data = {"name": "Test organism", "taxid_ncbi": 12345,
                "threat_level": threat}

        from_manager = WatchlistEntry.from_dict(data).alert_threshold
        from_loader = WatchlistPathogenEntry(
            name="Test organism", taxid_ncbi=12345, threat_level=threat,
        ).alert_threshold

        assert from_manager == from_loader, (
            f"a '{threat}' entry with no explicit alert_threshold screens at "
            f"{from_manager} reads when loaded one way and {from_loader} the "
            f"other; its threshold changes depending on when it was read"
        )

    @pytest.mark.parametrize("threat", THREAT_LEVELS)
    def test_the_threat_derived_table_is_the_one_that_survives(self, threat):
        """Pin the values, not just their agreement.

        Agreement alone would be satisfied by collapsing both to a flat
        number, which is the behaviour that halves sensitivity for critical.
        """
        expected = default_alert_threshold(ThreatLevel(threat))

        assert WatchlistEntry.from_dict({
            "name": "x", "taxid_ncbi": 1, "threat_level": threat,
        }).alert_threshold == expected

    def test_critical_is_more_sensitive_than_low(self):
        """The property the table exists for."""
        critical = default_alert_threshold(ThreatLevel.CRITICAL)
        low = default_alert_threshold(ThreatLevel.LOW)

        assert critical < low, (
            "a critical pathogen must alert on fewer reads than a low-threat "
            "one, otherwise the threat level is decorative"
        )


class TestExplicitValuesAreUntouched:
    @pytest.mark.parametrize("threat", THREAT_LEVELS)
    def test_an_explicit_threshold_always_wins(self, threat):
        """The operator's number is not a default and must not be derived."""
        data = {"name": "x", "taxid_ncbi": 1, "threat_level": threat,
                "alert_threshold": 42}

        assert WatchlistEntry.from_dict(data).alert_threshold == 42
        assert WatchlistPathogenEntry(
            name="x", taxid_ncbi=1, threat_level=threat, alert_threshold=42,
        ).alert_threshold == 42

    def test_the_dataclass_no_longer_carries_a_flat_default(self):
        """Guards the specific mechanism, a hardcoded field default."""
        field = {
            f.name: f for f in dataclasses.fields(WatchlistPathogenEntry)
        }["alert_threshold"]

        assert field.default is dataclasses.MISSING or field.default is None, (
            "WatchlistPathogenEntry.alert_threshold still has a flat default; "
            "it must be derived from threat_level so the two load paths agree"
        )
