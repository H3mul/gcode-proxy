"""
Task Queue for GCode Proxy.

This module provides the Task class and TaskQueue for managing GCode commands
from multiple TCP clients, ensuring sequential execution on the serial device.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import StreamWriter


logger = logging.getLogger(__name__)


@dataclass
class Task:
    """
    Encapsulates a GCode command and the TCP client to respond to.
    
    Attributes:
        command: The GCode command string to execute.
        client_address: Tuple of (host, port) identifying the client.
        writer: The StreamWriter to send the response back to the client.
        response_future: Future that will be set with the response when available.
    """
    command: str
    client_address: tuple[str, int]
    writer: "StreamWriter"
    response_future: asyncio.Future[str] = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )
    
    def set_response(self, response: str) -> None:
        """
        Set the response for this task.
        
        Args:
            response: The response string from the device.
        """
        if not self.response_future.done():
            self.response_future.set_result(response)
    
    def set_error(self, error: Exception) -> None:
        """
        Set an error for this task.
        
        Args:
            error: The exception that occurred.
        """
        if not self.response_future.done():
            self.response_future.set_exception(error)
    
    async def wait_for_response(self, timeout: float | None = None) -> str:
        """
        Wait for the response to be available.
        
        Args:
            timeout: Optional timeout in seconds.
            
        Returns:
            The response string from the device.
            
        Raises:
            asyncio.TimeoutError: If the timeout is exceeded.
        """
        if timeout is not None:
            return await asyncio.wait_for(self.response_future, timeout=timeout)
        return await self.response_future
    
    async def send_response_to_client(self, response: str) -> None:
        """
        Send the response back to the TCP client.
        
        Args:
            response: The response string to send.
        """
        try:
            response_data = response + "\n" if not response.endswith("\n") else response
            self.writer.write(response_data.encode("utf-8"))
            await self.writer.drain()
        except Exception as e:
            logger.error(f"Failed to send response to client {self.client_address}: {e}")


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
