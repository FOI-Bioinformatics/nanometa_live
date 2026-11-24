"""The per-sample freshness map is rebuilt only when the results tree changed.

``update_sample_freshness`` runs on every interval tick so the age pills
("updated 40 s ago") keep counting, and it rebuilt the map each time: a
scandir plus a stat per file of every ``kraken2/<sample>/batch_reports/``.
That grows with batches per sample -- 86-98 ms per tick at 96 barcodes x
300 batch reports (2026-11-23 bug hunt). The map holds timestamps, which
can only change when a file under ``kraken2/`` changes, and the results
fingerprint already advances on exactly that. So a tick with an unchanged
fingerprint reuses the map; the callback still fires, so ages still count.
"""

from unittest.mock import patch

import pytest

from nanometa_live.app.utils import freshness

pytestmark = pytest.mark.unit


@pytest.fixture
def tree(tmp_path):
    for s in ("barcode01", "barcode02"):
        d = tmp_path / "kraken2" / s / "batch_reports"
        d.mkdir(parents=True)
        (d / "batch_0.kraken2.report.txt").write_text("x")
    freshness.clear_freshness_memo()
    yield tmp_path
    freshness.clear_freshness_memo()


SAMPLES = ["All Samples", "barcode01", "barcode02"]


def _scans(tree, fingerprints):
    real = freshness._max_mtime_in_dir
    calls = {"n": 0}

    def counting(path):
        calls["n"] += 1
        return real(path)

    results = []
    with patch.object(freshness, "_max_mtime_in_dir", counting):
        for fp in fingerprints:
            results.append(freshness.freshness_map_for_fingerprint(
                str(tree), SAMPLES, fp))
    return calls["n"], results


def test_unchanged_fingerprint_reuses_the_map(tree):
    n, results = _scans(tree, [{"fp": "a"}, {"fp": "a"}, {"fp": "a"}])
    assert n == 2            # one scan per sample, once
    assert results[0] == results[1] == results[2]
    assert set(results[0]) == {"barcode01", "barcode02"}


def test_a_new_fingerprint_rescans(tree):
    n, _ = _scans(tree, [{"fp": "a"}, {"fp": "b"}])
    assert n == 4


def test_no_fingerprint_never_memoises(tree):
    n, _ = _scans(tree, [None, None])
    assert n == 4


def test_returned_map_is_a_copy(tree):
    _, results = _scans(tree, [{"fp": "a"}])
    results[0]["barcode01"] = -1
    _, again = _scans(tree, [{"fp": "a"}])
    assert again[0]["barcode01"] != -1


def test_run_boundary_reset_clears_it(tree):
    from nanometa_live.core.utils.loader_utils import clear_all_loader_caches
    _scans(tree, [{"fp": "a"}])
    assert freshness._freshness_memo
    clear_all_loader_caches()
    assert not freshness._freshness_memo
