"""The Dashboard alerts panel must not report a measurement it did not make.

``_generate_alerts`` defaulted the classified rate to 0.0 whenever the
Kraken2 frame was empty or held no reads, and the alert engine read that as
a measured rate under its 20% critical floor: an empty results directory
showed CRITICAL "Low organism identification: 0.0% of sequences
classified". The run-state half (the completion alert) is upstream's
run_status_for_alerts; the last test pins that it reaches the engine.
"""

import os
import time

import pytest

from nanometa_live.app.tabs.dashboard_helpers import _generate_alerts
from nanometa_live.core.utils.loader_utils import clear_all_loader_caches

pytestmark = pytest.mark.unit


def _messages(alerts):
    return [a.get("message", "") for a in alerts]


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_all_loader_caches()
    yield
    clear_all_loader_caches()


def test_no_classification_alert_without_reads(tmp_path):
    (tmp_path / "kraken2").mkdir()
    alerts = _generate_alerts({"total_reads": 0}, str(tmp_path), {}, [],
                              taxid_to_samples={})
    assert not any("organism identification" in m for m in _messages(alerts))


def test_low_classification_alert_still_fires_on_measured_data(tmp_path):
    kdir = tmp_path / "kraken2"
    kdir.mkdir()
    p = kdir / "barcode01.kraken2.report.txt"
    p.write_text("95.00\t95\t95\tU\t0\tunclassified\n"
                 "5.00\t5\t5\tR\t1\troot\n")
    old = time.time() - 60
    os.utime(p, (old, old))
    alerts = _generate_alerts({"total_reads": 100}, str(tmp_path), {}, [],
                              taxid_to_samples={})
    assert any("organism identification: 5.0%" in m for m in _messages(alerts))


def test_completed_run_reaches_the_alert_engine(tmp_path):
    (tmp_path / "kraken2").mkdir()
    from nanometa_live.app.tabs.dashboard_helpers import run_status_for_alerts
    overall = {"total_reads": 0,
               **run_status_for_alerts({"running": False, "completed": True})}
    alerts = _generate_alerts(overall, str(tmp_path), {}, [],
                              taxid_to_samples={})
    assert any(m.startswith("Analysis completed") for m in _messages(alerts))
