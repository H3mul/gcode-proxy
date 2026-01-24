"""
Unified logging setup for GCode Proxy Server.

This module provides centralized logging configuration with:
- Custom VERBOSE logging level (level 9, more verbose than DEBUG)
- verbose() method added to the standard Logger class
- Consistent logging setup across the application

Usage:
    from gcode_proxy.logging import setup_logging, VERBOSE

    # In your CLI or main entry point:
    setup_logging(verbosity_level=2, quiet=False)  # VERBOSE level

    # Use verbose logging anywhere:
    logger = logging.getLogger(__name__)
    logger.verbose("This is a verbose message")
"""

import logging
from pathlib import Path
from typing import Any

# Define custom VERBOSE level (9 is between DEBUG (10) and NOTSET (0))
# Lower numbers = more verbose logging enabled
VERBOSE = 9
logging.addLevelName(VERBOSE, "VERBOSE")

GCODE_LOGGER_ID = "gcode"


DATE_FMT = "%Y-%m-%d %H:%M:%S"
LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
GCODE_LOG_FMT = "%(asctime)s - %(levelname)s - %(source)s - %(message)s - %(command)s"


def verbose(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    """
    Log a message with severity 'VERBOSE'.

    VERBOSE is a custom level that is more verbose than DEBUG.
    It's useful for very detailed logging that would clutter DEBUG output.

    Args:
        self: The logger instance (injected via method binding).
        message: The log message.
        *args: Arguments for message formatting.
        **kwargs: Additional keyword arguments passed to log().
    """
    if self.isEnabledFor(VERBOSE):
        self._log(VERBOSE, message, args, **kwargs)


# Add the verbose() method to the standard Logger class
logging.Logger.verbose = verbose  # type: ignore[assignment]


def setup_logging(
    verbosity_level: int = 0, quiet: bool = False, gcode_log_file: str | None = None
) -> None:
    """
    Configure logging based on verbosity settings.

    This is the unified logging setup location used throughout the application.
    All logging configuration should happen here.

    Args:
        verbosity_level: Verbosity counter from CLI (e.g., from Click's count=True).
            - 0: INFO level (default)
            - 1: DEBUG level (-v flag)
            - 2+: VERBOSE level (-vv or more flags)
        quiet: If True, set log level to ERROR (takes precedence over verbosity_level).
        gcode_log_file: Optional path to a file to log all GCode communication.
            If provided, a separate logger named 'gcode' is configured to write
            messages only to this file (propagate=False).
    """
    # Determine the appropriate log level
    if quiet:
        level = logging.ERROR
    elif verbosity_level >= 2:
        level = VERBOSE
    elif verbosity_level == 1:
        level = logging.DEBUG
    else:
        level = logging.INFO

    # Configure basic logging with consistent format
    logging.basicConfig(level=level, format=LOG_FMT, datefmt=DATE_FMT)

    # Optional: set up separate logger for GCode file logging
    if gcode_log_file:
        try:
            # Ensure log file path exists
            log_path = Path(gcode_log_file)
            if log_path.parent:
                log_path.parent.mkdir(parents=True, exist_ok=True)
            if not log_path.exists():
                log_path.touch()

            gcode_logger = logging.getLogger(GCODE_LOGGER_ID)

            # Check if a FileHandler for this exact path already exists
            existing_same_file = False
            for h in gcode_logger.handlers:
                if isinstance(h, logging.FileHandler):
                    try:
                        if Path(getattr(h, "baseFilename", "")).resolve() == log_path.resolve():
                            existing_same_file = True
                            break
                    except Exception:
                        continue

            if not existing_same_file:
                # Remove any existing file handlers to avoid duplicates
                for h in list(gcode_logger.handlers):
                    if isinstance(h, logging.FileHandler):
                        gcode_logger.removeHandler(h)
                fh = logging.FileHandler(str(log_path), encoding="utf-8", mode='a')

                # Use the same format as stdout logging for consistency
                fh.setFormatter(logging.Formatter(GCODE_LOG_FMT, datefmt=DATE_FMT))
                fh.setLevel(logging.INFO)
                gcode_logger.addHandler(fh)

            gcode_logger.setLevel(logging.INFO)

            # Do not propagate to root logger - only write to file
            gcode_logger.propagate = False

        except Exception as e:
            logging.getLogger(__name__).error(
                f"Failed to set up GCode log file '{gcode_log_file}': {e}"
            )

def get_gcode_logger():
    return logging.getLogger(GCODE_LOGGER_ID)

def log_gcode(command: str | bytes, source: str, message: str = ""):
    get_gcode_logger().info(message, extra={"source": source, "command": repr(command)})
