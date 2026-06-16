"""Integration tests for organism_type + annotation across loader, manager,
example watchlists, alert emission, grouping, and table rendering.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.core.watchlist.watchlist_loader import WatchlistLoader
from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistManager,
    ORGANISM_TYPES,
    reset_watchlist_manager,
)

pytestmark = pytest.mark.unit

_EXAMPLES_DIR = (
    Path(__file__).resolve().parents[1]
    / "nanometa_live" / "core" / "config" / "data" / "watchlists" / "examples"
)

_EXAMPLE_FILES = {
    "toxin_producing_bacteria.yaml": ("bacteria", 8),
    "respiratory_viruses.yaml": ("virus", 6),
    "clinical_fungi.yaml": ("fungi", 6),
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    reset_watchlist_manager()
    yield
    reset_watchlist_manager()


# --- Loader ---------------------------------------------------------------

def test_loader_reads_new_fields(tmp_path):
    yaml_text = """
version: "2.0"
pathogens:
  - name: "Clostridium botulinum"
    taxid_ncbi: 1491
    organism_type: "bacteria"
    annotation: "produces botulinum neurotoxin"
"""
    f = tmp_path / "wl.yaml"
    f.write_text(yaml_text)
    pathogens = WatchlistLoader()._load_pathogens_from_file(f)
    assert len(pathogens) == 1
    assert pathogens[0].organism_type == "bacteria"
    assert pathogens[0].annotation == "produces botulinum neurotoxin"


def test_loader_defaults_when_absent(tmp_path):
    f = tmp_path / "wl.yaml"
    f.write_text('version: "2.0"\npathogens:\n  - name: "X"\n    taxid_ncbi: 1\n')
    p = WatchlistLoader()._load_pathogens_from_file(f)[0]
    assert p.organism_type is None
    assert p.annotation == ""


@pytest.mark.parametrize("filename,expected", _EXAMPLE_FILES.items())
def test_example_watchlists_load_with_fields(filename, expected):
    expected_type, expected_count = expected
    pathogens = WatchlistLoader()._load_pathogens_from_file(_EXAMPLES_DIR / filename)
    assert len(pathogens) == expected_count
    for p in pathogens:
        assert p.organism_type in ORGANISM_TYPES, p.name
        assert p.organism_type == expected_type, p.name
        assert p.annotation, f"{p.name} missing annotation"


# --- Manager add_custom_entry + grouping ----------------------------------

@pytest.fixture
def manager():
    with patch.object(WatchlistManager, "_save_toggle_state", lambda self: None):
        mgr = WatchlistManager()
        mgr._entries.clear()
        mgr._name_index.clear()
        yield mgr


def test_add_custom_entry_round_trips_fields(manager):
    entry = manager.add_custom_entry({
        "taxid": 1280, "name": "Staphylococcus aureus", "enabled": True,
        "organism_type": "bacteria", "annotation": "produces enterotoxin B",
    })
    assert entry.organism_type == "bacteria"
    assert entry.annotation == "produces enterotoxin B"


def test_check_organisms_alert_carries_fields(manager):
    manager.add_custom_entry({
        "taxid": 666, "name": "Vibrio cholerae", "threat_level": "high",
        "enabled": True, "alert_threshold": 5,
        "organism_type": "bacteria", "annotation": "produces cholera toxin",
    })
    alerts = manager.check_organisms(
        [{"taxid": 666, "name": "Vibrio cholerae", "reads": 100, "abundance": 1.0}]
    )
    assert len(alerts) == 1
    assert alerts[0]["organism_type"] == "bacteria"
    assert alerts[0]["annotation"] == "produces cholera toxin"


def test_grouping_by_organism_type(manager):
    manager.add_custom_entry({"taxid": 1, "name": "A", "enabled": True,
                              "organism_type": "bacteria"})
    manager.add_custom_entry({"taxid": 2, "name": "B", "enabled": True,
                              "organism_type": "virus"})
    manager.add_custom_entry({"taxid": 3, "name": "C", "enabled": True,
                              "organism_type": "bacteria"})
    groups: dict = {}
    for e in manager.get_active_entries().values():
        groups.setdefault(e.organism_type, []).append(e.name)
    assert sorted(groups["bacteria"]) == ["A", "C"]
    assert groups["virus"] == ["B"]


# --- Rendering ------------------------------------------------------------

def test_pathogen_row_renders_annotation_and_badge():
    from nanometa_live.app.layouts.watchlist_layout import create_pathogen_row
    row = create_pathogen_row({
        "taxid": 1280, "name": "Staphylococcus aureus", "common_name": "S. aureus",
        "organism_type": "bacteria", "annotation": "produces enterotoxin B",
        "threat_level": "high", "enabled": True,
    }, 0)
    rendered = str(row)
    assert "produces enterotoxin B" in rendered
    assert "Bacteria" in rendered


def test_organism_card_renders_annotation():
    from nanometa_live.app.components.organism_components import OrganismCard
    card = OrganismCard(
        "Staphylococcus aureus", 5.0, 10,
        annotation="produces enterotoxin B",
    )
    assert "produces enterotoxin B" in str(card)


def test_report_modal_payloads_are_aligned():
    """All three modal payload builders must return the same length and place
    the annotation at the same index (the positional Output contract)."""
    from types import SimpleNamespace
    from nanometa_live.app.tabs.dashboard_helpers import (
        _pathogen_payload, _unwatched_payload, _report_error_payload,
    )
    reads = {"name": "X", "rank": "S", "reads": "10", "abundance": "5%",
             "reads_int": 10}
    pathogen = SimpleNamespace(
        name="Vibrio cholerae", common_name="Cholera", threat_level="high",
        bsl="2", category="Toxin producer", notes="n", action_required="a",
        annotation="", organism_type="bacteria",
    )
    wl = SimpleNamespace(
        annotation="produces cholera toxin", validated=False, ncbi_link=None,
        gtdb_link=None, validation_date=None, lineage=None, gtdb_taxonomy=None,
    )
    pat = _pathogen_payload(pathogen, 666, 666, wl, reads, "now")
    unw = _unwatched_payload(666, 666, reads, "now")
    err = _report_error_payload(666, Exception("x"))
    # The annotation Output sits at index 3 (after is_open, name, common_name).
    assert len(pat) == len(unw) == len(err) == 17
    assert pat[3] == "produces cholera toxin"
