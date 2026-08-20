#!/usr/bin/env python3
"""Compare Kraken2 subspecies assignments against a known barcode composition.

Four barcode roles are judged by four different criteria, because one rule does
not fit them:

pure          the expected subspecies must lead, and must lead its best wrong
              sibling by a clear margin
mixture       every component must be detected above the alert threshold and
              ranked correctly; the margin is measured against the best
              NON-component subspecies, since here the runner-up is a real
              component rather than noise
sister        a related species that is not in the sample must not produce a
              watched call above the alert threshold; cross-assignment below
              that is reported, not failed
control       spiked contamination should be recovered and reported, and must
              stay below the alert threshold so it does not raise an alarm

What fraction of reads reaches S1 depends on how many discriminating
minimizers survived database minimization, so no absolute fraction is asserted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SPECIES_TAXID = 4007169
GENUS_TAXID = 4007157
SUBSPECIES = {
    4007186: "tularensis (Type A)",
    4007187: "holarctica (Type B)",
    4007188: "mediasiatica",
    4007189: "novicida",
}

ALERT_THRESHOLD = 25   # matches subspecies_francisella.yaml
SEPARATION_FACTOR = 5.0

BARCODES = {
    "barcode01": {"role": "pure", "components": [4007187]},
    "barcode02": {"role": "pure", "components": [4007186]},
    "barcode03": {"role": "pure", "components": [4007188]},
    "barcode04": {"role": "pure", "components": [4007189]},
    "barcode05": {"role": "mixture", "components": [4007187, 4007186],
                  "input_ratio": [0.686, 0.293]},
    "barcode06": {"role": "sister", "components": [],
                  "organism": "F. philomiragia"},
    "barcode07": {"role": "control", "components": [],
                  "spiked": {4007187: 19}},
}


def parse_report(path: Path) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        try:
            clade, direct, taxid = int(parts[1]), int(parts[2]), int(parts[4])
        except ValueError:
            continue
        rows[taxid] = {"clade": clade, "direct": direct,
                       "rank": parts[3], "name": parts[5].strip()}
    return rows


def _margin(top: int, runner: int) -> float:
    return top / runner if runner else float("inf")


def _fmt_margin(m: float) -> str:
    return "inf" if m == float("inf") else f"{m:.1f}x"


def evaluate(barcode: str, rows: dict[int, dict]) -> dict:
    spec = BARCODES[barcode]
    total = rows.get(1, {}).get("clade", 0) + rows.get(0, {}).get("clade", 0)
    species_clade = rows.get(SPECIES_TAXID, {}).get("clade", 0)
    subsp = {t: rows.get(t, {}).get("clade", 0) for t in SUBSPECIES}
    total_s1 = sum(subsp.values())
    ranked = sorted(subsp.items(), key=lambda kv: kv[1], reverse=True)

    r = {
        "barcode": barcode,
        "role": spec["role"],
        "total_reads": total,
        "watched_species_clade_reads": species_clade,
        "reads_at_subspecies": total_s1,
        "s1_share_of_clade": round(total_s1 / species_clade, 4) if species_clade else 0.0,
        "s1_share_of_sample": round(total_s1 / total, 5) if total else 0.0,
        "per_subspecies": {SUBSPECIES[t]: n for t, n in ranked},
    }

    components = spec["components"]
    non_component = [n for t, n in ranked if t not in components]
    best_non_component = max(non_component) if non_component else 0

    if spec["role"] == "pure":
        expected = components[0]
        top_taxid, top_reads = ranked[0]
        margin = _margin(top_reads, best_non_component)
        r["margin_over_best_wrong_sibling"] = _fmt_margin(margin)
        if top_taxid != expected:
            r["verdict"] = "FAIL"
            r["reason"] = (f"top call {SUBSPECIES[top_taxid]}, expected "
                           f"{SUBSPECIES[expected]}")
        elif top_reads < ALERT_THRESHOLD:
            r["verdict"] = "FAIL"
            r["reason"] = f"{top_reads} reads is below the alert threshold"
        elif margin < SEPARATION_FACTOR:
            r["verdict"] = "WEAK"
            r["reason"] = f"correct, but margin {_fmt_margin(margin)} < {SEPARATION_FACTOR}x"
        else:
            r["verdict"] = "PASS"
            r["reason"] = (f"{SUBSPECIES[expected]} leads by "
                           f"{_fmt_margin(margin)} over noise")

    elif spec["role"] == "mixture":
        missed = [t for t in components if subsp[t] < ALERT_THRESHOLD]
        order_ok = [t for t, _ in ranked if t in components] == components
        smallest = min(subsp[t] for t in components)
        margin = _margin(smallest, best_non_component)
        comp_total = sum(subsp[t] for t in components)
        r["observed_ratio"] = [round(subsp[t] / comp_total, 3) for t in components] \
            if comp_total else []
        r["input_ratio"] = spec["input_ratio"]
        r["margin_of_smallest_component_over_noise"] = _fmt_margin(margin)
        if missed:
            r["verdict"] = "FAIL"
            r["reason"] = ("component not detected above threshold: "
                           + ", ".join(SUBSPECIES[t] for t in missed))
        elif not order_ok:
            r["verdict"] = "FAIL"
            r["reason"] = "components detected but ranked in the wrong order"
        elif margin < SEPARATION_FACTOR:
            r["verdict"] = "WEAK"
            r["reason"] = f"both detected, but minor component margin {_fmt_margin(margin)}"
        else:
            obs = "/".join(f"{v:.0%}" for v in r["observed_ratio"])
            inp = "/".join(f"{v:.0%}" for v in spec["input_ratio"])
            r["verdict"] = "PASS"
            r["reason"] = f"both components resolved; observed {obs} vs input {inp}"

    elif spec["role"] == "sister":
        alerting = {SUBSPECIES[t]: n for t, n in ranked if n >= ALERT_THRESHOLD}
        r["cross_assigned_to_watched_clade"] = species_clade
        r["cross_assignment_rate"] = round(species_clade / total, 5) if total else 0.0
        r["would_alert"] = alerting
        if alerting:
            r["verdict"] = "FALSE POSITIVE"
            r["reason"] = (f"{spec['organism']} raises "
                           + ", ".join(f"{k} ({v} reads)" for k, v in alerting.items())
                           + f" at threshold {ALERT_THRESHOLD}")
        else:
            r["verdict"] = "PASS"
            r["reason"] = (f"cross-assignment {species_clade} reads "
                           f"({r['cross_assignment_rate']:.2%}) stays below threshold")

    else:  # control
        spiked = spec["spiked"]
        found = {SUBSPECIES[t]: subsp[t] for t in spiked}
        recovery = {SUBSPECIES[t]: round(subsp[t] / n, 3) for t, n in spiked.items()}
        over = {SUBSPECIES[t]: subsp[t] for t in spiked if subsp[t] >= ALERT_THRESHOLD}
        r["spiked_reads"] = {SUBSPECIES[t]: n for t, n in spiked.items()}
        r["recovered_reads"] = found
        r["recovery_fraction"] = recovery
        r["would_alert"] = over
        if over:
            r["verdict"] = "FAIL"
            r["reason"] = ("trace contamination reached the alert threshold: "
                           + ", ".join(f"{k}={v}" for k, v in over.items()))
        elif not any(found.values()):
            r["verdict"] = "FAIL"
            r["reason"] = "spiked contamination was not detected at all"
        else:
            r["verdict"] = "PASS"
            r["reason"] = ("contamination detected and below threshold: "
                           + ", ".join(f"{k}={v}/{r['spiked_reads'][k]}"
                                       for k, v in found.items()))
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("kraken_dir", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    results, missing = [], []
    for barcode in sorted(BARCODES):
        cands = [c for c in sorted(args.kraken_dir.glob(f"{barcode}*kraken2.report.txt"))
                 if "_batch" not in c.name]
        cumulative = [c for c in cands if "cumulative" in c.name]
        chosen = cumulative or cands
        if not chosen:
            missing.append(barcode)
            continue
        results.append(evaluate(barcode, parse_report(chosen[0])))

    print(f"{'barcode':<10} {'role':<8} {'verdict':<15} {'S1 reads':>8} "
          f"{'of clade':>9}  reason")
    print("-" * 108)
    for r in results:
        print(f"{r['barcode']:<10} {r['role']:<8} {r['verdict']:<15} "
              f"{r['reads_at_subspecies']:>8} {r['s1_share_of_clade']:>8.1%}  "
              f"{r['reason']}")
    if missing:
        print(f"\nNo report found for: {', '.join(missing)}")

    print("\nPer-barcode subspecies read counts:")
    for r in results:
        print(f"  {r['barcode']}: " + ", ".join(
            f"{k}={v}" for k, v in r["per_subspecies"].items()))

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f"\nWrote {args.json}")

    bad = [r for r in results if r["verdict"] in ("FAIL", "FALSE POSITIVE")]
    return 1 if (bad or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
