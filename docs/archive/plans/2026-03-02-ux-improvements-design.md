# UX Improvements Design: Taxonomy Empty State, Tab Grouping, Alert Severity

Date: 2026-03-02
Status: Completed (all 3 items implemented, verified 2026-03-07)

## Context

Integration testing of the Nanometa Live dashboard (v4.0.0) identified three UX issues rated medium priority in the review (overall 7.5/10).

## 1. Taxonomy Empty State

**Problem:** The Taxonomy (Classification) tab renders a blank gray rectangle when no classification data is available.

**Solution:** Use the existing `EmptyStateMessage` component from `modern_components.py` in `classification_tab.py` callbacks. When no data is available, return an empty state message instead of an empty chart area.

- Title: "No Classification Data"
- Message: "Classification results will appear here once analysis data is available"
- Icon: `bi-diagram-3`
- Pattern matches QC tab and Organisms tab usage

**Files:** `nanometa_live/app/tabs/classification_tab.py`

## 2. Tab Navigation Grouping

**Problem:** 8 flat tabs are difficult to scan quickly. Current code has `tab-group-start` CSS class creating a left-border separator but no visible group labels.

**Solution:** Add CSS `::before` pseudo-elements on group-start tabs to render small labels ("Results" and "Setup") above each group. Use muted, small font so labels do not compete with tab names. Add `data-group-label` attributes to tab elements in `app.py` for CSS targeting.

**Groups:**
- Results: Dashboard, Organisms, QC, Taxonomy, Validation
- Setup: Configuration, Watchlist, Preparation

**Files:** `nanometa_live/app/assets/styles.css`, `nanometa_live/app/app.py`

## 3. Alert Severity Matching

**Problem:** The "Active Alerts" card uses red styling regardless of actual alert severity. Some alerts in `alert_engine.py` are over-classified (informational content with WARNING severity).

**Solution:**
1. Update "Active Alerts" card badge color to reflect highest severity present (red for CRITICAL only, amber for WARNING, blue for INFO-only, green for SUCCESS-only)
2. Audit severity assignments in `alert_engine.py` and downgrade informational alerts from WARNING to INFO
3. Verify `create_alerts_list()` renders each alert with its correct Bootstrap color class

**Files:** `nanometa_live/app/layouts/dashboard_layout.py`, `nanometa_live/core/utils/alert_engine.py`, `nanometa_live/app/tabs/dashboard_tab.py`
