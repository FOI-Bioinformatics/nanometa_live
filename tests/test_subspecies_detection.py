"""Subspecies must be detectable, not silently rolled into their species.

A Bioshield report resolves *Francisella tularensis* into four subspecies, and
the distinction is clinical: holarctica is Type B and the lineage the LVS
vaccine strain comes from, tularensis is Type A and markedly more virulent.
Screening for Type A means matching the ``S1`` row.

Measured on the real report:

    rank=S    taxid=4007169  reads=3406  cumul=9602  Francisella tularensis
    rank=S1   taxid=4007187  reads=6184  cumul=6184    ...holarctica
    rank=S1   taxid=4007189  reads=6     cumul=6       ...novicida
    rank=S1   taxid=4007186  reads=4     cumul=4       ...tularensis
    rank=S1   taxid=4007188  reads=2     cumul=2       ...mediasiatica

Every consumer filtered ``rank == "S"`` and dropped all four -- except the
Organisms tab, which used ``{S, S1, S2}``. So a subspecies watchlist entry was
visible on one tab and could never reach the verdict banner.

Reads are not double counted by including them: 3,406 direct + 6,196 across
the children = 9,602, which is exactly the species row's cumulative figure.
Each row is a distinct taxid, so per-taxon consumers treat them as independent
candidates. Summing a species with its own children is the unsafe operation,
and the report's abundance table stays species-only for that reason.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nanometa_live.core.taxonomy.ranks import (
    SPECIES_RANKS, is_species_rank, species_rank_mask,
)

pytestmark = pytest.mark.unit


def _tularensis_frame():
    """The real report's shape, reads and taxids."""
    return pd.DataFrame([
        {"rank": "G",  "taxid": 4007157, "name": "Francisella",
         "reads": 111, "cumul_reads": 9717, "%": 48.59},
        {"rank": "S",  "taxid": 4007169, "name": "Francisella tularensis",
         "reads": 3406, "cumul_reads": 9602, "%": 48.01},
        {"rank": "S1", "taxid": 4007187, "name": "Francisella tularensis holarctica",
         "reads": 6184, "cumul_reads": 6184, "%": 30.92},
        {"rank": "S1", "taxid": 4007189, "name": "Francisella tularensis novicida",
         "reads": 6, "cumul_reads": 6, "%": 0.03},
        {"rank": "S1", "taxid": 4007186, "name": "Francisella tularensis tularensis",
         "reads": 4, "cumul_reads": 4, "%": 0.02},
        {"rank": "S1", "taxid": 4007188, "name": "Francisella tularensis mediasiatica",
         "reads": 2, "cumul_reads": 2, "%": 0.01},
    ])


class TestTheRankPredicate:
    @pytest.mark.parametrize("rank", ["S", "S1", "S2", "S3"])
    def test_species_and_subspecies_count(self, rank):
        assert is_species_rank(rank)

    @pytest.mark.parametrize("rank", ["G", "F", "O", "C", "P", "D", "K", "R", "U", "G1", "P9"])
    def test_higher_ranks_do_not(self, rank):
        assert not is_species_rank(rank)

    def test_whitespace_and_junk_are_tolerated(self):
        """Rank arrives from a parsed column and may be padded or NaN."""
        assert is_species_rank(" S1 ")
        assert not is_species_rank(None)
        assert not is_species_rank(float("nan"))

    def test_the_set_is_the_documented_one(self):
        assert SPECIES_RANKS == {"S", "S1", "S2", "S3"}


class TestSubspeciesReachDetection:
    def test_all_four_subspecies_are_selected(self):
        df = _tularensis_frame()

        selected = df[species_rank_mask(df)]

        names = set(selected["name"])
        assert "Francisella tularensis tularensis" in names, (
            "Type A was dropped; an operator screening for it would see "
            "nothing while the database resolved it"
        )
        assert len(selected) == 5  # the species plus its four children

    def test_the_genus_is_still_excluded(self):
        """Including subspecies must not start including higher ranks."""
        df = _tularensis_frame()

        assert "Francisella" not in set(df[species_rank_mask(df)]["name"])

    def test_each_subspecies_keeps_its_own_taxid(self):
        """They are independent candidates, not variants of one row."""
        df = _tularensis_frame()

        taxids = set(df[species_rank_mask(df)]["taxid"])
        assert {4007169, 4007186, 4007187, 4007188, 4007189} == taxids


class TestNoDoubleCounting:
    def test_the_species_cumulative_already_contains_its_children(self):
        """The arithmetic that makes inclusion safe for per-taxon consumers."""
        df = _tularensis_frame()
        species = df[df["rank"] == "S"].iloc[0]
        children = df[df["rank"] == "S1"]

        assert species["reads"] + children["reads"].sum() == species["cumul_reads"]

    def test_summing_across_ranks_would_double_count(self):
        """States the unsafe operation explicitly so it is not introduced.

        This is why the report's abundance table stays species-only.
        """
        df = _tularensis_frame()
        selected = df[species_rank_mask(df)]

        naive_total = selected["cumul_reads"].sum()
        true_total = df[df["rank"] == "S"]["cumul_reads"].sum()

        assert naive_total > true_total
        assert naive_total == 9602 + 6196
