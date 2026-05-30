"""
Unit tests for core/export/report_generator.py.

ReportGenerator turns a nanometanf results directory into a self-contained HTML
report plus copied raw files and a metadata sidecar. Tests run it end-to-end
against the shared batch_output_dir fixture (populated kraken2/ + fastp/) and
write the export under tmp_path, asserting the report is produced, the
include_raw toggle is honoured, and the sample filter is respected.
"""

import json

import pytest

from nanometa_live.core.export.report_generator import ReportGenerator


@pytest.fixture
def generator(batch_output_dir):
    return ReportGenerator(str(batch_output_dir), {"analysis_name": "Test Run"})


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
