# Manual Frontend Testing Guide

**Purpose**: Visual testing of modernized Nanometa Live UI with realistic test data

**Generated**: 2025-10-07
**Test Data Location**: `/tmp/nanometa_test_*`

---

## Quick Start Commands

### 1. Normal Run Scenario (Typical Operation)
```bash
# Launch app with normal quality data (5 samples)
python -m nanometa_live.app.app --main_dir /tmp/nanometa_test_normal --debug

# Expected characteristics:
# - Pass rate: 75-90%
# - Classification rate: 65-85%
# - 6-8 organisms
# - Quality score: >75 (Good/Excellent)
# - Status: Green/Amber indicators
```

**What to Test**:
- ✅ Dashboard shows green quality indicators
- ✅ OrganismCard components display with abundance bars
- ✅ QualityScoreIndicator shows "GOOD" or "EXCELLENT"
- ✅ Classification visualizations show typical diversity

---

### 2. Pathogen Detection Scenario (Alert Testing)
```bash
# Launch app with pathogen detection data (5 samples)
python -m nanometa_live.app.app --main_dir /tmp/nanometa_test_pathogen --debug

# Expected characteristics:
# - Contains rare pathogens:
#   • Bacillus anthracis (Anthrax) - taxid 1392
#   • Yersinia pestis (Plague) - taxid 632
#   • Clostridium botulinum (Botulinum) - taxid 1491
# - Good classification (70-85%)
# - CRITICAL alerts generated
```

**What to Test**:
- ✅ Alert banner displays for detected pathogens
- ✅ Pathogen organisms highlighted in Main Results tab
- ✅ OrganismCard shows HIGH confidence for pathogens
- ✅ Export functionality works (CSV, PDF)

---

### 3. Quality Issues Scenario (Troubleshooting Testing)
```bash
# Launch app with poor quality data (3 samples)
python -m nanometa_live.app.app --main_dir /tmp/nanometa_test_quality --debug

# Expected characteristics:
# - Pass rate: 45-65% (LOW)
# - Classification rate: 30-50% (LOW)
# - High unclassified percentage (>15%)
# - Quality score: <60 (Poor)
# - Status: Red/Amber indicators
```

**What to Test**:
- ✅ Dashboard shows red quality indicators
- ✅ QualityScoreIndicator shows "POOR" or "FAIR"
- ✅ FilteringBreakdownVisual shows high removal rates
- ✅ Help sections provide troubleshooting guidance
- ✅ Per-sample table color-coded (red rows for poor quality)

---

## Testing Checklist by Tab

### Dashboard Tab
- [ ] Traffic light status indicator visible and correct
- [ ] 4 metrics cards display correct values
- [ ] Overall statistics aggregate all samples
- [ ] Alerts display when expected (pathogens, low quality)
- [ ] Sample selector works (if multiple samples)

### Main Results Tab
- [ ] **OrganismSummaryCard** displays at top:
  - Total organisms count
  - Total DNA sequences
  - Classification rate
  - Most abundant organism
- [ ] **OrganismCard** components render:
  - Organism name prominent
  - Abundance bar visual (colored progress bar)
  - DNA sequence count
  - Confidence badge (HIGH/MEDIUM/LOW)
  - View Details and Export buttons
- [ ] Progressive disclosure works:
  - Advanced filters collapsible (collapsed by default)
  - Detailed data table collapsible
- [ ] Help section visible and informative
- [ ] Export buttons functional

### QC Tab
- [ ] **QualityScoreIndicator** displays:
  - Large circular gauge with score (0-100)
  - Plain language rating (EXCELLENT/GOOD/FAIR/POOR)
  - Color-coded (green/amber/red)
  - Interpretation text
- [ ] **FilteringBreakdownVisual** displays:
  - Pass/fail split bar
  - Removal reasons breakdown
  - Plain language labels
- [ ] Per-sample table shows:
  - Color-coded pass rates (green ≥75%, amber 60-74%, red <60%)
  - Quality scores and status
- [ ] Detailed plots collapsible
- [ ] Help section provides troubleshooting guidance

### Classification Tab
- [ ] View selector with explanations:
  - Sankey explanation visible when selected
  - Sunburst explanation visible when selected
- [ ] Visualization renders correctly:
  - Sankey shows flow paths
  - Sunburst shows hierarchy
  - Interactive (click to explore)
- [ ] Filter options collapsible (collapsed by default)
- [ ] Plain language filter labels
- [ ] Help section explains both views

---

## Verifying Modernization Features

### Progressive Disclosure
✅ Most important info visible by default
✅ Advanced options collapsed
✅ Technical details hidden until requested
✅ Collapsible sections expand/collapse smoothly

### Visual Hierarchy
✅ Large = Important (quality gauge, summary cards)
✅ Top = Priority (summaries before details)
✅ Color = Status (green/amber/red consistent)

### Plain Language
✅ "DNA sequences" not "reads"
✅ "Organisms" not "taxa"
✅ "Quality" not "QC metrics"
✅ Explanatory text with every metric

### Help Sections
✅ Help in every tab
✅ Plain language explanations
✅ Step-by-step guidance
✅ Tips for effective use

### Export Options
✅ Prominent export buttons
✅ Clear button labels
✅ Multiple formats available

---

## Known Scenarios and Expected Behavior

### Normal Run (`/tmp/nanometa_test_normal`)
| Metric | Expected Range | UI Behavior |
|--------|---------------|-------------|
| Pass Rate | 75-90% | Green indicators |
| Classification Rate | 65-85% | Green/Amber |
| Organism Count | 6-8 | Typical diversity |
| Quality Score | >75 | "GOOD" or "EXCELLENT" |

### Pathogen Detected (`/tmp/nanometa_test_pathogen`)
| Metric | Expected Range | UI Behavior |
|--------|---------------|-------------|
| Pass Rate | 70-90% | Green indicators |
| Classification Rate | 70-85% | Green |
| Alert Level | CRITICAL | Red alert banner |
| Pathogen Count | 3 (Anthrax, Plague, Botulinum) | Highlighted organisms |

### Quality Issues (`/tmp/nanometa_test_quality`)
| Metric | Expected Range | UI Behavior |
|--------|---------------|-------------|
| Pass Rate | 45-65% | Red/Amber indicators |
| Classification Rate | 30-50% | Red |
| Unclassified % | >15% | Warning displayed |
| Quality Score | <60 | "POOR" or "FAIR" |

---

## Testing Data Files

Each scenario includes complete datasets:

```
/tmp/nanometa_test_*/
├── kraken2/
│   ├── barcode01.kreport2.txt    # Taxonomic classification
│   ├── barcode02.kreport2.txt
│   └── barcode0N.kreport2.txt
├── fastp/
│   ├── barcode01.fastp.json      # Comprehensive QC data
│   ├── barcode02.fastp.json
│   └── barcode0N.fastp.json
├── qc/
│   ├── barcode01_qc.txt          # Legacy QC format
│   ├── barcode02_qc.txt
│   └── barcode0N_qc.txt
├── multiqc/
│   └── multiqc_data/
│       └── multiqc_general_stats.txt  # Aggregate stats
└── summary.txt                    # Scenario description
```

---

## Regenerating Test Data

If you need fresh test data or different sample counts:

```bash
# Generate new datasets
python -m nanometa_live.core.testing.mock_data_generator /tmp/test_normal normal 10
python -m nanometa_live.core.testing.mock_data_generator /tmp/test_pathogen pathogen 5
python -m nanometa_live.core.testing.mock_data_generator /tmp/test_quality quality_issues 3
python -m nanometa_live.core.testing.mock_data_generator /tmp/test_mixed mixed 8
python -m nanometa_live.core.testing.mock_data_generator /tmp/test_diversity high_diversity 10

# Available scenarios:
# - normal (typical operation)
# - pathogen (rare pathogen detection)
# - quality_issues (low quality data)
# - mixed (variable sample quality)
# - high_diversity (10+ organisms)
# - low_diversity (2-3 organisms)
```

---

## Screenshot Testing Checklist

Take screenshots for documentation:

1. **Dashboard Tab**:
   - [ ] Normal scenario (green indicators)
   - [ ] Quality issues scenario (red indicators)
   - [ ] Pathogen alert banner

2. **Main Results Tab**:
   - [ ] OrganismSummaryCard
   - [ ] OrganismCard grid (top organisms)
   - [ ] Abundance bars visible

3. **QC Tab**:
   - [ ] QualityScoreIndicator (all ratings: EXCELLENT, GOOD, FAIR, POOR)
   - [ ] FilteringBreakdownVisual
   - [ ] Color-coded per-sample table

4. **Classification Tab**:
   - [ ] Sankey diagram
   - [ ] Sunburst chart
   - [ ] Filter options expanded

---

## Troubleshooting

### App won't start
```bash
# Check dependencies
pip install -r requirements.txt

# Verify data directory exists
ls -la /tmp/nanometa_test_normal/

# Check permissions
chmod -R 755 /tmp/nanometa_test_*/
```

### ModuleNotFoundError: No module named 'snakemake'
**Issue**: RESOLVED - Snakemake is no longer a dependency. The app now uses Nextflow via `NextflowManager`.

If you see this error, ensure you have the latest version of the code with the updated `nanometa_live/core/workflow/__init__.py` that doesn't import `SnakemakeManager`.

### Components not displaying
- Check browser console for errors (F12)
- Verify data files are present in expected directories
- Check app logs for parser errors

### Data looks unrealistic
- Regenerate test data with different seed
- Adjust scenario parameters in mock_data_generator.py

---

## Next Steps After Manual Testing

1. **Document Issues**: Note any UI bugs or unexpected behavior
2. **User Feedback**: Share with end users (first responders, lab personnel)
3. **Performance Testing**: Test with larger datasets (50+ samples)
4. **Real Data Testing**: Test with actual nanometanf pipeline output
5. **Mobile Testing**: Test on tablets and phones

---

**Testing infrastructure completed**: 2025-10-07
**Related docs**:
- `TEST_COVERAGE_SUMMARY.md` - Automated test suite documentation
- `TAB_IMPLEMENTATION_COMPLETE.md` - Tab modernization summary
- `TAB_MODERNIZATION_STRATEGY.md` - Design strategy and principles
