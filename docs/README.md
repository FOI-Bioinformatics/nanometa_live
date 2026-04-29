# Nanometa Live Documentation

## User Documentation

| Document | Description |
|----------|-------------|
| [User Guide](user-guide.md) | Getting started and usage |
| [Configuration Reference](configuration.md) | All configuration options |
| [Operator Guide](OPERATOR_GUIDE.md) | Quick reference for lab personnel |

## Developer Documentation

| Document | Description |
|----------|-------------|
| [Developer Guide](developer-guide.md) | Architecture and contributing |
| [API Reference](api-reference.md) | Python API documentation |

## Technical Reference

| Document | Description |
|----------|-------------|
| [Parser Guide](nanometanf_parser_guide.md) | Output file parsing |
| [Parser Quick Reference](parser_quick_reference.md) | Common parser operations |
| [Migration Guide](MIGRATION_GUIDE_V2.md) | Upgrading from v1.x |
| [Validation Walkthrough](validation-walkthrough-checklist.md) | Validation feature checklist |

## Audits

| Audit | Date | Scope |
|-------|------|-------|
| [Production Readiness](audit-2026-04-28-production-readiness.md) | 2026-04-28 | Offline deployment cycle synthesis (86/100) |
| [nanometa_live Code](audit-2026-04-28-nanometa-live-code.md) | 2026-04-28 | Phase 4a python-pro audit (22 findings) |
| [Throughput: Pipeline](audit-2026-04-28-throughput-pipeline.md) | 2026-04-28 | nanometanf scaling at 12-24 barcodes |
| [Throughput: GUI](audit-2026-04-28-throughput-gui.md) | 2026-04-28 | Callback fanout + cache scaling at 12-24 barcodes |
| [Throughput: UX](audit-2026-04-28-throughput-ux.md) | 2026-04-28 | UI scaling at 12-24 barcodes |
| [Throughput Synthesis](audit-2026-04-28-throughput-synthesis.md) | 2026-04-28 | 12-24 barcode rubric (67/100) |
| [Container URLs](audit-2026-04-29-container-urls.md) | 2026-04-29 | Module container source verification (40 modules, 0 drift) |

## Design Plans

| Plan | Status |
|------|--------|
| [Validation Design](plans/2026-01-30-validation-design.md) | Completed |
| [Validation Implementation](plans/2026-01-30-validation-implementation.md) | Completed |
| [Validation Tab Redesign](plans/2026-01-31-validation-tab-redesign.md) | Completed |
| [UX Improvements](plans/2026-03-02-ux-improvements-design.md) | Completed |
| [Offline Deployment](plans/2026-03-06-offline-deployment-design.md) | Implemented |
| [E2E Testing Fixes](plans/2026-03-07-e2e-testing-fixes.md) | Completed |
| [Throughput Fixes (Waves 1-4, 6)](plan-2026-04-28-throughput-fixes.md) | Implemented; Waves 5 (empirical) + 7 (Apptainer) deferred |

## Archive

Historical implementation documents are in the [archive/](archive/) subdirectory.
