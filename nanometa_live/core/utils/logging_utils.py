# Create this file: nanometa_live/core/utils/logging_utils.py
import os
import sys
import logging
import time
from pathlib import Path

def setup_logging(debug=False, log_dir=None, log_to_console=True):
    """Configure unified logging across the application"""
    # Create formatter
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Set root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Clear any existing handlers to avoid duplication
    root_logger.handlers.clear()

    # Console handler
    if log_to_console:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root_logger.addHandler(console)

    # File handler
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"nanometa_live_{timestamp}.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Create a special API debug log
        api_logger = logging.getLogger('api')
        api_log_file = os.path.join(log_dir, f"api_calls_{timestamp}.log")
        api_handler = logging.FileHandler(api_log_file)
        api_handler.setFormatter(formatter)
        api_logger.addHandler(api_handler)
        api_logger.setLevel(logging.DEBUG)

        return log_file
    return None