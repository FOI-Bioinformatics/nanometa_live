"""The exported report lists subspecies in their own table.

The organism table is species-only, and stays that way: ranking a species
against its own children reads as double counting even though each row's
percentage is correct on its own -- *F. tularensis* at 99.87% beside
*F. t. holarctica* at 64% invites the reader to add them.

A database that resolves below species carries a distinction worth exporting
though (Type A vs Type B tularaemia), so subspecies get a separate section
with a note that their reads are already counted in the parent species row.

Omitted entirely when the database does not resolve subspecies, so reports
from an NCBI-style build are unchanged.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nanometa_live.core.export.report_generator import ReportGenerator

pytestmark = pytest.mark.unit


def _frame():
    """The real Bioshield shape: a species with four subspecies beneath it."""
    return pd.DataFrame([
        {"rank": "U",  "taxid": 0, "name": "unclassified", "reads": 21,
         "cumul_reads": 21, "%": 0.06},
        {"rank": "R",  "taxid": 1, "name": "root", "reads": 0,
         "cumul_reads": 34120, "%": 99.94},
        {"rank": "G",  "taxid": 4007157, "name": "Francisella", "reads": 111,
         "cumul_reads": 9717, "%": 48.59},
        {"rank": "S",  "taxid": 4007169, "name": "Francisella tularensis",
         "reads": 3406, "cumul_reads": 9602, "%": 48.01},
        {"rank": "S1", "taxid": 4007187,
         "name": "Francisella tularensis holarctica", "reads": 6184,
         "cumul_reads": 6184, "%": 30.92},
        {"rank": "S1", "taxid": 4007186,
         "name": "Francisella tularensis tularensis", "reads": 4,
         "cumul_reads": 4, "%": 0.02},
        {"rank": "S",  "taxid": 9606, "name": "Homo sapiens", "reads": 2,
         "cumul_reads": 2, "%": 0.01},
    ])


def _gen(tmp_path):
    return ReportGenerator(str(tmp_path), {})


class TestTheTwoTablesStaySeparate:
    def test_the_organism_table_stays_species_only(self, tmp_path):
        organisms = _gen(tmp_path)._extract_organisms(_frame())

        names = [o["name"] for o in organisms]
        assert "Francisella tularensis" in names
        assert not any("holarctica" in n for n in names), (
            "a subspecies was ranked against its own parent species"
        )
        assert all(o["rank"] == "S" for o in organisms)

    def test_subspecies_are_extracted_on_request(self, tmp_path):
        subs = _gen(tmp_path)._extract_organisms(
            _frame(), ranks=("S1", "S2", "S3")
        )

        names = [s["name"] for s in subs]
        assert "Francisella tularensis holarctica" in names
        assert "Francisella tularensis tularensis" in names, (
            "Type A missing from the subspecies table"
        )
        assert all(s["rank"].startswith("S") and s["rank"] != "S" for s in subs)

    def test_the_species_itself_is_not_in_the_subspecies_table(self, tmp_path):
        subs = _gen(tmp_path)._extract_organisms(
            _frame(), ranks=("S1", "S2", "S3")
        )

        assert not any(s["name"] == "Francisella tularensis" for s in subs)

    def test_higher_ranks_appear_in_neither(self, tmp_path):
        gen = _gen(tmp_path)
        both = (
            gen._extract_organisms(_frame())
            + gen._extract_organisms(_frame(), ranks=("S1", "S2", "S3"))
        )

        names = [o["name"] for o in both]
        for higher in ("Francisella", "root", "unclassified"):
            assert higher not in names

    def test_abundance_comes_from_the_percent_column(self, tmp_path):
        subs = _gen(tmp_path)._extract_organisms(
            _frame(), ranks=("S1", "S2", "S3")
        )
        holarctica = next(s for s in subs if "holarctica" in s["name"])

        assert holarctica["abundance"] == pytest.approx(30.92)
        assert holarctica["reads"] == 6184


class TestDatabasesWithoutSubspecies:
    def test_an_ncbi_style_report_yields_no_subspecies(self, tmp_path):
        """The section must vanish rather than render empty."""
        df = pd.DataFrame([
            {"rank": "S", "taxid": 562, "name": "Escherichia coli",
             "reads": 500, "cumul_reads": 500, "%": 50.0},
            {"rank": "G", "taxid": 561, "name": "Escherichia",
             "reads": 10, "cumul_reads": 510, "%": 51.0},
        ])

        assert _gen(tmp_path)._extract_organisms(
            df, ranks=("S1", "S2", "S3")
        ) == []

    def test_an_empty_frame_is_safe(self, tmp_path):
        assert _gen(tmp_path)._extract_organisms(
            pd.DataFrame(), ranks=("S1",)
        ) == []
