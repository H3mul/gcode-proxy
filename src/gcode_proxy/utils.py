"""
Utility functions for GCode Proxy.

This module provides utility functions for serial device discovery and communication.
"""

import logging

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
            f"Invalid USB ID format '{usb_id}'. Expected format: 'vendor:product' (e.g., '303a:4001')"
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