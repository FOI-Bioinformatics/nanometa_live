"""A batch download must fetch by the NCBI taxid, not the database graft id.

`download_genomes_batch` normalises each entry before queueing it. It set
``entry["taxid"]`` to the CACHE taxid (the flextaxd ``db_taxid``) and only then
computed ``entry["_fetch_taxid"]`` from that same dict -- so
`genome_fetch_taxid`, which reads ``taxid_ncbi`` and falls back to ``taxid``,
saw the graft id and offered it to NCBI. `genome_fetch_taxid`'s contract is
that "a database graft id is never offered"; the caller was destroying the
field the contract depends on.

The band check cannot catch this. Pseudo-taxids start at 2,000,000,000, while a
flextaxd graft id (4,007,187) sits far below it and is therefore indistinguishable
from a real NCBI taxid by range. Only call order keeps the two apart.

Impact is concentrated on subspecies entries. For a species, the Bacteria route
tries a name-based GTDB lookup first, which succeeds and hides the problem.
GTDB has no rank below species, so a subspecies name finds nothing there and
falls through to the NCBI-by-taxid call that this bug corrupts.
"""

from nanometa_live.core.utils.genome_manager import (
    genome_cache_taxid,
    genome_fetch_taxid,
    normalise_download_entry,
)


HOLARCTICA = {
    "name": "Francisella tularensis holarctica",
    "taxid": 119857,      # real NCBI subspecies taxid
    "db_taxid": 4007187,  # flextaxd graft id
}


class TestHelpersInIsolation:
    """The two helpers are correct on their own; the caller was not."""

    def test_cache_taxid_prefers_the_database_node(self):
        assert genome_cache_taxid(HOLARCTICA) == 4007187

    def test_fetch_taxid_prefers_the_ncbi_taxid(self):
        assert genome_fetch_taxid(HOLARCTICA) == 119857

    def test_a_graft_id_is_below_the_pseudo_taxid_band(self):
        """So range alone cannot distinguish it from a real taxid."""
        from nanometa_live.core.taxonomy.pseudo_taxid import is_real_ncbi_taxid

        assert is_real_ncbi_taxid(4007187) is True


class TestNormalisation:
    """`normalise_download_entry` is where the two taxids are separated."""

    def test_the_overwrite_is_what_corrupts_the_fetch_taxid(self):
        """Pins the mechanism, so a future refactor cannot reintroduce it."""
        entry = dict(HOLARCTICA)
        entry["taxid"] = genome_cache_taxid(entry)

        assert genome_fetch_taxid(entry) == 4007187, (
            "recomputing after the overwrite yields the graft id -- which is "
            "why the fetch taxid must be taken before the assignment"
        )

    def test_fetch_taxid_is_the_ncbi_taxid(self):
        normalised = normalise_download_entry(HOLARCTICA)

        assert normalised["_fetch_taxid"] == 119857

    def test_cache_taxid_is_the_database_node(self):
        normalised = normalise_download_entry(HOLARCTICA)

        assert normalised["taxid"] == 4007187

    def test_the_caller_s_dict_is_not_mutated(self):
        entry = dict(HOLARCTICA)

        normalise_download_entry(entry)

        assert entry["taxid"] == 119857

    def test_entry_without_a_db_taxid_is_unaffected(self):
        normalised = normalise_download_entry(
            {"name": "Escherichia coli", "taxid": 562})

        assert normalised["taxid"] == 562
        assert normalised["_fetch_taxid"] == 562

    def test_explicit_taxid_ncbi_wins_over_a_zero_taxid(self):
        normalised = normalise_download_entry(
            {"name": "F. t. holarctica", "taxid": 0,
             "db_taxid": 4007187, "taxid_ncbi": 119857})

        assert normalised["_fetch_taxid"] == 119857
        assert normalised["taxid"] == 4007187

    def test_entry_with_no_ncbi_identity_offers_nothing(self):
        """A pseudo-taxid entry must fetch 0 so callers fall back to the name."""
        normalised = normalise_download_entry(
            {"name": "Unknown organism", "taxid": 2_000_000_123,
             "db_taxid": 2_000_000_123})

        assert normalised["_fetch_taxid"] == 0
        assert normalised["taxid"] == 2_000_000_123

    def test_entry_with_no_taxid_at_all_returns_none(self):
        assert normalise_download_entry({"name": "nameless"}) is None

    def test_every_subspecies_in_the_exercise_fetches_by_ncbi_taxid(self):
        """The concrete case: four subspecies sharing one parent species."""
        subspecies = [
            ({"name": "F. t. tularensis", "taxid": 119856, "db_taxid": 4007186}, 119856),
            ({"name": "F. t. holarctica", "taxid": 119857, "db_taxid": 4007187}, 119857),
            ({"name": "F. t. mediasiatica", "taxid": 135248, "db_taxid": 4007188}, 135248),
            ({"name": "F. t. novicida", "taxid": 264, "db_taxid": 4007189}, 264),
        ]
        for entry, expected in subspecies:
            normalised = normalise_download_entry(entry)
            assert normalised["_fetch_taxid"] == expected
            assert normalised["taxid"] == entry["db_taxid"]
