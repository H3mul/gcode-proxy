"""
GCode Device - Base class for device implementations.

This module provides the GCodeDevice base class which defines the interface
for device implementations. It manages task queueing and connection state,
providing the minimal API needed by the server.

Subclasses should implement actual hardware communication or dry-run logic.
"""

from gcode_proxy.core.logging import get_logger
from gcode_proxy.core.task import create_task_queue, Task

logger = get_logger()


class GCodeDevice:
    """
    Base class for GCode device implementations.

    This class provides the minimal interface needed by the server:
    - Task queueing (do_task, queue management)
    - Connection state management (is_connected, connect, disconnect)

    Subclasses should override connect(), disconnect(), and handle task
    processing appropriately for their use case (dry-run, serial, etc).
    """

    def __init__(
        self,
        queue_size: int = 50,
    ):
        """
        Initialize the GCode device.

        Args:
            queue_size: Maximum number of commands allowed in the queue.
            response_timeout: Timeout in seconds for waiting for device response.
        """
        self.task_queue = create_task_queue(maxsize=queue_size)

        self._connected = False

    async def do_task(self, task: "Task") -> None:
        """
        Process a task by queueing it for processing.

        Args:
            task: The task to process.
        """
        logger.debug(f"Received task: {repr(task)}")
        await self.task_queue.put(task)

    def clear_queue(self) -> None:
        """Clear all pending tasks from the queue."""
        from gcode_proxy.core.task import empty_queue
        empty_queue(self.task_queue)

    def queue_size(self) -> int:
        """Get the current size of the task queue."""
        return self.task_queue.qsize()

    def queue_full(self) -> bool:
        """Check if the task queue is full."""
        return self.task_queue.full()

    def queue_maxsize(self) -> int:
        """Get the maximum size of the task queue."""
        return self.task_queue.maxsize

    @property
    def is_connected(self) -> bool:
        """Check if the device is connected."""
        return self._connected

    async def connect(self) -> None:
        """
        Connect to the device.

        Subclasses should override this to implement actual connection logic.
        """
        if self._connected:
            logger.warning("Already connected to device")
            return

        self._connected = True
        logger.info("Connected to device")

    async def disconnect(self) -> None:
        """
        Disconnect from the device.

        Subclasses should override this to implement actual disconnection logic.
        """
        if self._connected:
            self._connected = False
            logger.info("Disconnected from device")

    async def __aenter__(self) -> "GCodeDevice":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
