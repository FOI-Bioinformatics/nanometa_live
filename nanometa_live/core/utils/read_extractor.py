"""
Read extractor utility for on-demand BLAST validation.

This module extracts reads classified to a specific taxid from Kraken2 output
and retrieves their sequences from the original FASTQ files.
"""

import gzip
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of read extraction operation."""
    taxid: int
    sample: str
    total_reads: int
    extracted_reads: int
    output_file: Path
    success: bool
    error_message: Optional[str] = None


class ReadExtractor:
    """
    Extract reads classified to a specific taxid for on-demand validation.

    This class parses Kraken2 per-read output to find read IDs classified
    to a target taxid, then extracts those sequences from FASTQ files.
    """

    def __init__(self, results_dir: str, input_dir: Optional[str] = None):
        """
        Initialize the read extractor.

        Args:
            results_dir: Path to pipeline results directory (contains kraken2/)
            input_dir: Path to original FASTQ input directory (optional)
        """
        self.results_dir = Path(results_dir)
        self.input_dir = Path(input_dir) if input_dir else None
        self.kraken2_dir = self.results_dir / "kraken2"

        # Output directory for extracted reads
        self.extraction_dir = self.results_dir / "extracted_reads"
        self.extraction_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized ReadExtractor with results_dir: {self.results_dir}")

    def find_kraken_output_file(self, sample: str) -> Optional[Path]:
        """
        Find the Kraken2 per-read output file for a sample.

        Args:
            sample: Sample name

        Returns:
            Path to Kraken2 output file or None if not found
        """
        # Try multiple file patterns (nanometanf output formats)
        patterns = [
            f"{sample}.kraken2",
            f"{sample}.kraken2.output.txt",
            f"{sample}.kraken2.output",
            f"{sample}_kraken2.output",
        ]

        for pattern in patterns:
            path = self.kraken2_dir / pattern
            if path.exists():
                logger.info(f"Found Kraken2 output: {path}")
                return path

        # Check for batch output files (real-time mode produces per-batch files)
        import glob as glob_mod
        batch_pattern = str(self.kraken2_dir / f"{sample}_batch*.kraken2.output.txt")
        batch_files = sorted(glob_mod.glob(batch_pattern))
        if batch_files:
            logger.info(f"Found batch Kraken2 output: {batch_files[-1]}")
            return Path(batch_files[-1])

        # Check for merged output in parent kraken2 directory
        merged_path = self.kraken2_dir / f"{sample}.merged.kraken2.output.txt"
        if merged_path.exists():
            logger.info(f"Found merged Kraken2 output: {merged_path}")
            return merged_path

        logger.warning(f"Kraken2 output not found for sample: {sample}")
        return None

    def get_read_ids_for_taxid(
        self,
        kraken_output: Path,
        taxid: int,
        include_children: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Set[str]:
        """
        Extract read IDs classified to a specific taxid from Kraken2 output.

        Args:
            kraken_output: Path to Kraken2 per-read output file
            taxid: Target taxonomy ID
            include_children: If True, also include reads classified to child taxa
                              (currently not implemented - requires taxonomy tree)
            progress_callback: Optional callback(processed, total) for progress updates

        Returns:
            Set of read IDs classified to the taxid
        """
        read_ids = set()
        total_lines = 0

        # Count total lines for progress reporting
        if progress_callback:
            with open(kraken_output, 'r') as f:
                total_lines = sum(1 for _ in f)

        processed = 0
        with open(kraken_output, 'r') as f:
            for line in f:
                processed += 1
                if progress_callback and processed % 100000 == 0:
                    progress_callback(processed, total_lines)

                parts = line.strip().split('\t')
                if len(parts) >= 3:
                    classified = parts[0]  # C = classified, U = unclassified
                    read_id = parts[1]
                    read_taxid_str = parts[2]

                    if classified == 'C':
                        try:
                            read_taxid = int(read_taxid_str)
                            if read_taxid == taxid:
                                read_ids.add(read_id)
                        except ValueError:
                            continue

        logger.info(f"Found {len(read_ids)} reads for taxid {taxid}")
        return read_ids

    def find_fastq_files(self, sample: str) -> List[Path]:
        """
        Find FASTQ files for a sample.

        Searches in the input directory for FASTQ files matching the sample name.

        Args:
            sample: Sample name

        Returns:
            List of paths to FASTQ files
        """
        fastq_files = []

        if not self.input_dir:
            logger.warning("Input directory not configured for FASTQ file search")
            return fastq_files

        # Search patterns - handle both flat and barcoded structures
        search_dirs = [
            self.input_dir,
            self.input_dir / sample,  # For barcoded samples
        ]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            # Find all FASTQ files
            for ext in ['*.fastq', '*.fastq.gz', '*.fq', '*.fq.gz']:
                fastq_files.extend(search_dir.glob(ext))

        logger.info(f"Found {len(fastq_files)} FASTQ files for sample {sample}")
        return fastq_files

    def extract_reads_from_fastq(
        self,
        fastq_files: List[Path],
        read_ids: Set[str],
        output_file: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> int:
        """
        Extract reads with specific IDs from FASTQ files.

        Args:
            fastq_files: List of FASTQ files to search
            read_ids: Set of read IDs to extract
            output_file: Path to output FASTA file
            progress_callback: Optional callback(extracted, total, message)

        Returns:
            Number of reads extracted
        """
        extracted_count = 0
        total_to_extract = len(read_ids)
        remaining_ids = read_ids.copy()

        with open(output_file, 'w') as out_f:
            for fastq_file in fastq_files:
                if not remaining_ids:
                    break  # All reads found

                logger.info(f"Searching in {fastq_file.name}...")
                if progress_callback:
                    progress_callback(extracted_count, total_to_extract, f"Searching {fastq_file.name}")

                # Handle gzipped files
                open_func = gzip.open if str(fastq_file).endswith('.gz') else open
                mode = 'rt' if str(fastq_file).endswith('.gz') else 'r'

                with open_func(fastq_file, mode) as f:
                    while True:
                        # Read FASTQ record (4 lines)
                        header = f.readline()
                        if not header:
                            break

                        sequence = f.readline().strip()
                        plus_line = f.readline()
                        quality = f.readline()

                        # Extract read ID from header
                        # FASTQ header format: @read_id [optional description]
                        read_id = header.strip().lstrip('@').split()[0]

                        if read_id in remaining_ids:
                            # Write as FASTA for BLAST
                            out_f.write(f">{read_id}\n")
                            out_f.write(f"{sequence}\n")

                            remaining_ids.discard(read_id)
                            extracted_count += 1

                            if progress_callback and extracted_count % 100 == 0:
                                progress_callback(extracted_count, total_to_extract, f"Extracted {extracted_count} reads")

        logger.info(f"Extracted {extracted_count} of {total_to_extract} reads to {output_file}")
        return extracted_count

    def extract_reads_for_taxid(
        self,
        sample: str,
        taxid: int,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> ExtractionResult:
        """
        Extract all reads for a taxid from a sample.

        This is the main method that orchestrates the full extraction process.

        Args:
            sample: Sample name
            taxid: Target taxonomy ID
            progress_callback: Optional callback(status_message, percent)

        Returns:
            ExtractionResult with details of the extraction
        """
        output_file = self.extraction_dir / f"{sample}_{taxid}.fasta"

        try:
            # Step 1: Find Kraken2 output file
            if progress_callback:
                progress_callback("Finding Kraken2 output...", 10)

            kraken_output = self.find_kraken_output_file(sample)
            if not kraken_output:
                return ExtractionResult(
                    taxid=taxid,
                    sample=sample,
                    total_reads=0,
                    extracted_reads=0,
                    output_file=output_file,
                    success=False,
                    error_message=f"Kraken2 output not found for sample {sample}"
                )

            # Step 2: Get read IDs for the taxid
            if progress_callback:
                progress_callback("Parsing Kraken2 output...", 20)

            read_ids = self.get_read_ids_for_taxid(kraken_output, taxid)

            if not read_ids:
                # No reads found - this is valid, just no classification
                return ExtractionResult(
                    taxid=taxid,
                    sample=sample,
                    total_reads=0,
                    extracted_reads=0,
                    output_file=output_file,
                    success=True,
                    error_message=None
                )

            total_reads = len(read_ids)

            # Step 3: Find FASTQ files
            if progress_callback:
                progress_callback("Finding FASTQ files...", 40)

            fastq_files = self.find_fastq_files(sample)

            if not fastq_files:
                return ExtractionResult(
                    taxid=taxid,
                    sample=sample,
                    total_reads=total_reads,
                    extracted_reads=0,
                    output_file=output_file,
                    success=False,
                    error_message=f"No FASTQ files found for sample {sample}"
                )

            # Step 4: Extract reads from FASTQ
            if progress_callback:
                progress_callback("Extracting reads from FASTQ...", 60)

            def fastq_progress(extracted, total, msg):
                if progress_callback:
                    pct = 60 + int(35 * extracted / max(total, 1))
                    progress_callback(f"Extracting: {extracted}/{total}", pct)

            extracted_count = self.extract_reads_from_fastq(
                fastq_files,
                read_ids,
                output_file,
                fastq_progress
            )

            if progress_callback:
                progress_callback("Extraction complete", 100)

            return ExtractionResult(
                taxid=taxid,
                sample=sample,
                total_reads=total_reads,
                extracted_reads=extracted_count,
                output_file=output_file,
                success=True,
                error_message=None
            )

        except Exception as e:
            logger.error(f"Error extracting reads for taxid {taxid}: {e}")
            return ExtractionResult(
                taxid=taxid,
                sample=sample,
                total_reads=0,
                extracted_reads=0,
                output_file=output_file,
                success=False,
                error_message=str(e)
            )

    def get_classified_taxids(self, sample: str) -> Dict[int, int]:
        """
        Get all taxids and their read counts from Kraken2 output.

        Useful for showing available taxids for on-demand validation.

        Args:
            sample: Sample name

        Returns:
            Dictionary mapping taxid to read count
        """
        kraken_output = self.find_kraken_output_file(sample)
        if not kraken_output:
            return {}

        taxid_counts: Dict[int, int] = {}

        with open(kraken_output, 'r') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 3 and parts[0] == 'C':
                    try:
                        taxid = int(parts[2])
                        taxid_counts[taxid] = taxid_counts.get(taxid, 0) + 1
                    except ValueError:
                        continue

        return taxid_counts
