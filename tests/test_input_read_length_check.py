"""Too-short-input pre-flight: read-length probe + readiness check.

The QC length filter (default 1000 bp) discards ALL reads of a short-amplicon
run; chopper exits 0 on total loss and the run completes green with every
panel blank. The "Input Read Length" readiness check samples the input FASTQ
before launch and warns when the median read is below the filter -- the only
warning the operator gets for this failure mode.
"""

import gzip

import pytest

from nanometa_live.core.utils.read_length_probe import (
    find_input_fastqs,
    median_input_read_length,
    sample_read_lengths,
)
from nanometa_live.core.workflow.readiness_checker import ReadinessChecker, Severity

pytestmark = pytest.mark.unit


def _write_fastq(path, lengths, gz=False):
    records = []
    for i, n in enumerate(lengths):
        records.append(f"@read{i}\n{'A' * n}\n+\n{'I' * n}\n")
    data = "".join(records)
    if gz:
        with gzip.open(path, "wt") as fh:
            fh.write(data)
    else:
        path.write_text(data)


class TestReadLengthProbe:
    def test_plain_fastq(self, tmp_path):
        f = tmp_path / "s.fastq"
        _write_fastq(f, [300, 400, 350])
        assert sorted(sample_read_lengths(f)) == [300, 350, 400]

    def test_gzipped_fastq(self, tmp_path):
        f = tmp_path / "s.fastq.gz"
        _write_fastq(f, [1500, 1200], gz=True)
        assert sorted(sample_read_lengths(f)) == [1200, 1500]

    def test_max_reads_bounds_sampling(self, tmp_path):
        f = tmp_path / "s.fastq"
        _write_fastq(f, [100] * 50)
        assert len(sample_read_lengths(f, max_reads=10)) == 10

    def test_missing_file_returns_empty(self, tmp_path):
        assert sample_read_lengths(tmp_path / "absent.fastq") == []

    def test_find_flat_layout(self, tmp_path):
        _write_fastq(tmp_path / "a.fastq", [100])
        _write_fastq(tmp_path / "b.fq.gz", [100], gz=True)
        names = [p.name for p in find_input_fastqs(tmp_path)]
        assert names == ["a.fastq", "b.fq.gz"]

    def test_find_barcode_layout(self, tmp_path):
        bc = tmp_path / "barcode01"
        bc.mkdir()
        _write_fastq(bc / "run.fastq.gz", [100], gz=True)
        assert [p.name for p in find_input_fastqs(tmp_path)] == ["run.fastq.gz"]

    def test_hidden_appledouble_files_skipped(self, tmp_path):
        # macOS writes ._ sidecars on exFAT; they are not gzip and must not
        # be sampled (mirrors the pipeline's own hidden-file exclusion).
        (tmp_path / "._sample.fastq.gz").write_bytes(b"\x00\x05\x16\x07junk")
        _write_fastq(tmp_path / "sample.fastq", [250])
        assert [p.name for p in find_input_fastqs(tmp_path)] == ["sample.fastq"]

    def test_median_across_files(self, tmp_path):
        _write_fastq(tmp_path / "a.fastq", [300, 300])
        _write_fastq(tmp_path / "b.fastq", [1400])
        median, n, example = median_input_read_length(tmp_path)
        assert median == 300
        assert n == 3
        assert example == "a.fastq"

    def test_median_empty_dir(self, tmp_path):
        assert median_input_read_length(tmp_path) == (None, 0, None)


class TestInputReadLengthCheck:
    def _run(self, config):
        return ReadinessChecker()._check_input_read_length(config)

    def test_amplicon_reads_below_default_filter_warn(self, tmp_path):
        _write_fastq(tmp_path / "amplicons.fastq", [300] * 20)
        result = self._run({"nanopore_output_directory": str(tmp_path)})
        assert result.passed is False
        assert result.severity == Severity.WARNING
        assert "chopper_minlength = 1000" in result.message
        assert "amplicon" in (result.details or "").lower()

    def test_lowered_filter_passes(self, tmp_path):
        _write_fastq(tmp_path / "amplicons.fastq", [300] * 20)
        result = self._run({
            "nanopore_output_directory": str(tmp_path),
            "chopper_minlength": 100,
        })
        assert result.passed is True

    def test_long_reads_pass_default_filter(self, tmp_path):
        _write_fastq(tmp_path / "wgs.fastq", [5000] * 10)
        result = self._run({"nanopore_output_directory": str(tmp_path)})
        assert result.passed is True

    def test_no_input_dir_passes(self):
        result = self._run({})
        assert result.passed is True

    def test_empty_input_dir_passes(self, tmp_path):
        result = self._run({"nanopore_output_directory": str(tmp_path)})
        assert result.passed is True
        assert "No input FASTQ" in result.message

    def test_fastp_qc_tool_applies_the_same_floor(self, tmp_path):
        # fastp receives the minimum length as fastp_length_required, so
        # short amplicons under fastp are warned about exactly as under
        # chopper (the check used to exempt fastp, back when the pipeline
        # applied no filter to it).
        _write_fastq(tmp_path / "amplicons.fastq", [300] * 20)
        result = self._run({
            "nanopore_output_directory": str(tmp_path),
            "qc_tool": "fastp",
        })
        assert result.passed is False
        assert "fastp" in result.message
        lowered = self._run({
            "nanopore_output_directory": str(tmp_path),
            "qc_tool": "fastp",
            "chopper_minlength": 100,
        })
        assert lowered.passed is True

    def test_filtlong_reads_its_own_floor(self, tmp_path):
        _write_fastq(tmp_path / "amplicons.fastq", [300] * 20)
        result = self._run({
            "nanopore_output_directory": str(tmp_path),
            "qc_tool": "filtlong",
            "chopper_minlength": 100,
            "filtlong_min_length": 1000,
        })
        assert result.passed is False

    def test_filter_disabled_passes(self, tmp_path):
        _write_fastq(tmp_path / "amplicons.fastq", [300] * 20)
        result = self._run({
            "nanopore_output_directory": str(tmp_path),
            "chopper_minlength": 1,
        })
        assert result.passed is True

    def test_lowest_configured_floor_wins(self, tmp_path):
        # Operator lowered chopper for amplicons; the untouched filtlong
        # value must not re-raise the effective floor into a false alarm.
        _write_fastq(tmp_path / "amplicons.fastq", [300] * 20)
        result = self._run({
            "nanopore_output_directory": str(tmp_path),
            "chopper_minlength": 100,
            "filtlong_min_length": 1000,
        })
        assert result.passed is True

    def test_check_is_registered_in_full_report(self, tmp_path):
        report = ReadinessChecker().check_readiness(
            {"nanopore_output_directory": str(tmp_path)},
            nanometa_home=str(tmp_path / "home"),
            watchlist_entries=[],
        )
        assert any(c.name == "Input Read Length" for c in report.checks)
