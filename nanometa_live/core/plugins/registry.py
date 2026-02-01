"""
Plugin registry for Nanometa Live.

Handles plugin discovery, registration, and management. Plugins can be
loaded from built-in modules or external packages via pip entry points.
"""

import importlib
import logging
from typing import Dict, List, Optional, Any, Tuple

from nanometa_live.core.plugins.base import NanometaPlugin

logger = logging.getLogger(__name__)

# Global registry of loaded plugins
_registry: Dict[str, NanometaPlugin] = {}


def discover_plugins() -> List[NanometaPlugin]:
    """
    Discover and load available plugins.

    Loads plugins from:
    1. Built-in plugin modules in nanometa_live.plugins.*
    2. External packages registered via pip entry points

    Returns:
        List of discovered plugin instances
    """
    plugins = []

    # 1. Load built-in plugins
    builtin_modules = [
        # Future built-in plugins will be listed here
        # "nanometa_live.plugins.classification",
        # "nanometa_live.plugins.qc",
    ]

    for mod_name in builtin_modules:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "create_plugin"):
                plugin = mod.create_plugin()
                if isinstance(plugin, NanometaPlugin):
                    plugins.append(plugin)
                    logger.info(f"Loaded built-in plugin: {plugin.plugin_id}")
                else:
                    logger.warning(
                        f"Plugin from {mod_name} does not implement NanometaPlugin protocol"
                    )
        except ImportError as e:
            logger.debug(f"Built-in plugin module not found: {mod_name} - {e}")
        except Exception as e:
            logger.error(f"Failed to load built-in plugin {mod_name}: {e}")

    # 2. Load external plugins via entry points
    try:
        # Python 3.9+ has importlib.metadata in stdlib
        # For older versions, importlib_metadata backport would be needed
        from importlib.metadata import entry_points

        # Get entry points for our plugin group
        eps = entry_points()

        # Handle different Python versions (3.9 vs 3.10+ API)
        if hasattr(eps, "select"):
            # Python 3.10+
            plugin_eps = eps.select(group="nanometa_live.plugins")
        else:
            # Python 3.9
            plugin_eps = eps.get("nanometa_live.plugins", [])

        for ep in plugin_eps:
            try:
                # Load the entry point (calls the factory function)
                create_func = ep.load()
                plugin = create_func()

                if isinstance(plugin, NanometaPlugin):
                    plugins.append(plugin)
                    logger.info(f"Loaded external plugin: {plugin.plugin_id} from {ep.name}")
                else:
                    logger.warning(
                        f"External plugin {ep.name} does not implement NanometaPlugin protocol"
                    )
            except Exception as e:
                logger.error(f"Failed to load external plugin {ep.name}: {e}")

    except ImportError:
        logger.debug("importlib.metadata not available, skipping entry point discovery")
    except Exception as e:
        logger.error(f"Error discovering external plugins: {e}")

    return plugins


def register_plugin(plugin: NanometaPlugin) -> bool:
    """
    Register a plugin in the global registry.

    Args:
        plugin: Plugin instance to register

    Returns:
        True if registered successfully, False if plugin_id already exists
    """
    if plugin.plugin_id in _registry:
        logger.warning(
            f"Plugin '{plugin.plugin_id}' already registered, skipping duplicate"
        )
        return False

    _registry[plugin.plugin_id] = plugin
    logger.info(f"Registered plugin: {plugin.plugin_id} v{plugin.version}")
    return True


def get_plugin(plugin_id: str) -> Optional[NanometaPlugin]:
    """
    Get a registered plugin by ID.

    Args:
        plugin_id: The plugin identifier

    Returns:
        Plugin instance or None if not found
    """
    return _registry.get(plugin_id)


def get_all_plugins() -> Dict[str, NanometaPlugin]:
    """
    Get all registered plugins.

    Returns:
        Dictionary of plugin_id -> plugin instance
    """
    return dict(_registry)


def get_enabled_plugins(config: Dict[str, Any]) -> List[NanometaPlugin]:
    """
    Get plugins that are enabled in the configuration.

    If 'enabled_plugins' is not specified in config, all registered
    plugins are considered enabled.

    Args:
        config: Application configuration dictionary

    Returns:
        List of enabled plugin instances
    """
    if not config:
        return list(_registry.values())

    # Get list of enabled plugin IDs from config
    # Default to all plugins if not specified
    enabled_ids = config.get("enabled_plugins", list(_registry.keys()))

    # Return plugins that are both registered and enabled
    return [
        plugin
        for plugin_id, plugin in _registry.items()
        if plugin_id in enabled_ids
    ]


def clear_registry() -> None:
    """
    Clear all registered plugins.

    Primarily used for testing.
    """
    global _registry
    _registry = {}
    logger.debug("Plugin registry cleared")


def get_plugin_config_fields(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Get configuration fields from all enabled plugins.

    Aggregates config field definitions from all enabled plugins
    for dynamic form generation.

    Args:
        config: Application configuration (to determine which plugins are enabled)

    Returns:
        List of config field definitions from all enabled plugins
    """
    fields = []
    plugins = get_enabled_plugins(config) if config else list(_registry.values())

    for plugin in plugins:
        try:
            plugin_fields = plugin.get_config_fields()
            # Add plugin_id prefix to field IDs to avoid conflicts
            for field in plugin_fields:
                namespaced_field = field.copy()
                namespaced_field["id"] = f"{plugin.plugin_id}_{field['id']}"
                namespaced_field["plugin_id"] = plugin.plugin_id
                fields.append(namespaced_field)
        except Exception as e:
            logger.error(f"Error getting config fields from plugin {plugin.plugin_id}: {e}")

    return fields


def get_plugin_default_configs() -> Dict[str, Any]:
    """
    Get default configuration values from all registered plugins.

    Returns:
        Merged dictionary of default config values
    """
    defaults = {}

    for plugin in _registry.values():
        try:
            plugin_defaults = plugin.get_default_config()
            # Namespace the config keys
            for key, value in plugin_defaults.items():
                defaults[f"{plugin.plugin_id}_{key}"] = value
        except Exception as e:
            logger.error(f"Error getting defaults from plugin {plugin.plugin_id}: {e}")

    return defaults


def validate_plugin_configs(config: Dict[str, Any]) -> Dict[str, Tuple[bool, str]]:
    """
    Validate configuration for all enabled plugins.

    Args:
        config: Application configuration

    Returns:
        Dictionary of plugin_id -> (valid, message) tuples
    """
    results = {}

    for plugin in get_enabled_plugins(config):
        try:
            valid, message = plugin.validate_config(config)
            results[plugin.plugin_id] = (valid, message)
        except Exception as e:
            logger.error(f"Error validating config for plugin {plugin.plugin_id}: {e}")
            results[plugin.plugin_id] = (False, f"Validation error: {str(e)}")

    return results


def get_all_nextflow_params(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get Nextflow parameters from all enabled plugins.

    Merges parameters from all plugins. Later plugins override
    earlier ones if there are conflicts.

    Args:
        config: Application configuration

    Returns:
        Merged dictionary of Nextflow parameters
    """
    params = {}

    for plugin in get_enabled_plugins(config):
        try:
            plugin_params = plugin.get_nextflow_params(config)
            params.update(plugin_params)
        except Exception as e:
            logger.error(f"Error getting Nextflow params from plugin {plugin.plugin_id}: {e}")

    return params
