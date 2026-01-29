"""Trigger manager for converting GCode commands into tasks.

The trigger manager matches incoming GCode commands against configured triggers
and builds appropriate Task objects for the device to execute.
"""

from collections.abc import Sequence

from gcode_proxy.core.logging import get_logger
from .trigger import Trigger
from .triggers_config import CustomTriggerConfig
from gcode_proxy.core.task import Task, GCodeTask, ShellTask

logger = get_logger()


class TriggerManager:
    """
    Manages a list of GCode triggers and converts matches into tasks.

    When a GCode command is received, the trigger manager:
    1. Finds all triggers that match the command
    2. Builds a list of tasks to execute, including:
       - Optional synchronization task (G4 P0) if trigger requires it
       - ShellTask for the trigger command
    3. Returns the task list to be executed by the device

    If no triggers match, returns None to indicate the server should
    create a simple GCodeTask for the command.
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

        if trigger_configs:
            for config in trigger_configs:
                try:
                    trigger = Trigger(config)
                    self.triggers.append(trigger)
                    logger.info(
                        f"Loaded trigger '{config.id}': {config.trigger.match} "
                        f"-> {config.command}"
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

        If no triggers match, returns None. The server should then create
        a simple GCodeTask with the original command.

        Args:
            gcode: The GCode command string.
            client_uuid: The UUID of the client that sent the command.

        Returns:
            List of tasks to execute, or None if no triggers match.
        """
        matching_triggers = self.find_matching_triggers(gcode)

        if not matching_triggers:
            return None

        tasks: list[Task] = []

        # Process each matching trigger
        for trigger in matching_triggers:
            # If trigger requires synchronization, prepend a G4 P0 command
            if trigger.synchronize:
                sync_task = GCodeTask(
                    client_uuid=None,  # Internal sync command, don't respond to client
                    gcode="G4 P0\n",
                    immediate=False,
                    should_respond=False,
                )
                tasks.append(sync_task)

            # Create a ShellTask for the trigger command
            shell_task = ShellTask(
                client_uuid=client_uuid,
                id=trigger.id,
                command=trigger.command,
                immediate=False,
                should_respond=True,
            )
            tasks.append(shell_task)

        return tasks
