"""End-to-end scenario tests for data flow through the Nanometa Live system.

These tests verify that the data loading pipeline correctly handles
common real-world scenarios: fresh starts, file corruption, real-time
batch accumulation, and dynamic sample appearance.
"""

import pathlib

import pandas as pd
import pytest

from nanometa_live.core.utils.data_loaders import (
    clear_data_cache,
    KRAKEN2_EXPECTED_COLUMNS,
    load_kraken_data,
)
from nanometa_live.core.utils.sample_detector import get_available_samples


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
        """Batch reports are summed; cumulative report takes precedence when present."""
        # Place batch files in a subdirectory to mirror nanometanf output
        # structure and avoid glob pattern double-matching at top level.
        kraken_dir = tmp_path / "kraken2" / "barcode01"

        # First batch
        _write_kraken_report(
            kraken_dir / "barcode01_batch0.kraken2.report.txt",
            taxid=562,
            reads=100,
        )
        clear_data_cache()
        df1 = load_kraken_data(str(tmp_path))
        species1 = df1[df1["rank"] == "S"]
        assert int(species1.iloc[0]["reads"]) == 100

        # Second batch
        _write_kraken_report(
            kraken_dir / "barcode01_batch1.kraken2.report.txt",
            taxid=562,
            reads=150,
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
