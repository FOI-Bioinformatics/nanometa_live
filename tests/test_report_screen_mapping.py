"""The exported report must screen the watchlist the way the dashboard does.

Three defects in the report's own screen, all found 2026-11-06:

**Finding 2.** ``_match_entry_rows`` compared ``db_taxid or taxid`` against
the frame's taxid column and fell back to an exact lowercase name compare. It
consulted neither the taxid mapping collection nor any name normalisation, so
on a GTDB/flextaxd database -- where *Bacillus anthracis* (NCBI 1392) is the
node ``Bacillus_A anthracis`` at 4005020 -- it matched zero rows. Every entry
read ``detected=False`` and the report rendered the green "NO WATCHED
ORGANISMS DETECTED" for a run the dashboard alarmed on. The docstring claimed
"the same precedence the dashboard uses", which was false.

**Finding 21.** "Top Organisms" sorted on the per-rank ``reads`` column while
displaying Kraken2's clade ``%``, so a species whose reads sit in its
subspecies ranked below an abundant-looking neighbour and could fall off
``head(20)``.

**Finding 36.** The decision banner alarmed on any detection, ignoring the
entry's own ``alert_threshold`` -- one read of a critical entry rendered
ACTION REQUIRED where the dashboard rendered MONITORING.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nanometa_live.core.export.report_generator import ReportGenerator
from nanometa_live.core.taxonomy.taxid_mapping import (
    MappingConfidence,
    TaxidMapping,
    TaxidMappingCollection,
    set_mapping_collection,
)
from nanometa_live.core.watchlist.watchlist_manager import (
    ThreatLevel,
    WatchlistEntry,
)

pytestmark = pytest.mark.unit

_MGR_PATH = (
    "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager"
)


@pytest.fixture(autouse=True)
def _no_live_collection():
    set_mapping_collection(None)
    yield
    set_mapping_collection(None)


@pytest.fixture
def generator(tmp_path):
    return ReportGenerator(str(tmp_path), {"analysis_name": "Test Run"})


def _mock_manager(entries):
    mgr = MagicMock()
    mgr._loaded = True
    mgr.get_active_entries.return_value = entries
    return mgr


def _gtdb_frame():
    """A flextaxd-shaped report: grafted node, GTDB name, no NCBI taxid."""
    return pd.DataFrame([
        {"taxid": 0, "name": "unclassified", "rank": "U",
         "reads": 100, "cumul_reads": 100},
        {"taxid": 1, "name": "root", "rank": "R",
         "reads": 0, "cumul_reads": 900},
        {"taxid": 4005020, "name": "Bacillus_A anthracis", "rank": "S",
         "reads": 500, "cumul_reads": 500},
    ])


def _anthracis_entry(threshold=1):
    return {1392: WatchlistEntry(
        taxid=1392, name="Bacillus anthracis",
        threat_level=ThreatLevel.CRITICAL, enabled=True,
        alert_threshold=threshold,
    )}


def _collection_mapping_1392_to_node():
    collection = TaxidMappingCollection(database_path="/db", database_hash="h")
    collection.mappings[1392] = TaxidMapping(
        ncbi_taxid=1392,
        canonical_name="Bacillus anthracis",
        db_taxid=4005020,
        db_name="Bacillus_A anthracis",
        confidence=MappingConfidence.EXACT,
        match_score=1.0,
        match_method="variant",
    )
    return collection


class TestTheMappingCollectionIsConsulted:
    def test_the_mapped_node_is_detected(self, generator):
        set_mapping_collection(_collection_mapping_1392_to_node())

        with patch(_MGR_PATH, return_value=_mock_manager(_anthracis_entry())):
            rows = generator._screen_watchlist(_gtdb_frame())

        assert rows[0]["detected"] is True, (
            "the report screened NCBI 1392 against a GTDB node and found "
            "nothing, so it renders the green all-clear for an alarming run"
        )
        assert rows[0]["reads"] == 500

    def test_the_per_sample_breakdown_resolves_too(self, generator):
        set_mapping_collection(_collection_mapping_1392_to_node())
        frames = {"barcode01": _gtdb_frame()}

        with patch(_MGR_PATH, return_value=_mock_manager(_anthracis_entry())):
            rows = generator._screen_watchlist(_gtdb_frame(), frames)

        assert [s["sample"] for s in rows[0]["samples"]] == ["barcode01"]

    def test_a_cached_mappings_file_is_read_in_a_worker(
        self, tmp_path, monkeypatch
    ):
        """No singleton in a DiskcacheManager worker; the file is the source."""
        from nanometa_live.core.export.watchlist_screen import (
            resolve_mapping_collection,
        )
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
        db = tmp_path / "db"
        db.mkdir()
        (db / "hash.k2d").write_bytes(b"x" * 16)
        from nanometa_live.core.taxonomy.taxid_mapping import (
            get_mapping_cache_path,
        )
        path = get_mapping_cache_path(str(db))
        assert _collection_mapping_1392_to_node().save(str(path)) is True

        resolved = resolve_mapping_collection({"kraken_db": str(db)})

        assert resolved is not None
        assert resolved.get_db_taxid(1392) == 4005020

    def test_no_mapping_is_not_an_error(self, generator):
        """A database nobody scanned still screens on taxid plus names."""
        with patch(_MGR_PATH, return_value=_mock_manager(_anthracis_entry())):
            rows = generator._screen_watchlist(pd.DataFrame([
                {"taxid": 1, "name": "root", "rank": "R",
                 "reads": 0, "cumul_reads": 900},
                {"taxid": 1392, "name": "Bacillus anthracis", "rank": "S",
                 "reads": 7, "cumul_reads": 7},
            ]))

        assert rows[0]["detected"] is True
        assert rows[0]["reads"] == 7


class TestTheNameFallbackIsNormalised:
    @pytest.mark.parametrize("report_name", [
        "Bacillus anthracis str. Ames",      # strain suffix
        "Bacillus_anthracis",                # GTDB underscore spelling
        "s__Bacillus anthracis",             # GTDB rank prefix
        "Bacillus anthracis subsp. anthracis",
    ])
    def test_a_differently_spelled_name_still_matches(
        self, generator, report_name
    ):
        """Every one of these failed the old exact lowercase compare."""
        frame = pd.DataFrame([
            {"taxid": 1, "name": "root", "rank": "R",
             "reads": 0, "cumul_reads": 900},
            {"taxid": 55555, "name": report_name, "rank": "S",
             "reads": 500, "cumul_reads": 500},
        ])
        with patch(_MGR_PATH, return_value=_mock_manager(_anthracis_entry())):
            rows = generator._screen_watchlist(frame)

        assert rows[0]["detected"] is True, (
            f"{report_name!r} did not resolve to its watchlist entry"
        )
        assert rows[0]["reads"] == 500

    def test_an_unrelated_organism_is_not_claimed(self, generator):
        frame = pd.DataFrame([
            {"taxid": 1, "name": "root", "rank": "R",
             "reads": 0, "cumul_reads": 900},
            {"taxid": 1280, "name": "Staphylococcus aureus", "rank": "S",
             "reads": 500, "cumul_reads": 500},
        ])
        with patch(_MGR_PATH, return_value=_mock_manager(_anthracis_entry())):
            rows = generator._screen_watchlist(frame)

        assert rows[0]["detected"] is False
        assert rows[0]["reads"] == 0

    def test_a_species_and_its_subspecies_are_not_summed(self, generator):
        """Both rows carry the entry's name; the clade count contains both."""
        frame = pd.DataFrame([
            {"taxid": 1, "name": "root", "rank": "R",
             "reads": 0, "cumul_reads": 900},
            {"taxid": 4007169, "name": "Francisella tularensis",
             "rank": "S", "reads": 300, "cumul_reads": 900},
            {"taxid": 4007187, "name": "Francisella tularensis holarctica",
             "rank": "S1", "reads": 600, "cumul_reads": 600},
        ])
        entries = {263: WatchlistEntry(
            taxid=263, name="Francisella tularensis",
            threat_level=ThreatLevel.CRITICAL, enabled=True,
        )}
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            rows = generator._screen_watchlist(frame)

        assert rows[0]["reads"] == 900, (
            "the species clade count already contains its subspecies, so "
            "summing both rows double counts"
        )


class TestTopOrganismsSortsOnCladeReads:
    def test_a_species_whose_reads_sit_in_its_subspecies_ranks_first(
        self, generator
    ):
        df = pd.DataFrame([
            {"taxid": 263, "name": "Francisella tularensis", "rank": "S",
             "reads": 100, "cumul_reads": 6000, "%": 60.0},
            {"taxid": 562, "name": "Escherichia coli", "rank": "S",
             "reads": 200, "cumul_reads": 200, "%": 2.0},
        ])

        organisms = generator._extract_organisms(df)

        assert [o["name"] for o in organisms][0] == "Francisella tularensis", (
            "the ranking sorted on the per-rank reads column while showing "
            "clade abundance, so the dominant organism ranked second"
        )

    def test_a_frame_without_clade_counts_still_sorts(self, generator):
        df = pd.DataFrame([
            {"taxid": 562, "name": "Escherichia coli", "rank": "S",
             "reads": 10, "%": 1.0},
            {"taxid": 1280, "name": "Staphylococcus aureus", "rank": "S",
             "reads": 90, "%": 9.0},
        ])

        organisms = generator._extract_organisms(df)

        assert [o["name"] for o in organisms][0] == "Staphylococcus aureus"


class TestTheBannerRespectsTheEntryThreshold:
    def _render_banner(self):
        import pathlib
        import re

        import jinja2

        import nanometa_live.core.export.report_generator as rg
        tdir = pathlib.Path(rg.__file__).parent / "templates"
        source = (tdir / "report.html").read_text()
        start = source.index("<!-- DECISION BANNER -->")
        depth = 0
        end = None
        for m in re.finditer(r"{%-?\s*(if|endif)\b.*?%}", source[start:]):
            if m.group(1) == "if":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end = start + m.end()
                    break
        assert end is not None
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(tdir)), autoescape=True)
        return env.from_string(source[start:end])

    def test_a_below_threshold_detection_does_not_alarm(self, generator):
        html = self._render_banner().render(data={"watched_results": [{
            "name": "Bacillus anthracis", "detected": True,
            "threat_level": "critical", "reads": 1,
            "above_threshold": False, "alert_threshold": 100,
        }], "total_reads": 5000, "low_read_floor": 10})

        assert "ACTION REQUIRED" not in html, (
            "one read of a critical entry whose threshold is 100 rendered "
            "ACTION REQUIRED, where the dashboard renders MONITORING"
        )

    def test_it_is_still_reported(self, generator):
        html = self._render_banner().render(data={"watched_results": [{
            "name": "Bacillus anthracis", "detected": True,
            "threat_level": "critical", "reads": 1,
            "above_threshold": False, "alert_threshold": 100,
        }], "total_reads": 5000, "low_read_floor": 10})

        assert "REVIEW RECOMMENDED" in html
        assert "banner-safe" not in html

    def test_an_above_threshold_detection_still_alarms(self, generator):
        html = self._render_banner().render(data={"watched_results": [{
            "name": "Bacillus anthracis", "detected": True,
            "threat_level": "critical", "reads": 500,
            "above_threshold": True, "alert_threshold": 100,
        }], "total_reads": 5000, "low_read_floor": 10})

        assert "ACTION REQUIRED" in html

    def test_a_row_without_the_key_keeps_the_old_behaviour(self, generator):
        html = self._render_banner().render(data={"watched_results": [{
            "name": "Bacillus anthracis", "detected": True,
            "threat_level": "critical",
        }], "total_reads": 5000, "low_read_floor": 10})

        assert "ACTION REQUIRED" in html

    def test_a_mapped_gtdb_detection_renders_action_required(self, generator):
        """The whole chain: mapping -> screen row -> banner.

        This is the state the audit observed rendering the green banner: a
        flextaxd database, an NCBI-taxid watchlist entry, and reads on the
        grafted node.
        """
        set_mapping_collection(_collection_mapping_1392_to_node())
        with patch(_MGR_PATH, return_value=_mock_manager(_anthracis_entry(10))):
            rows = generator._screen_watchlist(_gtdb_frame())

        html = self._render_banner().render(data={
            "watched_results": rows, "total_reads": 1000,
            "low_read_floor": 10,
        })

        assert "ACTION REQUIRED" in html
        assert "banner-safe" not in html
        assert "NO WATCHED ORGANISMS DETECTED" not in html

    def test_the_screen_row_carries_the_verdict(self, generator):
        entries = _anthracis_entry(threshold=1000)
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            rows = generator._screen_watchlist(pd.DataFrame([
                {"taxid": 1, "name": "root", "rank": "R",
                 "reads": 0, "cumul_reads": 900},
                {"taxid": 1392, "name": "Bacillus anthracis", "rank": "S",
                 "reads": 500, "cumul_reads": 500},
            ]))

        assert rows[0]["detected"] is True
        assert rows[0]["above_threshold"] is False
        assert rows[0]["alert_threshold"] == 1000
