"""Trigger manager for executing GCode-triggered external commands.

The TriggerManager implements the GCodeHandler interface and manages a list
of triggers that match incoming GCode commands and execute triggers
in response. Different trigger behaviors control how commands are forwarded
and whether to wait for trigger completion.

Multiple triggers can match a single GCode command. Execution behavior:
- CAPTURE triggers execute synchronously (we wait for them)
- FORWARD/CAPTURE_NOWAIT triggers execute asynchronously
- If ANY trigger is FORWARD, GCode is sent to device
- If ALL triggers are CAPTURE, GCode is not sent to device
- Responses are merged: device response if forwarded, else aggregated trigger results
"""

import asyncio
import logging
from collections.abc import Sequence

from .handlers import GCodeHandler
from .trigger import Trigger
from .triggers_config import CustomTriggerConfig, TriggerBehavior


logger = logging.getLogger(__name__)


class TriggerExecutionResult:
    """Result of a single trigger execution with behavior-specific handling."""

    def __init__(
        self,
        trigger_id: str,
        behavior: TriggerBehavior,
        success: bool,
        error_msg: str | None = None,
    ):
        """
        Initialize trigger execution result.

        Args:
            trigger_id: The ID of the trigger.
            behavior: The trigger behavior mode.
            success: Whether the trigger executed successfully.
            error_msg: Error message if trigger failed.
        """
        self.trigger_id = trigger_id
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


class MultiTriggerExecutionResult:
    """Aggregated result of multiple trigger executions."""

    def __init__(self, results: list[TriggerExecutionResult]):
        """
        Initialize aggregated result from multiple trigger executions.

        Args:
            results: List of individual TriggerExecutionResult instances.
        """
        self.results = results
        self._compute_aggregated_behavior()

    def _compute_aggregated_behavior(self) -> None:
        """Compute aggregated behavior from all trigger results."""
        # Check if ANY trigger has FORWARD behavior
        has_forward = any(r.behavior == TriggerBehavior.FORWARD for r in self.results)

        # Determine if we should forward
        self.should_forward = has_forward

        # Check if all triggers succeeded
        self.all_succeeded = all(r.success for r in self.results)

        # Collect error messages from failed triggers
        self.error_messages = [
            f"{r.trigger_id}: {r.error_msg}"
            for r in self.results
            if not r.success and r.error_msg
        ]

    def get_response(self, device_response: str | None = None) -> str:
        """
        Get the response to return to the client.

        Args:
            device_response: The response from the device (if forwarded).
                           If None, uses aggregated trigger results.

        Returns:
            The response string to send to the client.
        """
        # If we forwarded the GCode to device, return device response
        if self.should_forward and device_response is not None:
            return device_response

        # All triggers were in CAPTURE mode, return aggregated result
        if self.all_succeeded:
            return "ok"
        else:
            # Merge error messages
            if self.error_messages:
                merged_errors = "; ".join(self.error_messages)
                return f"error: {merged_errors}"
            else:
                return "error: trigger execution failed"


class TriggerManager(GCodeHandler):
    """
    Manages a list of GCode triggers and executes them when GCode matches.

    This class implements the GCodeHandler interface, allowing it to be passed
    to GCodeSerialDevice to intercept GCode commands and execute triggers
    when patterns match.

    Supports multiple triggers matching the same GCode command with
    sophisticated aggregation logic:
    - CAPTURE triggers execute synchronously (we wait for them)
    - FORWARD/CAPTURE_NOWAIT triggers execute asynchronously
    - If ANY trigger is FORWARD, GCode is sent to device
    - If ALL triggers are CAPTURE, GCode is not sent to device
    - Responses are merged based on execution results
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

    def find_matching_triggers(self, gcode: str) -> list[Trigger]:
        """
        Find all triggers that match the given GCode.

        Args:
            gcode: The raw GCode command string.

        Returns:
            List of matching Trigger instances (empty list if none match).
        """
        matching = [trigger for trigger in self.triggers if trigger.matches(gcode)]
        return matching

    async def execute_trigger_with_behavior(
        self, trigger: Trigger
    ) -> TriggerExecutionResult:
        """
        Execute a trigger and return result based on its behavior.

        For CAPTURE triggers, this will block until the trigger completes.
        For CAPTURE_NOWAIT, it spawns a background task and returns immediately.
        For FORWARD, it executes and waits for completion.

        Args:
            trigger: The trigger to execute.

        Returns:
            TriggerExecutionResult containing execution status and behavior info.
        """
        if trigger.behavior in [
            TriggerBehavior.FORWARD, # We will wait on the device response instead
            TriggerBehavior.CAPTURE_NOWAIT
        ]:
            # Spawn background task and return immediately
            task = asyncio.create_task(trigger.execute())
            self._pending_tasks.add(task)

            def _task_done_callback(t):
                self._pending_tasks.discard(t)

            task.add_done_callback(_task_done_callback)
            # Return success immediately without waiting
            return TriggerExecutionResult(
                trigger_id=trigger.id,
                behavior=trigger.behavior,
                success=True,
                error_msg=None,
            )
        elif trigger.behavior in [TriggerBehavior.CAPTURE]:
            # For CAPTURE, wait for execution to complete
            success, error_msg = await trigger.execute()
            return TriggerExecutionResult(
                trigger_id=trigger.id,
                behavior=trigger.behavior,
                success=success,
                error_msg=error_msg,
            )

    async def execute_all_matching_triggers(
        self, matching_triggers: list[Trigger]
    ) -> MultiTriggerExecutionResult:
        """
        Execute all matching triggers and return aggregated results.

        Execution strategy:
        - CAPTURE triggers: Execute sequentially and wait for each
        - CAPTURE_NOWAIT triggers: Spawn async, don't wait
        - FORWARD triggers: Execute synchronously and wait

        Args:
            matching_triggers: List of triggers to execute.

        Returns:
            MultiTriggerExecutionResult with aggregated execution data.
        """
        results: list[TriggerExecutionResult] = []

        tasks = [
            asyncio.create_task(self.execute_trigger_with_behavior(trigger))
            for trigger in matching_triggers
        ]
        
        results = await asyncio.gather(*tasks)

        return MultiTriggerExecutionResult(results)

    async def on_gcode(
        self, gcode: str, client_address: tuple[str, int]
    ) -> dict[str, object] | None:
        """
        Called when a GCode command is received from a TCP client.

        Checks all registered triggers and handles execution based on behavior.
        Returns a dictionary with execution metadata that the device can use
        to determine how to process the GCode.

        Supports multiple matching triggers with aggregated behavior:
        - If ANY trigger is FORWARD, GCode is sent to device
        - If ALL triggers are CAPTURE, GCode is not sent to device
        - Responses are merged based on execution results

        Args:
            gcode: The raw GCode command string received.
            client_address: Tuple of (host, port) identifying the client.

        Returns:
            Dictionary with keys:
            - 'triggered': bool - Whether any trigger matched
            - 'should_forward': bool - Whether to send GCode to device
            - 'fake_response': str | None - Response to return for CAPTURE modes
            - 'all_results': MultiTriggerExecutionResult | None - Aggregated results
        """
        # Find all matching triggers
        matching_triggers = self.find_matching_triggers(gcode)

        if not matching_triggers:
            # No triggers matched, pass through normally
            return {
                "triggered": False,
                "should_forward": True,
                "fake_response": None,
                "all_results": None,
            }

        logger.debug(
            f"Found {len(matching_triggers)} matching trigger(s) for GCode: "
            f"{gcode.strip()}"
        )

        # Execute all matching triggers
        aggregated_result = await self.execute_all_matching_triggers(
            matching_triggers
        )

        # Log execution results
        for result in aggregated_result.results:
            logger.debug(
                f"Trigger '{result.trigger_id}' execution result: "
                f"success={result.success}, behavior={result.behavior.value}"
            )

        # Determine response based on aggregated behavior
        fake_response = None
        if not aggregated_result.should_forward:
            # All triggers are CAPTURE mode, use aggregated fake response
            fake_response = aggregated_result.get_response(device_response=None)

        return {
            "triggered": True,
            "should_forward": aggregated_result.should_forward,
            "fake_response": fake_response,
            "all_results": aggregated_result,
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
