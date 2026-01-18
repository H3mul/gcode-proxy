"""
Utility functions for GCode Proxy.

This module provides utility functions for serial device discovery and communication.
"""

import logging
import re

import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)


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
        raise SerialDeviceNotFoundError(
            f"Invalid USB ID format '{usb_id}'. \
              Expected format: 'vendor:product' (e.g., '303a:4001')"
        ) from e

    ports = serial.tools.list_ports.comports()

    for port in ports:
        if port.vid == vendor_id_int and port.pid == product_id_int:
            logger.info(f"Found device {usb_id} at {port.device}")
            return port.device

    # List available devices for debugging
    available = [
        f"{p.device} (VID:PID={p.vid:04x}:{p.pid:04x})"
        for p in ports
        if p.vid is not None and p.pid is not None
    ]
    logger.error(f"Device {usb_id} not found. Available devices: {available}")

    raise SerialDeviceNotFoundError(
        f"USB device with ID '{usb_id}' not found. "
        f"Available USB serial devices: {available or 'none'}"
    )


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
    # The regex focuses on the end of the string
    pattern = r"^.*?(ok|error:\d+|ALARM:\d+|<[^>]+>|\[MSG:[^\]]+\]|Grbl\s\d+\.\d+.*)$"
    match = re.search(pattern, raw_line.strip())
    
    cleaned = ""
    if match:
        cleaned = match.group(1) # Return only the GRBL part

    return cleaned.strip()
