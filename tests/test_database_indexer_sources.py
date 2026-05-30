"""
Tests for the alternate index-build sources in core/taxonomy/database_indexer.py.

test_database_indexer.py covers build_from_inspect and the source-priority logic;
this covers the gzip inspect path and the NCBI names.dmp/nodes.dmp parser, plus
the build_index fallback to names.dmp when no inspect.txt is present.
"""

import gzip

import pytest

from nanometa_live.core.taxonomy.database_indexer import (
    DatabaseIndexBuilder,
    build_database_index,
)

pytestmark = pytest.mark.unit

INSPECT = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "90.00\t900\t0\tD\t2\tBacteria\n"
    "50.00\t500\t500\tS\t562\tEscherichia coli\n"
    "30.00\t300\t300\tS\t1280\tStaphylococcus aureus\n"
)

# NCBI dump format: fields separated by '\t|\t', line terminated by '\t|'.
NAMES_DMP = (
    "2\t|\tBacteria\t|\t\t|\tscientific name\t|\n"
    "561\t|\tEscherichia\t|\t\t|\tscientific name\t|\n"
    "562\t|\tEscherichia coli\t|\t\t|\tscientific name\t|\n"
    "562\t|\tE. coli\t|\t\t|\tsynonym\t|\n"
)
# Real nodes.dmp has trailing columns after rank; include a div code so the
# rank field is not the last token (otherwise it keeps the '\t|' terminator).
NODES_DMP = (
    "2\t|\t131567\t|\tsuperkingdom\t|\tBA\t|\n"
    "561\t|\t543\t|\tgenus\t|\tBA\t|\n"
    "562\t|\t561\t|\tspecies\t|\tBA\t|\n"
)


class TestBuildFromInspectGz:
    def test_parses_gzipped_inspect(self, tmp_path):
        gz = tmp_path / "inspect.txt.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as f:
            f.write(INSPECT)
        index = DatabaseIndexBuilder().build_from_inspect_gz(str(gz), str(tmp_path))
        assert index is not None
        assert index.total_nodes == 4
        assert index.get_by_taxid(562).name == "Escherichia coli"

    def test_missing_gz_returns_none(self, tmp_path):
        assert DatabaseIndexBuilder().build_from_inspect_gz(
            str(tmp_path / "nope.gz"), str(tmp_path)
        ) is None


class TestBuildFromNamesDmp:
    def test_parses_names_with_ranks_and_parents(self, tmp_path):
        names = tmp_path / "names.dmp"
        nodes = tmp_path / "nodes.dmp"
        names.write_text(NAMES_DMP)
        nodes.write_text(NODES_DMP)
        index = DatabaseIndexBuilder().build_from_names_dmp(
            str(names), str(nodes), str(tmp_path)
        )
        assert index is not None
        # Only scientific names are indexed (synonym "E. coli" excluded).
        assert index.total_nodes == 3
        ecoli = index.get_by_taxid(562)
        assert ecoli.rank == "S"
        assert ecoli.parent_taxid == 561

    def test_works_without_nodes_dmp(self, tmp_path):
        names = tmp_path / "names.dmp"
        names.write_text(NAMES_DMP)
        index = DatabaseIndexBuilder().build_from_names_dmp(str(names), None, str(tmp_path))
        assert index is not None
        # Without nodes.dmp ranks default to "U".
        assert index.get_by_taxid(562).rank == "U"


class TestBuildIndexFallsBackToNamesDmp:
    def test_uses_names_dmp_when_no_inspect(self, tmp_path):
        # taxonomy/ subdir holds the dumps; no inspect.txt present.
        tax = tmp_path / "taxonomy"
        tax.mkdir()
        (tax / "names.dmp").write_text(NAMES_DMP)
        (tax / "nodes.dmp").write_text(NODES_DMP)
        index = build_database_index(str(tmp_path))
        assert index is not None
        assert index.get_by_taxid(562).name == "Escherichia coli"
