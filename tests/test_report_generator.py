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


class TestScreenWatchlistPerSample:
    """The archived report has to say WHICH barcode a hit came from; an
    aggregate-only screen tells the operator a pathogen is in the run but not
    where, which is not actionable."""

    def _entries(self):
        return {1392: WatchlistEntry(
            taxid=1392, name="Bacillus anthracis",
            threat_level=ThreatLevel.CRITICAL, enabled=True,
        )}

    def _sample_frame(self, reads):
        df = _kraken_df()
        df.loc[df["name"] == "Bacillus anthracis", "reads"] = reads
        df.loc[df["name"] == "Bacillus anthracis", "cumul_reads"] = reads
        return df

    def test_detected_rows_carry_a_sample_breakdown(self, generator):
        frames = {
            "barcode01": self._sample_frame(400),
            "barcode02": self._sample_frame(100),
        }
        with patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            rows = generator._screen_watchlist(_kraken_df(), frames)
        breakdown = rows[0]["samples"]
        # Sorted by read support, highest first.
        assert [s["sample"] for s in breakdown] == ["barcode01", "barcode02"]
        assert [s["reads"] for s in breakdown] == [400, 100]

    def test_samples_without_the_organism_are_omitted(self, generator):
        clean = _kraken_df()
        clean = clean[clean["name"] != "Bacillus anthracis"]
        frames = {"barcode01": self._sample_frame(400), "barcode02": clean}
        with patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            rows = generator._screen_watchlist(_kraken_df(), frames)
        assert [s["sample"] for s in rows[0]["samples"]] == ["barcode01"]

    def test_undetected_entry_has_no_breakdown(self, generator):
        entries = {99999: WatchlistEntry(
            taxid=99999, name="Yersinia pestis",
            threat_level=ThreatLevel.HIGH, enabled=True,
        )}
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            rows = generator._screen_watchlist(
                _kraken_df(), {"barcode01": _kraken_df()}
            )
        assert rows[0]["samples"] == []

    def test_aggregate_only_call_still_works(self, generator):
        """Callers that pass no per-sample frames keep the old behaviour."""
        with patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            rows = generator._screen_watchlist(_kraken_df())
        assert rows[0]["detected"] is True
        assert rows[0]["samples"] == []


class TestNegativeControlReporting:
    """A watchlist detection carried by a declared negative control must be
    reported (per CLAUDE.md's "Negative controls" contract), never treated as
    an ordinary triggering sample and never suppressed. Mirrors
    core.utils.attribution.build_pathogen_attribution, which the dashboard
    uses for the same contract."""

    def _entries(self):
        return {1392: WatchlistEntry(
            taxid=1392, name="Bacillus anthracis",
            threat_level=ThreatLevel.CRITICAL, enabled=True,
        )}

    def _sample_frame(self, reads):
        df = _kraken_df()
        df.loc[df["name"] == "Bacillus anthracis", "reads"] = reads
        df.loc[df["name"] == "Bacillus anthracis", "cumul_reads"] = reads
        return df

    def _gen(self, results_dir, negative_control_samples):
        g = ReportGenerator(
            str(results_dir),
            {"analysis_name": "Test Run",
             "negative_control_samples": negative_control_samples},
        )
        g.results_dir = str(results_dir)
        return g

    def test_control_excluded_from_triggering_samples(self, tmp_path):
        generator = self._gen(tmp_path, ["barcode02"])
        frames = {
            "barcode01": self._sample_frame(400),
            "barcode02": self._sample_frame(6),
        }
        with patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            rows = generator._screen_watchlist(_kraken_df(), frames)
        w = rows[0]
        assert [s["sample"] for s in w["triggering_samples"]] == ["barcode01"]
        assert [s["sample"] for s in w["negative_control_rows"]] == ["barcode02"]
        assert w["negative_control_rows"][0]["reads"] == 6
        assert w["control_only"] is False
        # The full breakdown (back-compat) still carries both samples.
        assert {s["sample"] for s in w["samples"]} == {"barcode01", "barcode02"}

    def test_control_only_detection_is_flagged_not_suppressed(self, tmp_path):
        generator = self._gen(tmp_path, ["barcode02"])
        frames = {
            "barcode01": self._sample_frame(0),
            "barcode02": self._sample_frame(6),
        }
        clean = _kraken_df()
        clean.loc[clean["name"] == "Bacillus anthracis", "reads"] = 0
        clean.loc[clean["name"] == "Bacillus anthracis", "cumul_reads"] = 0
        frames["barcode01"] = clean
        with patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            rows = generator._screen_watchlist(_kraken_df(), frames)
        w = rows[0]
        # Still a detection -- a control never removes a real aggregate hit.
        assert w["detected"] is True
        assert w["triggering_samples"] == []
        assert w["control_only"] is True
        assert [s["sample"] for s in w["negative_control_rows"]] == ["barcode02"]

    def test_no_negative_controls_declared_behaves_as_before(self, generator):
        frames = {
            "barcode01": self._sample_frame(400),
            "barcode02": self._sample_frame(100),
        }
        with patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            rows = generator._screen_watchlist(_kraken_df(), frames)
        w = rows[0]
        assert w["negative_control_rows"] == []
        assert w["control_only"] is False
        assert [s["sample"] for s in w["triggering_samples"]] == ["barcode01", "barcode02"]

    def test_report_html_renders_negative_control_note(self, tmp_path):
        generator = self._gen(tmp_path, ["barcode02"])
        per_sample = {
            "barcode01": self._sample_frame(400),
            "barcode02": self._sample_frame(6),
        }

        def _load(results_dir, sample=None):
            return per_sample.get(sample, _kraken_df())

        out = tmp_path / "export"
        with patch(
            "nanometa_live.core.export.report_generator.load_kraken_data",
            side_effect=_load,
        ), patch(
            "nanometa_live.core.export.report_generator.get_available_samples",
            return_value=["barcode01", "barcode02"],
        ), patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            generator.generate(str(out), include_raw=False)
        html = (out / "report.html").read_text()
        assert "negative control" in html.lower()
        assert "barcode02" in html

    def test_report_html_control_only_says_so(self, tmp_path):
        generator = self._gen(tmp_path, ["barcode02"])
        clean = _kraken_df()
        clean.loc[clean["name"] == "Bacillus anthracis", "reads"] = 0
        clean.loc[clean["name"] == "Bacillus anthracis", "cumul_reads"] = 0
        per_sample = {
            "barcode01": clean,
            "barcode02": self._sample_frame(6),
        }

        def _load(results_dir, sample=None):
            return per_sample.get(sample, _kraken_df())

        out = tmp_path / "export"
        with patch(
            "nanometa_live.core.export.report_generator.load_kraken_data",
            side_effect=_load,
        ), patch(
            "nanometa_live.core.export.report_generator.get_available_samples",
            return_value=["barcode01", "barcode02"],
        ), patch(_MGR_PATH, return_value=_mock_manager(self._entries())):
            generator.generate(str(out), include_raw=False)
        html = (out / "report.html").read_text()
        assert "negative control only" in html.lower()


class TestPerSampleAttemptedNoOutput:
    """_manifest.json predicts a sample's output files without verifying
    them; a stage failure absorbed by nanometanf's error isolation must not
    render identically to a genuine zero-read negative. Mirrors the
    dashboard's available-samples-vs-sample-file-mapping comparison
    (CLAUDE.md), applied on the export side. Audit 2026-08-16, finding W9."""

    def test_sample_with_no_files_is_flagged(self, generator):
        with patch(
            "nanometa_live.core.export.report_generator.get_sample_file_mapping",
            return_value={"barcode01": {"kraken2": ["/x/barcode01.kraken2.report.txt"]}},
        ):
            per_sample = generator._per_sample_data(
                ["barcode01", "barcode02"],
                {"barcode01": _kraken_df(), "barcode02": pd.DataFrame()},
            )
        assert per_sample["barcode01"]["attempted_no_output"] is False
        assert per_sample["barcode02"]["attempted_no_output"] is True

    def test_report_html_flags_the_sample_visibly(self, tmp_path):
        g = ReportGenerator(str(tmp_path), {"analysis_name": "Test Run"})
        g.results_dir = str(tmp_path)
        out = tmp_path / "export"

        def _load(results_dir, sample=None):
            return _kraken_df() if sample == "barcode01" else pd.DataFrame()

        with patch(
            "nanometa_live.core.export.report_generator.load_kraken_data",
            side_effect=_load,
        ), patch(
            "nanometa_live.core.export.report_generator.get_available_samples",
            return_value=["barcode01", "barcode02"],
        ), patch(
            "nanometa_live.core.export.report_generator.get_sample_file_mapping",
            return_value={"barcode01": {"kraken2": ["/x/barcode01.kraken2.report.txt"]}},
        ):
            g.generate(str(out), include_raw=False)

        html = (out / "report.html").read_text()
        assert "no output" in html.lower()
        # The caveat must be attached to the flagged sample only.
        assert html.index("barcode02") < html.index("No output files found")

    def test_sample_with_files_is_not_flagged_in_html(self, tmp_path):
        g = ReportGenerator(str(tmp_path), {"analysis_name": "Test Run"})
        g.results_dir = str(tmp_path)
        out = tmp_path / "export"
        with patch(
            "nanometa_live.core.export.report_generator.load_kraken_data",
            return_value=_kraken_df(),
        ), patch(
            "nanometa_live.core.export.report_generator.get_available_samples",
            return_value=["barcode01"],
        ), patch(
            "nanometa_live.core.export.report_generator.get_sample_file_mapping",
            return_value={"barcode01": {"kraken2": ["/x/barcode01.kraken2.report.txt"]}},
        ):
            g.generate(str(out), include_raw=False)
        html = (out / "report.html").read_text()
        assert "No output files found" not in html


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


class TestRawSkipDoesNotDangle:
    """W10: Pipeline Reports links must never point at a raw/ tree that was
    skipped (size cap) or a subdir that failed to copy, and the skip must be
    visible in both the HTML and metadata.json rather than a silent 404.
    Audit 2026-08-16, finding W10."""

    def _gen(self, results_dir, config=None):
        g = ReportGenerator(str(results_dir), config or {})
        g.results_dir = str(results_dir)
        return g

    def _with_multiqc_report(self, res):
        (res / "multiqc").mkdir(parents=True)
        (res / "multiqc" / "multiqc_report.html").write_text("<html>mqc</html>")

    def test_size_cap_skip_produces_no_pipeline_report_links(self, tmp_path):
        res = tmp_path / "res"
        self._with_multiqc_report(res)
        (res / "multiqc" / "big.bin").write_bytes(b"x" * 4096)
        out = tmp_path / "export"

        g = self._gen(res, {"export_max_raw_bytes": 100})
        report_file = g.generate(str(out), include_raw=True)

        # No dangling href: the whole raw/ tree was skipped by the cap.
        assert not (out / "raw").exists()
        html = report_file.read_text()
        assert 'href="raw/' not in html
        assert "omitted" in html.lower()

        meta = json.loads((out / "metadata.json").read_text())
        assert meta["raw_files_included"] == []
        assert meta["raw_skip_reason"]
        assert "gib" in meta["raw_skip_reason"].lower() or "cap" in meta["raw_skip_reason"].lower()

    def test_normal_copy_has_no_skip_reason_and_links_resolve(self, tmp_path):
        res = tmp_path / "res"
        self._with_multiqc_report(res)
        out = tmp_path / "export"

        g = self._gen(res)
        report_file = g.generate(str(out), include_raw=True)

        html = report_file.read_text()
        assert 'href="raw/multiqc/multiqc_report.html"' in html
        assert (out / "raw" / "multiqc" / "multiqc_report.html").exists()

        meta = json.loads((out / "metadata.json").read_text())
        assert meta["raw_skip_reason"] is None

    def test_partial_subdir_failure_omits_only_that_subdirs_links(self, tmp_path, monkeypatch):
        res = tmp_path / "res"
        self._with_multiqc_report(res)
        (res / "kraken2").mkdir()
        (res / "kraken2" / "a.kraken2.report.txt").write_text("data")
        out = tmp_path / "export"

        import shutil as _sh
        real_copytree = _sh.copytree

        def failing_copytree(src, dst, *a, **kw):
            if str(src).endswith("multiqc"):
                raise OSError("simulated copy failure")
            return real_copytree(src, dst, *a, **kw)

        monkeypatch.setattr(
            "nanometa_live.core.export.report_generator.shutil.copytree",
            failing_copytree,
        )

        g = self._gen(res)
        report_file = g.generate(str(out), include_raw=True)

        html = report_file.read_text()
        # multiqc failed to copy -> its link must not appear.
        assert 'href="raw/multiqc/' not in html
        # kraken2 copied fine -> unaffected.
        assert (out / "raw" / "kraken2" / "a.kraken2.report.txt").exists()
        assert "omitted" in html.lower()

        meta = json.loads((out / "metadata.json").read_text())
        assert "multiqc" in meta["raw_skip_reason"]
        assert "multiqc" not in meta["raw_files_included"]
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


class TestDecisionBannerCannotClaimAnUnearnedNegative:
    """The banner must not announce a finding that was never produced.

    Found 2026-07-29 by generating a report from a real results tree with no
    watchlist configured. The banner read

        NO WATCHED ORGANISMS DETECTED

    in the green "safe" style, while Francisella tularensis -- an HHS Tier 1
    select agent -- appeared in the report's own organism table at 34,096
    reads. Nothing had been screened, so there was no negative result to
    report.

    This is the same defect fixed on the dashboard in round 2
    (select_verdict -> NOT_SCREENED). It matters more here: the report is the
    artifact handed to someone else, and it outlives the session that made it.

    The template branch is report.html: `{% elif not data.watched_results %}`.
    """

    def _render(self, generator, watched_results):
        """Render the banner region with a given screened set."""
        from jinja2 import Environment, FileSystemLoader
        import pathlib

        template_dir = (
            pathlib.Path(generator.__class__.__module__.replace(".", "/")).parent
        )
        import nanometa_live.core.export.report_generator as rg

        tdir = pathlib.Path(rg.__file__).parent / "templates"
        env = Environment(loader=FileSystemLoader(str(tdir)), autoescape=True)
        env.filters["format_number"] = lambda v: f"{v:,}" if isinstance(v, (int, float)) else str(v)
        env.filters["format_pct"] = lambda v: f"{v:.1f}%" if isinstance(v, (int, float)) else str(v)
        src = (tdir / "report.html").read_text()
        # Render only the banner block, so this test does not depend on the
        # rest of the report's data contract.
        start = src.index("{% if critical_threats or high_threats %}")
        end = src.index("{% endif %}", start) + len("{% endif %}")
        block = (
            "{% set detected_threats = data.watched_results | selectattr('detected') | list %}"
            "{% set critical_threats = detected_threats | selectattr('threat_level', 'equalto', 'critical') | list %}"
            "{% set high_threats = detected_threats | selectattr('threat_level', 'equalto', 'high') | list %}"
            + src[start:end]
        )
        return env.from_string(block).render(data={"watched_results": watched_results})

    def test_nothing_screened_does_not_claim_a_negative(self, generator):
        out = self._render(generator, [])
        assert "NOT SCREENED" in out, (
            f"with an empty watchlist the banner should say screening did not "
            f"happen; got: {out.strip()[:200]}"
        )
        assert "NO WATCHED ORGANISMS DETECTED" not in out, (
            "the banner still announces a negative finding that was never produced"
        )

    def test_nothing_screened_is_not_styled_safe(self, generator):
        """Wording alone is not enough: a green banner reads as reassurance."""
        out = self._render(generator, [])
        assert "banner-safe" not in out, (
            "the not-screened banner uses the safe (green) style, which reads "
            "as an all-clear regardless of its wording"
        )

    def test_a_genuine_negative_still_reads_as_clear(self, generator):
        """The real all-clear must survive, and say what was screened."""
        screened = [
            {"detected": False, "threat_level": "critical", "name": "Bacillus anthracis"},
            {"detected": False, "threat_level": "high", "name": "Yersinia pestis"},
        ]
        out = self._render(generator, screened)
        assert "NO WATCHED ORGANISMS DETECTED" in out
        assert "banner-safe" in out
        assert "2 organisms screened" in out, (
            f"a genuine all-clear should state how many organisms were "
            f"screened, so it cannot be confused with the unscreened case: "
            f"{out.strip()[:200]}"
        )

    def test_a_detection_still_raises_action_required(self, generator):
        detected = [
            {"detected": True, "threat_level": "critical", "name": "Francisella tularensis"},
        ]
        out = self._render(generator, detected)
        assert "ACTION REQUIRED" in out
        assert "banner-action" in out


class TestChartJsonCannotBreakOutOfScript:
    """The inlined chart JSON must not be able to terminate its <script>.

    ``json.dumps`` does not escape "/", and the template embeds the charts
    dict with ``| safe`` inside a <script> element -- so a string reaching
    the chart payload (a sample or organism name; watchlist YAML upload is
    an external-input path) containing the literal "</script>" closed the
    element at the HTML-parser level and any following markup executed in
    the reader's browser. The report is designed to leave the machine.
    Audit 2026-08-16, finding W4.
    """

    def test_script_close_tag_in_chart_payload_is_escaped(
        self, generator, tmp_path, monkeypatch
    ):
        hostile = {
            "donut": '{"title": "a</script><script>alert(1)</script>"}'
        }
        monkeypatch.setattr(generator, "_build_charts", lambda data: hostile)

        out = tmp_path / "export"
        report = generator.generate(str(out), include_raw=False)
        html = report.read_text()

        assert "</script><script>alert(1)" not in html, (
            "a chart string terminated the script element; following "
            "markup executes in the reader's browser"
        )
        # The payload survives, JSON-escaped so the HTML parser cannot
        # see a close tag.
        assert "<\\/script>" in html


class TestScreenWatchlistEntryIsolation:
    """One malformed watchlist entry must cost only that entry.

    The whole per-entry loop sat in a single try/except, so an exception on
    entry N dropped entries N+1..end and returned a partial (often empty)
    list -- rendering the false "NOT SCREENED" banner while a true positive
    later in iteration order was silently unscreened. Audit 2026-08-16,
    finding W3.
    """

    class _ExplodingEntry:
        """Attribute access raises, as a corrupt/malformed entry would."""
        name = "Broken entry"
        taxid = 632
        db_taxid = None

        @property
        def threat_level(self):
            raise ValueError("corrupt entry")

    def test_bad_entry_does_not_blank_the_screen(self, generator):
        good = WatchlistEntry(
            taxid=1392, name="Bacillus anthracis",
            threat_level=ThreatLevel.HIGH, enabled=True,
        )
        bad = self._ExplodingEntry()

        # The bad entry iterates FIRST, so without per-entry isolation the
        # good entry is never screened.
        entries = {632: bad, 1392: good}
        with patch(_MGR_PATH, return_value=_mock_manager(entries)):
            results = generator._screen_watchlist(_kraken_df(), {})

        names = [r["name"] for r in results]
        assert "Bacillus anthracis" in names, (
            "a malformed sibling entry unscreened every entry after it"
        )
        detected = [r for r in results if r["detected"]]
        assert detected and detected[0]["reads"] == 500
