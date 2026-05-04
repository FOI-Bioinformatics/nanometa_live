"""
Mock Data Generator for Nanometa Live v2.0 Testing.

Generates realistic test data that mimics nanometanf pipeline output
for development, testing, and demonstration purposes.
"""

import random
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd


class MockDataScenario:
    """Predefined scenarios for testing different situations."""

    NORMAL_RUN = "normal"              # Everything working well
    QUALITY_ISSUES = "quality_issues"  # Low quality samples
    PATHOGEN_DETECTED = "pathogen"     # Target species found
    MIXED_QUALITY = "mixed"            # Some good, some bad
    LOW_YIELD = "low_yield"            # Insufficient reads
    HIGH_DIVERSITY = "high_diversity"  # Many organisms


class MockDataGenerator:
    """
    Generate realistic mock data for Nanometa Live testing.

    Simulates nanometanf pipeline output including:
    - Kraken2 taxonomic classification reports
    - FASTP quality control statistics
    - Sample-level data for multiplexed runs
    """

    # Common organism database for realistic testing
    COMMON_ORGANISMS = [
        {"taxid": 562, "name": "Escherichia coli", "rank": "S", "typical_abundance": 0.15,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1224, "name": "Pseudomonadota", "rank": "P"},
             {"taxid": 1236, "name": "Gammaproteobacteria", "rank": "C"},
             {"taxid": 91347, "name": "Enterobacterales", "rank": "O"},
             {"taxid": 543, "name": "Enterobacteriaceae", "rank": "F"},
             {"taxid": 561, "name": "Escherichia", "rank": "G"},
         ]},
        {"taxid": 1280, "name": "Staphylococcus aureus", "rank": "S", "typical_abundance": 0.10,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1239, "name": "Bacillota", "rank": "P"},
             {"taxid": 91061, "name": "Bacilli", "rank": "C"},
             {"taxid": 1385, "name": "Bacillales", "rank": "O"},
             {"taxid": 90964, "name": "Staphylococcaceae", "rank": "F"},
             {"taxid": 1279, "name": "Staphylococcus", "rank": "G"},
         ]},
        {"taxid": 1351, "name": "Enterococcus faecalis", "rank": "S", "typical_abundance": 0.08,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1239, "name": "Bacillota", "rank": "P"},
             {"taxid": 91061, "name": "Bacilli", "rank": "C"},
             {"taxid": 186826, "name": "Lactobacillales", "rank": "O"},
             {"taxid": 81852, "name": "Enterococcaceae", "rank": "F"},
             {"taxid": 1350, "name": "Enterococcus", "rank": "G"},
         ]},
        {"taxid": 287, "name": "Pseudomonas aeruginosa", "rank": "S", "typical_abundance": 0.12,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1224, "name": "Pseudomonadota", "rank": "P"},
             {"taxid": 1236, "name": "Gammaproteobacteria", "rank": "C"},
             {"taxid": 72274, "name": "Pseudomonadales", "rank": "O"},
             {"taxid": 135621, "name": "Pseudomonadaceae", "rank": "F"},
             {"taxid": 286, "name": "Pseudomonas", "rank": "G"},
         ]},
        {"taxid": 1392, "name": "Bacillus anthracis", "rank": "S", "typical_abundance": 0.001,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1239, "name": "Bacillota", "rank": "P"},
             {"taxid": 91061, "name": "Bacilli", "rank": "C"},
             {"taxid": 1385, "name": "Bacillales", "rank": "O"},
             {"taxid": 186817, "name": "Bacillaceae", "rank": "F"},
             {"taxid": 1386, "name": "Bacillus", "rank": "G"},
         ]},
        {"taxid": 632, "name": "Yersinia pestis", "rank": "S", "typical_abundance": 0.001,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1224, "name": "Pseudomonadota", "rank": "P"},
             {"taxid": 1236, "name": "Gammaproteobacteria", "rank": "C"},
             {"taxid": 91347, "name": "Enterobacterales", "rank": "O"},
             {"taxid": 1903411, "name": "Yersiniaceae", "rank": "F"},
             {"taxid": 629, "name": "Yersinia", "rank": "G"},
         ]},
        {"taxid": 1423, "name": "Bacillus subtilis", "rank": "S", "typical_abundance": 0.07,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1239, "name": "Bacillota", "rank": "P"},
             {"taxid": 91061, "name": "Bacilli", "rank": "C"},
             {"taxid": 1385, "name": "Bacillales", "rank": "O"},
             {"taxid": 186817, "name": "Bacillaceae", "rank": "F"},
             {"taxid": 1386, "name": "Bacillus", "rank": "G"},
         ]},
        {"taxid": 1613, "name": "Lactobacillus fermentum", "rank": "S", "typical_abundance": 0.05,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1239, "name": "Bacillota", "rank": "P"},
             {"taxid": 91061, "name": "Bacilli", "rank": "C"},
             {"taxid": 186826, "name": "Lactobacillales", "rank": "O"},
             {"taxid": 33958, "name": "Lactobacillaceae", "rank": "F"},
             {"taxid": 1578, "name": "Lactobacillus", "rank": "G"},
         ]},
        {"taxid": 817, "name": "Bacteroides fragilis", "rank": "S", "typical_abundance": 0.09,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 976, "name": "Bacteroidota", "rank": "P"},
             {"taxid": 200643, "name": "Bacteroidia", "rank": "C"},
             {"taxid": 171549, "name": "Bacteroidales", "rank": "O"},
             {"taxid": 815, "name": "Bacteroidaceae", "rank": "F"},
             {"taxid": 816, "name": "Bacteroides", "rank": "G"},
         ]},
        {"taxid": 1491, "name": "Clostridium botulinum", "rank": "S", "typical_abundance": 0.002,
         "lineage": [
             {"taxid": 2, "name": "Bacteria", "rank": "D"},
             {"taxid": 1239, "name": "Bacillota", "rank": "P"},
             {"taxid": 186801, "name": "Clostridia", "rank": "C"},
             {"taxid": 186802, "name": "Eubacteriales", "rank": "O"},
             {"taxid": 31979, "name": "Clostridiaceae", "rank": "F"},
             {"taxid": 1485, "name": "Clostridium", "rank": "G"},
         ]},
    ]

    def __init__(self, base_dir: str, scenario: str = MockDataScenario.NORMAL_RUN):
        """
        Initialize mock data generator.

        Args:
            base_dir: Base directory for output files
            scenario: Testing scenario to simulate
        """
        self.base_dir = base_dir
        self.scenario = scenario
        self.timestamp = datetime.now()

    def generate_complete_dataset(
        self,
        num_samples: int = 3,
        total_reads_range: Tuple[int, int] = (50000, 150000)
    ) -> Dict[str, str]:
        """
        Generate a complete dataset simulating nanometanf output.

        Args:
            num_samples: Number of barcoded samples to generate
            total_reads_range: Min and max total reads per sample

        Returns:
            Dictionary mapping file types to created paths
        """
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, "kraken2"), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, "fastp"), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, "multiqc", "multiqc_data"), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, "qc"), exist_ok=True)

        created_files = {}

        # Generate per-sample data
        for i in range(1, num_samples + 1):
            sample_name = f"barcode{i:02d}"

            # Generate Kraken2 report
            kraken_file = self._generate_kraken2_report(
                sample_name,
                random.randint(*total_reads_range)
            )
            created_files[f"kraken_{sample_name}"] = kraken_file

            # Generate FASTP JSON (comprehensive QC)
            fastp_file = self._generate_fastp_json(sample_name)
            created_files[f"fastp_{sample_name}"] = fastp_file

            # Generate QC text summary (legacy)
            qc_file = self._generate_qc_stats(sample_name)
            created_files[f"qc_{sample_name}"] = qc_file

        # Generate aggregate files
        created_files["multiqc"] = self._generate_multiqc_general_stats(num_samples)
        created_files["summary"] = self._generate_summary_stats(num_samples)

        return created_files

    def _generate_kraken2_report(self, sample_name: str, total_reads: int) -> str:
        """
        Generate a Kraken2-style taxonomic report.

        Format matches actual Kraken2 kreport2 output.
        """
        kraken_dir = os.path.join(self.base_dir, "kraken2")
        output_file = os.path.join(kraken_dir, f"{sample_name}.kreport2.txt")

        # Calculate classified vs unclassified based on scenario
        if self.scenario == MockDataScenario.QUALITY_ISSUES:
            classified_pct = random.uniform(0.30, 0.50)  # Low classification
        elif self.scenario == MockDataScenario.PATHOGEN_DETECTED:
            classified_pct = random.uniform(0.70, 0.85)  # Good classification
        elif self.scenario == MockDataScenario.MIXED_QUALITY:
            classified_pct = random.uniform(0.50, 0.75)  # Variable
        else:
            classified_pct = random.uniform(0.65, 0.85)  # Normal

        classified_reads = int(total_reads * classified_pct)
        unclassified_reads = total_reads - classified_reads

        rows = []

        # Unclassified reads (always first line)
        rows.append({
            "%": round((unclassified_reads / total_reads) * 100, 2),
            "cumul_reads": unclassified_reads,
            "reads": unclassified_reads,
            "rank": "U",
            "taxid": 0,
            "name": "unclassified"
        })

        # Root (classified)
        rows.append({
            "%": round(classified_pct * 100, 2),
            "cumul_reads": classified_reads,
            "reads": 0,  # No reads directly assigned to root
            "rank": "R",
            "taxid": 1,
            "name": "root"
        })

        # Distribute classified reads among organisms
        remaining_reads = classified_reads
        organisms_to_generate = self._select_organisms_for_scenario()

        # Collect species-level rows and track reads per ancestor taxid
        species_rows = []
        ancestor_reads = {}  # taxid -> cumulative reads

        for org_info in organisms_to_generate:
            # Calculate reads for this organism
            if self.scenario == MockDataScenario.HIGH_DIVERSITY:
                org_reads = int(remaining_reads * random.uniform(0.05, 0.15))
            else:
                base_abundance = org_info.get("typical_abundance", 0.10)
                noise = random.uniform(0.8, 1.2)
                org_reads = int(classified_reads * base_abundance * noise)

            org_reads = min(org_reads, remaining_reads)
            remaining_reads -= org_reads

            if org_reads > 0:
                species_rows.append((org_info, org_reads))
                # Accumulate reads for each ancestor
                for anc in org_info.get("lineage", []):
                    ancestor_reads[anc["taxid"]] = ancestor_reads.get(anc["taxid"], 0) + org_reads
                # Genus gets same reads as species (species directly assigned)
                genus_entries = [a for a in org_info.get("lineage", []) if a["rank"] == "G"]
                for g in genus_entries:
                    ancestor_reads[g["taxid"]] = ancestor_reads.get(g["taxid"], 0)

        # Build hierarchical rows: domain down to species
        # Collect unique ancestors, ordered by rank
        rank_order = {"D": 0, "P": 1, "C": 2, "O": 3, "F": 4, "G": 5}
        seen_ancestors = {}
        for org_info, _ in species_rows:
            for anc in org_info.get("lineage", []):
                if anc["taxid"] not in seen_ancestors:
                    seen_ancestors[anc["taxid"]] = anc

        sorted_ancestors = sorted(seen_ancestors.values(), key=lambda a: rank_order.get(a["rank"], 99))

        for anc in sorted_ancestors:
            cumul = ancestor_reads.get(anc["taxid"], 0)
            rows.append({
                "%": round((cumul / total_reads) * 100, 4),
                "cumul_reads": cumul,
                "reads": 0,  # No reads directly assigned to intermediate ranks
                "rank": anc["rank"],
                "taxid": anc["taxid"],
                "name": anc["name"],
            })

        for org_info, org_reads in species_rows:
            rows.append({
                "%": round((org_reads / total_reads) * 100, 4),
                "cumul_reads": org_reads,
                "reads": org_reads,
                "rank": org_info["rank"],
                "taxid": org_info["taxid"],
                "name": org_info["name"],
            })

        # Write to file (Kraken2 format)
        with open(output_file, 'w') as f:
            for row in rows:
                f.write(f"{row['%']:.2f}\t{row['cumul_reads']}\t{row['reads']}\t"
                       f"{row['rank']}\t{row['taxid']}\t{row['name']}\n")

        return output_file

    def _select_organisms_for_scenario(self) -> List[Dict]:
        """Select organisms based on testing scenario."""
        if self.scenario == MockDataScenario.PATHOGEN_DETECTED:
            # Include rare pathogens
            return [org for org in self.COMMON_ORGANISMS if org["typical_abundance"] <= 0.002] + \
                   random.sample([org for org in self.COMMON_ORGANISMS if org["typical_abundance"] > 0.05], 4)

        elif self.scenario == MockDataScenario.HIGH_DIVERSITY:
            # Include all organisms
            return self.COMMON_ORGANISMS

        elif self.scenario == MockDataScenario.NORMAL_RUN:
            # Typical community
            return random.sample([org for org in self.COMMON_ORGANISMS if org["typical_abundance"] > 0.05], 6)

        else:
            # Mixed/default
            return random.sample(self.COMMON_ORGANISMS, 5)

    def _generate_qc_stats(self, sample_name: str) -> str:
        """Generate QC statistics (FASTP-style)."""
        qc_dir = os.path.join(self.base_dir, "qc")
        output_file = os.path.join(qc_dir, f"{sample_name}_qc.txt")

        # Generate stats based on scenario
        if self.scenario == MockDataScenario.QUALITY_ISSUES:
            pass_rate = random.uniform(0.45, 0.65)  # Low
            mean_quality = random.uniform(25, 35)
        elif self.scenario == MockDataScenario.NORMAL_RUN:
            pass_rate = random.uniform(0.75, 0.90)  # Good
            mean_quality = random.uniform(35, 42)
        else:
            pass_rate = random.uniform(0.60, 0.80)  # Mixed
            mean_quality = random.uniform(30, 40)

        total_reads = random.randint(80000, 120000)
        passed_reads = int(total_reads * pass_rate)
        failed_reads = total_reads - passed_reads

        # Breakdown of failure reasons
        low_quality = int(failed_reads * random.uniform(0.5, 0.7))
        too_short = int(failed_reads * random.uniform(0.2, 0.3))
        low_complexity = failed_reads - low_quality - too_short

        stats = f"""Sample: {sample_name}
Total reads: {total_reads:,}
Passed reads: {passed_reads:,} ({pass_rate*100:.1f}%)
Failed reads: {failed_reads:,} ({(1-pass_rate)*100:.1f}%)

Failure reasons:
- Low quality: {low_quality:,} ({(low_quality/failed_reads)*100:.1f}%)
- Too short: {too_short:,} ({(too_short/failed_reads)*100:.1f}%)
- Low complexity: {low_complexity:,} ({(low_complexity/failed_reads)*100:.1f}%)

Mean quality score: {mean_quality:.1f}
"""

        with open(output_file, 'w') as f:
            f.write(stats)

        return output_file

    def _generate_fastp_json(self, sample_name: str) -> str:
        """
        Generate FASTP JSON output for comprehensive QC data.

        Matches actual FASTP output format used by nanometanf pipeline.
        """
        import json

        fastp_dir = os.path.join(self.base_dir, "fastp")
        output_file = os.path.join(fastp_dir, f"{sample_name}.fastp.json")

        # Generate stats based on scenario
        if self.scenario == MockDataScenario.QUALITY_ISSUES:
            pass_rate = random.uniform(0.45, 0.65)  # Low
            q20_before = random.uniform(0.70, 0.80)
            q30_before = random.uniform(0.60, 0.70)
            q20_after = random.uniform(0.75, 0.85)
            q30_after = random.uniform(0.65, 0.75)
        elif self.scenario == MockDataScenario.NORMAL_RUN:
            pass_rate = random.uniform(0.75, 0.90)  # Good
            q20_before = random.uniform(0.90, 0.95)
            q30_before = random.uniform(0.85, 0.90)
            q20_after = random.uniform(0.95, 0.98)
            q30_after = random.uniform(0.90, 0.95)
        else:
            pass_rate = random.uniform(0.60, 0.80)  # Mixed
            q20_before = random.uniform(0.80, 0.90)
            q30_before = random.uniform(0.70, 0.80)
            q20_after = random.uniform(0.85, 0.92)
            q30_after = random.uniform(0.75, 0.85)

        total_reads = random.randint(80000, 120000)
        passed_reads = int(total_reads * pass_rate)
        failed_reads = total_reads - passed_reads

        # Breakdown of failure reasons
        low_quality = int(failed_reads * random.uniform(0.5, 0.7))
        too_short = int(failed_reads * random.uniform(0.2, 0.3))
        low_complexity = failed_reads - low_quality - too_short

        # Average read length
        avg_length = random.randint(300, 1500)

        fastp_data = {
            "summary": {
                "before_filtering": {
                    "total_reads": total_reads,
                    "total_bases": int(total_reads * avg_length * random.uniform(0.9, 1.1)),
                    "q20_rate": round(q20_before, 4),
                    "q30_rate": round(q30_before, 4),
                    "gc_content": round(random.uniform(0.40, 0.55), 4),
                    "read_length_mean": avg_length
                },
                "after_filtering": {
                    "total_reads": passed_reads,
                    "total_bases": int(passed_reads * avg_length * random.uniform(0.95, 1.05)),
                    "q20_rate": round(q20_after, 4),
                    "q30_rate": round(q30_after, 4),
                    "gc_content": round(random.uniform(0.40, 0.55), 4),
                    "read_length_mean": avg_length + random.randint(-10, 10)
                }
            },
            "filtering_result": {
                "passed_filter_reads": passed_reads,
                "low_quality_reads": low_quality,
                "too_short_reads": too_short,
                "low_complexity_reads": low_complexity,
                "too_many_N_reads": 0
            },
            "adapter_cutting": {
                "adapter_trimmed_reads": int(total_reads * random.uniform(0.05, 0.15)),
                "adapter_trimmed_bases": int(total_reads * avg_length * random.uniform(0.01, 0.03))
            }
        }

        with open(output_file, 'w') as f:
            json.dump(fastp_data, f, indent=2)

        return output_file

    def _generate_multiqc_general_stats(self, num_samples: int) -> str:
        """Generate MultiQC general stats file."""
        multiqc_dir = os.path.join(self.base_dir, "multiqc", "multiqc_data")
        output_file = os.path.join(multiqc_dir, "multiqc_general_stats.txt")

        # Create header
        lines = ["Sample\tFASTQ Total Reads\tKraken Classified %\n"]

        # Generate stats for each sample
        for i in range(1, num_samples + 1):
            sample_name = f"barcode{i:02d}"

            # Get classification rate based on scenario
            if self.scenario == MockDataScenario.QUALITY_ISSUES:
                classified_pct = random.uniform(30, 50)
            elif self.scenario == MockDataScenario.PATHOGEN_DETECTED:
                classified_pct = random.uniform(70, 85)
            else:
                classified_pct = random.uniform(65, 85)

            total_reads = random.randint(80000, 120000)

            lines.append(f"{sample_name}\t{total_reads}\t{classified_pct:.1f}\n")

        with open(output_file, 'w') as f:
            f.writelines(lines)

        return output_file

    def _generate_summary_stats(self, num_samples: int) -> str:
        """Generate overall summary statistics."""
        summary_file = os.path.join(self.base_dir, "summary.txt")

        stats = f"""Nanometa Live Mock Data - {self.scenario.upper()} Scenario
Generated: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

Samples: {num_samples}
Status: {'Completed' if self.scenario != MockDataScenario.QUALITY_ISSUES else 'Completed with warnings'}

Scenario characteristics:
"""

        if self.scenario == MockDataScenario.NORMAL_RUN:
            stats += "- Normal operation, good quality\n- Expected results\n"
        elif self.scenario == MockDataScenario.QUALITY_ISSUES:
            stats += "- Low quality data detected\n- Below optimal pass rates\n"
        elif self.scenario == MockDataScenario.PATHOGEN_DETECTED:
            stats += "- Target pathogen(s) detected\n- Requires immediate attention\n"
        elif self.scenario == MockDataScenario.HIGH_DIVERSITY:
            stats += "- High organism diversity\n- Complex community structure\n"

        with open(summary_file, 'w') as f:
            f.write(stats)

        return summary_file


def generate_test_dataset(
    output_dir: str,
    scenario: str = MockDataScenario.NORMAL_RUN,
    num_samples: int = 3
) -> Dict[str, str]:
    """
    Convenience function to generate a complete test dataset.

    Args:
        output_dir: Where to write files
        scenario: Testing scenario
        num_samples: Number of barcoded samples

    Returns:
        Dictionary of created file paths

    Examples:
        >>> files = generate_test_dataset(
        ...     "/tmp/nanometa_test",
        ...     scenario=MockDataScenario.PATHOGEN_DETECTED,
        ...     num_samples=5
        ... )
        >>> print(files['summary'])
        '/tmp/nanometa_test/summary.txt'
    """
    generator = MockDataGenerator(output_dir, scenario)
    return generator.generate_complete_dataset(num_samples)


# CLI for manual testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python mock_data_generator.py <output_dir> [scenario] [num_samples]")
        print(f"Scenarios: {', '.join([s for s in dir(MockDataScenario) if not s.startswith('_')])}")
        sys.exit(1)

    output_dir = sys.argv[1]
    scenario = sys.argv[2] if len(sys.argv) > 2 else MockDataScenario.NORMAL_RUN
    num_samples = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    print(f"Generating mock data: {scenario} scenario with {num_samples} samples")
    print(f"Output directory: {output_dir}")

    files = generate_test_dataset(output_dir, scenario, num_samples)

    print("\nGenerated files:")
    for key, path in files.items():
        print(f"  {key}: {path}")

    print("\nDone! Use this directory as --main_dir in Nanometa Live configuration.")
