"""
Unit tests for core/export/report_generator.py.

ReportGenerator turns a nanometanf results directory into a self-contained HTML
report plus copied raw files and a metadata sidecar. Tests run it end-to-end
against the shared batch_output_dir fixture (populated kraken2/ + fastp/) and
write the export under tmp_path, asserting the report is produced, the
include_raw toggle is honoured, and the sample filter is respected.
"""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nanometa_live.core.export.report_generator import ReportGenerator
from nanometa_live.core.watchlist.watchlist_manager import (
    WatchlistEntry,
    ThreatLevel,
)


@pytest.fixture
def generator(batch_output_dir):
    return ReportGenerator(str(batch_output_dir), {"analysis_name": "Test Run"})


def _kraken_df():
    """Minimal kraken frame: root + unclassified totals plus one species."""
    return pd.DataFrame([
        {"taxid": 0, "name": "unclassified", "rank": "U", "reads": 100, "cumul_reads": 100},
        {"taxid": 1, "name": "root", "rank": "R", "reads": 0, "cumul_reads": 900},
        {"taxid": 1392, "name": "Bacillus anthracis", "rank": "S", "reads": 500, "cumul_reads": 500},
    ])


def _mock_manager(entries):
    """A watchlist manager whose get_active_entries returns the given dict."""
    mgr = MagicMock()
    mgr._loaded = True
    mgr.get_active_entries.return_value = entries
    return mgr


class TestGenerate:
    def test_writes_html_report(self, generator, tmp_path):
        out = tmp_path / "export"
        report = generator.generate(str(out), include_raw=False)
        assert report.name == "report.html"
        assert report.exists()
        content = report.read_text()
        assert "html" in content.lower()
        assert len(content) > 500

    def test_writes_metadata_sidecar(self, generator, tmp_path):
        out = tmp_path / "export"
        generator.generate(str(out), include_raw=False)
        metadata_files = list(out.glob("*.json"))
        assert metadata_files, "no metadata json written"
        # The metadata is valid JSON carrying the results dir.
        data = json.loads(metadata_files[0].read_text())
        assert isinstance(data, dict)

    def test_metadata_drops_redundant_fastp_summary(self, generator, tmp_path):
        out = tmp_path / "export"
        generator.generate(str(out), include_raw=False)
        metadata = json.loads((out / "metadata.json").read_text())
        # qc_summary covers both fastp and seqkit; the fastp-only block is gone.
        assert "fastp_summary" not in metadata
        assert "qc_summary" in metadata

    def test_generated_at_is_timezone_aware(self, generator, tmp_path):
        from datetime import datetime

        out = tmp_path / "export"
        generator.generate(str(out), include_raw=False)
        summary = json.loads((out / "summary.json").read_text())
        ts = datetime.fromisoformat(summary["generated_at"])
        assert ts.tzinfo is not None  # carries a UTC offset, not naive

    def test_include_raw_copies_kraken2(self, generator, tmp_path):
        out = tmp_path / "export"
        generator.generate(str(out), include_raw=True)
        # Raw kraken2 outputs are copied somewhere under the export dir.
        assert any(out.rglob("*kraken2*"))

    def test_include_raw_false_skips_copy(self, generator, tmp_path):
        out = tmp_path / "export"
        generator.generate(str(out), include_raw=False)
        assert not any(out.rglob("*.kraken2.report.txt"))

    def test_unknown_sample_filter_falls_back_to_aggregate(self, generator, tmp_path):
        out = tmp_path / "export"
        # No matching sample -> aggregated-only report, still produced.
        report = generator.generate(str(out), samples=["no_such_sample"], include_raw=False)
        assert report.exists()


_MGR_PATH = "nanometa_live.core.watchlist.watchlist_manager.get_watchlist_manager"


class TestScreenWatchlist:
    """Regression cover for the iteration/matching bug that left every
    exported report's threat screen empty (get_active_entries returns a dict
    of WatchlistEntry, not a list of dicts)."""

    def test_detected_entry_screened(self, generator):
        entries = {1392: WatchlistEntry(
            taxid=1392, name="Bacillus anthracis",
            threat_level=ThreatLevel.CRITICAL, enabled=True,
        )}
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            rows = generator._screen_watchlist(_kraken_df())
        assert len(rows) == 1
        row = rows[0]
        assert row["detected"] is True
        assert row["name"] == "Bacillus anthracis"
        assert row["threat_level"] == "critical"  # enum -> string
        assert row["reads"] == 500
        assert row["abundance"] == 50.0  # 500 / (900 + 100) total reads

    def test_absent_entry_marked_not_detected(self, generator):
        entries = {99999: WatchlistEntry(
            taxid=99999, name="Yersinia pestis",
            threat_level=ThreatLevel.HIGH, enabled=True,
        )}
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            rows = generator._screen_watchlist(_kraken_df())
        assert len(rows) == 1
        assert rows[0]["detected"] is False
        assert rows[0]["reads"] == 0

    def test_gtdb_db_taxid_match(self, generator):
        # NCBI taxid differs from the Kraken2 db taxid; db_taxid must drive the
        # match against the kraken frame (GTDB / custom DB case).
        df = _kraken_df()
        df.loc[df["name"] == "Bacillus anthracis", "taxid"] = 77643
        entries = {1392: WatchlistEntry(
            taxid=1392, name="Bacillus anthracis", db_taxid=77643,
            threat_level=ThreatLevel.CRITICAL, enabled=True,
        )}
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            rows = generator._screen_watchlist(df)
        assert rows[0]["detected"] is True
        assert rows[0]["reads"] == 500

    def test_name_fallback_when_no_taxid_match(self, generator):
        # Entry has no usable taxid match but the name matches a kraken row.
        df = _kraken_df()
        df.loc[df["name"] == "Bacillus anthracis", "taxid"] = 55555
        entries = {0: WatchlistEntry(
            taxid=0, name="Bacillus anthracis",
            threat_level=ThreatLevel.CRITICAL, enabled=True,
        )}
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            rows = generator._screen_watchlist(df)
        assert rows[0]["detected"] is True
        assert rows[0]["reads"] == 500


class TestReportSurfacesThreat:
    """End-to-end: a detected watchlist pathogen must reach the rendered
    report and the machine-readable summary -- the user-visible payoff of the
    screening fix."""

    def test_detected_threat_in_html_and_summary(self, generator, tmp_path):
        entries = {1392: WatchlistEntry(
            taxid=1392, name="Bacillus anthracis",
            threat_level=ThreatLevel.CRITICAL, enabled=True,
        )}
        out = tmp_path / "export"
        with patch(
            "nanometa_live.core.export.report_generator.load_kraken_data",
            return_value=_kraken_df(),
        ), patch(_MGR_PATH, return_value=_mock_manager(entries)):
            generator.generate(str(out), include_raw=False)

        html = (out / "report.html").read_text()
        assert "Bacillus anthracis" in html
        assert "DETECTED" in html
        assert "ACTION REQUIRED" in html  # critical detected -> banner

        summary = json.loads((out / "summary.json").read_text())
        detected = summary["watched_species_detected"]
        assert detected and detected[0]["name"] == "Bacillus anthracis"


class TestRawCopy:
    """Cover the expanded raw-dir set, AppleDouble exclusion, and size cap."""

    def _gen(self, results_dir, config=None):
        g = ReportGenerator(str(results_dir), config or {})
        # Pin results_dir to the controlled tree (bypass auto-resolution).
        g.results_dir = str(results_dir)
        return g

    def test_copies_seqkit_and_excludes_sidecars(self, tmp_path):
        res = tmp_path / "res"
        (res / "seqkit").mkdir(parents=True)
        (res / "seqkit" / "sampleA.tsv").write_text("data")
        (res / "seqkit" / "._sampleA.tsv").write_text("apple-double junk")
        (res / "kraken2").mkdir()
        (res / "kraken2" / "a.kraken2.report.txt").write_text("data")
        out = tmp_path / "export"
        out.mkdir()

        copied = self._gen(res)._copy_raw_files(str(out))

        assert "seqkit" in copied and "kraken2" in copied
        assert (out / "raw" / "seqkit" / "sampleA.tsv").exists()
        assert not (out / "raw" / "seqkit" / "._sampleA.tsv").exists()

    def test_size_cap_skips_copy(self, tmp_path):
        res = tmp_path / "res"
        (res / "kraken2").mkdir(parents=True)
        (res / "kraken2" / "big.txt").write_text("x" * 4096)
        out = tmp_path / "export"
        out.mkdir()

        g = self._gen(res, {"export_max_raw_bytes": 100})  # 100-byte ceiling
        copied = g._copy_raw_files(str(out))

        assert copied == []
        assert not (out / "raw").exists()

    def test_metadata_records_raw_included(self, tmp_path):
        res = tmp_path / "res"
        (res / "kraken2").mkdir(parents=True)
        (res / "kraken2" / "a.kraken2.report.txt").write_text("data")
        out = tmp_path / "export"

        self._gen(res).generate(str(out), include_raw=True)

        meta = json.loads((out / "metadata.json").read_text())
        assert "kraken2" in meta["raw_files_included"]


class TestExtractOrganisms:
    """Top-organisms extraction: species-only, kraken %-column abundance."""

    def _df(self):
        # A genus row whose reads include its species (clade semantics) plus a
        # standalone species. The genus must NOT appear in the output.
        return pd.DataFrame([
            {"taxid": 1386, "name": "Bacillus", "rank": "G", "reads": 800, "%": 80.0},
            {"taxid": 1392, "name": "Bacillus anthracis", "rank": "S", "reads": 500, "%": 50.0},
            {"taxid": 1423, "name": "Bacillus subtilis", "rank": "S", "reads": 300, "%": 30.0},
        ])

    def test_species_only_no_genus_double_count(self, generator):
        orgs = generator._extract_organisms(self._df())
        names = [o["name"] for o in orgs]
        assert "Bacillus" not in names  # genus excluded
        assert names == ["Bacillus anthracis", "Bacillus subtilis"]  # reads desc

    def test_abundance_from_percent_column(self, generator):
        orgs = generator._extract_organisms(self._df())
        anthracis = next(o for o in orgs if o["name"] == "Bacillus anthracis")
        assert anthracis["abundance"] == 50.0  # kraken % column, not reads/sum
        assert all(o["abundance"] <= 100 for o in orgs)

    def test_fallback_uses_total_reads_denominator(self, generator):
        # No %/fraction columns -> fall back to fraction of total (classified +
        # unclassified) reads, not the per-rank reads sum.
        df = pd.DataFrame([
            {"taxid": 0, "name": "unclassified", "rank": "U", "reads": 100, "cumul_reads": 100},
            {"taxid": 1, "name": "root", "rank": "R", "reads": 0, "cumul_reads": 900},
            {"taxid": 1392, "name": "Bacillus anthracis", "rank": "S", "reads": 500, "cumul_reads": 500},
        ])
        orgs = generator._extract_organisms(df)
        # 500 / (900 + 100) total reads = 50%
        assert orgs[0]["abundance"] == 50.0
