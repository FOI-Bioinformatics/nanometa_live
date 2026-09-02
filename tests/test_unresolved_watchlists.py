"""A watchlist the configuration names must exist, or the operator hears it.

Round-4 audit, H24 (observed live 2026-09-01 22:46): a config with
``watchlist: {enabled: true, builtin: [bioshield_agents]}`` under a new
config filename got a new project directory whose watchlist folder was
empty; ``bioshield_agents`` is not a package built-in. The manager loaded
zero entries, the Watchlist tab showed 0 total, and readiness said "No
watchlist enabled" as if the operator had chosen none.
"""

import pytest

from nanometa_live.core.watchlist import watchlist_manager as wm
from nanometa_live.core.workflow.readiness_checker import ReadinessChecker, Severity

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_loader(tmp_path, monkeypatch):
    """A loader whose user and project dirs are empty temp dirs."""
    from nanometa_live.core.watchlist.watchlist_loader import WatchlistLoader
    project = tmp_path / "project"
    project.mkdir()
    user = tmp_path / "user_watchlists"
    user.mkdir()
    loader = WatchlistLoader(project_dir=project, user_dir=user)
    monkeypatch.setattr(wm, "_watchlist_loader", loader)
    return loader


class TestUnresolvedWatchlistIds:
    def test_missing_named_list_is_reported_with_search_dirs(self, isolated_loader):
        missing = wm.unresolved_watchlist_ids(
            {"watchlist": {"enabled": True, "builtin": ["bioshield_agents"]}})
        assert list(missing) == ["bioshield_agents"]
        assert any("user_watchlists" in d for d in missing["bioshield_agents"])

    def test_package_builtin_resolves(self, isolated_loader):
        assert wm.unresolved_watchlist_ids(
            {"watchlist": {"enabled": True, "builtin": ["clinical_pathogens"]}}) == {}

    def test_disabled_watchlist_block_is_ignored(self, isolated_loader):
        assert wm.unresolved_watchlist_ids(
            {"watchlist": {"enabled": False, "builtin": ["bioshield_agents"]}}) == {}

    def test_no_watchlist_block(self, isolated_loader):
        assert wm.unresolved_watchlist_ids({}) == {}
        assert wm.unresolved_watchlist_ids(None) == {}


class TestReadinessNamesTheMissingList:
    def test_missing_list_is_critical(self, isolated_loader):
        result = ReadinessChecker()._check_watchlist_names_resolve(
            {"watchlist": {"enabled": True, "builtin": ["bioshield_agents"]}})
        assert result.passed is False
        assert result.severity == Severity.CRITICAL
        assert "bioshield_agents" in result.message
        assert result.details and "Searched" in result.details

    def test_resolved_lists_pass(self, isolated_loader):
        result = ReadinessChecker()._check_watchlist_names_resolve(
            {"watchlist": {"enabled": True, "builtin": ["clinical_pathogens"]}})
        assert result.passed is True
