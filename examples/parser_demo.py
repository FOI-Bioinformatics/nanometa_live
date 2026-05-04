#!/usr/bin/env python3
"""
Demonstration script for NanometanfOutputParser.

This script shows common usage patterns for parsing nanometanf v1.1.0 outputs
and extracting key metrics for visualization in Nanometa Live.

Usage:
    python parser_demo.py /path/to/nanometanf/results
"""

import sys
import argparse
from pathlib import Path
from nanometa_live.core.parsers import NanometanfOutputParser, RealtimeMonitor


def demo_multiqc_parsing(parser: NanometanfOutputParser):
    """Demonstrate MultiQC data parsing."""
    print("\n" + "=" * 60)
    print("MULTIQC PARSING DEMONSTRATION")
    print("=" * 60)

    # Parse general statistics
    print("\n1. General Statistics:")
    general_stats = parser.parse_multiqc_general_stats()
    if not general_stats.empty:
        print(f"   Samples: {len(general_stats)}")
        print(f"   Columns: {', '.join(general_stats.columns[:5])}...")
        print("\n   Sample preview:")
        print(general_stats.head())
    else:
        print("   No MultiQC general stats found")

    # Parse FASTP data
    print("\n2. FASTP Data:")
    fastp_data = parser.parse_multiqc_fastp_data()
    if not fastp_data.empty:
        print(f"   Samples with FASTP data: {len(fastp_data)}")
        print(f"   Metrics: {', '.join(fastp_data.columns[:5])}...")
    else:
        print("   No FASTP data found")

    # Parse Kraken2 data
    print("\n3. Kraken2 Data:")
    kraken_data = parser.parse_multiqc_kraken_data()
    if not kraken_data.empty:
        print(f"   Samples with Kraken2 data: {len(kraken_data)}")
        print(f"   Metrics: {', '.join(kraken_data.columns[:5])}...")
    else:
        print("   No Kraken2 data found")


def demo_kraken_parsing(parser: NanometanfOutputParser):
    """Demonstrate Kraken2 report parsing."""
    print("\n" + "=" * 60)
    print("KRAKEN2 PARSING DEMONSTRATION")
    print("=" * 60)

    # Combine all reports
    print("\n1. Combined Kraken2 Reports:")
    combined = parser.combine_kraken_reports()
    if not combined.empty:
        print(f"   Total entries: {len(combined)}")
        print(f"   Samples: {combined['sample'].nunique()}")
        print(f"   Unique taxa: {combined['taxid'].nunique()}")

        # Show unclassified rate
        unclassified = combined[combined['rank'] == 'U']['reads_clade'].sum()
        total = combined[combined['rank'] == 'R']['reads_clade'].sum() + unclassified
        if total > 0:
            print(f"   Unclassified rate: {unclassified/total:.2%}")
    else:
        print("   No Kraken2 reports found")

    # Get top species
    print("\n2. Top 10 Species:")
    top_species = parser.get_top_species(n=10)
    if not top_species.empty:
        for idx, row in top_species.iterrows():
            print(f"   {idx+1:2d}. {row['name']:<40} {row['total_reads']:>10,} reads ({row['num_samples']} samples)")
    else:
        print("   No species-level classifications found")

    # Get specific species counts
    print("\n3. Specific Species Lookup:")
    # Common pathogenic bacteria
    target_taxids = ['562', '1280', '1350']  # E. coli, S. aureus, E. faecalis
    species_names = {
        '562': 'Escherichia coli',
        '1280': 'Staphylococcus aureus',
        '1350': 'Enterococcus faecalis'
    }

    counts = parser.get_species_read_counts(target_taxids)
    for taxid, name in species_names.items():
        read_count = counts.get(taxid, 0)
        print(f"   {name:<30} (taxid {taxid}): {read_count:>10,} reads")


def demo_fastp_parsing(parser: NanometanfOutputParser):
    """Demonstrate FASTP report parsing."""
    print("\n" + "=" * 60)
    print("FASTP PARSING DEMONSTRATION")
    print("=" * 60)

    # Get summary statistics
    print("\n1. FASTP Summary Statistics:")
    summary = parser.get_fastp_summary()
    if summary['total_samples'] > 0:
        print(f"   Total samples: {summary['total_samples']}")
        print(f"   Total reads before filtering: {summary['total_reads_before']:,}")
        print(f"   Total reads after filtering: {summary['total_reads_after']:,}")
        print(f"   Reads passing filter: {summary['total_passed_filter']:,}")
        print(f"   Low quality reads: {summary['total_low_quality']:,}")
        print(f"   Too short reads: {summary['total_too_short']:,}")
        print(f"\n   Quality Metrics:")
        print(f"   Avg Q20 rate (before): {summary['avg_q20_rate_before']:.2%}")
        print(f"   Avg Q30 rate (before): {summary['avg_q30_rate_before']:.2%}")
        print(f"   Avg Q20 rate (after):  {summary['avg_q20_rate_after']:.2%}")
        print(f"   Avg Q30 rate (after):  {summary['avg_q30_rate_after']:.2%}")
    else:
        print("   No FASTP reports found")

    # Combined reports
    print("\n2. Per-Sample FASTP Data:")
    combined = parser.combine_fastp_reports()
    if not combined.empty:
        print(f"   Samples processed: {len(combined)}")
        print("\n   Sample quality summary:")
        for idx, row in combined.head(5).iterrows():
            sample = row['sample']
            before = row['total_reads_before']
            after = row['total_reads_after']
            q30 = row['q30_rate_after']
            retention = (after / before * 100) if before > 0 else 0
            print(f"   {sample:<20} {before:>10,} → {after:>10,} reads ({retention:>5.1f}% retained, Q30: {q30:.2%})")
    else:
        print("   No combined FASTP data available")


def demo_blast_parsing(parser: NanometanfOutputParser):
    """Demonstrate BLAST results parsing."""
    print("\n" + "=" * 60)
    print("BLAST PARSING DEMONSTRATION")
    print("=" * 60)

    # Get validation summary
    print("\n1. BLAST Validation Summary:")
    summary = parser.get_blast_validation_summary()
    if summary['total_samples'] > 0:
        print(f"   Total samples: {summary['total_samples']}")
        print(f"   Total BLAST hits: {summary['total_hits']}")
        print(f"   Average percent identity: {summary['avg_identity']:.2f}%")
        print(f"   Identity range: {summary['min_identity']:.2f}% - {summary['max_identity']:.2f}%")
        print(f"   Average E-value: {summary['avg_evalue']:.2e}")
        print(f"   E-value range: {summary['min_evalue']:.2e} - {summary['max_evalue']:.2e}")
    else:
        print("   No BLAST results found")


def demo_realtime_parsing(parser: NanometanfOutputParser):
    """Demonstrate real-time batch statistics parsing."""
    print("\n" + "=" * 60)
    print("REAL-TIME BATCH PARSING DEMONSTRATION")
    print("=" * 60)

    # Get latest batch
    print("\n1. Latest Batch:")
    latest_batch = parser.get_latest_batch_number()
    print(f"   Latest batch number: {latest_batch}")

    if latest_batch > 0:
        batch_data = parser.parse_batch_stats(latest_batch)
        if batch_data:
            print(f"   Timestamp: {batch_data.get('timestamp', 'N/A')}")
            print(f"   Files in batch: {batch_data.get('files_in_batch', 0)}")
            print(f"   Reads in batch: {batch_data.get('reads_in_batch', 0):,}")
            print(f"   Classified: {batch_data.get('classified_in_batch', 0):,}")
            print(f"   Unclassified: {batch_data.get('unclassified_in_batch', 0):,}")

    # Get cumulative statistics
    print("\n2. Cumulative Statistics:")
    cumulative = parser.get_cumulative_stats()
    if cumulative['total_batches'] > 0:
        print(f"   Total batches processed: {cumulative['total_batches']}")
        print(f"   Total files processed: {cumulative['total_files']}")
        print(f"   Total reads processed: {cumulative['total_reads']:,}")
        print(f"   Total classified: {cumulative['total_classified']:,}")
        print(f"   Total unclassified: {cumulative['total_unclassified']:,}")
        print(f"   Overall classification rate: {cumulative['classification_rate']:.2%}")
        print(f"   Time range: {cumulative['first_batch_time']} → {cumulative['last_batch_time']}")
    else:
        print("   No batch statistics found")

    # Show all batches
    print("\n3. All Batches:")
    all_batches = parser.parse_all_batch_stats()
    if all_batches:
        print(f"   Total batches: {len(all_batches)}")
        print("\n   Batch details:")
        for batch in all_batches[:5]:  # Show first 5
            batch_num = batch.get('batch_number', 'N/A')
            reads = batch.get('reads_in_batch', 0)
            classified = batch.get('classified_in_batch', 0)
            rate = (classified / reads * 100) if reads > 0 else 0
            print(f"   Batch {batch_num:3d}: {reads:>8,} reads, {classified:>8,} classified ({rate:>5.1f}%)")
        if len(all_batches) > 5:
            print(f"   ... and {len(all_batches) - 5} more batches")
    else:
        print("   No batches found")


def demo_classification_summary(parser: NanometanfOutputParser):
    """Demonstrate comprehensive classification summary."""
    print("\n" + "=" * 60)
    print("COMPREHENSIVE CLASSIFICATION SUMMARY")
    print("=" * 60)

    summary = parser.get_classification_summary()

    # Kraken2 summary
    print("\n1. Kraken2 Classification:")
    if summary['kraken2']:
        k2 = summary['kraken2']
        print(f"   Total reads: {k2['total_reads']:,}")
        print(f"   Classified: {k2['classified']:,} ({k2['classification_rate']:.2%})")
        print(f"   Unclassified: {k2['unclassified']:,}")
    else:
        print("   No Kraken2 data available")

    # FASTP summary
    print("\n2. FASTP Quality Control:")
    if summary['fastp']:
        fastp = summary['fastp']
        if fastp.get('total_samples', 0) > 0:
            print(f"   Samples processed: {fastp['total_samples']}")
            print(f"   Reads before filtering: {fastp['total_reads_before']:,}")
            print(f"   Reads after filtering: {fastp['total_reads_after']:,}")
            print(f"   Average Q30 rate: {fastp['avg_q30_rate_after']:.2%}")
        else:
            print("   No FASTP data available")
    else:
        print("   No FASTP data available")

    # Real-time summary
    print("\n3. Real-time Processing:")
    if summary['realtime']:
        rt = summary['realtime']
        if rt.get('total_batches', 0) > 0:
            print(f"   Batches processed: {rt['total_batches']}")
            print(f"   Total reads: {rt['total_reads']:,}")
            print(f"   Classification rate: {rt['classification_rate']:.2%}")
        else:
            print("   No real-time data available")
    else:
        print("   No real-time data available")

    # Overall summary
    print("\n4. Overall Summary:")
    overall = summary['overall']
    print(f"   Total reads: {overall['total_reads']:,}")
    print(f"   Classified: {overall['classified']:,}")
    print(f"   Unclassified: {overall['unclassified']:,}")
    print(f"   Classification rate: {overall['classification_rate']:.2%}")


def demo_realtime_monitoring(outdir: str):
    """Demonstrate real-time monitoring."""
    print("\n" + "=" * 60)
    print("REAL-TIME MONITORING DEMONSTRATION")
    print("=" * 60)

    print("\n1. Setting up real-time monitor...")

    def batch_callback(batch_data):
        """Callback for new batch data."""
        batch_num = batch_data.get('batch_number', 'N/A')
        reads = batch_data.get('reads_in_batch', 0)
        classified = batch_data.get('classified_in_batch', 0)
        timestamp = batch_data.get('timestamp', 'N/A')

        print(f"   [NEW BATCH] {batch_num} @ {timestamp}")
        print(f"   └─ {reads:,} reads, {classified:,} classified")

    monitor = RealtimeMonitor(outdir, batch_callback)

    print("   Monitor initialized")
    print("\n2. Starting monitoring (polling every 10 seconds)...")
    print("   Press Ctrl+C to stop\n")

    try:
        monitor.start_monitoring(interval=10)

        # Keep running until interrupted
        import time
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n3. Stopping monitoring...")
        monitor.stop_monitoring()
        print("   Monitoring stopped")


def main():
    """Main demonstration function."""
    parser_args = argparse.ArgumentParser(
        description='Demonstrate NanometanfOutputParser functionality',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all demonstrations
  python parser_demo.py /path/to/nanometanf/results

  # Enable real-time monitoring (requires Ctrl+C to stop)
  python parser_demo.py /path/to/nanometanf/results --monitor
        """
    )

    parser_args.add_argument(
        'outdir',
        type=str,
        help='Path to nanometanf pipeline output directory'
    )

    parser_args.add_argument(
        '--monitor',
        action='store_true',
        help='Enable real-time monitoring demonstration (runs continuously)'
    )

    args = parser_args.parse_args()

    # Validate output directory
    outdir = Path(args.outdir)
    if not outdir.exists():
        print(f"Error: Output directory does not exist: {outdir}")
        sys.exit(1)

    print("=" * 60)
    print("NANOMETANF OUTPUT PARSER DEMONSTRATION")
    print("=" * 60)
    print(f"\nOutput directory: {outdir}")

    # Initialize parser
    parser = NanometanfOutputParser(str(outdir))

    if args.monitor:
        # Run real-time monitoring demonstration
        demo_realtime_monitoring(str(outdir))
    else:
        # Run all static demonstrations
        demo_multiqc_parsing(parser)
        demo_kraken_parsing(parser)
        demo_fastp_parsing(parser)
        demo_blast_parsing(parser)
        demo_realtime_parsing(parser)
        demo_classification_summary(parser)

        print("\n" + "=" * 60)
        print("DEMONSTRATION COMPLETE")
        print("=" * 60)
        print("\nTip: Run with --monitor to see real-time monitoring in action")


if __name__ == '__main__':
    main()
