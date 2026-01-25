"""
Task Queue for GCode Proxy.

This module provides the Task class and TaskQueue for managing GCode commands
from multiple TCP clients, ensuring sequential execution on the serial device.
"""

import asyncio
import logging
from dataclasses import dataclass




logger = logging.getLogger(__name__)


@dataclass
class Task:
    """
    Encapsulates a GCode command and the TCP client to respond to.

    Attributes:
        command: The GCode command string to execute.
        client_uuid: UUID of the client connection.
        wait_response: Whether to wait for device confirmation.
        response_future: Future that will be set with the response when available.
    """
    command: str
    client_uuid: str
    queue_task: bool = True
    wait_response: bool = True

    def send_response(self, response: str, broadcast=False) -> None:
        """
        Set the response for this task.

        Args:
            response: The response string from the device.
        """
        from .connection_manager import ConnectionManager

        try:
            ConnectionManager().communicate(response, None if broadcast else self.client_uuid)
        except Exception as e:
            logger.error(f"Failed to queue response to client {self.client_uuid}: {e}")

# Type alias for the task queue
TaskQueue = asyncio.Queue[Task]


def create_task_queue(maxsize: int = 0) -> TaskQueue:
    """
    Create a new task queue.

    Args:
        maxsize: Maximum size of the queue (0 for unlimited).

    Returns:
        A new TaskQueue instance.
    """
    return asyncio.Queue(maxsize=maxsize)

def empty_queue(q: TaskQueue):
    while not q.empty():
        try:
            q.get_nowait()
            q.task_done()
        except asyncio.QueueEmpty:
            break
