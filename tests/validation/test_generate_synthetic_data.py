"""Tests for synthetic data generator."""
import os
import pytest
import pandas as pd


def test_generate_kraken_report_barcode01(tmp_path):
    """barcode01 (clinical) should contain M. tuberculosis and S. aureus."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
    assert report_path.exists(), "barcode01 kraken report missing"

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])

    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 1773 in taxids, "M. tuberculosis missing from barcode01"
    assert 1280 in taxids, "S. aureus missing from barcode01"
    assert species["reads"].sum() > 0, "No species-level reads"


def test_generate_kraken_report_barcode02(tmp_path):
    """barcode02 (foodborne) should contain L. monocytogenes and S. enterica."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode02.kraken2.report.txt"
    assert report_path.exists()

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 1639 in taxids, "L. monocytogenes missing from barcode02"
    assert 28901 in taxids, "S. enterica missing from barcode02"


def test_generate_kraken_report_barcode03(tmp_path):
    """barcode03 (water) should contain L. pneumophila and low E. coli."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode03.kraken2.report.txt"
    assert report_path.exists()

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 446 in taxids, "L. pneumophila missing from barcode03"
    assert 562 in taxids, "E. coli missing from barcode03"


def test_generate_kraken_report_barcode04_negative(tmp_path):
    """barcode04 (negative control) should have no watchlisted pathogens."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode04.kraken2.report.txt"
    assert report_path.exists()

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))

    watchlisted = {1773, 1280, 1639, 28901, 446, 83334, 1491}
    overlap = taxids & watchlisted
    assert len(overlap) == 0, f"Negative control has watchlisted pathogens: {overlap}"


def test_cumulative_time_points(tmp_path):
    """Cumulative reports should exist for 3 time points with increasing reads."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    kraken_dir = tmp_path / "kraken2"
    for i in range(3):
        batch_path = kraken_dir / f"barcode01_batch{i}.kraken2.report.txt"
        assert batch_path.exists(), f"Batch {i} report missing"

    import pandas as pd
    totals = []
    for i in range(3):
        batch_path = kraken_dir / f"barcode01_batch{i}.kraken2.report.txt"
        df = pd.read_csv(batch_path, sep="\t", header=None,
                         names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
        total = df[df["rank"] == "S"]["reads"].sum()
        totals.append(total)

    assert totals[0] < totals[1] < totals[2], f"Reads should increase: {totals}"
