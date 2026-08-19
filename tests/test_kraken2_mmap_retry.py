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


class TestErrorIsolationRetryPolicy:
    """SIGSEGV (exit 139) must still trigger a retry for every Kraken2 process.

    The retry SCHEDULING was consolidated into conf/error_isolation.config
    (the single source of errorStrategy -- it loads last, so directives in
    modules.config were dead; 2026-08-16 audit). The policy there ignores
    exits 1/2 and retries everything else with a bounded maxRetries, so 139
    lands in the retry branch. modules.config keeps the attempt-gated
    ext.args that drops --memory-mapping on the second attempt.
    """

    PROCESSES = (
        "KRAKEN2_KRAKEN2",
        "KRAKEN2_INCREMENTAL_CLASSIFIER",
        "KRAKEN2_OPTIMIZED",
    )

    @pytest.fixture(scope="class")
    def error_isolation_text(self) -> str:
        path = _nanometanf_path("conf/error_isolation.config")
        if path is None:
            pytest.skip("nanometanf checkout not found; skipping")
        return path.read_text()

    @pytest.mark.parametrize("process_name", PROCESSES)
    def test_exit_139_falls_into_the_retry_branch(
        self, error_isolation_text: str, process_name: str
    ):
        body = _retry_block(error_isolation_text, process_name)
        assert body, (
            f"Missing withName: '{process_name}' block in "
            "nanometanf/conf/error_isolation.config -- the single source "
            "of errorStrategy for Kraken2 processes"
        )
        assert "'retry'" in body or '"retry"' in body, (
            f"{process_name} errorStrategy has no retry branch; the kraken2 "
            "mmap segfault on network filesystems would be fatal"
        )
        # 139 must NOT be in the ignore set: an ignored segfault silently
        # drops the batch instead of retrying without --memory-mapping.
        ignore_sets = re.findall(r"exitStatus\s+in\s+\[([0-9,\s]+)\]", body)
        for s in ignore_sets:
            assert "139" not in s, (
                f"{process_name} ignores exit 139; the mmap segfault would "
                "silently drop the batch instead of retrying"
            )

    @pytest.mark.parametrize("process_name", PROCESSES)
    def test_retry_is_bounded(
        self, error_isolation_text: str, process_name: str
    ):
        body = _retry_block(error_isolation_text, process_name)
        assert body
        m = re.search(r"maxRetries\s*=\s*(\d+)", body)
        assert m, (
            f"{process_name} retry has no maxRetries cap; a persistent "
            "segfault (corrupt hash.k2d) would spin"
        )
        assert int(m.group(1)) <= 3

    def test_modules_config_drops_mmap_on_second_attempt(
        self, modules_config_text: str
    ):
        """The retry is only useful if attempt 2 stops using mmap."""
        body = _retry_block(modules_config_text, "KRAKEN2_KRAKEN2")
        assert body
        assert "task.attempt == 1" in body and "--memory-mapping" in body, (
            "KRAKEN2_KRAKEN2 ext.args no longer gates --memory-mapping on "
            "task.attempt; a retry would loop on the same SIGSEGV"
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


@pytest.fixture(scope="module")
def classification_subworkflow_text() -> str:
    path = _nanometanf_path(
        "subworkflows/local/taxonomic_classification/main.nf"
    )
    if path is None:
        pytest.skip("nanometanf checkout not found; skipping")
    return path.read_text()


class TestMemoryMappingSingleSourced:
    """The mmap decision must come from the param alone (2026-08-18 audit).

    An ARM force-disable in the classification subworkflow once produced a
    split brain: modules.config's KRAKEN2_KRAKEN2 ext.args read
    params.kraken2_memory_mapping directly, so the standard path ran
    --memory-mapping on ARM while the subworkflow logged it as disabled,
    skipped KRAKEN2_DB_PRELOAD, and stripped the flag from the
    incremental/optimized modules -- realtime mode on an ARM Mac re-loaded
    the full database on every batch. The ARM premise (SIGSEGV under
    Rosetta) did not reproduce on real hardware; the per-module retry
    without the flag remains the safety net.
    """

    def test_subworkflow_takes_the_param_verbatim(
        self, classification_subworkflow_text: str
    ):
        assert (
            "use_memory_mapping = params.kraken2_memory_mapping"
            in classification_subworkflow_text
        ), (
            "taxonomic_classification must assign use_memory_mapping from "
            "params.kraken2_memory_mapping with no platform gating; any "
            "other expression diverges from modules.config's ext.args, "
            "which reads the raw param."
        )

    def test_no_platform_gating_of_the_decision(
        self, classification_subworkflow_text: str
    ):
        assert "os.arch" not in classification_subworkflow_text, (
            "a platform probe is back in the classification subworkflow; "
            "if it feeds the mmap decision the split-brain returns "
            "(subworkflow paths without mmap, ext.args with it)."
        )

    def test_preload_gated_on_the_same_decision(
        self, classification_subworkflow_text: str
    ):
        assert re.search(
            r"if\s*\(\s*use_memory_mapping\s*&&[^)]*\)\s*\{\s*\n\s*KRAKEN2_DB_PRELOAD",
            classification_subworkflow_text,
        ), (
            "KRAKEN2_DB_PRELOAD must run whenever the (single-sourced) "
            "mmap decision is on -- the warm sequential read is what turns "
            "every later load into page-cache hits."
        )
