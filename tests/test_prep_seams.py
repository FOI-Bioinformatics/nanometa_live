"""Tests for the two Run Preparation seams.

Seam 1 -- DB prerequisite hint: Run Preparation's first stage (verify DB) is
critical and aborts the whole run if the species database is missing. The hint
on the primary path is driven by the same readiness-state Store as the
checklist, so it appears exactly when the "Kraken2 Database" check fails.

Seam 2 -- result banner has three distinct states (clean success vs completed
with warnings vs failed) so a green "complete" can no longer mask missing
genomes / BLAST DBs.
"""

import pytest
from dash import Dash

from dash_test_utils import get_callback_fn
from nanometa_live.app.tabs.preparation_tab import (
    _build_prep_result,
    register_preparation_callbacks,
)
from nanometa_live.core.workflow.mobile_lab_preparer import PreparationResult

pytestmark = pytest.mark.callback


def _text(component):
    """Flatten a Dash component (or string) tree to its concatenated text."""
    out = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, (list, tuple)):
            for c in node:
                walk(c)
        else:
            children = getattr(node, "children", None)
            if children is not None:
                walk(children)

    walk(component)
    return " ".join(out)


class TestResultBanner:
    def test_clean_success_is_green(self):
        r = PreparationResult(
            success=True,
            stages_completed=["verify_db", "build_index"],
            genomes_downloaded=3, blast_dbs_built=3,
        )
        alert = _build_prep_result(r)
        assert alert.color == "success"
        assert "Preparation complete." in _text(alert)

    def test_success_with_warnings_is_amber(self):
        r = PreparationResult(
            success=True,
            stages_completed=["verify_db"],
            warnings=["No genome for taxid 1280"],
        )
        alert = _build_prep_result(r)
        assert alert.color == "warning"
        assert "completed with warnings" in _text(alert)
        assert "No genome for taxid 1280" in _text(alert)

    def test_success_with_failed_stage_is_amber_with_human_label(self):
        r = PreparationResult(
            success=True,
            stages_completed=["verify_db"],
            stages_failed=["download_genomes"],
        )
        alert = _build_prep_result(r)
        assert alert.color == "warning"
        assert "Did not finish" in _text(alert)
        # Human stage label, not the raw enum value.
        assert "Downloading reference genomes" in _text(alert)

    def test_failure_is_red(self):
        r = PreparationResult(success=False, errors=["Invalid Kraken2 database"])
        alert = _build_prep_result(r)
        assert alert.color == "danger"
        assert "Preparation failed." in _text(alert)
        assert "Invalid Kraken2 database" in _text(alert)


class TestDbPrerequisiteHint:
    @pytest.fixture
    def render_fn(self):
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_preparation_callbacks(app)
        return get_callback_fn(app, "prep-db-prerequisite.children")

    def _state(self, db_passed):
        return {"checks": [{"name": "Kraken2 Database", "passed": db_passed,
                            "severity": "critical", "message": ""}]}

    def test_hint_shown_when_db_check_fails(self, render_fn):
        out = render_fn(self._state(False))
        assert out is not None
        assert "Species database required first" in _text(out)

    def test_no_hint_when_db_check_passes(self, render_fn):
        assert render_fn(self._state(True)) is None

    def test_no_hint_before_first_check(self, render_fn):
        # No config / pre-first-check: empty Store must not raise a false alarm.
        assert render_fn({"checks": []}) is None
        assert render_fn(None) is None


class TestRestrictedInternetGuards:
    """#1 pre-warm default/visibility and #2 offline genome-download guards."""

    @pytest.fixture
    def app(self):
        app = Dash(__name__, suppress_callback_exceptions=True)
        register_preparation_callbacks(app)
        return app

    def test_prewarm_defaults_off(self):
        # The checkbox must default unchecked so the default export does not
        # attempt a ~5 GB download on restricted internet.
        from nanometa_live.app.layouts.preparation_layout import build_export_bundle_card

        def find(node, target_id):
            if getattr(node, "id", None) == target_id:
                return node
            ch = getattr(node, "children", None)
            if ch is None:
                return None
            for c in (ch if isinstance(ch, (list, tuple)) else [ch]):
                found = find(c, target_id)
                if found is not None:
                    return found
            return None

        cb = find(build_export_bundle_card(), "bundle-export-prewarm")
        assert cb is not None and cb.value is False

    def test_prewarm_hidden_for_non_conda(self, app):
        fn = get_callback_fn(app, "prewarm-wrapper.style")
        assert fn("conda") == {}
        assert fn("docker") == {"display": "none"}
        assert fn("singularity") == {"display": "none"}

    def test_offline_notice_only_when_offline(self, app):
        fn = get_callback_fn(app, "prep-offline-notice.children")
        assert fn({"offline_mode": True}) is not None
        assert fn({"offline_mode": False}) is None
        assert fn({}) is None

    def test_download_stage_offline_skips_ncbi(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from nanometa_live.core.workflow.mobile_lab_preparer import (
            MobileLabPreparer, PreparationResult,
        )

        preparer = MobileLabPreparer(
            config={"offline_mode": True}, nanometa_home=str(tmp_path),
        )
        preparer._get_watchlist_entries = lambda: [
            {"taxid": 1, "name": "Present sp."},
            {"taxid": 2, "name": "Missing sp."},
        ]
        mgr = MagicMock()
        mgr.has_genome.side_effect = lambda t: t == 1
        result = PreparationResult(success=True)
        with patch(
            "nanometa_live.core.utils.genome_manager.get_genome_manager",
            return_value=mgr,
        ) as gm:
            preparer._run_download_genomes(3, result, skip_existing=True)

        # Constructed offline, and no network download attempted.
        assert gm.call_args.kwargs.get("offline_mode") is True
        mgr.download_genome.assert_not_called()
        # The missing bundled genome is reported as a warning.
        assert any("Missing sp." in w for w in result.warnings)
