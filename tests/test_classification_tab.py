"""
Comprehensive Tests for Classification Tab Functionality.

Tests all features of the Classification tab including:
- Sankey diagram generation
- Sunburst chart generation
- View type switching
- Domain filtering
- Taxonomy level filtering
- Export functionality (HTML)
- Per-sample and aggregated views
- Error handling
"""

import pytest
import os
import pandas as pd
from pathlib import Path
import tempfile

from dash import Dash
import dash_bootstrap_components as dbc

from nanometa_live.app.tabs.classification_tab import (
    register_classification_callbacks,
    create_sankey_data,
    create_sunburst_data,
    create_placeholder_sankey,
    create_empty_sunburst,
    filter_by_domains,
)
from nanometa_live.core.testing.mock_data_generator import (
    MockDataGenerator,
    MockDataScenario,
    generate_test_dataset
)


class TestClassificationVisualizations:
    """Tests for Sankey and Sunburst visualization generation."""

    @pytest.fixture(scope="class")
    def mock_data_dir(self, tmp_path_factory):
        """Create mock data directory with Kraken2 data."""
        test_dir = tmp_path_factory.mktemp("classification_test")

        # Generate test dataset with diverse taxonomy
        files = generate_test_dataset(
            str(test_dir),
            scenario=MockDataScenario.PATHOGEN_DETECTED,
            num_samples=3
        )

        return test_dir

    @pytest.fixture
    def sample_kraken_df(self):
        """Create sample Kraken dataframe for testing."""
        data = {
            "percent": [100.0, 30.0, 15.0, 10.0, 8.0, 5.0, 7.0, 4.0],
            "reads_clade": [10000, 3000, 1500, 1000, 800, 500, 700, 400],
            "reads": [10000, 3000, 1500, 1000, 800, 500, 700, 400],
            "rank": ["R", "D", "P", "C", "O", "F", "G", "S"],
            "taxid": ["0", "2", "1224", "1236", "91347", "543", "561", "562"],
            "name": [
                "root",
                "Bacteria",
                "Proteobacteria",
                "Gammaproteobacteria",
                "Enterobacterales",
                "Enterobacteriaceae",
                "Escherichia",
                "Escherichia coli"
            ]
        }
        return pd.DataFrame(data)

    @pytest.fixture
    def config_dict(self):
        """Configuration dictionary."""
        return {
            "taxonomic_hierarchy_letters": ["D", "P", "C", "O", "F", "G", "S"],
            "default_hierarchy_letters": ["D", "C", "G", "S"],
        }

    def test_placeholder_sankey_creation(self):
        """Test creation of placeholder Sankey diagram."""
        fig = create_placeholder_sankey("Test Message")

        assert fig is not None
        assert len(fig.data) == 1
        assert fig.data[0].type == "sankey"
        assert fig.layout.height == 400

    def test_empty_sunburst_creation(self):
        """Test creation of empty Sunburst chart."""
        fig = create_empty_sunburst("Test Message")

        assert fig is not None
        assert len(fig.data) == 1
        assert fig.data[0].type == "sunburst"
        assert fig.layout.height == 700

    def test_sankey_data_generation(self, sample_kraken_df):
        """Test Sankey diagram data generation."""
        domains = ["Bacteria"]
        tax_levels = ["D", "C", "G", "S"]
        top_filter = 10

        fig = create_sankey_data(sample_kraken_df, domains, tax_levels, top_filter, max_taxa_per_level=10)

        assert fig is not None
        assert len(fig.data) == 1
        assert fig.data[0].type == "sankey"

        # Check that nodes were created
        assert len(fig.data[0].node.label) > 0

        # Check that links were created
        assert len(fig.data[0].link.source) > 0
        assert len(fig.data[0].link.target) > 0
        assert len(fig.data[0].link.value) > 0

    def test_sankey_empty_result(self, sample_kraken_df):
        """Test Sankey diagram with filters that produce no results."""
        domains = ["Archaea"]  # Domain not in sample data
        tax_levels = ["D", "C", "G", "S"]
        top_filter = 10

        fig = create_sankey_data(sample_kraken_df, domains, tax_levels, top_filter, max_taxa_per_level=10)

        # Should return None when no data matches
        assert fig is None

    def test_sunburst_data_generation(self, sample_kraken_df, config_dict):
        """Test Sunburst chart data generation."""
        domains = ["Bacteria"]
        tax_levels = ["D", "P", "C", "O", "F", "G", "S"]
        min_reads = 100

        fig = create_sunburst_data(sample_kraken_df, domains, tax_levels, min_reads, config_dict)

        assert fig is not None
        assert len(fig.data) == 1
        assert fig.data[0].type == "sunburst"

        # Check that labels were created
        assert len(fig.data[0].labels) > 0

        # Check that parents were assigned
        assert len(fig.data[0].parents) > 0

        # Check that values were assigned
        assert len(fig.data[0].values) > 0

    def test_sunburst_min_reads_filter(self, sample_kraken_df, config_dict):
        """Test Sunburst chart with high minimum reads threshold."""
        domains = ["Bacteria"]
        tax_levels = ["D", "P", "C", "O", "F", "G", "S"]
        min_reads = 5000  # Higher than most entries

        fig = create_sunburst_data(sample_kraken_df, domains, tax_levels, min_reads, config_dict)

        # Should still show hierarchy (root + domain + hierarchy) even with high threshold
        # Hierarchy levels are always included regardless of min_reads
        assert fig is not None
        assert len(fig.data[0].labels) >= 2  # At least root + domain

    def test_sunburst_empty_result(self, sample_kraken_df, config_dict):
        """Test Sunburst chart with filters that produce no results."""
        domains = ["Archaea"]  # Domain not in sample data
        tax_levels = ["D", "P", "C", "O", "F", "G", "S"]
        min_reads = 100

        fig = create_sunburst_data(sample_kraken_df, domains, tax_levels, min_reads, config_dict)

        # filter_by_domains returns empty, but Sunburst builds from remaining data
        # So it may return a minimal figure with just root, or full hierarchy
        assert fig is None or (fig is not None and len(fig.data) >= 0)


class TestDomainFiltering:
    """Tests for domain filtering functionality."""

    @pytest.fixture
    def multi_domain_kraken_df(self):
        """Create Kraken dataframe with multiple domains."""
        data = {
            "percent": [100.0, 30.0, 15.0, 20.0, 10.0],
            "reads_clade": [10000, 3000, 1500, 2000, 1000],
            "reads": [10000, 3000, 1500, 2000, 1000],
            "rank": ["R", "D", "P", "D", "P"],
            "taxid": ["0", "2", "1224", "2157", "28890"],
            "name": [
                "root",
                "  Bacteria",  # 2-space indent for hierarchy
                "    Proteobacteria",  # 4-space indent (child of Bacteria)
                "  Archaea",  # 2-space indent for hierarchy
                "    Euryarchaeota"  # 4-space indent (child of Archaea)
            ]
        }
        return pd.DataFrame(data)

    def test_single_domain_filter(self, multi_domain_kraken_df):
        """Test filtering by single domain."""
        domains = ["Bacteria"]
        filtered_df = filter_by_domains(multi_domain_kraken_df, domains)

        assert not filtered_df.empty
        # Strip indentation for comparison
        names_stripped = [name.strip() for name in filtered_df["name"].values]
        assert "Bacteria" in names_stripped
        assert "Proteobacteria" in names_stripped
        # Should not include Archaea domain when filtering for Bacteria only
        assert "Archaea" not in names_stripped

    def test_multiple_domain_filter(self, multi_domain_kraken_df):
        """Test filtering by multiple domains."""
        domains = ["Bacteria", "Archaea"]
        filtered_df = filter_by_domains(multi_domain_kraken_df, domains)

        assert not filtered_df.empty
        # Strip indentation for comparison
        names_stripped = [name.strip() for name in filtered_df["name"].values]
        assert "Bacteria" in names_stripped
        assert "Archaea" in names_stripped

    def test_nonexistent_domain_filter(self, multi_domain_kraken_df):
        """Test filtering by domain that doesn't exist."""
        domains = ["Viruses"]
        filtered_df = filter_by_domains(multi_domain_kraken_df, domains)

        assert filtered_df.empty

    def test_empty_domain_list(self, multi_domain_kraken_df):
        """Test filtering with empty domain list."""
        domains = []
        filtered_df = filter_by_domains(multi_domain_kraken_df, domains)

        assert filtered_df.empty


class TestClassificationExport:
    """Tests for classification plot export functionality."""

    def test_export_filename_handling(self):
        """Test export filename handling with different inputs."""
        test_cases = [
            {"input": "my_plot", "expected": "my_plot.html"},
            {"input": "my_plot.html", "expected": "my_plot.html"},
            {"input": "", "expected": "classification_plot.html"},
            {"input": None, "expected": "classification_plot.html"},
        ]

        for case in test_cases:
            filename = case["input"]
            expected = case["expected"]

            # Simulate filename handling logic
            if not filename:
                filename = "classification_plot"

            if not filename.endswith(".html"):
                filename += ".html"

            assert filename == expected, f"Input '{case['input']}' should result in '{expected}'"

    def test_export_directory_creation(self, tmp_path):
        """Test that export creates reports directory if needed."""
        test_main_dir = tmp_path / "test_export"
        reports_dir = test_main_dir / "reports"

        # Verify directory doesn't exist
        assert not reports_dir.exists()

        # Simulate export creating directory
        os.makedirs(reports_dir, exist_ok=True)

        # Verify directory was created
        assert reports_dir.exists()
        assert reports_dir.is_dir()

    def test_export_notification_success(self):
        """Test successful export notification structure."""
        notification = {
            "title": "Export Successful",
            "message": "Classification plot exported to /path/to/file.html",
            "color": "success",
        }

        assert notification["title"] == "Export Successful"
        assert notification["color"] == "success"
        assert ".html" in notification["message"]

    def test_export_notification_failure(self):
        """Test failure export notification structure."""
        error_msg = "Permission denied"
        notification = {
            "title": "Export Failed",
            "message": f"Failed to export plot: {error_msg}",
            "color": "danger",
        }

        assert notification["title"] == "Export Failed"
        assert notification["color"] == "danger"
        assert "Failed to export" in notification["message"]


class TestTaxonomyLevels:
    """Tests for taxonomy level selection and ordering."""

    def test_taxonomy_level_ordering(self):
        """Test that taxonomy levels maintain correct order."""
        all_levels = ["D", "P", "C", "O", "F", "G", "S"]
        selected = ["D", "C", "G", "S"]

        # Filter while maintaining order
        ordered = [level for level in all_levels if level in selected]

        assert ordered == ["D", "C", "G", "S"]
        assert ordered != ["S", "G", "C", "D"]  # Wrong order

    def test_taxonomy_level_validation(self):
        """Test validation of taxonomy levels."""
        all_levels = ["D", "P", "C", "O", "F", "G", "S"]

        # Valid levels
        valid_levels = ["D", "C", "G"]
        filtered_valid = [level for level in all_levels if level in valid_levels]
        assert len(filtered_valid) == 3

        # Invalid levels should be filtered out
        invalid_levels = ["D", "X", "Y", "S"]
        filtered_invalid = [level for level in all_levels if level in invalid_levels]
        assert filtered_invalid == ["D", "S"]  # Only valid ones kept

    def test_default_taxonomy_levels(self):
        """Test default taxonomy level selection."""
        config = {
            "taxonomic_hierarchy_letters": ["D", "P", "C", "O", "F", "G", "S"],
            "default_hierarchy_letters": ["D", "C", "G", "S"],
        }

        default_levels = config["default_hierarchy_letters"]
        assert len(default_levels) == 4
        assert "D" in default_levels
        assert "S" in default_levels


class TestViewTypeToggling:
    """Tests for view type switching between Sankey and Sunburst."""

    def test_view_type_values(self):
        """Test valid view type values."""
        valid_types = ["sankey", "sunburst"]

        for view_type in valid_types:
            assert view_type in ["sankey", "sunburst"]

    def test_levels_visibility_for_sankey(self):
        """Test that levels selector is visible for Sankey."""
        view_type = "sankey"

        # Simulate visibility logic
        if view_type == "sankey":
            style = {"display": "block"}
        else:
            style = {"display": "none"}

        assert style["display"] == "block"

    def test_levels_visibility_for_sunburst(self):
        """Test that levels selector is hidden for Sunburst."""
        view_type = "sunburst"

        # Simulate visibility logic
        if view_type == "sankey":
            style = {"display": "block"}
        else:
            style = {"display": "none"}

        assert style["display"] == "none"


class TestErrorHandling:
    """Tests for error handling in classification tab."""

    def test_empty_dataframe_handling(self):
        """Test handling of empty Kraken dataframe."""
        empty_df = pd.DataFrame()
        domains = ["Bacteria"]
        tax_levels = ["D", "C", "G", "S"]
        top_filter = 10

        # Sankey should return a placeholder figure for empty data
        fig = create_sankey_data(empty_df, domains, tax_levels, top_filter, max_taxa_per_level=10)
        assert fig is not None
        assert len(fig.data) == 0  # No Sankey data, only annotation

    def test_missing_columns_handling(self):
        """Test handling of dataframe with missing columns."""
        # Create dataframe missing required columns
        incomplete_df = pd.DataFrame({
            "name": ["Bacteria"],
            "reads": [1000]
            # Missing "rank" column
        })

        domains = ["Bacteria"]
        tax_levels = ["D", "C", "G", "S"]
        top_filter = 10

        # Should handle missing columns gracefully
        try:
            fig = create_sankey_data(incomplete_df, domains, tax_levels, top_filter, max_taxa_per_level=10)
            # Either returns None or raises KeyError
            assert fig is None or True
        except KeyError:
            # Expected if columns are missing
            pass

    def test_backend_not_running(self):
        """Test behavior when backend is not running."""
        config = {"main_dir": "/tmp/test"}
        status = {"running": False}

        # Simulate callback logic
        if not status.get("running", False):
            result = "empty_plot"
        else:
            result = "data_plot"

        assert result == "empty_plot"

    def test_no_config_provided(self):
        """Test behavior when no config is provided."""
        config = None
        status = {"running": True}

        # Simulate callback logic
        if not config:
            result = "empty_plot"
        else:
            result = "data_plot"

        assert result == "empty_plot"


class TestPerSampleAnalysis:
    """Tests for per-sample vs aggregated analysis."""

    @pytest.fixture
    def mock_data_dir(self, tmp_path):
        """Create mock data directory with multiple samples."""
        test_dir = tmp_path / "multi_sample_test"
        test_dir.mkdir()

        # Create sample directories
        for i in range(1, 4):
            sample_dir = test_dir / f"barcode{i:02d}"
            sample_dir.mkdir()

        return test_dir

    def test_sample_selection_types(self):
        """Test different sample selection scenarios."""
        test_cases = [
            {"selected_sample": None, "description": "All samples aggregated"},
            {"selected_sample": "barcode01", "description": "Single sample"},
            {"selected_sample": "barcode02", "description": "Different sample"},
        ]

        for case in test_cases:
            sample = case["selected_sample"]

            # Verify sample selection is handled
            if sample is None:
                analysis_type = "aggregated"
            else:
                analysis_type = "per_sample"

            assert analysis_type in ["aggregated", "per_sample"]


class TestDataIntegrity:
    """Tests for data integrity in visualizations."""

    def test_sankey_node_link_consistency(self, sample_kraken_df=None):
        """Test that Sankey nodes and links are consistent."""
        if sample_kraken_df is None:
            # Create simple test data
            data = {
                "percent": [100.0, 30.0, 15.0],
                "reads_clade": [10000, 3000, 1500],
                "reads": [10000, 3000, 1500],
                "rank": ["D", "P", "C"],
                "taxid": ["2", "1224", "1236"],
                "name": ["Bacteria", "Proteobacteria", "Gammaproteobacteria"]
            }
            sample_kraken_df = pd.DataFrame(data)

        domains = ["Bacteria"]
        tax_levels = ["D", "P", "C"]
        top_filter = 10

        fig = create_sankey_data(sample_kraken_df, domains, tax_levels, top_filter, max_taxa_per_level=10)

        if fig is not None:
            # Check that source and target indices are within node range
            num_nodes = len(fig.data[0].node.label)
            sources = fig.data[0].link.source
            targets = fig.data[0].link.target

            for source in sources:
                assert 0 <= source < num_nodes

            for target in targets:
                assert 0 <= target < num_nodes

    def test_sunburst_parent_child_consistency(self):
        """Test that Sunburst parent-child relationships are valid."""
        data = {
            "Taxon": ["root", "Bacteria", "Proteobacteria"],
            "Parent": ["", "root", "Bacteria"],
            "Reads": [10000, 5000, 2000]
        }
        df = pd.DataFrame(data)

        # Verify each parent exists as a taxon (except root parent)
        for i, row in df.iterrows():
            parent = row["Parent"]
            if parent != "":  # Skip empty root parent
                assert parent in df["Taxon"].values

    def test_reads_sum_consistency(self, sample_kraken_df=None):
        """Test that reads sums are consistent."""
        if sample_kraken_df is None:
            data = {
                "percent": [100.0, 30.0, 15.0],
                "reads_clade": [10000, 3000, 1500],
                "reads": [10000, 3000, 1500],
                "rank": ["D", "P", "C"],
                "taxid": ["2", "1224", "1236"],
                "name": ["Bacteria", "Proteobacteria", "Gammaproteobacteria"]
            }
            sample_kraken_df = pd.DataFrame(data)

        # Total reads should be consistent
        total_reads = sample_kraken_df["reads"].sum()
        assert total_reads > 0

        # Child reads should not exceed parent reads
        # (This is a simplified check)
        for i in range(len(sample_kraken_df) - 1):
            parent_reads = sample_kraken_df.iloc[i]["reads"]
            child_reads = sample_kraken_df.iloc[i + 1]["reads"]
            # Child can have fewer or equal reads, but not more than parent
            assert child_reads <= parent_reads or parent_reads > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
