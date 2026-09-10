# 0004. Background callbacks share state through Stores and take no per-tick Input

**Status:** accepted (2026-08-25)

## Context

Dash's DiskcacheManager runs a background callback in a separate OS
process, where every Python singleton (WatchlistManager, caches) is empty.
The readiness checker reported every watchlist check as "not enabled" from
the worker. Separately, a background callback fed by `update-interval`
spawned a process per tick and leaked about five pipe descriptors per
spawn; 4,500 pipes were measured in two hours.

## Decision

A background callback that needs main-process state takes it from a
`dcc.Store` populated in the main process (`watchlist-entries-snapshot`,
passed into `ReadinessChecker.check_readiness(watchlist_entries=...)`).
No background callback takes `update-interval` as an Input; per-tick work
runs behind a synchronous main-process gate that bumps a "due" Store, and
periodic probes run in a daemon thread. Heavy click paths are
`background=True` with `running=` or `progress=` declared. Start and Stop
run main-process threads, because BackendManager holds subprocess handles
a worker cannot.

## Consequences

Every background callback follows the worker/Store/finalize split: I/O in
the worker, side effects in a main-process finalize. Browser Stores carry
slim payloads (`export_config(slim=True)`); disk files stay full.

## Evidence

`tests/test_background_callback_contract.py`,
`tests/test_readiness_spawn_gate.py`, `tests/test_payload_budgets.py`.
