# NanometanfOutputParser Guide

Comprehensive documentation for the `NanometanfOutputParser` class - the primary interface for parsing all nanometanf v1.1.0 pipeline outputs in Nanometa Live.

## Overview

The `NanometanfOutputParser` provides a unified API for accessing data from:
- MultiQC aggregated reports
- Kraken2 taxonomic classification results
- FASTP quality control metrics
- BLAST validation results
- Real-time batch processing statistics

## Quick Start

```python
from nanometa_live.core.parsers import NanometanfOutputParser

# Initialize parser with pipeline output directory
parser = NanometanfOutputParser("/path/to/nanometanf/results")

# Parse MultiQC general statistics
general_stats = parser.parse_multiqc_general_stats()

# Get top 10 species by read count
top_species = parser.get_top_species(n=10)

# Get comprehensive classification summary
summary = parser.get_classification_summary()
```

## Installation

The parser is included with Nanometa Live. Ensure dependencies are installed:

```bash
pip install pandas numpy
```

## Class Reference

### NanometanfOutputParser

Main parser class for all nanometanf outputs.

#### Initialization

```python
parser = NanometanfOutputParser(outdir: str)
```

**Parameters:**
- `outdir` (str): Path to nanometanf pipeline output directory

**Attributes:**
- `outdir` (Path): Pipeline output directory
- `multiqc_dir` (Path): MultiQC subdirectory
- `fastp_dir` (Path): FASTP subdirectory
- `kraken2_dir` (Path): Kraken2 subdirectory
- `blast_dir` (Path): BLAST subdirectory
- `realtime_batch_dir` (Path): Real-time batch statistics subdirectory

#### Directory Structure Expected

```
results/
├── multiqc/
│   └── multiqc_data/
│       ├── multiqc_general_stats.txt
│       ├── multiqc_data.json
│       ├── multiqc_fastp.txt
│       └── multiqc_kraken.txt
├── fastp/
│   ├── sample1.fastp.json
│   └── sample2.fastp.json
├── kraken2/
│   ├── sample1.kreport2
│   ├── sample1.kraken2
│   └── sample2.kreport2
├── blast/
│   ├── sample1_1350.blast.txt
│   └── sample2_562.blast.txt
└── realtime_batch_stats/
    ├── batch_0001_stats.json
    ├── batch_0002_stats.json
    └── batch_0003_stats.json
```

## MultiQC Parsers

### parse_multiqc_general_stats()

Parse MultiQC general statistics table with sample-level aggregated metrics.

**Returns:** `pd.DataFrame`

**Example:**
```python
df = parser.parse_multiqc_general_stats()
print(df.columns)
# ['FASTQ Total Reads', 'Kraken Classified %', 'FASTP Q20 Rate', ...]
```

### parse_multiqc_json()

Parse complete MultiQC JSON data structure.

**Returns:** `Dict[str, Any]`

**Example:**
```python
data = parser.parse_multiqc_json()
plot_data = data.get('report_plot_data', {})
```

### parse_multiqc_fastp_data()

Parse MultiQC aggregated FASTP data.

**Returns:** `pd.DataFrame`

**Example:**
```python
df = parser.parse_multiqc_fastp_data()
print(df['total_reads_before'].sum())
```

### parse_multiqc_kraken_data()

Parse MultiQC aggregated Kraken2 data.

**Returns:** `pd.DataFrame`

**Example:**
```python
df = parser.parse_multiqc_kraken_data()
print(df['classification_rate'].mean())
```

## Kraken2 Parsers

### parse_kraken_report(sample: str)

Parse Kraken2 kreport2 format file for a specific sample.

**Parameters:**
- `sample` (str): Sample name

**Returns:** `pd.DataFrame` with columns:
- `percent` (float): Percentage of reads in clade
- `reads_clade` (int): Reads covered by clade
- `reads_taxon` (int): Reads assigned directly to taxon
- `rank` (str): Taxonomic rank code (U, R, D, K, P, C, O, F, G, S)
- `taxid` (int): NCBI taxonomy ID
- `name` (str): Scientific name

**Example:**
```python
df = parser.parse_kraken_report("sample1")

# Filter for species-level classifications
species = df[df['rank'] == 'S']
print(species[['name', 'reads_clade']].head())
```

**Kraken2 Report Format:**
```
0.15    300     300     U       0       unclassified
99.85   19970   0       R       1       root
99.85   19970   100     D       2       Bacteria
50.00   10000   50      P       1239    Firmicutes
25.00   5000    100     S       1350    Enterococcus faecalis
```

### parse_kraken_output(sample: str)

Parse Kraken2 per-read classification output.

**Parameters:**
- `sample` (str): Sample name

**Returns:** `Dict[int, int]` mapping taxid to read counts

**Example:**
```python
taxid_counts = parser.parse_kraken_output("sample1")
print(f"Taxid 1350: {taxid_counts.get(1350, 0)} reads")
```

### combine_kraken_reports()

Combine Kraken2 reports from all samples.

**Returns:** `pd.DataFrame` with all samples' classification data

**Example:**
```python
df = parser.combine_kraken_reports()

# Group by species across all samples
species_summary = df[df['rank'] == 'S'].groupby('name')['reads_clade'].sum()
print(species_summary.sort_values(ascending=False).head(10))
```

### get_species_read_counts(species_taxids: List[str])

Get read counts for specific species across all samples.

**Parameters:**
- `species_taxids` (List[str]): List of NCBI taxonomy IDs

**Returns:** `Dict[str, int]` mapping taxid to total read count

**Example:**
```python
# Get counts for E. coli (562) and S. aureus (1280)
counts = parser.get_species_read_counts(['562', '1280'])
print(f"E. coli: {counts['562']} reads")
print(f"S. aureus: {counts['1280']} reads")
```

### get_top_species(n: int = 10)

Get top N species by read count across all samples.

**Parameters:**
- `n` (int): Number of top species (default: 10)

**Returns:** `pd.DataFrame` with columns:
- `taxid` (int): NCBI taxonomy ID
- `name` (str): Species name
- `total_reads` (int): Total reads across all samples
- `samples` (list): List of samples containing this species
- `num_samples` (int): Number of samples

**Example:**
```python
top10 = parser.get_top_species(n=10)
print(top10[['name', 'total_reads', 'num_samples']])
```

## FASTP Parsers

### parse_fastp_report(sample: str)

Parse FASTP JSON report for a specific sample.

**Parameters:**
- `sample` (str): Sample name

**Returns:** `Dict[str, Any]` with FASTP JSON structure

**Example:**
```python
data = parser.parse_fastp_report("sample1")
before = data['summary']['before_filtering']
after = data['summary']['after_filtering']

print(f"Reads: {before['total_reads']} → {after['total_reads']}")
print(f"Q30 rate: {before['q30_rate']:.2%} → {after['q30_rate']:.2%}")
```

**FASTP JSON Structure:**
```json
{
  "summary": {
    "before_filtering": {
      "total_reads": 10000,
      "total_bases": 5000000,
      "q20_rate": 0.95,
      "q30_rate": 0.90,
      "gc_content": 0.45
    },
    "after_filtering": {
      "total_reads": 9500,
      "total_bases": 4750000,
      "q20_rate": 0.97,
      "q30_rate": 0.92,
      "gc_content": 0.45
    }
  },
  "filtering_result": {
    "passed_filter_reads": 9500,
    "low_quality_reads": 300,
    "too_short_reads": 200
  }
}
```

### combine_fastp_reports()

Combine FASTP reports from all samples.

**Returns:** `pd.DataFrame` with aggregated FASTP statistics

**Example:**
```python
df = parser.combine_fastp_reports()
print(df[['sample', 'total_reads_before', 'total_reads_after', 'q30_rate_after']])
```

### get_fastp_summary()

Get summary statistics across all FASTP reports.

**Returns:** `Dict[str, Any]` with keys:
- `total_samples` (int)
- `total_reads_before` (int)
- `total_reads_after` (int)
- `total_bases_before` (int)
- `total_bases_after` (int)
- `avg_q20_rate_before` (float)
- `avg_q30_rate_before` (float)
- `avg_q20_rate_after` (float)
- `avg_q30_rate_after` (float)
- `total_passed_filter` (int)
- `total_low_quality` (int)
- `total_too_short` (int)

**Example:**
```python
summary = parser.get_fastp_summary()
print(f"Total samples: {summary['total_samples']}")
print(f"Total reads: {summary['total_reads_before']:,}")
print(f"Passed filter: {summary['total_passed_filter']:,}")
print(f"Avg Q30 rate: {summary['avg_q30_rate_after']:.2%}")
```

## BLAST Parsers

### parse_blast_results(sample: str, taxid: str = None)

Parse BLAST results for a specific sample.

**Parameters:**
- `sample` (str): Sample name
- `taxid` (str, optional): Taxonomy ID filter

**Returns:** `pd.DataFrame` with columns:
- `qseqid` (str): Query sequence ID
- `sseqid` (str): Subject sequence ID
- `pident` (float): Percent identity
- `length` (int): Alignment length
- `mismatch` (int): Number of mismatches
- `gapopen` (int): Number of gap openings
- `qstart` (int): Query start position
- `qend` (int): Query end position
- `sstart` (int): Subject start position
- `send` (int): Subject end position
- `evalue` (float): Expect value
- `bitscore` (float): Bit score

**Example:**
```python
df = parser.parse_blast_results("sample1", taxid="1350")

# Filter for high-quality hits
high_quality = df[(df['pident'] > 95) & (df['evalue'] < 1e-50)]
print(f"High-quality hits: {len(high_quality)}")
```

### get_blast_validation_summary()

Get BLAST validation summary across all samples.

**Returns:** `Dict[str, Any]` with validation statistics

**Example:**
```python
summary = parser.get_blast_validation_summary()
print(f"Total samples: {summary['total_samples']}")
print(f"Total hits: {summary['total_hits']}")
print(f"Avg identity: {summary['avg_identity']:.2f}%")
print(f"Avg E-value: {summary['avg_evalue']:.2e}")
```

## Real-time Batch Parsers

### parse_batch_stats(batch_number: int)

Parse statistics for a specific batch.

**Parameters:**
- `batch_number` (int): Batch number

**Returns:** `Dict[str, Any]` with batch data

**Example:**
```python
batch = parser.parse_batch_stats(1)
print(f"Batch {batch['batch_number']}")
print(f"Timestamp: {batch['timestamp']}")
print(f"Files: {batch['files_in_batch']}")
print(f"Reads: {batch['reads_in_batch']}")
print(f"Classified: {batch['classified_in_batch']}")
```

**Batch Stats JSON Format:**
```json
{
  "batch_number": 1,
  "timestamp": "2025-10-06T12:34:56",
  "files_in_batch": 10,
  "reads_in_batch": 50000,
  "classified_in_batch": 45000,
  "unclassified_in_batch": 5000
}
```

### get_latest_batch_number()

Get the latest batch number.

**Returns:** `int` (0 if no batches found)

**Example:**
```python
latest = parser.get_latest_batch_number()
print(f"Latest batch: {latest}")
```

### parse_all_batch_stats()

Parse all available batch statistics.

**Returns:** `List[Dict[str, Any]]` with all batch data

**Example:**
```python
batches = parser.parse_all_batch_stats()
for batch in batches:
    print(f"Batch {batch['batch_number']}: {batch['reads_in_batch']} reads")
```

### get_cumulative_stats()

Get cumulative statistics across all batches.

**Returns:** `Dict[str, Any]` with keys:
- `total_batches` (int)
- `total_files` (int)
- `total_reads` (int)
- `total_classified` (int)
- `total_unclassified` (int)
- `classification_rate` (float)
- `first_batch_time` (str)
- `last_batch_time` (str)

**Example:**
```python
stats = parser.get_cumulative_stats()
print(f"Total batches: {stats['total_batches']}")
print(f"Total reads: {stats['total_reads']:,}")
print(f"Classification rate: {stats['classification_rate']:.2%}")
print(f"Time range: {stats['first_batch_time']} to {stats['last_batch_time']}")
```

## Summary Methods

### get_classification_summary()

Get comprehensive classification summary across all data sources.

**Returns:** `Dict[str, Any]` with keys:
- `kraken2` (dict): Kraken2 classification stats
- `fastp` (dict): FASTP quality stats
- `realtime` (dict): Real-time batch stats
- `overall` (dict): Overall classification summary

**Example:**
```python
summary = parser.get_classification_summary()

# Kraken2 stats
k2 = summary['kraken2']
print(f"Kraken2 total reads: {k2['total_reads']:,}")
print(f"Classified: {k2['classified']:,} ({k2['classification_rate']:.2%})")

# FASTP stats
fastp = summary['fastp']
print(f"FASTP samples: {fastp['total_samples']}")
print(f"Avg Q30 rate: {fastp['avg_q30_rate_after']:.2%}")

# Overall summary
overall = summary['overall']
print(f"Overall classification rate: {overall['classification_rate']:.2%}")
```

## RealtimeMonitor

Monitor for new batch statistics in real-time processing mode.

### Initialization

```python
from nanometa_live.core.parsers import RealtimeMonitor

def on_new_batch(batch_data):
    print(f"New batch {batch_data['batch_number']}: {batch_data['reads_in_batch']} reads")

monitor = RealtimeMonitor(
    outdir="/path/to/nanometanf/results",
    update_callback=on_new_batch
)
```

**Parameters:**
- `outdir` (str): Pipeline output directory
- `update_callback` (Callable): Function to call with new batch data

### start_monitoring(interval: int = 10)

Start monitoring for new batches.

**Parameters:**
- `interval` (int): Polling interval in seconds (default: 10)

**Example:**
```python
monitor.start_monitoring(interval=5)  # Check every 5 seconds
```

### stop_monitoring()

Stop monitoring for new batches.

**Example:**
```python
monitor.stop_monitoring()
```

### Complete Real-time Monitoring Example

```python
import time
from nanometa_live.core.parsers import RealtimeMonitor

# Track processed batches
processed_batches = []

def handle_new_batch(batch_data):
    """Callback for new batch data."""
    batch_num = batch_data['batch_number']
    reads = batch_data['reads_in_batch']
    classified = batch_data['classified_in_batch']

    print(f"[Batch {batch_num}] {reads:,} reads, {classified:,} classified")
    processed_batches.append(batch_data)

# Initialize monitor
monitor = RealtimeMonitor(
    outdir="/path/to/nanometanf/results",
    update_callback=handle_new_batch
)

# Start monitoring (runs in background thread)
monitor.start_monitoring(interval=10)

try:
    # Let it run for some time
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    # Stop monitoring on Ctrl+C
    monitor.stop_monitoring()
    print(f"Processed {len(processed_batches)} batches total")
```

## Error Handling

All parser methods implement graceful error handling:

- **Missing files**: Return empty DataFrames/dicts instead of raising exceptions
- **Malformed data**: Log warnings and return empty structures
- **File I/O errors**: Retry logic for transient failures (real-time monitoring)

**Example:**
```python
# Safe to call even if file doesn't exist
df = parser.parse_kraken_report("nonexistent_sample")
if df.empty:
    print("No data available")
else:
    print(f"Found {len(df)} classifications")
```

## Logging

Enable detailed logging for debugging:

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Parser will now log operations
parser = NanometanfOutputParser("/path/to/results")
df = parser.parse_kraken_report("sample1")
# INFO - nanometa_live.core.parsers.nanometanf_parser - Parsed Kraken2 report for sample1: 150 taxa
```

## Integration with Dash

Example Dash callback using the parser:

```python
from dash import Input, Output
from nanometa_live.core.parsers import NanometanfOutputParser

parser = NanometanfOutputParser("/path/to/results")

@app.callback(
    Output('species-graph', 'figure'),
    Input('refresh-button', 'n_clicks')
)
def update_species_graph(n_clicks):
    # Get top species
    df = parser.get_top_species(n=10)

    # Create Plotly figure
    fig = px.bar(
        df,
        x='name',
        y='total_reads',
        title='Top 10 Species by Read Count'
    )

    return fig
```

## Performance Considerations

**File Caching:**
- Parser reads files on-demand (no automatic caching)
- For repeated access, cache DataFrames in your application:

```python
# Cache expensive operations
from functools import lru_cache

@lru_cache(maxsize=128)
def get_cached_kraken_reports(outdir):
    parser = NanometanfOutputParser(outdir)
    return parser.combine_kraken_reports()
```

**Large Datasets:**
- For very large Kraken2 outputs, consider filtering early:

```python
# Filter for species only during parsing
df = parser.parse_kraken_report("sample1")
species_only = df[df['rank'] == 'S']  # Much smaller DataFrame
```

**Real-time Monitoring:**
- Use appropriate polling intervals (5-30 seconds recommended)
- Monitor runs in background thread (non-blocking)

## Troubleshooting

**Problem:** Empty DataFrames returned
**Solution:** Check file paths and naming conventions. Enable logging to see warnings.

**Problem:** File not found errors in real-time mode
**Solution:** Increase retry count or delay in `file_exists_with_retry()`

**Problem:** Memory issues with large datasets
**Solution:** Process samples individually rather than combining all at once

**Problem:** Real-time monitor callback not triggering
**Solution:** Verify batch files are being written to correct directory and have proper naming

## API Summary

| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `parse_multiqc_general_stats()` | - | DataFrame | Sample-level QC metrics |
| `parse_multiqc_json()` | - | Dict | Complete MultiQC data |
| `parse_kraken_report(sample)` | sample name | DataFrame | Kraken2 taxonomic report |
| `combine_kraken_reports()` | - | DataFrame | All Kraken2 reports |
| `get_top_species(n)` | count | DataFrame | Top N species |
| `parse_fastp_report(sample)` | sample name | Dict | FASTP QC report |
| `combine_fastp_reports()` | - | DataFrame | All FASTP reports |
| `get_fastp_summary()` | - | Dict | FASTP totals |
| `parse_blast_results(sample, taxid)` | sample, taxid | DataFrame | BLAST hits |
| `parse_batch_stats(batch_num)` | batch number | Dict | Batch statistics |
| `get_cumulative_stats()` | - | Dict | Cumulative batch stats |
| `get_classification_summary()` | - | Dict | Overall classification summary |

## See Also

- [Nanometa Live Architecture](architecture.md)
- [Dash Development Guide](dash_development.md)
- [nanometanf Pipeline Documentation](https://github.com/foi-bioinformatics/nanometanf)
