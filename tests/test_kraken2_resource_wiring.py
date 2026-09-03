"""Kraken2 resource wiring: the GUI must not undo nanometanf's sizing.

The 2026-08-18 kraken2 optimization audit found that GUI-launched runs
classified single-threaded with an 8 GB cap on an 11-core machine:

- ``create_nextflow_config`` pinned ``KRAKEN2_KRAKEN2 { cpus = 1;
  memory = '8.GB' }`` into the ``-c`` config, which outranks every
  nanometanf config layer -- flattening the pipeline's own
  ``cpus = max(4, max_cpus/forks)`` scaling, its ``kraken2_memory_gb``
  sizing and its resourceLimits ceiling. The ``1`` came from
  ``create_default_config``'s ``kraken_cores: 1``, a v1/Snakemake-era
  fossil no widget could raise past the form's own default.
- ``create_default_config`` wrote ``kraken_memory_mapping: True`` into
  every config, so ``_resolve_kraken2_memory_mapping``'s "explicit
  override wins" branch always fired and its platform logic was dead
  code -- the ``min_perc_identity`` pattern.

Both defaults are retired (the skip-backward-compat convention: no shim,
old configs simply stop being consulted for the removed pin). Memory
mapping now defaults to True everywhere: the 2026-08-18 release check ran
51 tasks with ``--memory-mapping`` under Rosetta on an ARM Mac with zero
SIGSEGVs, and nanometanf retries without the flag on attempt 2 anyway.

``kraken2_memory_gb`` is derived from the actual database (hash.k2d size
+ 4 GB headroom, floor 12 = nanometanf's default) so operators with a
PlusPFP-sized database no longer OOM on a default sized for MiniKraken.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.config.parameter_mapping import (
    _resolve_kraken2_memory_gb,
    _resolve_kraken2_memory_mapping,
    create_nextflow_config,
)


class TestCustomConfigNoKrakenPin:
    def test_no_kraken2_withname_block(self):
        text = create_nextflow_config({"pipeline_profile": "conda"})
        assert "KRAKEN2_KRAKEN2" not in text, (
            "the -c config pins KRAKEN2_KRAKEN2 resources again; this "
            "outranks nanometanf's modules.config and forces "
            "single-threaded classification (2026-08-18 audit)"
        )

    def test_other_blocks_survive(self):
        text = create_nextflow_config({"pipeline_profile": "conda"})
        assert "NANOPLOT" in text
        assert "report {" in text


class TestRetiredDefaults:
    def test_default_config_carries_neither_key(self, tmp_path):
        cfg = ConfigLoader(str(tmp_path)).create_default_config()
        assert "kraken_cores" not in cfg, (
            "kraken_cores: 1 back in the defaults re-pins classification "
            "to one thread for every operator who never edits the field"
        )
        assert "kraken_memory_mapping" not in cfg, (
            "a default kraken_memory_mapping makes the resolver's "
            "'explicit override wins' branch unconditional -- the "
            "min_perc_identity pattern"
        )


class TestMemoryMappingResolution:
    def test_defaults_to_true_even_on_arm(self):
        with patch("nanometa_live.core.config.parameter_mapping.platform") as m:
            m.machine.return_value = "arm64"
            assert _resolve_kraken2_memory_mapping({}) is True, (
                "mmap must default ON: the 2026-08-18 release check ran 51 "
                "tasks with --memory-mapping under Rosetta on ARM with zero "
                "SIGSEGVs, and nanometanf drops the flag on retry anyway. "
                "Defaulting False costs a full private DB load per task."
            )

    def test_explicit_config_key_wins(self):
        assert _resolve_kraken2_memory_mapping(
            {"kraken_memory_mapping": False}
        ) is False
        assert _resolve_kraken2_memory_mapping(
            {"kraken_memory_mapping": True}
        ) is True


class TestKraken2MemoryFromDatabase:
    def _db(self, tmp_path, hash_bytes):
        db = tmp_path / "db"
        db.mkdir()
        with open(db / "hash.k2d", "wb") as f:
            f.seek(hash_bytes - 1)
            f.write(b"\0")
        return db

    def test_sized_from_hash_file_plus_headroom(self, tmp_path):
        db = self._db(tmp_path, 24 * 1024**3)  # sparse 24 GiB
        gb = _resolve_kraken2_memory_gb({"kraken_db": str(db)})
        assert gb == 28, (
            "a 24 GiB hash.k2d needs DB + 4 GB headroom; the old flat "
            "8 GB pin OOM'd or thrashed anything bigger than MiniKraken"
        )

    def test_floor_is_nanometanf_default(self, tmp_path):
        db = self._db(tmp_path, 1 * 1024**3)
        assert _resolve_kraken2_memory_gb({"kraken_db": str(db)}) == 12

    def test_explicit_config_key_wins(self, tmp_path):
        db = self._db(tmp_path, 24 * 1024**3)
        gb = _resolve_kraken2_memory_gb(
            {"kraken_db": str(db), "kraken2_memory_gb": 64}
        )
        assert gb == 64

    def test_unreadable_database_omits_the_param(self, tmp_path):
        assert _resolve_kraken2_memory_gb(
            {"kraken_db": str(tmp_path / "missing")}
        ) is None, (
            "with no measurable database the param must be omitted so "
            "nanometanf's own default applies, not a guess"
        )
