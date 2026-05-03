# Nanometa Live v2.0 Migration Guide

Migrating from Snakemake (v1.x) to the Nextflow/nanometanf backend (v2.0).

## Overview

Nanometa Live v2.0 replaces the Snakemake workflow engine with the **nanometanf** Nextflow pipeline as the backend. Practical effects of the change:

- Roughly 10-15% faster processing with dynamic resource allocation.
- Backend built on nf-core conventions with its own test suite.
- CPU and memory allocation handled by Nextflow rather than ad-hoc Snakemake rules.
- Real-time monitoring uses native `watchPath` and emits per-batch statistics.
- GUI and pipeline logic are now separated.

## Breaking Changes

### 1. Workflow Engine
- **Old (v1.x)**: Snakemake (`snakemake>=8.30.0`)
- **New (v2.0)**: Nextflow + nanometanf pipeline

### 2. Configuration Format
- **Old**: YAML files with Snakemake-specific string flags (e.g., `"--memory-mapping"`, `"yes"`)
- **New**: YAML files with direct boolean parameters (e.g., `true`, `false`)

### 3. Output Directory Structure
- **Old**: Custom Snakemake structure (`kraken_cumul/`, `qc_data/`, `fastp_reports/`)
- **New**: nanometanf structure (`multiqc/`, `kraken2/`, `fastp/`, `realtime_batch_stats/`)

### 4. Dependencies
- **Removed**: `snakemake>=8.30.0`
- **Added**: Nextflow (installed separately)

## Installation

### Step 1: Install Nextflow

**Option A: Direct Installation**
```bash
curl -s https://get.nextflow.io | bash
sudo mv nextflow /usr/local/bin/
```

**Option B: Via Conda**
```bash
conda install -c bioconda nextflow
```

**Verify Installation:**
```bash
nextflow -version
# Expected: nextflow version 25.10 or higher
```

### Step 2: Update Nanometa Live

**From Git (Development)**
```bash
cd nanometa_live
git pull origin main
pip install -e . --upgrade
```

**From PyPI (When Released)**
```bash
pip install --upgrade nanometa-live
```

## Configuration Migration

### Automatic Migration

Existing v1.x configurations are automatically converted when loaded in v2.0.

**What Changes:**
```yaml
# v1.x YAML format
kraken_memory_mapping: "--memory-mapping"  # String flag
remove_temp_files: "yes"                    # String "yes"/"no"
```

Converted to:

```yaml
kraken_memory_mapping: true            # Boolean
remove_temp_files: true                # Boolean
```

### Manual Migration

If you need to manually update configurations:

**Old Format (v1.x):**
```yaml
nanopore_output_directory: /path/to/sequencer
kraken_db: /path/to/kraken2_db
main_dir: /path/to/results
kraken_memory_mapping: "--memory-mapping"
blast_validation: true
snakemake_cores: 4
check_intervals_seconds: 15
```

**New Format (v2.0):**
```yaml
nanopore_output_directory: "/path/to/sequencer"
kraken_db: "/path/to/kraken2_db"
main_dir: "/path/to/results"
kraken_memory_mapping: true
blast_validation: true
pipeline_cores: 4
update_interval_seconds: 15
analysis_name: "My Analysis"
```

## Output Structure Changes

### Old Structure (v1.x)
```
results/
├── kraken_cumul/
│   ├── kraken_cumul_txt.kraken2
│   └── kraken_cumul_report.kreport2
├── qc_data/
│   └── cumul_qc.txt
├── fastp_reports/
│   └── compiled_fastp.txt
└── blast_result_files/
```

### New Structure (v2.0)
```
results/
├── multiqc/                    # Aggregated QC reports
│   └── multiqc_data/
│       ├── multiqc_data.json
│       ├── multiqc_general_stats.txt
│       ├── multiqc_fastp.txt
│       └── multiqc_kraken.txt
├── fastp/                      # Per-sample FASTP reports
│   ├── sample1.fastp.json
│   └── sample2.fastp.json
├── kraken2/                    # Per-sample Kraken2 results
│   ├── sample1.kreport2.txt
│   └── sample2.kreport2.txt
├── blast/                      # BLAST validation results
│   └── sample1_species1.txt
├── realtime_batch_stats/       # NEW: Real-time batch tracking
│   ├── batch_1.json
│   └── batch_2.json
└── pipeline_info/              # NEW: Nextflow execution reports
    ├── execution_report.html
    └── execution_timeline.html
```

## Data Access

### v1.x: Direct File Access (Old Structure)
```python
# Old approach (v1.x) - Reading from Snakemake structure
kraken_report = "results/kraken_cumul/kraken_cumul_report.kreport2"
qc_file = "results/qc_data/cumul_qc.txt"
fastp_file = "results/fastp_reports/compiled_fastp.txt"
```

### v2.0: Direct Access to Nanometanf Structure
```python
# New approach (v2.0) - Reading from nanometanf structure
import glob
import pandas as pd
import json

# Load Kraken2 reports (per-sample files)
kraken_dir = "results/kraken2"
kreport_files = glob.glob(f"{kraken_dir}/*.kreport2.txt")

# Combine all reports
all_reports = []
for file in kreport_files:
    df = pd.read_csv(file, sep="\t", header=None,
                     names=["%", "cumul_reads", "reads", "rank", "taxid", "name"])
    all_reports.append(df)

# Aggregate by taxid
combined = pd.concat(all_reports, ignore_index=True)
kraken_df = combined.groupby(["taxid", "rank", "name"], as_index=False).agg({
    "%": "sum", "cumul_reads": "sum", "reads": "sum"
})

# Load batch statistics (real-time monitoring)
batch_files = glob.glob("results/realtime_batch_stats/batch_*.json")
for batch_file in batch_files:
    with open(batch_file) as f:
        batch_data = json.load(f)
        # Access: batch_data["reads_in_batch"], batch_data["timestamp"], etc.

# Load FASTP statistics
fastp_files = glob.glob("results/fastp/*.fastp.json")
for fastp_file in fastp_files:
    with open(fastp_file) as f:
        fastp_data = json.load(f)
        # Access: fastp_data["summary"]["after_filtering"]["total_reads"], etc.
```

## Functional Equivalence

All Nanometa Live v1.x functionality is preserved in v2.0:

| Feature | v1.x (Snakemake) | v2.0 (nanometanf) | Status |
|---------|------------------|-------------------|--------|
| Real-time FASTQ monitoring | yes | yes | Now uses native `watchPath` |
| Kraken2 classification | yes | yes | Same |
| BLAST validation | yes | yes | Same |
| Quality control (FASTP) | yes | yes | Same |
| NanoPlot QC | yes | yes | Same |
| Species of interest tracking | yes | yes | Same |
| MultiQC aggregation | yes | yes | More metrics surfaced |
| Batch processing | yes | yes | Native Nextflow batching |
| Memory mapping | yes | yes | Now a boolean parameter |
| Custom databases | yes | yes | Same |

## Performance Improvements

**Benchmarks** (10,000 FASTQ files, 4 cores, 16GB RAM):

| Metric | v1.x (Snakemake) | v2.0 (nanometanf) | Improvement |
|--------|------------------|-------------------|-------------|
| Processing Time | 42 min | 36 min | **-14%** |
| Memory Usage (peak) | 12.5 GB | 10.2 GB | **-18%** |
| Real-time Latency | 45 sec | 22 sec | **-51%** |
| Classification Rate | Same | Same | - |

## Known Limitations

### Temporary Limitations (v2.0.0)
1. **Config UI**: GUI still shows "Snakemake Cores" label (functional, just naming).
2. **Legacy Configs**: Old YAML files with string flags auto-convert to boolean parameters.
3. **Pipeline profile**: Conda is the canonical and supported profile. Docker and Singularity profiles exist in the underlying nanometanf pipeline but are not exercised by Nanometa Live.

### No Longer Supported
1. **Snakemake-specific rules**: Custom Snakefile modifications no longer apply
2. **Direct Snakemake CLI**: Must use Nextflow/nanometanf commands
3. **Snakemake conda envs**: Replaced with Nextflow profiles

## Troubleshooting

### Issue: "Nextflow not found"
**Solution:**
```bash
# Check if Nextflow is installed
which nextflow

# If not found, install:
curl -s https://get.nextflow.io | bash
sudo mv nextflow /usr/local/bin/
```

### Issue: "Pipeline fails to start"
**Solution:**
1. Check Nextflow installation: `nextflow -version` (must be 25.10 or newer).
2. Verify the conda environment is available and `pipeline_profile: conda`.
3. Check logs: `~/nanometa_data/logs/nextflow.log`.
4. Verify the Kraken2 database exists.

### Issue: "Old results not visible"
**Explanation:** v2.0 cannot parse v1.x output structure directly.

**Solution:**
```python
# Option 1: Use old data_utils.py functions for v1.x results
from nanometa_live.core.utils.data_utils import parse_kraken_report
old_report = parse_kraken_report("v1_results/kraken_cumul/kraken_cumul_report.kreport2")

# Option 2: Reprocess with v2.0 (recommended for new analyses)
```

### Issue: "Configuration not loading"
**Solution:**
1. Check config format (YAML with boolean parameters)
2. Verify all paths are absolute
3. Ensure Kraken2 database has required files (`hash.k2d`, `opts.k2d`, `taxo.k2d`)

## Advanced: Custom Nextflow Configuration

For advanced users who need custom Nextflow settings:

```groovy
// Create: ~/nanometa_data/logs/custom.config

params {
  max_cpus = 16
  max_memory = '32.GB'
  max_time = '48.h'
}

process {
  withName: 'KRAKEN2_KRAKEN2' {
    cpus = 12
    memory = '24.GB'
  }

  withName: 'BLAST_BLASTN' {
    cpus = 4
    memory = '8.GB'
  }
}
```

This file is automatically generated by Nanometa Live v2.0 based on your GUI settings.

## Rollback to v1.x

If you need to revert to v1.x:

```bash
# Uninstall v2.0
pip uninstall nanometa-live

# Reinstall v1.x
pip install nanometa-live==1.3.0  # Replace with last v1.x version

# Reinstall Snakemake
pip install snakemake>=8.30.0
```

**Note:** Your v1.x configurations and results remain unchanged.

## FAQ

**Q: Can I run v1.x and v2.0 side-by-side?**
A: Yes, use separate conda/virtual environments.

**Q: Will my existing analyses still work?**
A: Yes, v1.x results are preserved. Use old parsers or reprocess with v2.0.

**Q: Do I need to redownload my Kraken2 database?**
A: No, existing databases work with v2.0.

**Q: What about my species of interest lists?**
A: Fully compatible - no changes needed.

**Q: Which container/runtime profile should I use?**
A: Conda is the canonical and supported profile for Nanometa Live with nanometanf. Docker and Singularity profiles exist in the upstream pipeline but are not used or tested through the GUI.

**Q: Does the pipeline basecall signal-level data?**
A: No. Nanometa Live v2 and the nanometanf pipeline accept only basecalled FASTQ input (live or batch). Run MinKNOW with basecalling enabled, or basecall separately, and point `nanopore_output_directory` at the resulting FASTQ directory.

## Support

- **Issues**: https://github.com/FOI-Bioinformatics/nanometa_live/issues
- **Documentation**: https://github.com/FOI-Bioinformatics/nanometa_live/wiki
- **Migration Help**: Tag issues with `migration-v2`

## Changelog Summary

### v2.0.0 - Nextflow/nanometanf Backend Migration

**Added:**
- Nextflow/nanometanf v1.1.0 backend integration
- NanometanfOutputParser for structured data access
- Real-time batch statistics monitoring
- Dynamic resource allocation
- Nextflow execution reports (HTML timeline, trace)

**Changed:**
- Backend: Snakemake → Nextflow/nanometanf
- Config format: String flags → native booleans
- Boolean parameters: Simplified (no more string flags)
- Output structure: Follows nanometanf conventions
- Performance: 10-15% faster with better resource usage

**Removed:**
- Snakemake dependency
- Snakemake-specific configuration adaptations
- Legacy output file structure (still parseable for migration)

**Fixed:**
- Real-time monitoring latency (45s → 22s)
- Resource over-allocation issues
- Memory usage spikes during high-throughput processing

## Migration Checklist

- [ ] Install Nextflow (`nextflow -version` works)
- [ ] Update Nanometa Live to v2.0
- [ ] Test with existing configuration (auto-converts)
- [ ] Verify Kraken2 database compatibility
- [ ] Review new output structure
- [ ] Update custom scripts to use NanometanfOutputParser
- [ ] Test real-time monitoring
- [ ] Benchmark performance vs v1.x (optional)
- [ ] Update documentation/SOPs to reference v2.0
- [ ] Archive v1.x environment (if needed for old analyses)

---

**Need Help?** Open an issue with the `migration-v2` tag and include:
- Nanometa Live version (`pip show nanometa-live`)
- Nextflow version (`nextflow -version`)
- Error logs (`~/nanometa_data/logs/nextflow.log`)
- Configuration file (sanitized paths)
