"""Regression test for the Kraken2 DB-publication bug (2026-05-11).

Symptom on a real server run: the full Kraken2 database (10-100 GB)
was duplicated under ``<outdir>/kraken2/<dbname>/`` on every pipeline
launch, while the GUI's loader sat at zero sequences for many minutes
because the actual Kraken2 reports could not appear until the
``publishDir copy`` step had finished writing the whole DB to disk.

Root cause: ``KRAKEN2_DB_PRELOAD``
(``nanometanf/modules/local/kraken2_db_preload/main.nf``) declares
``output: path db, emit: db`` as a channel-ordering passthrough.
Without an explicit ``publishDir`` override the global default in
``conf/modules.config:41-45`` (``mode: copy``, no pattern filter)
copies the entire database directory to ``<outdir>/kraken2/``. The
``withName: 'KRAKEN2_DB_PRELOAD'`` block we added restricts
publication to ``versions.yml`` only.

This test pins the contract at source level so a future template
sync or nf-core refresh cannot silently re-introduce the bug.

The test reads ``nanometanf/conf/modules.config`` directly from the
sibling repo at ``~/Code/nanometanf``. If that checkout is missing
(operator running the GUI without the pipeline source) the test is
skipped rather than failed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


def _nanometanf_modules_config() -> Path | None:
    """Locate the sibling nanometanf checkout's modules.config.

    The pipeline lives outside this repo, so we look in the conventional
    side-by-side checkout location. Return ``None`` if absent so the
    test self-skips on machines that only have nanometa_live.
    """
    candidates = [
        Path.home() / "Code" / "nanometanf" / "conf" / "modules.config",
        Path("/Users/andreassjodin/Code/nanometanf/conf/modules.config"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def modules_config_text() -> str:
    path = _nanometanf_modules_config()
    if path is None:
        pytest.skip(
            "nanometanf/conf/modules.config not found; this test requires "
            "the sibling pipeline repo to be checked out at ~/Code/nanometanf"
        )
    return path.read_text()


class TestKraken2DbPreloadPublishDirOverride:
    """KRAKEN2_DB_PRELOAD must have an explicit publishDir override."""

    def test_withname_block_present(self, modules_config_text):
        """A ``withName: 'KRAKEN2_DB_PRELOAD'`` selector must exist."""
        assert re.search(
            r"withName:\s*['\"]KRAKEN2_DB_PRELOAD['\"]",
            modules_config_text,
        ), (
            "Missing withName: 'KRAKEN2_DB_PRELOAD' block in "
            "nanometanf/conf/modules.config. Without this override the "
            "default global publishDir (mode: copy, no pattern filter) "
            "duplicates the entire Kraken2 database into "
            "${params.outdir}/kraken2/ on every pipeline run -- "
            "blocking the pipeline on SAN write throughput and "
            "delaying Kraken2 report production by minutes."
        )

    def test_block_restricts_to_versions_yml(self, modules_config_text):
        """The block's publishDir pattern must filter to ``versions.yml``."""
        # Locate the block body.
        block_pattern = re.compile(
            r"withName:\s*['\"]KRAKEN2_DB_PRELOAD['\"]\s*\{(?P<body>.*?)\n    \}",
            re.DOTALL,
        )
        match = block_pattern.search(modules_config_text)
        assert match, "withName: 'KRAKEN2_DB_PRELOAD' block found but body "\
            "could not be extracted; check the brace indentation"

        body = match.group("body")
        assert "publishDir" in body, (
            "KRAKEN2_DB_PRELOAD block exists but does not override "
            "publishDir. Add a publishDir = [...] entry that filters "
            "by pattern: 'versions.yml' so the DB directory is not "
            "republished."
        )
        assert "versions.yml" in body, (
            "KRAKEN2_DB_PRELOAD publishDir override is present but does "
            "not include a pattern: 'versions.yml' filter -- the db "
            "directory will leak through. Restrict to versions.yml."
        )
