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

# Re-exported so callers (and tests) can keep patching prepare._verify; the
# implementation moved to verify_bundle_cmd for the file-size ratchet.
from nanometa_live.cli.verify_bundle_cmd import _verify  # noqa: E402,F401
from pathlib import Path

# Doctor lives in its own module (code-size gate); prepare re-exports what
# its tests and the dispatch table use.
from nanometa_live.cli.doctor import (  # noqa: E402,F401
    _BOLD, _CYAN, _DIM, _GREEN, _RED, _RESET, _YELLOW,
    _doctor, _doctor_check_nf_schema_plugin, _java_runtime_available,
    default_pipeline_checkout, nextflow_runtime_cached, nf_schema_pin,
    nf_schema_plugin_status,
)


def _print_export_outcome(export_result):
    """Report an export's outcome, surfacing its warnings.

    A bundle can be produced successfully while still being incomplete
    (skipped container pull, failed pre-warm); unconditional green here
    is what hid those from the operator (2026-08-27 audit).
    """
    path = export_result.path
    size_mb = path.stat().st_size / (1024 * 1024)
    if export_result.warnings:
        print(
            f"{_YELLOW}Bundle exported WITH WARNINGS: {path} "
            f"({size_mb:.1f} MB){_RESET}"
        )
        for w in export_result.warnings:
            print(f"{_YELLOW}  - {w}{_RESET}")
        print(
            f"{_YELLOW}The bundle may be incomplete -- review the warnings "
            f"before shipping it to the field.{_RESET}"
        )
    else:
        print(f"{_GREEN}Bundle exported: {path} ({size_mb:.1f} MB){_RESET}")


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
        export_result = bm.export_bundle(args.output, config, nanometa_home)
        _print_export_outcome(export_result)

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

    from nanometa_live.core.workflow.bundle_manager import (
        _DEFAULT_TARGET_PLATFORM,
    )
    target_platform = (
        getattr(args, "target_platform", None) or _DEFAULT_TARGET_PLATFORM
    )

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
            f"  {_CYAN}Docker mode: pulls + saves {target_platform} images. "
            f"Field machine needs Docker installed.{_RESET}"
        )
    elif containerization == "singularity":
        print(
            f"  {_CYAN}Singularity mode: pulls {target_platform} .sif files. "
            f"Field machine must be Linux with Apptainer/Singularity.{_RESET}"
        )
    if pipeline_path:
        print(f"  Pipeline source: {pipeline_path}")
    print()

    bm = BundleManager()
    nanometa_home = args.home or None
    export_result = bm.export_bundle(
        args.output,
        config,
        nanometa_home=nanometa_home,
        pre_warm_conda_envs=pre_warm,
        pipeline_path=pipeline_path,
        containerization=containerization,
        target_platform=target_platform,
    )
    _print_export_outcome(export_result)
    sys.exit(0)


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
    result = bm.import_bundle(
        bundle_path, args.db, args.home,
        force=getattr(args, "force", False),
    )

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
    export_p.add_argument(
        "--target-platform", default=None,
        help="OCI platform to pull container images for, e.g. linux/amd64 "
             "(default) or linux/arm64. This describes the FIELD machine, not "
             "this one: docker and apptainer otherwise pull for the build "
             "host, so an Apple Silicon laptop silently produces arm64 images "
             "that cannot run on an x86_64 field machine. Ignored in conda "
             "mode.",
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
    import_p.add_argument(
        "--force", action="store_true",
        help=(
            "Proceed past non-fatal verification blockers (checksum "
            "mismatches, unsupported manifest version). The escape hatch "
            "that `verify` refers to; without it a failed verification "
            "aborts the import."
        ),
    )
    import_p.set_defaults(func=_import_bundle)

    args = parser.parse_args()
    # `verify` is the one subcommand that must not touch this machine.
    if args.command != "verify":
        _ensure_data_dirs(args)
    args.func(args)


if __name__ == "__main__":
    main()
