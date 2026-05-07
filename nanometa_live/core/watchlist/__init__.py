"""
Unified Watchlist System for Nanometa Live.

This module provides a unified approach to species watchlists, combining:
- Built-in CDC/WHO pathogen database (YAML-based)
- User-defined custom species from multiple locations
- Multi-taxonomy support (NCBI and GTDB)
- Legacy species_of_interest backward compatibility

Search order for custom watchlists:
1. <project_dir>/watchlists/ - Per-project custom watchlists
2. ~/.nanometa/watchlists/ - User's global watchlists
3. Built-in core/config/data/watchlists/ - System defaults

Usage:
    from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager

    manager = get_watchlist_manager()
    manager.load_config(config)
    alerts = manager.check_organisms(detected_organisms)

Import directly from leaf modules (watchlist_manager, taxonomy_matcher,
watchlist_loader); the package level re-export hub was collapsed in the
2026-05-07 audit pass.
"""
