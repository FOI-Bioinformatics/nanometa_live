"""Offline mode must make no network call, observed rather than assumed.

``offline_mode`` is the switch that makes this software usable on an air-gapped
field machine. Its correctness has only ever been argued from reading the code:
tests assert that a method returns ``None`` or logs a warning, which is
consistent with the network call being skipped *and* with it being made and
failing. On a machine with no route out those look identical; on one with a
route, an "offline" run can quietly reach the internet.

This module asserts the property directly, by making any outbound connection
raise and then driving the paths that would reach out.

WHAT IS AND IS NOT COVERED
--------------------------
Patching ``socket.socket.connect`` and ``socket.create_connection`` catches
everything that opens a connection **in this process** -- which is ``requests``
(taxonomy_api, genome_manager, kraken_utils, file_utils) and ``urllib.request``
(github_branches, readiness_checker), since both sit on top of the socket
module.

It does NOT catch a child process. ``genome_manager`` shells out to the NCBI
Datasets CLI and ``nextflow_manager`` to ``git ls-remote``; those open sockets
in their own address space, where a patch here cannot see them. Those paths are
covered separately by asserting no subprocess is spawned at all, which is the
strongest statement available without a network namespace.
"""

from __future__ import annotations

import socket
import subprocess
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


class NetworkAccessAttempted(AssertionError):
    """Raised in place of opening a connection, so any attempt is visible."""


@pytest.fixture
def no_network(monkeypatch):
    """Make every in-process outbound connection raise.

    Patching at the socket layer rather than at ``requests`` means a future
    switch to httpx, urllib3 or a bare socket cannot slip past this test.
    """
    def refuse(*args, **kwargs):
        raise NetworkAccessAttempted(
            f"offline mode attempted an outbound connection: {args[:2]}"
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    return refuse


@pytest.fixture
def no_subprocess(monkeypatch):
    """Record subprocess launches instead of running them."""
    calls = []

    def record(cmd, *args, **kwargs):
        calls.append(cmd)
        raise NetworkAccessAttempted(f"offline mode spawned a subprocess: {cmd}")

    monkeypatch.setattr(subprocess, "run", record)
    monkeypatch.setattr(subprocess, "Popen", record)
    monkeypatch.setattr(subprocess, "check_output", record)
    return calls


@pytest.fixture
def offline_genome_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
    from nanometa_live.core.utils.genome_manager import GenomeDownloadManager

    return GenomeDownloadManager(offline_mode=True)


class TestGenomeManagerStaysOffline:
    """The paths that would otherwise reach NCBI or GTDB."""

    def test_fetch_gtdb_accession_makes_no_connection(
        self, offline_genome_manager, no_network
    ):
        assert offline_genome_manager.fetch_gtdb_accession(263) is None

    def test_fetch_ncbi_accession_makes_no_connection(
        self, offline_genome_manager, no_network
    ):
        assert offline_genome_manager.fetch_ncbi_accession(263) is None

    def test_get_kingdom_makes_no_connection(
        self, offline_genome_manager, no_network
    ):
        offline_genome_manager.get_kingdom(263)

    def test_get_kingdoms_batch_makes_no_connection(
        self, offline_genome_manager, no_network
    ):
        offline_genome_manager.get_kingdoms_batch([263, 1392, 632])

    def test_download_genome_makes_no_connection(
        self, offline_genome_manager, no_network
    ):
        offline_genome_manager.download_genome(263, "Francisella tularensis")

    def test_download_genome_spawns_no_subprocess(
        self, offline_genome_manager, no_subprocess
    ):
        """The Datasets CLI opens its own sockets, invisible to a socket patch.

        Refusing to spawn it at all is the strongest guarantee available
        without a network namespace.
        """
        offline_genome_manager.download_genome(263, "Francisella tularensis")
        assert not no_subprocess, (
            f"offline mode launched {no_subprocess}, which would reach the "
            f"network from a child process where this test cannot see it"
        )


class TestTaxonomyApiStaysOffline:
    def _clients(self, tmp_path, monkeypatch):
        """Build offline clients the way production does.

        ``offline_mode`` is NOT a constructor argument on NCBIClient or
        GTDBClient -- both override __init__ without it and call super()
        with the default of False. The supported path is the module factories,
        which set the attribute after construction. Constructing the classes
        directly yields an ONLINE client, so a test that did so would prove
        nothing while appearing to pass.
        """
        monkeypatch.setenv("NANOMETA_DATA_DIR", str(tmp_path))
        from nanometa_live.core.taxonomy import taxonomy_api as api

        clients = [
            api.get_ncbi_client(offline_mode=True),
            api.get_gtdb_client(offline_mode=True),
        ]
        for c in clients:
            assert c.offline_mode is True, (
                f"{type(c).__name__} is not in offline mode; the test would "
                f"be exercising the online path"
            )
        return clients

    def test_every_offline_capable_client_makes_no_connection(
        self, tmp_path, monkeypatch, no_network
    ):
        for client in self._clients(tmp_path, monkeypatch):
            for method, args in (
                ("search_by_name", ("Francisella tularensis",)),
                ("get_by_taxid", (263,)),
            ):
                fn = getattr(client, method, None)
                if fn is None:
                    continue
                # Must not raise NetworkAccessAttempted; any other outcome
                # (None, empty, a cache miss) is acceptable behaviour offline.
                fn(*args)


class TestPipelineSourceRefusesRemote:
    """A remote pipeline source cannot be fetched on an air-gapped machine.

    The refusal must happen before any git process starts: a `git ls-remote`
    that hangs for its own timeout on a field laptop is a materially worse
    experience than an immediate, explanatory failure.
    """

    @pytest.mark.parametrize("source", [
        "remote:dev", "remote:master",
        "https://github.com/FOI-Bioinformatics/nanometanf",
        "git@github.com:FOI-Bioinformatics/nanometanf.git",
    ])
    def test_remote_sources_are_rejected_without_spawning_git(
        self, tmp_path, source, no_subprocess
    ):
        from nanometa_live.core.workflow.nextflow_manager import NextflowManager

        manager = NextflowManager(str(tmp_path))
        ok, message = manager.validate_pipeline_source(
            {"offline_mode": True, "pipeline_source": source}
        )

        assert ok is False, f"{source!r} was accepted in offline mode"
        assert "offline" in (message or "").lower(), (
            f"the refusal does not mention offline mode: {message!r}"
        )
        assert not no_subprocess, (
            f"offline mode spawned {no_subprocess} before refusing a remote "
            f"source; the point is to fail immediately, not after a timeout"
        )


class TestTheHarnessItselfWorks:
    """Without this, every test above could pass by never being reached."""

    def test_the_patch_actually_blocks_a_connection(self, no_network):
        with pytest.raises(NetworkAccessAttempted):
            socket.create_connection(("example.invalid", 80), timeout=1)

    def test_requests_is_blocked_by_the_socket_patch(self, no_network):
        """Proves the choke point covers the library the code actually uses."""
        requests = pytest.importorskip("requests")
        # A literal IP, deliberately: a hostname would fail in getaddrinfo
        # before reaching the socket connect this fixture patches, and the
        # test would pass for the wrong reason.
        with pytest.raises(Exception) as excinfo:
            requests.get("http://192.0.2.1", timeout=1)
        # requests wraps the socket error; the cause chain must contain ours.
        chain = []
        exc = excinfo.value
        while exc is not None and len(chain) < 12:
            chain.append(type(exc).__name__)
            exc = exc.__cause__ or exc.__context__
        assert "NetworkAccessAttempted" in chain, (
            f"requests was not stopped by the socket patch; chain was {chain}"
        )
