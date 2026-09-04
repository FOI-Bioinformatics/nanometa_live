#!/usr/bin/env python
"""Measure the sequencing depth an assembly could actually reach.

Assembly is the one feature that can run, succeed and publish a number that is
not a result: on the round-5 demo corpus Flye produced 8-27 kb "assemblies" of
3 contigs at 6-7x, which the Reports tab rendered with an N50 as though they
were genomes (audit 2026-09-03). Whether that is the assembler's fault or the
data's is an empirical question, and this script answers it.

For every (sample, taxid) pair it sums the bases Kraken2 assigned to that taxid
and divides by the length of the reference genome already in the cache. The
selection rule is deliberately the same one ``EXTRACT_READS_BY_TAXID`` uses --
``$1 == "C" && $3 == taxid`` over the per-read output -- so this census equals
what a depth gate would compute at run time, rather than approximating it.

Two input modes:

* ``kraken2/<sample>.kraken2.output.txt`` (exact). Column 4 is the read length,
  so no FASTQ is read. Written only when ``save_reads_assignment`` is on, which
  the GUI sets whenever confirmation testing runs.
* ``kraken2/<sample>*.kraken2.report.txt`` (estimated). Falls back to
  ``cumul_reads x mean_read_length``, the mean taken from the QC stats or from
  ``--mean-read-length``. Marked ``estimated`` in the output so the two are
  never confused.

Usage:
    python scripts/audit_assembly_depth.py <results_dir> \
        [--genomes pathogen_genomes.json] [--required-depth 30] \
        [--json out.json] [--min-reads 1]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Dict, Optional, Tuple

# A usable draft assembly of a bacterial genome needs roughly this coverage.
# Flye's own documentation and common practice put a usable ONT draft in the
# 30-50x band; 30 is the charitable end, so a shortfall against it is a floor
# on the shortfall, not an overstatement.
DEFAULT_REQUIRED_DEPTH = 30.0


def genome_length(path: str) -> Optional[int]:
    """Total bases in a FASTA, or None when it cannot be read."""
    try:
        total = 0
        with open(path) as fh:
            for line in fh:
                if not line.startswith(">"):
                    total += len(line.strip())
        return total or None
    except OSError:
        return None


def bases_per_taxid(output_path: str) -> Tuple[Dict[int, int], Dict[int, int], int, int]:
    """(bases, reads) per taxid plus classified/total bases, from a per-read output.

    Column layout is Kraken2's: C/U, read id, taxid, length, LCA map.
    """
    bases: Dict[int, int] = {}
    reads: Dict[int, int] = {}
    classified = total = 0
    with open(output_path) as fh:
        for line in fh:
            parts = line.split("\t", 4)
            if len(parts) < 4:
                continue
            try:
                length = int(parts[3])
            except ValueError:
                continue
            total += length
            if parts[0] != "C":
                continue
            classified += length
            try:
                taxid = int(parts[2])
            except ValueError:
                continue
            bases[taxid] = bases.get(taxid, 0) + length
            reads[taxid] = reads.get(taxid, 0) + 1
    return bases, reads, classified, total


def report_reads_per_taxid(report_path: str) -> Dict[int, Tuple[int, str]]:
    """{taxid: (cumul_reads, name)} from a Kraken2 report."""
    out: Dict[int, Tuple[int, str]] = {}
    try:
        with open(report_path) as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if len(f) < 6:
                    continue
                try:
                    out[int(f[4])] = (int(f[1]), f[5].strip())
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def clades(report_path: str) -> Dict[int, set]:
    """{taxid: set of taxids in its clade, itself included}.

    A Kraken2 report encodes the tree by indenting the name column two spaces
    per level, so a node's clade is itself plus every following row indented
    deeper, up to the first row at or above its own depth.

    This matters because ``EXTRACT_READS_BY_TAXID`` matches the taxid
    EXACTLY. On the demo corpus that captures 230 of the 763 reads of
    *F. tularensis* in barcode05 -- the other 530 sit on the holarctica
    subspecies node. Any depth measured on the exact node therefore
    understates what an assembly of the organism could use, and the same
    shortfall applies to the reads confirmatory validation aligns.
    """
    rows = []
    try:
        with open(report_path) as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if len(f) < 6:
                    continue
                try:
                    taxid = int(f[4])
                except ValueError:
                    continue
                name = f[5]
                rows.append((len(name) - len(name.lstrip(" ")), taxid))
    except OSError:
        return {}
    out: Dict[int, set] = {}
    for i, (depth, taxid) in enumerate(rows):
        members = {taxid}
        for other_depth, other_taxid in rows[i + 1:]:
            if other_depth <= depth:
                break
            members.add(other_taxid)
        out[taxid] = members
    return out


def _sample_of(path: str) -> str:
    base = os.path.basename(path)
    for suffix in (".kraken2.output.txt", ".cumulative.kraken2.report.txt",
                   ".kraken2.report.txt"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def find_genomes(results_dir: str, explicit: Optional[str]) -> Dict[int, str]:
    """{taxid: fasta path} from pathogen_genomes.json."""
    candidates = [explicit] if explicit else []
    candidates += [
        os.path.join(results_dir, "pipeline_input", "pathogen_genomes.json"),
        os.path.join(results_dir, "on_demand_validation", "pathogen_genomes.json"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                raw = json.load(open(path))
            except (OSError, ValueError):
                continue
            out: Dict[int, str] = {}
            for key, value in (raw or {}).items():
                try:
                    out[int(key)] = value if isinstance(value, str) else value.get("path", "")
                except (ValueError, AttributeError):
                    continue
            if out:
                return out
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir")
    ap.add_argument("--genomes", help="pathogen_genomes.json (else discovered under results_dir)")
    ap.add_argument("--required-depth", type=float, default=DEFAULT_REQUIRED_DEPTH)
    ap.add_argument("--mean-read-length", type=float, default=None,
                    help="used only in the estimated (report-based) mode")
    ap.add_argument("--min-reads", type=int, default=1,
                    help="skip taxids below this read count")
    ap.add_argument("--json", help="write the full census here")
    args = ap.parse_args()

    kraken_dir = os.path.join(args.results_dir, "kraken2")
    if not os.path.isdir(kraken_dir):
        print(f"no kraken2/ under {args.results_dir}", file=sys.stderr)
        return 2

    genomes = find_genomes(args.results_dir, args.genomes)
    if not genomes:
        print("warning: no pathogen_genomes.json found; depth needs a reference "
              "length, so only whole-sample totals will be reported",
              file=sys.stderr)

    outputs = sorted(glob.glob(os.path.join(kraken_dir, "*.kraken2.output.txt")))
    rows = []
    whole_sample = []

    if outputs:
        mode = "exact"
        for path in outputs:
            sample = _sample_of(path)
            bases, reads, classified, total = bases_per_taxid(path)
            names: Dict[int, str] = {}
            clade_of: Dict[int, set] = {}
            for pattern in (f"{sample}.cumulative.kraken2.report.txt",
                            f"{sample}.kraken2.report.txt"):
                rp = os.path.join(kraken_dir, pattern)
                if os.path.isfile(rp):
                    names = {t: n for t, (_c, n) in report_reads_per_taxid(rp).items()}
                    clade_of = clades(rp)
                    break
            whole_sample.append({
                "sample": sample, "total_bases": total,
                "classified_bases": classified,
            })
            for taxid, fasta in sorted(genomes.items()):
                b, r = bases.get(taxid, 0), reads.get(taxid, 0)
                members = clade_of.get(taxid, {taxid})
                clade_b = sum(bases.get(m, 0) for m in members)
                clade_r = sum(reads.get(m, 0) for m in members)
                if max(r, clade_r) < args.min_reads:
                    continue
                glen = genome_length(fasta)
                rows.append({
                    "sample": sample, "taxid": taxid,
                    "name": names.get(taxid, ""),
                    "reads": r, "bases": b,
                    "clade_reads": clade_r, "clade_bases": clade_b,
                    "clade_size": len(members),
                    "genome_size": glen, "genome_source": os.path.basename(fasta),
                    "depth": (b / glen) if glen else None,
                    "clade_depth": (clade_b / glen) if glen else None,
                    "required_depth": args.required_depth,
                    "shortfall_bases": (int(args.required_depth * glen) - clade_b) if glen else None,
                    "mode": "exact",
                })
    else:
        mode = "estimated"
        mean_len = args.mean_read_length or 800.0
        reports = sorted(glob.glob(os.path.join(kraken_dir, "*.cumulative.kraken2.report.txt"))) \
            or sorted(glob.glob(os.path.join(kraken_dir, "*.kraken2.report.txt")))
        for path in reports:
            sample = _sample_of(path)
            per_taxid = report_reads_per_taxid(path)
            for taxid, fasta in sorted(genomes.items()):
                cumul, name = per_taxid.get(taxid, (0, ""))
                if cumul < args.min_reads:
                    continue
                glen = genome_length(fasta)
                b = int(cumul * mean_len)
                rows.append({
                    "sample": sample, "taxid": taxid, "name": name,
                    "reads": cumul, "bases": b,
                    "genome_size": glen, "genome_source": os.path.basename(fasta),
                    "depth": (b / glen) if glen else None,
                    "required_depth": args.required_depth,
                    "shortfall_bases": (int(args.required_depth * glen) - b) if glen else None,
                    "mode": "estimated",
                })

    rows.sort(key=lambda r: (r.get("clade_depth") or r.get("depth") or 0), reverse=True)

    print(f"# assembly depth census ({mode}) -- {args.results_dir}")
    print(f"# required depth for a usable draft: {args.required_depth:g}x\n")
    if whole_sample:
        print(f"{'sample':<14} {'total Mb':>9} {'classified Mb':>14}")
        for w in whole_sample:
            print(f"{w['sample']:<14} {w['total_bases']/1e6:>9.2f} "
                  f"{w['classified_bases']/1e6:>14.2f}")
        print()
    if rows:
        has_clade = any("clade_depth" in r for r in rows)
        if has_clade:
            print(f"{'sample':<13} {'taxid':>8} {'exact rd':>9} {'clade rd':>9} "
                  f"{'clade Mb':>9} {'genome Mb':>10} {'exact':>7} {'clade':>7}  "
                  f"{'verdict':<9} name")
        else:
            print(f"{'sample':<13} {'taxid':>8} {'reads':>9} {'Mb':>9} "
                  f"{'genome Mb':>10} {'depth':>7}  {'verdict':<9} name")
        for r in rows:
            best = r.get("clade_depth") if r.get("clade_depth") is not None else r["depth"]
            verdict = "-" if best is None else (
                "assemble" if best >= r["required_depth"] else "decline")
            if has_clade:
                print(f"{r['sample']:<13} {r['taxid']:>8} {r['reads']:>9} "
                      f"{r.get('clade_reads', 0):>9} {r.get('clade_bases', 0)/1e6:>9.3f} "
                      f"{(r['genome_size'] or 0)/1e6:>10.2f} "
                      f"{(r['depth'] or 0):>6.2f}x {(best or 0):>6.2f}x  "
                      f"{verdict:<9} {r['name'][:30]}")
            else:
                print(f"{r['sample']:<13} {r['taxid']:>8} {r['reads']:>9} "
                      f"{r['bases']/1e6:>9.3f} {(r['genome_size'] or 0)/1e6:>10.2f} "
                      f"{(best or 0):>6.2f}x  {verdict:<9} {r['name'][:30]}")
        assemble = sum(1 for r in rows
                       if (r.get("clade_depth") or r.get("depth") or 0) >= r["required_depth"])
        print(f"\n{assemble} of {len(rows)} (sample, taxid) pairs reach "
              f"{args.required_depth:g}x on the best available measure.")
        if has_clade:
            missed = [r for r in rows if r.get("clade_reads", 0) > r["reads"]]
            if missed:
                worst = max(missed, key=lambda r: r["clade_reads"] - r["reads"])
                pct = 100.0 * worst["reads"] / worst["clade_reads"]
                print(f"Exact-taxid extraction (what EXTRACT_READS_BY_TAXID does) "
                      f"captures {pct:.0f}% of the clade at worst: "
                      f"{worst['name'].strip()[:34]} in {worst['sample']}, "
                      f"{worst['reads']} of {worst['clade_reads']} reads.")
    else:
        print("no (sample, taxid) pair had reads above the floor.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"mode": mode, "results_dir": args.results_dir,
                       "required_depth": args.required_depth,
                       "whole_sample": whole_sample, "targets": rows}, fh, indent=1)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
