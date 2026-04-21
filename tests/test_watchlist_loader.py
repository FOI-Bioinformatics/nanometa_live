"""Tests for watchlist_loader module."""

from pathlib import Path

import pytest

from nanometa_live.core.watchlist.watchlist_loader import (
    WatchlistLoader,
    WatchlistMetadata,
    WatchlistPathogenEntry,
)


@pytest.fixture
def watchlist_dir(tmp_path):
    """Create a temporary watchlist directory with a valid YAML file."""
    wl_dir = tmp_path / "watchlists"
    wl_dir.mkdir()
    return wl_dir


def _write_yaml(path, content):
    """Write raw YAML string to a file."""
    path.write_text(content, encoding="utf-8")


# -- Valid YAML loading --


class TestValidYamlLoading:
    def test_load_valid_watchlist(self, watchlist_dir, tmp_path):
        yaml_content = """\
version: "2.0"
taxonomy_support: ["ncbi", "gtdb"]
metadata:
  name: "Test Pathogens"
  description: "A test watchlist"
  source: "Test"
pathogens:
  - name: "Escherichia coli"
    taxid_ncbi: 562
    common_name: "E. coli"
    threat_level: "moderate"
    bsl_level: 2
    category: "Enteric"
    alert_threshold: 5
  - name: "Listeria monocytogenes"
    taxid_ncbi: 1639
    threat_level: "critical"
    category: "Foodborne"
"""
        _write_yaml(watchlist_dir / "test_pathogens.yaml", yaml_content)

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        watchlists = loader.discover_watchlists()

        assert len(watchlists) == 1
        wl = watchlists[0]
        assert wl.id == "test_pathogens"
        assert wl.name == "Test Pathogens"
        assert wl.pathogen_count == 2
        assert "Enteric" in wl.categories
        assert "Foodborne" in wl.categories

    def test_load_pathogens(self, watchlist_dir, tmp_path):
        yaml_content = """\
metadata:
  name: "Minimal"
pathogens:
  - name: "Species A"
    taxid_ncbi: 100
    threat_level: "high"
"""
        _write_yaml(watchlist_dir / "minimal.yaml", yaml_content)

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        loader.discover_watchlists()
        pathogens = loader.load_watchlist("minimal")

        assert len(pathogens) == 1
        assert pathogens[0].name == "Species A"
        assert pathogens[0].taxid_ncbi == 100
        assert pathogens[0].threat_level == "high"

    def test_taxid_key_alias(self, watchlist_dir, tmp_path):
        """Both taxid_ncbi and taxid should work."""
        yaml_content = """\
metadata:
  name: "Alias Test"
pathogens:
  - name: "Species B"
    taxid: 200
"""
        _write_yaml(watchlist_dir / "alias.yaml", yaml_content)

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        loader.discover_watchlists()
        pathogens = loader.load_watchlist("alias")

        assert len(pathogens) == 1
        assert pathogens[0].taxid_ncbi == 200


# -- Malformed YAML handling --


class TestMalformedYaml:
    def test_invalid_yaml_syntax(self, watchlist_dir, tmp_path):
        _write_yaml(watchlist_dir / "bad.yaml", "{{not: valid: yaml: [")

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        watchlists = loader.discover_watchlists()
        # Should not crash, just skip the bad file
        assert len(watchlists) == 0

    def test_empty_yaml_file(self, watchlist_dir, tmp_path):
        _write_yaml(watchlist_dir / "empty.yaml", "")

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        watchlists = loader.discover_watchlists()
        assert len(watchlists) == 0

    def test_yaml_without_pathogens(self, watchlist_dir, tmp_path):
        yaml_content = """\
metadata:
  name: "No Pathogens"
"""
        _write_yaml(watchlist_dir / "nopath.yaml", yaml_content)

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        watchlists = loader.discover_watchlists()
        # Metadata is still read; pathogen_count is 0
        assert len(watchlists) == 1
        assert watchlists[0].pathogen_count == 0


# -- Validation --


class TestValidation:
    def test_validate_valid_file(self, watchlist_dir):
        yaml_content = """\
pathogens:
  - name: "Species A"
    threat_level: "high"
    bsl_level: 2
"""
        path = watchlist_dir / "valid.yaml"
        _write_yaml(path, yaml_content)

        loader = WatchlistLoader()
        is_valid, errors = loader.validate_file(path)
        assert is_valid is True
        assert errors == []

    def test_validate_missing_name_field(self, watchlist_dir):
        yaml_content = """\
pathogens:
  - threat_level: "high"
"""
        path = watchlist_dir / "no_name.yaml"
        _write_yaml(path, yaml_content)

        loader = WatchlistLoader()
        is_valid, errors = loader.validate_file(path)
        assert is_valid is False
        assert any("name" in e for e in errors)

    def test_validate_invalid_threat_level(self, watchlist_dir):
        yaml_content = """\
pathogens:
  - name: "Species A"
    threat_level: "extreme"
"""
        path = watchlist_dir / "bad_threat.yaml"
        _write_yaml(path, yaml_content)

        loader = WatchlistLoader()
        is_valid, errors = loader.validate_file(path)
        assert is_valid is False
        assert any("threat_level" in e for e in errors)

    def test_validate_invalid_bsl_level(self, watchlist_dir):
        yaml_content = """\
pathogens:
  - name: "Species A"
    bsl_level: 5
"""
        path = watchlist_dir / "bad_bsl.yaml"
        _write_yaml(path, yaml_content)

        loader = WatchlistLoader()
        is_valid, errors = loader.validate_file(path)
        assert is_valid is False
        assert any("bsl_level" in e for e in errors)

    def test_validate_missing_file(self):
        loader = WatchlistLoader()
        is_valid, errors = loader.validate_file(Path("/nonexistent/file.yaml"))
        assert is_valid is False
        assert any("not found" in e.lower() for e in errors)

    def test_validate_empty_pathogens_list(self, watchlist_dir):
        yaml_content = """\
pathogens: []
"""
        path = watchlist_dir / "empty_list.yaml"
        _write_yaml(path, yaml_content)

        loader = WatchlistLoader()
        is_valid, errors = loader.validate_file(path)
        assert is_valid is False
        assert any("No pathogens" in e for e in errors)

    def test_validate_malformed_yaml_syntax(self, watchlist_dir):
        path = watchlist_dir / "broken.yaml"
        _write_yaml(path, "{{broken yaml")

        loader = WatchlistLoader()
        is_valid, errors = loader.validate_file(path)
        assert is_valid is False
        assert any("YAML" in e or "yaml" in e.lower() for e in errors)


# -- Priority / source precedence --


class TestSourcePrecedence:
    def test_project_overrides_builtin(self, tmp_path):
        # Simulate project and builtin directories
        project_wl = tmp_path / "watchlists"
        project_wl.mkdir()
        builtin_wl = tmp_path / "core" / "config" / "data" / "watchlists"
        builtin_wl.mkdir(parents=True)

        # Same ID in both locations
        yaml_content = """\
metadata:
  name: "From {source}"
pathogens:
  - name: "Species"
"""
        _write_yaml(project_wl / "overlap.yaml", yaml_content.format(source="project"))
        _write_yaml(builtin_wl / "overlap.yaml", yaml_content.format(source="builtin"))

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        watchlists = loader.discover_watchlists()

        # Only one entry for "overlap"
        overlap_wl = [w for w in watchlists if w.id == "overlap"]
        assert len(overlap_wl) == 1
        assert overlap_wl[0].source == "project"


# -- yml extension support --


class TestYmlExtension:
    def test_yml_files_discovered(self, watchlist_dir, tmp_path):
        yaml_content = """\
metadata:
  name: "YML File"
pathogens:
  - name: "Species Y"
"""
        _write_yaml(watchlist_dir / "test.yml", yaml_content)

        loader = WatchlistLoader(project_dir=tmp_path, app_root=tmp_path)
        watchlists = loader.discover_watchlists()
        assert len(watchlists) == 1
        assert watchlists[0].id == "test"
