"""The dashboard's realtime liveness depends on per-batch cumulative reports.

Every cumulative-tier surface (Sequences Analyzed, Organisms, the loaders'
primary ``*.cumulative.kraken2.report.txt`` glob) is blind until nanometanf's
progressive writer flushes. With the old default (every 5th batch per
sample), the 2026-08-18 realtime audit watched the tile sit at 0 for six
minutes while the verdict banner -- fed from latest-batch data -- already
showed ACTION REQUIRED. These pins keep the pipeline side of that contract:

- the default write interval is 1 (per batch);
- a sample's FIRST batch always flushes, whatever the interval;
- the interval is read null-safely, not with the elvis operator, which
  treated the documented "0 = every batch" value as falsy and silently
  turned it into the old default.

Same NANOMETANF_PATH self-skip pattern as test_validation_threshold_contract.
"""

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_NANOMETANF_PATH = Path(
    os.environ.get("NANOMETANF_PATH", str(Path.home() / "Code" / "nanometanf"))
)
_CONFIG = _NANOMETANF_PATH / "nextflow.config"
_SUBWORKFLOW = (_NANOMETANF_PATH / "subworkflows" / "local"
                / "taxonomic_classification" / "main.nf")


@pytest.mark.skipif(
    not _CONFIG.is_file(),
    reason="nanometanf checkout not present (set NANOMETANF_PATH to enable)",
)
class TestProgressiveReportLiveness:
    def test_default_interval_is_per_batch(self):
        text = _CONFIG.read_text()
        match = re.search(
            r"^\s*report_write_interval\s*=\s*(\d+)", text, re.MULTILINE
        )
        assert match, "report_write_interval not declared in nextflow.config"
        assert int(match.group(1)) == 1, (
            "the progressive cumulative report must flush every batch by "
            "default: the state merge runs per batch regardless, so a larger "
            "interval saves only a small file write while blinding the "
            "dashboard's cumulative tier for its first N batches"
        )

    def test_first_batch_always_flushes(self):
        text = _SUBWORKFLOW.read_text()
        assert re.search(
            r"batch_write_counter\[sample_id\]\s*==\s*1\s*\n\s*\|\|", text
        ), (
            "the first-batch flush clause is gone: an operator-configured "
            "coarse interval would again blind the dashboard until batch N"
        )

    def test_interval_read_is_null_safe_not_elvis(self):
        text = _SUBWORKFLOW.read_text()
        assert "params.report_write_interval ?:" not in text, (
            "the elvis operator treats 0 (documented as 'every batch') as "
            "falsy and replaces it with the fallback -- use an explicit "
            "null check"
        )
        assert "params.report_write_interval == null" in text
