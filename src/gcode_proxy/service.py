"""
GCode Proxy Service - High-level service management.

This module provides the GCodeProxyService class that combines the TCP server
and GCode device for a complete proxy service.
"""

import logging

from .device import GCodeDevice, GCodeSerialDevice
from .handlers import GCodeHandler, ResponseHandler
from .server import GCodeServer


logger = logging.getLogger(__name__)


class GCodeProxyService:
    """
    High-level service combining the TCP server and GCode device.
    
    This class provides a convenient interface for running the complete
    proxy service with proper lifecycle management.
    """
    
    def __init__(
        self,
        device: GCodeDevice,
        address: str = "0.0.0.0",
        port: int = 8080,
    ):
        """
        Initialize the proxy service with an existing device.
        
        Args:
            device: The GCodeDevice instance to use for communication.
            address: Address to bind the server to.
            port: Port to listen on.
        """
        self.device = device
        self.server = GCodeServer(
            device=self.device,
            address=address,
            port=port,
        )
    
    @classmethod
    def create_serial(
        cls,
        usb_id: str | None = None,
        dev_path: str | None = None,
        baud_rate: int = 115200,
        address: str = "0.0.0.0",
        port: int = 8080,
        serial_delay: float = 0.1,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        gcode_log_file: str | None = None,
    ) -> "GCodeProxyService":
        """
        Create a proxy service with a serial device.
        
        This is a convenience factory method that creates the service
        with a GCodeSerialDevice for actual hardware communication.
        
        Args:
            usb_id: USB device ID in vendor:product format (mutually exclusive with dev_path).
            dev_path: Device path like /dev/ttyACM0 (mutually exclusive with usb_id).
            baud_rate: Serial baud rate for the device.
            address: Address to bind the server to.
            port: Port to listen on.
            serial_delay: Delay in seconds for device initialization after connection.
            gcode_handler: Optional custom GCode handler.
            response_handler: Optional custom response handler.
            gcode_log_file: Optional path to file for logging GCode communication.
            
        Returns:
            A configured GCodeProxyService instance.
        """
        device = GCodeSerialDevice(
            usb_id=usb_id,
            dev_path=dev_path,
            baud_rate=baud_rate,
            initialization_delay=serial_delay,
            gcode_handler=gcode_handler,
            response_handler=response_handler,
            gcode_log_file=gcode_log_file,
        )
        return cls(device=device, address=address, port=port)
    
    @classmethod
    def create_dry_run(
        cls,
        address: str = "0.0.0.0",
        port: int = 8080,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        gcode_log_file: str | None = None,
    ) -> "GCodeProxyService":
        """
        Create a proxy service with a dry-run device.
        
        This is a convenience factory method that creates the service
        with a base GCodeDevice for testing without actual hardware.
        
        Args:
            address: Address to bind the server to.
            port: Port to listen on.
            gcode_handler: Optional custom GCode handler.
            response_handler: Optional custom response handler.
            gcode_log_file: Optional path to file for logging GCode communication.
            
        Returns:
            A configured GCodeProxyService instance.
        """
        device = GCodeDevice(
            gcode_handler=gcode_handler,
            response_handler=response_handler,
            gcode_log_file=gcode_log_file,
        )
        return cls(device=device, address=address, port=port)
    
    async def run(self) -> None:
        """
        Run the proxy service.
        
        Connects to the device and starts the TCP server.
        Runs until interrupted.
        """
        try:
            # Connect to the device
            await self.device.connect()
            
            # Start and run the server
            await self.server.serve_forever()
            
        finally:
            # Clean up
            await self.server.stop()
            await self.device.disconnect()
    
    async def start(self) -> None:
        """
        Start the service without blocking.
        
        Use this when you want to run the service in the background.
        """
        await self.device.connect()
        await self.server.start()
    
    async def stop(self) -> None:
        """Stop the service."""
        await self.server.stop()
        await self.device.disconnect()
    
    async def __aenter__(self) -> "GCodeProxyService":
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
