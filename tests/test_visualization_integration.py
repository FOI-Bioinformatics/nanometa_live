"""
Practical integration tests for visualization functionality.

Tests data loading, processing, and visualization creation with real test datasets.
"""

import pytest
import pandas as pd
import os
import importlib.util
from pathlib import Path

# Import core functions
from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.app.tabs.classification_helpers import create_sankey_data, create_sunburst_data
from nanometa_live.app.tabs.kraken2_helpers import filter_by_domains

# Import validation function from local conftest
import sys
conftest_path = Path(__file__).parent / "conftest.py"
spec = importlib.util.spec_from_file_location("local_conftest", conftest_path)
local_conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local_conftest)
validate_kraken_hierarchy = local_conftest.validate_kraken_hierarchy


class TestDataLoading:
    """Test that data loads correctly from all test datasets."""

    def test_load_single_species_dataset(self, test_datasets):
        """Test loading single species dataset."""
        df = load_kraken_data(str(test_datasets["single_species"]))

        assert not df.empty, "Single species dataset is empty"

        # Validate hierarchy
        errors = validate_kraken_hierarchy(df)
        assert not errors, f"Single species data has hierarchy errors: {errors}"

        # Should have at least one species
        species = df[df["rank"] == "S"]
        assert len(species) >= 1, "No species found in single species dataset"

    def test_load_medium_diversity_dataset(self, test_datasets):
        """Test loading medium diversity dataset."""
        df = load_kraken_data(str(test_datasets["medium_diversity"]))

        assert not df.empty, "Medium diversity dataset is empty"

        # Validate hierarchy
        errors = validate_kraken_hierarchy(df)
        assert not errors, f"Medium diversity data has hierarchy errors: {errors}"

        # Should have multiple species
        species = df[df["rank"] == "S"]
        assert len(species) >= 5, f"Expected at least 5 species, got {len(species)}"

    def test_load_high_diversity_dataset(self, test_datasets):
        """Test loading high diversity dataset."""
        df = load_kraken_data(str(test_datasets["high_diversity"]))

        assert not df.empty, "High diversity dataset is empty"

        # Validate hierarchy
        errors = validate_kraken_hierarchy(df)
        assert not errors, f"High diversity data has hierarchy errors: {errors}"

        # Should have many species
        species = df[df["rank"] == "S"]
        assert len(species) >= 10, f"Expected at least 10 species, got {len(species)}"

    def test_load_all_datasets(self, test_datasets):
        """Test that all datasets load without errors."""
        for name, path in test_datasets.items():
            df = load_kraken_data(str(path))
            assert not df.empty, f"Dataset {name} is empty"

            # Basic hierarchy validation
            errors = validate_kraken_hierarchy(df)
            assert not errors, f"Dataset {name} has hierarchy errors: {errors}"


class TestDomainFiltering:
    """Test domain filtering functionality."""

    def test_filter_bacteria_only(self, kraken_data_medium):
        """Test filtering to Bacteria domain."""
        filtered = filter_by_domains(kraken_data_medium, ["Bacteria"])

        assert not filtered.empty, "Bacteria filter returned empty data"

        # Should have Bacteria domain
        bacteria = filtered[filtered["name"].str.strip() == "Bacteria"]
        assert not bacteria.empty, "No Bacteria domain found after filtering"

        # Validate hierarchy preserved (filtered data doesn't need root/unclassified)
        errors = validate_kraken_hierarchy(filtered, require_root=False)
        assert not errors, f"Domain filtering broke hierarchy: {errors}"

    def test_filter_multiple_domains(self, kraken_data_medium):
        """Test filtering with multiple domains."""
        filtered = filter_by_domains(kraken_data_medium, ["Bacteria", "Viruses"])

        # Should not crash
        assert isinstance(filtered, pd.DataFrame), "Filter should return DataFrame"

    def test_filter_empty_domains(self, kraken_data_medium):
        """Test filtering with empty domain list."""
        filtered = filter_by_domains(kraken_data_medium, [])

        # Should return empty or original data
        assert isinstance(filtered, pd.DataFrame), "Filter should return DataFrame"


class TestSankeyVisualization:
    """Test Sankey diagram creation."""

    def test_sankey_single_species(self, kraken_data_single):
        """Test Sankey with single species."""
        fig = create_sankey_data(
            kraken_data_single,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=10,
            max_taxa_per_level=10
        )

        # Should return a valid figure (or None if no data)
        assert fig is None or hasattr(fig, 'data'), "Should return None or valid Figure"

    def test_sankey_medium_diversity(self, kraken_data_medium):
        """Test Sankey with medium diversity."""
        fig = create_sankey_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=10,
            max_taxa_per_level=10
        )

        # Should return a valid figure
        assert fig is not None, "Medium diversity should produce a figure"
        assert hasattr(fig, 'data'), "Should return valid Figure with data"

        # Check figure has Sankey data
        if fig is not None and hasattr(fig, 'data') and len(fig.data) > 0:
            sankey = fig.data[0]
            assert hasattr(sankey, 'node'), "Sankey should have nodes"
            assert hasattr(sankey, 'link'), "Sankey should have links"

    def test_sankey_non_consecutive_levels(self, kraken_data_medium):
        """Test Sankey with non-consecutive levels."""
        # Test P → F → S (skipping Class, Order, Genus)
        fig = create_sankey_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["P", "F", "S"],
            min_reads=10,
            max_taxa_per_level=10
        )

        # Should not crash
        assert fig is None or hasattr(fig, 'data'), "Should handle non-consecutive levels"

    def test_sankey_high_diversity(self, kraken_data_high):
        """Test Sankey with high diversity."""
        fig = create_sankey_data(
            kraken_data_high,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=20,
            max_taxa_per_level=10
        )

        # Should handle high diversity
        assert fig is None or hasattr(fig, 'data'), "Should handle high diversity"


class TestSunburstVisualization:
    """Test Sunburst chart creation."""

    def test_sunburst_single_species(self, kraken_data_single, sample_config):
        """Test Sunburst with single species."""
        fig = create_sunburst_data(
            kraken_data_single,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=1,
            config=sample_config
        )

        # Should return a valid figure
        assert fig is None or hasattr(fig, 'data'), "Should return None or valid Figure"

    def test_sunburst_medium_diversity(self, kraken_data_medium, sample_config):
        """Test Sunburst with medium diversity."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=10,
            config=sample_config
        )

        # Should return a valid figure
        assert fig is not None, "Medium diversity should produce a figure"
        assert hasattr(fig, 'data'), "Should return valid Figure with data"

        # Check figure has Sunburst data
        if fig is not None and hasattr(fig, 'data') and len(fig.data) > 0:
            sunburst = fig.data[0]
            assert hasattr(sunburst, 'labels'), "Sunburst should have labels"
            assert hasattr(sunburst, 'parents'), "Sunburst should have parents"
            assert hasattr(sunburst, 'values'), "Sunburst should have values"


class TestVisualizationRegression:
    """Regression tests for previously reported issues."""

    def test_domain_filtering_with_aggregated_data(self, kraken_data_medium):
        """
        Regression: Domain filtering failed with aggregated data.

        Previously used iloc[] which broke with non-sequential indices.
        """
        # Simulate aggregation (makes indices non-sequential)
        aggregated = kraken_data_medium.groupby(["taxid", "rank", "name"], as_index=False).agg({
            "%": "sum",
            "cumul_reads": "sum",
            "reads": "sum"
        })

        # Filter by domain - should not crash
        filtered = filter_by_domains(aggregated, ["Bacteria"])

        # Validate hierarchy preserved (filtered/aggregated data doesn't need root/unclassified)
        if not filtered.empty:
            errors = validate_kraken_hierarchy(filtered, require_root=False)
            assert not errors, f"Aggregated data filtering broke hierarchy: {errors}"

    def test_main_results_tab_shows_organisms(self, kraken_data_medium):
        """
        Regression: Main Results tab not showing organisms.

        Tests the top species extraction logic.
        """
        # Simulate main results logic - get top 10 species
        species_df = kraken_data_medium[kraken_data_medium["rank"] == "S"]
        species_df = species_df[species_df["reads"] > 0]
        species_df = species_df.sort_values("reads", ascending=False).head(10)

        assert not species_df.empty, "Should find top species"
        assert len(species_df) > 0, "Should have at least one species"

        # Check each species has required fields
        for _, row in species_df.iterrows():
            assert "name" in row, "Species should have name"
            assert "taxid" in row, "Species should have taxid"
            assert "reads" in row, "Species should have reads"
            assert row["reads"] > 0, "Species should have positive read count"


class TestVisualizationPerformance:
    """Test visualization performance with different data sizes."""

    def test_performance_single_species(self, kraken_data_single):
        """Test performance with single species."""
        import time

        start = time.time()
        fig = create_sankey_data(
            kraken_data_single,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=10,
            max_taxa_per_level=10
        )
        elapsed = time.time() - start

        assert elapsed < 2.0, f"Single species took too long: {elapsed:.2f}s"

    def test_performance_medium_diversity(self, kraken_data_medium):
        """Test performance with medium diversity."""
        import time

        start = time.time()
        fig = create_sankey_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=10,
            max_taxa_per_level=10
        )
        elapsed = time.time() - start

        assert elapsed < 3.0, f"Medium diversity took too long: {elapsed:.2f}s"

    def test_performance_high_diversity(self, kraken_data_high):
        """Test performance with high diversity."""
        import time

        start = time.time()
        fig = create_sankey_data(
            kraken_data_high,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=20,
            max_taxa_per_level=10
        )
        elapsed = time.time() - start

        assert elapsed < 5.0, f"High diversity took too long: {elapsed:.2f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
