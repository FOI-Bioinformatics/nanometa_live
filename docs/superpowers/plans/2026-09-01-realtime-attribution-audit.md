# Real-time Sample Attribution Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find and fix why the dashboard does not name which sample/barcode carries a
detected watchlist organism when the pipeline runs in real-time mode, while the same
data attributes correctly in batch mode.

**Architecture:** The audit drives a real nanorunner-fed real-time run against the
Bioshield demo kit, snapshots the results tree at intervals, and replays each snapshot
through the attribution chain offline so every hop can be measured without a browser.
The chain has five hops and the audit measures each one separately:

```
kraken2 report files            (hop 1: what the pipeline wrote, per sample)
  -> load_kraken_data(dir, sample)          (hop 2: per-sample frame + report tier)
  -> _load_per_sample_organisms             (hop 3: taxid -> [sample rows])
  -> samples_for_detection / build_pathogen_attribution  (hop 4: detection -> samples)
  -> banner subhead, alert card chips, popover           (hop 5: what is rendered)
```

Batch mode differs from real-time at hop 1 (one final report per sample versus a
progressive cumulative report rewritten every batch, plus per-batch reports under
`kraken2/<sample>/batch_reports/`) and at hop 4 (mid-run a barcode's own count is often
below the watchlist entry's `alert_threshold` even when the aggregate is above it).
Those two are the leading hypotheses; the probe decides between them and three others
before any fix is written.

**Tech Stack:** Python 3.11/3.12, pandas, Dash 4, pytest, Nextflow 26.04.x,
nanorunner 3.1.0, conda env `nf-core`.

**Spec:** This plan is the spec. The reported defect is: "cannot see which
sample/barcode contains discovered watchlist organisms; works in batch mode, not in
real-time." No written spec exists; the acceptance criterion is stated in Global
Constraints below.

## Global Constraints

- **Acceptance criterion.** During a live real-time run, for every watchlist detection
  the dashboard shows either the barcode names carrying it, or an explicit statement of
  why it cannot name them. A detection that names no sample and says nothing is a
  failure, in the verdict banner, on the alert card, and in the exported report.
- **Never trade a false negative for a false positive.** An unattributed detection must
  never be silently dropped, and a sample must never be named for a pathogen it does not
  carry. Where the two conflict, say more, not less. This mirrors the existing
  invariant in CLAUDE.md: "A verdict must never claim a result it did not earn."
- **Do not change the aggregate verdict.** `select_verdict` decides ACTION REQUIRED on
  the aggregate. Nothing in this plan may change which verdict state is chosen; only
  the attribution subhead and the per-sample rendering are in scope.
- **Environment.** All Python and Nextflow commands run in the `nf-core` conda env
  (`conda run -n nf-core ...`). The `nanometa` env has Dash but neither `pytest-xdist`
  nor `pytest-cov`; use `-o addopts=""` there.
- **Test suite floors.** `pytest.ini` enforces `fail_under = 74` on coverage runs and
  `filterwarnings = error::DeprecationWarning:nanometa_live`. Both must stay green.
- **No Unicode in Nextflow files** (user global rule). Use plain ASCII in any `.nf` or
  `.config` edit.
- **Modest scientific language** in all comments, docstrings and docs added here.
- **Attribution has one resolver.** Never index `taxid_to_samples` directly; call
  `samples_for_detection(detection, taxid_to_samples)` (CLAUDE.md invariant).
- **Attribution counts `cumul_reads`, not `reads`,** and the discovery floor gates on
  the same column (CLAUDE.md invariant, pinned by
  `tests/test_attribution_read_column.py`).
- **Demo kit paths** (verified present on this machine):
  - config `~/nanometa-demo/configs/demo3_realtime.yaml`
  - launcher `~/nanometa-demo/scripts/run_demo3.sh` (port 8063)
  - feeder `~/nanometa-demo/scripts/feed_demo3.sh` (nanorunner replay)
  - results `~/nanometa-demo/runs/demo3_results`
  - source reads `~/nanometa-demo/data/multiplex` (barcode05-08 + unclassified, 80 MB)
  - Kraken2 DB `~/nanometa-demo/db/bioshield26.1_8G`
  - watchlist: `bioshield_agents` builtin, enabled in the demo3 config
- **Batch-mode control** for the same organisms: `~/nanometa-demo/scripts/run_demo1.sh`
  (port 8061, results `~/nanometa-demo/runs/demo1_results`, already populated).

---

## File Structure

**New files:**

- `scripts/audit_realtime_attribution.py` — offline probe. Given a results directory,
  prints one line per hop of the attribution chain so a snapshot can be diagnosed
  without a browser. Retained after the audit as a support tool.
- `tests/fixtures/realtime_attribution/` — a captured real-time snapshot (progressive
  cumulative reports plus `<sample>/batch_reports/` and `<sample>/stats/`) used by the
  new regression tests. Small, hand-trimmed, tracked in git.
- `tests/test_realtime_attribution.py` — regression tests for the attribution chain
  over a real-time-shaped results tree. This layout is currently untested: no existing
  attribution test writes a `*.cumulative.kraken2.report.txt` or a `batch_reports/`
  directory.
- `docs/audit/realtime-attribution-2026-09-01.md` — findings, measurements, and what
  was ruled out.

**Modified files (only those the probe implicates):**

- `nanometa_live/core/utils/attribution.py` — `build_pathogen_attribution`,
  `_attribution_phrase` (Task 4).
- `nanometa_live/app/tabs/dashboard_helpers.py` — `_load_per_sample_organisms`
  (Task 5).
- `nanometa_live/app/components/attribution.py` — `_render_sample_attribution`
  (Task 6).
- `CLAUDE.md` — new invariant paragraph (Task 8).

---

## Task 1: Reproduce live and pin the failing surface

No code changes. This task produces evidence and decides which of the later tasks run.

**Files:**
- Create: `/tmp/rt-audit/notes.md` (scratch, not committed)

**Interfaces:**
- Consumes: nothing.
- Produces: `/tmp/rt-audit/notes.md` recording, for each of five surfaces, whether the
  barcode name is shown. Later tasks read this file to decide scope.

- [ ] **Step 1: Start from a clean slate**

```bash
~/nanometa-demo/scripts/stop_all.sh
mkdir -p /tmp/rt-audit/snapshots
rm -rf ~/nanometa-demo/runs/demo3_results ~/nanometa-demo/data/realtime_watch
mkdir -p ~/nanometa-demo/data/realtime_watch
```

- [ ] **Step 2: Confirm batch mode attributes correctly (the control)**

Launch the batch demo, which already has results on disk:

```bash
~/nanometa-demo/scripts/run_demo1.sh    # prints http://localhost:8061
```

Open the URL. On the Dashboard tab, record in `/tmp/rt-audit/notes.md`:
- the verdict banner title,
- the exact text of the "Triggered by:" line under it,
- for the top alert card, the text of the "DETECTED IN:" row.

Expected (batch, from the demo runbook): ACTION REQUIRED with a "Triggered by:" line
naming specific barcodes such as `barcode05`. If batch mode does NOT name barcodes
either, stop and report that: the defect is not real-time-specific and this plan's
framing is wrong.

- [ ] **Step 3: Start the real-time run**

```bash
~/nanometa-demo/scripts/run_demo3.sh     # prints http://localhost:8063
```

Open http://localhost:8063 and click **Start Analysis**. Wait for the SCREENING banner
(about 40 s).

- [ ] **Step 4: Start the feeder and the snapshotter together**

In one terminal:

```bash
~/nanometa-demo/scripts/feed_demo3.sh
```

In a second terminal, snapshot the results tree every 20 s for 12 minutes. The
snapshots are what Task 2's probe replays:

```bash
cd /tmp/rt-audit/snapshots
for i in $(seq 1 36); do
  ts=$(date +%H%M%S)
  rsync -a --exclude 'work' --exclude '*.fastq.gz' \
    ~/nanometa-demo/runs/demo3_results/ "snap_${ts}/"
  sleep 20
done
```

- [ ] **Step 5: Record every surface at the moment the verdict flips**

When the banner turns ACTION REQUIRED (expected about 60 s after the feed starts),
record all five in `/tmp/rt-audit/notes.md`, each as SHOWS BARCODE / SHOWS NOTHING /
SAYS WHY NOT, with the verbatim text:

1. Verdict banner subhead ("Triggered by: ..." or "Sample attribution unavailable ...").
2. Pathogen alert card "DETECTED IN:" row (critical and high tiers show chips; a
   moderate "watched" hit spanning more than one sample collapses to a count pill).
3. The attribution popover behind that count pill (click it).
4. Organisms tab, per-sample counts for the detected organism.
5. Export Results report, Watched Organisms table.

Also note the wall-clock time of the flip and the current per-barcode read counts from
the QC tab.

- [ ] **Step 6: Let the run finish, then record the same five again**

The feeder exits by itself after about 11 minutes. Once the pipeline self-terminates,
record the same five surfaces. A defect present mid-run but absent at the end points
at a horizon or timing cause (Tasks 4 and 5); one present at both points at a
structural cause (Tasks 5 and 6).

- [ ] **Step 7: Commit nothing; write the evidence file**

`/tmp/rt-audit/notes.md` must state, in one line each: which surfaces fail, whether
they fail mid-run only or also at the end, and the batch-mode control result.

---

## Task 2: Build the offline attribution probe

**Files:**
- Create: `scripts/audit_realtime_attribution.py`
- Test: `tests/test_realtime_attribution.py` (created here, extended in later tasks)

**Interfaces:**
- Consumes: a results directory path (a Task 1 snapshot, or a live outdir).
- Produces: `probe_results_dir(main_dir: str, config: dict) -> dict` with keys
  `samples: list[str]`, `tiers: dict[str, str]`, `aggregate_taxids: set[int]`,
  `per_sample_taxids: dict[int, list[str]]`, `detections: list[dict]`,
  `attributions: list[PathogenAttribution]`, `unresolved: list[str]`. Tasks 4-6 import
  nothing from it; it is a diagnostic entry point run from the command line.

- [ ] **Step 1: Write the failing test**

Create `tests/test_realtime_attribution.py`:

```python
"""The attribution chain over a real-time-shaped results tree.

Every existing attribution test writes a flat ``<sample>.kraken2.report.txt``.
Real-time mode writes a progressive ``<sample>.cumulative.kraken2.report.txt``
that is rewritten every batch, plus per-batch reports under
``kraken2/<sample>/batch_reports/`` and the incremental-layout marker under
``kraken2/<sample>/stats/``. The loader resolves a different report tier for
that tree, so the layout needs its own coverage.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _backdate(path: Path, seconds: int = 5) -> None:
    """Age a file past the loader's 1 s stability window."""
    old = time.time() - seconds
    os.utime(path, (old, old))


def _kreport(rows: list[tuple[float, int, int, str, int, str]]) -> str:
    return "".join(
        f"{pct:.2f}\t{cumul}\t{reads}\t{rank}\t{taxid}\t{name}\n"
        for pct, cumul, reads, rank, taxid, name in rows
    )


def write_realtime_sample(
    results_dir: Path,
    sample: str,
    species_taxid: int,
    species_name: str,
    cumul_reads: int,
    direct_reads: int | None = None,
    n_batches: int = 3,
) -> None:
    """Write one sample in the real-time layout.

    Produces the progressive cumulative report the head process writes, the
    per-batch reports KRAKEN2_REPORT_GENERATOR publishes, and the
    ``stats/batch_N_report_stats.json`` marker that makes
    ``_is_incremental_layout`` return True.
    """
    direct = cumul_reads if direct_reads is None else direct_reads
    kraken = results_dir / "kraken2"
    kraken.mkdir(parents=True, exist_ok=True)

    total = cumul_reads + 10
    rows = [
        (0.0, 10, 10, "U", 0, "unclassified"),
        (100.0, cumul_reads, 0, "R", 1, "root"),
        (100.0, cumul_reads, 0, "D", 2, "  Bacteria"),
        (
            round(direct / total * 100, 2),
            cumul_reads,
            direct,
            "S",
            species_taxid,
            f"    {species_name}",
        ),
    ]
    cumulative = kraken / f"{sample}.cumulative.kraken2.report.txt"
    cumulative.write_text(_kreport(rows))
    _backdate(cumulative)

    batch_dir = kraken / sample / "batch_reports"
    batch_dir.mkdir(parents=True, exist_ok=True)
    stats_dir = kraken / sample / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    per_batch = max(1, cumul_reads // n_batches)
    for b in range(n_batches):
        batch_rows = [
            (0.0, 3, 3, "U", 0, "unclassified"),
            (100.0, per_batch, 0, "R", 1, "root"),
            (100.0, per_batch, 0, "D", 2, "  Bacteria"),
            (100.0, per_batch, per_batch, "S", species_taxid, f"    {species_name}"),
        ]
        report = batch_dir / f"{sample}_batch{b}.kraken2.report.txt"
        report.write_text(_kreport(batch_rows))
        _backdate(report)
        stats = stats_dir / f"batch_{b}_report_stats.json"
        stats.write_text('{"total_reads": %d}' % per_batch)
        _backdate(stats)


class TestProbeReadsTheRealtimeLayout:
    def test_probe_resolves_every_sample_and_its_tier(self, tmp_path):
        from scripts.audit_realtime_attribution import probe_results_dir

        results = tmp_path / "results"
        write_realtime_sample(results, "barcode05", 263, "Francisella tularensis", 900)
        write_realtime_sample(results, "barcode06", 263, "Francisella tularensis", 40)

        report = probe_results_dir(str(results), config={})

        assert sorted(report["samples"]) == ["barcode05", "barcode06"]
        assert report["tiers"]["barcode05"] == "cumulative"
        assert 263 in report["aggregate_taxids"]
        assert sorted(report["per_sample_taxids"][263]) == ["barcode05", "barcode06"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_realtime_attribution.py::TestProbeReadsTheRealtimeLayout -x
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.audit_realtime_attribution'`.

- [ ] **Step 3: Write the probe**

Create `scripts/audit_realtime_attribution.py`:

```python
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
    unresolved = [
        a.pathogen for a in attributions if not a.resolved
    ]

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
    for row in report["resolution"]:
        print(
            f"       {row['pathogen']} taxid={row['taxid']} "
            f"detected_taxid={row['detected_taxid']} threshold={row['threshold']}"
        )
        if not row["samples"]:
            print("         UNRESOLVED: no per-sample rows for either taxid")
        for sample, reads in row["samples"]:
            above = "above" if reads >= (row["threshold"] or 0) else "below"
            print(f"         {sample:<18} {reads:>8} reads  ({above} threshold)")
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

        config = ConfigLoader().load_config(args.config)
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_realtime_attribution.py::TestProbeReadsTheRealtimeLayout -x
```

Expected: PASS.

- [ ] **Step 5: Run the probe over every Task 1 snapshot**

```bash
for snap in /tmp/rt-audit/snapshots/snap_*; do
  echo "=== $snap"
  conda run -n nf-core python scripts/audit_realtime_attribution.py "$snap" \
    --config ~/nanometa-demo/configs/demo3_realtime.yaml
done | tee /tmp/rt-audit/probe.log
```

Read `/tmp/rt-audit/probe.log` and classify the failure. The five candidate causes and
the line in the probe output that identifies each:

| Cause | Probe signature | Fix task |
|---|---|---|
| A. Per-sample counts below the entry's `alert_threshold` mid-run | hop 4 lists samples, all marked `below threshold`; hop 5 says "aggregate across N samples" | Task 4 |
| B. Multi-sample moderate hit collapsed to a count pill | hop 4 and hop 5 both name samples, but Task 1 recorded no barcode on the card | Task 6 |
| C. A sample silently dropped by the file-stability window | hop 3 taxid lists shrink and grow between consecutive snapshots with no other change | Task 5 |
| D. Discovery floor drops early per-sample rows | hop 2 has the taxid, hop 3 does not, and the sample's `cumul_reads` is under 5 | Task 5 |
| E. Aggregate and per-sample resolve different report tiers | hop 1 shows mixed tiers, and hop 4 prints UNRESOLVED | Task 5 |

- [ ] **Step 6: Commit**

```bash
git add scripts/audit_realtime_attribution.py tests/test_realtime_attribution.py
git commit -m "test(audit): probe the per-sample attribution chain on a realtime tree

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F6P7wEqXM1TmLN6on3S9DZ"
```

---

## Task 3: Capture a real-time snapshot as a tracked fixture

**Files:**
- Create: `tests/fixtures/realtime_attribution/kraken2/...` (from a Task 1 snapshot)
- Modify: `tests/test_realtime_attribution.py`

**Interfaces:**
- Consumes: `/tmp/rt-audit/snapshots/` from Task 1.
- Produces: a `realtime_snapshot` pytest fixture returning the fixture directory path,
  used by Tasks 4-6.

- [ ] **Step 1: Trim a snapshot down to a fixture**

Pick the earliest snapshot whose probe output reproduces the defect. Copy only the
Kraken2 tree, and trim each report to the rows the tests need (unclassified, root,
domain, the detected species, one subspecies):

```bash
SNAP=/tmp/rt-audit/snapshots/snap_XXXXXX   # the reproducing one
DEST=tests/fixtures/realtime_attribution
mkdir -p "$DEST"
rsync -a --include '*/' \
  --include '*.cumulative.kraken2.report.txt' \
  --include '*_batch*.kraken2.report.txt' \
  --include 'batch_*_report_stats.json' \
  --exclude '*' "$SNAP/kraken2/" "$DEST/kraken2/"
du -sh "$DEST"    # must stay under 200 KB
```

Trim any report over 200 lines with `head -1 && grep -E '\t(U|R|D|S|S1)\t'`.

- [ ] **Step 2: Verify the fixture is tracked, not ignored**

`.gitignore` has historically carried a blanket `test_*` that silently excluded
fixtures at any depth. Check explicitly:

```bash
git check-ignore -v tests/fixtures/realtime_attribution/kraken2/*.txt || echo "TRACKED OK"
```

Expected: `TRACKED OK`. If any path is ignored, add a negation to `.gitignore`.

- [ ] **Step 3: Add the fixture accessor and a characterization test**

Append to `tests/test_realtime_attribution.py`:

```python
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "realtime_attribution"


@pytest.fixture
def realtime_snapshot(tmp_path):
    """A copy of the captured realtime snapshot, mtimes aged past the gate."""
    import shutil

    dest = tmp_path / "results"
    shutil.copytree(FIXTURE_DIR, dest)
    for path in dest.rglob("*"):
        if path.is_file():
            _backdate(path)
    return dest


class TestCapturedSnapshotReproducesTheDefect:
    def test_the_detection_resolves_at_least_one_sample(self, realtime_snapshot):
        """The captured tree must attribute its detection to a named sample."""
        from scripts.audit_realtime_attribution import probe_results_dir

        report = probe_results_dir(str(realtime_snapshot), config={})

        assert report["per_sample_taxids"], (
            "no taxid resolved to any sample on a realtime tree that has "
            "per-sample reports on disk"
        )
```

- [ ] **Step 4: Run it**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_realtime_attribution.py -x
```

Record whether it passes. A pass means hop 3 is healthy in the captured snapshot and
the cause is A or B (Tasks 4 and 6). A fail means the cause is C, D or E (Task 5).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/realtime_attribution tests/test_realtime_attribution.py
git commit -m "test(audit): track a realtime kraken2 snapshot as an attribution fixture

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F6P7wEqXM1TmLN6on3S9DZ"
```

---

## Task 4: Name the samples a detection actually came from, whatever the threshold

Run this task only if Task 2 Step 5 classified the failure as cause A.

**Why:** `build_pathogen_attribution` lists a sample as triggering only when that
sample's own read count reaches the pathogen's `alert_threshold`. The verdict is
decided on the aggregate. In batch mode every barcode is complete when the verdict
appears, so the hot barcode clears its own threshold and is named. In real-time the
verdict flips as soon as the aggregate crosses, which happens minutes before any single
barcode does, so every sample lands in `below_threshold_samples` and
`_attribution_phrase` renders "aggregate across N samples" - a true statement that
names nobody. The threshold gate exists for a real reason (ten barcodes at 50 reads
each must not all be named for a pathogen with a threshold of 100), so the fix is to
keep the distinction and still name the samples, ranked, with their counts.

**Files:**
- Modify: `nanometa_live/core/utils/attribution.py:265-310` (`_attribution_phrase`)
- Test: `tests/test_attribution.py`, `tests/test_realtime_attribution.py`

**Interfaces:**
- Consumes: `PathogenAttribution` from Task 0 (existing dataclass; fields `pathogen`,
  `samples`, `below_threshold_samples`, `top_reads`, `negative_control_samples`,
  `negative_control_reads`, `negative_control_fraction`).
- Produces: no signature change. `_attribution_phrase(attribution) -> Optional[str]`
  keeps its shape; only the below-threshold branch's text changes.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_attribution.py`:

```python
class TestBelowThresholdSamplesAreStillNamed:
    """A detection carried only by sub-threshold samples must still name them.

    The aggregate crosses the alert threshold before any single barcode does,
    which is the normal state of a realtime run for its first several minutes.
    Rendering only "aggregate across 3 samples" tells the operator a detection
    exists and refuses to say where, which is the one thing they need in order
    to act.
    """

    def test_the_phrase_names_the_top_sub_threshold_samples(self):
        from nanometa_live.core.utils.attribution import (
            PathogenAttribution,
            format_attribution_text,
        )

        attribution = PathogenAttribution(
            pathogen="Francisella tularensis",
            samples=[],
            below_threshold_samples=["barcode05", "barcode06", "barcode07"],
            top_reads=64,
        )

        text = format_attribution_text([attribution])

        assert "barcode05" in text
        assert "aggregate across 3 samples" in text

    def test_a_sample_above_threshold_still_reads_as_triggering(self):
        from nanometa_live.core.utils.attribution import (
            PathogenAttribution,
            format_attribution_text,
        )

        attribution = PathogenAttribution(
            pathogen="Bacillus anthracis",
            samples=["barcode08"],
            below_threshold_samples=["barcode05"],
            top_reads=4000,
        )

        text = format_attribution_text([attribution])

        assert text == "Triggered by: Bacillus anthracis (barcode08)"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_attribution.py::TestBelowThresholdSamplesAreStillNamed -x
```

Expected: FAIL on the first test, because the current phrase is
`"Francisella tularensis (aggregate across 3 samples)"` with no barcode name.

- [ ] **Step 3: Change the below-threshold branch**

In `nanometa_live/core/utils/attribution.py`, replace the `below` branch of
`_attribution_phrase`:

```python
    below = [s for s in attribution.below_threshold_samples if s not in nc]
    if below:
        n = len(below)
        # Name them. The aggregate crosses the alert threshold before any one
        # sample does, which is the normal state of a realtime run for its
        # first minutes; "aggregate across 3 samples" is true and tells the
        # operator nothing they can act on. The samples are already sorted
        # descending by read count in build_pathogen_attribution, so the first
        # three are the ones worth naming.
        shown = below[:3]
        names = ", ".join(shown)
        overflow = n - len(shown)
        if overflow > 0:
            names += f", +{overflow} more"
        return (
            f"{attribution.pathogen} ({names}; aggregate across {n} "
            f"sample{'s' if n != 1 else ''}){nc_clause}"
        )
```

The ordering guarantee this relies on is real: `_load_per_sample_organisms` sorts each
sample list descending by reads, and `build_pathogen_attribution` appends in that
order.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_attribution.py tests/test_verdict_banner_callback.py -x
```

Expected: PASS. `tests/test_attribution.py:137` and
`tests/test_verdict_banner_callback.py:288` both assert the old string
`"aggregate across 10 samples"`; both must be updated to assert the new phrasing,
which still contains that substring, so they should pass unchanged. If either fails,
update the assertion to match the new text rather than weakening the new behaviour.

- [ ] **Step 5: Commit**

```bash
git add nanometa_live/core/utils/attribution.py tests/test_attribution.py
git commit -m "fix(attribution): name sub-threshold samples instead of only counting them

The aggregate crosses a watchlist entry's alert threshold minutes before any
single barcode does, which is the normal state of a realtime run. The phrase
then read 'aggregate across N samples' and named nobody, so an operator could
see ACTION REQUIRED with no way to tell which barcode to act on. The threshold
distinction is kept: sub-threshold samples are named alongside the aggregate
qualifier, not promoted to triggering samples.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F6P7wEqXM1TmLN6on3S9DZ"
```

---

## Task 5: Stop a sample from vanishing from attribution without a word

Run this task only if Task 2 Step 5 classified the failure as cause C, D or E, or if
Task 3 Step 4 failed.

**Why:** `_load_per_sample_organisms` swallows three different outcomes into the same
silent `continue`: the sample's report was mid-rewrite and unparseable (real-time
rewrites each sample's cumulative report every batch, and the loader's stability window
is 1 second), the sample's rows all fell under `PER_SAMPLE_DISCOVERY_FLOOR`, and the
sample genuinely carries nothing. The first two are "not measured" and the third is a
negative result. The existing `attribution_failed` flag on the banner only fires when
*no* detection resolves at all, so a partial loss is invisible.

**Files:**
- Modify: `nanometa_live/app/tabs/dashboard_helpers.py:2110-2180`
  (`_load_per_sample_organisms`)
- Modify: `nanometa_live/app/tabs/dashboard_tab.py:421-440` (verdict banner
  attribution block)
- Test: `tests/test_realtime_attribution.py`

**Interfaces:**
- Consumes: `_load_per_sample_organisms(main_dir, available_samples, config)`.
- Produces: same return type, `Dict[int, List[Dict]]`, plus a new module-level
  function `unmeasured_samples(main_dir, available_samples, config) -> List[str]`
  returning the samples whose report could not be read on the most recent call.
  `dashboard_tab.update_verdict_banner` reads it to extend the existing
  `attribution_failed` note.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_realtime_attribution.py`:

```python
class TestAnUnreadableSampleIsReported:
    """A sample whose report could not be parsed is not a negative result.

    Realtime rewrites each sample's cumulative report every batch. A poll that
    lands inside that write window gets None from the parser, and the sample
    silently disappeared from attribution: identical on screen to a sample that
    genuinely carries nothing.
    """

    def test_an_unparseable_sample_is_listed_as_unmeasured(self, tmp_path):
        from nanometa_live.app.tabs.dashboard_helpers import (
            _load_per_sample_organisms,
            unmeasured_samples,
        )
        from nanometa_live.core.utils.loader_utils import clear_all_loader_caches

        results = tmp_path / "results"
        write_realtime_sample(results, "barcode05", 263, "Francisella tularensis", 900)

        # barcode06 mid-rewrite: present, empty, and freshly touched.
        truncated = results / "kraken2" / "barcode06.cumulative.kraken2.report.txt"
        truncated.write_text("")

        clear_all_loader_caches()
        available = ["All Samples", "barcode05", "barcode06"]
        taxid_to_samples = _load_per_sample_organisms(str(results), available, {})

        assert [r["sample"] for r in taxid_to_samples[263]] == ["barcode05"]
        assert unmeasured_samples(str(results), available, {}) == ["barcode06"]

    def test_a_readable_empty_sample_is_not_unmeasured(self, tmp_path):
        """A sample that parsed and carries nothing is a negative, not a gap."""
        from nanometa_live.app.tabs.dashboard_helpers import unmeasured_samples
        from nanometa_live.core.utils.loader_utils import clear_all_loader_caches

        results = tmp_path / "results"
        write_realtime_sample(results, "barcode05", 263, "Francisella tularensis", 900)
        write_realtime_sample(results, "barcode06", 9999, "Escherichia coli", 900)

        clear_all_loader_caches()
        available = ["All Samples", "barcode05", "barcode06"]

        assert unmeasured_samples(str(results), available, {}) == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_realtime_attribution.py::TestAnUnreadableSampleIsReported -x
```

Expected: FAIL with `ImportError: cannot import name 'unmeasured_samples'`.

- [ ] **Step 3: Record the gap in the loader**

In `nanometa_live/app/tabs/dashboard_helpers.py`, add a module-level registry above
`_load_per_sample_organisms`:

```python
# Samples whose per-sample report could not be read on the most recent
# attribution build, keyed by (main_dir, sample tuple). A realtime run rewrites
# each sample's cumulative report every batch, so a poll landing inside that
# write window gets None from the parser. Dropping the sample silently makes a
# missing measurement indistinguishable from a negative result, which is the
# distinction the verdict guards exist to preserve.
_unmeasured_lock = threading.Lock()
_unmeasured: Dict[tuple, List[str]] = {}


def unmeasured_samples(
    main_dir: str,
    available_samples: List[str],
    config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Samples that produced no readable report on the last attribution build.

    Runs the build if it has not run for this key, so a caller never has to
    order itself after the attribution pass.
    """
    key = (main_dir, tuple(s for s in available_samples if s != "All Samples"))
    with _unmeasured_lock:
        if key in _unmeasured:
            return list(_unmeasured[key])
    _load_per_sample_organisms(main_dir, available_samples, config)
    with _unmeasured_lock:
        return list(_unmeasured.get(key, []))
```

Then, inside `_load_per_sample_organisms`, track the gap. Replace the per-sample body's
early exits:

```python
    taxid_to_samples: Dict[int, List[Dict[str, Any]]] = {}
    unreadable: List[str] = []

    for sample in real_samples:
        is_nc = is_negative_control(sample, config)
        try:
            kraken_df = load_kraken_data(main_dir, sample)
            if kraken_df.empty:
                # Empty is ambiguous: no report on disk yet, or a report that
                # was mid-rewrite when this poll landed. Both are "not
                # measured", never "measured and clean".
                unreadable.append(sample)
                continue
            species_df = _species_discovery_df(kraken_df)
            if species_df.empty:
                # Parsed fine, nothing above the discovery floor. A real
                # negative for this sample; not a gap.
                continue
            ...
        except Exception as exc:
            logger.debug(f"Per-sample organism load failed for {sample}: {exc}")
            unreadable.append(sample)
```

and before the final return:

```python
    key = (main_dir, tuple(real_samples))
    with _unmeasured_lock:
        _unmeasured[key] = unreadable
        while len(_unmeasured) > 8:
            _unmeasured.pop(next(iter(_unmeasured)))
```

Add `import threading` at the top of the module if it is not already imported.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_realtime_attribution.py tests/test_organisms_memo.py \
  tests/test_attribution.py tests/test_alert_panel_attribution_gate.py -x
```

Expected: PASS.

- [ ] **Step 5: Surface the gap on the banner**

In `nanometa_live/app/tabs/dashboard_tab.py`, inside the `descriptor.needs_attribution`
block, after `triggering_attribution` is built:

```python
                from nanometa_live.app.tabs.dashboard_helpers import (
                    unmeasured_samples,
                )

                unread = unmeasured_samples(main_dir, resolved_samples, config)
                if unread:
                    # Not a failure of attribution, a gap in it. Naming the
                    # samples lets the operator retry rather than read the
                    # silence as a clean result for those barcodes.
                    attribution_note = (
                        f"{len(unread)} sample(s) not readable this poll: "
                        + ", ".join(unread[:3])
                        + (f", +{len(unread) - 3} more" if len(unread) > 3 else "")
                    )
                else:
                    attribution_note = None
```

Pass `attribution_note` through `_make_banner_content` alongside `attribution_failed`,
rendering it with the same italic style as the existing "Sample attribution
unavailable" line in `_attribution_children`.

- [ ] **Step 6: Test the banner wiring**

Append to `tests/test_realtime_attribution.py`:

```python
class TestTheBannerReportsUnmeasuredSamples:
    def test_an_unreadable_barcode_is_named_on_the_banner(self, tmp_path, monkeypatch):
        """The subhead must say a barcode could not be read this poll."""
        from tests.test_verdict_banner_callback import _run_verdict_banner

        monkeypatch.setattr(
            "nanometa_live.app.tabs.dashboard_tab.unmeasured_samples",
            lambda *a, **k: ["barcode06"],
            raising=False,
        )
        rendered = _run_verdict_banner(
            tmp_path,
            detections=[{"taxid": 1392, "name": "Bacillus anthracis",
                         "threat_level": "critical", "reads": 5000,
                         "threshold": 10}],
            taxid_to_samples={1392: [{"sample": "barcode05", "reads": 5000,
                                      "abundance": 90.0,
                                      "is_negative_control": False}]},
            available_samples=["All Samples", "barcode05", "barcode06"],
        )

        assert "barcode06" in rendered
        assert "not readable" in rendered
```

`_run_verdict_banner` (`tests/test_verdict_banner_callback.py:51`) registers the
dashboard callbacks on a throwaway app, extracts the unwrapped verdict-banner
function, patches the loader and watchlist seams, and returns the outputs serialised
to JSON. Reuse it rather than re-registering the app.

- [ ] **Step 7: Run the full dashboard test set**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_realtime_attribution.py tests/test_verdict_banner_callback.py \
  tests/test_verdict_selector.py tests/test_tick_call_counts.py -x
```

Expected: PASS, including `test_tick_call_counts.py` - `unmeasured_samples` must not
add a second attribution build per tick, which is why it reads the registry the build
already populated.

- [ ] **Step 8: Commit**

```bash
git add nanometa_live/app/tabs/dashboard_helpers.py \
        nanometa_live/app/tabs/dashboard_tab.py tests/test_realtime_attribution.py
git commit -m "fix(attribution): report samples whose report could not be read

_load_per_sample_organisms swallowed 'report mid-rewrite' and 'sample carries
nothing' into the same silent continue. Realtime rewrites each sample's
cumulative report every batch, so a poll landing in that window dropped the
barcode from attribution and the screen showed the same thing as a clean
barcode. The two are now separated and the banner names the gap.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F6P7wEqXM1TmLN6on3S9DZ"
```

---

## Task 6: Make the barcode reachable on a moderate-tier alert card

Run this task only if Task 2 Step 5 classified the failure as cause B.

**Why:** `_render_sample_attribution` collapses a "watched" tier hit spanning more than
one sample into a single count pill; the barcode names live in a popover that fills on
click. That was a deliberate scale decision (chips per sample per card serialised
17.8k-55k components at 24-96 barcodes). It is also the exact reported symptom for an
operator whose watchlist hits are moderate tier: the count is visible, the names are
one undiscoverable click away.

**Files:**
- Modify: `nanometa_live/app/components/attribution.py:41-140`
  (`_render_sample_attribution`)
- Test: `tests/test_pathogen_alert_attribution.py`

**Interfaces:**
- Consumes: `_render_sample_attribution(samples, tier, max_inline=3,
  attribution_taxid=None) -> Optional[html.Div]`.
- Produces: same signature. The moderate-tier multi-sample branch renders the top
  sample's name inline beside the count pill instead of the count alone.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pathogen_alert_attribution.py`:

```python
class TestModerateTierNamesItsTopSample:
    """A count pill alone hides the one fact the operator needs.

    Chips per sample are suppressed at watched tier for a real reason (component
    budget at 96 barcodes). Naming the highest-count sample costs one chip per
    card and keeps the popover for the rest.
    """

    def test_the_top_sample_is_named_inline(self):
        from nanometa_live.app.components.attribution import (
            _render_sample_attribution,
        )

        samples = [
            {"sample": "barcode05", "reads": 900, "abundance": 12.0,
             "is_negative_control": False},
            {"sample": "barcode06", "reads": 40, "abundance": 1.0,
             "is_negative_control": False},
        ]

        row = _render_sample_attribution(samples, "watched", attribution_taxid=263)

        rendered = str(row)
        assert "barcode05" in rendered
        assert "+1 more" in rendered or "2 samples" in rendered

    def test_a_single_sample_is_unchanged(self):
        from nanometa_live.app.components.attribution import (
            _render_sample_attribution,
        )

        samples = [{"sample": "barcode05", "reads": 900, "abundance": 12.0,
                    "is_negative_control": False}]

        assert "barcode05" in str(
            _render_sample_attribution(samples, "watched", attribution_taxid=263)
        )
```

- [ ] **Step 2: Run it to verify it fails**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_pathogen_alert_attribution.py::TestModerateTierNamesItsTopSample -x
```

Expected: FAIL on the first test - `max_inline` is set to 0 for the multi-sample
watched tier, so no chip is built and no barcode name appears.

- [ ] **Step 3: Show one chip instead of none**

In `nanometa_live/app/components/attribution.py`, change the summarise branch:

```python
    # A multi-sample watched hit shows its highest-count sample plus a count
    # pill, rather than the count alone. The full list stays in the popover.
    # Chips per sample were suppressed here for the component budget at 96
    # barcodes (round-2 audit); one chip per card is 1/96th of that cost and
    # is the difference between an operator seeing a barcode and not.
    summarise_only = tier == "watched" and len(samples) > 1
    if summarise_only:
        max_inline = 1
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n nf-core python -m pytest -o addopts="" -q \
  tests/test_pathogen_alert_attribution.py tests/test_component_budgets.py -x
```

Expected: PASS. `tests/test_component_budgets.py` is the fence on card component
counts; if it fails, the budget is the authority - reduce elsewhere on the card rather
than reverting this, and record the trade in the audit doc.

- [ ] **Step 5: Commit**

```bash
git add nanometa_live/app/components/attribution.py \
        tests/test_pathogen_alert_attribution.py
git commit -m "fix(alerts): name the top sample on a multi-sample moderate hit

A watched-tier hit spanning several barcodes collapsed to a count pill with the
names only in a click-to-open popover, so the card showed that a detection had
samples without showing which. One chip per card restores the name at 1/96th of
the cost the original suppression was avoiding.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F6P7wEqXM1TmLN6on3S9DZ"
```

---

## Task 7: Re-run the live real-time verification

**Files:**
- Create: `docs/audit/realtime-attribution-2026-09-01.md`

**Interfaces:**
- Consumes: the fixes from whichever of Tasks 4-6 ran.
- Produces: the audit document, and a pass/fail against the Global Constraints
  acceptance criterion.

- [ ] **Step 1: Run the full suite before touching the live rig**

```bash
conda run -n nf-core python -m pytest -q
conda run -n nf-core python -m pytest --cov=nanometa_live --cov-report=term-missing -q
```

Expected: all pass, coverage at or above the `fail_under = 74` floor. Do not proceed to
the live run with a red suite.

- [ ] **Step 2: Repeat the Task 1 live procedure exactly**

```bash
~/nanometa-demo/scripts/stop_all.sh
rm -rf ~/nanometa-demo/runs/demo3_results ~/nanometa-demo/data/realtime_watch
mkdir -p ~/nanometa-demo/data/realtime_watch
~/nanometa-demo/scripts/run_demo3.sh
# click Start Analysis, wait for SCREENING, then:
~/nanometa-demo/scripts/feed_demo3.sh
```

- [ ] **Step 3: Record the same five surfaces at the verdict flip and at the end**

Same five as Task 1 Step 5. Every one must show a barcode name or state why it cannot.
Record the verbatim text of each.

- [ ] **Step 4: Confirm batch mode did not regress**

```bash
~/nanometa-demo/scripts/run_demo1.sh
```

The batch-mode "Triggered by:" line must still name the same barcodes it named in
Task 1 Step 2, with the same wording where nothing in this plan changed it.

- [ ] **Step 5: Write the audit document**

Create `docs/audit/realtime-attribution-2026-09-01.md` covering:
- the reported symptom and the surface it was actually on,
- the probe output that identified the cause, with the measured numbers,
- each hypothesis that was ruled out and the evidence that ruled it out,
- the fixes, with before and after text of each affected surface,
- what was verified live versus only by test, stated plainly. Anything not observed on
  the live rig is not reported as verified.

- [ ] **Step 6: Commit**

```bash
git add docs/audit/realtime-attribution-2026-09-01.md
git commit -m "docs(audit): realtime per-sample attribution audit, 2026-09-01

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F6P7wEqXM1TmLN6on3S9DZ"
```

---

## Task 8: Record the invariant so it cannot silently regress

**Files:**
- Modify: `CLAUDE.md` (the "Per-sample attribution has one resolver" paragraph)

**Interfaces:**
- Consumes: the fixes from Tasks 4-6.
- Produces: a documented invariant naming the tests that pin it.

- [ ] **Step 1: Extend the attribution paragraph**

Append to the "Per-sample attribution has one resolver" section of `CLAUDE.md`, using
only the parts that the audit actually established:

```markdown
**Real-time attribution has two failure modes batch mode does not.** The
verdict is decided on the aggregate, which crosses a watchlist entry's
`alert_threshold` minutes before any single barcode does, so for most of a
real-time run every sample is a `below_threshold_sample`. That branch of
`_attribution_phrase` now names the top samples alongside the aggregate
qualifier rather than rendering a bare count, because a detection that will
not say which barcode carries it is not actionable. Separately,
`_load_per_sample_organisms` distinguishes "the report could not be read this
poll" from "this sample carries nothing": real-time rewrites each sample's
cumulative report every batch, and a poll landing inside that window used to
drop the barcode from attribution silently. `unmeasured_samples` exposes the
gap and the verdict banner names it. Regression-covered in
`tests/test_realtime_attribution.py`, which owns the only test fixture in the
suite shaped like a real-time results tree (`tests/fixtures/realtime_attribution/`);
every other attribution test writes a flat `<sample>.kraken2.report.txt` and
therefore cannot see either failure. Use
`scripts/audit_realtime_attribution.py <results_dir> --config <config.yaml>` to
diagnose a live or captured outdir hop by hop.
```

- [ ] **Step 2: Verify the referenced paths exist**

```bash
ls tests/test_realtime_attribution.py tests/fixtures/realtime_attribution \
   scripts/audit_realtime_attribution.py
```

Expected: all three present. A CLAUDE.md paragraph naming a path that does not exist is
worse than no paragraph.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the realtime per-sample attribution invariants

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F6P7wEqXM1TmLN6on3S9DZ"
```

---

## Notes for the executor

- **Tasks 4, 5 and 6 are conditional.** Run only those the Task 2 probe implicated.
  Running all three without evidence changes three behaviours to fix one defect and
  makes the audit document unfalsifiable.
- **The `nanometa` conda env is not the test env.** It has Dash but neither
  `pytest-xdist` nor `pytest-cov`; use `nf-core` for anything with coverage.
- **Do not shrink the file-stability window** (`_is_file_stable`, effective threshold
  1 second) as a shortcut for cause C. It is the mid-write guard, and loosening it
  trades a visible gap for corrupt frames.
- **Do not remove the `alert_threshold` gate** in `build_pathogen_attribution` as a
  shortcut for cause A. Ten barcodes at 50 reads each must not all be reported as
  triggering for a pathogen with a threshold of 100; the fix is in the wording, not the
  gate.
- **Ports.** 8061 is demo 1 (batch control), 8063 is demo 3 (real-time). Free them with
  `~/nanometa-demo/scripts/stop_all.sh` before each run.
