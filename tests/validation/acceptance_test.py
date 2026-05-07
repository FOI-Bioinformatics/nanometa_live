"""
Acceptance tests for Nanometa Live classification, alerts, QC, and coverage.

Validates that synthetic data for 4 barcodes produces expected results
through the data loading and visualization pipeline.

Run standalone:
    python -m pytest tests/validation/acceptance_test.py -v
"""
import pytest
import pandas as pd


# ---- Fixture ----

@pytest.fixture
def synthetic_data_dir(tmp_path):
    """Generate synthetic data and return the directory."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data
    generate_all_synthetic_data(tmp_path)
    return tmp_path


# ---- Clinical pathogens (barcode01) ----

def test_clinical_pathogens_detected(synthetic_data_dir):
    """barcode01 should contain M. tuberculosis (1773) and S. aureus (1280) at species level."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode01")
    species_df = df[df["rank"] == "S"]
    species_taxids = set(species_df["taxid"].values)

    assert 1773 in species_taxids, "M. tuberculosis (1773) not found in barcode01"
    assert 1280 in species_taxids, "S. aureus (1280) not found in barcode01"


def test_clinical_pathogen_reads_above_threshold(synthetic_data_dir):
    """Both clinical pathogens in barcode01 should have >= 100 reads."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode01")

    for taxid, name in [(1773, "M. tuberculosis"), (1280, "S. aureus")]:
        row = df[df["taxid"] == taxid]
        assert not row.empty, f"{name} ({taxid}) missing"
        reads = int(row.iloc[0]["reads"])
        assert reads >= 100, f"{name} has only {reads} reads, expected >= 100"


# ---- Foodborne pathogens (barcode02) ----

def test_foodborne_pathogens_detected(synthetic_data_dir):
    """barcode02 should contain L. monocytogenes (1639) and S. enterica (28901)."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode02")
    species_df = df[df["rank"] == "S"]
    species_taxids = set(species_df["taxid"].values)

    assert 1639 in species_taxids, "L. monocytogenes (1639) not found in barcode02"
    assert 28901 in species_taxids, "S. enterica (28901) not found in barcode02"


# ---- Water pathogens (barcode03) ----

def test_water_pathogen_detected(synthetic_data_dir):
    """barcode03 should contain L. pneumophila (446)."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode03")
    species_df = df[df["rank"] == "S"]
    species_taxids = set(species_df["taxid"].values)

    assert 446 in species_taxids, "L. pneumophila (446) not found in barcode03"


def test_water_ecoli_low_level(synthetic_data_dir):
    """barcode03 E. coli (562) should have < 500 reads (low-level contamination)."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode03")
    ecoli = df[df["taxid"] == 562]
    assert not ecoli.empty, "E. coli (562) not found in barcode03"
    reads = int(ecoli.iloc[0]["reads"])
    assert reads < 500, f"E. coli reads = {reads}, expected < 500"


# ---- Negative control (barcode04) ----

def test_negative_no_pathogens(synthetic_data_dir):
    """barcode04 should have no watchlisted pathogen taxids at species level."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    watchlisted = {1773, 1280, 1639, 28901, 446, 83334, 1491, 287, 573}
    df = load_kraken_data(str(synthetic_data_dir), "barcode04")
    species_df = df[df["rank"] == "S"]
    species_taxids = set(species_df["taxid"].values)

    found = species_taxids & watchlisted
    assert len(found) == 0, f"Negative control has watchlisted taxids: {found}"


# ---- QC metrics ----

def test_qc_metrics_all_barcodes(synthetic_data_dir):
    """All barcodes should have valid FASTP data with sensible read counts."""
    from nanometa_live.core.utils.qc_loaders import load_fastp_data

    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        data = load_fastp_data(str(synthetic_data_dir), bc)
        before = data.get("total_reads_before", 0)
        after = data.get("total_reads_after", 0)
        assert before > 0, f"{bc}: total_reads_before is 0"
        assert after <= before, f"{bc}: after ({after}) > before ({before})"
        assert after > 0, f"{bc}: total_reads_after is 0"


# ---- Cross-barcode differentiation ----

def test_sample_data_differs_between_barcodes(synthetic_data_dir):
    """barcode01 and barcode02 should have different species taxid sets."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    df1 = load_kraken_data(str(synthetic_data_dir), "barcode01")
    df2 = load_kraken_data(str(synthetic_data_dir), "barcode02")

    species1 = set(df1[df1["rank"] == "S"]["taxid"].values)
    species2 = set(df2[df2["rank"] == "S"]["taxid"].values)

    assert species1 != species2, "barcode01 and barcode02 have identical species sets"


# ---- Batch reads increase ----

def test_batch_reads_increase(synthetic_data_dir):
    """barcode01 batch files should show increasing species reads over time."""
    kraken_dir = synthetic_data_dir / "kraken2"

    batch_totals = []
    for i in range(3):
        path = kraken_dir / f"barcode01_batch{i}.kraken2.report.txt"
        assert path.exists(), f"Batch file {i} missing"
        df = pd.read_csv(str(path), sep="\t", header=None,
                         names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
        # Sum species-level reads
        species_reads = df[df["rank"] == "S"]["reads"].sum()
        batch_totals.append(species_reads)

    for i in range(1, len(batch_totals)):
        assert batch_totals[i] >= batch_totals[i - 1], (
            f"Batch {i} species reads ({batch_totals[i]}) < batch {i-1} ({batch_totals[i-1]})"
        )


# ---- Coverage plots render ----

def test_coverage_plots_render(synthetic_data_dir):
    """PAF parsing and all 3 coverage plot functions should produce valid figures."""
    from nanometa_live.core.parsers.paf_coverage_parser import parse_paf_coverage
    from nanometa_live.app.components.coverage_plots import (
        create_coverage_depth_figure,
        create_cumulative_coverage_figure,
        create_depth_histogram_figure,
    )

    paf_path = synthetic_data_dir / "validation" / "minimap2" / "barcode01_taxid1773.paf"
    coverage = parse_paf_coverage(paf_path)
    assert len(coverage) > 0, "No coverage data parsed from PAF"

    cov_data = next(iter(coverage.values()))

    fig_depth = create_coverage_depth_figure(cov_data)
    fig_cumul = create_cumulative_coverage_figure(cov_data)
    fig_hist = create_depth_histogram_figure(cov_data)

    for name, fig in [("depth", fig_depth), ("cumulative", fig_cumul), ("histogram", fig_hist)]:
        assert fig is not None, f"{name} figure is None"
        assert len(fig.data) > 0, f"{name} figure has no traces"
