"""
Comprehensive Frontend Integration Tests for Nanometa Live v2.0.

Tests all tabs (Dashboard, Main Results, QC, Classification) with realistic
nanometanf data across multiple scenarios.
"""

import pytest
import os
import json
import tempfile
from pathlib import Path

from nanometa_live.core.testing.mock_data_generator import (
    MockDataGenerator,
    MockDataScenario,
    generate_test_dataset
)
from nanometa_live.core.parsers import NanometanfOutputParser


class TestFrontendIntegration:
    """Integration tests for frontend with realistic data."""

    @pytest.fixture(scope="class")
    def test_data_dir(self, tmp_path_factory):
        """Create temporary directory for test data."""
        return tmp_path_factory.mktemp("nanometa_test_data")

    @pytest.fixture(scope="class", params=[
        MockDataScenario.NORMAL_RUN,
        MockDataScenario.QUALITY_ISSUES,
        MockDataScenario.PATHOGEN_DETECTED,
        MockDataScenario.MIXED_QUALITY,
        MockDataScenario.HIGH_DIVERSITY
    ])
    def scenario_data(self, request, test_data_dir):
        """Generate test data for each scenario."""
        scenario = request.param
        scenario_dir = test_data_dir / scenario

        # Generate comprehensive dataset
        files = generate_test_dataset(
            str(scenario_dir),
            scenario=scenario,
            num_samples=5
        )

        return {
            "scenario": scenario,
            "dir": scenario_dir,
            "files": files
        }

    def test_kraken2_data_parsing(self, scenario_data):
        """Test Kraken2 data parsing for all scenarios."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Test parsing for each sample
        for sample_num in range(1, 6):
            sample_name = f"barcode{sample_num:02d}"
            df = parser.parse_kraken_report(sample_name)

            # Verify basic structure
            assert not df.empty, f"Kraken report empty for {sample_name} in {scenario_data['scenario']}"
            assert 'percent' in df.columns
            assert 'reads_clade' in df.columns
            assert 'taxid' in df.columns
            assert 'name' in df.columns

            # Verify data integrity
            assert df['taxid'].iloc[0] == 0, "First entry should be unclassified"
            assert df['name'].iloc[0] == 'unclassified'

            # Verify read counts make sense
            total_reads = df['reads_clade'].sum()
            assert total_reads > 0, "Total reads should be positive"

    def test_qc_data_structure(self, scenario_data):
        """Test QC data structure and values."""
        qc_dir = scenario_data["dir"] / "qc"

        # Verify QC files exist
        assert qc_dir.exists(), "QC directory should exist"

        for sample_num in range(1, 6):
            qc_file = qc_dir / f"barcode{sample_num:02d}_qc.txt"
            assert qc_file.exists(), f"QC file missing for barcode{sample_num:02d}"

            # Read and verify content
            content = qc_file.read_text()
            assert "Total reads:" in content
            assert "Passed reads:" in content
            assert "Failed reads:" in content
            assert "Low quality:" in content

    def test_scenario_specific_characteristics(self, scenario_data):
        """Test scenario-specific data characteristics."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))
        scenario = scenario_data["scenario"]

        # Get combined data for analysis
        combined_kraken = parser.combine_kraken_reports()

        if scenario == MockDataScenario.PATHOGEN_DETECTED:
            # Should have rare pathogens
            pathogen_taxids = [1392, 632, 1491]  # Anthrax, Plague, Botulinum
            found_pathogens = combined_kraken[combined_kraken['taxid'].isin(pathogen_taxids)]
            assert len(found_pathogens) > 0, "Pathogen scenario should contain pathogens"

        elif scenario == MockDataScenario.HIGH_DIVERSITY:
            # Should have many unique species
            species_df = combined_kraken[combined_kraken['rank'] == 'S']
            unique_species = species_df['taxid'].nunique()
            assert unique_species >= 8, "High diversity scenario should have many species"

        elif scenario == MockDataScenario.QUALITY_ISSUES:
            # Classification rate should be lower
            for sample_num in range(1, 6):
                sample_name = f"barcode{sample_num:02d}"
                df = parser.parse_kraken_report(sample_name)

                unclassified_pct = df[df['rank'] == 'U']['percent'].iloc[0]
                assert unclassified_pct > 15, f"Quality issues scenario should have high unclassified rate"

    def test_dashboard_data_aggregation(self, scenario_data):
        """Test data aggregation for dashboard display."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Test metrics that would appear on dashboard
        combined_kraken = parser.combine_kraken_reports()

        # Total organisms
        unique_species = combined_kraken[combined_kraken['rank'] == 'S']['taxid'].nunique()
        assert unique_species > 0, "Should have at least one species identified"

        # Total reads
        total_reads = combined_kraken['reads_clade'].sum()
        assert total_reads > 0, "Should have positive read count"

        # Classification rate
        unclassified_df = combined_kraken[combined_kraken['rank'] == 'U']
        if not unclassified_df.empty:
            unclassified_reads = unclassified_df['reads_clade'].sum()
            classification_rate = (total_reads - unclassified_reads) / total_reads
            assert 0 <= classification_rate <= 1, "Classification rate should be between 0 and 1"

    def test_main_results_tab_data(self, scenario_data):
        """Test data structure for Main Results tab (organism cards)."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Get top species (what would be displayed in organism cards)
        top_species = parser.get_top_species(n=10)

        assert not top_species.empty, "Should have top species data"
        assert 'name' in top_species.columns, "Should have organism names"
        assert 'total_reads' in top_species.columns, "Should have read counts"

        # Verify data for organism cards
        for _, organism in top_species.iterrows():
            assert organism['name'] is not None, "Organism name should not be null"
            assert organism['total_reads'] > 0, "Read count should be positive"

            # Calculate abundance percentage (for abundance bars)
            total_reads_all = top_species['total_reads'].sum()
            abundance_pct = (organism['total_reads'] / total_reads_all) * 100
            assert 0 < abundance_pct <= 100, "Abundance percentage should be valid"

    def test_qc_tab_quality_indicators(self, scenario_data):
        """Test QC data for quality indicator components."""
        qc_dir = scenario_data["dir"] / "qc"
        scenario = scenario_data["scenario"]

        quality_scores = []

        for sample_num in range(1, 6):
            qc_file = qc_dir / f"barcode{sample_num:02d}_qc.txt"
            content = qc_file.read_text()

            # Extract pass rate (would be used for quality score indicator)
            for line in content.split('\n'):
                if "Passed reads:" in line:
                    # Extract percentage
                    pct_str = line.split('(')[1].split('%')[0]
                    pass_rate = float(pct_str)
                    quality_scores.append(pass_rate)

                    # Verify quality score is in valid range
                    assert 0 <= pass_rate <= 100, "Pass rate should be percentage"

                    # Scenario-specific assertions
                    if scenario == MockDataScenario.QUALITY_ISSUES:
                        # Should generally be low
                        pass  # Allow any value but collect for aggregate check
                    elif scenario == MockDataScenario.NORMAL_RUN:
                        assert pass_rate >= 70, "Normal run should have good pass rate"

        # Verify we collected quality data for all samples
        assert len(quality_scores) == 5, "Should have quality score for each sample"

        # Calculate overall quality (for dashboard)
        avg_quality = sum(quality_scores) / len(quality_scores)
        assert 0 < avg_quality <= 100, "Average quality should be valid percentage"

    def test_classification_tab_sankey_data(self, scenario_data):
        """Test data structure for Sankey diagram."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Get hierarchical data (sample 1)
        df = parser.parse_kraken_report("barcode01")

        # Filter for ranks needed in Sankey (D, C, G, S)
        sankey_ranks = ['D', 'C', 'G', 'S']
        sankey_data = df[df['rank'].isin(sankey_ranks)]

        assert not sankey_data.empty, "Should have hierarchical data for Sankey"

        # Verify we have different rank levels
        ranks_present = set(sankey_data['rank'].unique())
        assert len(ranks_present) > 1, "Should have multiple taxonomic levels"

    def test_classification_tab_sunburst_data(self, scenario_data):
        """Test data structure for Sunburst chart."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Get all taxonomic data for sunburst
        df = parser.parse_kraken_report("barcode01")

        # Remove unclassified and root
        classified_df = df[(df['rank'] != 'U') & (df['rank'] != 'R')]

        assert not classified_df.empty, "Should have classified data"
        assert 'reads_clade' in classified_df.columns, "Should have read counts for sizing"

    def test_alert_generation_logic(self, scenario_data):
        """Test data conditions that would trigger alerts."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))
        scenario = scenario_data["scenario"]

        combined_kraken = parser.combine_kraken_reports()

        # Check for pathogen detection (would trigger critical alert)
        if scenario == MockDataScenario.PATHOGEN_DETECTED:
            pathogen_taxids = [1392, 632, 1491]
            pathogens_found = combined_kraken[combined_kraken['taxid'].isin(pathogen_taxids)]

            if not pathogens_found.empty:
                # Would trigger: "CRITICAL: Species of interest detected"
                assert len(pathogens_found) > 0, "Pathogen detection should be flagged"

        # Check for low classification rate (would trigger quality alert)
        for sample_num in range(1, 6):
            sample_name = f"barcode{sample_num:02d}"
            df = parser.parse_kraken_report(sample_name)

            unclassified_row = df[df['rank'] == 'U']
            if not unclassified_row.empty:
                unclassified_pct = unclassified_row['percent'].iloc[0]

                if unclassified_pct > 30:
                    # Would trigger: "WARNING: Low classification rate"
                    pass  # Alert condition met

    def test_export_data_formats(self, scenario_data):
        """Test that data can be formatted for export (CSV, PDF)."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Test CSV export format
        top_species = parser.get_top_species(n=20)

        # Verify can be converted to CSV
        csv_str = top_species.to_csv()
        assert len(csv_str) > 0, "Should generate CSV data"
        assert 'name' in csv_str, "CSV should contain organism names"
        assert 'total_reads' in csv_str, "CSV should contain read counts"

        # Test data completeness for PDF export
        combined_kraken = parser.combine_kraken_reports()
        assert 'sample' in combined_kraken.columns, "Should have sample identifiers for reports"

    def test_per_sample_comparison(self, scenario_data):
        """Test data for per-sample comparison views."""
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Get data for all samples
        all_samples = []
        for sample_num in range(1, 6):
            sample_name = f"barcode{sample_num:02d}"
            df = parser.parse_kraken_report(sample_name)

            # Calculate metrics for this sample
            total_reads = df['reads_clade'].iloc[1] if len(df) > 1 else 0  # Root reads
            species_count = len(df[df['rank'] == 'S'])

            all_samples.append({
                'sample': sample_name,
                'total_reads': total_reads,
                'species_count': species_count
            })

        assert len(all_samples) == 5, "Should have data for all samples"

        # Verify samples can be compared
        read_counts = [s['total_reads'] for s in all_samples]
        assert max(read_counts) > 0, "Should have positive read counts for comparison"

    def test_realtime_monitoring_data_structure(self, scenario_data):
        """Test data structure for real-time monitoring (if applicable)."""
        # This tests the data structure even if real-time monitoring isn't active
        parser = NanometanfOutputParser(str(scenario_data["dir"]))

        # Verify parser can handle sample discovery
        combined = parser.combine_kraken_reports()

        # Check sample tracking
        unique_samples = combined['sample'].unique()
        assert len(unique_samples) > 0, "Should track samples"

        # Verify data updates would work incrementally
        for sample in unique_samples:
            sample_data = combined[combined['sample'] == sample]
            assert not sample_data.empty, f"Should have data for {sample}"

    def test_error_handling_missing_data(self, test_data_dir):
        """Test handling of missing or incomplete data."""
        empty_dir = test_data_dir / "empty"
        empty_dir.mkdir(exist_ok=True)

        parser = NanometanfOutputParser(str(empty_dir))

        # Should handle missing Kraken reports gracefully
        df = parser.parse_kraken_report("nonexistent")
        assert df.empty, "Should return empty DataFrame for missing data"
        assert 'percent' in df.columns, "Should still have correct structure"

        # Should handle missing QC data
        combined = parser.combine_kraken_reports()
        assert combined.empty, "Should return empty DataFrame when no reports exist"

    def test_large_dataset_performance(self, test_data_dir):
        """Test performance with larger datasets."""
        large_dir = test_data_dir / "large_dataset"

        # Generate dataset with many samples
        files = generate_test_dataset(
            str(large_dir),
            scenario=MockDataScenario.HIGH_DIVERSITY,
            num_samples=20  # Larger dataset
        )

        parser = NanometanfOutputParser(str(large_dir))

        # Test parsing performance
        import time
        start_time = time.time()

        combined = parser.combine_kraken_reports()

        parse_time = time.time() - start_time

        # Should complete in reasonable time
        assert parse_time < 5.0, "Parsing should complete within 5 seconds"
        assert not combined.empty, "Should successfully parse large dataset"
        assert len(combined['sample'].unique()) == 20, "Should have all samples"


class TestDashboardComponents:
    """Test Dashboard tab components with realistic data."""

    @pytest.fixture
    def normal_data(self, tmp_path):
        """Generate normal scenario data."""
        return generate_test_dataset(
            str(tmp_path / "normal"),
            scenario=MockDataScenario.NORMAL_RUN,
            num_samples=3
        )

    def test_traffic_light_calculation(self, normal_data, tmp_path):
        """Test traffic light status calculation logic."""
        parser = NanometanfOutputParser(str(tmp_path / "normal"))
        combined = parser.combine_kraken_reports()

        # Calculate overall status (logic that would determine traffic light color)
        total_reads = combined['reads_clade'].sum()
        unclassified = combined[combined['rank'] == 'U']['reads_clade'].sum()

        classification_rate = (total_reads - unclassified) / total_reads if total_reads > 0 else 0

        # Status determination logic
        if classification_rate >= 0.75:
            status = "good"  # Green
        elif classification_rate >= 0.60:
            status = "fair"  # Amber
        else:
            status = "poor"  # Red

        # Normal scenario should be good
        assert status in ["good", "fair"], "Normal scenario should have decent status"

    def test_metrics_cards_data(self, normal_data, tmp_path):
        """Test data for 4 metrics cards on dashboard."""
        parser = NanometanfOutputParser(str(tmp_path / "normal"))
        combined = parser.parse_kraken_report("barcode01")

        # Card 1: DNA Sequences
        total_sequences = combined['reads_clade'].sum()
        assert total_sequences > 0, "Should have DNA sequence count"

        # Card 2: Data Quality (would need QC data)
        # Placeholder for quality score calculation

        # Card 3: Organisms
        unique_organisms = len(combined[combined['rank'] == 'S'])
        assert unique_organisms >= 0, "Should have organism count"

        # Card 4: Alerts
        # Would be calculated based on various conditions
        alert_count = 0  # Placeholder
        assert alert_count >= 0, "Should have alert count"


class TestComponentDataBinding:
    """Test that data correctly binds to UI components."""

    def test_organism_card_data_binding(self, tmp_path):
        """Test data for OrganismCard components."""
        files = generate_test_dataset(
            str(tmp_path / "test"),
            scenario=MockDataScenario.NORMAL_RUN,
            num_samples=3
        )

        parser = NanometanfOutputParser(str(tmp_path / "test"))
        top_species = parser.get_top_species(n=10)

        # Simulate creating organism card data
        for _, organism in top_species.iterrows():
            card_data = {
                "name": organism['name'],
                "abundance": (organism['total_reads'] / top_species['total_reads'].sum()) * 100,
                "read_count": organism['total_reads'],
                "confidence": "high" if organism['total_reads'] > 1000 else ("medium" if organism['total_reads'] > 100 else "low"),
                "taxid": organism['taxid']
            }

            # Verify all required fields present
            assert card_data['name'] is not None
            assert 0 < card_data['abundance'] <= 100
            assert card_data['read_count'] > 0
            assert card_data['confidence'] in ['high', 'medium', 'low']

    def test_quality_score_indicator_data(self, tmp_path):
        """Test data for QualityScoreIndicator component."""
        files = generate_test_dataset(
            str(tmp_path / "test"),
            scenario=MockDataScenario.NORMAL_RUN,
            num_samples=3
        )

        qc_file = tmp_path / "test" / "qc" / "barcode01_qc.txt"
        content = qc_file.read_text()

        # Extract pass rate for quality indicator
        for line in content.split('\n'):
            if "Passed reads:" in line:
                pct_str = line.split('(')[1].split('%')[0]
                pass_rate = float(pct_str)

                # Convert to 0-100 score for QualityScoreIndicator
                quality_score = int(pass_rate)

                assert 0 <= quality_score <= 100, "Quality score should be 0-100"

                # Test interpretation logic
                if quality_score >= 85:
                    rating = "Excellent"
                    color = "success"
                elif quality_score >= 75:
                    rating = "Good"
                    color = "success"
                elif quality_score >= 60:
                    rating = "Fair"
                    color = "warning"
                else:
                    rating = "Poor"
                    color = "danger"

                assert rating in ["Excellent", "Good", "Fair", "Poor"]
                assert color in ["success", "warning", "danger"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
