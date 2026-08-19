"""Validation genomes must be looked up by the taxid the reads are extracted for.

Found running the Bioshield exercise with validation enabled (2026-08-18).
``get_validation_species`` resolves a Kraken2 ``kraken_taxid`` per entry --
honouring an operator ``db_taxid`` -- and the pipeline extracts reads and
names its outputs by THAT id. The genome lookup, however, used
``entry.taxid``.

For a watchlist keyed to a custom/GTDB database those are different numbers:
an entry with no NCBI identity gets a synthetic pseudo-taxid, so the real
run showed

    entry.taxid = 2992764709   (synthetic)
    db_taxid    = 4007169      (what reads are extracted for, and where the
                                genome is cached)

The manager reported ``has_genome(4007169) is True`` with a valid path while
``get_validation_species`` returned 129 taxids and ZERO genomes, so the
launch disabled validation entirely: "no pathogen genomes downloaded".
Confirmatory validation was therefore impossible on exactly the database the
exercise runs on.
"""

import pytest

from nanometa_live.core.config.parameter_mapping import get_validation_species

pytestmark = pytest.mark.unit


@pytest.fixture
def watchlist_with_db_taxid(tmp_path, monkeypatch):
    """One enabled entry keyed by db_taxid, with its genome cached there."""
    from nanometa_live.core.utils.genome_manager import get_genome_manager
    from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

    genomes = tmp_path / "genomes"
    genomes.mkdir()
    (genomes / "4007169.fasta").write_text(">NZ_TEST\nACGTACGTACGT\n")

    gm = get_genome_manager(cache_dir=str(tmp_path), offline_mode=True)
    assert gm.has_genome(4007169), "fixture genome not visible to the manager"

    manager = get_watchlist_manager()
    manager.load_config({})

    class _Entry:
        name = "Francisella tularensis"
        taxid = 2992764709      # synthetic: the entry has no NCBI identity
        db_taxid = 4007169      # the database node reads are extracted for

    monkeypatch.setattr(manager, "get_active_entries", lambda: {1: _Entry()})
    monkeypatch.setattr(manager, "_loaded", True)
    return tmp_path


def test_genome_found_via_db_taxid(watchlist_with_db_taxid):
    config = {"genome_cache_dir": str(watchlist_with_db_taxid),
              "data_dir": str(watchlist_with_db_taxid)}
    species, genomes = get_validation_species(config)
    assert len(species) == 1
    assert genomes, (
        "the genome is cached under the db_taxid the pipeline extracts reads "
        "for; looking it up by the entry's synthetic taxid finds nothing and "
        "silently disables validation")
    assert genomes[0].endswith("4007169.fasta")


def test_ncbi_keyed_entry_still_resolves(tmp_path, monkeypatch):
    """The ordinary case must not regress: no db_taxid, genome under taxid."""
    from nanometa_live.core.utils.genome_manager import get_genome_manager
    from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

    genomes = tmp_path / "genomes"
    genomes.mkdir()
    (genomes / "263.fasta").write_text(">NZ_TEST\nACGT\n")
    get_genome_manager(cache_dir=str(tmp_path), offline_mode=True)

    manager = get_watchlist_manager()
    manager.load_config({})

    class _Entry:
        name = "Francisella tularensis"
        taxid = 263
        db_taxid = None

    monkeypatch.setattr(manager, "get_active_entries", lambda: {1: _Entry()})
    monkeypatch.setattr(manager, "_loaded", True)

    _species, found = get_validation_species(
        {"genome_cache_dir": str(tmp_path), "data_dir": str(tmp_path)})
    assert found and found[0].endswith("263.fasta")


class TestPathogenGenomesJson:
    """The file the pipeline consumes has the same key/lookup asymmetry.

    ``generate_pathogen_genomes_json`` keys entries by kraken_taxid (what the
    pipeline filters on) but looked the FILE up by ncbi_taxid. For an entry
    with no NCBI identity the genome is cached under the kraken taxid, so the
    lookup missed, the JSON came back None, and the launch disabled
    validation -- the second half of the same 2026-08-18 defect.
    """

    def test_genome_cached_under_kraken_taxid_is_found(self, tmp_path):
        from nanometa_live.core.utils.genome_manager import get_genome_manager

        (tmp_path / "genomes").mkdir()
        (tmp_path / "genomes" / "4007169.fasta").write_text(">X\nACGT\n")
        gm = get_genome_manager(cache_dir=str(tmp_path), offline_mode=True)

        out = gm.generate_pathogen_genomes_json(
            taxids=[2992764709],                       # synthetic NCBI taxid
            taxid_mapping={2992764709: 4007169},       # -> database node
            output_path=tmp_path / "pathogen_genomes.json",
        )
        assert out is not None, (
            "the genome is cached under the kraken taxid; looking it up only "
            "by the synthetic NCBI taxid returns None and disables validation")
        import json
        data = json.loads(out.read_text()) if hasattr(out, "read_text") \
            else json.load(open(out))
        assert "4007169" in data, "the pipeline filters on the kraken taxid"

    def test_ncbi_cached_genome_still_found(self, tmp_path):
        from nanometa_live.core.utils.genome_manager import get_genome_manager

        (tmp_path / "genomes").mkdir()
        (tmp_path / "genomes" / "263.fasta").write_text(">X\nACGT\n")
        gm = get_genome_manager(cache_dir=str(tmp_path), offline_mode=True)
        out = gm.generate_pathogen_genomes_json(
            taxids=[263], taxid_mapping={263: 4007169},
            output_path=tmp_path / "pg.json")
        assert out is not None
        import json
        assert "4007169" in json.load(open(out))
