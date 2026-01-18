"""Configuration models for GCode triggers.

Defines extensible data models for parsing and validating trigger configurations
that allow matching GCode commands and executing external commands in response.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TriggerBehavior(Enum):
    """Behavior modes for trigger execution.
    
    - FORWARD: Execute trigger async, send gcode to device, return device response.
    - CAPTURE: Execute trigger sync, don't send gcode to device, return fake response.
    - CAPTURE_NOWAIT: Execute trigger async, don't send gcode to device, return
      immediately.
    """
    FORWARD = "forward"
    CAPTURE = "capture"
    CAPTURE_NOWAIT = "capture-nowait"
    
    @classmethod
    def from_string(cls, value: str) -> "TriggerBehavior":
        """Create a TriggerBehavior from a string, defaulting to CAPTURE.
        
        Args:
            value: String representation of the behavior.
            
        Returns:
            TriggerBehavior enum value.
        """
        value_lower = value.lower().strip() if value else ""
        for member in cls:
            if member.value == value_lower:
                return member
        # Default to CAPTURE if not recognized
        return cls.CAPTURE


@dataclass
class GCodeTriggerConfig:
    """Configuration for GCode-based triggers.
    
    This matches GCode commands using regex patterns.
    """
    
    type: str
    match: str
    behavior: TriggerBehavior = TriggerBehavior.CAPTURE
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GCodeTriggerConfig":
        """Create a GCodeTriggerConfig from a dictionary.
        
        Args:
            data: Dictionary containing 'type', 'match', and optional 'behavior' keys.
            
        Returns:
            GCodeTriggerConfig instance.
            
        Raises:
            ValueError: If required fields are missing or invalid.
        """
        if not isinstance(data, dict):
            raise ValueError("Trigger config must be a dictionary")
        
        trigger_type = data.get("type", "").strip()
        match_pattern = data.get("match", "").strip()
        behavior_str = data.get("behavior", "capture")
        
        if not trigger_type:
            raise ValueError("Trigger 'type' is required")
        if not match_pattern:
            raise ValueError("Trigger 'match' pattern is required")
        
        if trigger_type != "gcode":
            raise ValueError(f"Unsupported trigger type: {trigger_type}")
        
        behavior = TriggerBehavior.from_string(behavior_str)
        
        return cls(type=trigger_type, match=match_pattern, behavior=behavior)


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
