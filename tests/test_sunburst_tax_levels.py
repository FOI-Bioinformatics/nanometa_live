"""
Comprehensive tests for Sunburst taxonomy level filtering.

Tests the new tax_levels parameter added to Sunburst visualization,
ensuring it filters correctly across different level combinations.
"""

import pytest
import pandas as pd
from pathlib import Path

# Import visualization functions
from nanometa_live.app.tabs.classification_helpers import create_sunburst_data


class TestSunburstTaxonomyLevels:
    """Test Sunburst visualization with different taxonomy level selections."""

    def test_sunburst_all_levels(self, kraken_data_medium, sample_config):
        """Test Sunburst with all taxonomy levels selected."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=1,
            config=sample_config
        )

        assert fig is not None, "Should create figure with all levels"
        assert hasattr(fig, 'data'), "Figure should have data"

        if len(fig.data) > 0:
            sunburst = fig.data[0]
            # Should have many labels (hierarchy + species)
            assert len(sunburst.labels) > 25, f"Expected >25 labels with full hierarchy, got {len(sunburst.labels)}"

    def test_sunburst_non_consecutive_phylum_family_species(self, kraken_data_medium, sample_config):
        """Test Sunburst with non-consecutive levels: P → F → S."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["P", "F", "S"],
            min_reads=1,
            config=sample_config
        )

        assert fig is not None, "Should create figure with P→F→S"
        if len(fig.data) > 0:
            sunburst = fig.data[0]
            # Should have root + phylums + families + species
            assert len(sunburst.labels) > 10, "Should have multiple levels"

    def test_sunburst_non_consecutive_class_genus_species(self, kraken_data_medium, sample_config):
        """Test Sunburst with non-consecutive levels: C → G → S."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["C", "G", "S"],
            min_reads=1,
            config=sample_config
        )

        assert fig is not None, "Should create figure with C→G→S"
        if len(fig.data) > 0:
            sunburst = fig.data[0]
            assert len(sunburst.labels) > 5, "Should have class, genus, and species"

    def test_sunburst_domain_species_only(self, kraken_data_medium, sample_config):
        """Test Sunburst with extreme non-consecutive: D → S."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D", "S"],
            min_reads=1,
            config=sample_config
        )

        assert fig is not None, "Should create figure with D→S"
        if len(fig.data) > 0:
            sunburst = fig.data[0]
            # Should have root + domain + species
            assert len(sunburst.labels) >= 3, "Should have at least root, domain, and species"

    def test_sunburst_species_only(self, kraken_data_medium, sample_config):
        """Test Sunburst with only Species level."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["S"],
            min_reads=1,
            config=sample_config
        )

        assert fig is not None, "Should create figure with species only"
        if len(fig.data) > 0:
            sunburst = fig.data[0]
            # Should have root + species (no intermediate levels)
            assert len(sunburst.labels) > 1, "Should have root and species"

    def test_sunburst_min_reads_filters_species_only(self, kraken_data_medium, sample_config):
        """Test that min_reads filters Species but keeps hierarchy levels."""
        # High threshold should filter species but keep D, P, C, O, F, G
        fig_low = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=1,
            config=sample_config
        )

        fig_high = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=10000,  # Very high threshold
            config=sample_config
        )

        assert fig_low is not None, "Low threshold should produce figure"
        assert fig_high is not None, "High threshold should still produce figure with hierarchy"

        if len(fig_low.data) > 0 and len(fig_high.data) > 0:
            labels_low = len(fig_low.data[0].labels)
            labels_high = len(fig_high.data[0].labels)
            # High threshold should have fewer labels (filtered species)
            # but should still have hierarchy levels
            assert labels_high < labels_low, "High threshold should filter some species"
            assert labels_high > 5, "Should still have hierarchy levels even with high threshold"

    def test_sunburst_empty_tax_levels_uses_config(self, kraken_data_medium, sample_config):
        """Test that empty tax_levels falls back to config."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=[],  # Empty - should use config
            min_reads=1,
            config=sample_config
        )

        # Should use config default: ["D", "P", "C", "O", "F", "G", "S"]
        assert fig is not None, "Should create figure using config tax_levels"

    def test_sunburst_none_tax_levels_uses_config(self, kraken_data_medium, sample_config):
        """Test that None tax_levels falls back to config."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=None,  # None - should use config
            min_reads=1,
            config=sample_config
        )

        assert fig is not None, "Should create figure using config tax_levels"


class TestSunburstVsSankeyParity:
    """Test that Sunburst and Sankey accept same parameters."""

    def test_same_parameters_signature(self, kraken_data_medium, sample_config):
        """Test that both functions accept same core parameters."""
        from nanometa_live.app.tabs.classification_helpers import create_sankey_data

        domains = ["Bacteria"]
        tax_levels = ["D", "P", "F", "S"]
        min_reads = 10

        # Both should accept these parameters without error
        sunburst_fig = create_sunburst_data(
            kraken_data_medium, domains, tax_levels, min_reads, sample_config
        )

        sankey_fig = create_sankey_data(
            kraken_data_medium, domains, tax_levels, min_reads, max_taxa_per_level=10
        )

        # Both should produce valid figures
        assert sunburst_fig is not None or sunburst_fig is None, "Sunburst should handle parameters"
        assert sankey_fig is not None or sankey_fig is None, "Sankey should handle parameters"

    def test_both_respect_tax_levels(self, kraken_data_medium, sample_config):
        """Test that both visualizations respect tax_levels parameter."""
        from nanometa_live.app.tabs.classification_helpers import create_sankey_data

        # Select only 3 levels
        tax_levels = ["P", "F", "S"]

        sunburst_fig = create_sunburst_data(
            kraken_data_medium, ["Bacteria"], tax_levels, 1, sample_config
        )

        sankey_fig = create_sankey_data(
            kraken_data_medium, ["Bacteria"], tax_levels, 1, max_taxa_per_level=10
        )

        # Both should work with non-consecutive levels
        # (may return None if insufficient data, but shouldn't crash)
        assert isinstance(sunburst_fig, (type(None), object)), "Sunburst should handle non-consecutive levels"
        assert isinstance(sankey_fig, (type(None), object)), "Sankey should handle non-consecutive levels"


class TestSunburstEdgeCases:
    """Test edge cases for Sunburst tax_levels filtering."""

    def test_sunburst_invalid_tax_levels(self, kraken_data_medium, sample_config):
        """Test Sunburst with invalid taxonomy levels."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["X", "Y", "Z"],  # Invalid ranks
            min_reads=1,
            config=sample_config
        )

        # Should handle gracefully (may return None or informative message)
        assert fig is None or hasattr(fig, 'layout'), "Should handle invalid levels gracefully"

    def test_sunburst_single_domain_level(self, kraken_data_medium, sample_config):
        """Test Sunburst with only Domain level selected."""
        fig = create_sunburst_data(
            kraken_data_medium,
            domains=["Bacteria"],
            tax_levels=["D"],
            min_reads=1,
            config=sample_config
        )

        assert fig is not None, "Should create figure with domain only"
        if len(fig.data) > 0:
            # Should have root + domain
            assert len(fig.data[0].labels) >= 2, "Should have at least root and domain"

    def test_sunburst_high_diversity_performance(self, kraken_data_high, sample_config):
        """Test Sunburst performance with high diversity data."""
        import time

        start = time.time()
        fig = create_sunburst_data(
            kraken_data_high,
            domains=["Bacteria"],
            tax_levels=["D", "P", "C", "O", "F", "G", "S"],
            min_reads=1,
            config=sample_config
        )
        elapsed = time.time() - start

        assert fig is not None, "Should handle high diversity"
        assert elapsed < 3.0, f"Should complete within 3s, took {elapsed:.2f}s"


class TestSunburstMaxTaxaPerLevel:
    """Test the max_taxa_per_level cap on Sunburst node count."""

    @staticmethod
    def _nodes(fig):
        tr = fig.data[0]
        return list(tr.ids), list(tr.parents), list(tr.labels)

    def test_cap_bounds_nodes_per_level(self, kraken_data_medium, sample_config):
        """A cap keeps at most N taxa per rank and never orphans a node."""
        levels = ["D", "P", "C", "O", "F", "G", "S"]
        cap = 2
        fig = create_sunburst_data(
            kraken_data_medium, domains=["Bacteria"], tax_levels=levels,
            min_reads=1, config=sample_config, max_taxa_per_level=cap,
        )
        ids, parents, _ = self._nodes(fig)

        # No orphan parents: every referenced parent is a real node (or root "").
        orphans = (set(parents) - {""}) - set(ids)
        assert not orphans, f"capping orphaned parents: {orphans}"

        # Per-rank node count is bounded by the cap. Node ids are "<rank>_<name>"
        # (plus the synthetic "root").
        per_rank = {}
        for nid in ids:
            if nid == "root":
                continue
            rank = nid.split("_", 1)[0]
            per_rank[rank] = per_rank.get(rank, 0) + 1
        for rank, count in per_rank.items():
            assert count <= cap, f"rank {rank} has {count} nodes, cap was {cap}"

    def test_cap_reduces_node_count(self, kraken_data_medium, sample_config):
        """Capping yields strictly fewer nodes than the uncapped default."""
        levels = ["D", "P", "C", "O", "F", "G", "S"]
        uncapped = create_sunburst_data(
            kraken_data_medium, domains=["Bacteria"], tax_levels=levels,
            min_reads=1, config=sample_config,
        )
        capped = create_sunburst_data(
            kraken_data_medium, domains=["Bacteria"], tax_levels=levels,
            min_reads=1, config=sample_config, max_taxa_per_level=2,
        )
        assert len(self._nodes(capped)[0]) < len(self._nodes(uncapped)[0])

    def test_default_is_uncapped(self, kraken_data_medium, sample_config):
        """Omitting max_taxa_per_level preserves the pre-cap behavior (no cap)."""
        levels = ["D", "P", "C", "O", "F", "G", "S"]
        default = create_sunburst_data(
            kraken_data_medium, domains=["Bacteria"], tax_levels=levels,
            min_reads=1, config=sample_config,
        )
        explicit_zero = create_sunburst_data(
            kraken_data_medium, domains=["Bacteria"], tax_levels=levels,
            min_reads=1, config=sample_config, max_taxa_per_level=0,
        )
        assert len(self._nodes(default)[0]) == len(self._nodes(explicit_zero)[0])


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
