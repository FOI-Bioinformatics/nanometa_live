"""
Plugin system for Nanometa Live.

This module provides extensibility through a plugin architecture that allows
adding new analysis types (assembly, AMR detection, phylogenetics) as
self-contained modules without modifying core code.

Usage:
    from nanometa_live.core.plugins import (
        NanometaPlugin,
        discover_plugins,
        register_plugin,
        get_plugin,
        get_all_plugins,
        get_enabled_plugins,
    )

    # Discover and register plugins at app startup
    for plugin in discover_plugins():
        register_plugin(plugin)

    # Get enabled plugins based on config
    for plugin in get_enabled_plugins(config):
        plugin.register_callbacks(app)
"""

from nanometa_live.core.plugins.base import NanometaPlugin
from nanometa_live.core.plugins.registry import (
    discover_plugins,
    register_plugin,
    get_plugin,
    get_all_plugins,
    get_enabled_plugins,
    clear_registry,
)

__all__ = [
    "NanometaPlugin",
    "discover_plugins",
    "register_plugin",
    "get_plugin",
    "get_all_plugins",
    "get_enabled_plugins",
    "clear_registry",
]
