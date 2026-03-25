"""
Watchlist Manager UI Component for Nanometa Live.

Provides a comprehensive UI for managing species watchlists:
- Enable/disable builtin watchlists
- Import custom watchlist files
- Toggle individual pathogens
- Edit alert thresholds
- View taxonomy indicator
"""

from typing import Any, Dict, List, Optional
from dash import html, dcc
import dash_bootstrap_components as dbc


"""
Watchlist Manager UI Component for Nanometa Live.

Provides reusable UI components for watchlist management. The main watchlist
layout and callbacks are in watchlist_layout.py and watchlist_tab.py.
"""
