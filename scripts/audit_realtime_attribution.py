#!/usr/bin/env python
"""Diagnostic probe for the per-sample attribution chain.

Prints one section per hop so a results directory can be diagnosed without a
browser:

  hop 1  which report files exist per sample, and which tier the loader picks
  hop 2  the aggregate frame's species taxids
  hop 3  the per-sample attribution dict (taxid -> samples)
  hop 4  watchlist detections and the samples each resolves to
  hop 5  the rendered "Triggered by" text

Usage:
    python scripts/audit_realtime_attribution.py <results_dir> [--config path.yaml]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tier_of(paths: List[str]) -> str:
    if not paths:
        return "none"
    first = os.path.basename(paths[0])
    if ".cumulative." in first:
        return "cumulative"
    if "batch" in first:
        return "batch"
    return "standard"


def probe_results_dir(main_dir: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Run every hop of the attribution chain and return the measurements."""
    from nanometa_live.app.tabs.dashboard_helpers import (
        _check_pathogens_both,
        _load_per_sample_organisms,
        _species_df_to_organisms,
        _species_discovery_df,
    )
    from nanometa_live.core.utils.attribution import (
        build_pathogen_attribution,
        format_attribution_text,
        samples_for_detection,
    )
    from nanometa_live.core.utils.classification_loaders import (
        _discover_sample_reports,
        load_kraken_data,
    )
    from nanometa_live.core.utils.sample_detector import get_available_samples

    available = get_available_samples(main_dir)
    samples = [s for s in available if s != "All Samples"]

    kraken_dir = os.path.join(main_dir, "kraken2")
    tiers = {s: _tier_of(_discover_sample_reports(kraken_dir, s)) for s in samples}

    aggregate_df = load_kraken_data(main_dir, "All Samples")
    aggregate_taxids = set()
    detected_organisms: List[Dict[str, Any]] = []
    if not aggregate_df.empty:
        species_df = _species_discovery_df(aggregate_df)
        detected_organisms = _species_df_to_organisms(species_df)
        aggregate_taxids = {int(o["taxid"]) for o in detected_organisms}

    taxid_to_samples = _load_per_sample_organisms(main_dir, available, config)
    per_sample_taxids = {
        taxid: [row["sample"] for row in rows]
        for taxid, rows in taxid_to_samples.items()
    }

    dangerous, subthreshold = _check_pathogens_both(detected_organisms, config)
    attributions = build_pathogen_attribution(dangerous, taxid_to_samples)
    unresolved = [a.pathogen for a in attributions if not a.resolved]

    return {
        "samples": samples,
        "tiers": tiers,
        "aggregate_taxids": aggregate_taxids,
        "per_sample_taxids": per_sample_taxids,
        "detections": dangerous,
        "subthreshold": subthreshold,
        "attributions": attributions,
        "unresolved": unresolved,
        "attribution_text": format_attribution_text(attributions),
        "resolution": [
            {
                "pathogen": d.get("name"),
                "taxid": d.get("taxid"),
                "detected_taxid": d.get("detected_taxid"),
                "threshold": d.get("threshold"),
                "reads": d.get("reads"),
                "samples": [
                    (r["sample"], r["reads"])
                    for r in samples_for_detection(d, taxid_to_samples)
                ],
            }
            for d in dangerous
        ],
    }


def _print_report(report: Dict[str, Any]) -> None:
    print("hop 1  samples and report tier")
    for sample in sorted(report["samples"]):
        print(f"       {sample:<20} tier={report['tiers'][sample]}")
    print()
    print(f"hop 2  aggregate species taxids: {len(report['aggregate_taxids'])}")
    print()
    print("hop 3  per-sample attribution dict")
    print(f"       taxids with at least one sample: {len(report['per_sample_taxids'])}")
    print()
    print("hop 4  detections and resolved samples")
    if not report["resolution"]:
        print("       (no watchlist detections above threshold)")
    for row in report["resolution"]:
        print(
            f"       {row['pathogen']} taxid={row['taxid']} "
            f"detected_taxid={row['detected_taxid']} threshold={row['threshold']} "
            f"aggregate_reads={row['reads']}"
        )
        if not row["samples"]:
            print("         UNRESOLVED: no per-sample rows for either taxid")
        for sample, reads in row["samples"]:
            above = "above" if reads >= (row["threshold"] or 0) else "BELOW"
            print(f"         {sample:<18} {reads:>8} reads  ({above} threshold)")
    if report["subthreshold"]:
        print()
        print("hop 4b sub-threshold watchlist hits")
        for hit in report["subthreshold"]:
            print(
                f"       {hit.get('name')} taxid={hit.get('taxid')} "
                f"reads={hit.get('reads')} threshold={hit.get('threshold')}"
            )
    print()
    print("hop 5  rendered text")
    print(f"       {report['attribution_text']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir")
    parser.add_argument("--config", default=None, help="Path to the run's config.yaml")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead")
    args = parser.parse_args()

    config: Dict[str, Any] = {}
    if args.config:
        from nanometa_live.core.config.config_loader import ConfigLoader

        config = ConfigLoader(
            os.path.dirname(os.path.abspath(args.config))
        ).load_config(args.config)
        from nanometa_live.core.watchlist.watchlist_manager import (
            get_watchlist_manager,
        )

        get_watchlist_manager().load_config(config)

    report = probe_results_dir(args.results_dir, config)
    if args.json:
        printable = {
            k: (sorted(v) if isinstance(v, set) else v)
            for k, v in report.items()
            if k not in ("attributions", "detections", "subthreshold")
        }
        print(json.dumps(printable, indent=2, default=str))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
