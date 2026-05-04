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
    from nanometa_live.core.watchlist import get_watchlist_manager

    manager = get_watchlist_manager()
    manager.load_config(config)
    alerts = manager.check_organisms(detected_organisms)
"""

from .watchlist_manager import (
    WatchlistManager,
    WatchlistEntry,
    WatchlistSource,
    BUILTIN_CATEGORIES,
    get_watchlist_manager,
    reset_watchlist_manager,
)

from .taxonomy_matcher import (
    TaxonomyMatcher,
    TaxonomyType,
    get_taxonomy_matcher,
    reset_taxonomy_matcher,
)

from .watchlist_loader import (
    WatchlistLoader,
    WatchlistMetadata,
    WatchlistPathogenEntry,
    get_watchlist_loader,
    reset_watchlist_loader,
)

__all__ = [
    # Manager
    "WatchlistManager",
    "WatchlistEntry",
    "WatchlistSource",
    "BUILTIN_CATEGORIES",
    "get_watchlist_manager",
    "reset_watchlist_manager",
    # Taxonomy
    "TaxonomyMatcher",
    "TaxonomyType",
    "get_taxonomy_matcher",
    "reset_taxonomy_matcher",
    # Loader
    "WatchlistLoader",
    "WatchlistMetadata",
    "WatchlistPathogenEntry",
    "get_watchlist_loader",
    "reset_watchlist_loader",
]
