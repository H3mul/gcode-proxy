"""Trigger implementation for matching and executing GCode commands.

Triggers match incoming GCode commands using regex patterns and execute
external commands in response.
"""

import asyncio
import logging
import re
from re import Pattern

from .triggers_config import CustomTriggerConfig


logger = logging.getLogger(__name__)


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
        self.behavior = config.trigger.behavior
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
    
    async def execute(self) -> tuple[bool, str | None]:
        """
        Execute the trigger's command asynchronously.
        
        The command is executed as a subprocess without blocking.
        
        Returns:
            Tuple of (success: bool, error_message: str | None).
            If successful, error_message is None.
            If failed, error_message contains the stderr output.
        """
        try:
            logger.info(f"Executing trigger '{self.id}': {self.command}")
            
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
                    f"Trigger '{self.id}' executed successfully "
                    f"(exit code: {process.returncode})"
                )
                return True, None
            else:
                stderr_str = stderr.decode('utf-8', errors='replace').strip()
                logger.error(
                    f"Trigger '{self.id}' failed with exit code {process.returncode}: "
                    f"{stderr_str}"
                )
                return False, stderr_str
                
        except Exception as e:
            logger.error(f"Trigger '{self.id}' execution error: {e}")
            return False, str(e)
