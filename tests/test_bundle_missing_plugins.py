"""A bundle that ships no Nextflow plugins must say so.

nanometanf declares ``plugins { id 'nf-schema@2.6.1' }``, so every run resolves
a plugin before it does anything else. Offline that can only come from the
bundle: ``_build_nextflow_env`` sets ``NXF_PLUGINS_PATH`` from
``nxf_plugins_dir``, and it is ``NXF_PLUGINS_PATH`` that suppresses the
registry probe.

``_bundle_nextflow_plugins`` sources them from ``Path.home()/".nextflow"/
"plugins"``. A build machine that has never *run* Nextflow -- a CI runner, a
container, a fresh laptop that only ever exported -- has no such directory, so
nothing is bundled at all.

The existing ``plugins_empty`` warning cannot catch that. It lives inside

    if npd == f"./{_BUNDLED_NXF_PLUGINS_DIRNAME}":

and that config key is only written when plugins *were* bundled. Plugins
bundled but empty warns; nothing bundled is silent. The silent case is the one
that actually happens.

Observed end to end in an air-gapped container rig: export, transfer, verify
and import all reported success, and the imported config had
``nxf_plugins_dir: None`` with not one warning -- a bundle that cannot run a
single pipeline process on the field machine it was built for.
"""

import pathlib

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.bundle_manager import BundleManager


class TestMissingPluginsIsReported:
    def test_import_warns_when_no_plugins_were_bundled(self, tmp_path, monkeypatch):
        """The end-to-end shape, reduced: a bundle with no nextflow_plugins/."""
        pipeline = tmp_path / "pipeline_source"
        pipeline.mkdir()
        (pipeline / "main.nf").write_text("// stub\n")

        home = tmp_path / "field_home"
        home.mkdir()

        mgr = BundleManager()
        result = {"warnings": [], "success": True}

        mgr._check_bundled_plugins(home, result)

        assert result.get("plugins_empty") is True, (
            "A bundle with no nextflow_plugins/ directory produced no "
            "plugins_empty flag. Offline, Nextflow will fall back to the "
            "online plugin registry and every run fails before the first "
            f"process. result={result}"
        )
        joined = " ".join(result["warnings"]).lower()
        assert "plugin" in joined, (
            f"no plugin warning surfaced to the operator: {result['warnings']}"
        )

    def test_no_warning_when_plugins_are_present(self, tmp_path):
        """Must not cry wolf on a correctly built bundle."""
        home = tmp_path / "field_home"
        (home / "nextflow_plugins" / "nf-schema-2.6.1").mkdir(parents=True)

        mgr = BundleManager()
        result = {"warnings": [], "success": True}

        mgr._check_bundled_plugins(home, result)

        assert not result.get("plugins_empty"), (
            f"warned about plugins on a bundle that has them: {result}"
        )

    def test_warns_when_plugins_dir_exists_but_holds_nothing_usable(self, tmp_path):
        """The case the original guard covered, kept working."""
        home = tmp_path / "field_home"
        (home / "nextflow_plugins" / "not-a-plugin").mkdir(parents=True)

        mgr = BundleManager()
        result = {"warnings": [], "success": True}

        mgr._check_bundled_plugins(home, result)

        assert result.get("plugins_empty") is True, (
            f"a plugins dir with no recognised plugin folders did not warn: {result}"
        )
