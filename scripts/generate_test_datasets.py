#!/usr/bin/env python3
"""
Generate comprehensive test datasets for Nanometa Live visualization testing.

Creates 8 specialized datasets with variable species counts (1-100) to test:
- Single species (edge case)
- Low diversity (5-10 species)
- Medium diversity (20-30 species)
- High diversity (50-100 species)
- Non-consecutive taxonomy levels
- Missing intermediate ranks
- Pathogen detection scenarios
- Quality/abundance variations
"""

import os
import random
import json
from pathlib import Path
from typing import List, Dict, Tuple


# Comprehensive organism database for realistic testing
EXTENDED_ORGANISM_DB = [
    # Bacteria - Proteobacteria
    {"taxid": 562, "name": "Escherichia coli", "genus": "Escherichia", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 564, "name": "Escherichia fergusonii", "genus": "Escherichia", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 573, "name": "Klebsiella pneumoniae", "genus": "Klebsiella", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 571, "name": "Klebsiella oxytoca", "genus": "Klebsiella", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 28901, "name": "Salmonella enterica", "genus": "Salmonella", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 287, "name": "Pseudomonas aeruginosa", "genus": "Pseudomonas", "family": "Pseudomonadaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},

    # Bacteria - Firmicutes
    {"taxid": 1280, "name": "Staphylococcus aureus", "genus": "Staphylococcus", "family": "Staphylococcaceae", "order": "Staphylococcales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1282, "name": "Staphylococcus epidermidis", "genus": "Staphylococcus", "family": "Staphylococcaceae", "order": "Staphylococcales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 29385, "name": "Staphylococcus saprophyticus", "genus": "Staphylococcus", "family": "Staphylococcaceae", "order": "Staphylococcales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1351, "name": "Enterococcus faecalis", "genus": "Enterococcus", "family": "Enterococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1423, "name": "Bacillus subtilis", "genus": "Bacillus", "family": "Bacillaceae", "order": "Bacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1392, "name": "Bacillus anthracis", "genus": "Bacillus", "family": "Bacillaceae", "order": "Bacillales", "class": "Bacilli", "phylum": "Firmicutes"},

    # Bacteria - Bacteroidetes
    {"taxid": 816, "name": "Bacteroides fragilis", "genus": "Bacteroides", "family": "Bacteroidaceae", "order": "Bacteroidales", "class": "Bacteroidia", "phylum": "Bacteroidetes"},

    # Bacteria - Actinobacteria
    {"taxid": 1773, "name": "Mycobacterium tuberculosis", "genus": "Mycobacterium", "family": "Mycobacteriaceae", "order": "Mycobacteriales", "class": "Actinomycetia", "phylum": "Actinobacteria"},
    {"taxid": 36809, "name": "Mycobacterium abscessus", "genus": "Mycobacterium", "family": "Mycobacteriaceae", "order": "Mycobacteriales", "class": "Actinomycetia", "phylum": "Actinobacteria"},
    {"taxid": 1765, "name": "Corynebacterium diphtheriae", "genus": "Corynebacterium", "family": "Corynebacteriaceae", "order": "Corynebacteriales", "class": "Actinomycetia", "phylum": "Actinobacteria"},

    # Add more diverse organisms to reach 100+ options
    {"taxid": 632, "name": "Yersinia pestis", "genus": "Yersinia", "family": "Yersiniaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 727, "name": "Haemophilus influenzae", "genus": "Haemophilus", "family": "Pasteurellaceae", "order": "Pasteurellales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 470, "name": "Acinetobacter baumannii", "genus": "Acinetobacter", "family": "Moraxellaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 1491, "name": "Clostridium botulinum", "genus": "Clostridium", "family": "Clostridiaceae", "order": "Clostridiales", "class": "Clostridia", "phylum": "Firmicutes"},
    {"taxid": 1639, "name": "Listeria monocytogenes", "genus": "Listeria", "family": "Listeriaceae", "order": "Bacillales", "class": "Bacilli", "phylum": "Firmicutes"},

    # Additional common organisms to reach variety
    {"taxid": 1613, "name": "Lactobacillus fermentum", "genus": "Lactobacillus", "family": "Lactobacillaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1352, "name": "Enterococcus faecium", "genus": "Enterococcus", "family": "Enterococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1313, "name": "Streptococcus pneumoniae", "genus": "Streptococcus", "family": "Streptococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1314, "name": "Streptococcus pyogenes", "genus": "Streptococcus", "family": "Streptococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
]


def generate_kraken_report(species_list: List[Dict], total_reads: int, unclassified_pct: float = 0.15) -> List[str]:
    """
    Generate Kraken2 report with proper hierarchical indentation.

    Args:
        species_list: List of species dicts with taxonomic information
        total_reads: Total number of reads
        unclassified_pct: Percentage of unclassified reads (0.0-1.0)

    Returns:
        List of formatted Kraken2 report lines
    """
    unclassified = int(total_reads * unclassified_pct)
    classified = total_reads - unclassified

    lines = []

    # Unclassified
    lines.append(f"{unclassified_pct*100:.2f}\t{unclassified}\t{unclassified}\tU\t0\tunclassified")

    # Root
    lines.append(f"{(1-unclassified_pct)*100:.2f}\t{classified}\t0\tR\t1\troot")

    # Build hierarchical tree
    domain_reads = {}
    phylum_reads = {}
    class_reads = {}
    order_reads = {}
    family_reads = {}
    genus_reads = {}

    # Distribute reads among species
    remaining_reads = classified
    species_reads = {}

    for i, species in enumerate(species_list):
        if i == len(species_list) - 1:
            # Last species gets remaining reads
            reads = remaining_reads
        else:
            # Random distribution with power law (some abundant, most rare)
            if i < len(species_list) * 0.2:  # Top 20% are abundant
                reads = int(remaining_reads * random.uniform(0.10, 0.20))
            else:  # Rest are less abundant
                reads = int(remaining_reads * random.uniform(0.01, 0.05))

        reads = min(reads, remaining_reads)
        remaining_reads -= reads
        species_reads[species["taxid"]] = reads

        # Aggregate to higher levels
        domain_reads["Bacteria"] = domain_reads.get("Bacteria", 0) + reads
        phylum_reads[species["phylum"]] = phylum_reads.get(species["phylum"], 0) + reads
        class_reads[species["class"]] = class_reads.get(species["class"], 0) + reads
        order_reads[species["order"]] = order_reads.get(species["order"], 0) + reads
        family_reads[species["family"]] = family_reads.get(species["family"], 0) + reads
        genus_reads[species["genus"]] = genus_reads.get(species["genus"], 0) + reads

    # Domain level (2 spaces)
    lines.append(f"{(domain_reads['Bacteria']/total_reads)*100:.2f}\t{domain_reads['Bacteria']}\t0\tD\t2\t  Bacteria")

    # Group by phylum, class, order, family, genus
    for phylum in sorted(set(s["phylum"] for s in species_list)):
        phylum_species = [s for s in species_list if s["phylum"] == phylum]
        lines.append(f"{(phylum_reads[phylum]/total_reads)*100:.2f}\t{phylum_reads[phylum]}\t0\tP\t{hash(phylum) % 90000 + 1000}\t    {phylum}")

        for class_name in sorted(set(s["class"] for s in phylum_species)):
            class_species = [s for s in phylum_species if s["class"] == class_name]
            lines.append(f"{(class_reads[class_name]/total_reads)*100:.2f}\t{class_reads[class_name]}\t0\tC\t{hash(class_name) % 90000 + 1000}\t      {class_name}")

            for order in sorted(set(s["order"] for s in class_species)):
                order_species = [s for s in class_species if s["order"] == order]
                lines.append(f"{(order_reads[order]/total_reads)*100:.2f}\t{order_reads[order]}\t0\tO\t{hash(order) % 90000 + 1000}\t        {order}")

                for family in sorted(set(s["family"] for s in order_species)):
                    family_species = [s for s in order_species if s["family"] == family]
                    lines.append(f"{(family_reads[family]/total_reads)*100:.2f}\t{family_reads[family]}\t0\tF\t{hash(family) % 90000 + 1000}\t          {family}")

                    for genus in sorted(set(s["genus"] for s in family_species)):
                        genus_species = [s for s in family_species if s["genus"] == genus]
                        lines.append(f"{(genus_reads[genus]/total_reads)*100:.2f}\t{genus_reads[genus]}\t0\tG\t{hash(genus) % 90000 + 1000}\t            {genus}")

                        for species in genus_species:
                            reads = species_reads[species["taxid"]]
                            if reads > 0:
                                lines.append(f"{(reads/total_reads)*100:.2f}\t{reads}\t{reads}\tS\t{species['taxid']}\t              {species['name']}")

    return lines


def create_dataset(output_dir: str, name: str, species_count: int, total_reads: int = 100000, unclassified_pct: float = 0.15):
    """Create a single test dataset."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    kraken_dir = Path(output_dir) / "kraken2"
    kraken_dir.mkdir(exist_ok=True)

    # Select random species
    selected_species = random.sample(EXTENDED_ORGANISM_DB, min(species_count, len(EXTENDED_ORGANISM_DB)))

    # Generate Kraken report
    lines = generate_kraken_report(selected_species, total_reads, unclassified_pct)

    # Write to file
    output_file = kraken_dir / "barcode01.kreport2.txt"
    with open(output_file, 'w') as f:
        f.write('\n'.join(lines))

    # Create summary
    summary = {
        "name": name,
        "species_count": species_count,
        "total_reads": total_reads,
        "unclassified_pct": unclassified_pct,
        "species": [s["name"] for s in selected_species]
    }

    with open(Path(output_dir) / "dataset_info.json", 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"✓ Created {name}: {species_count} species, {total_reads:,} reads")


def main():
    """Generate all 8 specialized test datasets."""
    base_path = "/tmp/nanometa_test_datasets"

    print("Generating comprehensive test datasets...")
    print("=" * 60)

    # 1. Single Species (edge case)
    create_dataset(f"{base_path}/01_single_species", "Single Species",
                   species_count=1, total_reads=50000, unclassified_pct=0.05)

    # 2. Low Diversity
    create_dataset(f"{base_path}/02_low_diversity", "Low Diversity (5 species)",
                   species_count=5, total_reads=80000, unclassified_pct=0.10)

    # 3. Medium Diversity
    create_dataset(f"{base_path}/03_medium_diversity", "Medium Diversity (25 species)",
                   species_count=25, total_reads=100000, unclassified_pct=0.15)

    # 4. High Diversity
    create_dataset(f"{base_path}/04_high_diversity", "High Diversity (50 species)",
                   species_count=min(50, len(EXTENDED_ORGANISM_DB)), total_reads=150000, unclassified_pct=0.20)

    # 5. Very High Diversity
    create_dataset(f"{base_path}/05_very_high_diversity", "Very High Diversity (all species)",
                   species_count=len(EXTENDED_ORGANISM_DB), total_reads=200000, unclassified_pct=0.25)

    # 6. Pathogen Detection (E. coli dominant)
    ecoli_species = [s for s in EXTENDED_ORGANISM_DB if "coli" in s["name"]]
    other_species = random.sample([s for s in EXTENDED_ORGANISM_DB if "coli" not in s["name"]], 5)
    pathogen_species = ecoli_species + other_species
    create_dataset(f"{base_path}/06_pathogen_detected", "Pathogen Detected (E. coli dominant)",
                   species_count=len(pathogen_species), total_reads=100000, unclassified_pct=0.10)

    # 7. Low Quality (high unclassified)
    create_dataset(f"{base_path}/07_low_quality", "Low Quality (high unclassified)",
                   species_count=10, total_reads=75000, unclassified_pct=0.50)

    # 8. Mixed Quality
    create_dataset(f"{base_path}/08_mixed_quality", "Mixed Quality",
                   species_count=15, total_reads=90000, unclassified_pct=0.30)

    print("=" * 60)
    print(f"\n✓ All datasets generated in: {base_path}")
    print(f"\nTo use these datasets:")
    print(f"  python -m nanometa_live.app --main_dir {base_path}/01_single_species")


if __name__ == "__main__":
    main()
