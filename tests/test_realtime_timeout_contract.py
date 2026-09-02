"""The real-time timeout means the same thing in the pipeline and the GUI.

Round-4 realtime audit (docs/audit/realtime-round4-2026-09-02.md, H1). The
GUI described ``realtime_timeout_minutes`` as minutes "without new files";
nanometanf scheduled a ONE-SHOT timer at timeout plus grace from the start
of monitoring. R1: the timer fired exactly 480,000 ms after monitoring
started while files kept landing every 15 s; 14 of 47 input files were never
classified and the run was reported complete. nanometanf now resets the
clock on every detected file; these pins keep the two sides agreeing.

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
_MONITORING = (_NANOMETANF_PATH / "subworkflows" / "local"
               / "realtime_monitoring" / "main.nf")
_CONFIG = _NANOMETANF_PATH / "nextflow.config"
_FORM = (Path(__file__).resolve().parents[1] / "nanometa_live" / "app"
         / "components" / "config_form.py")


@pytest.mark.skipif(
    not _MONITORING.is_file(),
    reason="nanometanf checkout not present (set NANOMETANF_PATH to enable)",
)
class TestPipelineTimerIsInactivityBased:
    def test_every_detected_file_resets_the_clock(self):
        text = _MONITORING.read_text()
        assert "last_file_at" in text
        # The reset sits on the merged file stream, before the timeout mix.
        reset = text.index("last_file_at.set(System.currentTimeMillis())")
        timeout_block = text.index("if (params.realtime_timeout_minutes)")
        assert reset < timeout_block

    def test_timer_checks_idle_time_rather_than_firing_once(self):
        text = _MONITORING.read_text()
        block = text[text.index("if (params.realtime_timeout_minutes)"):]
        assert "scheduleAtFixedRate" in block
        assert re.search(r"idle_ms\s*<\s*total_timeout_ms", block), \
            "the sentinel must fire only once the idle time exceeds the budget"
        assert "realtime_timer.schedule({" not in block, \
            "a one-shot schedule makes the parameter a wall-clock cap"

    def test_config_comment_describes_inactivity(self):
        text = _CONFIG.read_text()
        line = next(l for l in text.splitlines() if l.strip().startswith("realtime_timeout_minutes"))
        assert "without a new input file" in line


class TestGuiTextMatchesThePipeline:
    def test_form_text_describes_a_resetting_clock(self):
        text = _FORM.read_text()
        assert "resets the clock" in text
        assert "regardless of whether files" not in text
