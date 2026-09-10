# SWOT Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the seven moves the 2026-09-04 SWOT analysis ranked first: a
launch-time pipeline compatibility check, an amd64 singularity execution job
in CI, working distribution channels with a compatibility matrix, an answer
to the one open issue, decision records and a contributor guide for a second
maintainer, and an honest network posture.

**Architecture:** Each move is one task with its own tests and commit, in the
order of return against effort. Code tasks follow the repository's existing
split: a pure module under `core/` or `app/utils/` that is unit-tested
without a running app, thin wiring in the caller, and a "fence" test that
greps the repository so the property cannot regress silently. Two tasks are
documentation with a fence test; two produce text the owner posts to an
external service (GitHub, bioconda) after review.

**Tech Stack:** Python 3.11/3.12, pytest (run through the `nf-core` conda
env, which has pytest-xdist and pytest-cov), GitHub Actions, Apptainer
1.3.6, Nextflow 26.04.x, `gh` CLI.

**Spec:** The SWOT analysis published on 2026-09-04
(https://claude.ai/code/artifact/5eafe11f-3200-4436-b2ad-87391dfc1269). Its
"Moves that follow" section is the requirement list; the evidence for each
weakness is restated at the head of the task that closes it.

## Global Constraints

- Python floor is 3.11 (`pyproject.toml` `requires-python = ">=3.11"`); CI
  runs 3.11 and 3.12.
- The Nextflow floor is 26.04.0 (`_NEXTFLOW_MIN_VERSION` in
  `nanometa_live/core/workflow/bundle_manager.py`). The nanometanf floor this
  plan introduces is 1.10.0 (the 0.18.0 changelog: "Requires nanometanf
  v1.10.0").
- Use modest scientific language in documentation, docstrings and commit
  messages. No claims of "robust", "comprehensive" or similar.
- No Unicode in Nextflow files (`.nf`, `.config`), including the stand-in
  pipeline written by the CI job in Task 2.
- Run tests as `conda run -n nf-core python -m pytest <path> -q`. The
  `nanometa` env lacks pytest-xdist, so if you use it add `-o addopts=""`.
- Coverage floor is 76 (`pytest.ini` `fail_under = 76`); new modules must
  carry tests so the floor does not move down.
- Commit messages follow `type(scope): summary` as in the log
  (`feat(assembly): ...`, `docs(audit): ...`) and end with the two trailers
  below, verbatim:

  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW
  ```

- Work on `dev`. Nothing here is pushed to `main`; the release that carries
  it goes through the usual dev-to-main pull request.
- Anything posted to an external service (a GitHub issue comment, a bioconda
  pull request, a PyPI publisher registration) is prepared by the task and
  posted by the owner. The task ends with the text and the command ready.

---

## File map

| Path | Responsibility |
|------|----------------|
| `nanometa_live/core/workflow/pipeline_compat.py` (new) | Reads the version of the nanometanf checkout a launch would use and compares it with the floor. Pure functions, no subprocess. |
| `nanometa_live/core/workflow/readiness_checker.py` (modify) | Adds the "Pipeline Version" readiness check. |
| `nanometa_live/core/workflow/nextflow_manager.py` (modify) | `setup()` refuses a pipeline below the floor and warns when the version is unreadable. |
| `tests/test_pipeline_compat.py`, `tests/test_readiness_pipeline_version.py`, `tests/test_nextflow_manager.py` | Task 1 tests. |
| `.github/workflows/bundle-deploy.yml` (modify) | Two new jobs: export a singularity bundle on amd64, import it on a second amd64 runner and execute the bundled image offline. |
| `.github/workflows/publish.yml` (new) | Build sdist and wheel on release, publish to PyPI through trusted publishing. |
| `pyproject.toml` (modify) | `build` added to the dev extra so the wheel test stops skipping. |
| `README.md`, `docs/user-guide.md` (modify) | Compatibility matrix; corrected prerequisites. |
| `tests/test_compatibility_matrix.py` (new) | Fence: the README matrix names the current GUI minor and the nanometanf floor. |
| `docs/distribution/bioconda-0.18.0-meta.yaml` (new) | The recipe text for the bioconda pull request. |
| `docs/distribution/issue-69-reply.md` (new) | The reply text for GitHub issue 69. |
| `docs/decisions/README.md` and `docs/decisions/0001-...0010-*.md` (new) | Decision records distilled from CLAUDE.md. |
| `CONTRIBUTING.md` (new) | Contributor and second-maintainer guide. |
| `tests/test_decision_records.py` (new) | Fence: every record has the four headings and is indexed. |
| `nanometa_live/app/utils/network_posture.py` (new) | `exposure_warning(host)`. |
| `nanometa_live/app/__main__.py`, `nanometa_live/nanometa_live.py` (modify) | Print the warning when binding a non-loopback host; help text. |
| `tests/test_network_posture.py` (new) | Task 6 tests. |

---

### Task 1: Launch-time nanometanf compatibility check

**Why.** 0.18.0 sends assembly parameters that nanometanf below v1.10.0 does
not declare; nf-schema rejects unknown parameters, so the operator sees an
error naming a parameter, not a version. Nothing in the GUI compares
versions. A `remote:dev` run uses `~/.nextflow/assets/foi-bioinformatics/nanometanf`
and the run command carries no `-latest`, so that checkout is whatever was
last pulled (on the development machine today it is 1.4.1dev).

**Files:**
- Create: `nanometa_live/core/workflow/pipeline_compat.py`
- Modify: `nanometa_live/core/workflow/readiness_checker.py` (add
  `_check_pipeline_version`; call it in `check_readiness` after
  `_check_pipeline_cached`, around line 242)
- Modify: `nanometa_live/core/workflow/nextflow_manager.py:473-505` (`setup`)
  and the import block at line 23
- Test: `tests/test_pipeline_compat.py`, `tests/test_readiness_pipeline_version.py`,
  `tests/test_nextflow_manager.py`

**Interfaces:**
- Produces: `NANOMETANF_MIN_VERSION: str = "1.10.0"`,
  `parse_manifest_version(text: str) -> Optional[str]`,
  `version_key(version: str) -> tuple[int, int, int, int]`,
  `resolve_pipeline_checkout(pipeline_source: str) -> Optional[Path]`,
  `check_pipeline_compatibility(pipeline_source: str, floor: str = NANOMETANF_MIN_VERSION) -> CompatVerdict`
  where `CompatVerdict` is a frozen dataclass with `status` (`"ok"`,
  `"too_old"` or `"unknown"`), `found_version`, `checkout`, `message`.
- Task 3 reads `NANOMETANF_MIN_VERSION` in its fence test.

- [ ] **Step 1: Write the failing tests for the pure functions**

Create `tests/test_pipeline_compat.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n nf-core python -m pytest tests/test_pipeline_compat.py -q`
Expected: FAIL with `ImportError: cannot import name 'pipeline_compat'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Write the module**

Create `nanometa_live/core/workflow/pipeline_compat.py`:

```python
"""Compatibility floor between this GUI and the nanometanf it launches.

The GUI sends parameters that only a sufficiently recent nanometanf declares
(0.18.0 added the assembly parameters that v1.10.0 introduced). nf-schema
rejects unknown parameters, so an older checkout fails at Start with a
message naming a parameter rather than a version. This module reads the
version of the checkout the launch would use and compares it with the floor.

A ``remote:<branch>`` source runs the checkout under
``~/.nextflow/assets/foi-bioinformatics/nanometanf``; the run command carries
no ``-latest``, so that checkout is only as new as the last ``nextflow pull``.
Reading it is therefore reading what will run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

#: The oldest nanometanf whose schema declares every parameter this GUI sends.
NANOMETANF_MIN_VERSION = "1.10.0"

#: Where Nextflow keeps the checkout for the default remote repository
#: (NextflowManager.DEFAULT_REMOTE_REPO). Module-level so tests can point it
#: at a temporary directory.
NEXTFLOW_ASSETS_CHECKOUT = Path("~/.nextflow/assets/foi-bioinformatics/nanometanf")

_MANIFEST_VERSION_RE = re.compile(
    r"manifest\s*\{[^}]*?\bversion\s*=\s*['\"]([^'\"]+)['\"]", re.S
)


def parse_manifest_version(config_text: str) -> Optional[str]:
    """Return ``manifest.version`` from ``nextflow.config`` text, or None.

    The search is anchored on the ``manifest {`` block so the
    ``params.version = false`` that nf-core pipelines carry is not matched.
    """
    match = _MANIFEST_VERSION_RE.search(config_text)
    return match.group(1).strip() if match else None


def version_key(version: str) -> Tuple[int, int, int, int]:
    """Sortable key for a pipeline version string.

    A ``dev`` suffix marks a pre-release of that number, so
    ``1.10.0dev < 1.10.0 < 1.10.1dev``. Missing components read as zero.
    """
    text = version.strip().lstrip("vV")
    is_dev = text.endswith("dev")
    if is_dev:
        text = text[: -len("dev")].rstrip(".-")
    parts = []
    for piece in text.split("."):
        digits = re.match(r"\d+", piece)
        parts.append(int(digits.group(0)) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts[:3]
    return (major, minor, patch, 0 if is_dev else 1)


def resolve_pipeline_checkout(pipeline_source: str) -> Optional[Path]:
    """Directory a launch of ``pipeline_source`` would run from, or None.

    Mirrors ``NextflowManager._parse_pipeline_source``: ``remote:<rev>`` and
    the bare ``master`` / ``dev`` forms run from the Nextflow assets
    checkout; ``local:<path>`` and bare paths run from that path. URL forms
    are not resolved (the launcher refuses them in offline mode and
    Nextflow clones them under a name this module does not predict).
    """
    source = (pipeline_source or "").strip()
    if not source:
        return None
    if source.startswith("remote:") or source in ("master", "dev"):
        return NEXTFLOW_ASSETS_CHECKOUT.expanduser()
    if source.startswith("local:"):
        source = source.split(":", 1)[1]
    if source.startswith(("http://", "https://", "git@")):
        return None
    return Path(source).expanduser()


@dataclass(frozen=True)
class CompatVerdict:
    """Outcome of the compatibility check.

    ``status`` is ``"ok"``, ``"too_old"`` or ``"unknown"``. ``unknown`` means
    the version could not be read (no checkout yet, no ``nextflow.config``,
    or no manifest version in it); it is a warning, not a refusal, because
    a first ``remote:`` launch legitimately has no checkout until Nextflow
    pulls one.
    """

    status: str
    found_version: Optional[str]
    checkout: Optional[Path]
    message: str


def _fix_for(pipeline_source: str, checkout: Optional[Path]) -> str:
    source = (pipeline_source or "").strip()
    if source.startswith("remote:"):
        revision = source.split(":", 1)[1] or "master"
        return f"run 'nextflow pull foi-bioinformatics/nanometanf -r {revision}'"
    if source in ("master", "dev"):
        return f"run 'nextflow pull foi-bioinformatics/nanometanf -r {source}'"
    return f"update the checkout at {checkout}"


def check_pipeline_compatibility(
    pipeline_source: str,
    floor: str = NANOMETANF_MIN_VERSION,
) -> CompatVerdict:
    """Compare the version of the checkout ``pipeline_source`` runs with ``floor``."""
    checkout = resolve_pipeline_checkout(pipeline_source)
    config_path = (checkout / "nextflow.config") if checkout else None
    if config_path is None or not config_path.is_file():
        where = f" at {checkout}" if checkout else ""
        return CompatVerdict(
            "unknown", None, checkout,
            f"Could not read the pipeline version{where}; nanometanf >= {floor} "
            f"is required. If the run fails at parameter validation, update the pipeline.",
        )
    try:
        text = config_path.read_text(errors="replace")
    except OSError as exc:
        return CompatVerdict(
            "unknown", None, checkout,
            f"Could not read {config_path} ({exc}); nanometanf >= {floor} is required.",
        )
    found = parse_manifest_version(text)
    if found is None:
        return CompatVerdict(
            "unknown", None, checkout,
            f"{config_path} carries no manifest version; nanometanf >= {floor} is required.",
        )
    if version_key(found) >= version_key(floor):
        return CompatVerdict(
            "ok", found, checkout, f"nanometanf {found} at {checkout} (>= {floor})",
        )
    return CompatVerdict(
        "too_old", found, checkout,
        f"nanometanf {found} found at {checkout}, but this Nanometa Live release "
        f"requires >= {floor}: the run would reject the parameters it sends. "
        f"To fix, {_fix_for(pipeline_source, checkout)}.",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n nf-core python -m pytest tests/test_pipeline_compat.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing readiness test**

Create `tests/test_readiness_pipeline_version.py`:

```python
"""The readiness checklist names a nanometanf below the parameter floor.

Without this the checklist is green and the run fails at Start with an
nf-schema message naming a parameter (SWOT 2026-09-04, weakness 2).
"""

import pytest

from nanometa_live.core.workflow.readiness_checker import ReadinessChecker, Severity

pytestmark = pytest.mark.unit


def _checkout(tmp_path, version):
    (tmp_path / "main.nf").write_text("workflow { }\n")
    (tmp_path / "nextflow.config").write_text(
        f"manifest {{\n    name = 'nanometanf'\n    version = '{version}'\n}}\n"
    )
    return str(tmp_path)


def _find(report, name):
    matches = [c for c in report.checks if c.name == name]
    assert len(matches) == 1, [c.name for c in report.checks]
    return matches[0]


class TestPipelineVersionCheck:
    def test_below_floor_is_critical(self, tmp_path):
        result = ReadinessChecker()._check_pipeline_version(
            {"pipeline_source": _checkout(tmp_path, "1.4.1dev")}
        )
        assert result.name == "Pipeline Version"
        assert result.passed is False
        assert result.severity == Severity.CRITICAL
        assert "1.4.1dev" in result.message and "1.10.0" in result.message

    def test_at_floor_is_info_pass(self, tmp_path):
        result = ReadinessChecker()._check_pipeline_version(
            {"pipeline_source": _checkout(tmp_path, "1.10.0")}
        )
        assert result.passed is True
        assert result.severity == Severity.INFO

    def test_unreadable_is_warning(self, tmp_path):
        result = ReadinessChecker()._check_pipeline_version(
            {"pipeline_source": str(tmp_path)}
        )
        assert result.passed is False
        assert result.severity == Severity.WARNING

    # offline_mode: True keeps _check_network_connectivity from probing the
    # NCBI and GTDB endpoints during a unit test (the pattern in
    # tests/test_readiness_offline_checks.py::TestChecksAreWired).
    def test_report_carries_the_check_when_a_source_is_set(self, tmp_path):
        config = {
            "pipeline_source": _checkout(tmp_path, "1.10.0"),
            "kraken_db": "",
            "offline_mode": True,
            "pipeline_profile": "conda",
        }
        report = ReadinessChecker().check_readiness(config, nanometa_home=str(tmp_path))
        assert _find(report, "Pipeline Version").passed is True

    def test_report_omits_the_check_without_a_source(self, tmp_path):
        config = {
            "pipeline_source": "",
            "kraken_db": "",
            "offline_mode": True,
            "pipeline_profile": "conda",
        }
        report = ReadinessChecker().check_readiness(config, nanometa_home=str(tmp_path))
        assert not [c for c in report.checks if c.name == "Pipeline Version"]
```

- [ ] **Step 6: Run it to verify it fails**

Run: `conda run -n nf-core python -m pytest tests/test_readiness_pipeline_version.py -q`
Expected: FAIL with `AttributeError: 'ReadinessChecker' object has no attribute '_check_pipeline_version'`.

- [ ] **Step 7: Add the readiness check**

In `nanometa_live/core/workflow/readiness_checker.py`, after
`_check_pipeline_cached` (which ends near line 1290), add:

```python
    def _check_pipeline_version(self, config: Dict[str, Any]) -> CheckResult:
        """Compare the pipeline checkout the launch would use with the floor.

        The GUI sends parameters that only nanometanf >= NANOMETANF_MIN_VERSION
        declares; an older checkout fails at Start with an nf-schema message
        that names a parameter, not a version. A version that cannot be read
        (no checkout pulled yet) is a warning, since the first remote launch
        pulls one.
        """
        from nanometa_live.core.workflow.pipeline_compat import (
            check_pipeline_compatibility,
        )

        verdict = check_pipeline_compatibility(str(config.get("pipeline_source") or ""))
        if verdict.status == "ok":
            return CheckResult("Pipeline Version", True, Severity.INFO, verdict.message)
        if verdict.status == "too_old":
            return CheckResult("Pipeline Version", False, Severity.CRITICAL, verdict.message)
        return CheckResult("Pipeline Version", False, Severity.WARNING, verdict.message)
```

In `check_readiness`, directly after
`report.checks.append(self._check_pipeline_cached(config))` (line 242), add:

```python
        if config.get("pipeline_source"):
            report.checks.append(self._check_pipeline_version(config))
```

- [ ] **Step 8: Run the readiness tests**

Run: `conda run -n nf-core python -m pytest tests/test_readiness_pipeline_version.py tests/test_readiness_offline_checks.py -q`
Expected: all pass.

- [ ] **Step 9: Write the failing launcher tests**

Append to `tests/test_nextflow_manager.py`:

```python
class TestSetupPipelineFloor:
    """setup() refuses a checkout below NANOMETANF_MIN_VERSION before it
    builds parameters, and records a launch warning when the version cannot
    be read."""

    def _checkout(self, tmp_path, version):
        pipe = tmp_path / "pipe"
        pipe.mkdir()
        (pipe / "main.nf").write_text("workflow { }\n")
        (pipe / "nextflow.config").write_text(
            f"manifest {{\n    name = 'nanometanf'\n    version = '{version}'\n}}\n"
        )
        return pipe

    def _config(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("analysis_name: test\n")
        return str(cfg)

    def test_too_old_checkout_is_refused_by_name(self, tmp_path):
        pipe = self._checkout(tmp_path, "1.4.1dev")
        m = NextflowManager(str(tmp_path), pipeline_source=f"local:{pipe}")
        ok, message = m.setup(self._config(tmp_path))
        assert ok is False
        assert "1.4.1dev" in message and "1.10.0" in message

    def test_refusal_happens_before_parameters_are_built(self, tmp_path):
        pipe = self._checkout(tmp_path, "1.4.1dev")
        m = NextflowManager(str(tmp_path), pipeline_source=f"local:{pipe}")
        # setup() has no blanket except, so an AssertionError from the patch
        # would propagate; the refusal must come before the call.
        with patch(
            "nanometa_live.core.workflow.nextflow_manager.create_nextflow_params",
            side_effect=AssertionError("parameters must not be built"),
        ):
            ok, message = m.setup(self._config(tmp_path))
        assert ok is False
        assert "1.4.1dev" in message

    def test_unreadable_version_becomes_a_launch_warning(self, tmp_path):
        pipe = tmp_path / "pipe"
        pipe.mkdir()  # no nextflow.config
        m = NextflowManager(str(tmp_path), pipeline_source=f"local:{pipe}")
        with patch(
            "nanometa_live.core.workflow.nextflow_manager.create_nextflow_params",
            side_effect=RuntimeError("stop after the compatibility check"),
        ):
            with pytest.raises(RuntimeError):
                m.setup(self._config(tmp_path))
        from nanometa_live.core.config.parameter_mapping import pop_launch_warnings
        warnings = pop_launch_warnings()
        assert any("1.10.0" in w for w in warnings), warnings
```

- [ ] **Step 10: Run them to verify they fail**

Run: `conda run -n nf-core python -m pytest tests/test_nextflow_manager.py -k PipelineFloor -q`
Expected: the first two FAIL (setup proceeds past the check; parameters are built), the third FAILS on the empty warning list.

- [ ] **Step 11: Wire the check into `setup()`**

In `nanometa_live/core/workflow/nextflow_manager.py`, extend the import at
line 23 so it reads:

```python
from nanometa_live.core.config.parameter_mapping import (
    add_launch_warning,
    create_nextflow_config,
    pop_launch_warnings,
```

(keep the remaining names in that import block as they are). Add the import
`from nanometa_live.core.workflow.pipeline_compat import check_pipeline_compatibility`
beside the other `nanometa_live.core.workflow` imports.

In `setup()`, directly after `self._run_config = dict(config)` (line 490) and
before `params = create_nextflow_params(config)`, insert:

```python
            # The pipeline must declare every parameter this release sends;
            # an older checkout fails at Start with an nf-schema message that
            # names a parameter rather than a version. Refuse by name here.
            verdict = check_pipeline_compatibility(self.pipeline_source)
            if verdict.status == "too_old":
                logging.error(verdict.message)
                return False, verdict.message
            if verdict.status == "unknown":
                add_launch_warning(verdict.message)
```

The `unknown` warning is collected by the existing
`self.launch_warnings = pop_launch_warnings()` a few lines below and reaches
the "Analysis Started" toast through `BackendManager.start`.

- [ ] **Step 12: Run the launcher and readiness tests together**

Run: `conda run -n nf-core python -m pytest tests/test_nextflow_manager.py tests/test_readiness_pipeline_version.py tests/test_pipeline_compat.py -q`
Expected: all pass.

- [ ] **Step 13: Run the full suite**

Run: `conda run -n nf-core python -m pytest -q`
Expected: pass, no new skips. If `tests/test_tick_call_counts.py` or a
readiness fixture asserts an exact check count, update that count by one and
note it in the commit body.

- [ ] **Step 14: Document and commit**

Add to the CLAUDE.md "Toolchain floor" section, after the Nextflow paragraph:

```
**nanometanf floor.** `core/workflow/pipeline_compat.py` owns
`NANOMETANF_MIN_VERSION` (1.10.0 as of 0.18.0). `NextflowManager.setup`
refuses a checkout below it by name, the readiness checklist carries a
"Pipeline Version" row, and the README compatibility matrix names the same
floor (fence: `tests/test_compatibility_matrix.py`). A `remote:` source runs
`~/.nextflow/assets/foi-bioinformatics/nanometanf`, which the run command
never refreshes (no `-latest`), so the check reads that checkout: the fix it
names is `nextflow pull foi-bioinformatics/nanometanf -r <branch>`. Bump the
floor in the same commit that first sends a parameter the older schema lacks.
```

Add a CHANGELOG entry under a new `## [Unreleased]` heading, "Added": "Start
Analysis refuses a nanometanf checkout below 1.10.0 by name, and the
readiness checklist reports the pipeline version."

```bash
git add nanometa_live/core/workflow/pipeline_compat.py \
        nanometa_live/core/workflow/readiness_checker.py \
        nanometa_live/core/workflow/nextflow_manager.py \
        tests/test_pipeline_compat.py tests/test_readiness_pipeline_version.py \
        tests/test_nextflow_manager.py CLAUDE.md CHANGELOG.md
git commit -m "feat(launch): refuse a nanometanf checkout below the parameter floor by name

0.18.0 sends parameters that nanometanf < 1.10.0 does not declare, and the
run failed at Start with an nf-schema message naming a parameter. The
launcher now reads the version of the checkout it would run and refuses
below NANOMETANF_MIN_VERSION; the readiness checklist carries the same row.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

### Task 2: CI executes an imported singularity bundle on amd64

**Why.** The only air-gapped rig was arm64, so amd64 execution of a bundled
image has never been observed; the bundle-deploy workflow imports but never
runs. The field machine is Linux/amd64, which is exactly the GitHub
`ubuntu-latest` runner.

**Scope.** A stand-in pipeline with one module and one real image (the seqtk
biocontainer, as nanometanf's own CI uses), so the job pulls one image
rather than the ~25 a full nanometanf bundle carries. It proves the
export-import-execute path and the `NXF_SINGULARITY_CACHEDIR` wiring on
amd64; it does not prove a full nanometanf run and is not air-gapped. Say so
in the workflow comments.

**Files:**
- Modify: `.github/workflows/bundle-deploy.yml` (add two jobs; extend the
  path filter and add a weekly schedule)

**Interfaces:**
- Consumes: `nanometa-prepare export --containerization singularity --target-platform linux/amd64 --pipeline <dir>`; `nanometa-prepare import --bundle --db`; the imported `config.yaml` keys `nxf_singularity_cachedir` and `pipeline_source`; the cache name convention `BundleManager._singularity_cache_name` (scheme stripped, `:` and `/` to `-`, `.img` appended).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Extend the trigger block**

Replace the `on:` block at the top of `.github/workflows/bundle-deploy.yml` with:

```yaml
on:
  pull_request:
    paths:
      - 'nanometa_live/core/workflow/bundle_manager.py'
      - 'nanometa_live/core/workflow/container_inventory.py'
      - 'nanometa_live/core/workflow/nextflow_manager.py'
      - 'nanometa_live/cli/prepare.py'
      - '.github/workflows/bundle-deploy.yml'
  push:
    branches: [dev, main]
    paths:
      - 'nanometa_live/core/workflow/bundle_manager.py'
      - 'nanometa_live/core/workflow/container_inventory.py'
      - 'nanometa_live/core/workflow/nextflow_manager.py'
      - 'nanometa_live/cli/prepare.py'
      - '.github/workflows/bundle-deploy.yml'
  schedule:
    # Weekly, so a change in Nextflow's singularity cache-name convention
    # is noticed within a week rather than on a field machine.
    - cron: '0 5 * * 1'
  workflow_dispatch:
```

- [ ] **Step 2: Add the export job**

Append to the `jobs:` map (after the existing `import` job):

```yaml
  export-singularity:
    # amd64 execution of a bundled image has never been observed: the one
    # air-gapped rig was arm64 and failed exactly at "image architecture
    # (amd64) could not run on the host (arm64)". This pair of jobs exports
    # a singularity bundle on an amd64 runner, imports it on a second one,
    # and RUNS the bundled image offline. LIMITS: one stand-in module with
    # one real image (not the ~25 of nanometanf), and the runner is not
    # air-gapped -- the assertion that no pull happened rests on the
    # Nextflow log, not on a closed network.
    name: Export singularity bundle (amd64 build machine)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e .

      - name: Install Apptainer
        uses: eWaterCycle/setup-apptainer@v2
        with:
          apptainer-version: 1.3.6

      - name: Build a one-module stand-in pipeline
        run: |
          set -euo pipefail
          HOME_DIR="$RUNNER_TEMP/nanometa_home"
          mkdir -p "$HOME_DIR/watchlists"
          PIPE="$RUNNER_TEMP/standin"
          mkdir -p "$PIPE/modules/local/seqtk_arch"

          # The container directive uses the nf-core ternary so the inventory
          # walker finds both the singularity URL and the docker reference,
          # and the singularity profile resolves the same URL the bundle
          # pre-pulled. No Unicode in these files.
          cat > "$PIPE/modules/local/seqtk_arch/main.nf" <<'NF'
          process SEQTK_ARCH {
              container "${ workflow.containerEngine == 'singularity' ? 'https://depot.galaxyproject.org/singularity/seqtk:1.4--he4a0461_2' : 'quay.io/biocontainers/seqtk:1.4--he4a0461_2' }"

              output:
              path 'arch.txt'

              script:
              """
              uname -m > arch.txt
              seqtk 2>&1 | head -n 1 >> arch.txt || true
              """
          }
          NF

          cat > "$PIPE/main.nf" <<'NF'
          include { SEQTK_ARCH } from './modules/local/seqtk_arch/main'

          workflow {
              SEQTK_ARCH()
              SEQTK_ARCH.out.view { f -> "arch: " + f.text.trim() }
          }
          NF

          cat > "$PIPE/nextflow.config" <<'NF'
          manifest {
              name    = 'nanometanf'
              version = '1.10.0'
          }

          profiles {
              singularity {
                  singularity.enabled    = true
                  singularity.autoMounts = true
              }
          }
          NF

          mkdir -p "$RUNNER_TEMP/db"
          cat > "$RUNNER_TEMP/config.yaml" <<YAML
          nanometa_home: "$HOME_DIR"
          kraken_db: "$RUNNER_TEMP/db"
          pipeline_source: "$PIPE"
          pipeline_profile: "singularity"
          offline_mode: true
          YAML
          echo "NANOMETA_HOME_DIR=$HOME_DIR" >> "$GITHUB_ENV"
          echo "STANDIN_PIPE=$PIPE" >> "$GITHUB_ENV"

      - name: Export a singularity bundle for linux/amd64
        env:
          NANOMETA_DATA_DIR: ${{ env.NANOMETA_HOME_DIR }}
        run: |
          nanometa-prepare export \
            --config "$RUNNER_TEMP/config.yaml" \
            --output "$RUNNER_TEMP/bundle-sing.tar.gz" \
            --no-pre-warm \
            --containerization singularity \
            --target-platform linux/amd64 \
            --pipeline "$STANDIN_PIPE"
          ls -la "$RUNNER_TEMP/bundle-sing.tar.gz"

      - name: The bundle carries exactly one image under the predicted name
        run: |
          python - <<'PY'
          import os, sys, tarfile
          path = os.path.join(os.environ["RUNNER_TEMP"], "bundle-sing.tar.gz")
          expected = "depot.galaxyproject.org-singularity-seqtk-1.4--he4a0461_2.img"
          with tarfile.open(path) as tar:
              names = tar.getnames()
          images = [n for n in names if "/pipeline_containers/" in n and n.endswith((".img", ".sif"))]
          print("images in bundle:", images)
          if len(images) != 1 or not images[0].endswith("/" + expected):
              print(f"expected one image named {expected}")
              sys.exit(1)
          PY

      - name: Remove the build machine's home and checkout before handing on
        run: rm -rf "$NANOMETA_HOME_DIR" "$STANDIN_PIPE"

      - uses: actions/upload-artifact@v4
        with:
          name: offline-bundle-singularity
          path: ${{ runner.temp }}/bundle-sing.tar.gz
          retention-days: 1
```

- [ ] **Step 3: Add the import-and-run job**

Append after it:

```yaml
  run-singularity:
    name: Import and run the bundled image (amd64 field machine)
    needs: export-singularity
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e .

      - name: Install Apptainer
        uses: eWaterCycle/setup-apptainer@v2
        with:
          apptainer-version: 1.3.6

      - name: Install Nextflow
        run: |
          curl -fsSL get.nextflow.io | bash
          sudo install -m 0755 nextflow /usr/local/bin/nextflow
          nextflow -v

      - uses: actions/download-artifact@v4
        with:
          name: offline-bundle-singularity
          path: ${{ runner.temp }}

      - name: Verify, then import onto a machine that never saw the exporter
        run: |
          set -euo pipefail
          nanometa-prepare verify --bundle "$RUNNER_TEMP/bundle-sing.tar.gz"
          FIELD_HOME="$RUNNER_TEMP/field_home"
          mkdir -p "$RUNNER_TEMP/field_db"
          NANOMETA_DATA_DIR="$FIELD_HOME" nanometa-prepare import \
            --bundle "$RUNNER_TEMP/bundle-sing.tar.gz" \
            --db "$RUNNER_TEMP/field_db"
          echo "FIELD_HOME=$FIELD_HOME" >> "$GITHUB_ENV"

      - name: Read the wiring the import wrote
        run: |
          python - <<'PY'
          import os, pathlib, sys, yaml
          home = pathlib.Path(os.environ["FIELD_HOME"])
          cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
          cache = cfg.get("nxf_singularity_cachedir") or ""
          pipe = cfg.get("pipeline_source") or ""
          problems = []
          if not cache or not pathlib.Path(cache).is_dir():
              problems.append(f"nxf_singularity_cachedir not wired: {cache!r}")
          if not pipe or not (pathlib.Path(pipe) / "main.nf").is_file():
              problems.append(f"pipeline_source not rebased to a checkout: {pipe!r}")
          if cfg.get("offline_mode") is not True:
              problems.append("offline_mode is not True after import")
          if problems:
              print("\n".join(problems)); sys.exit(1)
          with open(os.environ["GITHUB_ENV"], "a") as fh:
              fh.write(f"SING_CACHE={cache}\nFIELD_PIPE={pipe}\n")
          print("cache:", cache); print("pipeline:", pipe)
          PY

      - name: Run the bundled image offline on amd64
        env:
          NXF_OFFLINE: "true"
          NXF_DISABLE_CHECK_LATEST: "true"
          NXF_SINGULARITY_CACHEDIR: ${{ env.SING_CACHE }}
          NXF_SINGULARITY_LIBRARYDIR: ${{ env.SING_CACHE }}
        run: |
          set -euo pipefail
          uname -m
          cd "$RUNNER_TEMP"
          nextflow run "$FIELD_PIPE/main.nf" \
            -profile singularity \
            -ansi-log false \
            -work-dir "$RUNNER_TEMP/work" | tee run.out

      - name: The image was found locally, not pulled, and ran as x86_64
        run: |
          set -euo pipefail
          cd "$RUNNER_TEMP"
          LOG=.nextflow.log
          grep -q "found local library for image" "$LOG" || { echo "no local-library hit in $LOG"; grep -i singularity "$LOG" || true; exit 1; }
          if grep -qi "pulling singularity image" "$LOG"; then echo "Nextflow pulled an image; the bundle was not used"; exit 1; fi
          grep -q "arch: x86_64" run.out || { echo "process output did not report x86_64"; cat run.out; exit 1; }
          echo "OK: bundled image executed on amd64 without a pull."
```

- [ ] **Step 4: Validate the YAML locally**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/bundle-deploy.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 5: Commit and trigger the job**

```bash
git add .github/workflows/bundle-deploy.yml
git commit -m "ci(bundle): execute an imported singularity bundle on an amd64 runner

The one air-gapped rig was arm64, so amd64 execution of a bundled image
was never observed. A second export/import pair now pulls one real image
into a singularity bundle on ubuntu-latest, imports it on a second runner
and runs it with NXF_OFFLINE=true, asserting the local-library hit in the
Nextflow log and x86_64 from inside the container.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
git push origin dev
gh workflow run bundle-deploy.yml --ref dev
```

- [ ] **Step 6: Watch the run and fix what it reports**

Run: `gh run watch $(gh run list --workflow bundle-deploy.yml --limit 1 --json databaseId -q '.[0].databaseId')`
Expected: all four jobs green. Two likely first-run failures and their fixes:
- The inventory walker found no image (`image_count 0`): confirm the module
  directory is `modules/local/<name>/main.nf` and the directive string
  contains `quay.io/biocontainers/` or `depot.galaxyproject.org/singularity/`
  in quotes, which are the two regexes in `container_inventory.py`.
- The strict parser rejects the stand-in: run
  `nextflow run "$PIPE/main.nf" -preview` locally against the same text
  before pushing again.

- [ ] **Step 7: Record the result**

In `docs/known-untested-surface.md`, under "Air-gapped operation", append:

```
**amd64 execution of a bundled image, verified 2026-MM-DD in CI.** The
bundle-deploy workflow exports a singularity bundle on an amd64 runner,
imports it on a second and runs the bundled image with `NXF_OFFLINE=true`;
the Nextflow log shows the local-library hit and no pull, and the process
reports x86_64. Limits: one stand-in module and one image, not the full
nanometanf set, and the runner is not air-gapped.
```

Fill in the date of the green run. Commit:

```bash
git add docs/known-untested-surface.md
git commit -m "docs(untested): amd64 execution of a bundled image is now observed in CI

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

### Task 3: Distribution: PyPI workflow, compatibility matrix, bioconda recipe text

**Why.** `docs/user-guide.md` tells operators to `pip install nanometa-live`,
and no such package exists on PyPI. bioconda carries 0.15.0 against 0.18.0.
Nothing states which nanometanf goes with which GUI release.

**Files:**
- Create: `.github/workflows/publish.yml`
- Modify: `pyproject.toml` (dev extra), `README.md` (new "Compatibility"
  section after "Requirements", line 87), `docs/user-guide.md:9-14`
  (prerequisites)
- Create: `tests/test_compatibility_matrix.py`
- Create: `docs/distribution/bioconda-0.18.0-meta.yaml`

**Interfaces:**
- Consumes: `NANOMETANF_MIN_VERSION` from Task 1;
  `nanometa_live.__version__`.

- [ ] **Step 1: Write the failing matrix fence test**

Create `tests/test_compatibility_matrix.py`:

```python
"""The README states which nanometanf this GUI release pairs with.

The two are released in lock-step (0.18.0 sends parameters only nanometanf
1.10.0 declares) and the launcher refuses an older checkout by version
(pipeline_compat). The table an operator reads must name the same floor
the code enforces, and the prerequisites must not contradict pyproject.
"""

from pathlib import Path

import pytest

import nanometa_live
from nanometa_live.core.workflow.pipeline_compat import NANOMETANF_MIN_VERSION

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def _current_minor():
    major, minor, *_ = nanometa_live.__version__.split(".")
    return f"{major}.{minor}"


def test_readme_matrix_names_the_current_minor_and_the_floor():
    text = (ROOT / "README.md").read_text()
    assert "## Compatibility" in text
    section = text.split("## Compatibility", 1)[1].split("\n## ", 1)[0]
    row = [ln for ln in section.splitlines() if ln.startswith(f"| {_current_minor()}.x")]
    assert row, f"no matrix row for {_current_minor()}.x"
    assert NANOMETANF_MIN_VERSION in row[0]


def test_user_guide_prerequisites_match_pyproject():
    text = (ROOT / "docs" / "user-guide.md").read_text()
    assert "Python 3.9" not in text
    assert "Python 3.11" in text
    assert "26.04" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `conda run -n nf-core python -m pytest tests/test_compatibility_matrix.py -q`
Expected: FAIL on `"## Compatibility" in text` and on `"Python 3.9" not in text`.

- [ ] **Step 3: Add the README section**

Insert after the "Requirements" section (before `## Development`):

```markdown
## Compatibility

Nanometa Live and nanometanf are released together. A GUI release sends
parameters that only its companion pipeline declares, and Start Analysis
refuses an older checkout by version. `remote:dev` runs whatever was last
pulled into `~/.nextflow/assets/foi-bioinformatics/nanometanf`; update it
with `nextflow pull foi-bioinformatics/nanometanf -r dev`.

| Nanometa Live | nanometanf | Nextflow |
|---------------|------------|----------|
| 0.18.x | 1.10.0 | >= 26.04.0 |
| 0.17.x | 1.9.0 | >= 26.04.0 |
| 0.16.x | 1.8.0 | >= 26.04.0 |

Earlier pairings are recorded in [`CHANGELOG.md`](CHANGELOG.md).
```

- [ ] **Step 4: Correct the user-guide prerequisites**

Replace lines 9 to 14 of `docs/user-guide.md` with:

```markdown
### Prerequisites

- Python 3.11 or higher
- Conda or Mamba (the canonical and supported pipeline profile)
- Nextflow 26.04.0 or newer (the version nanometanf floors at)
- A Kraken2 database
- The nanometanf release named in the README compatibility table
```

- [ ] **Step 5: Run the fence test**

Run: `conda run -n nf-core python -m pytest tests/test_compatibility_matrix.py -q`
Expected: pass.

- [ ] **Step 6: Add `build` to the dev extra**

In `pyproject.toml`, change the `dev` list to:

```toml
dev = [
    "pytest>=7.2.1",
    "pytest-xdist>=3.5.0",
    "pytest-cov>=4.1.0",
    "filelock>=3.10.0",
    "build>=1.2.0",
]
```

Then install it so the wheel test runs rather than skips:

Run: `conda run -n nf-core python -m pip install build twine && conda run -n nf-core python -m pytest tests/test_wheel_ships_assets.py -q -rs`
Expected: pass, with no `SKIPPED` line mentioning the build package.

- [ ] **Step 7: Prove the distribution builds**

Run:
```bash
rm -rf dist && conda run -n nf-core python -m build && conda run -n nf-core python -m twine check dist/*
```
Expected: `dist/nanometa_live-0.18.0-py3-none-any.whl` and
`dist/nanometa_live-0.18.0.tar.gz`, both `PASSED`. `dist/` is already in
`.gitignore` (line 14); do not commit the build output.

- [ ] **Step 8: Write the publish workflow**

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

# Builds the sdist and wheel for every published GitHub release and uploads
# them through PyPI trusted publishing (no API token in the repository).
# The owner must once register a pending publisher on PyPI for the project
# name "nanometa-live" with: owner FOI-Bioinformatics, repository
# nanometa_live, workflow publish.yml, environment pypi -- and create the
# "pypi" environment under the repository settings. Until then the publish
# job fails at upload and the build job still proves the distribution builds.

on:
  release:
    types: [published]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  build:
    name: Build sdist and wheel
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Build
        run: |
          python -m pip install --upgrade pip build twine
          python -m build
          python -m twine check dist/*

      - name: The wheel carries the release tag
        if: github.event_name == 'release'
        run: |
          TAG="${GITHUB_REF_NAME}"
          ls dist/
          ls dist/ | grep -q "^nanometa_live-${TAG}-" || { echo "wheel version does not match tag ${TAG}"; exit 1; }

      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    name: Upload to PyPI
    needs: build
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - uses: pypa/gh-action-pypi-publish@release/v1
```

Validate: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml')); print('yaml ok')"`.

- [ ] **Step 9: Write the bioconda recipe text**

Create `docs/distribution/bioconda-0.18.0-meta.yaml`. This is the full
replacement for `recipes/nanometa-live/meta.yaml` in bioconda-recipes; the
run dependencies follow `requirements.txt` plus the three preparation tools
the GUI shells out to (`kraken2-inspect`, `datasets`, `makeblastdb`) and
Nextflow at the pipeline floor. The 0.15.0 recipe still listed snakemake,
fastp and pytest, none of which the package uses.

```yaml
{% set name = "nanometa-live" %}
{% set version = "0.18.0" %}

package:
  name: {{ name }}
  version: {{ version }}

source:
  url: https://github.com/FOI-Bioinformatics/nanometa_live/archive/{{ version }}.tar.gz
  sha256: d6033d1563b57a9b7279f907d4bea2e9ba3119dcd222209ad01222efa5353b71

build:
  number: 0
  entry_points:
    - nanometa-live = nanometa_live.nanometa_live:main
    - nanometa-prepare = nanometa_live.cli.prepare:main
    - nanometa-report = nanometa_live.cli.report:main
  script: {{ PYTHON }} -m pip install . --no-deps --no-build-isolation --no-cache-dir -vvv
  noarch: python
  run_exports:
    - {{ pin_subpackage(name, max_pin="x.x") }}

requirements:
  host:
    - pip
    - python >=3.11
    - setuptools >=67.6.0
  run:
    - python >=3.11
    - dash >=4.0.0
    - dash-ag-grid >=31.0.0
    - dash-bootstrap-components >=1.7.1
    - dash-daq >=0.6.0
    - pandas >=2.2.3
    - numpy >=2.0.0
    - plotly >=6.0.0
    - ruamel.yaml >=0.18.10
    - pyyaml >=6.0.1
    - biopython >=1.85
    - tqdm >=4.67.1
    - flask >=3.1.0
    - requests >=2.32.3
    - diskcache >=5.6.0
    - psutil >=6.0.0
    - multiprocess >=0.70.0
    - dill >=0.3.0
    - openpyxl >=3.1.0
    - nextflow >=26.04.0
    - kraken2 >=2.1.4
    - blast >=2.16.0
    - ncbi-datasets-cli >=17.1.0

test:
  commands:
    - nanometa-live --help
    - nanometa-prepare --help
    - nanometa-report --help

about:
  home: "https://github.com/FOI-Bioinformatics/nanometa_live"
  license: "GPL-3.0-or-later"
  license_family: GPL3
  license_file: "LICENSE.txt"
  summary: "Real-time visualisation dashboard for Oxford Nanopore metagenomic sequencing analysis with the nanometanf pipeline."
  doc_url: "https://github.com/FOI-Bioinformatics/nanometa_live/tree/main/docs"
  dev_url: "https://github.com/FOI-Bioinformatics/nanometa_live"
```

The checksum was computed on 2026-09-04 with
`curl -sL https://github.com/FOI-Bioinformatics/nanometa_live/archive/0.18.0.tar.gz | shasum -a 256`.
Recompute it if the tag is ever moved.

- [ ] **Step 10: Commit**

```bash
git add .github/workflows/publish.yml pyproject.toml README.md docs/user-guide.md \
        tests/test_compatibility_matrix.py docs/distribution/bioconda-0.18.0-meta.yaml
git commit -m "build(dist): PyPI publish workflow, compatibility matrix, bioconda recipe text

The user guide told operators to pip install a package that was not on
PyPI, bioconda carried 0.15.0 against 0.18.0, and nothing named which
nanometanf pairs with which GUI release. The README now carries the table
(fenced against pipeline_compat's floor), releases build and upload through
trusted publishing, and the bioconda recipe text is ready to submit.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

- [ ] **Step 11: Owner actions (outside the repository)**

1. On PyPI, add a pending trusted publisher for project `nanometa-live`
   (owner `FOI-Bioinformatics`, repository `nanometa_live`, workflow
   `publish.yml`, environment `pypi`). On GitHub, create the `pypi`
   environment under Settings, Environments.
2. Fork `bioconda/bioconda-recipes`, branch `nanometa-live-0.18.0`, replace
   `recipes/nanometa-live/meta.yaml` with the file from Step 9, run
   `bioconda-utils lint --packages nanometa-live`, open the pull request.
   Bioconda's bot builds it; address what it reports.
3. Run `gh workflow run publish.yml --ref dev` once to confirm the build
   job is green before the next release.

---

### Task 4: Answer issue 69

**Why.** "usage with multiple barcodes" has been open and unanswered since
2024-06-06. The 2.x rewrite added exactly that, and the issue is the first
thing a visitor to the repository sees.

**Files:**
- Create: `docs/distribution/issue-69-reply.md`

- [ ] **Step 1: Write the reply**

```markdown
Thank you for the report, and apologies for the long silence on it.

Multiplexed (barcoded) runs are supported in the 2.x rewrite. Set
`sample_handling: by_barcode` in the configuration, or choose "By barcode"
in the Configuration tab, and point the input directory at the folder that
holds `barcode01/`, `barcode02/`, and so on (a MinKNOW `fastq_pass/` folder
is a valid input; `fastq_fail/` and `fastq_skip/` are excluded on intake).
The dashboard then lists every barcode in the sample selector, screens the
run as a whole for watchlist organisms, and names the barcodes carrying a
detection. Negative-control barcodes can be declared and are reported
alongside a detection rather than suppressing it.

Documentation: `docs/user-guide.md`, section "Barcoded data structure", and
`docs/quickstart-with-nanorunner.md` for an end-to-end demo with simulated
barcoded input.

Current release: Nanometa Live 0.18.0 with nanometanf v1.10.0. I am closing
this as addressed; please reopen if the current release does not cover your
layout, ideally with the directory listing and the configuration used.
```

- [ ] **Step 2: Commit the text**

```bash
git add docs/distribution/issue-69-reply.md
git commit -m "docs(issues): reply text for issue 69, multiplexed runs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

- [ ] **Step 3: Owner posts it**

```bash
gh issue comment 69 -R FOI-Bioinformatics/nanometa_live --body-file docs/distribution/issue-69-reply.md
gh issue close 69 -R FOI-Bioinformatics/nanometa_live --reason completed
```

---

### Task 5: Decision records and a contributor guide

**Why.** One author wrote 1,054 of 1,183 commits, and the invariants live in
a 1,921-line CLAUDE.md that reads as a log. A second maintainer needs the
decisions in a form they can read in an hour, each with its context, its
consequences and the test that pins it.

**Files:**
- Create: `docs/decisions/README.md`, `docs/decisions/0001-verdict-earns-its-result.md`
  through `docs/decisions/0010-a-control-must-do-something.md`
- Create: `CONTRIBUTING.md`
- Create: `tests/test_decision_records.py`
- Modify: `docs/README.md` (add a row under "Reference"),
  `docs/developer-guide.md` ("Contributing" section, line 419: link to
  CONTRIBUTING.md and docs/decisions)

**Interfaces:**
- Produces: the record format below, which the fence test enforces.

- [ ] **Step 1: Write the failing fence test**

Create `tests/test_decision_records.py`:

```python
"""Every decision record has the four sections and is listed in the index.

The records replace reading CLAUDE.md end to end for a new maintainer; a
record missing its Evidence section, or absent from the index, is one a
reader cannot find or cannot verify.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DECISIONS = Path(__file__).resolve().parents[1] / "docs" / "decisions"
REQUIRED = ("## Context", "## Decision", "## Consequences", "## Evidence")


def _records():
    return sorted(p for p in DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_there_are_records():
    assert len(_records()) >= 10


@pytest.mark.parametrize("path", _records(), ids=lambda p: p.stem)
def test_record_has_the_four_sections_in_order(path):
    text = path.read_text()
    positions = [text.find(h) for h in REQUIRED]
    assert all(p >= 0 for p in positions), f"{path.name} lacks {[h for h, p in zip(REQUIRED, positions) if p < 0]}"
    assert positions == sorted(positions), f"{path.name}: sections out of order"
    assert re.match(r"# \d{4}\. ", text), f"{path.name} must start with '# NNNN. Title'"
    assert "**Status:**" in text


def test_index_lists_every_record():
    index = (DECISIONS / "README.md").read_text()
    for path in _records():
        assert f"({path.name})" in index, f"{path.name} not linked from docs/decisions/README.md"


@pytest.mark.parametrize("path", _records(), ids=lambda p: p.stem)
def test_evidence_names_an_existing_test_file(path):
    root = DECISIONS.parents[1]
    evidence = path.read_text().split("## Evidence", 1)[1]
    named = re.findall(r"`(tests/[\w/.-]+\.py)`", evidence)
    assert named, f"{path.name}: Evidence must name at least one tests/ file"
    for rel in named:
        assert (root / rel).is_file(), f"{path.name}: {rel} does not exist"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `conda run -n nf-core python -m pytest tests/test_decision_records.py -q`
Expected: FAIL at `test_there_are_records` (no directory).

- [ ] **Step 3: Write the index**

Create `docs/decisions/README.md`:

```markdown
# Decision records

Each record states one decision the code depends on, why it was taken, what
it costs, and the test that pins it. They are distilled from `CLAUDE.md`
and the audit reports under `docs/audit/`; where the two disagree, the
record is wrong and should be corrected from the code.

Format: `NNNN-short-title.md`, starting with `# NNNN. Title`, a
`**Status:**` line (accepted, superseded by NNNN), then `## Context`,
`## Decision`, `## Consequences`, `## Evidence`. Evidence names at least one
file under `tests/`. `tests/test_decision_records.py` enforces the format.

| Record | Decision |
|--------|----------|
| [0001](0001-verdict-earns-its-result.md) | A verdict never claims a result it did not earn |
| [0002](0002-species-includes-subspecies.md) | Species includes subspecies |
| [0003](0003-one-alert-per-watchlist-entry.md) | One alert per watchlist entry, keyed by (NCBI taxid, db_taxid) |
| [0004](0004-background-callbacks-share-state-via-stores.md) | Background callbacks share state through Stores and take no per-tick Input |
| [0005](0005-per-sample-cache-scope.md) | A per-sample cache entry is fingerprinted against that sample's own files |
| [0006](0006-run-outdir-is-derived.md) | The run output directory is derived, not configured |
| [0007](0007-one-database-profile-two-axes.md) | One database profile with two independent axes |
| [0008](0008-kraken2-sizing-belongs-to-the-pipeline.md) | Kraken2 sizing belongs to nanometanf, not the generated config |
| [0009](0009-import-never-reports-success-over-a-problem.md) | A bundle import never reports success over a problem it found |
| [0010](0010-a-control-must-do-something.md) | A control must do something |
```

- [ ] **Step 4: Write the ten records**

Each file follows the same shape. Write them with this content (one file
per block; the heading line is the file's first line).

`docs/decisions/0001-verdict-earns-its-result.md`:

```markdown
# 0001. A verdict never claims a result it did not earn

**Status:** accepted (2026-07, extended 2026-08-08)

## Context

Three defects found in the 2026-07 campaign were one defect: the system
rendered "we did not check" identically to "we checked and it is fine". The
banner said ALL CLEAR with no watchlist loaded while F. tularensis sat at
54% of reads; the exported report said NO WATCHED ORGANISMS DETECTED in the
same state; a sample whose reads were unreadable was offered like a healthy
one. For a biothreat tool these are opposite statements.

## Decision

`select_verdict` (`app/tabs/dashboard_helpers.py`) is a pure function of
its inputs. It returns NOT_SCREENED when no watchlist entry is active and
INSUFFICIENT_READS when total reads fall below `low_read_floor` (anchored to
`min_reads_for_validation`). Both are amber, never green. `total_reads=None`
means "not determined" and never reads as zero. A detection always outranks
depth and run health; a pipeline error outranks every non-detection state
including "starting". The exported report template carries the same
branches, and the Organisms panel and alarm text state depth the same way.

## Consequences

Every new verdict state goes into the pure function, not the callback, so it
is testable without an app. Any surface that can say "all clear" must show
what it screened and at what depth. The banner is aggregate-scoped and does
not follow the selected sample, so a detection in an unviewed barcode is
never hidden.

## Evidence

`tests/test_verdict_selector.py`, `tests/test_report_generator.py`,
`tests/test_verdict_banner_callback.py`.
```

`docs/decisions/0002-species-includes-subspecies.md`:

```markdown
# 0002. Species includes subspecies

**Status:** accepted (2026-08-20)

## Context

Three rules disagreed on what "species" meant: `== "S"` in the verdict and
attribution paths, `{"S","S1","S2"}` in the Organisms tab, and a
`normalize_ranks` table that was never called. A subspecies watchlist entry
(F. tularensis holarctica, Type B, at rank S1) could be watched on the
Organisms tab and never reach the verdict banner. The distinction is
clinical: Type A tularensis is markedly more virulent than Type B.

## Decision

`core/taxonomy/ranks.py` owns `SPECIES_RANKS = {S, S1, S2, S3}` and is the
single definition. Per-taxon consumers treat each row as an independent
taxid. Rankings that list "most abundant" stay species-only, because a
species beside its own subspecies reads as double counting. On the pipeline
side, read extraction for validation selects the clade
(`KreportTree.cladeOf`), not the exact node.

## Consequences

Kraken2's `cumul_reads` already contains a node's descendants; never sum
across ranks. Subspecies get their own table in the report. The Taxonomy
tab offers S1 as a level, off by default, because adding it splits a
species' flow rather than adding to it.

## Evidence

`tests/test_taxid_coordination.py`, `tests/test_report_generator.py`,
`tests/test_sunburst_tax_levels.py`.
```

`docs/decisions/0003-one-alert-per-watchlist-entry.md`:

```markdown
# 0003. One alert per watchlist entry, keyed by (NCBI taxid, db_taxid)

**Status:** accepted (2026-09-02)

## Context

The Bioshield list carries E. coli, E. coli_E and E. coli_F as three entries
with distinct database nodes and one NCBI taxid (562). Deduplicating alerts
on the NCBI taxid alone collapsed them: E. coli_F at 11 reads (threshold 10)
vanished behind E. coli at 22, and which variant survived flipped with the
frame's row order.

## Decision

`_dedupe_alerts_by_entry` keeps the dominant node per entry, keyed on the
same pair `_identity_key` stores entries under. Every alert carries
`db_taxid`. Where several watchlist keys resolve to one database node
(B. mallei within B. pseudomallei under GTDB), the first is the match and
the rest become `ambiguous_with`, rendered as "X or Y".

## Consequences

Matching is index-based (O(rows + entries)) and only alert-relevant tiers
are indexed. Entries without any taxid get a synthetic key in the reserved
pseudo-taxid band (`core/taxonomy/pseudo_taxid.py`) and can never match a
report; the upload path surfaces them.

## Evidence

`tests/test_taxid_coordination.py`,
`tests/test_watchlist_matching_equivalence.py`,
`tests/test_pathogen_check_memo.py`.
```

`docs/decisions/0004-background-callbacks-share-state-via-stores.md`:

```markdown
# 0004. Background callbacks share state through Stores and take no per-tick Input

**Status:** accepted (2026-08-25)

## Context

Dash's DiskcacheManager runs a background callback in a separate OS
process, where every Python singleton (WatchlistManager, caches) is empty.
The readiness checker reported every watchlist check as "not enabled" from
the worker. Separately, a background callback fed by `update-interval`
spawned a process per tick and leaked about five pipe descriptors per
spawn; 4,500 pipes were measured in two hours.

## Decision

A background callback that needs main-process state takes it from a
`dcc.Store` populated in the main process (`watchlist-entries-snapshot`,
passed into `ReadinessChecker.check_readiness(watchlist_entries=...)`).
No background callback takes `update-interval` as an Input; per-tick work
runs behind a synchronous main-process gate that bumps a "due" Store, and
periodic probes run in a daemon thread. Heavy click paths are
`background=True` with `running=` or `progress=` declared. Start and Stop
run main-process threads, because BackendManager holds subprocess handles
a worker cannot.

## Consequences

Every background callback follows the worker/Store/finalize split: I/O in
the worker, side effects in a main-process finalize. Browser Stores carry
slim payloads (`export_config(slim=True)`); disk files stay full.

## Evidence

`tests/test_background_callback_contract.py`,
`tests/test_readiness_spawn_gate.py`, `tests/test_payload_budgets.py`.
```

`docs/decisions/0005-per-sample-cache-scope.md`:

```markdown
# 0005. A per-sample cache entry is fingerprinted against that sample's own files

**Status:** accepted (2026-07-25, extended 2026-08-25)

## Context

A quiet 24-sample real-time poll cost 74,462 `stat` calls and 772 ms, with
a scaling exponent of O(N^1.65): every per-sample lookup walked the whole
results tree, so one sample's new batch invalidated every other sample.

## Decision

`_sample_fingerprint_paths` and `_seqkit_fingerprint_paths` return the
sample-scoped path list; only the aggregate load may pass the directory.
`check_data_freshness` bumps a per-poll epoch, and an entry stored in the
current epoch is returned without a filesystem call. A `stale` mtime
verdict never falls through to the TTL cache. Write-once batch files are
cached on immutability; caches are byte-budgeted
(`NANOMETA_FRAME_CACHE_MB`) and every module-level cache is wired into
both `clear_all_loader_caches` and `instrument.reset_caches`.

## Consequences

The same poll now costs 2,119 calls and 59 ms at O(N^0.91). A frame served
from a last-good fallback or a tier fallback is transient and must not be
cached under the new fingerprint. Consumers copy a cached frame before
mutating it.

## Evidence

`tests/test_loader_cache_transparency.py`, `tests/test_cache_inventory.py`,
`tests/test_tick_call_counts.py`, `tests/test_cache_capacity_scaling.py`.
```

`docs/decisions/0006-run-outdir-is-derived.md`:

```markdown
# 0006. The run output directory is derived, not configured

**Status:** accepted (2026-08-18)

## Context

A hand-written config that set only `results_output_directory` was
silently redirected to a derived folder, and the collision modal's
Continue and Archive buttons launched into a fresh hidden directory while
the modal promised the one it showed.

## Decision

`resolve_run_outdir` (`app/utils/outdir_resolution.py`) decides where a
run writes: a non-empty `results_dir_override` verbatim, otherwise
`<project>/results/<slug(analysis_name)>`. `results_output_directory` is
the computed value written back at Start so the viewer follows it. Every
launch path, including the collision handler, resolves through the same
function. A mid-run Apply pins both keys for the running run.

## Consequences

An explicit custom folder goes in `results_dir_override`. Every successful
start writes `.nanometa.run.json` with an input fingerprint, so pointing a
different input at a populated folder is detected next time.

## Evidence

`tests/test_outdir_resolution.py`, `tests/test_outdir_resolution_sweep.py`,
`tests/test_input_layout_mismatch.py`.
```

`docs/decisions/0007-one-database-profile-two-axes.md`:

```markdown
# 0007. One database profile with two independent axes

**Status:** accepted (2026-07)

## Context

Four disagreeing axes (`kraken_taxonomy`, `DatabaseTaxonomyType`,
`TaxonomyType`, the watchlist's `taxonomy_mode`) tried to answer two
different questions with one value, and a MIXED value was never read.
Field databases are flextaxd hybrids: an NCBI backbone with GTDB-named
clades grafted in at high taxids.

## Decision

`core/taxonomy/database_profile.py` carries `taxids_are_ncbi` (may a raw
taxid comparison be trusted; defaults to False because a wrong trust names
the wrong organism) and `nomenclature` (ncbi, gtdb or unknown; unknown
narrows nothing). Both are detected from the database itself, never from
its directory name. `ExactTaxidStrategy` carries no name verification,
because renamed taxa (SARS-CoV-2, Candida auris) are matched only by taxid.
GTDB genus-suffix variants are generated lazily and gated on the profile.

## Consequences

The profile rides the index file (cache version 2.0) and is copied onto the
mappings file, because workers load the mappings standalone. Coverage
analysis (`core/taxonomy/coverage.py`) reports which watchlist entries a
minimized database can see at all; an ALL CLEAR for an absent entry is no
result.

## Evidence

`tests/test_database_profile.py`.
```

`docs/decisions/0008-kraken2-sizing-belongs-to-the-pipeline.md`:

```markdown
# 0008. Kraken2 sizing belongs to nanometanf, not the generated config

**Status:** accepted (2026-08-18)

## Context

The generated `-c` config outranks every pipeline config layer. A retired
`withName: 'KRAKEN2_KRAKEN2'` block pinned `cpus = 1` and `memory = 8.GB`,
so every GUI-launched classification ran single-threaded regardless of
nanometanf's own scaling.

## Decision

`create_nextflow_config` emits no Kraken2 process block. The GUI passes
`--kraken2_memory_gb` sized from the measured `hash.k2d` and
`kraken2_memory_mapping` resolved by an explicit-value-wins resolver. CPU
is `--max_cpus`; `pipeline_cores`, `validation_cores` and `blast_cores`
were removed because nothing read them or they pinned process names the
pipeline does not have.

## Consequences

`create_default_config` writes no default for a key whose resolver treats
"explicit value wins", or the resolver becomes dead code. The readiness
checklist warns when the database sits on a removable or network volume.

## Evidence

`tests/test_readiness_offline_checks.py`, `tests/test_deployment_gui_fixes.py`.
```

`docs/decisions/0009-import-never-reports-success-over-a-problem.md`:

```markdown
# 0009. A bundle import never reports success over a problem it found

**Status:** accepted (2026-08-14, extended 2026-08-27)

## Context

On an air-gapped rig a wrong `--db` path imported in silence, a failure
writing the rebased config left `success` True with `${KRAKEN_DB}` still in
it, and blocker messages opened with "Import aborted" during a dry run
that aborted nothing.

## Decision

`_verify_extracted_bundle` holds every pre-copy check and is shared by
`import_bundle` and the non-mutating `verify_bundle`, so the dry run
matches the import. A supplied database that is not usable sets
`kraken_db_invalid`; a config write failure sets `success = False`.
Messages state the condition, not the consequence. Singularity images are
named by Nextflow's own cache convention (`_singularity_cache_name`) and
`NXF_SINGULARITY_CACHEDIR` is injected at launch; conda caches are
relocated by rewriting the recorded build prefix and re-signing patched
Mach-O binaries.

## Consequences

Add a new check to `_verify_extracted_bundle`, never to the import path
alone. Build and field machine must share OS and CPU architecture for
conda mode; cross-platform means docker or singularity.

## Evidence

`tests/test_bundle_manager.py`, `tests/test_conda_cache_relocation.py`,
`tests/test_nextflow_manager.py`.
```

`docs/decisions/0010-a-control-must-do-something.md`:

```markdown
# 0010. A control must do something

**Status:** accepted (2026-08, extended 2026-09-03)

## Context

The Configuration tab carried an "Alert Threshold" whose tooltip promised
sensitivity and that nothing read, a "Clean temp files" switch with no
consumer, a port field that was saved and ignored, and a "Check Interval"
that reached only a logged legacy parameter. A slider for BLAST identity
was decorative because a back-compat shim read a key no widget could
change.

## Decision

Before adding a form field, decide what reads it; before removing one,
check whether the function exists elsewhere or whether wiring it would be
destructive. The three field lists (`apply_config_changes`,
`initialize_form_from_config`, `detect_form_changes`) and the session draft
stay key-compatible. Numeric fields are checked in the browser before the
server applies, and a rejected Apply leaves the dirty badge in place. Form
fallbacks come from `config_loader.default_config()`.

## Consequences

`validation_identity_threshold` is the one identity key and feeds both
pipeline parameters. `chopper_minlength` and `chopper_quality` are the one
read filter and travel under every QC tool's parameter names.

## Evidence

`tests/test_negative_controls_form_field.py`, `tests/test_deployment_gui_fixes.py`.
```

- [ ] **Step 5: Run the fence test**

Run: `conda run -n nf-core python -m pytest tests/test_decision_records.py -q`
Expected: pass. If `test_evidence_names_an_existing_test_file` fails for a
record, replace the named file with one that exists (`ls tests | grep
<topic>`); do not delete the Evidence section.

- [ ] **Step 6: Write CONTRIBUTING.md**

Create `CONTRIBUTING.md` at the repository root:

```markdown
# Contributing to Nanometa Live

## Set up

```bash
git clone https://github.com/FOI-Bioinformatics/nanometa_live.git
cd nanometa_live
conda env create -f nanometa_live_env.yml   # includes Nextflow >= 26.04.0
conda activate nanometa_live_env
pip install -e ".[dev]"
pytest -q
```

The suite has about 4,100 tests and runs in parallel by default. Tests
marked `slow` need Nextflow and conda and are skipped unless selected with
`-m slow`. The coverage gate (`pytest --cov=nanometa_live`) enforces the
floor in `pytest.ini`; do not lower it.

## Where things are

- `nanometa_live/app/` is the Dash application. Each tab is a `*_tab.py`
  (callback wiring) beside a `*_helpers.py` (pure logic). Put logic in the
  helper and test it without an app.
- `nanometa_live/core/` holds loaders, parsers, taxonomy, the watchlist and
  the pipeline launcher. Import from the leaf module that owns a symbol.
- `docs/decisions/` holds the decisions the code depends on, each with the
  test that pins it. Read these first; they replace reading `CLAUDE.md`
  end to end. `CLAUDE.md` remains the detailed working notes.
- `docs/audit/` records what was tried on real runs and what was found.
  `docs/known-untested-surface.md` says what has not been verified.

## Rules that have a fence

Several properties are enforced by tests that read the code: no background
callback takes a per-tick Input; every module-level cache is wired into
the reset functions; tab gating is display-only; the README compatibility
table names the pipeline floor; every decision record has its sections.
When such a test fails, the property it names has been broken; do not edit
the test to make it pass.

## Companion pipeline

The GUI launches [nanometanf](https://github.com/FOI-Bioinformatics/nanometanf).
The two are released together (see the README compatibility table). A GUI
change that sends a new parameter needs the pipeline change first, and
`NANOMETANF_MIN_VERSION` in `core/workflow/pipeline_compat.py` bumped in the
same commit. nanometanf work stays on its `dev` branch and reaches `master`
through a pull request, because its lint and pre-commit checks run only on
pull requests.

## Releasing

1. On `dev`: bump `nanometa_live/__init__.py`, move the `Unreleased`
   changelog section under the new version with the date, commit
   `chore(release): prepare X.Y.Z`.
2. Open a pull request from `dev` to `main`; CI must be green.
3. Merge, tag `X.Y.Z` (no `v` prefix), publish a GitHub release. The
   publish workflow builds and uploads to PyPI.
4. Update the bioconda recipe (version and sha256) in a pull request to
   bioconda-recipes.

## Style

Modest scientific language in code, documentation and commit messages. No
Unicode in Nextflow files. Commit subjects follow `type(scope): summary`
with a body that says what was wrong and what changed.

## Becoming a maintainer

A second maintainer needs, in this order: the ten decision records, one
full read of `docs/OPERATOR_GUIDE.md`, one end-to-end run of
`docs/quickstart-with-nanorunner.md`, and one release cut with the current
maintainer watching. After that, review rights on both repositories.
```

- [ ] **Step 7: Link the new documents**

In `docs/README.md`, add to the "Reference" table:

```markdown
| [Decision records](decisions/README.md)                     | The decisions the code depends on, each with its pinning test |
| [Contributing](../CONTRIBUTING.md)                          | Set-up, layout, fences, releasing, becoming a maintainer |
```

In `docs/developer-guide.md`, at the start of the "Contributing" section
(line 419), add the sentence: "See `CONTRIBUTING.md` for set-up and the
release process, and `docs/decisions/` for the decisions the code depends
on."

In `CLAUDE.md`, under "Documentation", add the row
`| docs/decisions/ | Decision records; fence in tests/test_decision_records.py |`.

- [ ] **Step 8: Run the docs-related tests and the link checker**

Run: `conda run -n nf-core python -m pytest tests/test_decision_records.py tests/test_compatibility_matrix.py -q`
Expected: pass.

Run: `grep -o '\](\([^)]*\.md\))' docs/decisions/README.md CONTRIBUTING.md docs/README.md | sed 's/.*](\(.*\))/\1/' | sort -u`
and confirm each listed relative path exists from its file's directory.

- [ ] **Step 9: Commit**

```bash
git add docs/decisions CONTRIBUTING.md tests/test_decision_records.py docs/README.md docs/developer-guide.md CLAUDE.md
git commit -m "docs(decisions): ten decision records and a contributor guide

One author wrote almost every commit and the invariants lived in a
1,900-line working file. Each record states one decision, its context,
its cost and the test that pins it; the guide says how to set up, where
things are, which rules have a fence, and how a release is cut.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

- [ ] **Step 10: Owner action**

Name a candidate second maintainer and walk them through the "Becoming a
maintainer" list. The plan cannot do this part.

---

### Task 6: Network posture

**Why.** The server binds 127.0.0.1 by default, and with `--host 0.0.0.0`
exposes Start, Stop and the configuration to anyone who can reach the port,
with no authentication and no warning. The DiskcacheManager pickle CVE is
documented as low exposure on that same assumption.

**Files:**
- Create: `nanometa_live/app/utils/network_posture.py`
- Modify: `nanometa_live/app/__main__.py:183-202` (`_run_server`),
  `nanometa_live/nanometa_live.py:42-46` (`--host` help)
- Modify: `docs/user-guide.md` (new subsection after "Install from source",
  line 42), `docs/OPERATOR_GUIDE.md` ("General" tips, line 203)
- Test: `tests/test_network_posture.py`

**Interfaces:**
- Produces: `exposure_warning(host: str) -> Optional[str]`,
  `LOOPBACK_HOSTS: frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_network_posture.py`:

```python
"""Binding a non-loopback host prints what it exposes.

The dashboard has no authentication. On 127.0.0.1 that is the single-user
posture the design assumes; on 0.0.0.0 it is an unauthenticated control
surface, and the operator must be told so at the moment they choose it.
"""

from unittest.mock import patch

import pytest

from nanometa_live.app.utils.network_posture import LOOPBACK_HOSTS, exposure_warning

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("host", sorted(LOOPBACK_HOSTS) + ["LOCALHOST", " 127.0.0.1 "])
def test_loopback_hosts_produce_no_warning(host):
    assert exposure_warning(host) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "myhost.example"])
def test_reachable_hosts_name_what_is_exposed(host):
    text = exposure_warning(host)
    assert text is not None
    assert host in text
    assert "no authentication" in text
    assert "start and stop" in text.lower()
    assert "127.0.0.1" in text


def test_run_server_prints_the_warning_for_a_reachable_host(capsys):
    from nanometa_live.app.__main__ import _run_server

    app = type("App", (), {"run": staticmethod(lambda **kw: None)})()
    _run_server(app, host="0.0.0.0", port=8050, debug=False)
    err = capsys.readouterr().err
    assert "0.0.0.0" in err and "no authentication" in err


def test_run_server_is_silent_on_loopback(capsys):
    from nanometa_live.app.__main__ import _run_server

    app = type("App", (), {"run": staticmethod(lambda **kw: None)})()
    _run_server(app, host="127.0.0.1", port=8050, debug=False)
    assert capsys.readouterr().err == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `conda run -n nf-core python -m pytest tests/test_network_posture.py -q`
Expected: FAIL with `ModuleNotFoundError: nanometa_live.app.utils.network_posture`.

- [ ] **Step 3: Write the helper**

Create `nanometa_live/app/utils/network_posture.py`:

```python
"""What binding a given host exposes.

The dashboard has no authentication. Bound to a loopback address it is
reachable only from the machine it runs on, which is the posture the design
assumes (a field laptop, one operator). Bound to anything else it is a
control surface -- Start, Stop, configuration -- for everyone who can reach
the port. The warning states that at the moment the operator chooses it.
"""

from __future__ import annotations

from typing import Optional

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def exposure_warning(host: str) -> Optional[str]:
    """Return the warning text for a reachable ``host``, or None for loopback."""
    if (host or "").strip().lower() in LOOPBACK_HOSTS:
        return None
    return (
        f"Nanometa Live is listening on {host}. The dashboard has no "
        "authentication: anyone who can reach this port can start and stop "
        "pipeline runs, change the configuration and read every result. Use "
        "this only on a trusted network, or place an authenticating reverse "
        "proxy in front of it. Bind to 127.0.0.1 (the default) for use on "
        "this machine alone."
    )
```

- [ ] **Step 4: Wire it into the server start and the help text**

In `nanometa_live/app/__main__.py`, change `_run_server` so the body begins:

```python
    import errno
    import logging
    import sys

    from nanometa_live.app.utils.network_posture import exposure_warning

    warning = exposure_warning(host)
    if warning:
        logging.warning(warning)
        print(f"WARNING: {warning}", file=sys.stderr)
    try:
        app.run(host=host, port=port, debug=debug, threaded=True)
```

(the existing `except OSError` block stays as it is).

In `nanometa_live/nanometa_live.py`, change the `--host` help string to:

```python
        help=(
            "Host to bind the server to (default: 127.0.0.1). 0.0.0.0 makes "
            "the dashboard reachable from the network with no authentication; "
            "a warning is printed when a non-loopback host is chosen."
        ),
```

- [ ] **Step 5: Run the tests**

Run: `conda run -n nf-core python -m pytest tests/test_network_posture.py -q`
Expected: pass.

- [ ] **Step 6: Document the posture**

In `docs/user-guide.md`, after the "Install from source" block (line 42),
add:

```markdown
### Network exposure

The dashboard listens on `127.0.0.1` and is reachable only from the machine
it runs on. It has no user accounts or authentication. Starting it with
`--host 0.0.0.0` makes it reachable from the network, and anyone who can
reach the port can start and stop runs, change the configuration and read
results; the application prints a warning when a non-loopback host is
chosen. For a shared laboratory server, place an authenticating reverse
proxy (for example nginx with client certificates or basic authentication)
in front of it and keep the application itself on loopback.
```

In `docs/OPERATOR_GUIDE.md`, under "### General" (line 203), add the bullet:

```markdown
- Leave the dashboard on its default address. It has no login; if it must
  be reached from another computer, ask your IT contact for an
  authenticating proxy rather than starting it with `--host 0.0.0.0`.
```

- [ ] **Step 7: Full suite and commit**

Run: `conda run -n nf-core python -m pytest -q`
Expected: pass.

```bash
git add nanometa_live/app/utils/network_posture.py nanometa_live/app/__main__.py \
        nanometa_live/nanometa_live.py tests/test_network_posture.py \
        docs/user-guide.md docs/OPERATOR_GUIDE.md
git commit -m "feat(server): say what a non-loopback bind exposes

The dashboard has no authentication. On 127.0.0.1 that is the intended
single-user posture; on 0.0.0.0 it is an unauthenticated control surface,
and nothing said so. The server now prints the exposure when a reachable
host is chosen, and the guides describe the reverse-proxy pattern.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
```

---

### Task 7: Close out

- [ ] **Step 1: Changelog**

Under `## [Unreleased]` in `CHANGELOG.md`, ensure these entries exist:

```markdown
### Added

- Start Analysis refuses a nanometanf checkout below 1.10.0 by name, and the
  readiness checklist reports the pipeline version.
- A README compatibility table pairing each GUI release with its nanometanf
  and Nextflow floor, fenced by a test against the code's own floor.
- Releases build and upload to PyPI through trusted publishing.
- `docs/decisions/`: ten decision records, and `CONTRIBUTING.md`.
- The server prints what is exposed when bound to a non-loopback host.

### Changed

- CI executes an imported singularity bundle on an amd64 runner, so amd64
  execution of a bundled image is observed rather than assumed.
- The user guide's prerequisites name Python 3.11 and Nextflow 26.04.0.
```

- [ ] **Step 2: Push and confirm CI**

```bash
git push origin dev
gh run list --branch dev --limit 6
```

Expected: tests, version check, link check and bundle-deploy green.

- [ ] **Step 3: Owner actions collected**

These are outside the repository and are listed here so none is lost:

1. Post the issue 69 reply and close the issue (Task 4, Step 3).
2. Register the PyPI trusted publisher and the `pypi` GitHub environment
   (Task 3, Step 11).
3. Open the bioconda pull request with `docs/distribution/bioconda-0.18.0-meta.yaml`
   (Task 3, Step 11).
4. Name and onboard a second maintainer (Task 5, Step 10).
5. Not planned here, from the SWOT's opportunities: a v2 application note
   and a short paper on the live-drill audit method. Both are writing tasks
   whose material is `docs/audit/` and `docs/known-untested-surface.md`.

---

### Task 8: The imported config names the field machine's installation root

**Why.** The first recorded run of the cross-machine bundle workflow (run
33947378546, 2026-09-05; the job had never run before) failed its import
assertion with:

```
Imported installation is not usable:
  - config.yaml: nanometa_home points at /home/runner/work/_temp/nanometa_home, which does not exist on this machine
  - config.yaml: data_dir points at /home/runner/.nanometa, which does not exist on this machine
  - config.yaml: genome_cache_dir points at /home/runner/.nanometa, which does not exist on this machine
```

`import_bundle` rebases `kraken_db`, `pipeline_source`, `nxf_plugins_dir` and
the conda and singularity cache dirs, but not the installation root keys.
`NanometaPaths.from_config` (`core/utils/paths.py:85`) prefers
`config["data_dir"]` over the environment, and `get_genome_manager` reads
`genome_cache_dir`, so a field installation started from the imported config
runs against the build machine's root, which does not exist there. The
`--data-dir` re-pointing in `nanometa_live/nanometa_live.py:228-246` shows the
same rule applied at the CLI; the import must apply it too.

**Files:**
- Modify: `nanometa_live/core/workflow/bundle_manager.py`, the config-rebase
  block in `import_bundle` that begins `cfg["offline_mode"] = True` (around
  line 2088). The block already writes `cfg` back to `home / "config.yaml"`
  at its end; add the new assignments beside the `offline_mode` one so the
  existing write persists them.
- Test: `tests/test_bundle_manager.py` (new class, appended)
- Modify: `docs/known-untested-surface.md` (the paragraph at line 137 that
  begins "The cross-machine bundle CI job"), `CLAUDE.md` (the "An import
  must not report success over a problem it found" list under Offline
  Deployment), `CHANGELOG.md` (`## [Unreleased]`, a `### Fixed` entry).
- Modify: `docs/superpowers/plans/2026-09-04-swot-followup.md`: append this
  task's text (this brief, from its heading down to the end of Step 6) after
  Task 7 so the plan on record matches what was executed.

**Interfaces:** none new. `import_bundle(bundle_path, kraken_db_path, nanometa_home=None, force=False)` is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bundle_manager.py` (it already imports `BundleManager`
and defines `_make_minimal_bundle`; construct the manager as the existing
tests do, `BundleManager()`):

```python
class TestImportRebasesInstallationRoot:
    """The imported config must name THIS machine's root, not the build machine's.

    Observed on the first run of the cross-machine CI job (run 33947378546):
    after import, data_dir and genome_cache_dir still pointed at
    /home/runner/.nanometa and nanometa_home at the exporter's temp dir.
    NanometaPaths prefers config["data_dir"] over the environment, so the
    field installation would have run against a directory that does not
    exist there.
    """

    def _import(self, tmp_path, config_text):
        bundle_path, _ = _make_minimal_bundle(
            tmp_path, extra_files={"config.yaml": config_text}
        )
        home = tmp_path / "field_home"
        result = BundleManager().import_bundle(
            str(bundle_path), kraken_db_path="", nanometa_home=str(home)
        )
        assert result["success"], result
        import yaml
        return home, yaml.safe_load((home / "config.yaml").read_text())

    def test_root_keys_are_rebased_onto_the_import_home(self, tmp_path):
        foreign = "/home/builder/.nanometa"
        home, cfg = self._import(
            tmp_path,
            f"nanometa_home: {foreign}\n"
            f"data_dir: {foreign}\n"
            f"genome_cache_dir: {foreign}\n"
            "kraken_db: ''\n",
        )
        for key in ("nanometa_home", "data_dir", "genome_cache_dir"):
            assert cfg[key] == str(home), (key, cfg[key])

    def test_absent_nanometa_home_is_not_invented(self, tmp_path):
        home, cfg = self._import(tmp_path, "kraken_db: ''\n")
        assert "nanometa_home" not in cfg
        assert cfg["data_dir"] == str(home)
        assert cfg["genome_cache_dir"] == str(home)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `conda run -n nf-core python -m pytest tests/test_bundle_manager.py -k RebasesInstallationRoot -q`
Expected: both FAIL on the `data_dir` (and `nanometa_home`) equality: the values are the build machine's paths.

- [ ] **Step 3: Rebase the root keys**

Directly after `cfg["offline_mode"] = True` in the rebase block, add:

```python
                    # The bundle's config was written on the build machine
                    # and names that machine's installation root.
                    # NanometaPaths prefers config["data_dir"] over the
                    # environment and the genome manager reads
                    # genome_cache_dir, so an imported config that still
                    # carries the build root points the field installation
                    # at a directory that does not exist there (first run of
                    # the cross-machine CI job, 33947378546). The restored
                    # genomes/ and watchlists/ live under this home.
                    cfg["data_dir"] = str(home)
                    cfg["genome_cache_dir"] = str(home)
                    if "nanometa_home" in cfg:
                        cfg["nanometa_home"] = str(home)
```

- [ ] **Step 4: Run the tests**

Run: `conda run -n nf-core python -m pytest tests/test_bundle_manager.py -q`
Expected: all pass, including the two new ones. Then the full suite once:
`conda run -n nf-core python -m pytest -q`.

- [ ] **Step 5: Documents**

In `docs/known-untested-surface.md`, replace the paragraph beginning "The
cross-machine bundle CI job (`.github/workflows/bundle-deploy.yml`)" so it
reads:

```
The cross-machine bundle CI job (`.github/workflows/bundle-deploy.yml`)
deliberately passes `--no-pre-warm`, so it proves the bundle transfers and
imports, and proves nothing about pre-warmed environments. Its first
recorded run was 2026-09-05 (it had been gated on pull requests touching
files that no pull request changed), and that run failed its own
assertion: the imported config still named the build machine's `data_dir`,
`genome_cache_dir` and `nanometa_home`. The import now rebases those keys
onto the field installation's root; the job is green from the fix commit
onward.
```

In `CLAUDE.md`, under "An import must not report success over a problem it
found", add a fourth bullet:

```
   - The rebased config names the field machine's root: `data_dir`,
     `genome_cache_dir` and (when present) `nanometa_home` are set to the
     import home beside `offline_mode`. `NanometaPaths` prefers the config's
     `data_dir` over the environment, so without this an imported
     installation ran against the build machine's root (first run of the
     cross-machine CI job, 2026-09-05).
```

In `CHANGELOG.md` under `## [Unreleased]`, add:

```
### Fixed

- A bundle import rebases `data_dir`, `genome_cache_dir` and `nanometa_home`
  onto the field installation, so the imported configuration no longer
  points at the build machine's directories.
```

Append this task's text to the plan file as described under Files.

- [ ] **Step 6: Commit, push the feature branch, confirm all four CI jobs green**

```bash
git add nanometa_live/core/workflow/bundle_manager.py tests/test_bundle_manager.py \
        docs/known-untested-surface.md CLAUDE.md CHANGELOG.md \
        docs/superpowers/plans/2026-09-04-swot-followup.md
git commit -m "fix(bundle): the imported config names the field machine's root

The first run of the cross-machine CI job showed the imported config still
carrying the build machine's data_dir, genome_cache_dir and nanometa_home.
NanometaPaths prefers the config's data_dir over the environment, so a field
installation would have run against a directory that does not exist there.
The import now sets those keys to the import home beside offline_mode.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RP2QKAewMS3LgFLh6ynjBW"
git push origin swot-followup
gh workflow run bundle-deploy.yml --ref swot-followup
```

Then `gh run watch <id> --exit-status` on the new run. Expected: export,
import, export-singularity and run-singularity all green. Record the run id
in the report.

---

## Self-review

**Spec coverage.** SWOT moves 1 through 7 map to Tasks 1, 2, 3, 4, 5, and
6 (the papers, move 6 in the SWOT, are an owner action in Task 7 because a
paper is not an implementation task). Weakness "bioconda lags" is Task 3
Step 9 and 11; "pip install nanometa-live does not exist" is Task 3 Steps 6
to 8 and 11.

**Placeholders.** Every code step carries its code; the two dates to fill
in (Task 2 Step 7) are the date of a CI run that has not happened yet, which
is the one value the plan cannot know.

**Type consistency.** `check_pipeline_compatibility` returns `CompatVerdict`
with `status`, `found_version`, `checkout`, `message` in Task 1 and is read
with exactly those names in the readiness check, the launcher and the
tests. `NANOMETANF_MIN_VERSION` is imported by name in Task 3's fence test.
`exposure_warning` and `LOOPBACK_HOSTS` are the only names Task 6's tests
import.
