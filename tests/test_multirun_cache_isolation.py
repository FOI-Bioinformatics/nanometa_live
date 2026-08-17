"""Multi-run isolation: no run-A data may survive into run B's GUI.

Reproduces the 2026-08-17 audit findings C1-C3:

- C1: ``canonical/`` was missing from ``BackendManager.RESULT_SUBDIRS``, so
  Archive left run A's canonical tree in place, the collision modal stayed
  silent on a canonical-only outdir, and the loaders (which consult
  ``canonical/`` before any cache) kept serving run A's sample list and
  classification during run B.
- C2: no production code path cleared the loader caches on a new run.
- C3: a missing ``kraken2/`` dir (the archive -> first-batch window) left the
  mtime state at ``absent``, which fell through to the TTL cache and served
  run A's frame for up to CACHE_TTL_SECONDS.
"""

import json
import os
import time

import pytest

from nanometa_live.core.utils import loader_utils
from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
from nanometa_live.core.utils.sample_detector import get_available_samples
from nanometa_live.core.workflow.backend_manager import BackendManager

RUN_A_REPORT = (
    " 24.05\t1972\t1972\tU\t0\tunclassified\n"
    " 75.95\t6228\t0\tR\t1\troot\n"
    " 62.00\t5083\t0\tD\t2\t  Bacteria\n"
    " 62.00\t5083\t0\tG\t262\t    Francisella\n"
    " 62.00\t5083\t5083\tS\t263\t      Francisella tularensis\n"
)


def _backdate_tree(path):
    old = time.time() - 120
    for root, _dirs, files in os.walk(path):
        for name in files:
            os.utime(os.path.join(root, name), (old, old))


def _write_run_a(outdir, samples=("barcode01", "barcode02")):
    kraken = outdir / "kraken2"
    kraken.mkdir(parents=True)
    for s in samples:
        (kraken / f"{s}.kraken2.report.txt").write_text(RUN_A_REPORT)
    canonical = outdir / "canonical" / "classification"
    canonical.mkdir(parents=True)
    taxa = [
        {"percent": 62.0, "reads_clade": 5083, "reads_direct": 5083,
         "rank": "S", "taxid": 263, "name": "Francisella tularensis"},
    ]
    for s in samples:
        (canonical / f"{s}.classification.json").write_text(
            json.dumps({"sample_id": s, "taxa": taxa})
        )
    (outdir / "canonical" / "_manifest.json").write_text(
        json.dumps({"samples": list(samples), "failed_samples": []})
    )
    _backdate_tree(str(outdir))


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_all_loader_caches()
    yield
    clear_all_loader_caches()


class TestResultSubdirsCoverCanonical:
    def test_canonical_in_result_subdirs(self):
        assert "canonical" in BackendManager.RESULT_SUBDIRS

    def test_pipeline_info_in_result_subdirs(self):
        assert "pipeline_info" in BackendManager.RESULT_SUBDIRS

    def test_collision_fires_on_canonical_only_outdir(self, tmp_path):
        canonical = tmp_path / "canonical" / "classification"
        canonical.mkdir(parents=True)
        (canonical / "barcode01.classification.json").write_text("{}")
        assert "canonical" in BackendManager.detect_existing_results(
            str(tmp_path)
        )

    def test_archive_moves_canonical(self, tmp_path):
        _write_run_a(tmp_path)
        archive = BackendManager.archive_existing_results(str(tmp_path))
        assert archive is not None
        assert not (tmp_path / "canonical").exists()
        assert (
            os.path.isdir(os.path.join(archive, "canonical"))
        )


class TestClearAllLoaderCaches:
    def test_archive_then_reload_serves_no_run_a_data(self, tmp_path):
        """The full leak scenario: run A on screen, Archive, run B polls."""
        _write_run_a(tmp_path)
        outdir = str(tmp_path)

        # Poll 1: run A on screen -- populates every cache layer.
        samples_a = get_available_samples(outdir)
        assert "barcode01" in samples_a
        df_a = load_kraken_data(outdir, "barcode01")
        assert "Francisella tularensis" in set(df_a["name"])
        agg_a = load_kraken_data(outdir)
        assert agg_a is not None and len(agg_a) > 0

        # Operator archives run A.
        assert BackendManager.archive_existing_results(outdir) is not None

        # Poll 2, immediately (inside the old TTL window): nothing from
        # run A may be served.
        samples_mid = get_available_samples(outdir)
        assert "barcode01" not in samples_mid
        df_mid = load_kraken_data(outdir, "barcode01")
        assert df_mid is None or len(df_mid) == 0
        agg_mid = load_kraken_data(outdir)
        assert agg_mid is None or len(agg_mid) == 0

    def test_clear_all_loader_caches_clears_kraken_ttl(self, tmp_path):
        _write_run_a(tmp_path)
        outdir = str(tmp_path)
        load_kraken_data(outdir)
        assert loader_utils._kraken_cache or loader_utils._file_mtimes
        clear_all_loader_caches()
        assert not loader_utils._kraken_cache
        assert not loader_utils._file_mtimes

    def test_clear_all_loader_caches_clears_alert_history(self):
        from nanometa_live.core.utils.alert_engine import get_alert_engine

        engine = get_alert_engine()
        engine.alert_history.append(object())
        clear_all_loader_caches()
        assert len(engine.alert_history) == 0


class TestFirstBatchFlagFollowsDisk:
    """C5: the 'first batch arrived' flag must reflect the current outdir."""

    def _fn(self):
        from unittest.mock import MagicMock

        from dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.callbacks.status import register_status

        app = make_callback_app(
            lambda a: register_status(a, MagicMock())
        )
        return get_callback_fn(
            app, "results-fingerprint.data", input_contains="app-config"
        )

    def test_flag_resets_when_outdir_is_emptied(self, tmp_path):
        fn = self._fn()
        prev = {"fp": "run-a-fp", "ts": 0, "first_batch_seen": True}
        out = fn(1, {"main_dir": str(tmp_path)}, prev)
        assert out["first_batch_seen"] is False

    def test_flag_set_when_data_present(self, tmp_path):
        (tmp_path / "kraken2").mkdir()
        (tmp_path / "kraken2" / "s.kraken2.report.txt").write_text(
            RUN_A_REPORT
        )
        fn = self._fn()
        out = fn(1, {"main_dir": str(tmp_path)}, None)
        assert out["first_batch_seen"] is True


class TestOnDemandStoreSync:
    """C4: the on-demand store must track the disk, not freeze on first load."""

    def _fn(self):
        from dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.tabs.main_tab import register_main_callbacks

        app = make_callback_app(register_main_callbacks)
        return get_callback_fn(
            app,
            "on-demand-validation-results.data",
            input_contains="update-interval",
        )

    @staticmethod
    def _write_result(outdir, taxid=263):
        od = outdir / "on_demand_validation"
        od.mkdir(parents=True, exist_ok=True)
        (od / f"s_{taxid}_validation.json").write_text(
            json.dumps({"taxid": taxid, "validation_rate": 90.0})
        )

    def test_reads_results_output_directory_like_the_writer(self, tmp_path):
        results = tmp_path / "results"
        self._write_result(results)
        cfg = {
            "results_output_directory": str(results),
            "main_dir": str(tmp_path / "project"),
        }
        store, _ = self._fn()(1, cfg, {})
        assert "263" in store

    def test_clears_store_when_directory_disappears(self, tmp_path):
        cfg = {"results_output_directory": str(tmp_path)}
        stale = {"263": {"taxid": 263, "validation_rate": 90.0}}
        store, _ = self._fn()(1, cfg, stale)
        assert store == {}

    def test_replaces_stale_results_after_run_switch(self, tmp_path):
        results = tmp_path / "results"
        self._write_result(results, taxid=1392)
        cfg = {"results_output_directory": str(results)}
        stale = {"263": {"taxid": 263, "validation_rate": 90.0}}
        store, _ = self._fn()(1, cfg, stale)
        assert "1392" in store and "263" not in store

    def test_no_update_when_disk_unchanged(self, tmp_path):
        from dash import no_update

        results = tmp_path / "results"
        self._write_result(results)
        cfg = {"results_output_directory": str(results)}
        current = {"263": {"taxid": 263, "validation_rate": 90.0}}
        store, _ = self._fn()(1, cfg, current)
        assert store is no_update


class TestMissingDirSkipsTtl:
    def test_removed_kraken_dir_is_stale_not_absent(self, tmp_path):
        """C3: after kraken2/ vanishes, the TTL cache must not answer."""
        import shutil

        _write_run_a(tmp_path)
        outdir = str(tmp_path)
        df_a = load_kraken_data(outdir)
        assert df_a is not None and len(df_a) > 0

        shutil.rmtree(tmp_path / "kraken2")
        shutil.rmtree(tmp_path / "canonical")

        # Mirror the poll: compute_results_fingerprint always runs
        # check_data_freshness before any loader, which bumps the epoch
        # when the tree changed. Without it, the once-per-poll epoch
        # shortcut may legitimately answer from cache -- that shortcut is
        # scoped to a single poll by design.
        loader_utils.check_data_freshness(outdir)

        # Within CACHE_TTL_SECONDS of the first load: must not serve run A.
        df_after = load_kraken_data(outdir)
        assert df_after is None or len(df_after) == 0
