"""
GCode Proxy Service - High-level service management.

This module provides the GCodeProxyService class that combines the TCP server
and GCode device for a complete proxy service, using a task queue for communication.
"""

from gcode_proxy.core.logging import setup_logging, get_logger

from gcode_proxy.device import GCodeDevice, GrblDevice
from gcode_proxy.core.server import GCodeServer
# from gcode_proxy.core.task import TaskQueue, create_task_queue
from gcode_proxy.trigger import TriggerManager
from gcode_proxy.core.connection_manager import ConnectionManager


logger = get_logger()


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
    ):
        """
        Initialize the proxy service with an existing device.

        Args:
            device: The GCodeDevice instance to use for communication.
            address: Address to bind the server to.
            port: Port to listen on.
            trigger_manager: Optional TriggerManager for handling GCode triggers.
        """
        self.device = device
        self.trigger_manager = trigger_manager
        self.connection_manager = ConnectionManager()

        # Create the server with the device
        self.server = GCodeServer(
            device=self.device,
            address=address,
            port=port,
            trigger_manager=trigger_manager,
        )

    @classmethod
    def create_serial(
        cls,
        usb_id: str | None = None,
        dev_path: str | None = None,
        baud_rate: int = 115200,
        address: str = "0.0.0.0",
        port: int = 8080,
        serial_delay: float = 100.0,
        gcode_log_file: str | None = None,
        queue_limit: int = 50,
        liveness_period: float = 1000.0,
        swallow_realtime_ok: bool = True,
        status_behavior: str = "forward",
    ) -> "GCodeProxyService":
        """
        Create a proxy service with a serial GRBL device.

        This is a convenience factory method that creates the service
        with a GrblDevice for actual hardware communication.

        Args:
            usb_id: USB device ID in vendor:product format.
            dev_path: Device path like /dev/ttyACM0.
            baud_rate: Serial baud rate for the device.
            address: Address to bind the server to.
            port: Port to listen on.
            serial_delay: Delay in ms for device initialization after connection.
            gcode_log_file: Optional path to file for logging GCode communication.
            queue_limit: Maximum size of the command queue (default: 50).
            liveness_period: Period in ms for pinging device with `?` command.
            swallow_realtime_ok: Suppress 'ok' responses from `?` commands.
            status_behavior: Status query behavior ('liveness-cache' or 'forward').

        Returns:
            A configured GCodeProxyService instance.
        """
        # Configure the GCode file logger if requested
        if gcode_log_file:
            setup_logging(gcode_log_file=gcode_log_file)

        device = GrblDevice(
            usb_id=usb_id,
            dev_path=dev_path,
            baud_rate=baud_rate,
            queue_size=queue_limit,
            initialization_delay=serial_delay,
            liveness_period=liveness_period,
            swallow_realtime_ok=swallow_realtime_ok,
            status_behavior=status_behavior,
        )
        return cls(
            device=device,
            address=address,
            port=port,
        )

    @classmethod
    def create_dry_run(
        cls,
        address: str = "0.0.0.0",
        port: int = 8080,
        gcode_log_file: str | None = None,
        queue_limit: int = 1000,
    ) -> "GCodeProxyService":
        """
        Create a proxy service with a dry-run device.

        This is a convenience factory method that creates the service
        with a base GCodeDevice for testing without actual hardware.

        Args:
            address: Address to bind the server to.
            port: Port to listen on.
            gcode_log_file: Optional path to file for logging GCode communication.
            queue_limit: Maximum size of the command queue (default: 50).

        Returns:
            A configured GCodeProxyService instance.
        """
        # Configure the GCode file logger if requested
        if gcode_log_file:
            setup_logging(gcode_log_file=gcode_log_file)

        device = GCodeDevice(
            queue_size=queue_limit,
        )
        return cls(
            device=device,
            address=address,
            port=port,
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
            await self.connection_manager.start()

            # Start and run the server
            await self.server.serve_forever()

        finally:
            # Clean up
            await self.server.stop()
            await self.connection_manager.stop()
            await self.device.disconnect()

    async def start(self) -> None:
        """
        Start the service without blocking.

        Use this when you want to run the service in the background.
        """
        await self.device.connect()
        await self.connection_manager.start()
        await self.server.start()

    async def stop(self) -> None:
        """Stop the service."""
        await self.server.stop()
        await self.connection_manager.stop()
        await self.device.disconnect()

    async def __aenter__(self) -> "GCodeProxyService":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
