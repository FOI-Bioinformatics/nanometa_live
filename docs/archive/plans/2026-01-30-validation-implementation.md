# End-to-End Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build synthetic test data and validation scripts to confirm Nanometa Live works end-to-end for real-time multiplexed nanopore analysis.

**Architecture:** A synthetic data generator creates 4 barcodes with known organisms from built-in watchlists. A smoke test verifies app startup and tab rendering. An acceptance test runner checks classification, alerts, validation, and QC against ground truth. A manual walkthrough checklist covers operator workflows.

**Tech Stack:** Python, pytest, requests, pandas, numpy, json

---

### Task 1: Create synthetic data generator — Kraken2 reports

**Files:**
- Create: `tests/validation/generate_synthetic_data.py`
- Test: `tests/validation/test_generate_synthetic_data.py`

**Step 1: Write the failing test**

```python
# tests/validation/test_generate_synthetic_data.py
"""Tests for synthetic data generator."""
import os
import pytest
import pandas as pd


def test_generate_kraken_report_barcode01(tmp_path):
    """barcode01 (clinical) should contain M. tuberculosis and S. aureus."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode01.kraken2.report.txt"
    assert report_path.exists(), "barcode01 kraken report missing"

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])

    # M. tuberculosis (taxid 1773) and S. aureus (taxid 1280) must be present
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 1773 in taxids, "M. tuberculosis missing from barcode01"
    assert 1280 in taxids, "S. aureus missing from barcode01"
    assert species["reads"].sum() > 0, "No species-level reads"


def test_generate_kraken_report_barcode02(tmp_path):
    """barcode02 (foodborne) should contain L. monocytogenes and S. enterica."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode02.kraken2.report.txt"
    assert report_path.exists()

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 1639 in taxids, "L. monocytogenes missing from barcode02"
    assert 28901 in taxids, "S. enterica missing from barcode02"


def test_generate_kraken_report_barcode03(tmp_path):
    """barcode03 (water) should contain L. pneumophila and low E. coli."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode03.kraken2.report.txt"
    assert report_path.exists()

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 446 in taxids, "L. pneumophila missing from barcode03"
    assert 562 in taxids, "E. coli missing from barcode03"


def test_generate_kraken_report_barcode04_negative(tmp_path):
    """barcode04 (negative control) should have no watchlisted pathogens."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    report_path = tmp_path / "kraken2" / "barcode04.kraken2.report.txt"
    assert report_path.exists()

    df = pd.read_csv(report_path, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))

    # None of the watchlisted pathogen taxids should appear
    watchlisted = {1773, 1280, 1639, 28901, 446, 83334, 1491}
    overlap = taxids & watchlisted
    assert len(overlap) == 0, f"Negative control has watchlisted pathogens: {overlap}"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/validation/test_generate_synthetic_data.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write the implementation**

```python
# tests/validation/generate_synthetic_data.py
"""
Generate synthetic Nanometa Live test data for end-to-end validation.

Creates 4 barcodes with known organisms from built-in watchlists:
- barcode01: Clinical (M. tuberculosis, S. aureus + background)
- barcode02: Foodborne (L. monocytogenes, S. enterica + background)
- barcode03: Environmental/water (L. pneumophila, low E. coli + diverse background)
- barcode04: Negative control (background flora only)
"""
import json
import os
from pathlib import Path


# ---- Taxonomy trees for each barcode ----
# Format: (percentage, cumul_reads, reads, rank, taxid, name)
# Leading spaces in name indicate hierarchy depth.

# Background flora (shared across barcodes, scaled per-barcode)
_BACKGROUND = [
    # Cutibacterium acnes (skin commensal)
    ("P", 1301, "  Actinomycetota"),
    ("C", 1301, "    Actinomycetia"),
    ("O", 1301, "      Propionibacteriales"),
    ("F", 1301, "        Propionibacteriaceae"),
    ("G", 1301, "          Cutibacterium"),
    ("S", 1301, "            Cutibacterium acnes", 1747),
    # Bacillus subtilis (soil)
    ("P", 1386, "  Bacillota"),
    ("C", 1386, "    Bacilli"),
    ("O", 1386, "      Bacillales"),
    ("F", 1386, "        Bacillaceae"),
    ("G", 1386, "          Bacillus"),
    ("S", 1386, "            Bacillus subtilis", 1423),
]


def _kraken_line(pct, cumul, reads, rank, taxid, name):
    """Format one Kraken2 report line."""
    return f"{pct:.2f}\t{cumul}\t{reads}\t{rank}\t{taxid}\t{name}"


def _build_report_lines(total_reads, organisms):
    """
    Build a complete Kraken2 report from organism definitions.

    organisms: list of dicts with keys:
        domain, phylum, phylum_class, order, family, genus, species,
        taxid, reads
    Plus background flora.
    Returns list of report lines.
    """
    lines = []
    classified_reads = sum(o["reads"] for o in organisms)
    # Add background reads
    bg_reads_each = max(50, int(total_reads * 0.02))
    bg_species_count = 2  # C. acnes, B. subtilis
    bg_total = bg_reads_each * bg_species_count
    classified_reads += bg_total
    unclassified = total_reads - classified_reads

    # Unclassified
    lines.append(_kraken_line(
        unclassified / total_reads * 100, unclassified, unclassified,
        "U", 0, "unclassified"
    ))
    # Root
    lines.append(_kraken_line(
        classified_reads / total_reads * 100, classified_reads, 0,
        "R", 1, "root"
    ))
    # Domain
    lines.append(_kraken_line(
        classified_reads / total_reads * 100, classified_reads, 0,
        "D", 2, "  Bacteria"
    ))

    # Each organism with full taxonomy
    for org in organisms:
        r = org["reads"]
        pct = r / total_reads * 100
        lines.append(_kraken_line(pct, r, 0, "P", org.get("phylum_taxid", 0), f"    {org['phylum']}"))
        lines.append(_kraken_line(pct, r, 0, "C", org.get("class_taxid", 0), f"      {org['phylum_class']}"))
        lines.append(_kraken_line(pct, r, 0, "O", org.get("order_taxid", 0), f"        {org['order']}"))
        lines.append(_kraken_line(pct, r, 0, "F", org.get("family_taxid", 0), f"          {org['family']}"))
        lines.append(_kraken_line(pct, r, 0, "G", org.get("genus_taxid", 0), f"            {org['genus']}"))
        lines.append(_kraken_line(pct, r, r, "S", org["taxid"], f"              {org['species']}"))

    # Background: C. acnes
    pct_bg = bg_reads_each / total_reads * 100
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "P", 201174, "    Actinomycetota"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "C", 1760, "      Actinomycetia"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "O", 31957, "        Propionibacteriales"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "F", 31958, "          Propionibacteriaceae"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "G", 1743, "            Cutibacterium"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, bg_reads_each, "S", 1747, "              Cutibacterium acnes"))

    # Background: B. subtilis
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "P", 1239, "    Bacillota"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "C", 91061, "      Bacilli"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "O", 1385, "        Bacillales"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "F", 186817, "          Bacillaceae"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, 0, "G", 1386, "            Bacillus"))
    lines.append(_kraken_line(pct_bg, bg_reads_each, bg_reads_each, "S", 1423, "              Bacillus subtilis"))

    return lines


# ---- Barcode definitions ----

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
        "order": "Staphylococcales", "order_taxid": 1385,  # simplified
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
        "reads": 150,  # low level — below typical alert thresholds
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

BARCODE04_NEGATIVE = []  # background flora only


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
                "q30_rate": 0.85,
                "mean_length": 1500,
            },
            "after_filtering": {
                "total_reads": passed,
                "total_bases": passed * 1520,
                "q30_rate": 0.92,
                "mean_length": 1520,
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
            f"read_{i}", str(qlen), "0", str(qlen),  # query
            "+",
            ref_name, str(ref_length), str(tstart), str(tend),  # target
            str(nmatch), str(qlen), str(mapq),
        ])
        lines.append(line)
    return lines


def generate_all_synthetic_data(output_dir):
    """Generate the complete 4-barcode synthetic dataset.

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

    # PAF file for barcode01 M. tuberculosis validation
    paf_lines = _generate_paf_lines(
        ref_name="NC_000962.3",  # M. tuberculosis H37Rv
        ref_length=4411532,
        num_reads=500,
        seed=1773,
    )
    paf_path = validation_dir / "barcode01_taxid1773.paf"
    paf_path.write_text("\n".join(paf_lines) + "\n")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/validation/test_generate_synthetic_data.py -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add tests/validation/generate_synthetic_data.py tests/validation/test_generate_synthetic_data.py
git commit -m "feat: add synthetic data generator for e2e validation"
```

---

### Task 2: Add cumulative time-point reports for real-time simulation

**Files:**
- Modify: `tests/validation/generate_synthetic_data.py`
- Test: `tests/validation/test_generate_synthetic_data.py`

**Step 1: Write the failing test**

Add to test file:

```python
def test_cumulative_time_points(tmp_path):
    """Cumulative reports should exist for 3 time points with increasing reads."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data

    generate_all_synthetic_data(tmp_path)

    kraken_dir = tmp_path / "kraken2"
    # Time point files: barcode01_batch0, barcode01_batch1, barcode01_batch2
    for i in range(3):
        batch_path = kraken_dir / f"barcode01_batch{i}.kraken2.report.txt"
        assert batch_path.exists(), f"Batch {i} report missing"

    # Read counts should increase across time points
    import pandas as pd
    totals = []
    for i in range(3):
        batch_path = kraken_dir / f"barcode01_batch{i}.kraken2.report.txt"
        df = pd.read_csv(batch_path, sep="\t", header=None,
                         names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
        total = df[df["rank"] == "S"]["reads"].sum()
        totals.append(total)

    assert totals[0] < totals[1] < totals[2], f"Reads should increase: {totals}"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/validation/test_generate_synthetic_data.py::test_cumulative_time_points -v`
Expected: FAIL

**Step 3: Add time-point generation to `generate_all_synthetic_data`**

Add to the barcode loop in `generate_all_synthetic_data`:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/validation/test_generate_synthetic_data.py -v`
Expected: 5 PASS

**Step 5: Commit**

```bash
git add tests/validation/generate_synthetic_data.py tests/validation/test_generate_synthetic_data.py
git commit -m "feat: add cumulative time-point reports for real-time simulation"
```

---

### Task 3: Create smoke test script

**Files:**
- Create: `tests/validation/smoke_test.py`
- Create: `tests/validation/__init__.py` (empty)

**Step 1: Write the test**

```python
# tests/validation/smoke_test.py
"""
Smoke test: verify Nanometa Live app starts and all components load.

Run standalone:
    python -m pytest tests/validation/smoke_test.py -v

Requires: synthetic data generated first (or any valid results directory).
"""
import importlib
import pytest


# ---- Import tests ----

CORE_MODULES = [
    "nanometa_live.core.utils.data_loaders",
    "nanometa_live.core.utils.sample_detector",
    "nanometa_live.core.config.config_loader",
    "nanometa_live.core.parsers.paf_coverage_parser",
]

APP_MODULES = [
    "nanometa_live.app.layouts.dashboard_layout",
    "nanometa_live.app.layouts.main_layout",
    "nanometa_live.app.layouts.classification_layout",
    "nanometa_live.app.layouts.validation_layout",
    "nanometa_live.app.layouts.qc_layout",
    "nanometa_live.app.layouts.watchlist_layout",
    "nanometa_live.app.layouts.config_layout",
    "nanometa_live.app.layouts.preparation_layout",
]


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_imports(module_name):
    """Core modules should import without error."""
    mod = importlib.import_module(module_name)
    assert mod is not None


@pytest.mark.parametrize("module_name", APP_MODULES)
def test_app_layout_imports(module_name):
    """App layout modules should import without error."""
    mod = importlib.import_module(module_name)
    assert mod is not None


# ---- Data loading tests ----

def test_sample_detection(synthetic_data_dir):
    """Sample detector should find all 4 barcodes."""
    from nanometa_live.core.utils.sample_detector import get_available_samples

    samples = get_available_samples(str(synthetic_data_dir))
    # Expect "All Samples" + barcode01-04
    assert len(samples) >= 5, f"Expected 5+ samples, got {samples}"
    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        assert bc in samples, f"{bc} not detected"


def test_kraken_data_loads(synthetic_data_dir):
    """Kraken2 data should load for each barcode."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        df = load_kraken_data(str(synthetic_data_dir), bc)
        assert df is not None, f"No data for {bc}"
        assert len(df) > 0, f"Empty data for {bc}"


def test_fastp_data_loads(synthetic_data_dir):
    """FASTP data should load for each barcode."""
    from nanometa_live.core.utils.data_loaders import load_fastp_data

    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        data = load_fastp_data(str(synthetic_data_dir), bc)
        assert data is not None, f"No FASTP data for {bc}"
        assert data.get("total_reads_before", 0) > 0, f"No reads for {bc}"


def test_paf_coverage_parses(synthetic_data_dir):
    """PAF coverage should parse for barcode01 M. tuberculosis."""
    from nanometa_live.core.parsers.paf_coverage_parser import parse_paf_coverage

    paf_path = synthetic_data_dir / "validation" / "minimap2" / "barcode01_taxid1773.paf"
    assert paf_path.exists(), "PAF file missing"

    coverage = parse_paf_coverage(paf_path)
    assert len(coverage) > 0, "No coverage data parsed"
    for ref_name, cov_data in coverage.items():
        assert cov_data.ref_length > 0
        assert cov_data.breadth > 0


# ---- Fixture ----

@pytest.fixture
def synthetic_data_dir(tmp_path):
    """Generate synthetic data and return the directory."""
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data
    generate_all_synthetic_data(tmp_path)
    return tmp_path
```

**Step 2: Run test to verify it passes (depends on Task 1)**

Run: `python -m pytest tests/validation/smoke_test.py -v`
Expected: All PASS (import tests may reveal broken imports — fix as needed)

**Step 3: Commit**

```bash
touch tests/validation/__init__.py
git add tests/validation/smoke_test.py tests/validation/__init__.py
git commit -m "feat: add smoke test for app imports and data loading"
```

---

### Task 4: Create acceptance test script

**Files:**
- Create: `tests/validation/acceptance_test.py`

**Step 1: Write the acceptance tests**

```python
# tests/validation/acceptance_test.py
"""
Acceptance tests: verify classification, alerts, and QC against ground truth.

Run:
    python -m pytest tests/validation/acceptance_test.py -v
"""
import pytest
import pandas as pd


@pytest.fixture
def synthetic_data_dir(tmp_path):
    from tests.validation.generate_synthetic_data import generate_all_synthetic_data
    generate_all_synthetic_data(tmp_path)
    return tmp_path


# ---- Clinical scenario (barcode01) ----

def test_clinical_pathogens_detected(synthetic_data_dir):
    """barcode01 should classify M. tuberculosis and S. aureus at species level."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode01")
    species = df[df["rank"] == "S"]
    names = set(species["name"].str.strip())

    assert "Mycobacterium tuberculosis" in names
    assert "Staphylococcus aureus" in names


def test_clinical_pathogen_reads_above_threshold(synthetic_data_dir):
    """Clinical pathogens should have substantial read counts."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode01")
    species = df[df["rank"] == "S"]

    mtb = species[species["taxid"] == 1773]
    assert len(mtb) == 1
    assert mtb.iloc[0]["reads"] >= 100, "M. tuberculosis reads too low for alert"

    sa = species[species["taxid"] == 1280]
    assert len(sa) == 1
    assert sa.iloc[0]["reads"] >= 100, "S. aureus reads too low for alert"


# ---- Foodborne scenario (barcode02) ----

def test_foodborne_pathogens_detected(synthetic_data_dir):
    """barcode02 should classify L. monocytogenes and S. enterica."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode02")
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))

    assert 1639 in taxids, "L. monocytogenes not detected"
    assert 28901 in taxids, "S. enterica not detected"


# ---- Water scenario (barcode03) ----

def test_water_pathogen_detected(synthetic_data_dir):
    """barcode03 should classify L. pneumophila."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode03")
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))
    assert 446 in taxids, "L. pneumophila not detected"


def test_water_ecoli_low_level(synthetic_data_dir):
    """barcode03 E. coli should be present but at low read count."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode03")
    species = df[df["rank"] == "S"]
    ecoli = species[species["taxid"] == 562]
    assert len(ecoli) == 1
    assert ecoli.iloc[0]["reads"] < 500, "E. coli should be low-level"


# ---- Negative control (barcode04) ----

def test_negative_no_pathogens(synthetic_data_dir):
    """barcode04 should contain only background flora."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    df = load_kraken_data(str(synthetic_data_dir), "barcode04")
    species = df[df["rank"] == "S"]
    taxids = set(species["taxid"].astype(int))

    watchlisted = {1773, 1280, 1639, 28901, 446, 83334, 1491, 287, 573}
    overlap = taxids & watchlisted
    assert len(overlap) == 0, f"Negative control has pathogens: {overlap}"


# ---- QC metrics ----

def test_qc_metrics_all_barcodes(synthetic_data_dir):
    """All barcodes should have valid QC metrics."""
    from nanometa_live.core.utils.data_loaders import load_fastp_data

    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        data = load_fastp_data(str(synthetic_data_dir), bc)
        assert data["total_reads_before"] > 0, f"{bc}: no reads before filtering"
        assert data["total_reads_after"] > 0, f"{bc}: no reads after filtering"
        assert data["total_reads_after"] <= data["total_reads_before"], \
            f"{bc}: more reads after filtering than before"


# ---- Sample switching ----

def test_sample_data_differs_between_barcodes(synthetic_data_dir):
    """Each barcode should have distinct classification data."""
    from nanometa_live.core.utils.data_loaders import load_kraken_data

    datasets = {}
    for bc in ["barcode01", "barcode02", "barcode03", "barcode04"]:
        df = load_kraken_data(str(synthetic_data_dir), bc)
        species = df[df["rank"] == "S"]
        datasets[bc] = set(species["taxid"].astype(int))

    # barcode01 and barcode02 should have different pathogens
    assert datasets["barcode01"] != datasets["barcode02"]
    # barcode04 should be a subset (background only)
    pathogen_taxids = {1773, 1280, 1639, 28901, 446}
    assert len(datasets["barcode04"] & pathogen_taxids) == 0


# ---- Real-time simulation ----

def test_batch_reads_increase(synthetic_data_dir):
    """Batch reports should show increasing species reads over time."""
    kraken_dir = synthetic_data_dir / "kraken2"
    totals = []
    for i in range(3):
        path = kraken_dir / f"barcode01_batch{i}.kraken2.report.txt"
        df = pd.read_csv(path, sep="\t", header=None,
                         names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
        total = df[df["rank"] == "S"]["reads"].sum()
        totals.append(total)

    assert totals[0] < totals[2], f"Reads should increase over batches: {totals}"


# ---- Coverage validation ----

def test_coverage_plots_render(synthetic_data_dir):
    """Coverage plot functions should produce valid Plotly figures from PAF data."""
    from nanometa_live.core.parsers.paf_coverage_parser import parse_paf_coverage
    from nanometa_live.app.components.coverage_plots import (
        create_coverage_depth_figure,
        create_cumulative_coverage_figure,
        create_depth_histogram_figure,
    )

    paf_path = synthetic_data_dir / "validation" / "minimap2" / "barcode01_taxid1773.paf"
    coverage = parse_paf_coverage(paf_path)
    cov_data = list(coverage.values())[0]

    fig1 = create_coverage_depth_figure(cov_data)
    fig2 = create_cumulative_coverage_figure(cov_data)
    fig3 = create_depth_histogram_figure(cov_data)

    assert fig1 is not None
    assert fig2 is not None
    assert fig3 is not None
    # Plotly figures should have data traces
    assert len(fig1.data) > 0, "Depth figure has no traces"
    assert len(fig2.data) > 0, "Cumulative figure has no traces"
    assert len(fig3.data) > 0, "Histogram figure has no traces"
```

**Step 2: Run tests**

Run: `python -m pytest tests/validation/acceptance_test.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/validation/acceptance_test.py
git commit -m "feat: add acceptance tests for classification, alerts, QC, coverage"
```

---

### Task 5: Create manual walkthrough checklist

**Files:**
- Create: `docs/validation-walkthrough-checklist.md`

**Step 1: Write the checklist**

```markdown
# Nanometa Live Validation Walkthrough Checklist

**Date:** ___________
**Tester:** ___________
**App version:** ___________
**Data source:** synthetic_testdata (4 barcodes)

## Setup

1. Generate synthetic data:
   ```
   python -c "
   from tests.validation.generate_synthetic_data import generate_all_synthetic_data
   generate_all_synthetic_data('/tmp/nanometa_validation_data')
   "
   ```
2. Launch app:
   ```
   python -m nanometa_live.app --main_dir /tmp/nanometa_validation_data --port 8050
   ```
3. Open browser to http://localhost:8050

## Walkthrough

| # | Step | Expected | Pass | Notes |
|---|------|----------|------|-------|
| 1 | Dashboard tab loads | Status indicators visible, 4 barcodes listed | [ ] | |
| 2 | Select barcode01 | Data updates to show clinical organisms | [ ] | |
| 3 | Organisms tab — barcode01 | Cards for M. tuberculosis and S. aureus visible | [ ] | |
| 4 | Alert banner — barcode01 | Critical/high alert for clinical pathogens | [ ] | |
| 5 | Select barcode02 | Data updates to foodborne organisms | [ ] | |
| 6 | Organisms tab — barcode02 | Cards for L. monocytogenes and S. enterica | [ ] | |
| 7 | Select barcode03 | Data updates to water/environmental organisms | [ ] | |
| 8 | Organisms tab — barcode03 | L. pneumophila card visible, low E. coli | [ ] | |
| 9 | Select barcode04 | Only background flora shown | [ ] | |
| 10 | Alert banner — barcode04 | No alert banners | [ ] | |
| 11 | Classification tab | Taxonomy breakdown visible, taxa match scenario | [ ] | |
| 12 | QC tab | FASTP metrics per barcode: reads, quality, length | [ ] | |
| 13 | Watchlist tab | Built-in watchlists load, toggle entries on/off | [ ] | |
| 14 | Validation tab | Results section renders | [ ] | |
| 15 | View Coverage — barcode01 | 3 plots render (depth, cumulative, histogram) | [ ] | |
| 16 | Config tab | Current config displays correctly | [ ] | |
| 17 | Rapid barcode switching | Switch 01→02→03→04 quickly, no stale data | [ ] | |

## Summary

**Passed:** ___ / 17
**Failed:** ___
**Observations:**

___________________________________________
```

**Step 2: Commit**

```bash
git add docs/validation-walkthrough-checklist.md
git commit -m "docs: add manual validation walkthrough checklist"
```

---

### Task 6: Run all validation and record results

**Step 1: Generate synthetic data**

Run: `python -c "from tests.validation.generate_synthetic_data import generate_all_synthetic_data; generate_all_synthetic_data('/tmp/nanometa_validation_data')"`

**Step 2: Run smoke tests**

Run: `python -m pytest tests/validation/smoke_test.py -v`
Record: pass/fail counts

**Step 3: Run acceptance tests**

Run: `python -m pytest tests/validation/acceptance_test.py -v`
Record: pass/fail counts

**Step 4: Fix any failures found**

If tests fail due to data format mismatches or import errors, fix the synthetic data generator or the test expectations. Do not modify the app code unless a clear bug is found.

**Step 5: Commit final state**

```bash
git add -A tests/validation/
git commit -m "feat: complete e2e validation suite — smoke + acceptance tests passing"
```
