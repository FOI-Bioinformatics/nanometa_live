# 0001. A verdict never claims a result it did not earn

**Status:** accepted (2026-07, extended 2026-08-08)

## Context

Three defects found in the 2026-07 campaign were one defect: the system
rendered "we did not check" identically to "we checked and it is fine". The
banner said ALL CLEAR with no watchlist loaded while F. tularensis sat at
54% of reads; the exported report said NO WATCHED ORGANISMS DETECTED in the
same state; a sample whose reads were unreadable was offered like a healthy
one. For a biothreat tool these are opposite statements.

## Decision

`select_verdict` (`app/tabs/dashboard_helpers.py`) is a pure function of
its inputs. It returns NOT_SCREENED when no watchlist entry is active and
INSUFFICIENT_READS when total reads fall below `low_read_floor` (anchored to
`min_reads_for_validation`). Both are amber, never green. `total_reads=None`
means "not determined" and never reads as zero. A detection always outranks
depth and run health; a pipeline error outranks every non-detection state
including "starting". The exported report template carries the same
branches, and the Organisms panel and alarm text state depth the same way.

## Consequences

Every new verdict state goes into the pure function, not the callback, so it
is testable without an app. Any surface that can say "all clear" must show
what it screened and at what depth. The banner is aggregate-scoped and does
not follow the selected sample, so a detection in an unviewed barcode is
never hidden.

## Evidence

`tests/test_verdict_selector.py`, `tests/test_report_generator.py`,
`tests/test_verdict_banner_callback.py`.
