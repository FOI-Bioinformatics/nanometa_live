"""
Configuration manager for Nanometa Live.

This module provides a manager for handling configuration state,
including updating, validating, and providing a single source of
configuration truth for the application.
"""

import os
import logging
from typing import Dict, Any, Optional, List

from nanometa_live.core.config.config_loader import ConfigLoader
from nanometa_live.core.config.config_validator import validate_config


class ConfigManager:
    """
    Manages application configuration state.

    This class provides methods for initializing, updating, validating, and
    accessing application configuration.
    """

    def __init__(self, data_dir: str):
        """
        Initialize the configuration manager.

        Args:
            data_dir: Base directory for storing configuration files
        """
        self.data_dir = data_dir
        self.config_dir = os.path.join(data_dir, "configs")
        self.config_loader = ConfigLoader(self.config_dir)
        self.current_config = None
        self.config_path = None

    def load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Load configuration from a file.

        Args:
            config_path: Path to the configuration file to load, or None to load the most recent

        Returns:
            The loaded configuration

        Raises:
            FileNotFoundError: If the configuration file doesn't exist
            ValueError: If the configuration is invalid
        """
        try:
            if config_path:
                self.config_path = config_path
                self.current_config = self.config_loader.load_config(config_path)
            else:
                # Try to load the most recent configuration
                most_recent = self.config_loader.get_most_recent_config()
                if most_recent:
                    self.current_config = most_recent
                    # Get the path from the available configs
                    available_configs = self.config_loader.get_available_configs()
                    if available_configs:
                        self.config_path = available_configs[0]["path"]
                else:
                    # Create default configuration
                    self.current_config = self.config_loader.create_default_config()
                    self.config_path = None

            # Validate the configuration
            self.current_config = validate_config(self.current_config)

            return self.current_config

        except Exception as e:
            logging.error(f"Failed to load configuration: {e}")
            # Fall back to a default configuration
            self.current_config = self.config_loader.create_default_config()
            self.config_path = None
            return self.current_config

    def save_config(self, filename: Optional[str] = None) -> str:
        """
        Save the current configuration to a file.

        Args:
            filename: Filename to save the configuration to, or None for a timestamp-based name

        Returns:
            The path to the saved configuration file

        Raises:
            ValueError: If there is no current configuration
        """
        if not self.current_config:
            raise ValueError("No current configuration to save")

        # If existing file and no new filename, use the same file to preserve comments
        if self.config_path and not filename:
            filename = os.path.basename(self.config_path)

        self.config_path = self.config_loader.save_config(self.current_config, filename)
        return self.config_path

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update the current configuration with new values.

        Args:
            updates: Dictionary of configuration updates

        Returns:
            The updated configuration

        Raises:
            ValueError: If there is no current configuration
        """
        if not self.current_config:
            raise ValueError("No current configuration to update")

        # Create a copy of the current configuration
        config = dict(self.current_config)

        # Update with new values
        config.update(updates)

        # Validate the updated configuration
        self.current_config = validate_config(config)

        return self.current_config

    def get_config(self) -> Dict[str, Any]:
        """
        Get the current configuration.

        Returns:
            The current configuration

        Raises:
            ValueError: If there is no current configuration
        """
        if not self.current_config:
            raise ValueError("No current configuration")

        return self.current_config

    def reset_to_defaults(self) -> Dict[str, Any]:
        """
        Reset the configuration to defaults.

        Returns:
            The default configuration
        """
        self.current_config = self.config_loader.create_default_config()
        self.config_path = None
        return self.current_config

    def get_available_configs(self) -> List[Dict[str, Any]]:
        """
        Get a list of available configuration files.

        Returns:
            A list of dictionaries containing metadata about available configs
        """
        return self.config_loader.get_available_configs()