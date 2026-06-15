"""Optional follow-on: the exported standalone report links the pipeline reports.

The export already copies multiqc/ + pipeline_info/ into raw/; this surfaces
links to them in the exported HTML (only when raw is included, so they never
dangle).
"""

from pathlib import Path

import pytest

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
    (base / "multiqc").mkdir()
    (base / "multiqc" / "multiqc_report.html").write_text("<html>mqc</html>")
    (base / "pipeline_info").mkdir()
    (base / "pipeline_info" / "execution_report_2026-06-15.html").write_text("<html>e</html>")
    return base


def test_export_links_and_copies_reports(tmp_path):
    results = _results(tmp_path)
    out = tmp_path / "export"
    gen = ReportGenerator(str(results), {"analysis_name": "Test"})
    report = gen.generate(str(out), include_raw=True)

    html = Path(report).read_text()
    assert "Pipeline Reports" in html
    assert 'href="raw/multiqc/multiqc_report.html"' in html
    assert 'raw/pipeline_info/execution_report_2026-06-15.html' in html
    # MultiQC was actually bundled (so the link resolves offline).
    assert (out / "raw" / "multiqc" / "multiqc_report.html").exists()


def test_no_links_without_raw(tmp_path):
    results = _results(tmp_path)
    out = tmp_path / "export_noraw"
    gen = ReportGenerator(str(results), {"analysis_name": "Test"})
    report = gen.generate(str(out), include_raw=False)
    # Links would dangle without the bundled files, so the section is omitted.
    assert "Pipeline Reports" not in Path(report).read_text()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
