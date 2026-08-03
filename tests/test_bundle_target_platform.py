"""Container images must be pulled for the field machine's architecture.

The build machine and the field machine are routinely different: a macOS
arm64 laptop building a bundle for a Linux x86_64 air-gapped field machine is
the normal case for this project.

Neither pull path pinned an architecture. ``apptainer pull`` and ``docker pull``
both default to the *host* platform, so an Apple Silicon build produced arm64
images. Those images then:

  * are md5-checksummed into the manifest like any other file, so
    ``verify_bundle`` reports the bundle intact;
  * trip ``_verify_build_platform``, which produced a *warning* rather than a
    blocker for container bundles (it only blocks when the bundle also ships
    pre-warmed conda envs, which a singularity bundle does not);
  * import cleanly, with ``nxf_singularity_cachedir`` wired up correctly;
  * and finally fail at the first pipeline process on the field machine, where
    there is no network to re-pull from.

That is the worst possible failure shape: every check passes and the defect
surfaces only where it cannot be fixed. The CLI made it worse by printing
"Docker mode: pulls + saves linux/amd64 images", which was simply untrue --
no ``--platform`` or ``--arch`` existed anywhere in the package.

These tests pin the behaviour: the target platform is an explicit choice
recorded in the manifest, not an accident of the build host.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from nanometa_live.core.workflow.bundle_manager import BundleManager


class TestSingularityPullPinsPlatform:
    def test_docker_ref_is_pulled_for_the_target_platform(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            class _Done:
                returncode = 0
                stdout = b""
                stderr = b""
            return _Done()

        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run", fake_run
        )

        mgr = BundleManager()
        mgr._pull_one_singularity_image(
            "docker://quay.io/biocontainers/chopper:0.12.0--hdcf5f25_0",
            tmp_path,
            "apptainer",
            platform="linux/amd64",
        )

        assert calls, "no pull was attempted"
        argv = calls[0]
        assert "--platform" in argv, (
            "apptainer pull was not given a platform, so it resolved the "
            f"manifest list to the build host's architecture. argv={argv}"
        )
        assert argv[argv.index("--platform") + 1] == "linux/amd64"

    def test_direct_sif_url_is_not_given_a_platform(self, tmp_path, monkeypatch):
        """A depot.galaxyproject.org URL is a file download, not an OCI pull.

        There is no manifest list to select from -- the .sif is whatever
        Galaxy built (amd64) -- and passing --platform to a direct download is
        meaningless at best and an error at worst. Pinning must apply only
        where there is actually a choice.
        """
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            class _Done:
                returncode = 0
                stdout = b""
                stderr = b""
            return _Done()

        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run", fake_run
        )

        mgr = BundleManager()
        mgr._pull_one_singularity_image(
            "https://depot.galaxyproject.org/singularity/chopper:0.12.0--hdcf5f25_0",
            tmp_path,
            "apptainer",
            platform="linux/amd64",
        )

        assert calls, "no pull was attempted"
        assert "--platform" not in calls[0], (
            "a direct .sif download was given --platform, which selects from "
            f"an OCI manifest list that does not exist here. argv={calls[0]}"
        )


class TestDockerPullPinsPlatform:
    def test_docker_pull_is_given_the_target_platform(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["docker", "save"]:
                Path(cmd[3]).write_bytes(b"fake")
            class _Done:
                returncode = 0
                stdout = b""
                stderr = b""
            return _Done()

        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.subprocess.run", fake_run
        )

        mgr = BundleManager()
        mgr._pull_one_docker_image(
            "quay.io/biocontainers/chopper:0.12.0--hdcf5f25_0",
            tmp_path,
            platform="linux/amd64",
        )

        pulls = [c for c in calls if c[:2] == ["docker", "pull"]]
        assert pulls, f"no docker pull issued; calls={calls}"
        assert "--platform" in pulls[0], (
            "docker pull inherited the build host's architecture. The CLI "
            "claims it saves linux/amd64 images; it must actually do so. "
            f"argv={pulls[0]}"
        )
        assert pulls[0][pulls[0].index("--platform") + 1] == "linux/amd64"


class TestPlatformMismatchIsABlocker:
    """A wrong-architecture image set must stop an import, not warn.

    The operator's only signal today is an advisory they can dismiss, after
    which the run dies on a machine with no network. Verified against the
    shared `_verify_extracted_bundle`, so `verify_bundle` (the dry run) and
    `import_bundle` cannot disagree.
    """

    def _manifest(self, target_platform, image_count=3):
        return {
            "version": "1.1",
            "checksums": {},
            "build_platform": {
                "system": "Darwin",
                "machine": "arm64",
                "python": "3.13.0",
            },
            "containerization": {
                "engine": "singularity",
                "pull_result": {"image_count": image_count},
                "target_platform": target_platform,
            },
        }

    def test_images_built_for_another_platform_block_the_import(self, monkeypatch):
        mgr = BundleManager()
        report = {"warnings": [], "blockers": []}

        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.system",
            lambda: "Linux",
        )
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.machine",
            lambda: "x86_64",
        )

        mgr._verify_build_platform(self._manifest("linux/arm64"), report)

        codes = [b.get("code") for b in report["blockers"]]
        assert "container_platform_mismatch" in codes, (
            "A bundle of arm64 images imported onto an x86_64 field machine "
            "produced no blocker. Every image is unusable and there is no "
            f"network to re-pull. blockers={report['blockers']} "
            f"warnings={report['warnings']}"
        )

    def test_matching_platform_does_not_block(self, monkeypatch):
        """Cross-OS builds are the normal case and must stay allowed.

        macOS arm64 building linux/amd64 images for a Linux x86_64 field
        machine is correct once the pull is pinned; only the *image* platform
        has to match the field machine.
        """
        mgr = BundleManager()
        report = {"warnings": [], "blockers": []}

        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.system",
            lambda: "Linux",
        )
        monkeypatch.setattr(
            "nanometa_live.core.workflow.bundle_manager.platform.machine",
            lambda: "x86_64",
        )

        mgr._verify_build_platform(self._manifest("linux/amd64"), report)

        codes = [b.get("code") for b in report["blockers"]]
        assert "container_platform_mismatch" not in codes, (
            "A correctly pinned linux/amd64 bundle was blocked on an x86_64 "
            f"field machine. blockers={report['blockers']}"
        )
