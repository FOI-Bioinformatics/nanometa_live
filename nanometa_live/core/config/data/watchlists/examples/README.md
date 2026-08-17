# Example watchlists (not auto-loaded)

The YAML files in this directory are **templates**, not active watchlists.
Watchlist discovery scans only the top level of each watchlist directory, so
nothing in `examples/` appears in the GUI, in counts, or in exported bundles.

To use one:

1. Copy it out of `examples/` and adjust the entries (names, `taxid_ncbi`,
   `alert_threshold`, `action_required`) for your deployment.
2. Import it through the GUI: Watchlist & Preparation → Watchlist Files →
   Import YAML Watchlist. The upload validator will report schema problems.
   Alternatively drop it directly into your user watchlist directory
   (`<data_dir>/watchlists`).

These files also demonstrate the optional `organism_type` and `annotation`
fields that the built-in lists do not use.
