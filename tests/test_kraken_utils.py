"""
Unit tests for the parsing half of core/utils/kraken_utils.py.

The database-validation half (``check_kraken_db`` and friends) is already
exercised indirectly through the readiness checker; what had no coverage was
the report-parsing and aggregation logic that runs on every classification
result: ``parse_kraken_report``, ``get_species_reads``, ``get_top_taxa``,
``get_taxonomy_tree`` and ``extract_classification_stats``.

Tests assert exact DataFrame shapes, counts and tree structure, and cover the
documented quirks (name stripping, the int taxid column, empty-file handling).
"""

import pandas as pd
import pytest

from nanometa_live.core.utils.kraken_utils import (
    extract_classification_stats,
    get_species_reads,
    get_taxonomy_tree,
    get_top_taxa,
    parse_kraken_report,
)


# Raw Kraken2 report (tab-separated, leading-space indentation in the name
# column as the real tool emits). reads column totals 300; unclassified is 50.
REPORT_TEXT = (
    "50.00\t50\t50\tU\t0\tunclassified\n"
    "50.00\t250\t0\tR\t1\troot\n"
    "42.00\t250\t0\tD\t2\t  Bacteria\n"
    "25.00\t150\t150\tS\t562\t    Escherichia coli\n"
    "15.00\t90\t90\tS\t1280\t    Staphylococcus aureus\n"
    "1.60\t10\t10\tS\t1392\t    Bacillus anthracis\n"
)


@pytest.fixture
def report_file(tmp_path):
    path = tmp_path / "sample.kraken2.report.txt"
    path.write_text(REPORT_TEXT)
    return path


@pytest.fixture
def report_df(report_file):
    return parse_kraken_report(str(report_file))


class TestParseKrakenReport:
    def test_columns_and_row_count(self, report_df):
        assert list(report_df.columns) == [
            "percent",
            "cumulative_reads",
            "reads",
            "rank_code",
            "taxid",
            "name",
        ]
        assert len(report_df) == 6

    def test_names_are_stripped(self, report_df):
        # The name column is right-trimmed of the report's indentation.
        assert "Escherichia coli" in report_df["name"].tolist()
        assert report_df["name"].str.startswith(" ").any() == False  # noqa: E712

    def test_taxid_column_is_integer(self, report_df):
        assert pd.api.types.is_integer_dtype(report_df["taxid"])

    def test_empty_file_returns_empty_frame_with_columns(self, tmp_path):
        # Because column names are supplied explicitly, pandas returns an empty
        # frame for an empty file rather than raising EmptyDataError.
        empty = tmp_path / "empty.kraken2.report.txt"
        empty.write_text("")
        df = parse_kraken_report(str(empty))
        assert df.empty
        assert list(df.columns) == [
            "percent",
            "cumulative_reads",
            "reads",
            "rank_code",
            "taxid",
            "name",
        ]


class TestGetSpeciesReads:
    def test_present_taxids_return_reads(self, report_df):
        result = get_species_reads(report_df, [562, 1392])
        assert result == {562: 150, 1392: 10}

    def test_absent_taxid_returns_zero(self, report_df):
        result = get_species_reads(report_df, [9999])
        assert result == {9999: 0}


class TestGetTopTaxa:
    def test_limits_and_orders_by_reads_desc(self, report_df):
        top = get_top_taxa(report_df, rank_code="S", n=2)
        assert len(top) == 2
        assert top.iloc[0]["name"] == "Escherichia coli"
        assert top.iloc[1]["name"] == "Staphylococcus aureus"

    def test_filters_to_requested_rank(self, report_df):
        species = get_top_taxa(report_df, rank_code="S", n=10)
        assert set(species["rank_code"]) == {"S"}
        assert len(species) == 3

    def test_nonexistent_rank_returns_empty(self, report_df):
        assert get_top_taxa(report_df, rank_code="G").empty


class TestGetTaxonomyTree:
    def test_indentation_builds_nested_hierarchy(self):
        # get_taxonomy_tree derives depth from leading spaces in the name, so it
        # must be fed indentation-preserving names (i.e. not a stripped
        # parse_kraken_report frame).
        df = pd.DataFrame(
            {
                "name": ["root", "  Bacteria", "    Escherichia coli"],
                "taxid": ["1", "2", "562"],
                "reads": [0, 0, 150],
                "rank_code": ["R", "D", "S"],
            }
        )
        tree = get_taxonomy_tree(df)

        assert tree["name"] == "root"
        top = tree["children"][0]
        assert top["name"] == "root"
        bacteria = top["children"][0]
        assert bacteria["name"] == "Bacteria"
        ecoli = bacteria["children"][0]
        assert ecoli["name"] == "Escherichia coli"
        assert ecoli["reads"] == 150

    def test_include_ranks_filter(self):
        df = pd.DataFrame(
            {
                "name": ["Escherichia coli", "Staphylococcus aureus"],
                "taxid": ["562", "1280"],
                "reads": [150, 90],
                "rank_code": ["S", "S"],
            }
        )
        tree = get_taxonomy_tree(df, include_ranks=["S"])
        assert len(tree["children"]) == 2


class TestExtractClassificationStats:
    def test_counts_and_rate(self, report_df):
        stats = extract_classification_stats(report_df)
        # reads column sums to 300; unclassified row carries 50.
        assert stats["total_reads"] == 300
        assert stats["unclassified_reads"] == 50
        assert stats["classified_reads"] == 250
        assert stats["classification_rate"] == pytest.approx(250 / 300)

    def test_zero_total_yields_zero_rate(self):
        df = pd.DataFrame(
            {
                "percent": [0.0],
                "cumulative_reads": [0],
                "reads": [0],
                "rank_code": ["U"],
                "taxid": [0],
                "name": ["unclassified"],
            }
        )
        stats = extract_classification_stats(df)
        assert stats["total_reads"] == 0
        assert stats["classification_rate"] == 0
