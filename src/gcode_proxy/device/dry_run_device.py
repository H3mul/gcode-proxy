"""
Dry-Run Device - Device implementation for testing without hardware.

This module provides the DryRunDevice class which implements a dry-run mode
for testing GCode commands without actual hardware communication. It logs
all commands but doesn't send them to any device.
"""

import asyncio

from gcode_proxy.core.logging import get_logger
from gcode_proxy.core.task import GCodeTask, ShellTask, Task
from gcode_proxy.device.device import GCodeDevice

logger = get_logger()


class DryRunDevice(GCodeDevice):
    """
    GCode device for dry-run testing without hardware communication.

    This implementation provides dummy send/receive operations that log
    commands but don't actually communicate with any hardware. It's useful
    for testing the server and task processing logic without a physical
    device connected.

    All commands are logged but not sent anywhere. Tasks are processed
    immediately with 'ok' responses.
    """

    def __init__(
        self,
        queue_size: int = 50,
    ):
        """
        Initialize the dry-run device.

        Args:
            queue_size: Maximum number of commands allowed in the queue.
        """
        super().__init__(
            queue_size=queue_size,
        )
        self._task_loop_task: asyncio.Task | None = None
        self._running = False

    async def connect(self) -> None:
        """
        Connect to the dry-run device.

        This starts the task processing loop without any actual hardware communication.
        """
        if self._connected:
            logger.warning("Already connected to device")
            return

        self._connected = True
        logger.info("Connected to dry-run device (no actual hardware)")

        # Start the task processing loop
        self._running = True
        self._task_loop_task = asyncio.create_task(self._task_loop())

    async def disconnect(self) -> None:
        """Disconnect from the dry-run device."""
        self._running = False

        # Cancel the task loop
        if self._task_loop_task:
            self._task_loop_task.cancel()
            try:
                await self._task_loop_task
            except asyncio.CancelledError:
                pass
            self._task_loop_task = None

        if self._connected:
            self._connected = False
            logger.info("Disconnected from dry-run device")

    async def _task_loop(self) -> None:
        """
        Main loop that processes tasks from the queue.

        Continuously awaits tasks from the queue and processes them.
        """
        if not self.task_queue:
            logger.error("No task queue set for device")
            return

        logger.info("Device task loop started")

        try:
            while self._running:
                try:
                    # Wait for a task from the queue
                    task = await self.task_queue.get()

                    try:
                        # Process the task
                        await self._process_task(task)
                    except Exception as e:
                        logger.error(f"Error processing task: {e}")
                        task.send_response(f"error: {e}")
                    finally:
                        # Mark task as done
                        self.task_queue.task_done()

                except Exception as e:
                    logger.error(f"Error in task loop: {e}")

        except asyncio.CancelledError:
            logger.info("Device task loop stopped")

    async def _process_task(self, task: Task) -> None:
        """
        Process a single task in dry-run mode.

        All tasks are logged but not sent to any hardware. Responses are
        sent immediately with 'ok'.

        Args:
            task: The task to process (GCodeTask or ShellTask).
        """
        # Log the task
        if isinstance(task, GCodeTask):
            await self._send(task.gcode)
        elif isinstance(task, ShellTask):
            logger.debug(f"[DRY-RUN] Would execute shell: {task.command}")
        else:
            logger.warning(f"Unknown task type: {type(task)}")

        # Send response if required
        if task.should_respond:
            task.send_response("ok")

    async def _send(self, gcode: str) -> None:
        """
        Log a GCode command without sending it anywhere.

        Args:
            gcode: The GCode command to log.
        """
        logger.debug(f"[DRY-RUN] Would send: {gcode.strip()}")
