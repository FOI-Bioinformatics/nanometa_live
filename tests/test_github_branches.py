"""Tests for the nanometanf branch-list fetcher.

The helper is invoked from the Configuration tab callback to populate
the pipeline-branch-input dropdown. We exercise the offline path,
the cache, the fallback on network failure, and the priority sort.
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from nanometa_live.app.utils.github_branches import (
    FALLBACK_BRANCHES,
    PRIORITY_BRANCHES,
    _sort_branches,
    fetch_nanometanf_branches,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty cache so behaviour is deterministic."""
    reset_cache()
    yield
    reset_cache()


class TestOfflineMode:
    def test_offline_returns_fallback(self):
        result = fetch_nanometanf_branches(offline_mode=True)
        assert result == FALLBACK_BRANCHES

    def test_offline_does_not_hit_network(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            fetch_nanometanf_branches(offline_mode=True)
            mock_urlopen.assert_not_called()


class TestNetworkSuccess:
    def _stub_response(self, branches):
        body = json.dumps([{"name": b} for b in branches]).encode()
        ctx = MagicMock()
        ctx.__enter__.return_value.read.return_value = body
        ctx.__enter__.return_value.__iter__ = lambda self: iter([body])
        # urllib.request.urlopen + json.load is what the helper uses.
        # json.load(resp) calls resp.read; the stub above returns the
        # body bytes for that.
        return ctx

    def test_returns_branch_names_from_payload(self):
        with patch("nanometa_live.app.utils.github_branches.urllib.request.urlopen") as mu:
            mu.return_value = self._stub_response(["dev", "main", "feature/x"])
            result = fetch_nanometanf_branches()
        # Priority order: main, dev (master not present), then feature/x
        assert result == ["main", "dev", "feature/x"]

    def test_caches_within_ttl(self):
        with patch("nanometa_live.app.utils.github_branches.urllib.request.urlopen") as mu:
            mu.return_value = self._stub_response(["dev", "main"])
            fetch_nanometanf_branches()
            fetch_nanometanf_branches()
            fetch_nanometanf_branches()
            # One network call + two cache hits
            assert mu.call_count == 1

    def test_use_cache_false_forces_fetch(self):
        with patch("nanometa_live.app.utils.github_branches.urllib.request.urlopen") as mu:
            mu.return_value = self._stub_response(["dev"])
            fetch_nanometanf_branches()
            fetch_nanometanf_branches(use_cache=False)
            assert mu.call_count == 2


class TestNetworkFailure:
    def test_url_error_returns_fallback(self):
        with patch("nanometa_live.app.utils.github_branches.urllib.request.urlopen") as mu:
            mu.side_effect = urllib.error.URLError("dns failure")
            assert fetch_nanometanf_branches() == FALLBACK_BRANCHES

    def test_timeout_returns_fallback(self):
        with patch("nanometa_live.app.utils.github_branches.urllib.request.urlopen") as mu:
            mu.side_effect = TimeoutError("slow")
            assert fetch_nanometanf_branches() == FALLBACK_BRANCHES

    def test_invalid_json_returns_fallback(self):
        ctx = MagicMock()
        ctx.__enter__.return_value.read.return_value = b"not-json"
        with patch("nanometa_live.app.utils.github_branches.urllib.request.urlopen") as mu:
            mu.return_value = ctx
            assert fetch_nanometanf_branches() == FALLBACK_BRANCHES

    def test_unexpected_payload_shape_returns_fallback(self):
        # GitHub returning a dict instead of a list (e.g. rate-limit error)
        ctx = MagicMock()
        ctx.__enter__.return_value.read.return_value = json.dumps(
            {"message": "API rate limit exceeded"}
        ).encode()
        with patch("nanometa_live.app.utils.github_branches.urllib.request.urlopen") as mu:
            mu.return_value = ctx
            assert fetch_nanometanf_branches() == FALLBACK_BRANCHES


class TestPrioritySort:
    def test_main_first_when_present(self):
        assert _sort_branches(["dev", "main", "feature/x"])[0] == "main"

    def test_master_after_main(self):
        assert _sort_branches(["dev", "master", "main"]) == ["main", "master", "dev"]

    def test_feature_branches_alphabetical(self):
        assert _sort_branches(["zfeature", "afeature", "main"]) == [
            "main",
            "afeature",
            "zfeature",
        ]

    def test_no_priority_branches_present(self):
        # Pure alphabetical when none of main/master/dev exist.
        assert _sort_branches(["zfeat", "afeat"]) == ["afeat", "zfeat"]

    def test_empty_list(self):
        assert _sort_branches([]) == []

    def test_priority_constant_order_preserved(self):
        # All three priority branches present -> emitted in PRIORITY_BRANCHES
        # order, not whatever GitHub returned.
        assert PRIORITY_BRANCHES == ("main", "master", "dev")
        assert _sort_branches(["dev", "main", "master"]) == [
            "main",
            "master",
            "dev",
        ]
