"""Unit tests for the genome-manager per-host circuit breaker state machine.

The breaker's integration (short-circuiting fetch_gtdb_accession after repeated
failures) is covered in test_genome_manager_lifecycle.py; these test the
class-level state transitions directly so a regression in the threshold logic is
caught in isolation.
"""

import pytest

from nanometa_live.core.utils.genome_manager import GenomeDownloadManager as GM


@pytest.fixture(autouse=True)
def _reset_breaker():
    GM._host_failures = {}
    GM._host_open = {}
    yield
    GM._host_failures = {}
    GM._host_open = {}


def test_starts_closed():
    assert GM._circuit_is_open("gtdb") is False


def test_opens_exactly_at_threshold():
    err = RuntimeError("boom")
    # CIRCUIT_THRESHOLD - 1 failures must NOT open the breaker
    for _ in range(GM.CIRCUIT_THRESHOLD - 1):
        GM._circuit_record_failure("gtdb", "GTDB", err)
    assert GM._circuit_is_open("gtdb") is False
    # the threshold-th failure opens it
    GM._circuit_record_failure("gtdb", "GTDB", err)
    assert GM._circuit_is_open("gtdb") is True
    assert GM._host_failures["gtdb"] == GM.CIRCUIT_THRESHOLD


def test_breaker_is_per_host():
    err = RuntimeError("boom")
    for _ in range(GM.CIRCUIT_THRESHOLD):
        GM._circuit_record_failure("gtdb", "GTDB", err)
    assert GM._circuit_is_open("gtdb") is True
    # a different host is unaffected
    assert GM._circuit_is_open("ncbi") is False


def test_success_resets_failure_count():
    err = RuntimeError("boom")
    GM._circuit_record_failure("ncbi", "NCBI", err)
    GM._circuit_record_failure("ncbi", "NCBI", err)
    assert GM._host_failures["ncbi"] == 2
    GM._circuit_record_success("ncbi")
    assert GM._host_failures["ncbi"] == 0
    # and a fresh failure run must again take THRESHOLD failures to open
    for _ in range(GM.CIRCUIT_THRESHOLD - 1):
        GM._circuit_record_failure("ncbi", "NCBI", err)
    assert GM._circuit_is_open("ncbi") is False


def test_stays_open_after_further_failures():
    err = RuntimeError("boom")
    for _ in range(GM.CIRCUIT_THRESHOLD + 2):
        GM._circuit_record_failure("gtdb", "GTDB", err)
    assert GM._circuit_is_open("gtdb") is True
