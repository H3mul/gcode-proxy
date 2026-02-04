"""Trigger manager for converting GCode commands into tasks and handling state changes.

The trigger manager matches incoming GCode commands against configured triggers
and builds appropriate Task objects for the device to execute. It also handles
state-based triggers that execute in response to device state changes.
"""

import asyncio
from collections.abc import Sequence
import threading

from gcode_proxy.core.logging import get_logger
from .trigger import Trigger, StateTrigger
from .triggers_config import CustomTriggerConfig, GCodeTriggerConfig, StateTriggerConfig, TriggerBehavior
from gcode_proxy.core.task import GCodeTask, Task, ShellTask
from gcode_proxy.device.grbl_device_status import GrblDeviceStatus

logger = get_logger()


class TriggerManager:
    """
    Manages a list of GCode and state triggers and converts matches into tasks.

    When a GCode command is received, the trigger manager:
    1. Finds all triggers that match the command
    2. Builds a list of tasks to execute, including:
       - Optional synchronization task (G4 P0) if trigger requires it
       - ShellTask for the trigger command
    3. Returns the task list to be executed by the device

    When a device state change is detected, the trigger manager:
    1. Finds all state triggers that match the new state
    2. Executes matching triggers asynchronously with optional delays
    3. Maintains only one pending task per trigger ID (singular execution)
    4. Cancels pending triggers if state changes and no longer matches

    State Trigger Behavior:
    - Each trigger ID can have at most one pending execution
    - If a trigger is triggered while already pending, the new trigger replaces the old one
    - If state changes during the delay and no longer matches the trigger, execution is cancelled
    - This ensures consistent state during execution and prevents duplicate executions

    If no triggers match, returns None to indicate the server should
    create a simple GCodeTask for the command.

    This class is implemented as a thread-safe singleton to ensure a single
    instance is shared across the application.
    """

    _instance: "TriggerManager | None" = None
    _lock = threading.Lock()
    gcode_triggers: list[Trigger] = []
    state_triggers: list[StateTrigger] = []
    # Maps trigger ID to pending task for state triggers
    _pending_state_triggers: dict[str, asyncio.Task] = {}
    # Current device state for state-restricted gcode triggers
    _current_device_state: str | None = GrblDeviceStatus.DISCONNECTED

    def __new__(cls) -> "TriggerManager":
        """
        Create or return the singleton instance.

        Returns:
            The singleton TriggerManager instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    cls._instance = instance

        return cls._instance

    def __init__(self) -> None:
        """
        Initialize the TriggerManager singleton.

        This method is idempotent - it only initializes the trigger lists
        if they haven't been initialized yet. Subsequent calls do nothing.
        """
        # Triggers are initialized in __new__, so nothing to do here
        pass

    def load_from_config(
        self, trigger_configs: Sequence[CustomTriggerConfig]
    ) -> None:
        """
        Load triggers from CustomTriggerConfig instances.

        This method populates the singleton's trigger lists from the given
        configuration. Should be called once during application startup.

        Args:
            trigger_configs: Sequence of CustomTriggerConfig instances.

        Raises:
            ValueError: If any trigger configuration is invalid.
        """
        self.gcode_triggers.clear()
        self.state_triggers.clear()

        for config in trigger_configs:
            try:
                # Determine trigger type and load accordingly
                if isinstance(config.trigger, GCodeTriggerConfig):
                    # GCode trigger
                    trigger = Trigger(config)
                    self.gcode_triggers.append(trigger)
                    logger.info(
                        "Loaded GCode trigger '%s': /%s/ (sync: %s, behavior: %s)",
                        config.id, config.trigger.match, config.trigger.synchronize,
                        config.trigger.behavior
                    )
                elif isinstance(config.trigger, StateTriggerConfig):
                    # State trigger
                    trigger = StateTrigger(config)
                    self.state_triggers.append(trigger)
                    logger.info(
                        "Loaded state trigger '%s': /%s/ (delay: %.1fs)",
                        config.id, config.trigger.match, config.trigger.delay
                    )
                else:
                    raise ValueError(f"Unsupported trigger type: {type(config.trigger).__name__}")
            except ValueError as e:
                logger.error(f"Failed to load trigger: {e}")
                raise

    @classmethod
    def get_instance(cls) -> "TriggerManager":
        """
        Get the singleton instance without initializing triggers.

        Returns:
            The singleton TriggerManager instance.
        """
        if cls._instance is None:
            return cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance (useful for testing).

        This clears the singleton so a new instance can be created.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance.gcode_triggers.clear()
                cls._instance.state_triggers.clear()
                # Cancel any pending state triggers
                for task in cls._instance._pending_state_triggers.values():
                    if not task.done():
                        task.cancel()
                cls._instance._pending_state_triggers.clear()
                cls._instance._current_device_state = None
            cls._instance = None

    def find_matching_gcode_triggers(self, gcode: str) -> list[Trigger]:
        """
        Find all GCode triggers that match the given GCode and device state restrictions.

        Args:
            gcode: The raw GCode command string.

        Returns:
            List of matching Trigger instances (empty list if none match).
        """
        matching = [
            trigger for trigger in self.gcode_triggers
            if trigger.matches(gcode, self._current_device_state)
        ]
        return matching

    def find_matching_state_triggers(self, state: str) -> list[StateTrigger]:
        """
        Find all state triggers that match the given device state.

        Args:
            state: The device state string (e.g., 'Idle', 'Run', 'Hold').

        Returns:
            List of matching StateTrigger instances (empty list if none match).
        """
        matching = [trigger for trigger in self.state_triggers if trigger.matches(state)]
        return matching

    def build_tasks_for_gcode(
        self,
        gcode: str,
        client_uuid: str,
    ) -> list[Task] | None:
        """
        Build a list of tasks for the given GCode command.

        If any triggers match the command, returns a list of tasks including:
        - Optional GCodeTask with synchronization command (G4 P0) if synchronize=true
        - ShellTask for the trigger command

        Triggers may have an optional state restriction, which limits matching to
        specific device states (e.g., only trigger when device is in "Idle" state).

        If no triggers match, returns None. The server should then create
        a simple GCodeTask with the original command.

        Args:
            gcode: The GCode command string.
            client_uuid: The UUID of the client that sent the command.

        Returns:
            List of tasks to execute, or None if no triggers match.
        """
        matching_triggers = self.find_matching_gcode_triggers(gcode)

        if not matching_triggers:
            return None

        tasks: list[Task] = []

        # Process each matching trigger
        for trigger in matching_triggers:
            if trigger.behavior == TriggerBehavior.FORWARD:
                tasks.append(
                    GCodeTask(
                        client_uuid=client_uuid,
                        gcode=gcode,
                        should_respond=True
                    )
                )

            # Create a ShellTask for the trigger command
            tasks.append(
                ShellTask(
                    client_uuid=client_uuid,
                    id=trigger.id,
                    command=trigger.command,
                    should_respond=trigger.behavior != TriggerBehavior.FORWARD,
                    wait_for_idle=trigger.synchronize and
                        trigger.behavior != TriggerBehavior.FORWARD,
                )
            )

        return tasks

    def _cancel_pending_trigger(self, trigger_id: str) -> None:
        """
        Cancel a pending state trigger by ID.

        Args:
            trigger_id: The ID of the trigger to cancel.
        """
        if trigger_id in self._pending_state_triggers:
            task = self._pending_state_triggers[trigger_id]
            if not task.done():
                logger.debug(
                    "Cancelling pending state trigger '%s' due to state change",
                    trigger_id
                )
                task.cancel()
            del self._pending_state_triggers[trigger_id]

    def set_current_device_state(self, state: str) -> None:
        """
        Update the current device state.

        This is called by the device when state changes and is used to restrict
        GCode trigger matching to specific device states.

        Args:
            state: The new device state (e.g., 'Idle', 'Run', 'Hold').
        """
        self._current_device_state = state

    async def on_device_status(self, state: str) -> None:
        """
        Handle a device status change by executing matching state triggers.

        This method enforces two key behaviors:

        1. Consistency: If a state trigger with a delay is pending and the
           device state changes to something that doesn't match the trigger's
           pattern, the pending execution is cancelled.

        2. Singularity: Each trigger ID can have at most one pending execution.
           If a trigger is triggered while already pending, the new trigger
           replaces the old one.

        Args:
            state: The new device state (e.g., 'Idle', 'Run', 'Hold').
        """
        # Update current device state for state-restricted gcode triggers
        self.set_current_device_state(state)

        # First, handle consistency: cancel pending triggers that no longer match
        self._check_consistency_for_pending_triggers(state)

        # Find all triggers that match the new state
        matching_triggers = self.find_matching_state_triggers(state)

        if not matching_triggers:
            return

        # Process each matching trigger (singularity: one per trigger ID)
        for trigger in matching_triggers:
            # Cancel any existing pending execution for this trigger (singularity)
            self._cancel_pending_trigger(trigger.id)

            # Create a new background task for this trigger
            task = asyncio.create_task(
                self._execute_state_trigger(trigger, state)
            )

            # Track the pending task
            self._pending_state_triggers[trigger.id] = task

            # Clean up when task completes
            def make_cleanup_callback(trigger_id: str):
                def cleanup(t):
                    self._pending_state_triggers.pop(trigger_id, None)
                return cleanup

            task.add_done_callback(make_cleanup_callback(trigger.id))

    def _check_consistency_for_pending_triggers(self, state: str) -> None:
        """
        Check if any pending state triggers no longer match the current state.

        If a pending trigger's pattern doesn't match the new state, cancel it.
        This ensures that triggers only fire if the state remains consistent
        throughout the delay period.

        Args:
            state: The new device state.
        """
        # Find triggers that are no longer consistent with the new state
        triggers_to_cancel = []

        for trigger_id in list(self._pending_state_triggers.keys()):
            # Find the trigger definition
            trigger = None
            for t in self.state_triggers:
                if t.id == trigger_id:
                    trigger = t
                    break

            if trigger and not trigger.matches(state):
                # State changed and no longer matches this trigger
                triggers_to_cancel.append(trigger_id)

        # Cancel all inconsistent triggers
        for trigger_id in triggers_to_cancel:
            self._cancel_pending_trigger(trigger_id)

    async def _execute_state_trigger(self, trigger: StateTrigger, state: str) -> None:
        """
        Execute a state trigger with optional delay.

        Args:
            trigger: The StateTrigger to execute.
            state: The device state that triggered this execution.
        """
        try:
            # Wait for the delay period if specified
            if trigger.delay > 0:
                await asyncio.sleep(trigger.delay)

            logger.info(
                "Executing state trigger '%s' for state '%s'",
                trigger.id, state
            )

            # Execute the trigger command using ShellTask
            shell_task = ShellTask(
                id=trigger.id,
                command=trigger.command,
            )

            # Execute the shell task
            success, error_message = await shell_task.execute()
            if success:
                logger.debug(
                    "State trigger '%s' executed successfully",
                    trigger.id
                )
            else:
                logger.warning(
                    "State trigger '%s' execution failed: %s",
                    trigger.id, error_message
                )
        except asyncio.CancelledError:
            logger.debug("State trigger '%s' was cancelled", trigger.id)
        except Exception as e:
            logger.error(
                "Error executing state trigger '%s': %s",
                trigger.id, e
            )
