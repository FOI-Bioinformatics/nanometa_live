"""Verify the architecture of the images, not the architecture we asked for.

`--arch` is a request, not a guarantee. Measured in an apptainer 1.5.3 rig,
exporting a real nanometanf bundle with `--target-platform linux/arm64`:

  * 23 of 24 images came back **amd64** -- apptainer silently served the only
    architecture those images publish, rather than failing;
  * 1 (community.wave.seqera.io/library/porechop_pigz) failed hard with exit
    255, because it too is amd64-only.

So the manifest recorded `target_platform: linux/arm64` over 24 amd64 images,
and `verify_bundle` reported `platform_mismatch: False` on an arm64 field
machine -- every image unrunnable, every check green. Nextflow then resolved
one from the cache correctly and apptainer refused it: "the image's
architecture (amd64) could not run on the host's (arm64)".

The guard compared the *declared* target against the field machine. A
declaration is not evidence. Record what the images actually are and check
that instead.

(For a linux/amd64 target -- the normal case -- the declaration and the
artifacts agree, which is exactly why this stayed invisible.)
"""

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.bundle_manager import BundleManager


class TestObservedArchitectureIsChecked:
    def _manifest(self, declared, observed, image_count=24):
        m = {
            "version": "1.1",
            "checksums": {},
            "build_platform": {"system": "Linux", "machine": "aarch64",
                               "python": "3.12.3"},
            "containerization": {
                "engine": "singularity",
                "pull_result": {"image_count": image_count},
                "target_platform": declared,
            },
        }
        if observed is not None:
            m["containerization"]["observed_architectures"] = observed
        return m

    def test_declared_target_matching_does_not_excuse_wrong_images(self, monkeypatch):
        """The exact bundle the rig produced: declared arm64, images amd64."""
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.machine",
            lambda: "aarch64",
        )
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.system",
            lambda: "Linux",
        )
        mgr = BundleManager()
        report = {"warnings": [], "blockers": []}

        mgr._verify_build_platform(
            self._manifest(declared="linux/arm64", observed=["amd64"]), report
        )

        codes = [b.get("code") for b in report["blockers"]]
        assert "container_platform_mismatch" in codes, (
            "The bundle declares linux/arm64 and the field machine is arm64, "
            "so the declaration check passes -- but every image in it is "
            "amd64 and cannot execute. Checking the declaration is not "
            f"checking the artifact. blockers={report['blockers']}"
        )

    def test_observed_matching_the_field_machine_is_fine(self, monkeypatch):
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.machine",
            lambda: "x86_64",
        )
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.system",
            lambda: "Linux",
        )
        mgr = BundleManager()
        report = {"warnings": [], "blockers": []}

        mgr._verify_build_platform(
            self._manifest(declared="linux/amd64", observed=["amd64"]), report
        )

        assert not [
            b for b in report["blockers"]
            if b.get("code") == "container_platform_mismatch"
        ], f"a correct amd64 bundle was blocked on x86_64: {report['blockers']}"

    def test_mixed_architectures_are_reported(self, monkeypatch):
        """A partly-runnable bundle starts and dies mid-pipeline."""
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.machine",
            lambda: "x86_64",
        )
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.system",
            lambda: "Linux",
        )
        mgr = BundleManager()
        report = {"warnings": [], "blockers": []}

        mgr._verify_build_platform(
            self._manifest(declared="linux/amd64", observed=["amd64", "arm64"]),
            report,
        )

        codes = [b.get("code") for b in report["blockers"]]
        assert "container_platform_mismatch" in codes, (
            "A bundle containing both amd64 and arm64 images was accepted. "
            "The run starts and fails at whichever process draws the wrong "
            f"one. blockers={report['blockers']}"
        )

    def test_older_bundle_without_observed_data_falls_back(self, monkeypatch):
        """Bundles predating this check must still import, using the declaration."""
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.machine",
            lambda: "x86_64",
        )
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.system",
            lambda: "Linux",
        )
        mgr = BundleManager()
        report = {"warnings": [], "blockers": []}

        mgr._verify_build_platform(
            self._manifest(declared="linux/amd64", observed=None), report
        )

        assert not [
            b for b in report["blockers"]
            if b.get("code") == "container_platform_mismatch"
        ], "an older bundle with a matching declaration was refused"
