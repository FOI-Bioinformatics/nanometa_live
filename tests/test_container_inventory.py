"""Tests for the container inventory helper.

Closes part of W7-A from
``docs/plan-2026-04-28-throughput-fixes.md``: the parser used by
both the W6 audit script and the W7 BundleManager docker/singularity
modes lives in ``core/workflow/container_inventory`` and must
correctly enumerate modules + their tri-source artefacts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanometa_live.core.workflow.container_inventory import (
    ContainerInventoryEntry,
    inventory_pipeline,
    unique_container_refs,
)


# -- Synthetic-fixture tests (no live nanometanf checkout needed) -----------


class TestInventoryParserOnFixtures:
    """Inventory parser must correctly extract Singularity URL,
    Docker ref, and conda spec from a small synthetic modules tree."""

    def _build_module_dir(
        self,
        modules_dir: Path,
        scope: str,
        tool_name: str,
        main_nf_body: str,
        env_yml_body: str | None = None,
    ) -> Path:
        target = modules_dir / scope / tool_name
        target.mkdir(parents=True, exist_ok=True)
        (target / "main.nf").write_text(main_nf_body)
        if env_yml_body is not None:
            (target / "environment.yml").write_text(env_yml_body)
        return target

    def test_nf_core_module_with_full_tri_source(self, tmp_path):
        """A typical nf-core module declares both Singularity and Docker
        plus a bioconda-prefixed env spec; all three must round-trip."""
        modules_dir = tmp_path / "modules"
        self._build_module_dir(
            modules_dir,
            "nf-core",
            "chopper",
            main_nf_body=(
                'process CHOPPER {\n'
                '    container "${ workflow.containerEngine == \'singularity\' '
                "? 'https://depot.galaxyproject.org/singularity/chopper:0.12.0--hdcf5f25_0' "
                ": 'biocontainers/chopper:0.12.0--hdcf5f25_0' }\"\n"
                '}\n'
            ),
            env_yml_body=(
                "channels:\n"
                "  - conda-forge\n"
                "  - bioconda\n"
                "dependencies:\n"
                "  - bioconda::chopper=0.12.0\n"
            ),
        )

        entries = inventory_pipeline(tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e.module_name == "chopper"
        assert e.singularity_url == \
            "https://depot.galaxyproject.org/singularity/chopper:0.12.0--hdcf5f25_0"
        assert e.docker_ref == "biocontainers/chopper:0.12.0--hdcf5f25_0"
        assert e.conda_spec == "chopper=0.12.0"
        assert e.has_container is True

    def test_local_module_without_container(self, tmp_path):
        """A pure-bash local module exposes neither container nor conda;
        ``has_container`` reports False."""
        modules_dir = tmp_path / "modules"
        self._build_module_dir(
            modules_dir,
            "local",
            "do_thing",
            main_nf_body='process DO_THING {\n    """echo hi"""\n}\n',
        )

        entries = inventory_pipeline(tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e.singularity_url is None
        assert e.docker_ref is None
        assert e.conda_spec is None
        assert e.has_container is False

    def test_wave_only_module_no_singularity_url(self, tmp_path):
        """Modules using community.wave.seqera.io ship a Docker
        reference but no depot.galaxyproject.org Singularity URL.
        Apptainer can pull these directly from the OCI registry, so
        the entry is still ``has_container=True``."""
        modules_dir = tmp_path / "modules"
        self._build_module_dir(
            modules_dir,
            "nf-core",
            "fastp",
            main_nf_body=(
                'process FASTP {\n'
                '    container "community.wave.seqera.io/library/fastp:1.1.0--abc123"\n'
                '}\n'
            ),
            env_yml_body=(
                "dependencies:\n  - bioconda::fastp=1.1.0\n"
            ),
        )

        entries = inventory_pipeline(tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e.singularity_url is None
        assert e.docker_ref == "community.wave.seqera.io/library/fastp:1.1.0--abc123"
        assert e.has_container is True

    def test_flat_local_module_file(self, tmp_path):
        """Flat ``modules/local/foo.nf`` files (no own directory)
        should still surface in the inventory."""
        modules_dir = tmp_path / "modules"
        local = modules_dir / "local"
        local.mkdir(parents=True)
        (local / "snapshot.nf").write_text(
            'process SNAPSHOT {\n    """date > snapshot.txt"""\n}\n'
        )

        entries = inventory_pipeline(tmp_path)
        names = [e.module_name for e in entries]
        assert "snapshot" in names

    def test_missing_modules_dir_returns_empty(self, tmp_path):
        """Directories without a ``modules/`` subtree get an empty list."""
        assert inventory_pipeline(tmp_path) == []


# -- unique_container_refs --------------------------------------------------


class TestUniqueContainerRefs:
    def _entries(self):
        return [
            ContainerInventoryEntry(
                module_name="chopper",
                main_nf_path=Path("dummy"),
                singularity_url="https://depot.galaxyproject.org/singularity/chopper:0.12.0--hdcf5f25_0",
                docker_ref="biocontainers/chopper:0.12.0--hdcf5f25_0",
                conda_spec="chopper=0.12.0",
            ),
            ContainerInventoryEntry(
                module_name="fastp",
                main_nf_path=Path("dummy"),
                singularity_url=None,
                docker_ref="community.wave.seqera.io/library/fastp:1.1.0--abc",
                conda_spec="fastp=1.1.0",
            ),
            ContainerInventoryEntry(
                # Two modules sharing one image must dedupe.
                module_name="chopper2",
                main_nf_path=Path("dummy"),
                singularity_url="https://depot.galaxyproject.org/singularity/chopper:0.12.0--hdcf5f25_0",
                docker_ref="biocontainers/chopper:0.12.0--hdcf5f25_0",
                conda_spec="chopper=0.12.0",
            ),
        ]

    def test_docker_dedupes_shared_image(self):
        refs = unique_container_refs(self._entries(), "docker")
        assert refs == [
            "biocontainers/chopper:0.12.0--hdcf5f25_0",
            "community.wave.seqera.io/library/fastp:1.1.0--abc",
        ]

    def test_singularity_skips_entries_without_url(self):
        refs = unique_container_refs(self._entries(), "singularity")
        assert refs == [
            "https://depot.galaxyproject.org/singularity/chopper:0.12.0--hdcf5f25_0",
        ]

    def test_invalid_engine_raises(self):
        with pytest.raises(ValueError, match="unsupported engine"):
            unique_container_refs(self._entries(), "podman")


# -- Smoke test against the live nanometanf checkout (skipped if absent) ---


@pytest.mark.skipif(
    not Path("/Users/andreassjodin/Code/nanometanf/modules").is_dir(),
    reason="nanometanf checkout not present at expected path",
)
def test_inventory_against_real_pipeline():
    """Sanity-check the parser on the real nanometanf checkout. The
    audit (W6-A) reported 40 modules with 26 unique Docker refs and
    13 unique Singularity URLs; this acts as a regression sentinel."""
    entries = inventory_pipeline(Path("/Users/andreassjodin/Code/nanometanf"))
    assert len(entries) >= 30, (
        f"expected at least 30 modules in the live checkout, got {len(entries)}"
    )
    docker_refs = unique_container_refs(entries, "docker")
    sing_refs = unique_container_refs(entries, "singularity")
    # Allow some drift but flag a major change in either count.
    assert 15 <= len(docker_refs) <= 50
    assert 5 <= len(sing_refs) <= 30
