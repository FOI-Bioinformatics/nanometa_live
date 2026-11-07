"""A custom watchlist entry must be found however the report spells the name.

``_check_for_dangerous_pathogens_uncached`` looked a custom watchlist entry up
by exact lowercase name. A Kraken2 report names the organism as the database
does -- with a GTDB polyphyly suffix, an underscore spelling, a strain suffix
-- so the lookup missed, and the miss did more than lose a custom threshold:
where the built-in pathogen database matched the same row by substring, the
"a watchlist exists but this pathogen is not in it" branch SKIPPED the alert
entirely. A differently spelled name therefore suppressed the detection
(audit 2026-11-06, finding 33).

The resolution now goes through ``TaxonomyMatcher`` at its 0.7 alert floor --
the same matcher and the same floor as ``check_organisms_with_mapping_split``,
so this path and the dashboard's agree on what a name means.
"""

import pytest

from nanometa_live.core.utils.pathogen_database import (
    check_for_dangerous_pathogens,
    get_all_dangerous_pathogens,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def builtin_entry():
    """A built-in pathogen whose name has two words, so a suffix can be added."""
    for entry in get_all_dangerous_pathogens().values():
        if len(entry.name.split()) == 2:
            return entry
    pytest.skip("no binomial entry in the built-in database")


def _watchlist(entry, threshold=1):
    return [{
        "taxid": entry.taxid,
        "name": entry.name,
        "enabled": True,
        "alert_threshold": threshold,
        "threat_level": "critical",
    }]


def _row(name, taxid, reads=500):
    return [{"taxid": taxid, "name": name, "reads": reads, "abundance": 5.0}]


class TestADifferentlySpelledNameIsStillWatched:
    @pytest.mark.parametrize("spelling", ["{name} str. Ames", "{name}_variant"])
    def test_the_detection_is_not_suppressed(self, builtin_entry, spelling):
        name = spelling.format(name=builtin_entry.name)
        # A taxid the watchlist does not carry, so only the name can resolve.
        alerts = check_for_dangerous_pathogens(
            _row(name, 999001), _watchlist(builtin_entry))

        assert alerts, (
            f"{name!r} raised no alert at all: the exact-name lookup missed "
            "the custom entry and the 'not in the watchlist' branch then "
            "suppressed the built-in match"
        )

    def test_the_underscored_name_is_watched(self, builtin_entry):
        name = builtin_entry.name.replace(" ", "_")
        alerts = check_for_dangerous_pathogens(
            _row(name, 999002), _watchlist(builtin_entry))

        assert alerts


class TestTheEntrysOwnPolicyStillDecides:
    def test_a_disabled_entry_still_suppresses(self, builtin_entry):
        """Resolution must not turn an opt-out into an alert."""
        watchlist = _watchlist(builtin_entry)
        watchlist[0]["enabled"] = False
        name = f"{builtin_entry.name} str. Ames"

        alerts = check_for_dangerous_pathogens(
            _row(name, 999003), watchlist)

        assert alerts == []

    def test_a_high_threshold_still_gates(self, builtin_entry):
        name = f"{builtin_entry.name} str. Ames"

        alerts = check_for_dangerous_pathogens(
            _row(name, 999004, reads=3),
            _watchlist(builtin_entry, threshold=1000))

        assert alerts == []


class TestUnrelatedOrganismsAreNotClaimed:
    def test_a_different_organism_raises_nothing(self, builtin_entry):
        alerts = check_for_dangerous_pathogens(
            _row("Lactobacillus delbrueckii", 999005),
            _watchlist(builtin_entry))

        assert alerts == []

    def test_an_empty_watchlist_is_still_an_opt_out(self, builtin_entry):
        """[] means "no alerts wanted" and must keep meaning that."""
        alerts = check_for_dangerous_pathogens(
            _row(builtin_entry.name, builtin_entry.taxid), [])

        assert alerts == []

    def test_no_watchlist_leaves_the_builtin_database_in_charge(
        self, builtin_entry
    ):
        alerts = check_for_dangerous_pathogens(
            _row(builtin_entry.name, builtin_entry.taxid), None)

        assert [a["name"] for a in alerts] == [builtin_entry.name]
