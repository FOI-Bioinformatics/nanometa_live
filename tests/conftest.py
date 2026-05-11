"""
Pytest configuration and shared fixtures for Nanometa Live tests.

This module provides:
- Test dataset fixtures with variable species counts (1-100)
- Mock data loaders
- Dash app testing utilities
- Data validation helpers
"""

import pytest
import pandas as pd
import os
import time
from pathlib import Path
from typing import Dict, List, Any


def pytest_configure(config):
    """Register custom markers used in this suite.

    The ``slow`` marker is used to gate end-to-end smoke tests that
    invoke external binaries (Nextflow, conda, datasets) and take many
    minutes. Run them explicitly with ``pytest -m slow``.
    """
    config.addinivalue_line(
        "markers",
        "slow: end-to-end test requiring external binaries; not run by default.",
    )


def _backdate_mtime(path, seconds=5):
    """Set a file's mtime to *seconds* ago so it passes the stability check."""
    old_time = time.time() - seconds
    os.utime(str(path), (old_time, old_time))


def _backdate_all_files(directory: Path, seconds: int = 5) -> None:
    """Recursively backdate all files in a directory tree."""
    for root, _dirs, files in os.walk(str(directory)):
        for fname in files:
            _backdate_mtime(os.path.join(root, fname), seconds)


# Test dataset paths
TEST_DATA_DIR = Path("/tmp/nanometa_test_datasets")

DATASETS = {
    "single_species": TEST_DATA_DIR / "01_single_species",
    "low_diversity": TEST_DATA_DIR / "02_low_diversity",
    "medium_diversity": TEST_DATA_DIR / "03_medium_diversity",
    "high_diversity": TEST_DATA_DIR / "04_high_diversity",
    "very_high_diversity": TEST_DATA_DIR / "05_very_high_diversity",
    "pathogen_detected": TEST_DATA_DIR / "06_pathogen_detected",
    "low_quality": TEST_DATA_DIR / "07_low_quality",
    "mixed_quality": TEST_DATA_DIR / "08_mixed_quality"
}


@pytest.fixture(scope="session")
def test_datasets() -> Dict[str, Path]:
    """Provide paths to all test datasets, generating if missing.

    Under ``pytest-xdist``, every worker spawns its own pytest session and
    therefore enters this session-scoped fixture independently. Without a
    cross-process lock the workers race on ``TEST_DATA_DIR`` and corrupt
    the shared dataset. ``filelock.FileLock`` serialises the generation
    step; subsequent workers find the datasets already on disk and skip
    the generator.
    """
    import filelock

    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    lockfile = TEST_DATA_DIR.parent / ".nanometa_test_datasets.lock"

    with filelock.FileLock(str(lockfile)):
        missing = [name for name, path in DATASETS.items() if not path.exists()]
        if missing:
            # Auto-generate datasets instead of skipping
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
            from generate_test_datasets import main as generate_main
            generate_main()

            # Verify generation succeeded
            still_missing = [name for name, path in DATASETS.items() if not path.exists()]
            if still_missing:
                pytest.skip(f"Failed to generate test datasets: {still_missing}")

        # Backdate all generated files so they pass the file stability check
        _backdate_all_files(TEST_DATA_DIR)

    return DATASETS


@pytest.fixture(params=[
    "single_species",
    "low_diversity",
    "medium_diversity",
    "high_diversity"
])
def dataset_path(request, test_datasets) -> Path:
    """Parametrized fixture providing each dataset path."""
    return test_datasets[request.param]


@pytest.fixture
def kraken_data_single(test_datasets) -> pd.DataFrame:
    """Load single species Kraken2 data."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data
    return load_kraken_data(str(test_datasets["single_species"]))


@pytest.fixture
def kraken_data_medium(test_datasets) -> pd.DataFrame:
    """Load medium diversity Kraken2 data."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data
    return load_kraken_data(str(test_datasets["medium_diversity"]))


@pytest.fixture
def kraken_data_high(test_datasets) -> pd.DataFrame:
    """Load high diversity Kraken2 data."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data
    return load_kraken_data(str(test_datasets["high_diversity"]))


@pytest.fixture
def kraken_data_all(test_datasets) -> Dict[str, pd.DataFrame]:
    """Load all test datasets."""
    from nanometa_live.core.utils.classification_loaders import load_kraken_data

    data = {}
    for name, path in test_datasets.items():
        data[name] = load_kraken_data(str(path))

    return data


@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """Provide sample app configuration."""
    return {
        "main_dir": str(TEST_DATA_DIR / "01_single_species"),
        "visualization_only": True,
        "species_of_interest": [],
        "update_interval": 5000
    }


@pytest.fixture
def sample_status() -> Dict[str, Any]:
    """Provide sample backend status."""
    return {
        "running": False,
        "visualization_mode": True
    }


@pytest.fixture(scope="session")
def realtime_output_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a simulated real-time pipeline output directory."""
    base = tmp_path_factory.mktemp("realtime_output")

    kraken_dir = base / "kraken2"
    kraken_dir.mkdir()
    fastp_dir = base / "fastp"
    fastp_dir.mkdir()

    cumulative_report = (
        " 0.00\t0\t0\tU\t0\tunclassified\n"
        "100.00\t150\t0\tR\t1\troot\n"
        "100.00\t150\t0\tD\t2\t  Bacteria\n"
        "100.00\t150\t150\tS\t562\t    Escherichia coli\n"
    )
    (kraken_dir / "barcode01.cumulative.kraken2.report.txt").write_text(cumulative_report)

    batch_report = (
        " 0.00\t0\t0\tU\t0\tunclassified\n"
        "100.00\t50\t0\tR\t1\troot\n"
        "100.00\t50\t0\tD\t2\t  Bacteria\n"
        "100.00\t50\t50\tS\t562\t    Escherichia coli\n"
    )
    (kraken_dir / "barcode01_batch0.kraken2.report.txt").write_text(batch_report)

    standard_report = (
        " 0.00\t0\t0\tU\t0\tunclassified\n"
        "100.00\t100\t0\tR\t1\troot\n"
        "100.00\t100\t0\tD\t2\t  Bacteria\n"
        "100.00\t100\t100\tS\t562\t    Escherichia coli\n"
    )
    (kraken_dir / "barcode01.kraken2.report.txt").write_text(standard_report)

    fastp_json = (
        '{"summary":{"before_filtering":{"total_reads":1000,"total_bases":500000},'
        '"after_filtering":{"total_reads":950,"total_bases":475000,"q30_rate":0.92}},'
        '"filtering_result":{"passed_filter_reads":950,"low_quality_reads":30,'
        '"too_short_reads":15,"too_many_N_reads":5}}'
    )
    (fastp_dir / "barcode01.fastp.json").write_text(fastp_json)

    _backdate_all_files(base)
    return base


@pytest.fixture(scope="session")
def batch_output_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a simulated batch pipeline output directory."""
    base = tmp_path_factory.mktemp("batch_output")

    kraken_dir = base / "kraken2"
    kraken_dir.mkdir()
    fastp_dir = base / "fastp"
    fastp_dir.mkdir()

    standard_report = (
        " 0.00\t0\t0\tU\t0\tunclassified\n"
        "100.00\t200\t0\tR\t1\troot\n"
        "100.00\t200\t0\tD\t2\t  Bacteria\n"
        "100.00\t200\t200\tS\t562\t    Escherichia coli\n"
    )
    (kraken_dir / "barcode01.kraken2.report.txt").write_text(standard_report)

    fastp_json = (
        '{"summary":{"before_filtering":{"total_reads":1000,"total_bases":500000},'
        '"after_filtering":{"total_reads":950,"total_bases":475000,"q30_rate":0.92}},'
        '"filtering_result":{"passed_filter_reads":950,"low_quality_reads":30,'
        '"too_short_reads":15,"too_many_N_reads":5}}'
    )
    (fastp_dir / "barcode01.fastp.json").write_text(fastp_json)

    _backdate_all_files(base)
    return base


@pytest.fixture(scope="session")
def malformed_output_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a directory with malformed output files for error handling tests."""
    base = tmp_path_factory.mktemp("malformed_output")

    kraken_dir = base / "kraken2"
    kraken_dir.mkdir()
    fastp_dir = base / "fastp"
    fastp_dir.mkdir()
    validation_dir = base / "validation" / "minimap2"
    validation_dir.mkdir(parents=True)

    (kraken_dir / "bad_columns.kraken2.report.txt").write_text(
        "col1\tcol2\tcol3\n"
        "a\tb\tc\n"
    )
    (kraken_dir / "truncated.kraken2.report.txt").write_text("X")
    (fastp_dir / "corrupt.fastp.json").write_text("not json {")
    (validation_dir / "empty.paf").write_text("")

    _backdate_all_files(base)
    return base


@pytest.fixture(scope="session")
def multi_analysis_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a directory with multiple timestamped analysis runs."""
    base = tmp_path_factory.mktemp("multi_analysis")

    report_100 = (
        " 0.00\t0\t0\tU\t0\tunclassified\n"
        "100.00\t100\t0\tR\t1\troot\n"
        "100.00\t100\t0\tD\t2\t  Bacteria\n"
        "100.00\t100\t100\tS\t562\t    Escherichia coli\n"
    )
    report_200 = (
        " 0.00\t0\t0\tU\t0\tunclassified\n"
        "100.00\t200\t0\tR\t1\troot\n"
        "100.00\t200\t0\tD\t2\t  Bacteria\n"
        "100.00\t200\t200\tS\t562\t    Escherichia coli\n"
    )

    for dirname, content in [
        ("analysis_20240101_120000", report_100),
        ("analysis_20240102_120000", report_200),
    ]:
        kraken_dir = base / dirname / "kraken2"
        kraken_dir.mkdir(parents=True)
        (kraken_dir / "barcode01.kraken2.report.txt").write_text(content)

    _backdate_all_files(base)
    return base


# Validation helper functions

def validate_kraken_hierarchy(df: pd.DataFrame, require_root: bool = True) -> List[str]:
    """
    Validate Kraken2 report hierarchy integrity.

    Args:
        df: Kraken2 DataFrame to validate
        require_root: If True, require unclassified and root entries (full report).
                     If False, allow domain subtrees without root (filtered data).

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check required columns
    required_cols = ["%", "cumul_reads", "reads", "rank", "taxid", "name"]
    missing_cols = set(required_cols) - set(df.columns)
    if missing_cols:
        errors.append(f"Missing columns: {missing_cols}")
        return errors

    # Check for empty dataframe
    if df.empty:
        errors.append("DataFrame is empty")
        return errors

    # Check indentation consistency (2 spaces per level)
    # Note: After filtering, indentation may not start at 0, so check relative jumps
    prev_indent = None
    for idx, row in df.iterrows():
        name_full = row["name"]
        indent = len(name_full) - len(name_full.lstrip())

        if prev_indent is not None:
            # Indentation should increase by 2 or decrease to any previous level
            if indent > prev_indent and (indent - prev_indent) != 2:
                # Allow this for filtered data (domain subtrees may have irregular indentation)
                if require_root:
                    errors.append(f"Invalid indentation jump at {row['name'].strip()}: {prev_indent} -> {indent}")

        prev_indent = indent

    # Check unclassified entry exists (only for full reports)
    if require_root:
        unclassified = df[df["taxid"] == 0]
        if unclassified.empty:
            errors.append("Missing unclassified entry (taxid=0)")

        # Check root entry exists
        root = df[df["taxid"] == 1]
        if root.empty:
            errors.append("Missing root entry (taxid=1)")

    # Check taxonomy rank codes
    valid_ranks = ["U", "R", "D", "P", "C", "O", "F", "G", "S", "S1"]
    invalid_ranks = df[~df["rank"].isin(valid_ranks)]
    if not invalid_ranks.empty:
        errors.append(f"Invalid taxonomy ranks found: {invalid_ranks['rank'].unique()}")

    # Check read counts are non-negative
    negative_reads = df[df["reads"] < 0]
    if not negative_reads.empty:
        errors.append("Negative read counts found")

    return errors


def validate_sankey_data(nodes: List, links: List) -> List[str]:
    """
    Validate Sankey diagram data structure.

    Args:
        nodes: List of node dictionaries
        links: List of link dictionaries

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check nodes structure
    if not nodes:
        errors.append("No nodes in Sankey diagram")
        return errors

    for i, node in enumerate(nodes):
        if "label" not in node:
            errors.append(f"Node {i} missing 'label' field")
        if "color" not in node:
            errors.append(f"Node {i} missing 'color' field")

    # Check links structure
    if not links:
        errors.append("No links in Sankey diagram")
        return errors

    for i, link in enumerate(links):
        required_fields = ["source", "target", "value"]
        for field in required_fields:
            if field not in link:
                errors.append(f"Link {i} missing '{field}' field")

        # Validate indices
        if "source" in link and "target" in link:
            if link["source"] >= len(nodes):
                errors.append(f"Link {i} source index {link['source']} out of range (max {len(nodes)-1})")
            if link["target"] >= len(nodes):
                errors.append(f"Link {i} target index {link['target']} out of range (max {len(nodes)-1})")

            # Source index should be less than target (left to right flow)
            if link["source"] >= link["target"]:
                errors.append(f"Link {i} has source >= target ({link['source']} >= {link['target']})")

    return errors


def validate_sunburst_data(data: Dict) -> List[str]:
    """
    Validate Sunburst chart data structure.

    Args:
        data: Plotly Sunburst figure data dictionary

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not data:
        errors.append("Empty Sunburst data")
        return errors

    # Check required fields
    required_fields = ["labels", "parents", "values"]
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # Check data consistency
    labels = data["labels"]
    parents = data["parents"]
    values = data["values"]

    if len(labels) != len(parents) or len(labels) != len(values):
        errors.append(f"Inconsistent data lengths: labels={len(labels)}, parents={len(parents)}, values={len(values)}")

    # Check root node exists (empty parent)
    if "" not in parents:
        errors.append("No root node found (missing empty parent)")

    # Check all parents exist as labels (except root)
    parent_set = set(parents) - {""}
    label_set = set(labels)
    orphan_parents = parent_set - label_set
    if orphan_parents:
        errors.append(f"Orphan parent references: {orphan_parents}")

    # Check values are positive
    if any(v <= 0 for v in values):
        errors.append("Non-positive values found")

    return errors


# Export validation functions
__all__ = [
    "test_datasets",
    "dataset_path",
    "kraken_data_single",
    "kraken_data_medium",
    "kraken_data_high",
    "kraken_data_all",
    "sample_config",
    "sample_status",
    "validate_kraken_hierarchy",
    "validate_sankey_data",
    "validate_sunburst_data",
    "TEST_DATA_DIR",
    "DATASETS"
]
