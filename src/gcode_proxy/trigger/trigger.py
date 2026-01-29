"""Trigger implementation for matching and executing GCode commands.

Triggers match incoming GCode commands using regex patterns and execute
external commands in response.
"""

import re
from re import Pattern

from gcode_proxy.core.logging import get_logger
from .triggers_config import CustomTriggerConfig


logger = get_logger()


class Trigger:
    """
    A trigger that matches GCode and executes external commands.

    Triggers use regex patterns to match GCode commands and execute
    external commands (scripts, programs, etc.) when a match is found.
    """

    def __init__(self, config: CustomTriggerConfig):
        """
        Initialize a trigger from configuration.

        Args:
            config: CustomTriggerConfig instance defining the trigger.

        Raises:
            ValueError: If the regex pattern is invalid.
        """
        self.config = config
        self.id = config.id
        self.command = config.command
        self.synchronize = config.trigger.synchronize

        # Compile the regex pattern for matching GCode
        try:
            self.pattern: Pattern[str] = re.compile(config.trigger.match)
        except re.error as e:
            raise ValueError(
                f"Trigger '{config.id}' has invalid regex pattern "
                f"'{config.trigger.match}': {e}"
            ) from e

    def matches(self, gcode: str) -> bool:
        """
        Check if the given GCode matches this trigger's pattern.

        Args:
            gcode: The GCode command to test.

        Returns:
            True if the GCode matches the trigger pattern, False otherwise.
        """
        # Strip whitespace and newlines for comparison
        gcode_stripped = gcode.strip()
        return bool(self.pattern.search(gcode_stripped))
