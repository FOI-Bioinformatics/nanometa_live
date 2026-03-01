"""
Unit tests for NanometanfOutputParser class.

Tests all parsing methods with mock data structures matching nanometanf v1.1.0 outputs.
"""

import os
import json
import tempfile
import pytest
from pathlib import Path
import pandas as pd

from nanometa_live.core.parsers import NanometanfOutputParser, RealtimeMonitor


class TestNanometanfOutputParser:
    """Test suite for NanometanfOutputParser class."""

    @pytest.fixture
    def mock_outdir(self, tmp_path):
        """Create a mock nanometanf output directory structure."""
        outdir = tmp_path / "results"
        outdir.mkdir()

        # Create subdirectories
        (outdir / "multiqc" / "multiqc_data").mkdir(parents=True)
        (outdir / "fastp").mkdir()
        (outdir / "kraken2").mkdir()
        (outdir / "validation" / "blast").mkdir(parents=True)
        (outdir / "realtime_batch_stats").mkdir()

        return outdir

    @pytest.fixture
    def parser(self, mock_outdir):
        """Create parser instance with mock output directory."""
        return NanometanfOutputParser(str(mock_outdir))

    def test_parser_initialization(self, mock_outdir):
        """Test parser initializes with correct directory structure."""
        parser = NanometanfOutputParser(str(mock_outdir))

        assert parser.outdir == Path(mock_outdir)
        assert parser.multiqc_dir == Path(mock_outdir) / "multiqc"
        assert parser.fastp_dir == Path(mock_outdir) / "fastp"
        assert parser.kraken2_dir == Path(mock_outdir) / "kraken2"
        assert parser.blast_dir == Path(mock_outdir) / "validation" / "blast"
        assert parser.realtime_batch_dir == Path(mock_outdir) / "realtime_batch_stats"

    def test_file_exists_with_retry(self, parser, tmp_path):
        """Test file existence checking with retry logic."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # File exists
        assert parser.file_exists_with_retry(str(test_file)) is True

        # File doesn't exist
        assert parser.file_exists_with_retry(str(tmp_path / "nonexistent.txt")) is False

    def test_parse_multiqc_general_stats(self, parser, mock_outdir):
        """Test MultiQC general stats parsing."""
        # Create mock general stats file
        stats_file = mock_outdir / "multiqc" / "multiqc_data" / "multiqc_general_stats.txt"
        stats_data = "Sample\tFASTQ Total Reads\tKraken Classified %\n"
        stats_data += "sample1\t10000\t95.5\n"
        stats_data += "sample2\t20000\t92.3\n"
        stats_file.write_text(stats_data)

        df = parser.parse_multiqc_general_stats()

        assert len(df) == 2
        assert "sample1" in df.index
        assert "sample2" in df.index

    def test_parse_multiqc_general_stats_missing(self, parser):
        """Test MultiQC general stats parsing when file is missing."""
        df = parser.parse_multiqc_general_stats()

        assert df.empty
        assert isinstance(df, pd.DataFrame)

    def test_parse_kraken_report(self, parser, mock_outdir):
        """Test Kraken2 report parsing."""
        # Create mock Kraken2 report
        kraken_file = mock_outdir / "kraken2" / "sample1.kreport2"
        kraken_data = "0.15\t300\t300\tU\t0\tunclassified\n"
        kraken_data += "99.85\t19970\t0\tR\t1\troot\n"
        kraken_data += "99.85\t19970\t100\tD\t2\tBacteria\n"
        kraken_data += "50.00\t10000\t50\tP\t1239\tFirmicutes\n"
        kraken_data += "25.00\t5000\t100\tS\t1350\tEnterococcus faecalis\n"
        kraken_file.write_text(kraken_data)

        df = parser.parse_kraken_report("sample1")

        assert len(df) == 5
        assert list(df.columns) == ['percent', 'reads_clade', 'reads_taxon', 'rank', 'taxid', 'name']
        assert df.iloc[0]['rank'] == 'U'
        assert df.iloc[0]['taxid'] == 0
        assert df.iloc[4]['name'] == 'Enterococcus faecalis'

    def test_parse_kraken_report_missing(self, parser):
        """Test Kraken2 report parsing when file is missing."""
        df = parser.parse_kraken_report("nonexistent_sample")

        assert df.empty
        assert list(df.columns) == ['percent', 'reads_clade', 'reads_taxon', 'rank', 'taxid', 'name']

    def test_combine_kraken_reports(self, parser, mock_outdir):
        """Test combining multiple Kraken2 reports."""
        # Create mock reports for two samples
        for sample in ["sample1", "sample2"]:
            kraken_file = mock_outdir / "kraken2" / f"{sample}.kreport2"
            kraken_data = f"0.15\t300\t300\tU\t0\tunclassified\n"
            kraken_data += f"99.85\t19970\t0\tR\t1\troot\n"
            kraken_data += f"50.00\t10000\t100\tS\t1350\tEnterococcus faecalis\n"
            kraken_file.write_text(kraken_data)

        df = parser.combine_kraken_reports()

        assert len(df) == 6  # 3 entries x 2 samples
        assert 'sample' in df.columns
        assert 'sample1' in df['sample'].values
        assert 'sample2' in df['sample'].values

    def test_get_top_species(self, parser, mock_outdir):
        """Test getting top species by read count."""
        # Create mock reports with species data
        kraken_file = mock_outdir / "kraken2" / "sample1.kreport2"
        kraken_data = "0.15\t300\t300\tU\t0\tunclassified\n"
        kraken_data += "99.85\t19970\t0\tR\t1\troot\n"
        kraken_data += "50.00\t10000\t100\tS\t1350\tEnterococcus faecalis\n"
        kraken_data += "30.00\t6000\t100\tS\t562\tEscherichia coli\n"
        kraken_data += "10.00\t2000\t100\tS\t1280\tStaphylococcus aureus\n"
        kraken_file.write_text(kraken_data)

        df = parser.get_top_species(n=2)

        assert len(df) == 2
        assert df.iloc[0]['taxid'] == 1350  # Highest read count
        assert df.iloc[0]['total_reads'] == 10000

    def test_parse_fastp_report(self, parser, mock_outdir):
        """Test FASTP JSON report parsing."""
        # Create mock FASTP JSON
        fastp_file = mock_outdir / "fastp" / "sample1.fastp.json"
        fastp_data = {
            "summary": {
                "before_filtering": {
                    "total_reads": 10000,
                    "total_bases": 5000000,
                    "q20_rate": 0.95,
                    "q30_rate": 0.90,
                    "gc_content": 0.45
                },
                "after_filtering": {
                    "total_reads": 9500,
                    "total_bases": 4750000,
                    "q20_rate": 0.97,
                    "q30_rate": 0.92,
                    "gc_content": 0.45
                }
            },
            "filtering_result": {
                "passed_filter_reads": 9500,
                "low_quality_reads": 300,
                "too_short_reads": 200
            }
        }
        fastp_file.write_text(json.dumps(fastp_data))

        data = parser.parse_fastp_report("sample1")

        assert data["summary"]["before_filtering"]["total_reads"] == 10000
        assert data["filtering_result"]["passed_filter_reads"] == 9500

    def test_combine_fastp_reports(self, parser, mock_outdir):
        """Test combining multiple FASTP reports."""
        # Create mock FASTP reports
        for i, sample in enumerate(["sample1", "sample2"]):
            fastp_file = mock_outdir / "fastp" / f"{sample}.fastp.json"
            fastp_data = {
                "summary": {
                    "before_filtering": {
                        "total_reads": 10000 * (i + 1),
                        "total_bases": 5000000 * (i + 1),
                        "q20_rate": 0.95,
                        "q30_rate": 0.90,
                        "gc_content": 0.45
                    },
                    "after_filtering": {
                        "total_reads": 9500 * (i + 1),
                        "total_bases": 4750000 * (i + 1),
                        "q20_rate": 0.97,
                        "q30_rate": 0.92,
                        "gc_content": 0.45
                    }
                },
                "filtering_result": {
                    "passed_filter_reads": 9500 * (i + 1),
                    "low_quality_reads": 300,
                    "too_short_reads": 200
                }
            }
            fastp_file.write_text(json.dumps(fastp_data))

        df = parser.combine_fastp_reports()

        assert len(df) == 2
        assert 'sample1' in df['sample'].values
        assert 'sample2' in df['sample'].values
        assert df[df['sample'] == 'sample2']['total_reads_before'].values[0] == 20000

    def test_get_fastp_summary(self, parser, mock_outdir):
        """Test FASTP summary statistics."""
        # Create mock FASTP report
        fastp_file = mock_outdir / "fastp" / "sample1.fastp.json"
        fastp_data = {
            "summary": {
                "before_filtering": {
                    "total_reads": 10000,
                    "total_bases": 5000000,
                    "q20_rate": 0.95,
                    "q30_rate": 0.90,
                    "gc_content": 0.45
                },
                "after_filtering": {
                    "total_reads": 9500,
                    "total_bases": 4750000,
                    "q20_rate": 0.97,
                    "q30_rate": 0.92,
                    "gc_content": 0.45
                }
            },
            "filtering_result": {
                "passed_filter_reads": 9500,
                "low_quality_reads": 300,
                "too_short_reads": 200
            }
        }
        fastp_file.write_text(json.dumps(fastp_data))

        summary = parser.get_fastp_summary()

        assert summary['total_samples'] == 1
        assert summary['total_reads_before'] == 10000
        assert summary['total_reads_after'] == 9500
        assert summary['total_passed_filter'] == 9500

    def test_parse_blast_results(self, parser, mock_outdir):
        """Test BLAST results parsing."""
        # Create mock BLAST output (nanometanf v1.1+ publishes to validation/blast/)
        blast_file = mock_outdir / "validation" / "blast" / "sample1_1350.blast.txt"
        blast_data = "read1\tref1\t98.5\t500\t2\t1\t1\t500\t1\t500\t1e-100\t900\n"
        blast_data += "read2\tref2\t95.0\t450\t5\t2\t1\t450\t1\t450\t1e-80\t800\n"
        blast_file.write_text(blast_data)

        df = parser.parse_blast_results("sample1", "1350")

        assert len(df) == 2
        assert df.iloc[0]['pident'] == 98.5
        assert df.iloc[0]['length'] == 500

    def test_parse_batch_stats(self, parser, mock_outdir):
        """Test batch statistics parsing."""
        # Create mock batch stats
        batch_file = mock_outdir / "realtime_batch_stats" / "batch_0001_stats.json"
        batch_data = {
            "batch_number": 1,
            "timestamp": "2025-10-06T12:34:56",
            "files_in_batch": 10,
            "reads_in_batch": 50000,
            "classified_in_batch": 45000,
            "unclassified_in_batch": 5000
        }
        batch_file.write_text(json.dumps(batch_data))

        data = parser.parse_batch_stats(1)

        assert data['batch_number'] == 1
        assert data['reads_in_batch'] == 50000
        assert data['classified_in_batch'] == 45000

    def test_get_latest_batch_number(self, parser, mock_outdir):
        """Test getting latest batch number."""
        # Create mock batch files
        for i in range(1, 6):
            batch_file = mock_outdir / "realtime_batch_stats" / f"batch_{i:04d}_stats.json"
            batch_data = {"batch_number": i}
            batch_file.write_text(json.dumps(batch_data))

        latest = parser.get_latest_batch_number()

        assert latest == 5

    def test_get_latest_batch_number_empty(self, parser):
        """Test getting latest batch number when no batches exist."""
        latest = parser.get_latest_batch_number()

        assert latest == 0

    def test_parse_all_batch_stats(self, parser, mock_outdir):
        """Test parsing all batch statistics."""
        # Create mock batch files
        for i in range(1, 4):
            batch_file = mock_outdir / "realtime_batch_stats" / f"batch_{i:04d}_stats.json"
            batch_data = {
                "batch_number": i,
                "reads_in_batch": 10000 * i,
                "classified_in_batch": 9000 * i
            }
            batch_file.write_text(json.dumps(batch_data))

        all_batches = parser.parse_all_batch_stats()

        assert len(all_batches) == 3
        assert all_batches[0]['batch_number'] == 1
        assert all_batches[2]['reads_in_batch'] == 30000

    def test_get_cumulative_stats(self, parser, mock_outdir):
        """Test cumulative statistics calculation."""
        # Create mock batch files
        for i in range(1, 4):
            batch_file = mock_outdir / "realtime_batch_stats" / f"batch_{i:04d}_stats.json"
            batch_data = {
                "batch_number": i,
                "timestamp": f"2025-10-06T12:{i:02d}:00",
                "files_in_batch": 10,
                "reads_in_batch": 10000,
                "classified_in_batch": 9000,
                "unclassified_in_batch": 1000
            }
            batch_file.write_text(json.dumps(batch_data))

        stats = parser.get_cumulative_stats()

        assert stats['total_batches'] == 3
        assert stats['total_reads'] == 30000
        assert stats['total_classified'] == 27000
        assert stats['total_unclassified'] == 3000
        assert stats['classification_rate'] == 0.9

    def test_get_classification_summary(self, parser, mock_outdir):
        """Test comprehensive classification summary."""
        # Create mock Kraken2 report
        kraken_file = mock_outdir / "kraken2" / "sample1.kreport2"
        kraken_data = "5.00\t1000\t1000\tU\t0\tunclassified\n"
        kraken_data += "95.00\t19000\t0\tR\t1\troot\n"
        kraken_data += "50.00\t10000\t100\tS\t1350\tEnterococcus faecalis\n"
        kraken_file.write_text(kraken_data)

        summary = parser.get_classification_summary()

        assert 'kraken2' in summary
        assert 'overall' in summary
        assert summary['kraken2']['total_reads'] == 20000
        assert summary['kraken2']['classified'] == 19000
        assert summary['kraken2']['unclassified'] == 1000


class TestRealtimeMonitor:
    """Test suite for RealtimeMonitor class."""

    @pytest.fixture
    def mock_outdir(self, tmp_path):
        """Create mock output directory."""
        outdir = tmp_path / "results"
        outdir.mkdir()
        (outdir / "realtime_batch_stats").mkdir()
        return outdir

    def test_monitor_initialization(self, mock_outdir):
        """Test monitor initialization."""
        callback_called = []

        def test_callback(data):
            callback_called.append(data)

        monitor = RealtimeMonitor(str(mock_outdir), test_callback)

        assert monitor.parser.outdir == Path(mock_outdir)
        assert monitor.monitoring is False
        assert monitor.last_batch_number == 0

    def test_monitor_start_stop(self, mock_outdir):
        """Test starting and stopping monitor."""
        def test_callback(data):
            pass

        monitor = RealtimeMonitor(str(mock_outdir), test_callback)

        monitor.start_monitoring(interval=1)
        assert monitor.monitoring is True
        assert monitor.monitor_thread is not None

        monitor.stop_monitoring()
        assert monitor.monitoring is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
