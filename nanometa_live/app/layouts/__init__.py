"""
Layouts package for Nanometa Live application.

This package contains the layout definitions for each tab in the application.
"""

from nanometa_live.app.layouts.config_layout import create_config_layout
from nanometa_live.app.layouts.dashboard_layout import create_dashboard_layout
from nanometa_live.app.layouts.main_layout import create_main_layout
from nanometa_live.app.layouts.qc_layout import create_qc_layout
from nanometa_live.app.layouts.classification_layout import create_classification_layout
from nanometa_live.app.layouts.validation_layout import (
    create_validation_layout,
    create_validation_status_card,
    create_validation_result_card,
)
# Watchlist and Preparation were merged into one tab; offline deployment split
# into its own tab.
from nanometa_live.app.layouts.watchlist_preparation_layout import (
    create_watchlist_preparation_layout,
)
from nanometa_live.app.layouts.deployment_layout import create_deployment_layout

__all__ = [
    "create_config_layout",
    "create_dashboard_layout",
    "create_main_layout",
    "create_qc_layout",
    "create_classification_layout",
    "create_validation_layout",
    "create_validation_status_card",
    "create_validation_result_card",
    "create_watchlist_preparation_layout",
    "create_deployment_layout",
]
