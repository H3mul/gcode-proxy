"""Configuration models for GCode triggers.

Defines extensible data models for parsing and validating trigger configurations
that allow matching GCode commands and executing external commands in response.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class GCodeTriggerConfig:
    """Configuration for GCode-based triggers.
    
    This matches GCode commands using regex patterns.
    """
    
    type: str
    match: str
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GCodeTriggerConfig":
        """Create a GCodeTriggerConfig from a dictionary.
        
        Args:
            data: Dictionary containing 'type' and 'match' keys.
            
        Returns:
            GCodeTriggerConfig instance.
            
        Raises:
            ValueError: If required fields are missing or invalid.
        """
        if not isinstance(data, dict):
            raise ValueError("Trigger config must be a dictionary")
        
        trigger_type = data.get("type", "").strip()
        match_pattern = data.get("match", "").strip()
        
        if not trigger_type:
            raise ValueError("Trigger 'type' is required")
        if not match_pattern:
            raise ValueError("Trigger 'match' pattern is required")
        
        if trigger_type != "gcode":
            raise ValueError(f"Unsupported trigger type: {trigger_type}")
        
        return cls(type=trigger_type, match=match_pattern)


@dataclass
class CustomTriggerConfig:
    """Configuration for a custom trigger.
    
    Represents a single trigger that matches GCode and executes a command.
    """
    
    id: str
    trigger: GCodeTriggerConfig
    command: str
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CustomTriggerConfig":
        """Create a CustomTriggerConfig from a dictionary.
        
        Args:
            data: Dictionary containing 'id', 'trigger', and 'command' keys.
            
        Returns:
            CustomTriggerConfig instance.
            
        Raises:
            ValueError: If required fields are missing or invalid.
        """
        if not isinstance(data, dict):
            raise ValueError("Custom trigger must be a dictionary")
        
        trigger_id = data.get("id", "").strip()
        if not trigger_id:
            raise ValueError("Trigger 'id' is required")
        
        trigger_data = data.get("trigger")
        if not trigger_data:
            raise ValueError(f"Trigger '{trigger_id}' missing 'trigger' configuration")
        
        command = data.get("command", "").strip()
        if not command:
            raise ValueError(f"Trigger '{trigger_id}' missing 'command'")
        
        try:
            trigger_config = GCodeTriggerConfig.from_dict(trigger_data)
        except ValueError as e:
            raise ValueError(f"Trigger '{trigger_id}' has invalid configuration: {e}") from e
        
        return cls(
            id=trigger_id,
            trigger=trigger_config,
            command=command,
        )
