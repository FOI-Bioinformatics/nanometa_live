"""Deterministic N-sample result trees for the scaling harness.

Three layouts are produced, chosen so that the loader dispatches down a
different real code path in each:

``batch``
    ``kraken2/<sample>.kraken2.report.txt`` plus flat ``seqkit/<sample>.tsv``
    and ``fastp/<sample>.fastp.json``. Exercises the standard-report branch
    of ``_discover_sample_reports``.

``realtime_incremental``
    ``kraken2/<sample>/batch_reports/*.kraken2.report.txt`` with the
    ``kraken2/<sample>/stats/batch_N_report_stats.json`` marker, and
    ``seqkit/<sample>/batch_stats/*.tsv`` with no flat companion. Exercises
    full batch aggregation.

``realtime_cumulative``
    As above plus ``kraken2/<sample>.cumulative.kraken2.report.txt``, which
    short-circuits the batch files entirely.

Two marker files are load-bearing. Without
``stats/batch_N_report_stats.json`` the loader treats the batch reports as
cumulative snapshots and reads only the highest-numbered one, so the harness
would silently measure a fraction of the intended work.
``_is_incremental_seqkit_layout`` likewise requires batch TSVs *and* the
absence of the flat TSV. ``build_fixture`` asserts both detectors agree with
the requested layout before returning.

Files are backdated with ``os.utime``. ``loader_utils._is_file_stable``
rejects anything younger than about one second, so a freshly written tree
makes every loader return empty and the harness would measure nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LAYOUTS: Tuple[str, ...] = ("batch", "realtime_incremental", "realtime_cumulative")

_DONE_MARKER = ".perf_fixture_done"

# Rank scaffold above the species level. Fan-out is fixed so the taxa count
# is a deterministic function of the requested species count.
_DOMAINS = 2
_CLASSES_PER_DOMAIN = 3
_GENERA_PER_CLASS = 5

# Taxid blocks, chosen to avoid colliding with the reserved 0 (unclassified)
# and 1 (root) that Kraken2 uses.
_TAXID_DOMAIN_BASE = 100
_TAXID_CLASS_BASE = 1_000
_TAXID_GENUS_BASE = 10_000
_TAXID_SPECIES_BASE = 100_000


@dataclass(frozen=True)
class FixtureSpec:
    """Everything that determines the shape of a generated tree."""

    n_samples: int
    layout: str = "batch"
    taxa_per_report: int = 300
    batches_per_sample: int = 20
    seed: int = 1337
    write_manifest: bool = False

    def __post_init__(self) -> None:
        if self.layout not in LAYOUTS:
            raise ValueError(
                f"unknown layout {self.layout!r}; expected one of {LAYOUTS}"
            )
        if self.n_samples < 1:
            raise ValueError("n_samples must be >= 1")

    @property
    def key(self) -> str:
        manifest = "-man" if self.write_manifest else ""
        return (
            f"{self.layout}-n{self.n_samples}"
            f"-t{self.taxa_per_report}-b{self.effective_batches}"
            f"-s{self.seed}{manifest}"
        )

    @property
    def effective_batches(self) -> int:
        """Batch count actually written; the flat layout has none."""
        return 0 if self.layout == "batch" else max(1, self.batches_per_sample)

    @property
    def sample_names(self) -> List[str]:
        return [f"barcode{i:02d}" for i in range(1, self.n_samples + 1)]

    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# Deterministic pseudo-random stream
# --------------------------------------------------------------------------

def _rng(seed: int, *salt: object) -> int:
    """A stable integer derived from a seed and arbitrary salt.

    A hash is used rather than :mod:`random` so that generating sample 17 in
    isolation produces the same numbers as generating it as part of a
    24-sample run. That property is what makes the N series comparable.
    """
    raw = "|".join([str(seed)] + [str(s) for s in salt])
    return int(hashlib.sha256(raw.encode()).hexdigest()[:12], 16)


def _spread(seed: int, lo: int, hi: int, *salt: object) -> int:
    """A stable integer in ``[lo, hi]``."""
    if hi <= lo:
        return lo
    return lo + _rng(seed, *salt) % (hi - lo + 1)


# --------------------------------------------------------------------------
# Kraken2 report synthesis
# --------------------------------------------------------------------------

def _taxonomy(n_species: int) -> List[Tuple[int, str, int, str]]:
    """Build the scaffold as ``(depth, rank, taxid, name)`` in report order.

    Depth is the indentation level Kraken2 writes into the name column, from
    which the loader reconstructs ``parent_taxid``.
    """
    rows: List[Tuple[int, str, int, str]] = []
    per_genus = max(1, -(-n_species // (_DOMAINS * _CLASSES_PER_DOMAIN * _GENERA_PER_CLASS)))
    emitted = 0

    for d in range(_DOMAINS):
        d_taxid = _TAXID_DOMAIN_BASE + d
        rows.append((1, "D", d_taxid, f"Domain_{d}"))
        for c in range(_CLASSES_PER_DOMAIN):
            c_taxid = _TAXID_CLASS_BASE + d * _CLASSES_PER_DOMAIN + c
            rows.append((2, "C", c_taxid, f"Class_{d}_{c}"))
            for g in range(_GENERA_PER_CLASS):
                g_idx = (d * _CLASSES_PER_DOMAIN + c) * _GENERA_PER_CLASS + g
                g_taxid = _TAXID_GENUS_BASE + g_idx
                rows.append((3, "G", g_taxid, f"Genus_{g_idx}"))
                for s in range(per_genus):
                    if emitted >= n_species:
                        break
                    s_taxid = _TAXID_SPECIES_BASE + emitted
                    rows.append(
                        (4, "S", s_taxid, f"Genus_{g_idx} species_{emitted}")
                    )
                    emitted += 1
    return rows


def _species_count(taxa_per_report: int) -> int:
    scaffold = _DOMAINS * (1 + _CLASSES_PER_DOMAIN * (1 + _GENERA_PER_CLASS))
    # 2 extra rows for the unclassified and root lines.
    return max(1, taxa_per_report - scaffold - 2)


def _render_kraken_report(
    spec: FixtureSpec,
    sample: str,
    batch: Optional[int],
    total_reads: int,
) -> str:
    """Render one Kraken2 report as text.

    Column order is the Kraken2 default: percentage, clade-cumulative reads,
    directly-assigned reads, rank code, taxid, indented name.
    """
    n_species = _species_count(spec.taxa_per_report)
    scaffold = _taxonomy(n_species)
    salt = (sample, batch if batch is not None else "flat")

    # Assign directly-observed reads to species only, mirroring a real
    # report where higher ranks carry clade totals rather than assignments.
    species_rows = [r for r in scaffold if r[1] == "S"]
    weights = [
        _spread(spec.seed, 1, 1000, "w", sample, taxid) for _, _, taxid, _ in species_rows
    ]
    weight_total = sum(weights) or 1

    classified = int(total_reads * 0.78)
    unclassified = total_reads - classified

    species_reads: Dict[int, int] = {}
    assigned = 0
    for (_, _, taxid, _), w in zip(species_rows, weights):
        r = classified * w // weight_total
        species_reads[taxid] = r
        assigned += r
    # Push the rounding remainder onto the first species so the clade totals
    # add up exactly.
    if species_rows:
        species_reads[species_rows[0][2]] += classified - assigned

    # Roll species reads up the scaffold to get clade-cumulative counts.
    cumul: Dict[int, int] = {taxid: 0 for _, _, taxid, _ in scaffold}
    stack: List[Tuple[int, int]] = []
    for depth, rank, taxid, _name in scaffold:
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if rank == "S":
            r = species_reads[taxid]
            cumul[taxid] += r
            for _, ancestor in stack:
                cumul[ancestor] += r
        stack.append((depth, taxid))

    lines: List[str] = []

    def emit(pct: float, cumul_reads: int, reads: int, rank: str,
             taxid: int, depth: int, name: str) -> None:
        indent = "  " * depth
        lines.append(
            f"{pct:.2f}\t{cumul_reads}\t{reads}\t{rank}\t{taxid}\t{indent}{name}"
        )

    denom = total_reads or 1
    emit(unclassified / denom * 100, unclassified, unclassified, "U", 0, 0,
         "unclassified")
    emit(classified / denom * 100, classified, 0, "R", 1, 0, "root")
    for depth, rank, taxid, name in scaffold:
        c = cumul[taxid]
        direct = species_reads.get(taxid, 0)
        emit(c / denom * 100, c, direct, rank, taxid, depth, name)

    return "\n".join(lines) + "\n"


def _reads_for(spec: FixtureSpec, sample: str, batch: Optional[int]) -> int:
    base = _spread(spec.seed, 40_000, 120_000, "reads", sample)
    if batch is None:
        return base
    # Each incremental batch is a delta, so divide the run total across them.
    return max(500, base // spec.effective_batches)


# --------------------------------------------------------------------------
# QC file synthesis
# --------------------------------------------------------------------------

_SEQKIT_COLUMNS = (
    "file", "format", "type", "num_seqs", "sum_len", "min_len", "avg_len",
    "max_len", "Q1", "Q2", "Q3", "sum_gap", "N50", "N50_num", "Q20(%)",
    "Q30(%)", "AvgQual", "GC(%)",
)


def _render_seqkit_tsv(spec: FixtureSpec, sample: str,
                       batch: Optional[int]) -> str:
    reads = _reads_for(spec, sample, batch)
    avg_len = _spread(spec.seed, 900, 4500, "len", sample, batch)
    sum_len = reads * avg_len
    row = {
        "file": f"{sample}.fastq.gz" if batch is None
        else f"{sample}_batch{batch}.fastq.gz",
        "format": "FASTQ",
        "type": "DNA",
        "num_seqs": reads,
        "sum_len": sum_len,
        "min_len": 200,
        "avg_len": avg_len,
        "max_len": avg_len * 4,
        "Q1": int(avg_len * 0.75),
        "Q2": avg_len,
        "Q3": int(avg_len * 1.5),
        "sum_gap": 0,
        "N50": avg_len,
        "N50_num": reads // 2,
        "Q20(%)": round(_spread(spec.seed, 8000, 9700, "q20", sample, batch) / 100, 2),
        "Q30(%)": round(_spread(spec.seed, 5000, 8500, "q30", sample, batch) / 100, 2),
        "AvgQual": round(_spread(spec.seed, 1100, 1800, "q", sample, batch) / 100, 2),
        "GC(%)": round(_spread(spec.seed, 3800, 6200, "gc", sample, batch) / 100, 2),
    }
    header = "\t".join(_SEQKIT_COLUMNS)
    values = "\t".join(str(row[c]) for c in _SEQKIT_COLUMNS)
    return f"{header}\n{values}\n"


def _render_fastp_json(spec: FixtureSpec, sample: str) -> str:
    reads_before = _reads_for(spec, sample, None)
    reads_after = int(reads_before * 0.93)
    avg_len = _spread(spec.seed, 900, 4500, "len", sample, None)
    payload = {
        "summary": {
            "before_filtering": {
                "total_reads": reads_before,
                "total_bases": reads_before * avg_len,
                "q20_rate": 0.94,
                "q30_rate": 0.81,
                "read1_mean_length": avg_len,
            },
            "after_filtering": {
                "total_reads": reads_after,
                "total_bases": reads_after * avg_len,
                "q20_rate": 0.96,
                "q30_rate": 0.86,
                "read1_mean_length": avg_len,
            },
        },
        "filtering_result": {
            "passed_filter_reads": reads_after,
            "low_quality_reads": reads_before - reads_after,
        },
    }
    return json.dumps(payload, indent=2)


# --------------------------------------------------------------------------
# Tree construction
# --------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_batch_layout(spec: FixtureSpec, root: Path) -> None:
    for sample in spec.sample_names:
        _write(
            root / "kraken2" / f"{sample}.kraken2.report.txt",
            _render_kraken_report(spec, sample, None, _reads_for(spec, sample, None)),
        )
        _write(root / "seqkit" / f"{sample}.tsv",
               _render_seqkit_tsv(spec, sample, None))
        _write(root / "fastp" / f"{sample}.fastp.json",
               _render_fastp_json(spec, sample))


def _build_realtime_layout(spec: FixtureSpec, root: Path,
                           cumulative: bool) -> None:
    for sample in spec.sample_names:
        sample_dir = root / "kraken2" / sample
        for b in range(1, spec.effective_batches + 1):
            _write(
                sample_dir / "batch_reports" / f"batch_{b}.kraken2.report.txt",
                _render_kraken_report(spec, sample, b, _reads_for(spec, sample, b)),
            )
            # The marker that makes _is_incremental_layout return True. Without
            # it the loader reads only the highest-numbered batch.
            _write(
                sample_dir / "stats" / f"batch_{b}_report_stats.json",
                json.dumps({"batch_id": b, "sample": sample,
                            "reads": _reads_for(spec, sample, b)}),
            )
            _write(
                root / "seqkit" / sample / "batch_stats" / f"batch_{b}.tsv",
                _render_seqkit_tsv(spec, sample, b),
            )
        if cumulative:
            _write(
                root / "kraken2" / f"{sample}.cumulative.kraken2.report.txt",
                _render_kraken_report(
                    spec, sample, None, _reads_for(spec, sample, None)
                ),
            )
        # No flat seqkit/<sample>.tsv: its absence is half of what
        # _is_incremental_seqkit_layout keys on.


def _write_manifest(spec: FixtureSpec, root: Path) -> None:
    payload = {
        "samples": spec.sample_names,
        "generated_by": "scripts.perf.fixtures",
        "layout": spec.layout,
    }
    _write(root / "canonical" / "_manifest.json", json.dumps(payload, indent=2))


def backdate(root: Path, age_s: float = 5.0) -> None:
    """Age every file in the tree so the stability check accepts it.

    ``_is_file_stable`` requires an mtime at least one second old. A tree
    written and read in the same instant yields empty frames from every
    loader, which would make the harness measure nothing at all.
    """
    stamp = time.time() - age_s
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            target = os.path.join(dirpath, name)
            try:
                os.utime(target, (stamp, stamp))
            except OSError:
                continue


# A process-wide counter so two consecutive mutations never land on the same
# mtime. _get_path_fingerprint compares (mtime, size, count) for equality, so
# an identical stamp would silently turn a "changed" poll into a quiet one.
_mutation_seq = 0


def _restamp(path: Path) -> None:
    global _mutation_seq
    _mutation_seq += 1
    stamp = time.time() - 5.0 + _mutation_seq * 0.001
    os.utime(path, (stamp, stamp))


def _newest_report(root: Path, sample: str, layout: str) -> Optional[Path]:
    if layout == "batch":
        candidate = root / "kraken2" / f"{sample}.kraken2.report.txt"
        return candidate if candidate.exists() else None
    batch_dir = root / "kraken2" / sample / "batch_reports"
    if not batch_dir.is_dir():
        return None
    batches = sorted(batch_dir.glob("batch_*.kraken2.report.txt"))
    return batches[-1] if batches else None


def touch_sample(root: Path, sample: str, layout: str) -> None:
    """Advance exactly one sample, as a realtime batch would.

    The highest-numbered existing report is rewritten in place rather than a
    new one appended, so repeated calls cost the same and the file count
    stays constant. Content changes (a trailing comment line) so the size
    component of the fingerprint moves too.
    """
    target = _newest_report(root, sample, layout)
    if target is None:
        return
    global _mutation_seq
    text = target.read_text()
    text += f"# perf-mutation {_mutation_seq}\n"
    target.write_text(text)
    _restamp(target)


def touch_all(root: Path, layout: str) -> None:
    """Advance every sample, the worst case for cache invalidation."""
    kraken_dir = root / "kraken2"
    if not kraken_dir.is_dir():
        return
    if layout == "batch":
        samples = [p.name.split(".")[0]
                   for p in kraken_dir.glob("*.kraken2.report.txt")]
    else:
        samples = [p.name for p in kraken_dir.iterdir() if p.is_dir()]
    for sample in sorted(samples):
        touch_sample(root, sample, layout)


def build_fixture(spec: FixtureSpec, base: Path) -> Path:
    """Materialise the tree for ``spec`` under ``base`` and validate it.

    Idempotent: an existing tree whose recorded spec digest matches is reused
    untouched, so fixture construction never lands inside a timed region.
    """
    root = Path(base) / spec.key
    marker = root / _DONE_MARKER
    if marker.exists() and marker.read_text().strip() == spec.digest():
        return root

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    if spec.layout == "batch":
        _build_batch_layout(spec, root)
    else:
        _build_realtime_layout(
            spec, root, cumulative=spec.layout == "realtime_cumulative"
        )

    # Present but empty: the freshness fingerprint walks it every poll, and a
    # missing directory would understate that cost.
    (root / "validation").mkdir(exist_ok=True)

    if spec.write_manifest:
        _write_manifest(spec, root)

    backdate(root)
    _validate(spec, root)

    marker.write_text(spec.digest())
    os.utime(marker, (time.time() - 5.0, time.time() - 5.0))
    return root


def _validate(spec: FixtureSpec, root: Path) -> None:
    """Fail loudly if the tree does not dispatch down the intended path."""
    from nanometa_live.core.utils.classification_loaders import (
        _is_incremental_layout, load_kraken_data,
    )
    from nanometa_live.core.utils.qc_loaders import _is_incremental_seqkit_layout
    from nanometa_live.core.utils.sample_detector import get_available_samples

    kraken_dir = str(root / "kraken2")
    seqkit_dir = str(root / "seqkit")
    incremental_expected = spec.layout != "batch"

    got_kraken = _is_incremental_layout(kraken_dir)
    if got_kraken is not incremental_expected:
        raise AssertionError(
            f"{spec.key}: _is_incremental_layout returned {got_kraken}, "
            f"expected {incremental_expected}. The loader would read a "
            f"different set of reports than this layout intends."
        )

    got_seqkit = _is_incremental_seqkit_layout(seqkit_dir)
    if got_seqkit is not incremental_expected:
        raise AssertionError(
            f"{spec.key}: _is_incremental_seqkit_layout returned {got_seqkit}, "
            f"expected {incremental_expected}."
        )

    from scripts.perf.instrument import reset_caches
    reset_caches()

    detected = [s for s in get_available_samples(str(root)) if s != "All Samples"]
    if len(detected) != spec.n_samples:
        raise AssertionError(
            f"{spec.key}: sample detection found {len(detected)} samples "
            f"({detected[:5]}...), expected {spec.n_samples}."
        )

    probe = load_kraken_data(str(root), spec.sample_names[0])
    if probe.empty:
        raise AssertionError(
            f"{spec.key}: load_kraken_data returned an empty frame. The "
            f"most likely cause is that backdating did not take effect, so "
            f"_is_file_stable rejected every report."
        )
    reset_caches()
