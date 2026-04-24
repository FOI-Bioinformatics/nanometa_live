"""End-to-end scenario tests for data flow through the Nanometa Live system.

These tests verify that the data loading pipeline correctly handles
common real-world scenarios: fresh starts, file corruption, real-time
batch accumulation, and dynamic sample appearance.
"""

import os
import pathlib
import time

import pandas as pd
import pytest

from nanometa_live.core.utils.data_loaders import (
    clear_data_cache,
    KRAKEN2_EXPECTED_COLUMNS,
    load_kraken_data,
)
from nanometa_live.core.utils.sample_detector import get_available_samples


def _backdate_mtime(path, seconds=5):
    """Set a file's mtime to *seconds* ago so it passes the stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


def _write_kraken_report(
    path: pathlib.Path,
    taxid: int = 562,
    species_name: str = "Escherichia coli",
    reads: int = 100,
) -> None:
    """Write a minimal valid kraken2 report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f" 0.00\t0\t0\tU\t0\tunclassified",
        f"100.00\t{reads}\t0\tR\t1\troot",
        f"100.00\t{reads}\t0\tD\t2\t  Bacteria",
        f"100.00\t{reads}\t{reads}\tS\t{taxid}\t    {species_name}",
    ]
    path.write_text("\n".join(lines) + "\n")
    _backdate_mtime(path)


class TestFreshStartToDataAppearance:
    """Verify behaviour when data appears after an initially empty directory."""

    def test_empty_then_data_appears(self, tmp_path: pathlib.Path) -> None:
        """Loading an empty directory returns an empty frame; adding data makes it visible."""
        clear_data_cache()
        df_empty = load_kraken_data(str(tmp_path))
        assert isinstance(df_empty, pd.DataFrame)
        assert df_empty.empty

        report_path = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
        _write_kraken_report(report_path, taxid=562, reads=100)

        clear_data_cache()
        df = load_kraken_data(str(tmp_path))
        species = df[df["rank"] == "S"]
        assert not species.empty
        assert int(species.iloc[0]["taxid"]) == 562
        assert int(species.iloc[0]["reads"]) == 100

    def test_data_then_corrupt_file(self, tmp_path: pathlib.Path) -> None:
        """Corrupted report files are gracefully rejected."""
        report_path = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
        _write_kraken_report(report_path, taxid=562, reads=50)

        clear_data_cache()
        df = load_kraken_data(str(tmp_path))
        assert not df.empty

        # Overwrite with truncated / invalid content
        report_path.write_text("X\n")

        clear_data_cache()
        df_corrupt = load_kraken_data(str(tmp_path))
        assert df_corrupt.empty


class TestRealtimeBatchAccumulation:
    """Verify batch-file aggregation and cumulative report priority."""

    def test_batch_accumulation(self, tmp_path: pathlib.Path) -> None:
        """Each batch file is a cumulative snapshot.

        The all-samples loader must pick the highest-numbered batch per
        sample (matching the per-sample branch fixed in the 2026-04-15
        audit) rather than summing across batches -- summing would
        multi-count reads because each batch already contains everything
        from earlier batches. The explicit cumulative report takes
        precedence over any batch file when present.
        """
        # Place batch files at the top level of kraken2/ to match the loader's
        # glob pattern: kraken2/*_batch*.kraken2.report.txt
        kraken_dir = tmp_path / "kraken2"

        # First batch: 100 reads cumulative so far
        _write_kraken_report(
            kraken_dir / "barcode01_batch0.kraken2.report.txt",
            taxid=562,
            reads=100,
        )
        clear_data_cache()
        df1 = load_kraken_data(str(tmp_path))
        species1 = df1[df1["rank"] == "S"]
        assert int(species1.iloc[0]["reads"]) == 100

        # Second batch: 250 cumulative reads (100 prior + 150 new). Each batch
        # file is a full cumulative snapshot, so the latest file IS the run
        # cumulative. The loader must NOT sum this with batch0.
        _write_kraken_report(
            kraken_dir / "barcode01_batch1.kraken2.report.txt",
            taxid=562,
            reads=250,
        )
        clear_data_cache()
        df2 = load_kraken_data(str(tmp_path))
        species2 = df2[df2["rank"] == "S"]
        assert int(species2.iloc[0]["reads"]) == 250

        # Cumulative report appears -- should be used instead of batch files
        _write_kraken_report(
            tmp_path / "kraken2" / "barcode01.cumulative.kraken2.report.txt",
            taxid=562,
            reads=250,
        )
        clear_data_cache()
        df3 = load_kraken_data(str(tmp_path))
        species3 = df3[df3["rank"] == "S"]
        assert int(species3.iloc[0]["reads"]) == 250

    def test_sample_appears_dynamically(self, tmp_path: pathlib.Path) -> None:
        """New sample directories are detected as their reports appear."""
        kraken_dir = tmp_path / "kraken2"
        _write_kraken_report(
            kraken_dir / "barcode01.kraken2.report.txt",
            taxid=562,
            reads=80,
        )

        samples = get_available_samples(str(tmp_path))
        assert "barcode01" in samples
        assert "barcode02" not in samples

        _write_kraken_report(
            kraken_dir / "barcode02.kraken2.report.txt",
            taxid=1639,
            species_name="Listeria monocytogenes",
            reads=30,
        )

        samples_updated = get_available_samples(str(tmp_path))
        assert "barcode01" in samples_updated
        assert "barcode02" in samples_updated


class TestBatchInputDirAutoDetect:
    """Scenario E: batch mode + by_barcode auto-enables --input_dir.

    The GUI exposes processing_mode and sample_handling but has no toggle
    for the use_input_dir_mode flag. Before the fix, selecting batch +
    by_barcode with no pre-built samplesheet silently fell back to
    realtime mode. create_nextflow_params now emits --input_dir for this
    combination and no longer emits --input.
    """

    @staticmethod
    def _base_config(tmp_path: pathlib.Path) -> dict:
        nanopore_dir = tmp_path / "input"
        nanopore_dir.mkdir()
        # Populate with minimal barcode directories so the layout validator
        # recognises a by_barcode shape.
        for barcode in ("barcode01", "barcode02"):
            sub = nanopore_dir / barcode
            sub.mkdir()
            (sub / "reads.fastq.gz").write_bytes(b"@seq\nACGT\n+\n!!!!\n")

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        return {
            "nanopore_output_directory": str(nanopore_dir),
            "results_output_directory": str(results_dir),
            "kraken_db": str(tmp_path / "kraken2_db"),
            "processing_mode": "batch",
            "sample_handling": "by_barcode",
            "sample_name": "sample",
            "analysis_name": "TestBatchByBarcode",
            "check_intervals_seconds": 15,
            "blast_validation": False,
        }

    def test_auto_enables_input_dir_when_no_samplesheet(
        self, tmp_path: pathlib.Path
    ) -> None:
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        config = self._base_config(tmp_path)
        params = create_nextflow_params(config)

        assert params.get("input_dir") == config["nanopore_output_directory"]
        # Must not also set --input -- nanometanf rejects multiple input modes.
        assert "input" not in params or not params.get("input")
        # Scenario E is batch; realtime_mode must not be set.
        assert not params.get("realtime_mode")
        # No auto-generated samplesheet should have been written when
        # INPUT_SCANNER is responsible for layout discovery.
        generated = (
            pathlib.Path(config["results_output_directory"])
            / "samplesheets"
            / "input_samplesheet.csv"
        )
        assert not generated.exists()

    def test_explicit_samplesheet_still_wins(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A caller-supplied config['input'] must still be honoured verbatim."""
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        config = self._base_config(tmp_path)
        samplesheet = tmp_path / "prebuilt.csv"
        samplesheet.write_text("sample,fastq_1\nbarcode01,barcode01/reads.fastq.gz\n")
        config["input"] = str(samplesheet)

        params = create_nextflow_params(config)

        assert params.get("input") == str(samplesheet)
        assert "input_dir" not in params

    def test_scenario_e_does_not_fall_back_to_realtime(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Regression guard for the silent-fallback bug.

        Before the fix, batch + by_barcode with no samplesheet flipped the
        params to realtime mode. The emitted params must now declare batch
        semantics (input_dir + no realtime_mode + no nanopore_output_dir).
        """
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        config = self._base_config(tmp_path)
        params = create_nextflow_params(config)

        assert params.get("input_dir") == config["nanopore_output_directory"]
        assert not params.get("realtime_mode")
        assert "nanopore_output_dir" not in params

    def test_single_sample_still_generates_samplesheet(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Scenario E must be scoped to by_barcode -- single_sample is unaffected."""
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params

        nanopore_dir = tmp_path / "input"
        nanopore_dir.mkdir()
        (nanopore_dir / "reads.fastq.gz").write_bytes(b"@seq\nACGT\n+\n!!!!\n")

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        config = {
            "nanopore_output_directory": str(nanopore_dir),
            "results_output_directory": str(results_dir),
            "kraken_db": str(tmp_path / "kraken2_db"),
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "sample_name": "sample",
            "analysis_name": "TestBatchSingleSample",
            "check_intervals_seconds": 15,
            "blast_validation": False,
        }

        params = create_nextflow_params(config)

        assert "input" in params and params["input"]
        assert "input_dir" not in params
