"""CLI: generate the operator HTML report from a nanometanf results directory.

Runs the same self-contained report the dashboard exports -- classification,
pathogen screening + verdict, validation confirmation, QC, alerts, and links to
the bundled MultiQC / Nextflow reports -- WITHOUT launching the dashboard or any
server. Point it at a ``nextflow run`` output directory.

  nanometa-report --results results/Nanometa_Live_Analysis
  nanometa-report -r <outdir> -o ~/report --watchlist cdc_bioterrorism --offline

Pathogen screening needs a watchlist: pass ``--watchlist <id>`` (a built-in id
such as cdc_bioterrorism, clinical_pathogens, ...) so the threat section
populates. Without it the report still covers classification / validation / QC,
just with an empty pathogen screen.
"""

import argparse
import os
import sys


def _resolve_watchlist_ids(arg_value, results_dir):
    """Watchlist ids to enable: the --watchlist argument, or the run record.

    ``--watchlist none`` forces an unscreened report even when the run
    recorded watchlists. With no argument, the ids the run recorded in
    ``.nanometa.run.json`` are used (and announced), so the post-hoc report
    reproduces the run's own screen.
    """
    if arg_value is not None:
        if arg_value.strip().lower() == "none":
            return []
        return [w.strip() for w in arg_value.split(",") if w.strip()]

    from nanometa_live.core.workflow.backend_manager import BackendManager
    meta = BackendManager.read_run_metadata(results_dir) or {}
    recorded = [w for w in (meta.get("watchlists") or []) if w]
    if recorded:
        print(
            "Using the watchlists recorded by the run: "
            + ", ".join(recorded)
            + " (override with --watchlist, or --watchlist none)"
        )
    return recorded


def main():
    parser = argparse.ArgumentParser(
        prog="nanometa-report",
        description="Generate the operator HTML report from a nanometanf results "
                    "directory (headless -- no dashboard).",
    )
    parser.add_argument("--results", "-r", required=True,
                        help="nanometanf results output directory (contains kraken2/, validation/, ...)")
    parser.add_argument("--output", "-o", default=None,
                        help="Directory to write the report bundle (default: <results>/report)")
    parser.add_argument("--config", "-c", default=None,
                        help="Optional config.yaml (analysis_name, offline_mode, ...)")
    parser.add_argument("--watchlist", "-w", default=None,
                        help="Comma-separated built-in watchlist id(s) to enable for "
                             "pathogen screening (e.g. cdc_bioterrorism). Default: the "
                             "watchlists recorded in the run's .nanometa.run.json, when "
                             "present. Pass 'none' to force an unscreened report.")
    parser.add_argument("--samples", default=None,
                        help="Comma-separated sample ids to include (default: all detected)")
    parser.add_argument("--offline", action="store_true",
                        help="Force a fully offline report (no plotly CDN fallback)")
    parser.add_argument("--no-raw", action="store_true",
                        help="Do not copy raw result files into the bundle")
    args = parser.parse_args()

    results = os.path.abspath(os.path.expanduser(args.results))
    if not os.path.isdir(results):
        print(f"Results directory not found: {results}", file=sys.stderr)
        sys.exit(1)

    config = {}
    if args.config:
        if not os.path.exists(args.config):
            print(f"Config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        import yaml
        with open(args.config) as f:
            config = yaml.safe_load(f) or {}
    if args.offline:
        config["offline_mode"] = True
    config.setdefault("analysis_name",
                      os.path.basename(results.rstrip("/")) or "Nanometa Report")

    # Enable watchlist(s) so the pathogen-screening section populates -- the
    # report screens get_active_entries() from the WatchlistManager singleton,
    # which is empty in a fresh process. When no --watchlist is given, fall
    # back to the ids the run recorded in .nanometa.run.json, so a post-hoc
    # report reproduces the run's own screen instead of silently rendering
    # NOT SCREENED (2026-08-17 storage audit, finding R2).
    watchlist_ids = _resolve_watchlist_ids(args.watchlist, results)
    if watchlist_ids:
        from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
        wm = get_watchlist_manager()
        for wl in watchlist_ids:
            try:
                wm.enable_watchlist(wl)
            except Exception as e:  # noqa: BLE001 -- surface, keep going
                print(f"Warning: could not enable watchlist '{wl}': {e}", file=sys.stderr)

    output = (os.path.abspath(os.path.expanduser(args.output))
              if args.output else os.path.join(results, "report"))
    samples = [s.strip() for s in args.samples.split(",")] if args.samples else None

    from nanometa_live.core.export.report_generator import ReportGenerator
    generator = ReportGenerator(results, config)
    report_path = generator.generate(output, samples=samples, include_raw=not args.no_raw)
    print(f"Report written: {report_path}")


if __name__ == "__main__":
    main()
