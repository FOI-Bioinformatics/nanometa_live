# Nanometa Live v2.0 - Operator Guide

**For**: First Responders, Laboratory Personnel, Non-Bioinformatics Operators
**Purpose**: Rapid analysis and decision-making from nanopore sequencing data
**Training Time**: 10 minutes to basic proficiency

---

## 🎯 What This Tool Does (In Plain Language)

Nanometa Live analyzes DNA from your samples and tells you:
1. **What organisms are present** (bacteria, viruses, etc.)
2. **How good the data quality is** (reliable or needs attention)
3. **If target pathogens are detected** (automatic alerts)
4. **What you should do next** (clear action guidance)

**You don't need to be a bioinformatics expert to use this tool.**

---

## 🚦 The Traffic Light System

Everything in Nanometa Live uses traffic lights - just like a stoplight:

🟢 **GREEN** = Good
- Quality is acceptable
- No issues detected
- Safe to proceed

🟡 **AMBER** = Review Needed
- Quality is fair but could be better
- Attention recommended
- Check details before proceeding

🔴 **RED** = Action Required
- Critical issue detected
- Immediate attention needed
- Follow recommended actions

**You can understand the status at a glance - no reading required.**

---

## 📊 Dashboard Overview (Your Starting Point)

When you open Nanometa Live, you see the **Dashboard** tab (default view). It has four zones, top to bottom.

### Zone 1 — Clinical Verdict Banner (Your Primary Signal)

A single large banner across the top of the page. **The background color of this banner is the answer to "is there a problem?"**:

```
🟢 ALL CLEAR                       0 of 42 monitored pathogens found
   No action required              Sample: barcode01 | ACTIVE  02:14:06
                                   Last updated 14:23:45
```

```
🔴 ACTION REQUIRED                 2 of 42 monitored pathogens found
   Act immediately                 Sample: barcode01 | ACTIVE  02:14:06
                                   Last updated 14:23:45
```

**Verdict states**:

| State | Color | What it means |
|-------|-------|---------------|
| ALL CLEAR | Green | No watched pathogens detected. Run is progressing or complete. |
| ACTION REQUIRED | Red | A critical or high-risk pathogen on your watchlist was detected. Follow your safety protocol. |
| MONITORING | Amber | Only moderate-risk watched species detected. Review. |
| SCREENING IN PROGRESS | Blue | Run is active; first results pending. |
| STANDBY | Grey | No run is active. |

If validation (BLAST / minimap2) has not yet run on a detected pathogen, the ACTION REQUIRED banner appends "— pending confirmatory validation" to the sub-line.

### Zone 2 — Pathogen Found Cards (only when alerts exist)

When a pathogen is detected, one or more cards appear beneath Zone 1:

```
🔴 CRITICAL — Bacillus anthracis (Anthrax)
   4,521 matches | 3.62% of sample | HIGH confidence | BLAST Verified
   DETECTED IN: [barcode03] [barcode11]
   Contact your safety officer immediately.
```

**DETECTED IN:** tells you *which samples* each pathogen was found in. Colored chips list the samples.
- Normal sample chips use the alert severity color
- **Negative control samples** appear as flat gray chips with `(NC)` after the name
- If a pathogen appears in many samples, the first 3 are shown inline and the rest indicated as `+X more`

### Zone 3 — Supporting Metrics (4 cards)
```
┌──────────────────┬──────────────┬──────────────────┬──────────┐
│    10,000        │  Good        │  12 species      │  ACTIVE  │
│ Sequences        │  Q17 Quality │  detected        │ 02:14:06 │
│ Analyzed         │              │                  │          │
└──────────────────┴──────────────┴──────────────────┴──────────┘
```

1. **Sequences Analyzed**: total reads processed so far
2. **Sample Quality**: plain-language level (Excellent / Good / Fair / Poor) with the Q-score as a subtitle
3. **Species Detected**: count of distinct organisms found
4. **Run Time**: elapsed time + run state badge

### Zone 4 — Sample Details (collapsed accordion)

Click to expand a per-sample table with plain-language columns:
- **Sequences Analyzed** — reads processed for that sample
- **Sample Quality** — Q-score with color coding
- **Read Length** — typical read length
- **Match Rate** — how many reads were classified

---

## 🎬 Quick Start (3 Steps to Understanding Your Results)

### Step 1: Check the Traffic Light (5 seconds)
Look at the large circle at the top:
- 🟢 Green? Everything is good.
- 🟡 Amber? Check the alerts panel.
- 🔴 Red? Follow the action guidance immediately.

### Step 2: Read the Top Alert (30 seconds)
Look at the first item in the **Active Alerts** panel:
- **What it says**: Plain language description
- **Why it matters**: Reason for the alert
- **What to do**: Specific next steps

**Example**:
```
🔴 CRITICAL: Low quality detected in 3 samples: barcode01 (45%), barcode03 (38%)

→ Check sequencing conditions (temperature, flow cell health, sample quality)

Technical details: Pass rate below 50%
```

### Step 3: Follow Recommended Actions (varies)
Click the button in the alert or follow the listed steps.

**That's it. You now know the status and what to do.**

---

## 📋 Common Situations & What To Do

### Situation 1: "Analysis Complete" with Green Light
**Meaning**: Everything processed successfully, good quality data.

**What to do**:
1. Click "Generate Report" button (in alerts or top right)
2. Select PDF or Excel format
3. Save to your designated location
4. Review results in Taxonomy tab if needed
5. Archive or share report as per protocol

**Time required**: 5 minutes

---

### Situation 2: Amber Light with "Fair Quality" Warning
**Meaning**: Data is usable but not optimal. Results are likely valid but with some uncertainty.

**What to do**:
1. Click "View QC Report" button
2. Check which samples are affected
3. Review the "Reasons for Removal" section in QC tab
4. If pass rate is 60-70%: Proceed with caution, note in report
5. If pass rate < 60%: Consider re-running affected samples

**Time required**: 10 minutes

---

### Situation 3: Red Light with "Species of Interest Detected"
**Meaning**: A target organism (potential pathogen) was identified.

**What to do** (IMMEDIATE):
1. Click "Review Detections" button
2. Navigate to Organisms tab
3. Verify the organism identification (check read counts)
4. Click "Generate Report" for detailed species info
5. Follow your organization's reporting protocol
6. Contact appropriate authorities per guidelines

**Time required**: 15-20 minutes
**Priority**: IMMEDIATE

---

### Situation 4: "Low Yield" or "Insufficient Reads"
**Meaning**: Not enough genetic material was sequenced.

**What to do**:
1. Check if the sequencing run is still active
2. If active: Let it continue, check back in 30 minutes
3. If complete: Verify sample loading was correct
4. Check Summary tab for total reads
5. If critical sample: Consider re-running

**Time required**: 5 minutes (plus wait time)

---

### Situation 5: "High Error Count" or Red System Alert
**Meaning**: Technical problem with analysis.

**What to do**:
1. Take screenshot of error message
2. Note what you were doing when error occurred
3. Click "Help" → "Report Issue"
4. Contact bioinformatics support team
5. Provide screenshot and description

**Time required**: 5 minutes
**Priority**: URGENT (if blocking your work)

---

## 🗺️ Tab Guide (Where to Find What)

### Dashboard Tab (Default - Start Here)
- **Purpose**: At-a-glance clinical verdict
- **When to use**: Always check first
- **Key info**: Zone 1 verdict banner (color is the answer), Zone 2 pathogen cards with sample attribution, Zone 3 metrics, Zone 4 per-sample details
- **Action buttons**: View Report, Confirm (on pathogen cards)

### Configuration Tab
- **Purpose**: Set up new analyses
- **When to use**: Before starting a new run
- **Key settings**: Database selection, processing mode
- **Note**: Usually pre-configured, but verify before critical runs

### Organisms Tab
- **Purpose**: Detected organisms and classification results
- **When to use**: After analysis completes
- **Key info**: Organism cards with abundance bars and confidence badges
- **Export**: Download species lists

### Quality Control Tab
- **Purpose**: Data quality metrics across pipeline stages
- **When to use**: When quality alerts appear, or to verify data is trustworthy
- **Key info**:
  - **Stage Strip** at top: `Raw → Quality-filtered → Classified` with counts and a classification-rate delta
  - **Read Quality** card: Q20/Q30/average quality with color-coded thresholds
  - **Read Length** card: N50 and average length
  - **Sample Breakdown** table: per-sample filtered reads, classification rate, average Q score
- **Pipeline note**: When running Chopper (the default), the "Raw" slot shows "Not available" because Chopper does not produce a pre-filter read count

### Taxonomy Tab
- **Purpose**: Visual organism relationships
- **When to use**: Understanding complex samples
- **Key views**: Sankey diagram (flow), Sunburst (hierarchy)
- **Tip**: Switch between views with radio buttons

### Validation Tab
- **Purpose**: Verify organism identifications
- **When to use**: When a detection needs confirmation
- **Key views**: BLAST identity scores, minimap2 coverage plots
- **Tip**: Use "Validate" buttons on organism cards to trigger on-demand validation

### Watchlist Tab
- **Purpose**: Manage which pathogens to monitor
- **When to use**: Setting up monitoring for specific organisms
- **Key features**: Built-in watchlists (clinical, foodborne, respiratory, etc.), custom uploads
- **Tip**: Quick-start buttons let you activate common watchlists with one click

### Preparation Tab
- **Purpose**: Download reference genomes and prepare BLAST databases
- **When to use**: Before running validation on new organisms
- **Key info**: Genome download status, database readiness

---

## 💡 Tips for Effective Use

### General Tips
1. **Check Dashboard first, always**: It's your mission control
2. **Follow the alerts in order**: They're priority-sorted
3. **Hover for help**: Every element has a tooltip
4. **Click red rows**: They need immediate attention
5. **Screenshot important findings**: For records and reports

### Quality Tips
1. **Data Quality score > 75**: Excellent, proceed with confidence
2. **Data Quality score 60-75**: Good, usable for most purposes
3. **Data Quality score < 60**: Review carefully, consider re-running critical samples
4. **Pass rate matters**: >70% is normal, <60% indicates issues

### Organism Detection Tips
1. **High read counts** (>1000 reads): High confidence identification
2. **Medium read counts** (100-1000): Likely present, verify if critical
3. **Low read counts** (<100): Possible contamination or background
4. **Verify target species**: Always check Taxonomy tab for confirmation

### When to Contact Support
- Red system errors that persist
- Data quality consistently <50% for known good samples
- Unexpected organism detections in negative controls
- Questions about specific organism identifications
- Need for assistance interpreting complex results

---

## 🎓 Training Scenarios (Practice With Mock Data)

### Scenario 1: Normal Run (Easy)
**Goal**: Understand the interface with good data.

**Setup**:
```bash
python -m nanometa_live.core.testing.mock_data_generator \
    /tmp/test_data_normal \
    normal \
    3
```

**Expected**: Green light, ~80% quality, 5-8 organisms, no critical alerts.

**Practice**: Navigate all tabs, hover tooltips, generate report.

---

### Scenario 2: Quality Issues (Moderate)
**Goal**: Recognize and respond to quality problems.

**Setup**:
```bash
python -m nanometa_live.core.testing.mock_data_generator \
    /tmp/test_data_quality \
    quality_issues \
    5
```

**Expected**: Amber/red light, <65% quality, quality alerts.

**Practice**: Find affected samples, read QC report, follow action guidance.

---

### Scenario 3: Pathogen Detection (Advanced)
**Goal**: Handle potential bioterror threat.

**Setup**:
```bash
python -m nanometa_live.core.testing.mock_data_generator \
    /tmp/test_data_pathogen \
    pathogen \
    3
```

**Expected**: Red alert for species of interest, high priority action.

**Practice**: Rapid verification, report generation, protocol following.

---

## 📞 Support & Resources

### Quick Help
- **In-app help**: Click "?" icon next to any element
- **Tab help**: Click "Help" button in each tab
- **Alert guidance**: Read "→" recommendation in each alert

### Contact Information
- **Bioinformatics Support**: [Contact details here]
- **Emergency Pathogen Hotline**: [Emergency contact here]
- **Technical Issues**: [IT support here]

### Additional Resources
- **Full documentation**: [Link to detailed docs]
- **Video tutorials**: [Link to training videos]
- **FAQ**: [Link to common questions]

---

## 📝 Checklist: Operator Proficiency

Mark when you've successfully completed each task:

**Basic (Required - 10 minutes)**
- [ ] Understand traffic light colors (green/amber/red)
- [ ] Locate and read alerts panel
- [ ] Check data quality score
- [ ] Navigate to different tabs
- [ ] Hover over elements to see tooltips

**Intermediate (Recommended - 20 minutes)**
- [ ] Generate a PDF report
- [ ] Interpret QC statistics
- [ ] Identify samples needing attention
- [ ] Follow action guidance for an alert
- [ ] Export organism list from Taxonomy tab

**Advanced (Optional - 30 minutes)**
- [ ] Configure species of interest
- [ ] Interpret Sankey/Sunburst diagrams
- [ ] Compare results across multiple samples
- [ ] Troubleshoot quality issues
- [ ] Practice emergency pathogen response protocol

---

## 🚀 Remember: You Don't Need to Know Bioinformatics

**The system tells you**:
- ✅ What's happening (traffic lights)
- ✅ What it means (plain language)
- ✅ What to do (action guidance)
- ✅ Why it matters (context and consequences)

**You just need to**:
1. Look at the colors
2. Read the alerts
3. Follow the guidance
4. Contact support when unsure

**Trust the system. Follow the guidance. You've got this.**

---

*Nanometa Live v2.0 - Designed for operators, tested by operators*
*Questions? Contact your bioinformatics support team*
