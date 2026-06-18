"""Tests for the organism_type and annotation watchlist fields.

Covers the serialization round-trip through every hop -- PathogenEntry,
WatchlistPathogenEntry, and WatchlistEntry (from_dict / to_dict /
from_pathogen_entry / to_pathogen_entry) -- plus organism_type normalisation.
"""

import pytest

from nanometa_live.core.config.pathogen_loader import PathogenEntry, ThreatLevel
from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistEntry,
    ORGANISM_TYPES,
    normalize_organism_type,
)

pytestmark = pytest.mark.unit


def test_from_dict_reads_both_fields():
    entry = WatchlistEntry.from_dict({
        "name": "Staphylococcus aureus",
        "taxid_ncbi": 1280,
        "organism_type": "bacteria",
        "annotation": "produces enterotoxin B",
    })
    assert entry.organism_type == "bacteria"
    assert entry.annotation == "produces enterotoxin B"


def test_from_dict_normalizes_case():
    entry = WatchlistEntry.from_dict({
        "name": "X", "taxid_ncbi": 1, "organism_type": "  VIRUS "})
    assert entry.organism_type == "virus"


def test_from_dict_unknown_organism_type_becomes_none():
    entry = WatchlistEntry.from_dict({
        "name": "X", "taxid_ncbi": 1, "organism_type": "not-a-kingdom"})
    assert entry.organism_type is None


def test_to_dict_always_includes_both_keys():
    # Even when unset, the keys must be present so the dcc.Store / snapshot
    # shape is stable for downstream readers.
    entry = WatchlistEntry.from_dict({"name": "X", "taxid_ncbi": 1})
    d = entry.to_dict()
    assert "organism_type" in d and d["organism_type"] is None
    assert "annotation" in d and d["annotation"] == ""


def test_round_trip_preserves_fields():
    src = {
        "name": "Vibrio cholerae", "taxid_ncbi": 666,
        "organism_type": "bacteria", "annotation": "produces cholera toxin",
    }
    entry = WatchlistEntry.from_dict(src)
    rt = WatchlistEntry.from_dict(entry.to_dict())
    assert rt.organism_type == "bacteria"
    assert rt.annotation == "produces cholera toxin"


def test_pathogen_entry_to_dict_includes_fields():
    pe = PathogenEntry(
        taxid=1280, name="Staphylococcus aureus",
        organism_type="bacteria", annotation="produces enterotoxin B",
    )
    d = pe.to_dict()
    assert d["organism_type"] == "bacteria"
    assert d["annotation"] == "produces enterotoxin B"


def test_from_pathogen_entry_carries_fields():
    pe = PathogenEntry(
        taxid=1280, name="Staphylococcus aureus",
        threat_level=ThreatLevel.HIGH,
        organism_type="bacteria", annotation="produces enterotoxin B",
    )
    entry = WatchlistEntry.from_pathogen_entry(pe)
    assert entry.organism_type == "bacteria"
    assert entry.annotation == "produces enterotoxin B"


def test_to_pathogen_entry_carries_fields():
    entry = WatchlistEntry.from_dict({
        "name": "Vibrio cholerae", "taxid_ncbi": 666,
        "organism_type": "bacteria", "annotation": "produces cholera toxin",
    })
    pe = entry.to_pathogen_entry()
    assert pe.organism_type == "bacteria"
    assert pe.annotation == "produces cholera toxin"


def test_normalize_helper():
    assert normalize_organism_type("Fungi") == "fungi"
    assert normalize_organism_type("") is None
    assert normalize_organism_type(None) is None
    assert normalize_organism_type("plant") is None
    for t in ORGANISM_TYPES:
        assert normalize_organism_type(t.upper()) == t
