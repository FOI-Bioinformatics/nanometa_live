"""Round-2 click-path fixes: debounced path inputs, capped genome list.

- The config tab's path inputs fed validators that walk the filesystem
  (one runs `detect_existing_results`) on EVERY keystroke; `debounce=True`
  fires them on blur/Enter instead.
- The missing-genome list rendered one component per missing genome
  (500 at large watchlists); it is capped with an explicit "and N more"
  row — the count is stated, never hidden.
"""

import pytest
from dash.development.base_component import Component

pytestmark = pytest.mark.unit


def _walk(node):
    if isinstance(node, (list, tuple)):
        for c in node:
            yield from _walk(c)
        return
    if not isinstance(node, Component):
        return
    yield node
    yield from _walk(getattr(node, "children", None))


class TestPathInputsDebounced:
    PATH_INPUT_IDS = {
        "nanopore-dir-input", "kraken-db-input", "results-dir-input",
        "genome-cache-dir-input",
    }

    def test_every_path_input_is_debounced(self):
        from nanometa_live.app.components.config_form import (
            create_config_form,
        )
        form = create_config_form()
        found = {}
        for node in _walk(form):
            cid = getattr(node, "id", None)
            if cid in self.PATH_INPUT_IDS:
                found[cid] = getattr(node, "debounce", None)
        assert set(found) == self.PATH_INPUT_IDS, (
            f"missing inputs: {self.PATH_INPUT_IDS - set(found)}"
        )
        not_debounced = [k for k, v in found.items() if v is not True]
        assert not not_debounced, (
            f"path inputs firing per keystroke: {not_debounced}"
        )


class TestBackgroundExport:
    """Export Results runs in a background worker with staged progress and
    reports its outcome INSIDE the still-open modal (it used to run for
    minutes on the request thread and write its status into a modal that
    had already closed)."""

    def _results_tree(self, tmp_path):
        main = tmp_path / "results"
        (main / "kraken2").mkdir(parents=True)
        (main / "kraken2" / "barcode01.kraken2.report.txt").write_text(
            " 90.00\t90\t10\tR\t1\troot\n"
            " 80.00\t80\t80\tS\t666\tTestus organismus\n"
        )
        import os
        import time as _time
        for dirpath, _d, files in __import__("os").walk(main):
            for f in files:
                p = os.path.join(dirpath, f)
                back = _time.time() - 60
                os.utime(p, (back, back))
        return main

    def test_generator_reports_monotonic_stage_progress(self, tmp_path):
        from nanometa_live.core.export.report_generator import ReportGenerator
        main = self._results_tree(tmp_path)
        stages = []
        gen = ReportGenerator(str(main), {"analysis_name": "t"})
        report = gen.generate(
            str(tmp_path / "out"), include_raw=False,
            progress_cb=lambda pct, label: stages.append((pct, label)))
        assert report.exists()
        percents = [p for p, _ in stages]
        assert percents == sorted(percents)
        assert percents[0] <= 10 and percents[-1] == 100
        assert all(label for _, label in stages)

    def test_a_failing_progress_callback_never_fails_the_export(self, tmp_path):
        from nanometa_live.core.export.report_generator import ReportGenerator
        main = self._results_tree(tmp_path)

        def broken(_pct, _label):
            raise RuntimeError("ui went away")

        report = ReportGenerator(str(main), {}).generate(
            str(tmp_path / "out"), include_raw=False, progress_cb=broken)
        assert report.exists()

    def test_worker_returns_success_into_the_modal_and_a_toast(self, tmp_path):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from nanometa_live.app.tabs.dashboard_tab import (
            register_dashboard_callbacks,
        )
        main = self._results_tree(tmp_path)
        app = make_callback_app(register_dashboard_callbacks)
        fn = get_callback_fn(app, "export-status-message",
                             input_contains="export-generate-btn")
        progress_calls = []
        status, toast = fn(
            lambda payload: progress_calls.append(payload),
            1, str(tmp_path / "out"), False,
            {"results_dir_override": str(main)})
        assert "report.html" in str(status)
        assert toast["color"] == "success"
        assert len(progress_calls) >= 3, "staged progress must be visible"

    def test_modal_stays_open_on_generate(self):
        from tests.dash_test_utils import get_callback_fn, make_callback_app
        from unittest.mock import patch as _patch
        from nanometa_live.app.tabs import dashboard_tab
        from nanometa_live.app.tabs.dashboard_tab import (
            register_dashboard_callbacks,
        )
        app = make_callback_app(register_dashboard_callbacks)
        fn = get_callback_fn(app, "report-export-modal",
                             input_contains="dashboard-export-btn")
        with _patch.object(dashboard_tab, "ctx") as mock_ctx:
            mock_ctx.triggered_id = "export-generate-btn"
            assert fn(None, None, 1, True) is True, (
                "the modal must stay open so the progress bar and the "
                "terminal status are visible"
            )


class TestMissingGenomeListCap:
    def _entries(self, n):
        return [
            {"taxid": 90000 + i, "name": f"Missingus organismus{i}",
             "threat_level": "high"}
            for i in range(n)
        ]

    def test_large_list_is_capped_with_a_stated_count(self):
        from nanometa_live.app.tabs.preparation_tab import (
            MISSING_GENOME_LIST_CAP, _missing_genome_items,
        )
        items = _missing_genome_items(self._entries(100))
        assert len(items) == MISSING_GENOME_LIST_CAP + 1
        blob = str(items[-1])
        assert f"{100 - MISSING_GENOME_LIST_CAP} more" in blob, (
            "the overflow row must state how many are hidden"
        )

    def test_small_list_is_untouched(self):
        from nanometa_live.app.tabs.preparation_tab import (
            _missing_genome_items,
        )
        items = _missing_genome_items(self._entries(3))
        assert len(items) == 3