"""
UI components package for Nanometa Live.

This package contains reusable UI components used across the application.

Components are organized as follows:
- header.py: Application header with status and controls
- config_form.py: Configuration form for analysis settings
- sample_selector.py: Multi-sample/barcode selection
- watchlist_manager_ui.py: Unified watchlist management UI
- watchlist_modal.py: Watchlist modals for detail views
- modern_components.py: Operator-friendly cards, badges, meters
- organism_components.py: Organism display cards
- tooltip_components.py: Help icons and contextual guidance
- pathogen_alert.py: Critical pathogen alert banners and panels
"""

from nanometa_live.app.components.header import create_header
from nanometa_live.app.components.config_form import create_config_form
from nanometa_live.app.components.sample_selector import (
    create_sample_selector,
    create_compact_sample_selector,
)
from nanometa_live.app.components.watchlist_manager_ui import (
    create_watchlist_section,
    create_active_species_list,
    create_taxonomy_selector,
    create_watchlist_stats_card,
)
from nanometa_live.app.components.watchlist_modal import (
    create_watchlist_view_modal,
    create_pathogen_detail_modal,
    create_pathogen_list_content,
    create_pathogen_detail_content,
    create_threshold_edit_modal,
    create_all_modals,
)
from nanometa_live.app.components.pathogen_alert import (
    CriticalPathogenAlert,
    HighRiskPathogenAlert,
    WatchedSpeciesAlert,
    PathogenAlertPanel,
    ThreatSummaryIndicator,
)
from nanometa_live.app.components.modern_components import (
    QualityScoreBadge,
    N50Badge,
    ClassificationRateBadge,
    StatusCard,
    StatCard,
    AlertBanner,
    SampleStatusBadge,
    EmptyStateMessage,
    TrendIndicator,
    DecisionBanner,
)
from nanometa_live.app.components.organism_components import (
    QualityScoreIndicator,
    FilteringBreakdownVisual,
    OrganismCard,
    OrganismSummaryCard,
    KeyMetricsSummaryCard,
)

__all__ = [
    "create_header",
    "create_config_form",
    "create_sample_selector",
    "create_compact_sample_selector",
    # Watchlist management
    "create_watchlist_section",
    "create_active_species_list",
    "create_taxonomy_selector",
    "create_watchlist_stats_card",
    "create_watchlist_view_modal",
    "create_pathogen_detail_modal",
    "create_pathogen_list_content",
    "create_pathogen_detail_content",
    "create_threshold_edit_modal",
    "create_all_modals",
    # Pathogen alerts
    "CriticalPathogenAlert",
    "HighRiskPathogenAlert",
    "WatchedSpeciesAlert",
    "PathogenAlertPanel",
    "ThreatSummaryIndicator",
    # Modern components
    "QualityScoreBadge",
    "N50Badge",
    "ClassificationRateBadge",
    "StatusCard",
    "StatCard",
    "AlertBanner",
    "SampleStatusBadge",
    "EmptyStateMessage",
    "TrendIndicator",
    "DecisionBanner",
    # Organism components
    "QualityScoreIndicator",
    "FilteringBreakdownVisual",
    "OrganismCard",
    "OrganismSummaryCard",
    "KeyMetricsSummaryCard",
]
