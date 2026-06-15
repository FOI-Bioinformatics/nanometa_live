"""The nanometa-report CLI generates the operator report headless, and the
report's alert collection (previously broken) now surfaces pathogen/QC alerts.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from nanometa_live.cli import report as report_cli
from nanometa_live.core.export.report_generator import ReportGenerator

pytestmark = pytest.mark.unit

_KRAKEN = (
    " 0.00\t0\t0\tU\t0\tunclassified\n"
    "100.00\t100\t0\tR\t1\troot\n"
    "100.00\t100\t0\tD\t2\t  Bacteria\n"
    "100.00\t100\t100\tS\t562\t    Escherichia coli\n"
)


def _results(tmp_path):
    base = tmp_path / "results"
    (base / "kraken2").mkdir(parents=True)
    (base / "kraken2" / "barcode01.kraken2.report.txt").write_text(_KRAKEN)
    return base


class TestReportCLI:
    def test_generates_report_headless(self, tmp_path):
        results = _results(tmp_path)
        out = tmp_path / "report"
        argv = ["nanometa-report", "--results", str(results),
                "--output", str(out), "--no-raw"]
        with patch("sys.argv", argv):
            report_cli.main()
        assert (out / "report.html").exists()
        assert (out / "summary.json").exists()
        html = (out / "report.html").read_text()
        assert "Classification Summary" in html

    def test_missing_results_dir_exits(self, tmp_path):
        argv = ["nanometa-report", "--results", str(tmp_path / "nope")]
        with patch("sys.argv", argv), pytest.raises(SystemExit):
            report_cli.main()


class TestReportAlerts:
    def test_alerts_surface_detected_pathogen(self, tmp_path):
        # Regression: _collect_alerts called a non-existent engine method, so the
        # Alerts section was always empty. It now generates pathogen alerts from
        # the watchlist screen.
        gen = ReportGenerator(str(_results(tmp_path)), {"analysis_name": "t"})
        watched = [
            {"name": "Bacillus anthracis", "taxid": 1392, "threat_level": "critical",
             "reads": 37, "abundance": 0.05, "detected": True},
            {"name": "Yersinia pestis", "taxid": 632, "threat_level": "critical",
             "reads": 0, "abundance": 0.0, "detected": False},
        ]
        alerts = gen._collect_alerts(qc_stats=None, watched_results=watched)
        assert isinstance(alerts, list)
        assert any("Bacillus anthracis" in str(a) for a in alerts)

    def test_alerts_empty_without_watched(self, tmp_path):
        gen = ReportGenerator(str(_results(tmp_path)), {"analysis_name": "t"})
        # No detected pathogens, no qc -> no pathogen/QC alerts (no crash).
        alerts = gen._collect_alerts(qc_stats=None, watched_results=[])
        assert isinstance(alerts, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
