"""
Utility functions for GCode Proxy.

This module provides utility functions for serial device discovery and communication.
"""

import asyncio
import re

import serial
import serial.tools.list_ports

from gcode_proxy.core.logging import get_logger

logger = get_logger()

class SerialDeviceNotFoundError(Exception):
    """Raised when the specified USB device cannot be found."""

    pass


class SerialConnectionError(Exception):
    """Raised when there's an error connecting to or communicating with the serial device."""

    pass


def find_serial_port_by_usb_id(usb_id: str) -> str:
    """
    Find the serial port path for a given USB device ID.

    Args:
        usb_id: USB device ID in vendor:product format (e.g., "303a:4001").

    Returns:
        The serial port path (e.g., "/dev/ttyUSB0" or "COM3").

    Raises:
        SerialDeviceNotFoundError: If no matching device is found.
    """
    try:
        vendor_id, product_id = usb_id.lower().split(":")
        vendor_id_int = int(vendor_id, 16)
        product_id_int = int(product_id, 16)
    except (ValueError, AttributeError) as e:
        raise AttributeError(
            f"Invalid USB ID format '{usb_id}'. \
              Expected format: 'vendor:product' (e.g., '303a:4001')"
        ) from e

    ports = serial.tools.list_ports.comports()

    for port in ports:
        if port.vid == vendor_id_int and port.pid == product_id_int:
            logger.debug(f"Found device {usb_id} at {port.device}")
            return port.device

    # List available devices for debugging
    available = [
        f"{p.device} (VID:PID={p.vid:04x}:{p.pid:04x})"
        for p in ports
        if p.vid is not None and p.pid is not None
    ]

    logger.debug(f"Device {usb_id} not found. Available devices: {available}")

    raise SerialDeviceNotFoundError(
        f"USB device with ID '{usb_id}' not found. "
        f"Available USB serial devices: {available or 'none'}"
    )

async def wait_for_device(
    usb_id: str | None = None,
    dev_path: str | None = None,
    poll_interval: float = 1.0,
) -> str:
    """
    Wait for a device to become available, polling at regular intervals.

    If a USB ID is provided, polls for devices with that ID. If a device path
    is provided, polls for the existence of that path. At least one must be provided.

    Polling is done quietly without logging spam. Device discovery is only logged
    when found or when the list of available devices changes.

    Args:
        usb_id: USB device ID in vendor:product format (e.g., "303a:4001").
        dev_path: Device path like /dev/ttyACM0.
        timeout: Maximum time to wait in seconds. None means wait forever
            (default: None).
        poll_interval: Time between polls in seconds (default: 1.0).

    Returns:
        The device path when found.

    Raises:
        asyncio.CancelledError: If the polling task is cancelled (e.g., on shutdown).
        SerialDeviceNotFoundError: If device is not found within timeout.
        ValueError: If neither usb_id nor dev_path are provided.
    """
    if not usb_id and not dev_path:
        raise ValueError("Must specify either usb_id or dev_path")

    while True:
        try:
            if usb_id:
                return find_serial_port_by_usb_id(usb_id)
            else:
                # Check if the specified device path exists
                try:
                    with serial.Serial(dev_path) as _:
                        return dev_path
                except (serial.SerialException, FileNotFoundError):
                    pass  # Device not found yet

        except asyncio.CancelledError:
            logger.debug("Device wait task cancelled")
        except SerialDeviceNotFoundError:
            pass  # Continue polling

        await asyncio.sleep(poll_interval)

GRBL_CONTENT_RE = re.compile(
    r"^.*?(\d+\.\d+|\$.*|ok|error:\d+|ALARM:\d+|<[^>]+>|\[MSG:[^\]]+\]|Grbl\s\d+\.\d+.*)$",
    re.IGNORECASE,
)
GRBL_TERMINATORS_RE = re.compile(r"ok|error:\d+|!!|grbl\s\d+\.\d+.*", re.IGNORECASE)
GRBL_SOFT_RESET_RE = re.compile(r"\x18", re.IGNORECASE)
GRBL_IMMEDIATE_COMMANDS_RE = re.compile(r"\?|M0|M1|M2|M30|!|~|\x18", re.IGNORECASE)


def clean_grbl_response(raw_line: str) -> str:
    """
    Clean a single line of GRBL response by removing ESP log output.

    ESP logging can clobber serial responses. This function detects and removes
    ESP log headers while preserving valid GRBL response content.

    Args:
        raw_line: A single line of raw serial output.

    Returns:
        The cleaned line with ESP log prefixes removed, or empty string if
        line contains only ESP logging.

    Example:
        >>> clean_grbl_response("I (123) tag: ok")
        "ok"
        >>> clean_grbl_response("E (456) mytag: error:5")
        "error:5"
        >>> clean_grbl_response("ok")
        "ok"
    """

    match = GRBL_CONTENT_RE.search(raw_line.strip())

    cleaned = ""
    if match:
        cleaned = match.group(1)  # Return only the GRBL part

    return cleaned.strip()


def detect_grbl_terminator(line: str) -> bool:
    """
    Detect if a line contains a GRBL terminator.

    GRBL terminators include "ok", "error:<code>", "!!", and version strings.

    Args:
        line: A single line of cleaned GRBL response.
    """

    return bool(GRBL_TERMINATORS_RE.search(line))


def detect_grbl_soft_reset_command(command: str) -> bool:
    """
    Detect if a command contains a GRBL soft reset character.

    Args:
        line: A single line of raw serial output.
    """

    return bool(GRBL_SOFT_RESET_RE.search(command))

def is_immediate_grbl_command(command: str) -> bool:
    """
    Check if a GCode command is an immediate command.

    Immediate commands are executed right away without queuing.

    Args:
        gcode: The GCode command string.
    """

    return bool(GRBL_IMMEDIATE_COMMANDS_RE.search(command))
