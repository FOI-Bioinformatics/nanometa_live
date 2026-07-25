"""Guards for the scaling harness in ``scripts/perf/``.

The harness itself is not run by the default suite: it monkeypatches
``os.stat`` process-globally and takes timings, neither of which survives
``pytest-xdist``. These tests exist so the harness cannot silently rot
against loader refactors. Enable with::

    NANOMETA_PERF=1 pytest tests/test_perf_harness.py -n 0

The fidelity test is the important one. ``simulate_poll`` deliberately does
not drive the real Dash callbacks, so something has to pin its call pattern
to what the app actually does, or the committed baseline would slowly stop
describing production.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytestmark = pytest.mark.skipif(
    not os.environ.get("NANOMETA_PERF"),
    reason="perf harness; set NANOMETA_PERF=1 and run with -n 0",
)


@pytest.fixture(scope="module")
def perf_base(tmp_path_factory):
    return tmp_path_factory.mktemp("perf_fixtures")


class TestFixtures:
    @pytest.mark.parametrize("layout", ["batch", "realtime_incremental"])
    def test_builds_and_validates(self, perf_base, layout):
        """build_fixture asserts the tree dispatches down the intended path."""
        from scripts.perf import fixtures as fx

        spec = fx.FixtureSpec(n_samples=2, layout=layout, taxa_per_report=60,
                              batches_per_sample=3)
        root = fx.build_fixture(spec, perf_base)
        assert (root / "kraken2").is_dir()

    def test_loaders_see_the_generated_data(self, perf_base):
        """A tree the loaders read as empty would make every number a lie."""
        from nanometa_live.core.utils.classification_loaders import load_kraken_data
        from scripts.perf import fixtures as fx
        from scripts.perf.instrument import reset_caches

        spec = fx.FixtureSpec(n_samples=2, layout="batch", taxa_per_report=60)
        root = fx.build_fixture(spec, perf_base)
        reset_caches()
        df = load_kraken_data(str(root), "barcode01")
        assert not df.empty
        assert (df["rank"] == "S").any()

    def test_is_idempotent(self, perf_base):
        from scripts.perf import fixtures as fx

        spec = fx.FixtureSpec(n_samples=2, layout="batch", taxa_per_report=60)
        first = fx.build_fixture(spec, perf_base)
        stamp = (first / "kraken2" / "barcode01.kraken2.report.txt").stat().st_mtime
        second = fx.build_fixture(spec, perf_base)
        assert first == second
        assert (second / "kraken2" / "barcode01.kraken2.report.txt").stat().st_mtime == stamp


class TestInstrumentation:
    def test_counts_are_deterministic(self, perf_base):
        """Two identical measured runs must produce identical counts.

        If they do not, something in the loader stack is time- or
        ordering-dependent and every later comparison in the baseline is
        meaningless. This is the harness's own smoke alarm.
        """
        from scripts.perf import fixtures as fx
        from scripts.perf.instrument import count_syscalls, reset_caches
        from scripts.perf.poll import simulate_poll

        spec = fx.FixtureSpec(n_samples=2, layout="batch", taxa_per_report=60)
        root = fx.build_fixture(spec, perf_base)

        runs = []
        for _ in range(2):
            reset_caches()
            simulate_poll(str(root), build_figures=False)  # warm
            simulate_poll(str(root), build_figures=False)
            with count_syscalls() as counted:
                simulate_poll(str(root), build_figures=False)
            runs.append(counted.as_dict())

        assert runs[0] == runs[1], (
            f"non-deterministic syscall counts: {runs[0]} vs {runs[1]}"
        )

    def test_patch_is_fully_restored(self):
        """A leaked patch would corrupt every later test in the process."""
        import glob as glob_mod

        from scripts.perf.instrument import count_syscalls

        before = (os.stat, os.walk, glob_mod.glob)
        with count_syscalls():
            pass
        assert (os.stat, os.walk, glob_mod.glob) == before


class TestPollFidelity:
    def test_load_count_matches_the_documented_model(self, perf_base):
        """simulate_poll issues 3N + 2 kraken loads.

        Three per-sample sweeps (dashboard sample data, pathogen attribution,
        QC summary) plus the aggregate and selected-sample loads. If a
        refactor changes how many sweeps a poll makes, this number moves and
        the baseline must be re-recorded rather than silently reinterpreted.
        """
        from scripts.perf import fixtures as fx
        from scripts.perf.instrument import reset_caches
        from scripts.perf.poll import simulate_poll

        for n in (1, 3):
            spec = fx.FixtureSpec(n_samples=n, layout="batch", taxa_per_report=60)
            root = fx.build_fixture(spec, perf_base)
            reset_caches()
            result = simulate_poll(str(root), build_figures=False)
            assert result.samples == n
            assert result.kraken_loads == 3 * n + 2, (
                f"n={n}: poll made {result.kraken_loads} kraken loads, "
                f"expected {3 * n + 2}"
            )

    def test_real_callbacks_sweep_every_sample(self, perf_base):
        """The real dashboard callback loads data for each sample.

        This is the claim simulate_poll's per-sample loops stand in for. It
        is asserted against the production helper rather than a copy, so a
        change that stops the dashboard reading per-sample data -- which
        would also silently break sample attribution -- fails here.
        """
        from nanometa_live.app.tabs import dashboard_helpers
        from scripts.perf import fixtures as fx
        from scripts.perf.instrument import reset_caches

        spec = fx.FixtureSpec(n_samples=3, layout="batch", taxa_per_report=60)
        root = fx.build_fixture(spec, perf_base)
        reset_caches()

        seen = []
        original = dashboard_helpers.load_kraken_data

        def spy(main_dir, sample=None):
            seen.append(sample)
            return original(main_dir, sample)

        dashboard_helpers.load_kraken_data = spy
        try:
            dashboard_helpers._load_per_sample_organisms(
                str(root), ["All Samples"] + spec.sample_names
            )
        finally:
            dashboard_helpers.load_kraken_data = original

        assert sorted(s for s in seen if s) == sorted(spec.sample_names)
