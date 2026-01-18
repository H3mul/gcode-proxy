"""Trigger manager for executing GCode-triggered external commands.

The TriggerManager implements the GCodeHandler interface and manages a list
of triggers that match incoming GCode commands and execute external commands
in response. Different trigger behaviors control how commands are forwarded
and whether to wait for trigger completion.
"""

import asyncio
import logging
from collections.abc import Sequence

from .handlers import GCodeHandler
from .trigger import Trigger
from .triggers_config import CustomTriggerConfig, TriggerBehavior


logger = logging.getLogger(__name__)


class TriggerExecutionResult:
    """Result of a trigger execution with behavior-specific handling."""
    
    def __init__(self, behavior: TriggerBehavior, success: bool, error_msg: str | None = None):
        """
        Initialize trigger execution result.
        
        Args:
            behavior: The trigger behavior mode.
            success: Whether the trigger executed successfully.
            error_msg: Error message if trigger failed.
        """
        self.behavior = behavior
        self.success = success
        self.error_msg = error_msg
    
    def should_forward_gcode(self) -> bool:
        """Check if GCode should be forwarded to device."""
        return self.behavior == TriggerBehavior.FORWARD
    
    def should_wait(self) -> bool:
        """Check if we should wait for trigger execution."""
        return self.behavior in (TriggerBehavior.FORWARD, TriggerBehavior.CAPTURE)
    
    def get_fake_response(self) -> str:
        """Get the fake response to send to client for CAPTURE modes."""
        if self.success:
            return "ok"
        else:
            error_msg = self.error_msg or "trigger execution failed"
            return f"error: {error_msg}"


class TriggerManager(GCodeHandler):
    """
    Manages a list of GCode triggers and executes them when GCode matches.
    
    This class implements the GCodeHandler interface, allowing it to be passed
    to GCodeSerialDevice to intercept GCode commands and execute triggers
    when patterns match.
    
    Three execution behaviors are supported:
    - FORWARD: Execute async, send GCode to device, return device response
    - CAPTURE: Execute sync, don't send GCode, return fake response
    - CAPTURE_NOWAIT: Execute async, don't send GCode, return fake response immediately
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
                    logger.info(
                        f"Loaded trigger '{config.id}': {config.trigger.match} "
                        f"[behavior: {config.trigger.behavior.value}]"
                    )
                except ValueError as e:
                    logger.error(f"Failed to load trigger: {e}")
                    raise
    
    def find_matching_trigger(self, gcode: str) -> Trigger | None:
        """
        Find the first trigger that matches the given GCode.
        
        Args:
            gcode: The raw GCode command string.
            
        Returns:
            The first matching Trigger, or None if no triggers match.
        """
        for trigger in self.triggers:
            if trigger.matches(gcode):
                return trigger
        return None
    
    async def execute_trigger_with_behavior(
        self, trigger: Trigger
    ) -> TriggerExecutionResult:
        """
        Execute a trigger and return result based on its behavior.
        
        For CAPTURE and CAPTURE behaviors that need to wait, this will block
        until the trigger completes. For CAPTURE_NOWAIT, it spawns a background
        task and returns immediately.
        
        Args:
            trigger: The trigger to execute.
            
        Returns:
            TriggerExecutionResult containing execution status and behavior info.
        """
        if trigger.behavior == TriggerBehavior.CAPTURE_NOWAIT:
            # Spawn background task and return immediately
            task = asyncio.create_task(trigger.execute())
            self._pending_tasks.add(task)
            
            def _task_done_callback(t):
                self._pending_tasks.discard(t)
            
            task.add_done_callback(_task_done_callback)
            # Return success immediately without waiting
            return TriggerExecutionResult(
                behavior=trigger.behavior,
                success=True,
                error_msg=None
            )
        else:
            # For FORWARD and CAPTURE, wait for execution to complete
            success, error_msg = await trigger.execute()
            return TriggerExecutionResult(
                behavior=trigger.behavior,
                success=success,
                error_msg=error_msg
            )
    
    async def on_gcode(
        self, gcode: str, client_address: tuple[str, int]
    ) -> dict[str, object] | None:
        """
        Called when a GCode command is received from a TCP client.
        
        Checks all registered triggers and handles execution based on behavior.
        Returns a dictionary with execution metadata that the device can use
        to determine how to process the GCode.
        
        Args:
            gcode: The raw GCode command string received.
            client_address: Tuple of (host, port) identifying the client.
            
        Returns:
            Dictionary with keys:
            - 'triggered': bool - Whether a trigger matched
            - 'should_forward': bool - Whether to send GCode to device
            - 'fake_response': str | None - Response to return for CAPTURE modes
            - 'behavior': TriggerBehavior - The behavior mode used
        """
        # Find matching trigger
        trigger = self.find_matching_trigger(gcode)
        
        if trigger is None:
            # No trigger matched, pass through normally
            return {
                "triggered": False,
                "should_forward": True,
                "fake_response": None,
                "behavior": None,
            }
        
        logger.debug(
            f"Trigger '{trigger.id}' matched GCode: {gcode.strip()}"
        )
        
        # Execute the trigger
        result = await self.execute_trigger_with_behavior(trigger)
        
        logger.debug(
            f"Trigger '{trigger.id}' execution result: "
            f"success={result.success}, behavior={result.behavior.value}"
        )
        
        return {
            "triggered": True,
            "should_forward": result.should_forward_gcode(),
            "fake_response": (
                result.get_fake_response()
                if not result.should_forward_gcode()
                else None
            ),
            "behavior": result.behavior,
        }
    
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
