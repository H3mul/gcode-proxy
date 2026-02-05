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
    Optionally restricts trigger to specific device states.
    """

    type: str
    match: str
    synchronize: bool = True
    state: str | None = None  # Optional device state restriction
    behavior: TriggerBehavior = TriggerBehavior.CAPTURE

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GCodeTriggerConfig":
        """Create a GCodeTriggerConfig from a dictionary.

        Args:
            data: Dictionary containing 'type', 'match', 'behavior', 'synchronize', and optional
            'state' keys.

        Returns:
            GCodeTriggerConfig instance.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        if not isinstance(data, dict):
            raise ValueError("Trigger config must be a dictionary")

        trigger_type = data.get("type", "").strip()
        match_pattern = data.get("match", "").strip()
        synchronize = data.get("synchronize", True)
        behavior = data.get("behavior", TriggerBehavior.CAPTURE)
        state_restriction = data.get("state")
        if state_restriction:
            state_restriction = state_restriction.strip()

        if not trigger_type:
            raise ValueError("Trigger 'type' is required")
        if not match_pattern:
            raise ValueError("Trigger 'match' pattern is required")

        if trigger_type != "gcode":
            raise ValueError(f"Unsupported trigger type: {trigger_type}")

        return cls(
            type=trigger_type,
            match=match_pattern,
            synchronize=bool(synchronize),
            behavior=TriggerBehavior.from_string(str(behavior)),
            state=state_restriction,
        )


@dataclass
class StateTriggerConfig:
    """Configuration for state-based triggers.

    This matches device state changes (e.g., Idle, Run, Hold, etc.).
    """

    type: str
    match: str
    delay: float = 0  # seconds

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateTriggerConfig":
        """Create a StateTriggerConfig from a dictionary.

        Args:
            data: Dictionary containing 'type', 'match', and optional 'delay' keys.

        Returns:
            StateTriggerConfig instance.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        if not isinstance(data, dict):
            raise ValueError("Trigger config must be a dictionary")

        trigger_type = data.get("type", "").strip()
        match_pattern = data.get("match", "").strip()
        delay = data.get("delay", 0)

        if not trigger_type:
            raise ValueError("Trigger 'type' is required")
        if not match_pattern:
            raise ValueError("Trigger 'match' pattern is required")

        if trigger_type != "state":
            raise ValueError(f"Unsupported trigger type: {trigger_type}")

        # Convert delay to float and validate
        try:
            delay_seconds = float(delay)
            if delay_seconds < 0:
                raise ValueError("Delay must be non-negative")
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid delay value: {e}") from e

        return cls(
            type=trigger_type,
            match=match_pattern,
            delay=delay_seconds,
        )


@dataclass
class CustomTriggerConfig:
    """Configuration for a custom trigger.

    Represents a single trigger that matches GCode or device state and executes a command.
    """

    id: str
    trigger: GCodeTriggerConfig | StateTriggerConfig
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
            # Determine trigger type and parse accordingly
            trigger_type = trigger_data.get("type", "").strip()

            if trigger_type == "gcode":
                trigger_config = GCodeTriggerConfig.from_dict(trigger_data)
            elif trigger_type == "state":
                trigger_config = StateTriggerConfig.from_dict(trigger_data)
            else:
                raise ValueError(f"Unsupported trigger type: {trigger_type}")
        except ValueError as e:
            raise ValueError(f"Trigger '{trigger_id}' has invalid configuration: {e}") from e

        return cls(
            id=trigger_id,
            trigger=trigger_config,
            command=command,
        )
