#!/usr/bin/env python3
"""
Generate a comprehensive 6-barcode test dataset for Nanometa Live.

Creates 6 barcodes with progressively increasing diversity and read counts:
- barcode01: 5 species, 10K reads (low diversity, low reads)
- barcode02: 10 species, 50K reads (low-medium diversity)
- barcode03: 25 species, 100K reads (medium diversity)
- barcode04: 50 species, 200K reads (medium-high diversity)
- barcode05: 75 species, 500K reads (high diversity)
- barcode06: 100 species, 1M reads (very high diversity, high reads)
"""

import os
import random
import json
from pathlib import Path
from typing import List, Dict

# Comprehensive organism database (100+ organisms)
EXTENDED_ORGANISM_DB = [
    # Bacteria - Proteobacteria
    {"taxid": 562, "name": "Escherichia coli", "genus": "Escherichia", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 564, "name": "Escherichia fergusonii", "genus": "Escherichia", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 573, "name": "Klebsiella pneumoniae", "genus": "Klebsiella", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 571, "name": "Klebsiella oxytoca", "genus": "Klebsiella", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 28901, "name": "Salmonella enterica", "genus": "Salmonella", "family": "Enterobacteriaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 287, "name": "Pseudomonas aeruginosa", "genus": "Pseudomonas", "family": "Pseudomonadaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 632, "name": "Yersinia pestis", "genus": "Yersinia", "family": "Yersiniaceae", "order": "Enterobacterales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 727, "name": "Haemophilus influenzae", "genus": "Haemophilus", "family": "Pasteurellaceae", "order": "Pasteurellales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 470, "name": "Acinetobacter baumannii", "genus": "Acinetobacter", "family": "Moraxellaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},

    # Bacteria - Firmicutes
    {"taxid": 1280, "name": "Staphylococcus aureus", "genus": "Staphylococcus", "family": "Staphylococcaceae", "order": "Staphylococcales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1282, "name": "Staphylococcus epidermidis", "genus": "Staphylococcus", "family": "Staphylococcaceae", "order": "Staphylococcales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 29385, "name": "Staphylococcus saprophyticus", "genus": "Staphylococcus", "family": "Staphylococcaceae", "order": "Staphylococcales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1351, "name": "Enterococcus faecalis", "genus": "Enterococcus", "family": "Enterococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1423, "name": "Bacillus subtilis", "genus": "Bacillus", "family": "Bacillaceae", "order": "Bacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1392, "name": "Bacillus anthracis", "genus": "Bacillus", "family": "Bacillaceae", "order": "Bacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1491, "name": "Clostridium botulinum", "genus": "Clostridium", "family": "Clostridiaceae", "order": "Clostridiales", "class": "Clostridia", "phylum": "Firmicutes"},
    {"taxid": 1639, "name": "Listeria monocytogenes", "genus": "Listeria", "family": "Listeriaceae", "order": "Bacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1613, "name": "Lactobacillus fermentum", "genus": "Lactobacillus", "family": "Lactobacillaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1352, "name": "Enterococcus faecium", "genus": "Enterococcus", "family": "Enterococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1313, "name": "Streptococcus pneumoniae", "genus": "Streptococcus", "family": "Streptococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},
    {"taxid": 1314, "name": "Streptococcus pyogenes", "genus": "Streptococcus", "family": "Streptococcaceae", "order": "Lactobacillales", "class": "Bacilli", "phylum": "Firmicutes"},

    # Bacteria - Bacteroidetes
    {"taxid": 816, "name": "Bacteroides fragilis", "genus": "Bacteroides", "family": "Bacteroidaceae", "order": "Bacteroidales", "class": "Bacteroidia", "phylum": "Bacteroidetes"},
    {"taxid": 817, "name": "Bacteroides thetaiotaomicron", "genus": "Bacteroides", "family": "Bacteroidaceae", "order": "Bacteroidales", "class": "Bacteroidia", "phylum": "Bacteroidetes"},
    {"taxid": 818, "name": "Bacteroides vulgatus", "genus": "Bacteroides", "family": "Bacteroidaceae", "order": "Bacteroidales", "class": "Bacteroidia", "phylum": "Bacteroidetes"},

    # Bacteria - Actinobacteria
    {"taxid": 1773, "name": "Mycobacterium tuberculosis", "genus": "Mycobacterium", "family": "Mycobacteriaceae", "order": "Mycobacteriales", "class": "Actinomycetia", "phylum": "Actinobacteria"},
    {"taxid": 36809, "name": "Mycobacterium abscessus", "genus": "Mycobacterium", "family": "Mycobacteriaceae", "order": "Mycobacteriales", "class": "Actinomycetia", "phylum": "Actinobacteria"},
    {"taxid": 1765, "name": "Corynebacterium diphtheriae", "genus": "Corynebacterium", "family": "Corynebacteriaceae", "order": "Corynebacteriales", "class": "Actinomycetia", "phylum": "Actinobacteria"},
    {"taxid": 1764, "name": "Corynebacterium jeikeium", "genus": "Corynebacterium", "family": "Corynebacteriaceae", "order": "Corynebacteriales", "class": "Actinomycetia", "phylum": "Actinobacteria"},

    # Additional organisms to reach 100+
    {"taxid": 285, "name": "Pseudomonas fluorescens", "genus": "Pseudomonas", "family": "Pseudomonadaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 294, "name": "Pseudomonas putida", "genus": "Pseudomonas", "family": "Pseudomonadaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 300, "name": "Pseudomonas stutzeri", "genus": "Pseudomonas", "family": "Pseudomonadaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    {"taxid": 286, "name": "Pseudomonas syringae", "genus": "Pseudomonas", "family": "Pseudomonadaceae", "order": "Pseudomonadales", "class": "Gammaproteobacteria", "phylum": "Proteobacteria"},
    # Add 70+ more diverse organisms
] + [
    # Generate synthetic organisms to reach 100+ total
    {"taxid": 10000 + i, "name": f"Synthetic_species_{i:03d}", "genus": f"Synthetic_genus_{i//10:02d}",
     "family": f"Synthetic_family_{i//20:02d}", "order": f"Synthetic_order_{i//30:02d}",
     "class": ["Gammaproteobacteria", "Bacilli", "Bacteroidia", "Actinomycetia"][i % 4],
     "phylum": ["Proteobacteria", "Firmicutes", "Bacteroidetes", "Actinobacteria"][i % 4]}
    for i in range(70)
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


def main():
    """Generate 6-barcode test dataset."""
    base_path = "/tmp/nanometa_6_barcode_test"
    kraken_dir = Path(base_path) / "kraken2"
    kraken_dir.mkdir(parents=True, exist_ok=True)

    print("Generating 6-barcode test dataset...")
    print("=" * 70)

    # Barcode configurations: (species_count, total_reads, unclassified_pct, name)
    barcodes = [
        (5, 10_000, 0.10, "barcode01", "Low diversity, low reads"),
        (10, 50_000, 0.12, "barcode02", "Low-medium diversity"),
        (25, 100_000, 0.15, "barcode03", "Medium diversity"),
        (50, 200_000, 0.18, "barcode04", "Medium-high diversity"),
        (75, 500_000, 0.20, "barcode05", "High diversity"),
        (100, 1_000_000, 0.22, "barcode06", "Very high diversity, high reads"),
    ]

    dataset_summary = {
        "dataset_name": "6-Barcode Comprehensive Test Dataset",
        "total_barcodes": 6,
        "barcodes": []
    }

    for species_count, total_reads, unclassified_pct, barcode_name, description in barcodes:
        # Select random species (ensure unique across all barcodes for variety)
        selected_species = random.sample(EXTENDED_ORGANISM_DB, min(species_count, len(EXTENDED_ORGANISM_DB)))

        # Generate Kraken report
        lines = generate_kraken_report(selected_species, total_reads, unclassified_pct)

        # Write to file
        output_file = kraken_dir / f"{barcode_name}.kreport2.txt"
        with open(output_file, 'w') as f:
            f.write('\n'.join(lines))

        barcode_info = {
            "barcode": barcode_name,
            "description": description,
            "species_count": species_count,
            "total_reads": total_reads,
            "unclassified_pct": unclassified_pct,
            "species": [s["name"] for s in selected_species[:10]]  # First 10 species
        }
        dataset_summary["barcodes"].append(barcode_info)

        print(f"✓ {barcode_name}: {species_count} species, {total_reads:,} reads - {description}")

    # Write summary
    with open(Path(base_path) / "dataset_info.json", 'w') as f:
        json.dump(dataset_summary, f, indent=2)

    print("=" * 70)
    print(f"\n✓ 6-barcode dataset generated in: {base_path}")
    print(f"\nTo use this dataset:")
    print(f"  python -m nanometa_live.app --main_dir {base_path}")
    print(f"\nBarcode overview:")
    for barcode_info in dataset_summary["barcodes"]:
        print(f"  {barcode_info['barcode']}: {barcode_info['species_count']} species, {barcode_info['total_reads']:,} reads")


if __name__ == "__main__":
    main()
