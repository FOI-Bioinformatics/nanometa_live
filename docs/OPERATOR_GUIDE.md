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

When you open Nanometa Live, you see the **Dashboard** tab (default view):

### Top Section: Overall Status
```
🟢 System Running
Analysis in progress - processing sample data
Time elapsed: 00:15:32 | Processing - 3 of 5 samples complete
```

**What to look for**:
- Traffic light color (green/amber/red)
- Time running
- Progress statement

### Middle Section: Key Metrics (4 Cards)
```
┌──────────────┬─────────────┬──────────────┬────────────┐
│   10,000     │     85      │      12      │      2     │
│ DNA Sequences│ Data Quality│  Organisms   │   Alerts   │
└──────────────┴─────────────┴──────────────┴────────────┘
```

**What each means**:
1. **DNA Sequences**: Total genetic material processed (higher = more data)
2. **Data Quality**: Score 0-100 (>75 is good, <60 needs attention)
3. **Organisms**: Number of different species found
4. **Alerts**: Active issues requiring attention (0 is best)

**Hover over any number for detailed explanation.**

### Bottom Left: Sample Status Table

Color-coded table showing each sample:
- 🟢 **Green row**: Good quality, no issues
- 🟡 **Amber row**: Review recommended
- 🔴 **Red row**: Problem detected

**Click any row to see detailed info for that sample.**

### Bottom Right: Active Alerts

Priority-sorted list of issues:
- 🔴 **Red**: Critical - act immediately
- 🟡 **Amber**: Warning - review soon
- 🔵 **Blue**: Info - for your awareness
- 🟢 **Green**: Success - positive update

**Each alert tells you WHAT to do, not just what's wrong.**

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
4. Review results in Classification tab if needed
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
2. Navigate to Classification tab
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
- **Purpose**: At-a-glance status
- **When to use**: Always check first
- **Key info**: Traffic light, alerts, sample status
- **Action buttons**: Generate Report, View Details

### Configuration Tab
- **Purpose**: Set up new analyses
- **When to use**: Before starting a new run
- **Key settings**: Database selection, species of interest
- **Note**: Usually pre-configured, but verify before critical runs

### Main Results Tab
- **Purpose**: Detailed classification results
- **When to use**: After analysis completes
- **Key info**: Top organisms, abundance charts
- **Export**: Download species lists

### QC (Quality Control) Tab
- **Purpose**: Data quality metrics
- **When to use**: When quality alerts appear
- **Key info**: Pass rates, filtering reasons, per-sample breakdown
- **Use for**: Troubleshooting quality issues

### Classification Tab
- **Purpose**: Visual organism relationships
- **When to use**: Understanding complex samples
- **Key views**: Sankey diagram (flow), Sunburst (hierarchy)
- **Tip**: Switch between views with radio buttons

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
4. **Verify target species**: Always check Classification tab for confirmation

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
- [ ] Export organism list from Classification tab

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
