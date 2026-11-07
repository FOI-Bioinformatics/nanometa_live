"""`nanometa-prepare doctor`: the config-free check of a fresh install.

``check`` needs an existing ``--config``, so it cannot answer the first
question an operator has on a new machine: is the toolchain here at all?
This module checks only what is needed before any config exists -- Python,
Java, Nextflow and its floor, the launcher's runtime cache, the nf-schema
plugin the pipeline pins, conda and the container runtimes, the pipeline
checkout when one is named, and the data directories. Split out of
``prepare.py`` on 2026-10-29 when that file crossed the code-size gate.
"""

import os
import shutil
import sys
from pathlib import Path

_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _doctor(args):
    """Config-free sanity check of a fresh install.

    ``check`` needs an existing ``--config``, so it cannot answer the first
    question an operator has on a new machine: is the toolchain here at all?
    This checks only what is needed before any config exists.
    """
    print(f"{_BOLD}Nanometa Live - Install Doctor{_RESET}")
    print()

    problems = []

    def report(name, ok, message, hint=None, fatal=True):
        status = f"{_GREEN}PASS{_RESET}" if ok else (
            f"{_RED}FAIL{_RESET}" if fatal else f"{_YELLOW}WARN{_RESET}")
        print(f"  {status}  {name:<22} {message}")
        if not ok and hint:
            print(f"        {_DIM}{hint}{_RESET}")
        if not ok and fatal:
            problems.append(name)

    _doctor_check_toolchain(report)
    _doctor_check_runtimes(report)
    _doctor_check_pipeline(args, report)
    _doctor_check_nf_schema_plugin(args, report)
    _doctor_check_data_dirs(args, report)
    _doctor_summarise(problems)


def _java_runtime_available():
    """Whether a usable Java Runtime is present.

    Nextflow is a JVM application, so a laptop with the `nextflow` launcher
    on PATH but no JRE cannot run a single task. Installing Nextflow from a
    tarball, or as a bare conda package without its openjdk dependency,
    produces exactly that state -- and it is a common one on a fresh field
    machine.

    Returns ``(ok, detail)`` where detail is the reported version or the
    reason it could not be determined.
    """
    import subprocess

    java = shutil.which("java")
    if not java:
        return False, "not found on PATH"
    try:
        result = subprocess.run(
            ["java", "-version"], capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"could not run java -version ({exc})"

    # java -version writes to stderr by convention.
    first = _java_version_line(result.stderr + result.stdout)
    if result.returncode != 0:
        return False, first or f"java -version exited {result.returncode}"
    return True, first or java


def _java_version_line(output):
    """The line of ``java -version`` output that names the version.

    A JVM with ``JAVA_TOOL_OPTIONS`` set (proxy or trust-store settings on a
    managed machine) prints ``Picked up JAVA_TOOL_OPTIONS: ...`` first, so the
    first line is not reliably the version. Prefer the line containing
    ``version``; fall back to the first non-empty line.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if "version" in line.lower():
            return line
    return lines[0] if lines else ""


def _doctor_check_toolchain(report):
    """Python, Java and Nextflow -- all hard requirements for a run."""
    from nanometa_live.core.workflow.bundle_manager import (
        _NEXTFLOW_MIN_VERSION,
        _get_nextflow_version,
        _parse_semver,
    )

    py = sys.version_info
    report(
        "Python", py >= (3, 11),
        f"{py.major}.{py.minor}.{py.micro}",
        "Nanometa Live requires Python 3.11 or newer.",
    )

    # Java, checked before Nextflow because Nextflow cannot start without it
    # and its absence is otherwise reported as an unreadable Nextflow version.
    java_ok, java_detail = _java_runtime_available()
    report(
        "Java runtime", java_ok, java_detail,
        "Nextflow is a JVM application and cannot start without a Java "
        "Runtime. Install one, e.g. "
        "`conda install -c conda-forge openjdk`.",
    )

    # Nextflow, and its version floor.
    nf_version = _get_nextflow_version()
    nf_found = shutil.which("nextflow") is not None
    if not nf_found:
        report(
            "Nextflow", False, "not found on PATH",
            "The pipeline cannot run without it. Install with "
            "`conda install -c bioconda nextflow` "
            f"(>= {_NEXTFLOW_MIN_VERSION} required).",
        )
    else:
        local_t = _parse_semver(nf_version)
        floor_t = _parse_semver(_NEXTFLOW_MIN_VERSION)
        if local_t is None:
            # Unreadable output is a failure, not a pass. It usually means
            # Nextflow could not start at all -- most often no Java Runtime.
            report(
                "Nextflow", False,
                f"version not readable ({nf_version})",
                "`nextflow -version` did not report a version. If the Java "
                "check above also failed, fix that first; otherwise run "
                "`nextflow -version` by hand to see the error.",
            )
        else:
            ok = bool(floor_t and local_t >= floor_t)
            report(
                "Nextflow", ok, nf_version,
                f"nanometanf requires Nextflow >= {_NEXTFLOW_MIN_VERSION}. "
                "Update it before launching a run.",
            )
            cached, where = nextflow_runtime_cached(nf_version)
            report(
                "Nextflow runtime cache", cached, where,
                "The get.nextflow.io launcher downloads its runtime jar into "
                "NXF_HOME/framework/<version>/ when absent, and a Start into a "
                "new results folder uses a fresh NXF_HOME; NXF_OFFLINE does not "
                "stop that fetch. Run `nextflow -version` once while online so "
                "the jar is cached under ~/.nextflow (Start seeds per-run homes "
                "from it). A bioconda Nextflow ships its jar and needs nothing.",
                fatal=False,
            )

def nextflow_runtime_cached(nf_version, nxf_home=None):
    """Whether the launcher's runtime jar for ``nf_version`` is cached.

    ``nf_version`` is the "X.Y.Z build N" string ``_get_nextflow_version``
    returns. The get.nextflow.io launcher keeps the jar under
    ``$NXF_HOME/framework/<X.Y.Z>/``; a bioconda install keeps its jar
    beside the launcher and passes here through that directory instead.
    Returns ``(ok, detail)``.
    """
    import re as _re

    m = _re.match(r"(\d+\.\d+\.\d+[^\s]*)", (nf_version or "").strip())
    if not m:
        return False, "version unknown, cache not checked"
    version = m.group(1)
    home = Path(nxf_home or os.environ.get("NXF_HOME") or os.path.expanduser("~/.nextflow"))
    framework = home / "framework" / version
    if framework.is_dir() and any(framework.glob("*.jar")):
        return True, str(framework)
    launcher = shutil.which("nextflow")
    if launcher:
        beside = Path(launcher).resolve().parent.parent / "share" / "nextflow"
        if beside.is_dir() and any(beside.rglob("nextflow*.jar")):
            return True, f"{beside} (launcher ships its runtime)"
    return False, f"no runtime jar for {version} under {home / 'framework'}"


def _doctor_check_runtimes(report):
    """Conda and the container engines.

    Conda is a warning rather than a failure: it is only needed for the
    default profile, and a docker or singularity user legitimately has none.
    """
    conda = shutil.which("conda") or shutil.which("mamba")
    report(
        "conda/mamba", conda is not None, conda or "not found on PATH",
        "The default pipeline profile is conda. Install conda/mamba, or "
        "run with a docker or singularity profile.",
        fatal=False,
    )

    # Container runtimes are informational: only one is needed, and only
    # when the operator has chosen that profile.
    for tool in ("docker", "apptainer", "singularity"):
        path = shutil.which(tool)
        if path:
            print(f"  {_DIM}INFO{_RESET}  {tool:<22} {path}")

def _doctor_check_pipeline(args, report):
    """The local nanometanf checkout, when one was named."""
    if args.pipeline:
        main_nf = os.path.join(args.pipeline, "main.nf")
        report(
            "Pipeline checkout", os.path.isfile(main_nf),
            args.pipeline,
            "The path does not contain main.nf; point --pipeline at a "
            "nanometanf checkout.",
        )
    else:
        print(
            f"  {_DIM}INFO{_RESET}  {'Pipeline checkout':<22} "
            "not checked (pass --pipeline <path> to verify a local checkout)"
        )

_NF_SCHEMA_PIN_RE = r"id\s+['\"]nf-schema@([^'\"]+)['\"]"


def nf_schema_pin(pipeline_dir):
    """The nf-schema version a nanometanf checkout declares, or None.

    Read from ``plugins { id 'nf-schema@X.Y.Z' }`` in the checkout's
    ``nextflow.config``; None when the checkout or the line is absent.
    """
    import re

    cfg = os.path.join(str(pipeline_dir), "nextflow.config")
    try:
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            m = re.search(_NF_SCHEMA_PIN_RE, fh.read())
    except OSError:
        return None
    return m.group(1) if m else None


def default_pipeline_checkout():
    """Where ``nextflow pull foi-bioinformatics/nanometanf`` lands by default.

    ``NXF_ASSETS``, else ``$NXF_HOME/assets``, else ``~/.nextflow/assets``;
    None when no checkout with a ``nextflow.config`` is there.
    """
    assets = os.environ.get("NXF_ASSETS")
    if not assets:
        nxf_home = os.environ.get("NXF_HOME") or os.path.join(
            os.path.expanduser("~"), ".nextflow")
        assets = os.path.join(nxf_home, "assets")
    checkout = os.path.join(assets, "foi-bioinformatics", "nanometanf")
    return checkout if os.path.isfile(
        os.path.join(checkout, "nextflow.config")) else None


def nf_schema_plugin_status(pipeline_dir=None, plugins_home=None):
    """What the Nextflow plugin cache holds against what the pipeline pins.

    Returns ``(required, cached, plugins_home)``: ``required`` is the version
    the checkout pins (None when no checkout is known), ``cached`` the sorted
    nf-schema versions present under ``plugins_home`` (the directory the
    bundle exporter also reads: ``NXF_PLUGINS_DIR``, else ``$NXF_HOME/plugins``,
    else ``~/.nextflow/plugins``).
    """
    from nanometa_live.core.workflow.bundle_manager import _nextflow_plugins_home

    home = Path(plugins_home) if plugins_home else _nextflow_plugins_home()
    cached = []
    if home.is_dir():
        for entry in home.iterdir():
            if entry.is_dir() and entry.name.startswith("nf-schema-"):
                cached.append(entry.name[len("nf-schema-"):])
    required = nf_schema_pin(pipeline_dir) if pipeline_dir else None
    return required, sorted(cached), home


def _doctor_check_nf_schema_plugin(args, report):
    """The nf-schema plugin the pipeline pins must be in the plugin cache.

    nanometanf declares ``plugins { id 'nf-schema@X' }`` and Nextflow fetches
    that version from registry.nextflow.io when it is not cached. Two paths
    depend on the cache rather than the network: a GUI Start seeds its
    per-run NXF_HOME from ``~/.nextflow`` (plugins included), and a bundle
    export copies ``nf-schema-<X>`` from this directory into the bundle. A
    build machine without it ships an air-gapped bundle that fails at the
    registry probe. Non-fatal online; the hint is one command.
    """
    pipeline_dir = args.pipeline or default_pipeline_checkout()
    required, cached, home = nf_schema_plugin_status(pipeline_dir)
    cached_text = ", ".join(cached) if cached else "none"
    if required is None:
        print(
            f"  {_DIM}INFO{_RESET}  {'nf-schema plugin':<22} "
            f"pipeline pin not known (no checkout found); cached: {cached_text}"
        )
        return
    ok = required in cached
    report(
        "nf-schema plugin", ok,
        f"{required} required by {pipeline_dir}; cached: {cached_text}",
        f"Run `nextflow plugin install nf-schema@{required}` once while "
        f"online. The plugin lands under {home}; a Start seeds each run's "
        "NXF_HOME from there and a bundle export copies it, so without it an "
        "air-gapped machine reaches for registry.nextflow.io and fails.",
        fatal=False,
    )


def _doctor_check_data_dirs(args, report):
    """Report the data directories; _ensure_data_dirs already created them."""
    from nanometa_live.core.utils.paths import NanometaPaths, get_data_dir_from_env

    data_dir = args.home or get_data_dir_from_env()
    paths = NanometaPaths.from_data_dir(data_dir)
    report(
        "Data directories", paths.data_dir.is_dir(), str(paths.data_dir),
        "Could not create the data directory. Check permissions, or set "
        "--home to a writable location.",
    )

def _doctor_summarise(problems):
    """Print the verdict and exit non-zero on any fatal problem."""
    print()
    if problems:
        print(
            f"{_RED}{_BOLD}Install is not ready: {', '.join(problems)}."
            f"{_RESET}"
        )
        print(
            f"{_DIM}Next: fix the failures above, then "
            f"`nanometa-prepare check --config <config.yaml>` for a "
            f"run-specific check.{_RESET}"
        )
    else:
        print(f"{_GREEN}{_BOLD}Install looks sane.{_RESET}")
        print(
            f"{_DIM}Next: `nanometa-prepare check --config <config.yaml> "
            f"--db <kraken2_db>` to check a specific run.{_RESET}"
        )
    sys.exit(1 if problems else 0)
