"""
Unit tests for core/taxonomy/database_indexer.py.

The indexer turns a Kraken2 database's inspect.txt into a queryable
DatabaseTaxonomyIndex (name/taxid lookups, species list, lineage). Tests build
from a small synthetic inspect.txt under tmp_path and assert the resulting index
structure and the source-priority logic in build_index, plus the to_dict/from_dict
round-trip of the index itself.
"""

import pytest

from nanometa_live.core.taxonomy import database_indexer as di
from nanometa_live.core.taxonomy.database_indexer import (
    DatabaseIndexBuilder,
    build_database_index,
    get_index_builder,
)
from nanometa_live.core.taxonomy.taxid_mapping import DatabaseTaxonomyIndex

INSPECT = (
    "100.00\t1000\t0\tR\t1\troot\n"
    "90.00\t900\t0\tD\t2\tBacteria\n"
    "50.00\t500\t500\tS\t562\tEscherichia coli\n"
    "30.00\t300\t300\tS\t1280\tStaphylococcus aureus\n"
)


@pytest.fixture(autouse=True)
def _reset_builder_singleton():
    di._builder = None
    yield
    di._builder = None


@pytest.fixture
def inspect_file(tmp_path):
    f = tmp_path / "inspect.txt"
    f.write_text(INSPECT)
    return f


class TestBuildFromInspect:
    def test_index_node_and_species_counts(self, inspect_file, tmp_path):
        index = DatabaseIndexBuilder().build_from_inspect(str(inspect_file), str(tmp_path))
        assert index is not None
        assert index.total_nodes == 4
        assert index.species_count == 2

    def test_lookup_by_taxid(self, inspect_file, tmp_path):
        index = DatabaseIndexBuilder().build_from_inspect(str(inspect_file), str(tmp_path))
        node = index.get_by_taxid(562)
        assert node is not None
        assert node.name == "Escherichia coli"
        assert node.rank == "S"

    def test_lookup_by_name_is_normalised(self, inspect_file, tmp_path):
        index = DatabaseIndexBuilder().build_from_inspect(str(inspect_file), str(tmp_path))
        nodes = index.get_by_name("escherichia coli")
        assert any(n.taxid == 562 for n in nodes)

    def test_get_species(self, inspect_file, tmp_path):
        index = DatabaseIndexBuilder().build_from_inspect(str(inspect_file), str(tmp_path))
        species_taxids = {n.taxid for n in index.get_species()}
        assert species_taxids == {562, 1280}


class TestBuildIndexSourcePriority:
    def test_builds_from_inspect_txt_in_db_dir(self, tmp_path):
        (tmp_path / "inspect.txt").write_text(INSPECT)
        index = build_database_index(str(tmp_path))
        assert index is not None
        assert index.get_by_taxid(562).name == "Escherichia coli"

    def test_explicit_inspect_file_takes_priority(self, tmp_path):
        explicit = tmp_path / "custom_inspect.txt"
        explicit.write_text(INSPECT)
        index = build_database_index(str(tmp_path), inspect_file=str(explicit))
        assert index is not None
        assert index.total_nodes == 4

    def test_missing_database_path_returns_none(self, tmp_path):
        assert build_database_index(str(tmp_path / "does_not_exist")) is None


class TestIndexRoundTrip:
    def test_to_dict_from_dict_preserves_lookups(self, inspect_file, tmp_path):
        index = DatabaseIndexBuilder().build_from_inspect(str(inspect_file), str(tmp_path))
        rebuilt = DatabaseTaxonomyIndex.from_dict(index.to_dict())
        assert rebuilt.get_by_taxid(562).name == "Escherichia coli"
        assert any(n.taxid == 1280 for n in rebuilt.get_by_name("staphylococcus aureus"))


class TestFactory:
    def test_get_index_builder_is_singleton(self):
        assert get_index_builder() is get_index_builder()
        assert isinstance(get_index_builder(), DatabaseIndexBuilder)
