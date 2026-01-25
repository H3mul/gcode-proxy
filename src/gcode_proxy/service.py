"""
GCode Proxy Service - High-level service management.

This module provides the GCodeProxyService class that combines the TCP server
and GCode device for a complete proxy service, using a task queue for communication.
"""

import logging
from .logging import setup_logging

from .device import GCodeDevice, GCodeSerialDevice
from .handlers import GCodeHandler, ResponseHandler
from .server import GCodeServer
# from .task_queue import TaskQueue, create_task_queue
from .trigger_manager import TriggerManager


logger = logging.getLogger(__name__)


class GCodeProxyService:
    """
    High-level service combining the TCP server and GCode device.
    
    This class provides a convenient interface for running the complete
    proxy service with proper lifecycle management. It creates a task queue
    that serves as the communication bridge between the server and device.
    """
    
    def __init__(
        self,
        device: GCodeDevice,
        address: str = "0.0.0.0",
        port: int = 8080,
        trigger_manager: TriggerManager | None = None,
        response_timeout: float = 30.0,
        normalize_grbl_responses: bool = True,
    ):
        """
        Initialize the proxy service with an existing device.
        
        Args:
            device: The GCodeDevice instance to use for communication.
            address: Address to bind the server to.
            port: Port to listen on.
            trigger_manager: Optional TriggerManager for handling GCode triggers.
            response_timeout: Timeout in seconds for waiting for device response (default: 30.0).
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).
        """
        self.device = device
        self.trigger_manager = trigger_manager
        
        # Create the server with the device
        self.server = GCodeServer(
            device=self.device,
            address=address,
            port=port,
            response_timeout=response_timeout,
            normalize_grbl_responses=normalize_grbl_responses,
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
        queue_limit: int = 50,
        response_timeout: float = 30.0,
        normalize_grbl_responses: bool = True,
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
            queue_limit: Maximum size of the command queue (default: 50).
            response_timeout: Timeout in seconds for waiting for device response (default: 30.0).
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).
            
        Returns:
            A configured GCodeProxyService instance.
        """
        # Configure the GCode file logger if requested
        if gcode_log_file:
            setup_logging(gcode_log_file=gcode_log_file)
        
        device = GCodeSerialDevice(
            usb_id=usb_id,
            dev_path=dev_path,
            baud_rate=baud_rate,
            queue_size=queue_limit,
            initialization_delay=serial_delay,
            gcode_handler=gcode_handler,
            response_handler=response_handler,
            response_timeout=response_timeout,
            normalize_grbl_responses=normalize_grbl_responses,
        )
        return cls(
            device=device,
            address=address,
            port=port,
            response_timeout=response_timeout,
            normalize_grbl_responses=normalize_grbl_responses,
        )
    
    @classmethod
    def create_dry_run(
        cls,
        address: str = "0.0.0.0",
        port: int = 8080,
        gcode_handler: GCodeHandler | None = None,
        response_handler: ResponseHandler | None = None,
        gcode_log_file: str | None = None,
        queue_limit: int = 50,
        response_timeout: float = 30.0,
        normalize_grbl_responses: bool = True,
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
            queue_limit: Maximum size of the command queue (default: 50).
            response_timeout: Timeout in seconds for waiting for device response (default: 30.0).
            normalize_grbl_responses: Whether to normalize GRBL
                responses (default: True).
            
        Returns:
            A configured GCodeProxyService instance.
        """
        # Configure the GCode file logger if requested
        if gcode_log_file:
            setup_logging(gcode_log_file=gcode_log_file)
        
        device = GCodeDevice(
            queue_size=queue_limit,
            gcode_handler=gcode_handler,
            response_handler=response_handler,
            response_timeout=response_timeout,
            normalize_grbl_responses=normalize_grbl_responses,
        )
        return cls(
            device=device,
            address=address,
            port=port,
            response_timeout=response_timeout,
            normalize_grbl_responses=normalize_grbl_responses,
        )
    
    async def run(self) -> None:
        """
        Run the proxy service.
        
        Connects to the device and starts the TCP server.
        Runs until interrupted.
        """
        try:
            # Connect to the device (this starts the task processing loop)
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
        
        # Wait for any pending trigger tasks
        if self.trigger_manager:
            await self.trigger_manager.shutdown()
    
    async def __aenter__(self) -> "GCodeProxyService":
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
