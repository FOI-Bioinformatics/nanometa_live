"""
Base plugin protocol for Nanometa Live.

Defines the interface that all plugins must implement to integrate with
the Nanometa Live dashboard. Plugins provide configuration, data loading,
visualization, and callback functionality for specific analysis types.
"""

from typing import Any, Dict, List, Optional, Tuple, Protocol, runtime_checkable
from abc import abstractmethod

from dash import Dash, html


@runtime_checkable
class NanometaPlugin(Protocol):
    """
    Protocol defining the interface for Nanometa Live plugins.

    All plugins must implement these methods and properties to integrate
    with the dashboard. The plugin system uses duck typing - any class
    that implements these methods will work as a plugin.

    Example implementation:
        class MyAnalysisPlugin:
            @property
            def plugin_id(self) -> str:
                return "my_analysis"

            @property
            def display_name(self) -> str:
                return "My Analysis"

            # ... implement other required methods
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """
        Unique identifier for this plugin.

        Used for configuration, registration, and internal references.
        Should be lowercase with underscores (e.g., "assembly", "amr_detection").

        Returns:
            Unique string identifier
        """
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable name for display in the UI.

        Used as the tab label and in configuration interfaces.

        Returns:
            Display name (e.g., "Assembly", "AMR Detection")
        """
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Brief description of the plugin's functionality.

        Shown in tooltips and plugin management interfaces.

        Returns:
            Description string (1-2 sentences)
        """
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """
        Plugin version string.

        Follows semantic versioning (e.g., "1.0.0", "2.1.3").

        Returns:
            Version string
        """
        ...

    @abstractmethod
    def get_config_fields(self) -> List[Dict[str, Any]]:
        """
        Get configuration field definitions for the config form.

        Each field dictionary should contain:
            - id: str - Unique field identifier
            - label: str - Display label
            - type: str - Field type ("text", "number", "select", "checkbox", "path")
            - options: List[Dict] - For select fields: [{"label": ..., "value": ...}]
            - default: Any - Default value
            - required: bool - Whether field is required
            - group: str - Grouping for UI organization
            - help_text: str - Optional help text / tooltip

        Returns:
            List of field definition dictionaries
        """
        ...

    @abstractmethod
    def get_default_config(self) -> Dict[str, Any]:
        """
        Get default configuration values for this plugin.

        Returns:
            Dictionary of config key -> default value
        """
        ...

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate the provided configuration.

        Should check that all required fields are present and valid.

        Args:
            config: Configuration dictionary

        Returns:
            Tuple of (valid: bool, message: str)
            If invalid, message should describe what's wrong
        """
        ...

    @abstractmethod
    def get_nextflow_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get Nextflow parameters to merge into params.json.

        Maps plugin configuration to Nextflow pipeline parameters.
        Return empty dict if plugin doesn't use Nextflow.

        Args:
            config: Current application configuration

        Returns:
            Dictionary of Nextflow parameters
        """
        ...

    @abstractmethod
    def prepare(
        self,
        config: Dict[str, Any],
        progress_callback: Optional[callable] = None
    ) -> Tuple[bool, str]:
        """
        Run preparation steps for this plugin.

        Called before pipeline execution. Use for downloading databases,
        building indices, validating inputs, etc.

        Args:
            config: Current application configuration
            progress_callback: Optional callback for progress updates
                              Called with (percent: int, message: str)

        Returns:
            Tuple of (success: bool, message: str)
        """
        ...

    @abstractmethod
    def load_data(
        self,
        main_dir: str,
        sample: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load plugin output data from results directory.

        Called by callbacks to get data for visualization.

        Args:
            main_dir: Path to results directory
            sample: Optional sample name for sample-specific data

        Returns:
            Dictionary of loaded data
        """
        ...

    @abstractmethod
    def create_tab_layout(self) -> html.Div:
        """
        Create the Dash layout for this plugin's tab.

        Returns a complete tab layout including all UI components.
        Component IDs should be namespaced with plugin_id to avoid conflicts.

        Returns:
            html.Div containing the tab layout
        """
        ...

    @abstractmethod
    def register_callbacks(self, app: Dash) -> None:
        """
        Register Dash callbacks for this plugin.

        Called during app initialization. Should register all callbacks
        needed for the plugin's tab functionality.

        Args:
            app: The Dash application instance
        """
        ...


class BasePlugin:
    """
    Base class providing common functionality for plugins.

    Plugins can inherit from this class to get default implementations
    of some methods. Override methods as needed for custom behavior.
    """

    @property
    def plugin_id(self) -> str:
        raise NotImplementedError("Subclass must implement plugin_id")

    @property
    def display_name(self) -> str:
        raise NotImplementedError("Subclass must implement display_name")

    @property
    def description(self) -> str:
        return f"{self.display_name} plugin for Nanometa Live"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_config_fields(self) -> List[Dict[str, Any]]:
        """Default: no additional config fields."""
        return []

    def get_default_config(self) -> Dict[str, Any]:
        """Default: no additional config values."""
        return {}

    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Default: always valid."""
        return True, "Configuration valid"

    def get_nextflow_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Default: no Nextflow parameters."""
        return {}

    def prepare(
        self,
        config: Dict[str, Any],
        progress_callback: Optional[callable] = None
    ) -> Tuple[bool, str]:
        """Default: no preparation needed."""
        if progress_callback:
            progress_callback(100, "No preparation required")
        return True, "No preparation required"

    def load_data(
        self,
        main_dir: str,
        sample: Optional[str] = None
    ) -> Dict[str, Any]:
        """Default: return empty data."""
        return {}

    def create_tab_layout(self) -> html.Div:
        """Default: placeholder layout."""
        return html.Div([
            html.H4(self.display_name),
            html.P(self.description),
            html.P("This plugin has not implemented a custom layout.", className="text-muted"),
        ], className="p-3")

    def register_callbacks(self, app: Dash) -> None:
        """Default: no callbacks."""
        pass

    def _make_id(self, component_id: str) -> str:
        """
        Create a namespaced component ID to avoid conflicts.

        Args:
            component_id: The local component ID

        Returns:
            Namespaced ID: "{plugin_id}-{component_id}"
        """
        return f"{self.plugin_id}-{component_id}"
