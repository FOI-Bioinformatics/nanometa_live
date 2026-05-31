"""
UI components package for Nanometa Live.

This package contains reusable UI components used across the application.

Components are organized as follows:
- header.py: Application header with status and controls
- config_form.py: Configuration form for analysis settings
- modern_components.py: Operator-friendly cards, badges, meters
- organism_components.py: Organism display cards
- pathogen_alert.py: Critical pathogen alert banners and panels
"""

from nanometa_live.app.components.header import create_header
from nanometa_live.app.components.config_form import create_config_form
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
    OrganismCard,
    OrganismSummaryCard,
)

__all__ = [
    "create_header",
    "create_config_form",
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
    "OrganismCard",
    "OrganismSummaryCard",
]
