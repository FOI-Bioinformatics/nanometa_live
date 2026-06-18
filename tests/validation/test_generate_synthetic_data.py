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


# ---------------------------------------------------------------------------
# Validation tree (blast / minimap2 / both) -- parses back through ValidationParser
# ---------------------------------------------------------------------------

def test_validation_tree_files_written(tmp_path):
    """The generator emits blast.tsv, minimap2_stats.json, aggregate JSON, and
    a per-batch drill-down tree."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)
    v = tmp_path / "validation"
    assert (v / "validation_results.json").exists()
    assert (v / "blast" / "barcode01_taxid1773.blast.tsv").exists()
    assert (v / "minimap2" / "barcode01_taxid1773.minimap2_stats.json").exists()
    assert (v / "minimap2" / "barcode01_taxid1773.paf").exists()
    assert (v / "blast" / "batch" / "barcode01_taxid1773_1.blast.tsv").exists()
    assert (v / "minimap2" / "batch" / "barcode01_taxid1773_2.minimap2_stats.json").exists()


def test_aggregate_parses_with_expected_statuses(tmp_path):
    """The aggregate validation_results.json parses through ValidationParser and
    yields exactly the designed (sample, taxid, method, status) tuples, including
    the 'both' -> two-results expansion."""
    from tests.validation.generate_synthetic_data import (
        generate_all_synthetic_data, EXPECTED_AGGREGATE_RESULTS,
    )
    from nanometa_live.core.parsers.blast_validation_parser import ValidationParser

    generate_all_synthetic_data(tmp_path)

    parser = ValidationParser(str(tmp_path))
    results = parser.get_validation_results()
    got = {
        (r.sample_id, r.taxid, r.validation_method, r.status.value)
        for r in results
    }
    for expected in EXPECTED_AGGREGATE_RESULTS:
        assert expected in got, f"missing {expected}; got {sorted(got)}"


def test_blast_tabular_dedup_matches_unique_reads(tmp_path):
    """The generated blast.tsv has multi-HSP rows; parsing must dedup by qseqid
    so validated_reads equals the unique-read count, not the line count."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data
    from nanometa_live.core.parsers.blast_validation_parser import ValidationParser

    generate_all_synthetic_data(tmp_path)
    tsv = tmp_path / "validation" / "blast" / "barcode01_taxid1773.blast.tsv"
    raw_lines = [ln for ln in tsv.read_text().splitlines() if ln.strip()]
    unique_qseqids = len({ln.split("\t")[0] for ln in raw_lines})
    assert unique_qseqids < len(raw_lines), "fixture should contain duplicate HSPs"

    parser = ValidationParser(str(tmp_path))
    result = parser.parse_blast_tabular(tsv, "barcode01", 1773, total_reads=3500)
    assert result.validated_reads == unique_qseqids == 3200


def test_batch_drilldown_isolates_single_batch(tmp_path):
    """get_validation_results(batch_id=...) returns only that batch's results."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data
    from nanometa_live.core.parsers.blast_validation_parser import ValidationParser

    generate_all_synthetic_data(tmp_path)
    parser = ValidationParser(str(tmp_path))
    batch1 = parser.get_validation_results(batch_id="1")
    keys = {(r.sample_id, r.taxid, r.validation_method) for r in batch1}
    assert ("barcode01", 1773, "blast") in keys
    assert ("barcode01", 1773, "minimap2") in keys
    # taxid 1280 / 562 / 263 are only in the cumulative aggregate, never per-batch
    assert all(r.taxid == 1773 for r in batch1)


def test_barcode05_tul4_amplicon_generated(tmp_path):
    """barcode05 (TUL4 amplicon) should contain F. tularensis with single-copy gene coverage."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    # Check Kraken2 report
    report_path = tmp_path / "kraken2" / "barcode05.kraken2.report.txt"
    assert report_path.exists(), "barcode05 kraken report missing"

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 263 in taxids, "F. tularensis (taxid 263) missing from barcode05"
    assert species["reads"].sum() > 0, "No species-level reads in barcode05"


def test_barcode05_tul4_amplicon_validation_files(tmp_path):
    """barcode05 validation files should include PAF and minimap2 stats for TUL4 amplicon."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)
    v = tmp_path / "validation"

    # Check minimap2 files (TUL4 is a single-copy gene, uses minimap2 only)
    assert (v / "minimap2" / "barcode05_taxid263.minimap2_stats.json").exists(), \
        "barcode05 minimap2_stats.json missing"
    assert (v / "minimap2" / "barcode05_taxid263.paf").exists(), \
        "barcode05 PAF missing"

    # Verify PAF contains amplicon-region reads (positions 435-863)
    paf_path = v / "minimap2" / "barcode05_taxid263.paf"
    paf_lines = [ln for ln in paf_path.read_text().splitlines() if ln.strip()]
    assert len(paf_lines) > 0, "barcode05 PAF should have alignment lines"

    # Check that reads map to the TUL4 amplicon window (chr coords ~435-863)
    for line in paf_lines[:5]:  # Sample first 5 lines
        cols = line.split("\t")
        ref_start, ref_end = int(cols[7]), int(cols[8])
        # Reads should be within or near the TUL4 window (435-863)
        assert ref_start >= 400 and ref_end <= 900, \
            f"Amplicon read maps outside TUL4 window: {ref_start}-{ref_end}"


def test_barcode05_tul4_in_aggregate_results(tmp_path):
    """barcode05 F. tularensis should appear in aggregate validation results."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data
    from nanometa_live.core.parsers.blast_validation_parser import ValidationParser

    generate_all_synthetic_data(tmp_path)
    parser = ValidationParser(str(tmp_path))
    results = parser.get_validation_results()

    # barcode05 / 263 yields BOTH methods: the aggregate's minimap2 entry and
    # the on-disk blast.tsv (previously hidden by the minimap2-only-aggregate
    # short-circuit; see TestAggregateWinsHidesBlast).
    barcode05_results = [r for r in results if r.sample_id == "barcode05" and r.taxid == 263]
    assert len(barcode05_results) == 2, \
        f"Expected 2 barcode05/263 results (minimap2 + blast), got {len(barcode05_results)}"

    by_method = {r.validation_method: r for r in barcode05_results}
    assert set(by_method) == {"minimap2", "blast"}
    mm2 = by_method["minimap2"]
    assert mm2.species == "Francisella tularensis"
    assert mm2.status.value == "confirmed"  # High hit rate (96.1%)
    assert mm2.validated_reads == 3650  # minimap2 mapped reads
    assert by_method["blast"].status.value == "confirmed"  # on-disk blast.tsv
