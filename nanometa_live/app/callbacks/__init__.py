"""Application callback registration, split by domain.

``register_core_callbacks`` composes the per-domain ``register_*`` functions
in the same order they were originally defined.
"""

from dash import Dash

from nanometa_live.core.workflow.backend_manager import BackendManager
from nanometa_live.app.callbacks.interval_offline import register_interval_offline
from nanometa_live.app.callbacks.startup import register_startup
from nanometa_live.app.callbacks.status import register_status
from nanometa_live.app.callbacks.start_stop import register_start_stop
from nanometa_live.app.callbacks.readiness import register_readiness
from nanometa_live.app.callbacks.samples import register_samples
from nanometa_live.app.callbacks.indicators import register_indicators
from nanometa_live.app.callbacks.progress import register_progress
from nanometa_live.app.callbacks.navigation import register_navigation


__all__ = ["register_core_callbacks"]


def register_core_callbacks(app: Dash, backend_manager: BackendManager):
    """
    Register core application callbacks.

    Args:
        app: Dash application
        backend_manager: Backend manager instance
    """
    register_interval_offline(app, backend_manager)
    register_startup(app, backend_manager)
    register_status(app, backend_manager)
    register_start_stop(app, backend_manager)
    register_readiness(app, backend_manager)
    register_samples(app, backend_manager)
    register_indicators(app, backend_manager)
    register_progress(app, backend_manager)
    register_navigation(app, backend_manager)
