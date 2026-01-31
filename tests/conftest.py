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
from pathlib import Path
from typing import Dict, List, Any


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
    """Provide paths to all test datasets, generating if missing."""
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
    from nanometa_live.core.utils.data_loaders import load_kraken_data
    return load_kraken_data(str(test_datasets["single_species"]))


@pytest.fixture
def kraken_data_medium(test_datasets) -> pd.DataFrame:
    """Load medium diversity Kraken2 data."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data
    return load_kraken_data(str(test_datasets["medium_diversity"]))


@pytest.fixture
def kraken_data_high(test_datasets) -> pd.DataFrame:
    """Load high diversity Kraken2 data."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data
    return load_kraken_data(str(test_datasets["high_diversity"]))


@pytest.fixture
def kraken_data_all(test_datasets) -> Dict[str, pd.DataFrame]:
    """Load all test datasets."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

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
