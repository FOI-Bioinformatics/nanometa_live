"""The test suite must never touch the operator's real ~/.nanometa.

Found live (2026-08-25): a full ``pytest`` run rewrote a 57-byte mock
``263.fasta`` into the real ``~/.nanometa/genomes/`` -- tests constructed
``OnDemandValidator`` without ``cache_dir``, whose fallback is
``get_data_dir_from_env()`` and, with no env var set, the operator's home
data dir. The mock genome then shadowed the real one, and every subsequent
GUI-launched validation mapped reads against 20 bp of ACGT and reported
"rejected" (the empty Validation tab in the Bioshield demo rehearsal).

The fence: ``tests/conftest.py`` exports ``NANOMETA_DATA_DIR`` and
``NANOMETA_PROJECT_DIR`` into a per-session temp sandbox at import time, so
even a test that forgets to isolate itself writes to the sandbox. These
tests pin the sandbox and the default-construction paths that leaked.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REAL_HOME_DATA_DIR = Path(os.path.expanduser("~/.nanometa")).resolve()


class TestSessionSandbox:
    def test_data_dir_env_points_away_from_the_real_home(self):
        value = os.environ.get("NANOMETA_DATA_DIR")
        assert value, "conftest must export NANOMETA_DATA_DIR for the session"
        assert Path(value).resolve() != REAL_HOME_DATA_DIR

    def test_project_dir_env_points_away_from_the_projects_root(self):
        value = os.environ.get("NANOMETA_PROJECT_DIR")
        assert value, "conftest must export NANOMETA_PROJECT_DIR for the session"
        assert not str(Path(value).resolve()).startswith(
            os.path.expanduser("~/nanometa-projects"))

    def test_env_resolver_returns_the_sandbox(self):
        from nanometa_live.core.utils.paths import get_data_dir_from_env
        assert Path(get_data_dir_from_env()).resolve() != REAL_HOME_DATA_DIR


class TestDefaultConstructionsLandInTheSandbox:
    """The constructors that leaked: with no explicit cache_dir they must
    resolve inside the sandbox, never the real home."""

    def test_on_demand_validator_default_cache_dir(self, tmp_path):
        from nanometa_live.core.workflow.on_demand_validator import (
            OnDemandValidator,
        )
        v = OnDemandValidator(results_dir=str(tmp_path / "results"),
                              input_dir=None)
        genomes = Path(v.genomes_dir).resolve()
        assert not str(genomes).startswith(str(REAL_HOME_DATA_DIR)), (
            f"OnDemandValidator default genomes_dir escaped the sandbox: "
            f"{genomes}"
        )

    def test_genome_manager_default_cache_dir(self):
        from nanometa_live.core.utils.genome_manager import (
            GenomeDownloadManager,
        )
        gm = GenomeDownloadManager()
        genomes = Path(gm.genomes_dir).resolve()
        assert not str(genomes).startswith(str(REAL_HOME_DATA_DIR)), (
            f"GenomeDownloadManager default genomes_dir escaped the "
            f"sandbox: {genomes}"
        )
