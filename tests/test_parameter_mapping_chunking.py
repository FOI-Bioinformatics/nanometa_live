"""The launch sends the chunking and task-memory parameters nanometanf reads.

Chunked batch mode needs the incremental classifier path, so the launch forces
kraken2_enable_incremental on when chunking is on in batch mode. The task
memory is the process's own memory under memory mapping; it is sent only when
the database fits the page cache with room to spare, because forks over a
database larger than RAM thrash the cache and the full reservation, which
serialises them, is the safer choice.
"""

from unittest.mock import patch

import pytest

from nanometa_live.core.config import parameter_mapping as pm

pytestmark = pytest.mark.unit


def _config(tmp_path, **over):
    db = tmp_path / "db"
    db.mkdir()
    (db / "hash.k2d").write_bytes(b"0" * 1024)
    base = {
        "nanopore_output_directory": str(tmp_path),
        "results_output_directory": str(tmp_path / "res"),
        "kraken_db": str(db),
        "processing_mode": "batch",
        "sample_handling": "single_sample",
        "kraken2_enable_incremental": False,
        "batch_chunking": True,
        "batch_first_chunk_files": 2,
        "batch_chunk_growth": 3.0,
    }
    base.update(over)
    (tmp_path / "res").mkdir(exist_ok=True)
    (tmp_path / "reads.fastq.gz").write_bytes(b"\x1f\x8b")
    return base


def test_chunking_params_are_sent_and_incremental_is_forced_on(tmp_path):
    params = pm.create_nextflow_params(_config(tmp_path))
    assert params["batch_chunking"] is True
    assert params["batch_first_chunk_files"] == 2
    assert params["batch_chunk_growth"] == 3.0
    assert params["kraken2_enable_incremental"] is True


def test_chunking_off_leaves_incremental_alone(tmp_path):
    params = pm.create_nextflow_params(_config(tmp_path, batch_chunking=False))
    assert params["batch_chunking"] is False
    # Batch mode sends no incremental switch today (the key is set in the
    # real-time branch only), so "left alone" means absent or False.
    assert params.get("kraken2_enable_incremental") in (None, False)


def test_chunking_is_not_sent_in_realtime_mode(tmp_path):
    params = pm.create_nextflow_params(_config(tmp_path, processing_mode="realtime"))
    assert "batch_chunking" not in params


class TestTaskMemory:
    def test_small_database_gets_the_floor(self, tmp_path):
        cfg = _config(tmp_path)
        with patch.object(pm, "_host_memory_bytes", return_value=18 * 1024 ** 3):
            assert pm._resolve_kraken2_task_memory_gb(cfg) == 4

    def test_large_database_gets_none(self, tmp_path):
        cfg = _config(tmp_path)
        (tmp_path / "db" / "hash.k2d").write_bytes(b"0" * (12 * 1024 ** 3 // 1024))  # sparse-ish stand-in
        with patch.object(pm, "_host_memory_bytes", return_value=16 * 1024 ** 3), \
             patch.object(pm, "_hash_bytes", return_value=12 * 1024 ** 3):
            assert pm._resolve_kraken2_task_memory_gb(cfg) is None

    def test_memory_mapping_off_gets_none(self, tmp_path):
        # The resolver delegates to _resolve_kraken2_memory_mapping, which
        # reads the established "kraken_memory_mapping" config key (no "2";
        # see its docstring), not the "kraken2_memory_mapping" pipeline
        # parameter name.
        cfg = _config(tmp_path, kraken_memory_mapping=False)
        assert pm._resolve_kraken2_task_memory_gb(cfg) is None

    def test_explicit_value_wins(self, tmp_path):
        cfg = _config(tmp_path, kraken2_task_memory_gb=6)
        assert pm._resolve_kraken2_task_memory_gb(cfg) == 6

    def test_sent_to_the_pipeline(self, tmp_path):
        with patch.object(pm, "_host_memory_bytes", return_value=18 * 1024 ** 3):
            params = pm.create_nextflow_params(_config(tmp_path))
        assert params["kraken2_task_memory_gb"] == 4
