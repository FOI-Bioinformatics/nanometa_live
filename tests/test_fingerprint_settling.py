"""The results fingerprint must move when a just-written file settles.

The loaders skip a report younger than the stability window (1 s,
``_is_file_stable``). A poll that lands inside that window fingerprints the
new file, triggers every results-driven panel, and those panels render
without it -- then record the fingerprint as rendered. The file settles by
time passing, which changes no mtime, so the fingerprint used to stay put
and every later backstop tick was judged redundant: the Organisms, QC and
Validation panels (store-backed memo, no TTL) stayed on the previous batch
until the next file landed, which for the last file of a run is never.

The fingerprint therefore carries a settling marker while the newest file
of a watched subdirectory is inside the window; its disappearance is the
change that re-renders the panels.
"""

import time
from unittest.mock import patch

import pytest

from nanometa_live.core.utils import loader_utils
from nanometa_live.core.utils.loader_utils import check_data_freshness

pytestmark = pytest.mark.unit


def _write_report(tmp_path):
    kdir = tmp_path / "kraken2"
    kdir.mkdir()
    path = kdir / "barcode01.kraken2.report.txt"
    path.write_text("100.00\t10\t10\tU\t0\tunclassified\n")
    return str(path)


def test_fingerprint_changes_once_the_newest_file_settles(tmp_path):
    _write_report(tmp_path)
    now = time.time()

    with patch.object(loader_utils.time, "time", return_value=now + 0.2):
        inside_window = check_data_freshness(str(tmp_path))
    with patch.object(loader_utils.time, "time", return_value=now + 5.0):
        settled = check_data_freshness(str(tmp_path))
    with patch.object(loader_utils.time, "time", return_value=now + 15.0):
        later = check_data_freshness(str(tmp_path))

    assert inside_window != settled
    # Once settled, a quiet tree keeps one fingerprint.
    assert settled == later


@pytest.mark.parametrize("offset", [0.2, 0.9, 1.1, 3.0])
def test_the_settling_window_matches_the_loaders(tmp_path, offset):
    """A file the loaders call stable must not be marked as settling."""
    path = _write_report(tmp_path)
    mtime = __import__("os").stat(path).st_mtime
    with patch.object(loader_utils.time, "time", return_value=mtime + offset):
        stable = loader_utils._is_file_stable(path)
        fp = check_data_freshness(str(tmp_path))
    with patch.object(loader_utils.time, "time", return_value=mtime + 60):
        settled_fp = check_data_freshness(str(tmp_path))
    assert (fp == settled_fp) == stable
