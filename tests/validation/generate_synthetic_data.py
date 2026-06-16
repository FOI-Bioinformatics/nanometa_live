"""
Generate synthetic Nanometa Live test data for end-to-end validation.

Creates 5 barcodes with known organisms from built-in watchlists:
- barcode01: Clinical (M. tuberculosis, S. aureus + background)
- barcode02: Foodborne (L. monocytogenes, S. enterica + background)
- barcode03: Environmental/water (L. pneumophila, low E. coli + diverse background)
- barcode04: Negative control (background flora only)
- barcode05: F. tularensis TUL4 amplicon (single-copy gene target)
"""
import json
import os
import time
from pathlib import Path


def _kraken_line(pct, cumul, reads, rank, taxid, name):
    """Format one Kraken2 report line."""
    return f"{pct:.2f}\t{cumul}\t{reads}\t{rank}\t{taxid}\t{name}"


def _build_report_lines(total_reads, organisms):
    """Build a complete Kraken2 report with unique taxid rows.

    Aggregates taxonomy nodes that share the same taxid so each taxid
    appears exactly once, matching real Kraken2 report format.

    Args:
        total_reads: Total number of reads in the sample.
        organisms: List of dicts with taxonomy and read count info.

    Returns:
        List of formatted Kraken2 report lines.
    """
    bg_reads_each = max(50, int(total_reads * 0.02))

    # Collect all nodes: taxid -> {rank, name, reads (direct), cumul}
    nodes = {}

    # Add organisms and their lineage
    for org in organisms:
        lineage = [
            ("P", org.get("phylum_taxid", 0), f"    {org['phylum']}"),
            ("C", org.get("class_taxid", 0), f"      {org['phylum_class']}"),
            ("O", org.get("order_taxid", 0), f"        {org['order']}"),
            ("F", org.get("family_taxid", 0), f"          {org['family']}"),
            ("G", org.get("genus_taxid", 0), f"            {org['genus']}"),
            ("S", org["taxid"], f"              {org['species']}"),
        ]
        for rank, taxid, name in lineage:
            if taxid not in nodes:
                nodes[taxid] = {"rank": rank, "name": name, "reads": 0, "cumul": 0}
            if rank == "S":
                nodes[taxid]["reads"] = org["reads"]
            nodes[taxid]["cumul"] += org["reads"]

    # Background: C. acnes
    bg_lineage_acnes = [
        ("P", 201174, "    Actinomycetota"),
        ("C", 1760, "      Actinomycetia"),
        ("O", 31957, "        Propionibacteriales"),
        ("F", 31958, "          Propionibacteriaceae"),
        ("G", 1743, "            Cutibacterium"),
        ("S", 1747, "              Cutibacterium acnes"),
    ]
    for rank, taxid, name in bg_lineage_acnes:
        if taxid not in nodes:
            nodes[taxid] = {"rank": rank, "name": name, "reads": 0, "cumul": 0}
        if rank == "S":
            nodes[taxid]["reads"] = bg_reads_each
        nodes[taxid]["cumul"] += bg_reads_each

    # Background: B. subtilis
    bg_lineage_bsub = [
        ("P", 1239, "    Bacillota"),
        ("C", 91061, "      Bacilli"),
        ("O", 1385, "        Bacillales"),
        ("F", 186817, "          Bacillaceae"),
        ("G", 1386, "            Bacillus"),
        ("S", 1423, "              Bacillus subtilis"),
    ]
    for rank, taxid, name in bg_lineage_bsub:
        if taxid not in nodes:
            nodes[taxid] = {"rank": rank, "name": name, "reads": 0, "cumul": 0}
        if rank == "S":
            nodes[taxid]["reads"] = bg_reads_each
        nodes[taxid]["cumul"] += bg_reads_each

    # Calculate totals
    total_classified = sum(n["reads"] for n in nodes.values())
    unclassified = total_reads - total_classified

    # Build lines in order: U, R, D, then by rank depth
    lines = []
    lines.append(_kraken_line(
        unclassified / total_reads * 100, unclassified, unclassified,
        "U", 0, "unclassified"
    ))
    lines.append(_kraken_line(
        total_classified / total_reads * 100, total_classified, 0,
        "R", 1, "root"
    ))
    lines.append(_kraken_line(
        total_classified / total_reads * 100, total_classified, 0,
        "D", 2, "  Bacteria"
    ))

    # Output by rank order, sorted by cumulative reads within each rank
    rank_order = ["P", "C", "O", "F", "G", "S"]
    for rank in rank_order:
        rank_nodes = [(tid, n) for tid, n in nodes.items() if n["rank"] == rank]
        rank_nodes.sort(key=lambda x: x[1]["cumul"], reverse=True)
        for taxid, node in rank_nodes:
            pct = node["cumul"] / total_reads * 100
            lines.append(_kraken_line(
                pct, node["cumul"], node["reads"],
                node["rank"], taxid, node["name"]
            ))

    return lines


BARCODE01_CLINICAL = [
    {
        "phylum": "Actinomycetota", "phylum_taxid": 201174,
        "phylum_class": "Actinomycetia", "class_taxid": 1760,
        "order": "Mycobacteriales", "order_taxid": 85007,
        "family": "Mycobacteriaceae", "family_taxid": 1762,
        "genus": "Mycobacterium", "genus_taxid": 1763,
        "species": "Mycobacterium tuberculosis", "taxid": 1773,
        "reads": 3500,
    },
    {
        "phylum": "Bacillota", "phylum_taxid": 1239,
        "phylum_class": "Bacilli", "class_taxid": 91061,
        "order": "Bacillales", "order_taxid": 1385,
        "family": "Staphylococcaceae", "family_taxid": 90964,
        "genus": "Staphylococcus", "genus_taxid": 1279,
        "species": "Staphylococcus aureus", "taxid": 1280,
        "reads": 2800,
    },
]

BARCODE02_FOODBORNE = [
    {
        "phylum": "Bacillota", "phylum_taxid": 1239,
        "phylum_class": "Bacilli", "class_taxid": 91061,
        "order": "Lactobacillales", "order_taxid": 186826,
        "family": "Listeriaceae", "family_taxid": 186820,
        "genus": "Listeria", "genus_taxid": 1637,
        "species": "Listeria monocytogenes", "taxid": 1639,
        "reads": 4200,
    },
    {
        "phylum": "Pseudomonadota", "phylum_taxid": 1224,
        "phylum_class": "Gammaproteobacteria", "class_taxid": 1236,
        "order": "Enterobacterales", "order_taxid": 91347,
        "family": "Enterobacteriaceae", "family_taxid": 543,
        "genus": "Salmonella", "genus_taxid": 590,
        "species": "Salmonella enterica", "taxid": 28901,
        "reads": 3100,
    },
]

BARCODE03_WATER = [
    {
        "phylum": "Pseudomonadota", "phylum_taxid": 1224,
        "phylum_class": "Gammaproteobacteria", "class_taxid": 1236,
        "order": "Legionellales", "order_taxid": 118969,
        "family": "Legionellaceae", "family_taxid": 444,
        "genus": "Legionella", "genus_taxid": 445,
        "species": "Legionella pneumophila", "taxid": 446,
        "reads": 2500,
    },
    {
        "phylum": "Pseudomonadota", "phylum_taxid": 1224,
        "phylum_class": "Gammaproteobacteria", "class_taxid": 1236,
        "order": "Enterobacterales", "order_taxid": 91347,
        "family": "Enterobacteriaceae", "family_taxid": 543,
        "genus": "Escherichia", "genus_taxid": 561,
        "species": "Escherichia coli", "taxid": 562,
        "reads": 150,
    },
    {
        "phylum": "Pseudomonadota", "phylum_taxid": 1224,
        "phylum_class": "Alphaproteobacteria", "class_taxid": 28211,
        "order": "Sphingomonadales", "order_taxid": 204457,
        "family": "Sphingomonadaceae", "family_taxid": 41297,
        "genus": "Sphingomonas", "genus_taxid": 13687,
        "species": "Sphingomonas paucimobilis", "taxid": 13689,
        "reads": 800,
    },
]

BARCODE04_NEGATIVE = []

BARCODE05_AMPLICON = [
    {
        "phylum": "Pseudomonadota", "phylum_taxid": 1224,
        "phylum_class": "Gammaproteobacteria", "class_taxid": 1236,
        "order": "Thiomacrales", "order_taxid": 335192,
        "family": "Coxiellaceae", "family_taxid": 802,
        "genus": "Francisella", "genus_taxid": 258,
        "species": "Francisella tularensis", "taxid": 263,
        "reads": 3800,
    },
]


def _generate_fastp_json(total_reads):
    """Generate a realistic FASTP JSON for the given total reads."""
    passed = int(total_reads * 0.92)
    low_q = int(total_reads * 0.05)
    too_short = int(total_reads * 0.02)
    too_many_n = total_reads - passed - low_q - too_short
    return {
        "summary": {
            "before_filtering": {
                "total_reads": total_reads,
                "total_bases": total_reads * 1500,
                "q20_bases": int(total_reads * 1500 * 0.95),
                "q30_bases": int(total_reads * 1500 * 0.85),
                "q20_rate": 0.95,
                "q30_rate": 0.85,
                "read1_mean_length": 1500,
                "mean_length": 1500,
                "gc_content": 0.45,
            },
            "after_filtering": {
                "total_reads": passed,
                "total_bases": passed * 1520,
                "q20_bases": int(passed * 1520 * 0.97),
                "q30_bases": int(passed * 1520 * 0.92),
                "q20_rate": 0.97,
                "q30_rate": 0.92,
                "read1_mean_length": 1520,
                "mean_length": 1520,
                "gc_content": 0.46,
            },
        },
        "filtering_result": {
            "passed_filter_reads": passed,
            "low_quality_reads": low_q,
            "too_short_reads": too_short,
            "too_many_N_reads": too_many_n,
        },
        "adapter_cutting": {
            "adapter_trimmed_reads": int(total_reads * 0.15),
            "adapter_trimmed_bases": int(total_reads * 0.15) * 20,
        },
    }


def _generate_paf_lines(ref_name, ref_length, num_reads, seed=42):
    """Generate synthetic PAF alignment lines for coverage testing."""
    import random
    rng = random.Random(seed)
    lines = []
    for i in range(num_reads):
        read_len = rng.randint(500, 5000)
        tstart = rng.randint(0, max(0, ref_length - read_len))
        tend = min(tstart + read_len, ref_length)
        qlen = tend - tstart
        mapq = rng.choice([0, 10, 20, 30, 40, 50, 60])
        nmatch = int(qlen * rng.uniform(0.85, 0.99))
        line = "\t".join([
            f"read_{i}", str(qlen), "0", str(qlen),
            "+",
            ref_name, str(ref_length), str(tstart), str(tend),
            str(nmatch), str(qlen), str(mapq),
        ])
        lines.append(line)
    return lines


def _generate_amplicon_paf_lines(ref_name, ref_length, window_start, window_len,
                                 num_reads, seed=16):
    """Generate PAF lines emulating a full-length amplicon (e.g. 16S rRNA).

    All reads align inside a narrow ``window_len`` window of an otherwise large
    ``ref_length`` reference -- the realistic minimap2 output when ~1500 bp 16S
    reads map to the 16S locus of a multi-Mb genome. Drives the amplicon
    coverage-detection tests deterministically without a read simulator.
    """
    import random
    rng = random.Random(seed)
    lines = []
    for i in range(num_reads):
        rstart = window_start + rng.randint(0, max(1, window_len // 10))
        rend = min(window_start + window_len - rng.randint(0, max(1, window_len // 10)),
                   ref_length)
        if rend <= rstart:
            rend = min(rstart + 1, ref_length)
        qlen = rend - rstart
        mapq = rng.choice([30, 40, 50, 60])
        nmatch = int(qlen * rng.uniform(0.92, 0.99))
        lines.append("\t".join([
            f"amp_read_{i}", str(qlen), "0", str(qlen), "+",
            ref_name, str(ref_length), str(rstart), str(rend),
            str(nmatch), str(qlen), str(mapq),
        ]))
    return lines


def _blast_tsv_lines(n_unique, identity_mean, seed, dup_fraction=0.2):
    """Generate BLAST outfmt-6 lines (15 columns) for ``n_unique`` reads.

    A fraction of reads emit a second HSP (same ``qseqid``) so the parser's
    deduplicate-by-qseqid invariant is exercised: the parsed ``validated_reads``
    must equal ``n_unique``, not the raw line count.
    """
    import random
    rng = random.Random(seed)
    lines = []
    for i in range(n_unique):
        qseqid = f"read_{i}"
        n_hsp = 2 if rng.random() < dup_fraction else 1
        for _ in range(n_hsp):
            pident = round(min(100.0, max(70.0, rng.gauss(identity_mean, 1.5))), 2)
            length = rng.randint(400, 4000)
            mismatch = int(length * (100 - pident) / 100)
            qlen = length + rng.randint(0, 200)
            qcovs = min(100, int(length / qlen * 100))
            lines.append("\t".join([
                qseqid, "ref_contig", f"{pident:.2f}", str(length),
                str(mismatch), "0", "1", str(length), "1", str(length),
                "1e-50", "500.0", str(qlen), "5000000", str(qcovs),
            ]))
    return lines


def _minimap2_stats_dict(sample, taxid, species, total_reads, mapped_reads,
                         identity, coverage, mapq, ref_name="ref_contig"):
    """Build a ``*.minimap2_stats.json`` payload matching the parser fields."""
    hit_rate = round(mapped_reads / total_reads, 4) if total_reads else 0.0
    return {
        "sample_id": sample,
        "taxid": taxid,
        "species": species,
        "total_reads": total_reads,
        "mapped_reads": mapped_reads,
        "hit_rate": hit_rate,
        "avg_identity": identity,
        "avg_coverage": coverage,
        "avg_mapq": mapq,
        "ref_name": ref_name,
        "timestamp": "2026-06-07T00:00:00",
    }


# Aggregate validation design: one blast-only, one minimap2-only, one "both",
# one no-data, plus one single-copy amplicon (TUL4). The expansion of the "both"
# entry into a separate minimap2 ValidationResult is intentional (see
# parse_nanometanf_aggregate_json). EXPECTED_AGGREGATE_RESULTS lists the
# (sample_id, taxid, validation_method, status) tuples a parse must yield so the
# generator and its test stay in lock-step.
EXPECTED_AGGREGATE_RESULTS = [
    ("barcode01", 1773, "both", "confirmed"),       # M. tuberculosis (blast side)
    ("barcode01", 1773, "minimap2", "confirmed"),   # expanded minimap2 side
    ("barcode01", 1280, "blast", "partial"),        # S. aureus
    ("barcode02", 1639, "minimap2", "confirmed"),   # L. monocytogenes
    ("barcode03", 562, "blast", "no_data"),         # E. coli (low, no hits)
    ("barcode05", 263, "minimap2", "confirmed"),    # F. tularensis TUL4 amplicon
]


def _build_aggregate_results():
    """Assemble the nanometanf-style aggregate ``validation_results.json`` dict."""
    return {
        "pipeline_version": "synthetic",
        "validation_method": "both",
        "timestamp": "2026-06-07T00:00:00",
        "results": {
            "barcode01": {
                "1773": {
                    "taxid": 1773,
                    "species": "Mycobacterium tuberculosis",
                    "validation_method": "both",
                    "kraken_reads": 3500,
                    "blast_hits": 3200,
                    "hit_rate": 0.914,
                    "avg_identity": 97.5,
                    "avg_coverage": 0.90,
                    "minimap2_mapped": 3300,
                    "minimap2_hit_rate": 0.943,
                    "minimap2_identity": 98.0,
                    "avg_mapq": 55.0,
                },
                "1280": {
                    "taxid": 1280,
                    "species": "Staphylococcus aureus",
                    "validation_method": "blast",
                    "kraken_reads": 2800,
                    "blast_hits": 1800,
                    "hit_rate": 0.643,
                    "avg_identity": 93.0,
                    "avg_coverage": 0.55,
                },
            },
            "barcode02": {
                "1639": {
                    "taxid": 1639,
                    "species": "Listeria monocytogenes",
                    "validation_method": "minimap2",
                    "kraken_reads": 4200,
                    "mapped_reads": 4000,
                    "hit_rate": 0.952,
                    "avg_identity": 96.0,
                    "avg_coverage": 0.88,
                    "avg_mapq": 58.0,
                },
            },
            "barcode03": {
                "562": {
                    "taxid": 562,
                    "species": "Escherichia coli",
                    "validation_method": "blast",
                    "kraken_reads": 150,
                    "blast_hits": 0,
                    "hit_rate": 0.0,
                    "avg_identity": 0.0,
                    "avg_coverage": 0.0,
                },
            },
            "barcode05": {
                "263": {
                    "taxid": 263,
                    "species": "Francisella tularensis",
                    "validation_method": "minimap2",
                    "kraken_reads": 3800,
                    "mapped_reads": 3650,
                    "hit_rate": 0.961,
                    "avg_identity": 97.8,
                    "avg_coverage": 0.94,
                    "avg_mapq": 56.0,
                },
            },
        },
    }


def _consensus_stats_dict(sample, taxid, species, ref_name, ref_length,
                          covered_start, covered_end, mean_depth, n_count,
                          min_depth=10):
    """Build a ``*.consensus_stats.json`` payload matching the parser fields."""
    span = covered_end - covered_start + 1
    return {
        "sample_id": sample, "taxid": taxid, "species": species,
        "validation_method": "consensus", "ref_name": ref_name,
        "ref_length": ref_length, "covered_start": covered_start,
        "covered_end": covered_end, "span": span, "mean_depth": mean_depth,
        "min_depth_threshold": min_depth, "n_count": n_count,
        "consensus_length": span, "total_reads": 3800, "mapped_reads": 3650,
    }


def _consensus_fasta(sample, taxid, ref_name, start, end, n_count, seed=263):
    """Build a deterministic consensus FASTA record of length (end-start+1)."""
    import random
    rng = random.Random(seed)
    span = end - start + 1
    seq = [rng.choice("ACGT") for _ in range(span)]
    # Scatter the masked positions in the interior (not at the trimmed ends).
    for i in range(n_count):
        pos = 5 + (i * max(1, (span - 10) // max(1, n_count)))
        if pos < span:
            seq[pos] = "N"
    body = "".join(seq)
    wrapped = "\n".join(body[i:i + 70] for i in range(0, len(body), 70))
    return f">{sample}_taxid{taxid} ref={ref_name} region={start}-{end}\n{wrapped}\n"


def _generate_validation_tree(output_dir):
    """Write a realistic validation/ tree: per-(sample,taxid) blast.tsv +
    minimap2_stats.json, the aggregate validation_results.json, consensus
    FASTA + stats, and a per-batch drill-down set so GUI/loader tests have
    deterministic input for all methods (blast, minimap2, both, consensus)."""
    validation_root = output_dir / "validation"
    blast_dir = validation_root / "blast"
    mm2_dir = validation_root / "minimap2"
    consensus_dir = validation_root / "consensus"
    blast_batch = blast_dir / "batch"
    mm2_batch = mm2_dir / "batch"
    for d in (blast_dir, mm2_dir, consensus_dir, blast_batch, mm2_batch):
        d.mkdir(parents=True, exist_ok=True)

    # Aggregate (source of truth when present)
    (validation_root / "validation_results.json").write_text(
        json.dumps(_build_aggregate_results(), indent=2)
    )

    # Individual cumulative files (fallback path + Coverage sub-tab during realtime)
    (blast_dir / "barcode01_taxid1773.blast.tsv").write_text(
        "\n".join(_blast_tsv_lines(3200, 97.5, seed=1773)) + "\n"
    )
    (blast_dir / "barcode01_taxid1280.blast.tsv").write_text(
        "\n".join(_blast_tsv_lines(1800, 93.0, seed=1280)) + "\n"
    )
    (mm2_dir / "barcode01_taxid1773.minimap2_stats.json").write_text(json.dumps(
        _minimap2_stats_dict("barcode01", 1773, "Mycobacterium tuberculosis",
                             3500, 3300, 98.0, 0.90, 55.0)))
    (mm2_dir / "barcode02_taxid1639.minimap2_stats.json").write_text(json.dumps(
        _minimap2_stats_dict("barcode02", 1639, "Listeria monocytogenes",
                             4200, 4000, 96.0, 0.88, 58.0)))
    (mm2_dir / "barcode05_taxid263.minimap2_stats.json").write_text(json.dumps(
        _minimap2_stats_dict("barcode05", 263, "Francisella tularensis",
                             3800, 3650, 97.8, 0.94, 56.0)))
    # matching minimap2 PAF for the Coverage depth plot (taxid 1773)
    (mm2_dir / "barcode01_taxid1773.paf").write_text(
        "\n".join(_generate_paf_lines("ref_contig", 4411532, 500, seed=1773)) + "\n"
    )

    # BLAST tsv for the TUL4 amplicon so the per-read BLAST detail panel has
    # data for F. tularensis (barcode05 / taxid 263).
    (blast_dir / "barcode05_taxid263.blast.tsv").write_text(
        "\n".join(_blast_tsv_lines(3650, 97.8, seed=263)) + "\n"
    )

    # Consensus artifacts (--generate_consensus output):
    #  - barcode05 / taxid 263: the TUL4 amplicon, trimmed to its ~428 bp window
    #  - barcode01 / taxid 1773: a whole-genome partial consensus
    (consensus_dir / "barcode05_taxid263.consensus_stats.json").write_text(json.dumps(
        _consensus_stats_dict("barcode05", 263, "Francisella tularensis",
                              "ref_contig", 1892775, 435, 863, 56.0, 3)))
    (consensus_dir / "barcode05_taxid263.consensus.fasta").write_text(
        _consensus_fasta("barcode05", 263, "ref_contig", 435, 863, 3, seed=263))
    (consensus_dir / "barcode01_taxid1773.consensus_stats.json").write_text(json.dumps(
        _consensus_stats_dict("barcode01", 1773, "Mycobacterium tuberculosis",
                              "ref_contig", 4411532, 1200, 3800, 42.0, 60)))
    (consensus_dir / "barcode01_taxid1773.consensus.fasta").write_text(
        _consensus_fasta("barcode01", 1773, "ref_contig", 1200, 3800, 60, seed=1773))

    # Per-batch drill-down for barcode01 / taxid 1773 (batch ids "1" and "2")
    # barcode05 (TUL4 amplicon) uses cumulative results only
    for batch_id, n_reads in (("1", 1200), ("2", 3300)):
        (blast_batch / f"barcode01_taxid1773_{batch_id}.blast.tsv").write_text(
            "\n".join(_blast_tsv_lines(n_reads, 97.5, seed=1773 + int(batch_id))) + "\n"
        )
        (mm2_batch / f"barcode01_taxid1773_{batch_id}.minimap2_stats.json").write_text(
            json.dumps(_minimap2_stats_dict(
                "barcode01", 1773, "Mycobacterium tuberculosis",
                3500, n_reads, 98.0, 0.90, 55.0))
        )
        (mm2_batch / f"barcode01_taxid1773_{batch_id}.paf").write_text(
            "\n".join(_generate_paf_lines("ref_contig", 4411532, n_reads // 4,
                                          seed=1773 + int(batch_id))) + "\n"
        )


def generate_all_synthetic_data(output_dir):
    """Generate the complete 5-barcode synthetic dataset.

    Includes:
    - barcode01: Clinical (M. tuberculosis, S. aureus)
    - barcode02: Foodborne (L. monocytogenes, S. enterica)
    - barcode03: Water (L. pneumophila, E. coli)
    - barcode04: Negative control
    - barcode05: F. tularensis TUL4 amplicon (single-copy gene)

    Args:
        output_dir: Path or str to the output directory.
    """
    output_dir = Path(output_dir)
    kraken_dir = output_dir / "kraken2"
    fastp_dir = output_dir / "fastp"
    validation_dir = output_dir / "validation" / "minimap2"

    kraken_dir.mkdir(parents=True, exist_ok=True)
    fastp_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    barcodes = {
        "barcode01": (BARCODE01_CLINICAL, 10000),
        "barcode02": (BARCODE02_FOODBORNE, 12000),
        "barcode03": (BARCODE03_WATER, 8000),
        "barcode04": (BARCODE04_NEGATIVE, 5000),
        "barcode05": (BARCODE05_AMPLICON, 7000),
    }

    for name, (organisms, total_reads) in barcodes.items():
        # Kraken2 report
        lines = _build_report_lines(total_reads, organisms)
        report_path = kraken_dir / f"{name}.kraken2.report.txt"
        report_path.write_text("\n".join(lines) + "\n")

        # Cumulative report (same content for static test)
        cumul_path = kraken_dir / f"{name}.cumulative.kraken2.report.txt"
        cumul_path.write_text("\n".join(lines) + "\n")

        # FASTP JSON
        fastp_path = fastp_dir / f"{name}.fastp.json"
        fastp_path.write_text(json.dumps(_generate_fastp_json(total_reads), indent=2))

        # Batch time-point reports (3 points with 33%, 66%, 100% of reads)
        for batch_idx, fraction in enumerate([0.33, 0.66, 1.0]):
            scaled_organisms = []
            for org in organisms:
                scaled = dict(org)
                scaled["reads"] = max(1, int(org["reads"] * fraction))
                scaled_organisms.append(scaled)
            scaled_total = max(100, int(total_reads * fraction))
            batch_lines = _build_report_lines(scaled_total, scaled_organisms)
            batch_path = kraken_dir / f"{name}_batch{batch_idx}.kraken2.report.txt"
            batch_path.write_text("\n".join(batch_lines) + "\n")

    # PAF file for barcode01 M. tuberculosis validation
    paf_lines = _generate_paf_lines(
        ref_name="NC_000962.3",
        ref_length=4411532,
        num_reads=500,
        seed=1773,
    )
    paf_path = validation_dir / "barcode01_taxid1773.paf"
    paf_path.write_text("\n".join(paf_lines) + "\n")

    # PAF file for barcode05 F. tularensis TUL4 amplicon (single-copy gene)
    # TUL4 primer pair: Forward (TUL4-435, 28bp) and Reverse (TUL4-863, 24bp)
    # Amplicon spans ~435-863 bp on the reference (~428 bp)
    amplicon_paf_lines = _generate_amplicon_paf_lines(
        ref_name="Francisella_tularensis_chr",
        ref_length=1892775,  # F. tularensis genome size
        window_start=435,
        window_len=428,  # TUL4 amplicon region
        num_reads=400,
        seed=263,
    )
    amplicon_paf_path = validation_dir / "barcode05_taxid263.paf"
    amplicon_paf_path.write_text("\n".join(amplicon_paf_lines) + "\n")

    # Full validation tree: blast.tsv + minimap2_stats.json + aggregate JSON +
    # per-batch drill-down, covering blast / minimap2 / both methods.
    _generate_validation_tree(output_dir)

    # Backdate all generated files so they pass the file stability check
    old_time = time.time() - 5
    for root, _dirs, files in os.walk(str(output_dir)):
        for fname in files:
            fpath = os.path.join(root, fname)
            os.utime(fpath, (old_time, old_time))
