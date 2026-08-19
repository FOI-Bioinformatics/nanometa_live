"""Every app-layer consumer must resolve the results dir through the resolver.

``results_output_directory`` is a COMPUTED key, written into the config only
when a run starts. A config that has not been through Start -- a fresh boot
pointed at a custom analysis folder via ``results_dir_override``, the normal
post-run review workflow -- carries only the override. Any callback reading
``config.get("results_output_directory") or config.get("main_dir")`` raw
dead-ends on such a config and renders its empty state over real data.

This bit three times before the sweep: the Validation tab (fixed ae63b3a),
the report modal lookups, and -- found during the 2026-08-19 bug-report
reproduction -- the whole Dashboard, which showed STANDBY over a completed
run's results after an app restart because the verdict banner, alert panel,
QC, classification, organisms and sample callbacks all resolved raw.
``resolve_outdir_for_fingerprint`` is the single fallback chain; this test
keeps new callbacks from reintroducing the raw idiom.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

APP_DIR = Path(__file__).resolve().parents[1] / "nanometa_live" / "app"

# Files allowed to read the key directly:
# - outdir_resolution.py IS the resolver.
# - start_stop.py reads it as the documented last-resort fallback AFTER
#   resolve_run_outdir (which already honours the override).
# - callback_helpers.py's get_pipeline_output_dir walks the SAME chain
#   per-candidate (its contract is "an existing dir or None", so a stale
#   computed dir must not shadow an existing fallback); it includes the
#   override and is itself covered by TestPipelineOutputDir.
ALLOWED = {"outdir_resolution.py", "start_stop.py", "callback_helpers.py"}


def test_no_raw_results_dir_reads_in_the_app_layer():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.name in ALLOWED:
            continue
        text = path.read_text()
        if 'get("results_output_directory"' in text:
            offenders.append(str(path.relative_to(APP_DIR)))
    assert not offenders, (
        "raw results-dir resolution reintroduced (dead-ends on a config "
        "that has not been through Start; use "
        f"resolve_outdir_for_fingerprint): {sorted(offenders)}"
    )


def test_resolver_falls_back_to_the_override():
    from nanometa_live.app.utils.outdir_resolution import (
        resolve_outdir_for_fingerprint,
    )

    assert resolve_outdir_for_fingerprint(
        {"results_dir_override": "/data/run1"}) == "/data/run1"
    assert resolve_outdir_for_fingerprint(
        {"results_output_directory": "/computed",
         "results_dir_override": "/data/run1"}) == "/computed"
    assert resolve_outdir_for_fingerprint(None) == ""
