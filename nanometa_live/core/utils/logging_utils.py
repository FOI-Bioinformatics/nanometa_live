import os
import sys
import logging
import logging.handlers
import time

def setup_logging(debug=False, log_dir=None, log_to_console=True):
    """Configure unified logging across the application.

    Console output is intentionally terse: only level + message, with a
    short logger tag. The full ``asctime - name - levelname - message``
    format is preserved on the file handler for post-mortem use.

    Werkzeug per-request access logs and the duplicate ``dash.dash``
    "Dash is running on..." line are demoted to WARNING so the console
    is not flooded with one INFO line per Dash callback POST.
    """
    file_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_formatter = logging.Formatter(file_format)

    console_format = "%(levelname)s %(name)s: %(message)s" if debug else "%(levelname)s: %(message)s"
    console_formatter = logging.Formatter(console_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    root_logger.handlers.clear()

    if log_to_console:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(console_formatter)
        root_logger.addHandler(console)

    # Quiet noisy third-party loggers unless --debug is set. Werkzeug
    # logs every Dash callback POST at INFO, and dash.dash echoes the
    # already-printed "Dash is running on" banner. Both clutter the
    # console without adding information.
    if not debug:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("dash.dash").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)

    # File handler
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"nanometa_live_{timestamp}.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

        # Create a special API debug log
        api_logger = logging.getLogger('api')
        api_log_file = os.path.join(log_dir, f"api_calls_{timestamp}.log")
        api_handler = logging.handlers.RotatingFileHandler(
            api_log_file, maxBytes=5 * 1024 * 1024, backupCount=3
        )
        api_handler.setFormatter(file_formatter)
        api_logger.addHandler(api_handler)
        api_logger.setLevel(logging.DEBUG)

        return log_file
    return None