"""
Task Queue for GCode Proxy.

This module provides the Task class and TaskQueue for managing GCode commands
from multiple TCP clients, ensuring sequential execution on the serial device.
"""

import asyncio
from dataclasses import dataclass

from .connection_manager import ConnectionManager
from gcode_proxy.core.logging import get_logger

logger = get_logger()

@dataclass
class Task:
    """
    Encapsulates a GCode command and the TCP client to respond to.

    Attributes:
        client_uuid: UUID of the client connection.
        should_respond: Whether a response should be sent back to the client.
    """
    client_uuid: str | None
    should_respond: bool = True
    char_count: int = 0

    def send_response(self, response: str, broadcast=False) -> None:
        """
        Queue a response to be sent back to the client. Non-blocking

        Args:
            response: The response string from the device.
        """
        try:
            ConnectionManager().communicate(response, None if broadcast else self.client_uuid)
        except Exception as e:
            logger.error(f"Failed to queue response to client {self.client_uuid}: {e}")

    def get_client_address(self) -> str:
        """
        Get the address string of the client associated with this task.
        """
        if self.client_uuid:
            return ConnectionManager().get_client_address_str(self.client_uuid)

        return "unknown:0"

@dataclass
class GCodeTask(Task):
    """
    A Task specifically for GCode commands.

    Attributes:
        gcode: The GCode command string to execute.
        char_count: Number of characters in the gcode (including newline).
                   Calculated automatically during initialization.
    """

    gcode: str = ""

    def __post_init__(self) -> None:
        """
        Post-initialization hook to ensure gcode ends with newline
        and calculate char_count.
        """
        # Ensure gcode ends with newline
        if self.gcode and not self.gcode.endswith("\n"):
            self.gcode += "\n"

        # Calculate character count (including newline)
        self.char_count = len(self.gcode)

@dataclass
class ShellTask(Task):
    """
    A Task specifically for shell commands.

    Attributes:
        id: Identifier for the task.
        command: The shell command string to execute.
    """

    id: str = ""
    command: str = ""

    async def execute(self) -> tuple[bool, str | None]:
        """
        Execute the task's command asynchronously.

        The command is executed as a subprocess without blocking.

        Returns:
            Tuple of (success: bool, error_message: str | None).
            If successful, error_message is None.
            If failed, error_message contains the stderr output.
        """
        try:
            logger.info(f"Executing Task '{self.id}': {self.command}")

            # Execute the command as a subprocess
            process = await asyncio.create_subprocess_shell(
                self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for the process to complete
            stdout, stderr = await process.communicate()

            # Check the return code
            if process.returncode == 0:
                logger.debug(
                    f"Task '{self.id}' executed successfully "
                    f"(exit code: {process.returncode})"
                )
                return True, None
            else:
                stderr_str = stderr.decode('utf-8', errors='replace').strip()
                logger.error(
                    f"Task '{self.id}' failed with exit code {process.returncode}: "
                    f"{stderr_str}"
                )
                return False, stderr_str

        except Exception as e:
            logger.error(f"Task '{self.id}' execution error: {e}")
            return False, str(e)

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
