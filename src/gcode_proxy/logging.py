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
from typing import Any


# Define custom VERBOSE level (9 is between DEBUG (10) and NOTSET (0))
# Lower numbers = more verbose logging enabled
VERBOSE = 9
logging.addLevelName(VERBOSE, "VERBOSE")


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


def setup_logging(verbosity_level: int = 0, quiet: bool = False) -> None:
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
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
