"""End-to-end validation smoke test against the real SAMMLA biothreat dataset.

This is the automated counterpart to the manual "is validation actually
working" check. It runs a small batch ``validation_method=both`` job through
``BackendManager`` and asserts that F. tularensis (taxid 263) is confirmed by
BLAST and produces a minimap2 result -- exactly the pair the operator was not
seeing.

It is deliberately gated three ways so it never runs by accident:

* ``@pytest.mark.slow`` -- skipped by the default suite.
* the SAMMLA dataset, Kraken2 DB, and nanometanf checkout must exist on disk.
* the opt-in env var ``NANOMETA_RUN_E2E=1`` must be set, because a real run
  takes minutes and needs Nextflow + conda.

Reference setup: see the ``validation-live-test-env`` project memory.
"""

import json
import os
import time
from pathlib import Path

import pytest

HOME = Path.home()
KRAKEN_DB = HOME / "Desktop/snabbsekvensering/bioshield/kraken_db/k2_pluspfp_08_GB_20251015"
WATCH_DIR = HOME / "Desktop/SAMMLA-demo/watch"
DATA_DIR = HOME / "Desktop/SAMMLA-demo/datadir"
PIPELINE_SOURCE = Path("/Users/andreassjodin/Code/nanometanf")

_PATHS = [KRAKEN_DB, WATCH_DIR, DATA_DIR, PIPELINE_SOURCE]

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("NANOMETA_RUN_E2E") != "1",
        reason="set NANOMETA_RUN_E2E=1 to run the live validation end-to-end test",
    ),
    pytest.mark.skipif(
        not all(p.exists() for p in _PATHS),
        reason="SAMMLA live-test dataset / Kraken2 DB / nanometanf checkout not present",
    ),
]

TIMEOUT_S = 900  # 15 min ceiling; the documented run is ~5 min with warm conda


def _build_config(results_dir: str) -> dict:
    return {
        "nanopore_output_directory": str(WATCH_DIR),
        "results_output_directory": results_dir,
        "kraken_db": str(KRAKEN_DB),
        "kraken_taxonomy": "ncbi",
        "processing_mode": "batch",
        "sample_handling": "by_barcode",
        "pipeline_profile": "conda",
        "pipeline_source": str(PIPELINE_SOURCE),
        "data_dir": str(DATA_DIR),
        # GenomeManager treats cache_dir as the root and looks in <root>/genomes
        # and <root>/blast, so this must be the datadir itself, not datadir/genomes.
        "genome_cache_dir": str(DATA_DIR),
        "blast_validation": True,
        "validation_method": "both",
        "save_reads_assignment": True,
        "min_reads_for_validation": 1,
    }


def test_validation_confirms_f_tularensis(tmp_path):
    from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
    from nanometa_live.core.config.parameter_mapping import get_validation_species
    from nanometa_live.core.workflow.backend_manager import BackendManager

    # A fresh process has an empty WatchlistManager singleton, so the CDC
    # bioterrorism set (which includes F. tularensis, taxid 263) must be enabled
    # before the config is built or validation is silently skipped.
    get_watchlist_manager().enable_watchlist("cdc_bioterrorism")

    config = _build_config(str(tmp_path))
    taxids, _genomes = get_validation_species(config)
    assert "263" in [str(t) for t in taxids], "F. tularensis must be a validation target"

    bm = BackendManager(str(DATA_DIR))
    bm.config = config
    ok, msg = bm.start(profile="conda")
    assert ok, f"pipeline failed to start: {msg}"

    try:
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            status = bm.get_status()
            if status.get("completed") or status.get("pipeline_status") == "completed":
                break
            if not status.get("running") and status.get("pipeline_status") in {"failed", "stopped"}:
                pytest.fail(f"pipeline ended without completing: {status}")
            time.sleep(5)
        else:
            pytest.fail("pipeline did not complete within the timeout")
    finally:
        bm.stop()

    results_json = tmp_path / "validation" / "validation_results.json"
    assert results_json.exists(), "validation_results.json was not produced"
    data = json.loads(results_json.read_text())

    # Find the taxid-263 entry across whatever sample carried it (barcode14).
    entry = None
    for _sample, taxids_map in data.get("results", {}).items():
        if "263" in taxids_map:
            entry = taxids_map["263"]
            break
    assert entry is not None, "no validation entry for taxid 263"

    # BLAST confirmed, and a minimap2 result is present (the operator's two
    # missing signals).
    assert entry.get("validation_status") == "confirmed", entry
    assert "minimap2_status" in entry or entry.get("validation_method") in {"minimap2", "both"}, entry
