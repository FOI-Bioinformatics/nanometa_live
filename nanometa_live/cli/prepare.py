"""
CLI entry point for offline deployment preparation.

Provides three subcommands:
  deploy  - Run full MobileLabPreparer pipeline with console progress.
  check   - Run ReadinessChecker only, print pass/fail table.
  import  - Import a portable bundle via BundleManager.
"""

import argparse
import os
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
        overall_bar = _progress_bar(progress.overall_progress)
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
    if result.blast_dbs_built:
        print(f"  BLAST DBs built: {result.blast_dbs_built}")
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
              nanometa-prepare deploy --config config.yaml --db /data/kraken2_db
              nanometa-prepare deploy --config config.yaml --output bundle.tar.gz
              nanometa-prepare check --config config.yaml --db /data/kraken2_db
              nanometa-prepare import --bundle bundle.tar.gz --db /data/kraken2_db
        """),
    )

    parser.add_argument(
        "--home", default=None,
        help="Nanometa home directory (default: ~/.nanometa)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

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
    args.func(args)


if __name__ == "__main__":
    main()
