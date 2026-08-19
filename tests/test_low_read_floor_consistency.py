"""One configured floor, honoured by every surface that reports depth.

``min_reads_for_validation`` is the operator's "how thin is too thin" knob.
Three surfaces quote it:

- the Organisms tab's not-detected caveat (`main_tab.py`, reads the config),
- the exported report's depth branch (`report_generator.py`, reads the config),
- the verdict banner's INSUFFICIENT_READS gate (`dashboard_helpers.py`).

Only the first two actually read it. ``select_verdict`` takes a
``low_read_floor`` argument that defaults to ``DEFAULT_LOW_READ_FLOOR``, and
``update_verdict_banner`` never passed the configured value -- so the banner
applied a hard-coded number while its two siblings applied the operator's.

That was survivable while both numbers were 50. Lowering the shipped default
to 10 for low-abundance screening makes them disagree by default: the same
run would be called thin by the banner and adequate by the report. The
callback now passes the config value, and the shipped default is 10.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.app.tabs.dashboard_helpers import (
    DEFAULT_LOW_READ_FLOOR,
    select_verdict,
)


class TestShippedDefault:
    def test_default_config_floor_is_ten(self, tmp_path):
        from nanometa_live.core.config.config_loader import ConfigLoader

        cfg = ConfigLoader(str(tmp_path)).create_default_config()
        assert cfg["min_reads_for_validation"] == 10, (
            "the shipped floor drives the Organisms caveat, the report's "
            "depth branch and the verdict banner; low-abundance screening "
            "needs it at 10"
        )

    def test_module_default_matches_the_config_default(self):
        assert DEFAULT_LOW_READ_FLOOR == 10, (
            "the fallback used when no config value is present must not "
            "contradict the shipped default"
        )


class TestBannerHonoursTheConfiguredFloor:
    """The gate itself, exercised through the pure selector."""

    def _verdict(self, total_reads, floor):
        return select_verdict(
            has_config=True,
            pipeline_running=False,
            overall_status_starting=False,
            main_dir_available=True,
            kraken_has_data=True,
            dangerous=[],
            n_watched=5,
            validation_has_results=False,
            total_reads=total_reads,
            low_read_floor=floor,
        )

    def test_below_a_configured_floor_is_insufficient(self):
        assert self._verdict(8, 10).state == "INSUFFICIENT_READS"

    def test_at_the_floor_is_a_real_all_clear(self):
        assert self._verdict(10, 10).state == "ALL_CLEAR"

    def test_a_raised_floor_is_respected(self):
        # An operator who wants 500 reads before trusting a negative gets it.
        assert self._verdict(120, 500).state == "INSUFFICIENT_READS"
        assert self._verdict(600, 500).state == "ALL_CLEAR"


class TestCallbackPassesTheConfiguredFloor:
    SOURCE = (
        Path(__file__).resolve().parents[1]
        / "nanometa_live" / "app" / "tabs" / "dashboard_tab.py"
    )

    def test_verdict_call_site_supplies_low_read_floor(self):
        src = self.SOURCE.read_text()
        assert "low_read_floor=" in src, (
            "the banner is back on the hard-coded floor while the Organisms "
            "tab and the exported report read the operator's config value"
        )
