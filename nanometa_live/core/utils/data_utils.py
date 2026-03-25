"""
Data utility functions for Nanometa Live.

This module provides utility functions for data handling and processing
used by the application.
"""

import logging
import json
import pandas as pd
from typing import Dict, Any, List, Tuple


def parse_kraken_report(report_file: str) -> pd.DataFrame:
    """
    Parse a Kraken report file into a pandas DataFrame.

    Args:
        report_file: Path to the Kraken report file

    Returns:
        DataFrame with parsed report data
    """
    try:
        df = pd.read_csv(
            report_file,
            sep="\t",
            header=None,
            names=["%", "cumul_reads", "reads", "rank", "taxid", "name"],
        )

        logging.info(f"Parsed Kraken report {report_file} with {len(df)} entries")
        return df

    except Exception as e:
        logging.error(f"Error parsing Kraken report {report_file}: {e}")
        # Return empty DataFrame with correct columns
        return pd.DataFrame(
            columns=["%", "cumul_reads", "reads", "rank", "taxid", "name"]
        )


def parse_kraken_output(kraken_file: str) -> Dict[str, int]:
    """
    Parse a Kraken output file to extract read counts by taxid.

    Args:
        kraken_file: Path to the Kraken output file

    Returns:
        Dictionary mapping taxids to read counts
    """
    taxid_counts = {}

    try:
        with open(kraken_file, "r") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 3:
                    continue

                # Extract classification
                classification = parts[2]
                taxid = classification

                # Handle format variations
                if classification.startswith("taxid "):
                    taxid = classification.split(" ")[1].strip()

                # Count reads
                try:
                    taxid = int(taxid)
                    if taxid in taxid_counts:
                        taxid_counts[taxid] += 1
                    else:
                        taxid_counts[taxid] = 1
                except ValueError:
                    # Skip non-integer taxids
                    continue

        logging.info(
            f"Parsed Kraken output {kraken_file} with {len(taxid_counts)} unique taxids"
        )
        return taxid_counts

    except Exception as e:
        logging.error(f"Error parsing Kraken output {kraken_file}: {e}")
        return {}


def parse_fastq_file(fastq_file: str) -> Tuple[int, int]:
    """
    Parse a FASTQ file to extract basic statistics.

    Args:
        fastq_file: Path to the FASTQ file (can be gzipped)

    Returns:
        Tuple of (read_count, total_base_pairs)
    """
    try:
        read_count = 0
        total_bp = 0

        # Open file based on extension
        if fastq_file.endswith(".gz"):
            import gzip

            f = gzip.open(fastq_file, "rt")
        else:
            f = open(fastq_file, "r")

        # Process file
        line_count = 0
        for line in f:
            line_count += 1
            if line_count % 4 == 1:  # Header line
                read_count += 1
            elif line_count % 4 == 2:  # Sequence line
                total_bp += len(line.strip())

        f.close()

        logging.info(f"Parsed {fastq_file}: {read_count} reads, {total_bp} bp")
        return read_count, total_bp

    except Exception as e:
        logging.error(f"Error parsing FASTQ file {fastq_file}: {e}")
        return 0, 0


def parse_fastp_report(report_file: str) -> Dict[str, int]:
    """
    Parse a FastP JSON report file.

    Args:
        report_file: Path to the FastP JSON report file

    Returns:
        Dictionary with filtering statistics
    """
    try:
        with open(report_file, "r") as f:
            report_data = json.load(f)

        # Extract filtering results
        filtering_result = report_data.get("filtering_result", {})
        stats = {
            "passed_filter_reads": filtering_result.get("passed_filter_reads", 0),
            "low_quality_reads": filtering_result.get("low_quality_reads", 0),
            "too_many_N_reads": filtering_result.get("too_many_N_reads", 0),
            "too_short_reads": filtering_result.get("too_short_reads", 0),
        }

        logging.info(f"Parsed FastP report {report_file}")
        return stats

    except Exception as e:
        logging.error(f"Error parsing FastP report {report_file}: {e}")
        return {
            "passed_filter_reads": 0,
            "low_quality_reads": 0,
            "too_many_N_reads": 0,
            "too_short_reads": 0,
        }


def parse_blast_results(blast_file: str) -> Tuple[int, int]:
    """
    Parse BLAST results to count validated reads.

    Args:
        blast_file: Path to BLAST results file

    Returns:
        Tuple of (unique_reads, total_alignments)
    """
    try:
        # Read BLAST output
        df = pd.read_csv(
            blast_file,
            sep="\t",
            header=None,
            names=[
                "qseqid",
                "sseqid",
                "pident",
                "length",
                "mismatch",
                "gapopen",
                "qstart",
                "qend",
                "sstart",
                "send",
                "evalue",
                "bitscore",
            ],
        )

        # Count unique reads and total alignments
        unique_reads = df["qseqid"].nunique()
        total_alignments = len(df)

        logging.info(
            f"Parsed BLAST results {blast_file}: {unique_reads} unique reads, {total_alignments} alignments"
        )
        return unique_reads, total_alignments

    except Exception as e:
        logging.error(f"Error parsing BLAST results {blast_file}: {e}")
        return 0, 0


def extract_classified_reads(kraken_report: str) -> Tuple[int, int, float, float]:
    """
    Extract classification statistics from a Kraken report.

    Args:
        kraken_report: Path to a Kraken report file

    Returns:
        Tuple of (classified_reads, unclassified_reads, percent_classified, percent_unclassified)
    """
    try:
        # Parse the Kraken report
        df = parse_kraken_report(kraken_report)

        # Extract unclassified reads (first row, taxid 0)
        unclassified_row = df[df["taxid"] == 0]

        if unclassified_row.empty:
            unclassified_reads = 0
            percent_unclassified = 0.0
        else:
            unclassified_reads = int(unclassified_row.iloc[0]["reads"])
            percent_unclassified = float(unclassified_row.iloc[0]["%"])

        # Get total reads from cumulative reads
        root_row = df[df["taxid"] == 1]

        if root_row.empty:
            # If no root row, use sum of all reads
            total_reads = unclassified_reads + df[df["taxid"] != 0]["reads"].sum()
        else:
            # Use root row cumulative reads
            total_reads = int(root_row.iloc[0]["cumul_reads"]) + unclassified_reads

        # Calculate classified reads
        classified_reads = total_reads - unclassified_reads

        # Calculate percentages
        if total_reads > 0:
            percent_classified = 100.0 - percent_unclassified
        else:
            percent_classified = 0.0

        logging.info(
            f"Extracted classification stats from {kraken_report}: {classified_reads} classified ({percent_classified:.1f}%), {unclassified_reads} unclassified ({percent_unclassified:.1f}%)"
        )
        return (
            classified_reads,
            unclassified_reads,
            percent_classified,
            percent_unclassified,
        )

    except Exception as e:
        logging.error(
            f"Error extracting classification stats from {kraken_report}: {e}"
        )
        return 0, 0, 0.0, 0.0
