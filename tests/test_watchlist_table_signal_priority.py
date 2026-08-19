"""The watchlist table must lead with detectability, not with a name lookup.

Two adjacent columns answer completely different questions:

- "In Database" -- did this organism resolve to a node in the LOADED Kraken2
  database? This decides whether a run can detect it at all.
- the public-taxonomy lookup -- does NCBI or GTDB know this name? Network
  only, and orthogonal to the database in use.

The lookup used to come first and render a green check. On a flextaxd build
(Bioshield and similar) an entry can carry that green check while being
absent from the database entirely -- undetectable -- and on an air-gapped
field machine, the deployment this tool targets, every entry shows unchecked
while being perfectly detectable. That is a green tick reading as
reassurance about something it does not measure, the same failure mode the
NOT_SCREENED verdict work fixed (2026-08-19 taxid-verification audit).
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.layouts.watchlist_layout import (
    _create_pathogens_table_section,
    _create_stats_bar,
    create_pathogen_row,
)


def _render(component) -> str:
    return str(component)


class TestColumnOrder:
    def test_database_column_precedes_the_name_check(self):
        rendered = _render(_create_pathogens_table_section())
        db_at = rendered.find("In Database")
        name_at = rendered.find("Name check")
        assert db_at != -1, "the In Database column header is missing"
        assert name_at != -1, "the name-check column header is missing"
        assert db_at < name_at, (
            "the public-taxonomy lookup is displayed before the column that "
            "says whether the organism can be detected at all"
        )

    def test_name_check_header_is_not_called_verified(self):
        rendered = _render(_create_pathogens_table_section())
        assert ">Verified<" not in rendered, (
            "'Verified' invites the reading 'this organism is confirmed "
            "usable'; it records a name lookup only"
        )

    def test_name_check_tooltip_disclaims_detectability(self):
        rendered = _render(_create_pathogens_table_section())
        assert "does NOT mean the organism is present in your database" in rendered

    def test_database_tooltip_states_it_decides_detection(self):
        rendered = _render(_create_pathogens_table_section())
        assert "decides" in rendered and "detected in a run" in rendered


class TestRowRendering:
    ENTRY = {"taxid": 1392, "name": "Bacillus anthracis", "threat_level": "critical"}

    def test_unchecked_name_is_a_dash_not_a_cross(self):
        rendered = _render(create_pathogen_row({**self.ENTRY, "validated": False}, 0))
        assert "bi-dash" in rendered, (
            "not looking a name up is the normal state offline; a red cross "
            "reads as a failure the operator should fix"
        )
        assert "bi-x-circle" not in rendered

    def test_checked_name_is_not_a_green_success_tick(self):
        rendered = _render(create_pathogen_row({**self.ENTRY, "validated": True}, 0))
        assert "bi-check-circle-fill text-success" not in rendered, (
            "a green success tick competes with the In Database column and "
            "is read as 'ready to detect'"
        )
        assert "text-secondary" in rendered

    def test_database_status_still_renders_its_badge(self):
        rendered = _render(create_pathogen_row(
            {**self.ENTRY, "validated": False},
            0,
            mapping_info={"confidence": "exact", "db_taxid": 4005020,
                          "db_name": "Bacillus_A anthracis"},
        ))
        assert "Exact" in rendered
        assert "4005020" in rendered


class TestStatsBar:
    def test_lookup_count_is_not_labelled_validated(self):
        rendered = _render(_create_stats_bar())
        assert "name-checked" in rendered
        assert " validated" not in rendered, (
            "'validated' beside the active-organism count reads as a "
            "readiness figure for the run"
        )

    def test_lookup_count_disclaims_detectability(self):
        rendered = _render(_create_stats_bar())
        assert "Not a measure of detectability" in rendered
