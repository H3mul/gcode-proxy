"""
GCode Device - Serial communication with USB devices.

This module provides the GCodeDevice class for managing serial connections
and communication with USB-connected devices using non-blocking async operations.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from .handlers import (
    GCodeHandler,
    ResponseHandler,
    DefaultGCodeHandler,
    DefaultResponseHandler,
)
from .utils import SerialConnectionError, find_serial_port_by_usb_id


logger = logging.getLogger(__name__)


class GCodeDevice:
    """
    Base GCode device class that can be used for dry-run testing.
    
    This class provides dummy send/receive operations that log commands
    but don't actually communicate with any hardware. Subclass this
    and override _send() and _receive() for actual device communication.
    """
    
    def __init__(
        self,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        response_timeout: float = 5.0,
        gcode_log_file: str | None = None,
    ):
        """
        Initialize the GCode device.
        
        Args:
            gcode_handler: Custom handler for GCode commands.
            response_handler: Custom handler for serial responses.
            response_timeout: Timeout in seconds for waiting for device response.
            gcode_log_file: Optional path to file for logging GCode communication.
        """
        self.gcode_handler = gcode_handler or DefaultGCodeHandler()
        self.response_handler = response_handler or DefaultResponseHandler()
        self.response_timeout = response_timeout
        self.gcode_log_file = Path(gcode_log_file) if gcode_log_file else None
        
        self._lock = asyncio.Lock()
        self._connected = False
        self._log_lock = asyncio.Lock()
    
    @property
    def is_connected(self) -> bool:
        """Check if the device is connected."""
        return self._connected
    
    async def connect(self) -> None:
        """
        Connect to the device.
        
        For the base class (dry-run mode), this simply marks the device as connected.
        """
        if self._connected:
            logger.warning("Already connected to device")
            return
        
        self._connected = True
        logger.info("Connected to dry-run device (no actual hardware)")
        
        # Initialize log file if specified
        if self.gcode_log_file:
            await self._initialize_log_file()
    
    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._connected:
            self._connected = False
            logger.info("Disconnected from dry-run device")
    
    async def _send(self, gcode: str) -> None:
        """
        Send a GCode command to the device.
        
        Override this method in subclasses for actual hardware communication.
        
        Args:
            gcode: The GCode command to send (already has newline appended).
        """
        logger.debug(f"[DRY-RUN] Would send: {gcode.strip()}")
    
    async def _receive(self) -> str:
        """
        Receive a response from the device.
        
        Override this method in subclasses for actual hardware communication.
        
        Returns:
            The response string from the device.
        """
        logger.debug("[DRY-RUN] Returning simulated 'ok' response")
        return "ok"
    
    async def _initialize_log_file(self) -> None:
        """Initialize the GCode log file."""
        if not self.gcode_log_file:
            return
        
        try:
            # Create parent directories if needed
            self.gcode_log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Create the file if it doesn't exist
            if not self.gcode_log_file.exists():
                self.gcode_log_file.touch()
                logger.info(f"Created GCode log file: {self.gcode_log_file}")
        except Exception as e:
            logger.error(f"Failed to initialize log file {self.gcode_log_file}: {e}")
            self.gcode_log_file = None
    
    async def _log_gcode(self, gcode: str, source: str) -> None:
        """
        Log a GCode command or response to the log file.
        
        Args:
            gcode: The GCode command or response to log.
            source: The source (client address or device identifier).
        """
        if not self.gcode_log_file:
            return
        
        try:
            # Format: [timestamp][source]: message

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            log_entry = f"{timestamp} - {source}: {gcode.strip()}"
            
            async with self._log_lock:
                with open(self.gcode_log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry + "\n")
        except Exception as e:
            logger.error(f"Failed to write to GCode log file: {e}")
    
    async def send_gcode(
        self,
        gcode: str,
        client_address: tuple[str, int] = ("unknown", 0),
    ) -> str:
        """
        Send a GCode command to the device and wait for a response.
        
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
            raise SerialConnectionError("Not connected to device")
        
        async with self._lock:
            return await self._handle_gcode_unlocked(gcode, client_address)
    
    async def _handle_gcode_unlocked(
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
            await self._send(processed_gcode)
            
            logger.debug(f"Sent: {processed_gcode.strip()}")
            
            # Log the GCode command
            source_address = f"{client_address[0]}:{client_address[1]}"
            await self._log_gcode(processed_gcode, source_address)
            
            # Notify handler that command was sent
            await self.gcode_handler.on_gcode_sent(processed_gcode, client_address)
            
            # Wait for and collect response
            response = await self._receive()
            
            # Process response through handler
            processed_response = await self.response_handler.on_response_received(
                response, gcode, client_address
            )
            
            # Log the response
            await self._log_gcode(processed_response, "device")
            
            # Notify handler that response was sent
            await self.response_handler.on_response_sent(processed_response, client_address)
            
            return processed_response
            
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response to: {gcode.strip()}")
            return ""
        except Exception as e:
            logger.error(f"Error sending GCode: {e}")
            raise SerialConnectionError(f"Failed to send GCode: {e}") from e
    
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
    
    async def __aenter__(self) -> "GCodeDevice":
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()


class GCodeSerialDevice(GCodeDevice):
    """
    GCode device that communicates with USB serial devices.
    
    This class extends GCodeDevice with actual serial communication
    capabilities using pyserial and serial_asyncio.
    """
    
    # Import serial modules at class level to avoid requiring them for base class
    try:
        import serial as _serial_module
        from serial_asyncio import open_serial_connection as _open_serial_connection
    except ImportError:
        _serial_module = None  # type: ignore[assignment]
        _open_serial_connection = None  # type: ignore[assignment]
    
    def __init__(
        self,
        usb_id: str,
        baud_rate: int = 115200,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        response_timeout: float = 5.0,
        read_buffer_size: int = 4096,
        initialization_delay: float = 0.1,
        gcode_log_file: str | None = None,
    ):
        """
        Initialize the GCode serial device.
        
        Args:
            usb_id: USB device ID in vendor:product format.
            baud_rate: Serial baud rate for communication.
            gcode_handler: Custom handler for GCode commands.
            response_handler: Custom handler for serial responses.
            response_timeout: Timeout in seconds for waiting for device response.
            read_buffer_size: Size of the read buffer for serial communication.
            initialization_delay: Delay in seconds to allow device initialization after connection.
            gcode_log_file: Optional path to file for logging GCode communication.
        """
        super().__init__(
            gcode_handler=gcode_handler,
            response_handler=response_handler,
            response_timeout=response_timeout,
            gcode_log_file=gcode_log_file,
        )
        self.usb_id = usb_id
        self.baud_rate = baud_rate
        self.read_buffer_size = read_buffer_size
        self.initialization_delay = initialization_delay
        
        self._serial_port: str | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
    
    @property
    def is_connected(self) -> bool:
        """Check if the device is connected to the serial device."""
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
        
        if self._open_serial_connection is None:
            raise SerialConnectionError(
                "serial_asyncio module is not available. "
                "Install it with: pip install pyserial-asyncio"
            )
        
        try:
            self._reader, self._writer = await self._open_serial_connection(
                url=self._serial_port,
                baudrate=self.baud_rate,
            )
            self._connected = True
            logger.info(f"Connected to {self._serial_port} at {self.baud_rate} baud")
            
            # Give the device a moment to initialize
            await asyncio.sleep(self.initialization_delay)
            
            # Flush any startup messages from the device
            await self._flush_input()
            
        except Exception as e:
            # Catch serial exceptions without importing serial at module level
            if self._serial_module and isinstance(e, self._serial_module.SerialException):
                raise SerialConnectionError(
                    f"Failed to connect to {self._serial_port}: {e}"
                ) from e
            raise
    
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
    
    async def _send(self, gcode: str) -> None:
        """
        Send a GCode command to the serial device.
        
        Args:
            gcode: The GCode command to send (already has newline appended).
            
        Raises:
            SerialConnectionError: If the serial writer is not available.
        """
        if not self._writer:
            raise SerialConnectionError("Serial writer is not available")
        
        self._writer.write(gcode.encode("utf-8"))
        await self._writer.drain()
    
    async def _receive(self) -> str:
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
