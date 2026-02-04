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
TCP_LOGGER_ID = "tcp"

DATE_FMT = "%Y-%m-%d %H:%M:%S"
LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
COMM_LOG_FMT = "%(asctime)s - %(source)s: %(message)s"


class VerboseLogger(logging.Logger):
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


def setup_logging(
    verbosity_level: int = 0,
    quiet: bool = False,
    gcode_log_file: str | None = None,
    tcp_log_file: str | None = None,
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
        tcp_log_file: Optional path to a file to log all TCP communication.
            If provided, a separate logger named 'tcp' is configured to write
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

    logging.setLoggerClass(VerboseLogger)

    # Configure basic logging with consistent format
    logging.basicConfig(level=level, format=LOG_FMT, datefmt=DATE_FMT)

    # Optional: set up separate logger for GCode file logging
    setup_file_logger(gcode_log_file, GCODE_LOGGER_ID)

    # Optional: set up separate logger for TCP file logging
    setup_file_logger(tcp_log_file, TCP_LOGGER_ID)


def setup_file_logger(log_file: str | None, logger_id) -> None:
    file_logger = logging.getLogger(logger_id)

    # Already configured
    if file_logger.handlers and \
        any(isinstance(h, logging.FileHandler) for h in file_logger.handlers):
        return

    try:
        fh = logging.NullHandler()
        if log_file:
            # Ensure log file path exists
            log_path = Path(log_file)
            if log_path.parent:
                log_path.parent.mkdir(parents=True, exist_ok=True)
            if not log_path.exists():
                log_path.touch()

            fh = logging.FileHandler(str(log_path), encoding="utf-8", mode="a")

            # Use the same format as stdout logging for consistency
            fh.setFormatter(logging.Formatter(COMM_LOG_FMT, datefmt=DATE_FMT))
            fh.setLevel(logging.INFO)

        file_logger.addHandler(fh)
        file_logger.setLevel(logging.INFO)

        # Do not propagate to root logger - only write to file
        file_logger.propagate = False

    except Exception as e:
        logging.getLogger(__name__).error(
            f"Failed to set up log file '{log_file}' for logger '{logger_id}': {e}"
        )


def get_logger(name: str | None = None) -> VerboseLogger:
    """
    Get a logger instance, ensuring it is a VerboseLogger.

    This function is a wrapper around logging.getLogger that ensures the
    returned logger is an instance of VerboseLogger, even if it was
    created before setup_logging() was called.

    Args:
        name: The name of the logger to get. Defaults to the calling module.

    Returns:
        An instance of VerboseLogger.
    """
    if name is None:
        # Get the name of the calling module
        import inspect

        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        name = module.__name__ if module else "__main__"

    logger = logging.getLogger(name)

    # If the logger is not a VerboseLogger, it was created before
    # setLoggerClass was called. We need to replace it.
    if not isinstance(logger, VerboseLogger):
        logger.__class__ = VerboseLogger

    return logger  # type: ignore


def get_gcode_logger():
    return logging.getLogger(GCODE_LOGGER_ID)


def get_tcp_logger():
    return logging.getLogger(TCP_LOGGER_ID)


def log_gcode_communication(content: str | bytes, sent: bool = True):
    get_gcode_logger().info(content, extra={"source": "Sent" if sent else "Recv"})


def log_gcode_sent(command: str):
    log_gcode_communication(command, sent=True)


def log_gcode_recv(command: str):
    log_gcode_communication(command, sent=False)


def log_tcp_communication(content: str | bytes, client_address: tuple[str, int] | None, sent: bool):
    # Assume broadcast if no client address provided
    source_str = "Broadcast"
    if client_address:
        source_str = f"{client_address[0]}:{client_address[1]}"
    get_tcp_logger().info(
        content, extra={"source": f"Sent {source_str}" if sent else f"Recv {source_str}"}
    )

def log_tcp_sent(content: str | bytes, source: tuple[str, int] | None):
    log_tcp_communication(content, source, sent=True)


def log_tcp_recv(content: str | bytes, source: tuple[str, int] | None):
    log_tcp_communication(content, source, sent=False)
