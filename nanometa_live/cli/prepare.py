"""
CLI entry point for offline deployment preparation.

Provides six subcommands:
  doctor  - Config-free sanity check of a fresh install (Nextflow, conda, pipeline).
  deploy  - Run full MobileLabPreparer pipeline with console progress.
  check   - Run ReadinessChecker only, print pass/fail table.
  export  - Export an offline bundle from a prepared ~/.nanometa.
  verify  - Check a bundle without installing anything.
  import  - Import a portable bundle via BundleManager.
"""

import argparse
import os
import shutil
import subprocess
import sys
import textwrap

_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _progress_bar(pct, width=30):
    filled = int(width * pct / 100)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {pct:5.1f}%"


def _ensure_data_dirs(args):
    """Create the per-installation directory layout.

    Previously only ``app.py`` called ``ensure_dirs()``, so on an install
    where the GUI had never been launched every CLI subcommand operated on
    directories that did not exist -- ``check`` in particular reported
    CRITICAL failures whose real cause was "the GUI was never started".
    Called for every subcommand; it is idempotent.
    """
    from nanometa_live.core.utils.paths import NanometaPaths

    home = getattr(args, "home", None)
    try:
        if home:
            paths = NanometaPaths.from_data_dir(home)
        else:
            from nanometa_live.core.utils.paths import get_data_dir_from_env
            paths = NanometaPaths.from_data_dir(get_data_dir_from_env())
        paths.ensure_dirs()
    except OSError as e:
        print(
            f"{_YELLOW}Could not create the Nanometa data directories: {e}"
            f"{_RESET}",
            file=sys.stderr,
        )


def _deploy(args):
    """Run full preparation pipeline."""
    import yaml
    from nanometa_live.core.workflow.mobile_lab_preparer import MobileLabPreparer

    config_path = args.config
    if not os.path.exists(config_path):
        print(f"{_RED}Config file not found: {config_path}{_RESET}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    # Override kraken_db if provided
    if args.db:
        config["kraken_db"] = args.db

    # Override watchlists if provided
    if args.watchlists:
        config["watchlists"] = args.watchlists.split(",")

    print(f"{_BOLD}Nanometa Live - Offline Deployment Preparation{_RESET}")
    print(f"{_DIM}Config: {config_path}{_RESET}")
    if args.db:
        print(f"{_DIM}Kraken2 DB: {args.db}{_RESET}")
    print()

    def progress_callback(progress):
        stage_bar = _progress_bar(progress.stage_progress, 20)
        detail = progress.stage_detail or ""
        # Clear line and print in-place
        sys.stdout.write(
            f"\r{_CYAN}[{progress.stage_index + 1}/{progress.total_stages}]{_RESET} "
            f"{progress.stage_label}  {stage_bar}  "
            f"{_DIM}{detail[:40]:<40}{_RESET}"
        )
        sys.stdout.flush()

    nanometa_home = args.home or None
    preparer = MobileLabPreparer(
        config=config,
        nanometa_home=nanometa_home,
        progress_callback=progress_callback,
    )

    skip = not args.no_skip
    result = preparer.prepare(skip_existing=skip)
    print()  # newline after progress
    print()

    # Summary
    if result.success:
        print(f"{_GREEN}{_BOLD}Preparation completed.{_RESET}")
    else:
        print(f"{_RED}{_BOLD}Preparation failed.{_RESET}")

    if result.stages_completed:
        print(f"  Stages completed: {', '.join(result.stages_completed)}")
    if result.stages_failed:
        print(f"  {_RED}Stages failed: {', '.join(result.stages_failed)}{_RESET}")
    if result.genomes_downloaded:
        print(f"  Genomes downloaded: {result.genomes_downloaded}")
    # Total ready = built this run + already present (the genome manager
    # auto-builds DBs on scan, so blast_dbs_built alone understates readiness).
    blast_ready = result.blast_dbs_built + result.blast_dbs_present
    if blast_ready:
        detail = ""
        if result.blast_dbs_present:
            detail = (f" ({result.blast_dbs_built} built now, "
                      f"{result.blast_dbs_present} already present)")
        print(f"  BLAST DBs ready: {blast_ready}{detail}")
    if result.blast_dbs_failed:
        print(f"  {_YELLOW}BLAST DBs failed: {len(result.blast_dbs_failed)}{_RESET}")
    if result.warnings:
        print(f"\n{_YELLOW}Warnings:{_RESET}")
        for w in result.warnings:
            print(f"  - {w}")
    if result.errors:
        print(f"\n{_RED}Errors:{_RESET}")
        for e in result.errors:
            print(f"  - {e}")

    # Export bundle if output path given
    if args.output and result.success:
        print(f"\n{_CYAN}Exporting bundle to {args.output}...{_RESET}")
        from nanometa_live.core.workflow.bundle_manager import BundleManager
        bm = BundleManager()
        path = bm.export_bundle(args.output, config, nanometa_home)
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"{_GREEN}Bundle exported: {path} ({size_mb:.1f} MB){_RESET}")

    sys.exit(0 if result.success else 1)


def _check(args):
    """Run readiness check only."""
    import yaml
    from nanometa_live.core.workflow.readiness_checker import (
        ReadinessChecker,
        Severity,
    )

    config_path = args.config
    if not os.path.exists(config_path):
        print(f"{_RED}Config file not found: {config_path}{_RESET}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    if args.db:
        config["kraken_db"] = args.db

    print(f"{_BOLD}Nanometa Live - Readiness Check{_RESET}")
    print()

    checker = ReadinessChecker()
    nanometa_home = args.home or None
    report = checker.check_readiness(config, nanometa_home)

    # Print table
    severity_icons = {
        Severity.CRITICAL: f"{_RED}CRIT{_RESET}",
        Severity.WARNING: f"{_YELLOW}WARN{_RESET}",
        Severity.INFO: f"{_DIM}INFO{_RESET}",
    }

    for check in report.checks:
        icon = severity_icons.get(check.severity, "    ")
        if check.passed:
            status = f"{_GREEN}PASS{_RESET}"
        else:
            status = f"{_RED}FAIL{_RESET}"
        print(f"  {icon}  {status}  {check.name:<25} {check.message}")
        if check.details and not check.passed:
            print(f"              {_DIM}{check.details}{_RESET}")

    summary = report.summary()
    print()
    print(
        f"  {summary['passed']}/{summary['total']} checks passed, "
        f"{summary['critical_failures']} critical failures, "
        f"{summary['warnings']} warnings"
    )

    if report.ready:
        print(f"\n{_GREEN}{_BOLD}System is ready for offline operation.{_RESET}")
    else:
        print(f"\n{_RED}{_BOLD}System is NOT ready. Resolve critical failures above.{_RESET}")

    sys.exit(0 if report.ready else 1)


def _export(args):
    """Export an offline bundle from an already-prepared ~/.nanometa.

    Mirrors the GUI Preparation tab's Export Bundle action without running
    the preparer first. Use this when ~/.nanometa already contains downloaded
    genomes, BLAST DBs, mappings, and watchlists from a prior deploy.
    """
    import platform
    import yaml
    from nanometa_live.core.workflow.bundle_manager import BundleManager

    if not os.path.exists(args.config):
        print(f"{_RED}Config file not found: {args.config}{_RESET}", file=sys.stderr)
        sys.exit(1)

    with open(args.config) as f:
        config = yaml.safe_load(f) or {}

    if args.db:
        config["kraken_db"] = args.db

    pre_warm = bool(args.pre_warm) and not bool(args.no_pre_warm)
    containerization = args.containerization or "conda"

    pipeline_path = args.pipeline
    if pipeline_path is None:
        # Fall back to a local pipeline_source from the config, but only
        # if it resolves to a directory that contains main.nf.
        pipeline_source = config.get("pipeline_source", "")
        if (
            isinstance(pipeline_source, str)
            and not pipeline_source.startswith(("remote:", "https://", "git@"))
            and os.path.isdir(pipeline_source)
        ):
            pipeline_path = pipeline_source

    needs_pipeline = (
        (containerization == "conda" and pre_warm)
        or containerization in ("docker", "singularity")
    )
    if needs_pipeline and not pipeline_path:
        print(
            f"{_RED}--containerization {containerization} requires "
            f"--pipeline pointing to a local nanometanf checkout "
            f"(config.pipeline_source did not resolve to a local "
            f"directory).{_RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"{_BOLD}Nanometa Live - Export Offline Bundle{_RESET}")
    print(f"  Output: {args.output}")
    print(f"  Containerization: {containerization}")
    if containerization == "conda":
        print(f"  Pre-warm conda envs: {'YES' if pre_warm else 'no'}")
        if pre_warm:
            print(
                f"  {_YELLOW}Build platform: {platform.system()} "
                f"{platform.machine()}. Field machine must match.{_RESET}"
            )
    elif containerization == "docker":
        print(
            f"  {_CYAN}Docker mode: pulls + saves linux/amd64 images. "
            f"Field machine needs Docker installed.{_RESET}"
        )
    elif containerization == "singularity":
        print(
            f"  {_CYAN}Singularity mode: pulls .sif files. "
            f"Field machine must be Linux with Apptainer/Singularity.{_RESET}"
        )
    if pipeline_path:
        print(f"  Pipeline source: {pipeline_path}")
    print()

    bm = BundleManager()
    nanometa_home = args.home or None
    path = bm.export_bundle(
        args.output,
        config,
        nanometa_home=nanometa_home,
        pre_warm_conda_envs=pre_warm,
        pipeline_path=pipeline_path,
        containerization=containerization,
    )
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"{_GREEN}Bundle exported: {path} ({size_mb:.1f} MB){_RESET}")
    sys.exit(0)


def _verify(args):
    """Verify a bundle without installing anything.

    ``import`` is the only other code path that checks a bundle, and it
    writes as it goes; an operator with a USB copy of a multi-GB bundle
    could not confirm the transfer before committing the field machine to
    it. Shares one implementation with the import path
    (``BundleManager._verify_extracted_bundle``) so the dry run cannot
    disagree with the real thing.
    """
    from nanometa_live.core.workflow.bundle_manager import BundleManager

    if not os.path.exists(args.bundle):
        print(f"{_RED}Bundle not found: {args.bundle}{_RESET}", file=sys.stderr)
        sys.exit(1)

    print(f"{_BOLD}Nanometa Live - Verify Bundle{_RESET}")
    print(f"  Bundle: {args.bundle}")
    if args.db:
        print(f"  Kraken2 DB: {args.db}")
    print(f"{_DIM}  Read-only: nothing on this machine is modified.{_RESET}")
    print()

    result = BundleManager().verify_bundle(args.bundle, kraken_db_path=args.db)

    manifest = result.get("manifest", {})
    if manifest:
        print(f"  Created:        {manifest.get('created', 'unknown')}")
        print(f"  Built by:       {manifest.get('creator', 'unknown')}")
        plat = manifest.get("build_platform", {})
        if plat:
            print(
                f"  Build platform: {plat.get('system', '?')}/"
                f"{plat.get('machine', '?')}"
            )
        print(f"  Files:          {len(manifest.get('checksums', {}))}")
        mode = manifest.get("containerization", {}).get("mode")
        if mode:
            print(f"  Containerization: {mode}")
        print()

    mismatches = result.get("checksum_mismatches") or []
    if mismatches:
        print(f"{_RED}Checksum failures ({len(mismatches)}):{_RESET}")
        for m in mismatches[:20]:
            print(f"  - {m}")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more")
        print()

    if result.get("warnings"):
        print(f"{_YELLOW}Warnings:{_RESET}")
        for w in result["warnings"]:
            print(f"  - {w}")
        print()

    if result["success"]:
        print(f"{_GREEN}{_BOLD}Bundle verified. Safe to import.{_RESET}")
    else:
        print(f"{_RED}{_BOLD}Bundle verification FAILED. Do not import "
              f"without --force.{_RESET}")

    sys.exit(0 if result["success"] else 1)


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
    _doctor_check_data_dirs(args, report)
    _doctor_summarise(problems)


def _doctor_check_toolchain(report):
    """Python and Nextflow, both hard requirements for a run."""
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
        ok = bool(local_t and floor_t and local_t >= floor_t)
        report(
            "Nextflow", ok, nf_version,
            f"nanometanf requires Nextflow >= {_NEXTFLOW_MIN_VERSION}. "
            "Update it before launching a run.",
        )

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


def _import_bundle(args):
    """Import a portable bundle."""
    from nanometa_live.core.workflow.bundle_manager import BundleManager

    bundle_path = args.bundle
    if not os.path.exists(bundle_path):
        print(f"{_RED}Bundle not found: {bundle_path}{_RESET}", file=sys.stderr)
        sys.exit(1)

    if not args.db:
        print(f"{_RED}--db is required for import (local Kraken2 DB path){_RESET}", file=sys.stderr)
        sys.exit(1)

    print(f"{_BOLD}Nanometa Live - Import Bundle{_RESET}")
    print(f"  Bundle: {bundle_path}")
    print(f"  Kraken2 DB: {args.db}")
    print()

    bm = BundleManager()
    result = bm.import_bundle(bundle_path, args.db, args.home)

    if result["success"]:
        print(f"{_GREEN}Bundle imported.{_RESET}")
    else:
        print(f"{_RED}Import failed.{_RESET}")

    if result.get("warnings"):
        print(f"\n{_YELLOW}Warnings:{_RESET}")
        for w in result["warnings"]:
            print(f"  - {w}")

    manifest = result.get("manifest", {})
    if manifest:
        print(f"\n{_DIM}Bundle created: {manifest.get('created', 'unknown')}{_RESET}")
        checksums = manifest.get("checksums", {})
        print(f"{_DIM}Files in bundle: {len(checksums)}{_RESET}")

    sys.exit(0 if result["success"] else 1)


def main():
    parser = argparse.ArgumentParser(
        prog="nanometa-prepare",
        description="Prepare Nanometa Live for offline/mobile lab deployment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              nanometa-prepare doctor
              nanometa-prepare doctor --pipeline /path/to/nanometanf
              nanometa-prepare deploy --config config.yaml --db /data/kraken2_db
              nanometa-prepare deploy --config config.yaml --output bundle.tar.gz
              nanometa-prepare check --config config.yaml --db /data/kraken2_db
              nanometa-prepare export --config config.yaml --output bundle.tar.gz \\
                  --pre-warm --pipeline /path/to/nanometanf
              nanometa-prepare verify --bundle bundle.tar.gz
              nanometa-prepare import --bundle bundle.tar.gz --db /data/kraken2_db
        """),
    )

    parser.add_argument(
        "--home", default=None,
        help="Nanometa home directory (default: ~/.nanometa)",
    )
    # The version_check CI workflow invokes `nanometa-prepare --version`;
    # without this flag argparse exits 2 on an unrecognised argument.
    from nanometa_live import __version__
    parser.add_argument(
        "--version", action="version",
        version=f"nanometa-prepare {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # doctor
    doctor_p = subparsers.add_parser(
        "doctor",
        help="Config-free sanity check of a fresh install",
    )
    doctor_p.add_argument(
        "--pipeline", default=None,
        help="Optional path to a local nanometanf checkout to verify",
    )
    doctor_p.set_defaults(func=_doctor)

    # deploy
    deploy_p = subparsers.add_parser(
        "deploy",
        help="Run full preparation pipeline",
    )
    deploy_p.add_argument(
        "--config", "-c", required=True,
        help="Path to Nanometa Live config.yaml",
    )
    deploy_p.add_argument(
        "--db", default=None,
        help="Override Kraken2 database path from config",
    )
    deploy_p.add_argument(
        "--watchlists", "-w", default=None,
        help="Comma-separated watchlist names to enable",
    )
    deploy_p.add_argument(
        "--output", "-o", default=None,
        help="Export bundle to this path after preparation",
    )
    deploy_p.add_argument(
        "--no-skip", action="store_true",
        help="Re-run all steps even if already completed",
    )
    deploy_p.set_defaults(func=_deploy)

    # check
    check_p = subparsers.add_parser(
        "check",
        help="Run readiness check only",
    )
    check_p.add_argument(
        "--config", "-c", required=True,
        help="Path to Nanometa Live config.yaml",
    )
    check_p.add_argument(
        "--db", default=None,
        help="Override Kraken2 database path from config",
    )
    check_p.set_defaults(func=_check)

    # export
    export_p = subparsers.add_parser(
        "export",
        help="Export offline bundle from a prepared ~/.nanometa",
    )
    export_p.add_argument(
        "--config", "-c", required=True,
        help="Path to Nanometa Live config.yaml",
    )
    export_p.add_argument(
        "--output", "-o", required=True,
        help="Output bundle path (e.g. bundle.tar.gz)",
    )
    export_p.add_argument(
        "--db", default=None,
        help="Override Kraken2 database path from config",
    )
    export_p.add_argument(
        "--pipeline", default=None,
        help="Path to local nanometanf checkout (required for --pre-warm)",
    )
    export_p.add_argument(
        "--pre-warm", action="store_true", default=True,
        help="Pre-warm conda environments (conda mode only; default: on; "
             "build/field machines must match OS+CPU)",
    )
    export_p.add_argument(
        "--no-pre-warm", action="store_true", default=False,
        help="Disable pre-warming for cross-platform conda deployment",
    )
    export_p.add_argument(
        "--containerization", choices=["conda", "docker", "singularity"],
        default="conda",
        help="Offline-deployment engine. ``conda`` ships pre-warmed envs "
             "(this OS+arch only). ``docker`` ships pre-pulled images "
             "(cross-platform). ``singularity`` ships .sif files "
             "(Linux-only, rootless). Default: conda.",
    )
    export_p.set_defaults(func=_export)

    # verify
    verify_p = subparsers.add_parser(
        "verify",
        help="Verify a bundle without installing anything",
    )
    verify_p.add_argument(
        "--bundle", "-b", required=True,
        help="Path to the bundle tar.gz file",
    )
    verify_p.add_argument(
        "--db", default=None,
        help="Optional local Kraken2 database, to check the bundle's DB hash",
    )
    verify_p.set_defaults(func=_verify)

    # import
    import_p = subparsers.add_parser(
        "import",
        help="Import a portable bundle",
    )
    import_p.add_argument(
        "--bundle", "-b", required=True,
        help="Path to the bundle tar.gz file",
    )
    import_p.add_argument(
        "--db", required=True,
        help="Path to local Kraken2 database",
    )
    import_p.set_defaults(func=_import_bundle)

    args = parser.parse_args()
    # `verify` is the one subcommand that must not touch this machine.
    if args.command != "verify":
        _ensure_data_dirs(args)
    args.func(args)


if __name__ == "__main__":
    main()
