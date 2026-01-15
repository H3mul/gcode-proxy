"""Trigger manager for executing GCode-triggered external commands.

The TriggerManager implements the GCodeHandler interface and manages a list
of triggers that match incoming GCode commands and execute external commands
in response.
"""

import asyncio
import logging
from collections.abc import Sequence

from .handlers import GCodeHandler
from .trigger import Trigger
from .triggers_config import CustomTriggerConfig


logger = logging.getLogger(__name__)


class TriggerManager(GCodeHandler):
    """
    Manages a list of GCode triggers and executes them when GCode matches.
    
    This class implements the GCodeHandler interface, allowing it to be passed
    to GCodeSerialDevice to intercept GCode commands and execute triggers
    when patterns match.
    """
    
    def __init__(self, trigger_configs: Sequence[CustomTriggerConfig] | None = None):
        """
        Initialize the trigger manager with a list of trigger configurations.
        
        Args:
            trigger_configs: Sequence of CustomTriggerConfig instances.
                           If None, initializes with an empty list.
            
        Raises:
            ValueError: If any trigger configuration is invalid.
        """
        self.triggers: list[Trigger] = []
        self._pending_tasks: set[asyncio.Task] = set()
        
        if trigger_configs:
            for config in trigger_configs:
                try:
                    trigger = Trigger(config)
                    self.triggers.append(trigger)
                    logger.info(f"Loaded trigger '{config.id}': {config.trigger.match}")
                except ValueError as e:
                    logger.error(f"Failed to load trigger: {e}")
                    raise
    
    async def on_gcode_received(
        self, gcode: str, client_address: tuple[str, int]
    ) -> str:
        """
        Called when a GCode command is received from a TCP client.
        
        Checks all registered triggers and spawns background tasks for
        any that match the GCode pattern.
        
        Args:
            gcode: The raw GCode command string received.
            client_address: Tuple of (host, port) identifying the client.
            
        Returns:
            The GCode unchanged (pass-through).
        """
        # Check each trigger for a match
        for trigger in self.triggers:
            if trigger.matches(gcode):
                # Spawn a background task for execution
                task = asyncio.create_task(trigger.execute())
                self._pending_tasks.add(task)
                
                # Remove the task from the set when it's done
                def _task_done_callback(t):
                    self._pending_tasks.discard(t)
                
                task.add_done_callback(_task_done_callback)
        
        # Always return the gcode unchanged
        return gcode
    
    async def on_gcode_sent(
        self, gcode: str, client_address: tuple[str, int]
    ) -> None:
        """
        Called after a GCode command has been sent to the serial device.
        
        This is a no-op for the trigger manager.
        
        Args:
            gcode: The GCode command that was sent.
            client_address: Tuple of (host, port) identifying the client.
        """
        pass
    
    async def shutdown(self) -> None:
        """
        Wait for all pending trigger tasks to complete.
        
        Call this during graceful shutdown to ensure all spawned
        commands are allowed to finish.
        """
        if self._pending_tasks:
            logger.info(
                f"Waiting for {len(self._pending_tasks)} pending trigger tasks..."
            )
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            logger.info("All pending trigger tasks completed")
