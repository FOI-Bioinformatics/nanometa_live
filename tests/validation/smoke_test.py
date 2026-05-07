"""
Smoke test: verify Nanometa Live app starts and all components load.

Run standalone:
    python -m pytest tests/validation/smoke_test.py -v

Requires: synthetic data generated first (or any valid results directory).
"""
import importlib
import pytest


# ---- Import tests ----

CORE_MODULES = [
    # Loader package was split: the data_loaders re-export hub was
    # collapsed in the 2026-05-07 audit pass, so import each leaf
    # module directly to verify they all parse cleanly.
    "nanometa_live.core.utils.classification_loaders",
    "nanometa_live.core.utils.qc_loaders",
    "nanometa_live.core.utils.validation_loaders",
    "nanometa_live.core.utils.canonical_loaders",
    "nanometa_live.core.utils.loader_utils",
    "nanometa_live.core.utils.sample_detector",
    "nanometa_live.core.config.config_loader",
    "nanometa_live.core.parsers.paf_coverage_parser",
]

APP_MODULES = [
    "nanometa_live.app.layouts.dashboard_layout",
    "nanometa_live.app.layouts.main_layout",
    "nanometa_live.app.layouts.classification_layout",
    "nanometa_live.app.layouts.validation_layout",
    "nanometa_live.app.layouts.qc_layout",
    "nanometa_live.app.layouts.watchlist_layout",
    "nanometa_live.app.layouts.config_layout",
    "nanometa_live.app.layouts.preparation_layout",
]


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_imports(module_name):
    """Core modules should import without error."""
    mod = importlib.import_module(module_name)
    assert mod is not None


@pytest.mark.parametrize("module_name", APP_MODULES)
def test_app_layout_imports(module_name):
    """App layout modules should import without error."""
    mod = importlib.import_module(module_name)
    assert mod is not None


# ---- Data loading tests ----

def test_sample_detection(synthetic_data_dir):
    """Sample detector should find all 4 barcodes."""
    from nanometa_live.core.utils.sample_detector import get_available_samples

    samples = get_available_samples(str(synthetic_data_dir))
    assert len(samples) >= 5, f"Expected 5+ samples, got {samples}"
    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        assert bc in samples, f"{bc} not detected"


def test_kraken_data_loads(synthetic_data_dir):
    """Kraken2 data should load for each barcode."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        df = load_kraken_data(str(synthetic_data_dir), bc)
        assert df is not None, f"No data for {bc}"
        assert len(df) > 0, f"Empty data for {bc}"


def test_fastp_data_loads(synthetic_data_dir):
    """FASTP data should load for each barcode."""
    from nanometa_live.core.utils.qc_loaders import load_fastp_data

    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        data = load_fastp_data(str(synthetic_data_dir), bc)
        assert data is not None, f"No FASTP data for {bc}"
        assert data.get("total_reads_before", 0) > 0, f"No reads for {bc}"


def test_paf_coverage_parses(synthetic_data_dir):
    """PAF coverage should parse for barcode01 M. tuberculosis."""
    from nanometa_live.core.parsers.paf_coverage_parser import parse_paf_coverage

    paf_path = synthetic_data_dir / "validation" / "minimap2" / "barcode01_taxid1773.paf"
    assert paf_path.exists(), "PAF file missing"

    coverage = parse_paf_coverage(paf_path)
    assert len(coverage) > 0, "No coverage data parsed"
    for ref_name, cov_data in coverage.items():
        assert cov_data.ref_length > 0
        assert cov_data.breadth > 0


# ---- Fixture ----

@pytest.fixture
def synthetic_data_dir(tmp_path):
    """Generate synthetic data and return the directory."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data
    generate_all_synthetic_data(tmp_path)
    return tmp_path
