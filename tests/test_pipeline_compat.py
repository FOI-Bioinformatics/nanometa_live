"""The GUI refuses a nanometanf checkout below its parameter floor.

0.18.0 sends parameters that nanometanf < 1.10.0 does not declare; nf-schema
then fails the run with a message naming a parameter, not a version. The
checkout a remote source runs is ~/.nextflow/assets/..., which is only as new
as the last pull, so the check reads the version from that checkout.
"""

from pathlib import Path

import pytest

from nanometa_live.core.workflow import pipeline_compat as pc

pytestmark = pytest.mark.unit

NANOMETANF_CONFIG = """
params {
    version                      = false
    custom_config_version        = 'master'
}

manifest {
    name            = 'nanometanf'
    contributors    = [
        [name: 'A. Person', affiliation: 'FOI', contribution: ['author']],
    ]
    nextflowVersion = '>=26.04.0'
    version         = '1.10.1dev'
}
"""


class TestParseManifestVersion:
    def test_reads_the_manifest_block_not_params(self):
        assert pc.parse_manifest_version(NANOMETANF_CONFIG) == "1.10.1dev"

    def test_missing_manifest_is_none(self):
        assert pc.parse_manifest_version("params { version = false }") is None

    def test_double_quotes(self):
        text = 'manifest {\n  version = "1.10.0"\n}'
        assert pc.parse_manifest_version(text) == "1.10.0"


class TestVersionKey:
    def test_dev_is_before_its_release(self):
        assert pc.version_key("1.10.0dev") < pc.version_key("1.10.0")

    def test_next_dev_is_after_the_release(self):
        assert pc.version_key("1.10.1dev") > pc.version_key("1.10.0")

    def test_minor_ordering(self):
        assert pc.version_key("1.9.0") < pc.version_key("1.10.0")

    def test_leading_v_and_short_forms(self):
        assert pc.version_key("v1.10") == pc.version_key("1.10.0")


class TestResolvePipelineCheckout:
    def test_remote_resolves_to_nextflow_assets(self):
        p = pc.resolve_pipeline_checkout("remote:dev")
        assert p == Path("~/.nextflow/assets/foi-bioinformatics/nanometanf").expanduser()

    def test_local_prefix_is_stripped(self, tmp_path):
        assert pc.resolve_pipeline_checkout(f"local:{tmp_path}") == tmp_path

    def test_bare_path(self, tmp_path):
        assert pc.resolve_pipeline_checkout(str(tmp_path)) == tmp_path

    def test_url_sources_are_not_resolved(self):
        assert pc.resolve_pipeline_checkout("https://github.com/x/y") is None

    def test_empty_is_none(self):
        assert pc.resolve_pipeline_checkout("") is None


def _checkout(tmp_path, version):
    (tmp_path / "main.nf").write_text("workflow { }\n")
    (tmp_path / "nextflow.config").write_text(
        f"manifest {{\n    name = 'nanometanf'\n    version = '{version}'\n}}\n"
    )
    return tmp_path


class TestCheckPipelineCompatibility:
    def test_ok_at_or_above_floor(self, tmp_path):
        v = pc.check_pipeline_compatibility(str(_checkout(tmp_path, "1.10.0")))
        assert v.status == "ok"
        assert v.found_version == "1.10.0"
        assert "1.10.0" in v.message

    def test_too_old_names_both_versions_and_the_fix(self, tmp_path):
        v = pc.check_pipeline_compatibility(str(_checkout(tmp_path, "1.4.1dev")))
        assert v.status == "too_old"
        assert "1.4.1dev" in v.message
        assert pc.NANOMETANF_MIN_VERSION in v.message
        assert str(tmp_path) in v.message

    def test_too_old_remote_names_the_pull_command(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pc, "NEXTFLOW_ASSETS_CHECKOUT", _checkout(tmp_path, "1.4.1dev"))
        v = pc.check_pipeline_compatibility("remote:dev")
        assert v.status == "too_old"
        assert "nextflow pull foi-bioinformatics/nanometanf -r dev" in v.message

    def test_unknown_when_no_config(self, tmp_path):
        v = pc.check_pipeline_compatibility(str(tmp_path))
        assert v.status == "unknown"
        assert v.found_version is None
        assert pc.NANOMETANF_MIN_VERSION in v.message

    def test_unknown_when_manifest_has_no_version(self, tmp_path):
        (tmp_path / "nextflow.config").write_text("params { x = 1 }\n")
        v = pc.check_pipeline_compatibility(str(tmp_path))
        assert v.status == "unknown"

    def test_custom_floor(self, tmp_path):
        v = pc.check_pipeline_compatibility(str(_checkout(tmp_path, "1.10.0")), floor="1.11.0")
        assert v.status == "too_old"
