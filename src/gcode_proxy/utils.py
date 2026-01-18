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


# Response terminators that indicate end of device response
RESPONSE_TERMINATORS = ("ok", "error", "!!")

def normalize_response_terminators(
    data: str,
    terminators: tuple[str, ...],
) -> str:
    """
    Normalize response data by ensuring all terminators are on separate lines.

    Scans through the entire data buffer and identifies terminators that are stuck
    at the end of content lines due to serial corruption (e.g., "gpio_install_isrok\r\r\n"
    where "ok" should be on its own line). Inserts newlines to separate them.

    Args:
        data: The response data string to process.
        terminators: Tuple of valid terminators (e.g., ("ok", "error", "!!")).

    Returns:
        The normalized data with all terminators on their own lines.

    Example:
        >>> normalize_response_terminators(
        ...     "gpio_install_isrok\nok\nerror_msg\nerror",
        ...     ("ok", "error", "!!")
        ... )
        "gpio_install_isrok\nok\nerror_msg\nerror"

        >>> normalize_response_terminators(
        ...     "response dataok",
        ...     ("ok", "error", "!!")
        ... )
        "response data\nok"
    """
    # Build case-insensitive regex pattern for terminators at line end
    # Matches: any content (non-newline) + optional whitespace + terminator + optional \r
    terminators_pattern = "|".join(re.escape(t) for t in terminators)
    pattern = rf"^([^\r\n]*?)\s*({terminators_pattern})(\r?)$"

    lines = data.split("\n")
    result_lines = []

    for line in lines:
        match = re.match(pattern, line, re.IGNORECASE)
        if match:
            prefix = match.group(1).strip()
            terminator = match.group(2)
            carriage_return = match.group(3)

            # Only separate if there's actual content before the terminator
            # and that content isn't just another terminator
            if prefix and prefix.lower() not in terminators:
                result_lines.append(prefix)
                result_lines.append(terminator + carriage_return)
            else:
                # Line is just a terminator or empty, keep as is
                result_lines.append(line)
        else:
            # Regular line without terminator at end, keep as is
            result_lines.append(line)

    return "\n".join(result_lines)
