"""Regression test for the Kraken2 mmap segfault auto-retry (2026-05-11).

Symptom on a server run: kraken2 segfaulted (exit 139) on the very
first batch because the Kraken2 hash file lives on a network mount
(NFS / GlusterFS / CIFS / FUSE) whose mmap'd pages return invalid
data once the kraken2 process touches them. Loading database
information succeeded, then the first read of the mmap'd hash table
killed the process.

Fix in nanometanf:
1. Modules drop --memory-mapping when ``task.attempt > 1`` so the
   retry reads the DB into per-process RAM via plain read() instead.
2. ``conf/modules.config`` sets a narrow errorStrategy that retries
   ONLY on exit 139 ONLY on the first attempt.

This pytest pins both halves at source level so a future template
sync cannot silently re-introduce the bug or widen the retry to
mask unrelated OOM kills (exit 137) or container failures.

Self-skips when the sibling nanometanf repo is not checked out.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _nanometanf_path(rel: str) -> Path | None:
    candidates = [
        Path.home() / "Code" / "nanometanf" / rel,
        Path("/Users/andreassjodin/Code/nanometanf") / rel,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def modules_config_text() -> str:
    path = _nanometanf_path("conf/modules.config")
    if path is None:
        pytest.skip("nanometanf checkout not found; skipping")
    return path.read_text()


@pytest.fixture(scope="module")
def incremental_classifier_text() -> str:
    path = _nanometanf_path(
        "modules/local/kraken2_incremental_classifier/main.nf"
    )
    if path is None:
        pytest.skip("nanometanf checkout not found; skipping")
    return path.read_text()


@pytest.fixture(scope="module")
def kraken2_optimized_text() -> str:
    path = _nanometanf_path("modules/local/kraken2_optimized/main.nf")
    if path is None:
        pytest.skip("nanometanf checkout not found; skipping")
    return path.read_text()


def _retry_block(text: str, process_name: str) -> str:
    """Extract the body of a ``withName: '<process>'`` block."""
    pattern = re.compile(
        rf"withName:\s*['\"]{re.escape(process_name)}['\"]\s*\{{(.*?)\n    \}}",
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


class TestModulesConfigRetryDirectives:
    """The three Kraken2 classifier processes each need narrow retry rules."""

    PROCESSES = (
        "KRAKEN2_KRAKEN2",
        "KRAKEN2_INCREMENTAL_CLASSIFIER",
        "KRAKEN2_OPTIMIZED",
    )

    @pytest.mark.parametrize("process_name", PROCESSES)
    def test_retry_only_on_exit_139(
        self, modules_config_text: str, process_name: str
    ):
        body = _retry_block(modules_config_text, process_name)
        assert body, (
            f"Missing withName: '{process_name}' block in "
            "nanometanf/conf/modules.config"
        )
        # The errorStrategy must mention 139 specifically -- a wider
        # retry rule would mask OOM (137) and SIGTERM (143).
        assert "139" in body, (
            f"{process_name} block is present but does not mention exit "
            "139. Add `errorStrategy = { task.exitStatus == 139 && "
            "task.attempt == 1 ? 'retry' : 'finish' }` to auto-retry "
            "the kraken2 mmap segfault on network filesystems."
        )
        # Retry must be capped at exactly one extra attempt so a
        # persistent segfault (e.g. corrupt hash.k2d) does not spin.
        assert "maxRetries = 1" in body, (
            f"{process_name} block has the errorStrategy directive but "
            "no `maxRetries = 1`. A retry loop without a cap can mask "
            "deterministic failures."
        )


class TestIncrementalClassifierDropsMmapOnRetry:
    def test_script_disables_memory_mapping_on_attempt_gt_1(
        self, incremental_classifier_text: str
    ):
        # The module's memory_mapping flag must look at task.attempt so
        # the second run drops --memory-mapping. Without this, retry
        # would loop on the same SIGSEGV.
        pattern = re.compile(
            r"def\s+memory_mapping\s*=\s*\("
            r"use_memory_mapping\s*&&\s*task\.attempt\s*==\s*1\)"
        )
        assert pattern.search(incremental_classifier_text), (
            "KRAKEN2_INCREMENTAL_CLASSIFIER must compute memory_mapping "
            "with the task.attempt == 1 guard so the retry path drops "
            "--memory-mapping. Otherwise the errorStrategy retry will "
            "loop on the same mmap segfault."
        )


class TestKraken2OptimizedDropsMmapOnRetry:
    def test_script_disables_memory_mapping_on_attempt_gt_1(
        self, kraken2_optimized_text: str
    ):
        pattern = re.compile(
            r"def\s+memory_mapping\s*=\s*\("
            r"use_memory_mapping\s*&&\s*task\.attempt\s*==\s*1\)"
        )
        assert pattern.search(kraken2_optimized_text), (
            "KRAKEN2_OPTIMIZED must compute memory_mapping with the "
            "task.attempt == 1 guard (same pattern as "
            "KRAKEN2_INCREMENTAL_CLASSIFIER)."
        )


class TestKraken2KrakenExtArgs:
    """The nf-core KRAKEN2_KRAKEN2 module gets its flags via ext.args."""

    def test_ext_args_drops_memory_mapping_on_retry(
        self, modules_config_text: str
    ):
        body = _retry_block(modules_config_text, "KRAKEN2_KRAKEN2")
        # ext.args should reference both params.kraken2_memory_mapping
        # AND task.attempt so the retry path drops --memory-mapping.
        assert "task.attempt" in body and "--memory-mapping" in body, (
            "KRAKEN2_KRAKEN2 ext.args must reference task.attempt so the "
            "retry path emits an empty args string (no --memory-mapping). "
            f"Found body:\n{body}"
        )
