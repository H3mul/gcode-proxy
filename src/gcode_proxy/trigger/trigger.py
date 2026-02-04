"""Trigger implementation for matching and executing GCode commands and device state changes.

Triggers match incoming GCode commands using regex patterns or match device state changes
and execute external commands in response.
"""

import re
from re import Pattern

from gcode_proxy.core.logging import get_logger
from .triggers_config import CustomTriggerConfig, GCodeTriggerConfig, StateTriggerConfig


logger = get_logger()


class Trigger:
    """
    A trigger that matches GCode and executes external commands.

    Triggers use regex patterns to match GCode commands and execute
    external commands (scripts, programs, etc.) when a match is found.
    Optionally restricts matching to specific device states.
    """

    def __init__(self, config: CustomTriggerConfig):
        """
        Initialize a trigger from configuration.

        Args:
            config: CustomTriggerConfig instance defining the trigger.
                   The trigger config must be a GCodeTriggerConfig.

        Raises:
            ValueError: If the regex pattern is invalid or config is wrong type.
        """
        if not isinstance(config.trigger, GCodeTriggerConfig):
            raise ValueError(
                f"Trigger '{config.id}' must have a GCodeTriggerConfig, "
                f"got {type(config.trigger).__name__}"
            )

        self.config = config
        self.id = config.id
        self.command = config.command
        self.behavior = config.trigger.behavior
        self.synchronize = config.trigger.synchronize
        self.state_restriction = config.trigger.state  # Optional state restriction

        # Compile the regex pattern for matching GCode
        try:
            self.pattern: Pattern[str] = re.compile(config.trigger.match)
        except re.error as e:
            raise ValueError(
                f"Trigger '{config.id}' has invalid regex pattern "
                f"'{config.trigger.match}': {e}"
            ) from e

    def matches(self, gcode: str, current_state: str | None = None) -> bool:
        """
        Check if the given GCode matches this trigger's pattern and state restriction.

        Args:
            gcode: The GCode command to test.
            current_state: The current device state (required if trigger has state restriction).

        Returns:
            True if the GCode matches the trigger pattern and state restriction (if any).
        """
        # Check state restriction if configured
        if self.state_restriction is not None:
            if current_state is None or current_state.strip() != self.state_restriction:
                return False

        # Strip whitespace and newlines for comparison
        gcode_stripped = gcode.strip()
        return bool(self.pattern.search(gcode_stripped))


class StateTrigger:
    """
    A trigger that matches device state changes and executes external commands.

    State triggers use regex patterns to match device state (e.g., Idle, Run, Hold)
    and execute external commands when a state change is detected that matches
    the trigger pattern. An optional delay can be applied before execution.
    """

    def __init__(self, config: CustomTriggerConfig):
        """
        Initialize a state trigger from configuration.

        Args:
            config: CustomTriggerConfig instance defining the state trigger.
                   The trigger config must be a StateTriggerConfig.

        Raises:
            ValueError: If the regex pattern is invalid or config is wrong type.
        """
        if not isinstance(config.trigger, StateTriggerConfig):
            raise ValueError(
                f"State trigger '{config.id}' must have a StateTriggerConfig, "
                f"got {type(config.trigger).__name__}"
            )

        self.config = config
        self.id = config.id
        self.command = config.command
        self.delay = config.trigger.delay  # delay in seconds

        # Compile the regex pattern for matching device state
        try:
            self.pattern: Pattern[str] = re.compile(config.trigger.match)
        except re.error as e:
            raise ValueError(
                f"State trigger '{config.id}' has invalid regex pattern "
                f"'{config.trigger.match}': {e}"
            ) from e

    def matches(self, state: str) -> bool:
        """
        Check if the given device state matches this trigger's pattern.

        Args:
            state: The device state to test (e.g., 'Idle', 'Run', 'Hold').

        Returns:
            True if the state matches the trigger pattern, False otherwise.
        """
        # Strip whitespace for comparison
        state_stripped = state.strip()
        return bool(self.pattern.search(state_stripped))
