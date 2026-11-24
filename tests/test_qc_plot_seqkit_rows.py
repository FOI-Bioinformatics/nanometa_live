"""QC plots on a seqkit (chopper) run: real sample names, real times.

The seqkit path named each sample with ``basename(file).split('.')[0]``, so
sample "run.2" plotted as "run", and stamped every point ``datetime.now()``,
so the "cumulative over time" plots put every sample at one instant (live
test 2026-11-24). The loader supplies a ``sample`` column; the time is the
sample's seqkit file mtime.
"""

import os
import time
from datetime import datetime

import pandas as pd
import pytest

from nanometa_live.app.tabs.qc_tab_helpers import seqkit_plot_rows

pytestmark = pytest.mark.unit


def test_rows_use_the_sample_column_and_file_times(tmp_path):
    seqkit = tmp_path / "seqkit"
    seqkit.mkdir()
    t1, t2 = time.time() - 3600, time.time() - 60
    for name, t in (("run.2", t1), ("barcode01", t2)):
        f = seqkit / f"{name}.tsv"
        f.write_text("x")
        os.utime(f, (t, t))
    df = pd.DataFrame([
        {"file": "run.2.fastq.gz", "sample": "run.2", "num_seqs": 10, "sum_len": 1000},
        {"file": "barcode01.fastq.gz", "sample": "barcode01", "num_seqs": 5, "sum_len": 500},
    ])
    rows = seqkit_plot_rows(df, str(seqkit))
    by_name = {r["Sample"]: r for r in rows}
    assert set(by_name) == {"run.2", "barcode01"}
    assert by_name["run.2"]["Time"] == datetime.fromtimestamp(t1)
    assert by_name["barcode01"]["Time"] == datetime.fromtimestamp(t2)
    assert by_name["run.2"]["Reads"] == 10 and by_name["run.2"]["Bp"] == 1000
