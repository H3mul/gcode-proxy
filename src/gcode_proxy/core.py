"""
Core GCode Proxy functionality.

This module provides the core logic for proxying GCode commands between
TCP clients and USB serial devices using non-blocking async operations.
"""

import asyncio
import logging
from typing import Callable, Awaitable

import serial
import serial.tools.list_ports
from serial_asyncio import open_serial_connection

from .handlers import (
    GCodeHandler,
    ResponseHandler,
    DefaultGCodeHandler,
    DefaultResponseHandler,
)


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


class GCodeProxy:
    """
    Core GCode proxy that handles communication between TCP clients and serial devices.
    
    This class manages the serial connection and provides methods for sending
    GCode commands and receiving responses using non-blocking async operations.
    """
    
    def __init__(
        self,
        usb_id: str,
        baud_rate: int = 115200,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        response_timeout: float = 5.0,
        read_buffer_size: int = 4096,
    ):
        """
        Initialize the GCode proxy.
        
        Args:
            usb_id: USB device ID in vendor:product format.
            baud_rate: Serial baud rate for communication.
            gcode_handler: Custom handler for GCode commands.
            response_handler: Custom handler for serial responses.
            response_timeout: Timeout in seconds for waiting for device response.
            read_buffer_size: Size of the read buffer for serial communication.
        """
        self.usb_id = usb_id
        self.baud_rate = baud_rate
        self.gcode_handler = gcode_handler or DefaultGCodeHandler()
        self.response_handler = response_handler or DefaultResponseHandler()
        self.response_timeout = response_timeout
        self.read_buffer_size = read_buffer_size
        
        self._serial_port: str | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        """Check if the proxy is connected to the serial device."""
        return self._connected and self._writer is not None
    
    async def connect(self) -> None:
        """
        Connect to the USB serial device.
        
        Raises:
            SerialDeviceNotFoundError: If the device cannot be found.
            SerialConnectionError: If the connection fails.
        """
        if self._connected:
            logger.warning("Already connected to serial device")
            return
        
        # Find the serial port for the USB device
        self._serial_port = find_serial_port_by_usb_id(self.usb_id)
        
        try:
            self._reader, self._writer = await open_serial_connection(
                url=self._serial_port,
                baudrate=self.baud_rate,
            )
            self._connected = True
            logger.info(f"Connected to {self._serial_port} at {self.baud_rate} baud")
            
            # Give the device a moment to initialize
            await asyncio.sleep(0.1)
            
            # Flush any startup messages from the device
            await self._flush_input()
            
        except serial.SerialException as e:
            raise SerialConnectionError(
                f"Failed to connect to {self._serial_port}: {e}"
            ) from e
    
    async def disconnect(self) -> None:
        """Disconnect from the serial device."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                logger.warning(f"Error closing serial connection: {e}")
            finally:
                self._writer = None
                self._reader = None
                self._connected = False
                logger.info("Disconnected from serial device")
    
    async def _flush_input(self) -> None:
        """Flush any pending input from the serial device."""
        if not self._reader:
            return
        
        try:
            # Read any available data with a very short timeout
            while True:
                try:
                    await asyncio.wait_for(
                        self._reader.read(self.read_buffer_size),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    break
        except Exception as e:
            logger.debug(f"Error flushing input: {e}")
    
    async def send_gcode(
        self,
        gcode: str,
        client_address: tuple[str, int] = ("unknown", 0),
    ) -> str:
        """
        Send a GCode command to the serial device and wait for a response.
        
        This method is thread-safe and uses a lock to ensure only one
        command is processed at a time.
        
        Args:
            gcode: The GCode command to send.
            client_address: The client address for handler callbacks.
            
        Returns:
            The response from the device.
            
        Raises:
            SerialConnectionError: If not connected or communication fails.
        """
        if not self.is_connected:
            raise SerialConnectionError("Not connected to serial device")
        
        async with self._lock:
            return await self._send_gcode_unlocked(gcode, client_address)
    
    async def _send_gcode_unlocked(
        self,
        gcode: str,
        client_address: tuple[str, int],
    ) -> str:
        """
        Internal method to send GCode without acquiring the lock.
        
        Args:
            gcode: The GCode command to send.
            client_address: The client address for handler callbacks.
            
        Returns:
            The response from the device.
        """
        # Process through handler
        processed_gcode = await self.gcode_handler.on_gcode_received(
            gcode, client_address
        )
        
        # Ensure the command ends with a newline
        if not processed_gcode.endswith("\n"):
            processed_gcode += "\n"
        
        try:
            # Send the command
            self._writer.write(processed_gcode.encode("utf-8"))
            await self._writer.drain()
            
            logger.debug(f"Sent: {processed_gcode.strip()}")
            
            # Notify handler that command was sent
            await self.gcode_handler.on_gcode_sent(processed_gcode, client_address)
            
            # Wait for and collect response
            response = await self._read_response()
            
            # Process response through handler
            processed_response = await self.response_handler.on_response_received(
                response, gcode, client_address
            )
            
            # Notify handler that response was sent
            await self.response_handler.on_response_sent(processed_response, client_address)
            
            return processed_response
            
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response to: {gcode.strip()}")
            return ""
        except Exception as e:
            logger.error(f"Error sending GCode: {e}")
            raise SerialConnectionError(f"Failed to send GCode: {e}") from e
    
    async def _read_response(self) -> str:
        """
        Read a response from the serial device.
        
        Reads until we get an 'ok' or error response, or until timeout.
        
        Returns:
            The complete response string.
        """
        if not self._reader:
            return ""
        
        response_lines: list[str] = []
        
        try:
            while True:
                line = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=self.response_timeout
                )
                
                if not line:
                    break
                
                decoded_line = line.decode("utf-8", errors="replace").strip()
                logger.debug(f"Received: {decoded_line}")
                response_lines.append(decoded_line)
                
                # Check for common response terminators
                # Most GCode devices respond with "ok" when ready for next command
                lower_line = decoded_line.lower()
                if (lower_line.startswith("ok") or 
                    lower_line.startswith("error") or
                    lower_line.startswith("!!")):  # Marlin fatal error
                    break
                    
        except asyncio.TimeoutError:
            if not response_lines:
                logger.debug("No response received within timeout")
        
        return "\n".join(response_lines)
    
    async def send_multiple(
        self,
        gcodes: list[str],
        client_address: tuple[str, int] = ("unknown", 0),
    ) -> list[str]:
        """
        Send multiple GCode commands sequentially.
        
        Args:
            gcodes: List of GCode commands to send.
            client_address: The client address for handler callbacks.
            
        Returns:
            List of responses, one per command.
        """
        responses = []
        for gcode in gcodes:
            if gcode.strip():  # Skip empty lines
                response = await self.send_gcode(gcode, client_address)
                responses.append(response)
        return responses
    
    async def __aenter__(self) -> "GCodeProxy":
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()